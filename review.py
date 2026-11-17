"""Self-review: Claude looks at every picture and clip the way a viewer would, and says what is wrong.

Three checks, each at the cheapest point to catch what it catches:

    pictures   each keyframe, before its clip is made, next to the character sheets and the
               earlier shot of its scene: missing or extra people, a face that is not the
               character, people or a car on the wrong side, broken hands, text nobody asked for
    clips      each clip as a strip of frames, next to its keyframe: people fading or vanishing,
               melting faces, a jump to another angle, a parked car rolling away, an action that
               happens outside the part of the clip the cut uses (with a better start)
    final      the finished video: black or frozen stretches, dead air, shots that sit too long,
               and one look at a strip of the cut for captions over faces or cut off. When
               Claude Eyes (github.com/moritzkremb/claude-eyes) is installed it also measures the
               cut's pacing, speech speed and loudness; without it the rest works the same.

The verdicts go in the run's qa_report.json. Each one is tied to the file it judged (its time
stamp), so a picture or clip made again is checked again and an old verdict never sticks to a
new file. A problem worth a new take is "redo"; the rest are "minor" notes. Auto-fix draws a
flagged picture or makes a flagged clip again with the reviewer's fix in its prompt, at most
`max_fixes` times per shot, and checks it again.

The review never stops a video: when it fails (no key, the API is down) it says so and the
video carries on. Each check is one Claude request with small pictures, about 1 to 3 cents.

    settings(config)                 the review block of the config, with its defaults
    on(config, run_dir) / auto_fix   whether this video is checked / fixed as it is made
    set_for_run(run_dir, on, fix)    a video's own choice (run.json "review")
    check_pictures / check_clips / check_final
    after_step(step, run_dir, config)   what the pipeline calls after images, video, assemble
    fix(run_dir, config, shots, what)   make flagged shots again with the reviewer's fixes
    for_status(run_dir)              the current verdicts, for the run page
"""

from __future__ import annotations

import base64
import io
import json
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from common import StepError, read_json, write_json

REPORT = "qa_report.json"
TIMELINE = "build/timeline.json"            # written by the assemble step: where each shot sits

DEFAULTS = {
    "enabled": False,          # check every new video as it is made
    "auto_fix": False,         # and make what it flags again (costs a picture or a clip each time)
    "max_fixes": 2,            # new takes per shot at most
    "pictures": True,
    "clips": True,
    "final": True,
    "final_look": True,        # one Claude look at a strip of the finished cut (captions, framing)
    "model": "claude-sonnet-5-5",
    "effort": "medium",        # low | medium | high; how hard it thinks before it answers
    "max_tokens": 16000,       # thinking counts toward this; you pay only for what is used
    "price_in": 2.0,           # USD per million tokens, for the cost line (Sonnet 5.5)
    "price_out": 10.0,
    "frames": 8,               # frames of a clip the reviewer sees
    "workers": 4,              # checks at once
    "slow_shot_seconds": 5.0,  # a shot on screen longer than this is noted as slow
    "eyes": "auto",            # auto = use Claude Eyes when the `eyes` command is installed | off
    "eyes_command": "eyes",
}

_lock = threading.Lock()


# --------------------------------------------------------------- settings ----

def settings(config: dict) -> dict:
    block = config.get("review") if isinstance(config.get("review"), dict) else {}
    s = {**DEFAULTS, **{k: v for k, v in block.items() if v is not None}}
    s["max_fixes"] = max(0, min(5, int(s["max_fixes"])))
    s["frames"] = max(4, min(12, int(s["frames"])))
    s["workers"] = max(1, min(8, int(s["workers"])))
    return s


def run_choice(run_dir: Path | None) -> dict:
    if run_dir is None:
        return {}
    try:
        value = read_json(Path(run_dir) / "run.json").get("review")
    except (OSError, ValueError, AttributeError):
        return {}
    return value if isinstance(value, dict) else {}


def set_for_run(run_dir: Path, on: bool | None = None, auto_fix: bool | None = None) -> dict:
    """Save this video's choice (None leaves that part as it is)."""
    path = Path(run_dir) / "run.json"
    meta = read_json(path)
    choice = dict(meta.get("review") or {}) if isinstance(meta.get("review"), dict) else {}
    if on is not None:
        choice["on"] = bool(on)
    if auto_fix is not None:
        choice["auto_fix"] = bool(auto_fix)
    meta["review"] = choice
    write_json(path, meta)
    return choice


def on(config: dict, run_dir: Path | None = None) -> bool:
    choice = run_choice(run_dir).get("on")
    return bool(settings(config)["enabled"] if choice is None else choice)


def auto_fix(config: dict, run_dir: Path | None = None) -> bool:
    choice = run_choice(run_dir).get("auto_fix")
    return bool(settings(config)["auto_fix"] if choice is None else choice)


# ----------------------------------------------------------------- report ----

def report_path(run_dir: Path) -> Path:
    return Path(run_dir) / REPORT


def load(run_dir: Path) -> dict:
    try:
        data = read_json(report_path(run_dir))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("pictures", {})
    data.setdefault("clips", {})
    data.setdefault("final", None)
    data.setdefault("cost", 0.0)
    return data


def _update(run_dir: Path, fn) -> dict:
    """Read, change and write the report under one lock (checks run side by side)."""
    with _lock:
        data = load(run_dir)
        fn(data)
        data["updated"] = _now()
        write_json(report_path(run_dir), data)
        return data


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mtime(path: Path) -> float | None:
    try:
        return round(path.stat().st_mtime, 3)
    except OSError:
        return None


def current(entry: dict | None, path: Path) -> bool:
    """The verdict is about the file that is there now."""
    return bool(entry) and entry.get("mtime") is not None and entry.get("mtime") == _mtime(path)


def for_status(run_dir: Path, config: dict | None = None) -> dict:
    """{"shots": {n: {"picture": entry, "clip": entry}}, "final": entry, "cost": usd}, current
    verdicts only (a verdict about a picture that has since been drawn again is left out)."""
    from steps.images import shot_path
    from steps.video import video_path
    data = load(run_dir)
    shots: dict[int, dict] = {}
    for key, path_of in (("pictures", shot_path), ("clips", video_path)):
        for n_str, entry in data[key].items():
            try:
                n = int(n_str)
            except ValueError:
                continue
            if current(entry, path_of(run_dir, n)):
                shots.setdefault(n, {})["picture" if key == "pictures" else "clip"] = entry
    final = data.get("final")
    if not (isinstance(final, dict) and current(final, Path(run_dir) / "final.mp4")):
        final = None
    out = {"shots": shots, "final": final, "cost": round(float(data.get("cost") or 0), 4)}
    if config is not None:
        out.update({"on": on(config, run_dir), "auto_fix": auto_fix(config, run_dir),
                    "eyes": bool(eyes_command(config)), "max_fixes": settings(config)["max_fixes"]})
    return out


def flagged(run_dir: Path, what: str, only: set[int] | None = None) -> list[int]:
    """Shots whose current picture ("pictures") or clip ("clips") was judged worth a new take
    and not set aside."""
    from steps.images import shot_path
    from steps.video import video_path
    path_of = shot_path if what == "pictures" else video_path
    out = []
    for n_str, entry in load(run_dir)[what].items():
        if not n_str.isdigit() or (only is not None and int(n_str) not in only):
            continue
        n = int(n_str)
        if entry.get("verdict") == "redo" and not entry.get("ignored") and current(entry, path_of(run_dir, n)):
            out.append(n)
    return sorted(out)


def set_ignored(run_dir: Path, n: int, what: str, ignored: bool) -> bool:
    key = "pictures" if what == "picture" else "clips"
    found = {"ok": False}

    def change(data):
        entry = data[key].get(str(n))
        if entry:
            entry["ignored"] = bool(ignored)
            found["ok"] = True
    _update(run_dir, change)
    return found["ok"]


# ---------------------------------------------------------------- pictures ----

def _jpeg(img, max_side: int) -> dict:
    """An image block for the Messages API: the picture scaled down to `max_side` as JPEG."""
    from PIL import Image
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(buf.getvalue()).decode("ascii")}}


def image_block(path: Path, max_side: int = 1024) -> dict:
    from PIL import Image
    with Image.open(path) as img:
        return _jpeg(img, max_side)


def _font(size: int):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                       # an older Pillow
        return ImageFont.load_default()


def frame_times(duration: float, count: int) -> list[float]:
    """`count` moments spread over a clip, the first just after it starts, the last just before
    it ends (the very last frame of a file is often missing)."""
    if duration <= 0:
        return [0.0]
    step = duration / count
    return [round(min(duration - 0.05, step * (i + 0.5)), 2) for i in range(count)]


def contact_sheet(clip: Path, times: list[float], dest: Path, window: tuple[float, float] | None = None,
                  cols: int = 4, tile: tuple[int, int] = (216, 384)) -> Path:
    """The clip's frames at `times` in a grid, each with its time. Frames inside `window` (the
    part of the clip the cut uses) get a green bar under them, the others a grey one."""
    from PIL import Image, ImageDraw
    import media
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.stem}_frames"
    tmp.mkdir(exist_ok=True)
    tiles = []
    try:
        for i, t in enumerate(times):
            f = tmp / f"{i}.jpg"
            media.run_ffmpeg(["-ss", f"{t:.2f}", "-i", str(clip), "-frames:v", "1", "-q:v", "3", str(f)],
                             f"frame {t:.2f}s of {clip.name}")
            if f.is_file():
                with Image.open(f) as im:
                    tiles.append((t, im.convert("RGB").resize(tile)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not tiles:
        raise StepError(f"no frames could be read from {clip.name}")
    rows = (len(tiles) + cols - 1) // cols
    bar, gap = 22, 6
    sheet = Image.new("RGB", (cols * tile[0] + (cols - 1) * gap, rows * (tile[1] + bar) + (rows - 1) * gap), "white")
    draw = ImageDraw.Draw(sheet)
    font = _font(16)
    for i, (t, im) in enumerate(tiles):
        x = (i % cols) * (tile[0] + gap)
        y = (i // cols) * (tile[1] + bar + gap)
        sheet.paste(im, (x, y))
        used = window is None or window[0] - 0.01 <= t <= window[1] + 0.01
        draw.rectangle([x, y + tile[1], x + tile[0], y + tile[1] + bar], fill=(46, 160, 67) if used else (150, 150, 150))
        draw.text((x + 6, y + tile[1] + 3), f"{i + 1}  {t:.1f}s" + ("" if used else "  not used"), fill="white", font=font)
    sheet.save(dest, "JPEG", quality=85)
    return dest


# ------------------------------------------------------------------ Claude ----

def ask(config: dict, system: str, content: list, label: str) -> tuple[dict, float]:
    """One request to Claude; returns (the JSON it answered, the cost in USD)."""
    from steps.script import call_model, create_client
    s = settings(config)
    effort = str(s.get("effort") or "").strip() or None
    response = call_model(create_client(), s["model"], int(s["max_tokens"]), system,
                          [{"role": "user", "content": content}], effort=effort)
    text = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text")
    usage = getattr(response, "usage", None)
    cost = 0.0
    if usage is not None:
        cost = (float(getattr(usage, "input_tokens", 0) or 0) * float(s["price_in"])
                + float(getattr(usage, "output_tokens", 0) or 0) * float(s["price_out"])) / 1e6
    return parse_answer(text, label), cost


def parse_answer(text: str, label: str) -> dict:
    """The JSON object in the reply (the model is told to write only that; this also takes it
    from inside a code fence or after a stray sentence)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise StepError(f"{label}: the review did not come back as JSON")
    try:
        data = json.loads(m.group(0))
    except ValueError as e:
        raise StepError(f"{label}: the review's JSON did not read ({e})") from e
    if not isinstance(data, dict):
        raise StepError(f"{label}: the review is not a JSON object")
    return data


SEVERITIES = ("redo", "minor")


def clean_problems(data: dict, keep_at: bool = False) -> list[dict]:
    out = []
    for p in data.get("problems") or []:
        if not isinstance(p, dict):
            continue
        what = " ".join(str(p.get("what") or "").split())[:400]
        if not what:
            continue
        sev = str(p.get("severity") or "minor").strip().lower()
        item = {"severity": sev if sev in SEVERITIES else "minor", "what": what,
                "fix": " ".join(str(p.get("fix") or "").split())[:400]}
        for key in ("start", "at") if keep_at else ("start",):
            v = p.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
                item[key] = round(float(v), 2)
        out.append(item)
    return out[:5]


BRIEF = (
    "You check one shot of a short vertical video (9:16, watched once on a phone) before it goes into the cut. "
    "You have seen none of the work behind it: you stand in for a stranger. Report only what you can see in "
    "the pictures, each problem tied to something specific in them. A kind verdict is useless, and so is a "
    "harsh one that names nothing visible. Never invent a problem to have something to say.\n\n"
    "What cannot change, so never ask for it: the drawing style of the video, the story and what the script "
    "asks for. Judge the shot against its own description.\n\n")

PICTURE_RULES = (
    "Severity \"redo\" is for a problem a viewer would notice that a new picture fixes:\n"
    "- someone the description names is missing, someone is there who should not be, or the number of people is wrong\n"
    "- a person does not look like their character sheet: another face, hair, skin tone, build or age, "
    "or they wear someone else's clothes (ignore the sheet's plain grey clothes and background: those are placeholders)\n"
    "- it contradicts the earlier shot of the same scene: people or things on the other side, a car facing the "
    "other way or moved, the place or the time of day changed, different clothes\n"
    "- what the description says is not shown or is shown wrong: sitting vs standing, inside vs outside a car, "
    "who is where, who holds what, which way someone looks\n"
    "- broken anatomy: extra or fused fingers or limbs, a melted or doubled face, eyes looking two ways\n"
    "- writing, letters, a logo or a watermark nobody asked for; borders, or a picture that is not tall\n"
    "Anything else (a small detail, a matter of taste) is \"minor\".\n\n"
    "Reply with JSON only, no other words:\n"
    '{"verdict": "ok" or "redo", "problems": [{"severity": "redo" or "minor", '
    '"what": "one plain sentence for the person making the video", '
    '"fix": "one sentence for the picture model that fixes it, an instruction that names who and where"}]}\n'
    'The verdict is "redo" when any problem is. At most 4 problems, the worst first. Nothing wrong: '
    '{"verdict": "ok", "problems": []}')

CLIP_RULES = (
    "The first picture is the frame the clip starts from. The second is the clip itself: frames in time order, "
    "numbered, each with its time in the clip. A green bar under a frame means that moment is in the part "
    "of the clip the finished video uses; grey means it is cut away.\n\n"
    "Severity \"redo\" is for a problem a viewer would notice that a new clip fixes:\n"
    "- someone fades, flickers, turns see-through, vanishes, appears from nowhere, or turns into someone else\n"
    "- a face or hands melt, warp or double; a body bends the wrong way\n"
    "- the clip jumps: a cut to another angle or place, or a sudden change of the scene\n"
    "- something that should stay put moves (a parked car rolls, a wall shifts), or the motion the shot asks "
    "for does not happen or goes the wrong way (the car drives off the wrong side, someone walks off instead of "
    "sitting down)\n"
    "- writing or subtitles appear\n"
    "Only judge the green frames for these, unless a grey frame shows the action the shot needs.\n"
    "When what the shot needs happens in the clip but outside the green part (the car only drives off after "
    "the cut has moved on), that is not a redo: give it severity \"minor\" with \"start\": the time in seconds "
    "the used part should start from so it shows it.\n"
    "Anything else is \"minor\".\n\n"
    "Reply with JSON only, no other words:\n"
    '{"verdict": "ok" or "redo", "problems": [{"severity": "redo" or "minor", '
    '"what": "one plain sentence for the person making the video, with the frame number", '
    '"fix": "one sentence for the video model that fixes it, an instruction", "start": optional seconds}]}\n'
    'The verdict is "redo" when any problem is. At most 4 problems, the worst first. Nothing wrong: '
    '{"verdict": "ok", "problems": []}')

FINAL_RULES = (
    "This is the finished video: frames in time order, each with its time. The words at the bottom are its "
    "captions, burnt in on purpose. Black frames with white words are time cards, on purpose.\n"
    "Look for what a viewer would notice: captions that are cut off at an edge, too small to read on a phone, "
    "over a face or over other writing; a frame that is broken, empty or the wrong shape; the same picture "
    "twice in a row where the story moves on; anything that looks unfinished.\n\n"
    "Reply with JSON only, no other words:\n"
    '{"problems": [{"severity": "redo" or "minor", "at": seconds into the video, '
    '"what": "one plain sentence for the person making the video"}]}\n'
    'At most 5 problems, the worst first. Nothing wrong: {"problems": []}')


def _shot_text(shot: dict, script: dict, part: str) -> str:
    """What the reviewer is told about the shot: its description, who is in it and what they look like."""
    chars = {c.get("id"): c for c in script.get("characters") or [] if isinstance(c, dict)}
    lines = [f"Shot {shot['n']} of {len(script.get('shots') or [])}."]
    who = shot.get("characters") or []
    if who:
        lines.append("In this shot: " + "; ".join(
            f"{cid} ({' '.join(str(chars.get(cid, {}).get('description') or '').split())[:300]})" for cid in who))
    else:
        lines.append("No people are meant to be in this shot.")
    lines.append(f"Picture description: {' '.join(str(shot.get('image_prompt') or '').split())}")
    if part == "clip":
        lines.append(f"What should happen in the clip: {' '.join(str(shot.get('motion_prompt') or '').split())}")
    line = " ".join(str(shot.get("vo_line") or "").split())
    if line:
        lines.append(f"Spoken in this shot{' by ' + shot['speaker'] if shot.get('speaker') else ''}: \"{line}\"")
    return "\n".join(lines)


def _neighbours(script: dict, n: int) -> str:
    shots = [s for s in script.get("shots") or [] if isinstance(s, dict)]
    idx = next((i for i, s in enumerate(shots) if s.get("n") == n), None)
    if idx is None:
        return ""
    out = []
    for j, word in ((idx - 1, "Before it"), (idx + 1, "After it")):
        if 0 <= j < len(shots):
            out.append(f"{word} (shot {shots[j]['n']}): {' '.join(str(shots[j].get('image_prompt') or shots[j].get('card') or '').split())[:300]}")
    return "\n".join(out)


def _record(run_dir: Path, key: str, n: int, path: Path, data: dict, cost: float, extra: dict | None = None) -> dict:
    problems = clean_problems(data)
    verdict = "redo" if any(p["severity"] == "redo" for p in problems) else "ok"
    entry = {"mtime": _mtime(path), "verdict": verdict, "problems": problems,
             "cost": round(cost, 4), "checked": _now(), **(extra or {})}

    def change(d):
        old = d[key].get(str(n)) or {}
        entry["fixes"] = int(old.get("fixes") or 0)            # takes made by auto-fix survive a re-check
        d[key][str(n)] = entry
        d["cost"] = round(float(d.get("cost") or 0) + cost, 4)
    _update(run_dir, change)
    return entry


def check_picture(run_dir: Path, config: dict, script: dict, shot: dict) -> dict | None:
    from steps.images import is_tall, picture_size, shape_name, sheet_path, shot_path
    from steps.script import scene_anchor
    n = shot["n"]
    pic = shot_path(run_dir, n)
    if not pic.is_file():
        return None
    content: list = [{"type": "text", "text": BRIEF + _shot_text(shot, script, "picture") + "\n" + _neighbours(script, n)}]
    content += [{"type": "text", "text": f"The picture to check (shot {n}):"}, image_block(pic, 1024)]
    if not is_tall(pic):
        content.append({"type": "text", "text": f"(Its shape is {shape_name(picture_size(pic))}, not 9:16.)"})
    for cid in (shot.get("characters") or [])[:3]:
        sheet = sheet_path(run_dir, cid)
        if sheet.is_file():
            content += [{"type": "text", "text": f"Character sheet of {cid} (who {cid} must look like):"},
                        image_block(sheet, 768)]
    every = script.get("shots") or []
    idx = next((i for i, s in enumerate(every) if s.get("n") == n), None)
    shown: set[int] = set()
    if idx is not None:
        a = scene_anchor(every, idx)
        refs = []
        if a is not None:
            refs.append((every[a]["n"], "the first shot of this scene"))
        if idx > 0 and every[idx - 1].get("n") is not None and shot.get("same_scene") is True:
            refs.append((every[idx - 1]["n"], "the shot right before this one, same scene"))
        for rn, why in refs:
            rp = shot_path(run_dir, rn)
            if rn in shown or rn == n or not rp.is_file():
                continue
            shown.add(rn)
            content += [{"type": "text", "text": f"Shot {rn}, {why} (places, sides and clothes carry over):"},
                        image_block(rp, 768)]
    content.append({"type": "text", "text": PICTURE_RULES})
    data, cost = ask(config, "You are a careful film continuity reviewer.", content, f"shot {n} picture")
    return _record(run_dir, "pictures", n, pic, data, cost)


def _window(run_dir: Path, shot: dict, duration: float) -> tuple[float, float] | None:
    """The part of the clip the finished video uses: from the last cut when there is one, else
    from the script's clip timing."""
    try:
        for item in read_json(Path(run_dir) / TIMELINE):
            if item.get("n") == shot["n"] and item.get("clip_from") is not None:
                start = float(item["clip_from"])
                return (start, min(duration, start + float(item.get("end", 0)) - float(item.get("start", 0))))
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    start = float(shot.get("clip_start") or 0)
    if shot.get("seconds"):
        return (start, min(duration, start + float(shot["seconds"])))
    return (start, duration) if start else None


def check_clip(run_dir: Path, config: dict, script: dict, shot: dict) -> dict | None:
    import media
    from steps.images import shot_path
    from steps.video import video_path
    n = shot["n"]
    clip = video_path(run_dir, n)
    if not clip.is_file():
        return None
    duration = media.probe_duration(clip)
    window = _window(run_dir, shot, duration)
    times = frame_times(duration, settings(config)["frames"])
    sheet = contact_sheet(clip, times, Path(run_dir) / "review" / f"clip_{n:02d}.jpg", window)
    used = (f"The finished video uses {window[0]:.1f}s to {window[1]:.1f}s of this {duration:.1f}s clip."
            if window else f"The finished video uses the clip from its start ({duration:.1f}s long).")
    content: list = [{"type": "text", "text": BRIEF + _shot_text(shot, script, "clip") + "\n" + used}]
    pic = shot_path(run_dir, n)
    if pic.is_file():
        content += [{"type": "text", "text": "The frame the clip starts from:"}, image_block(pic, 768)]
    content += [{"type": "text", "text": "The clip, frame by frame:"}, image_block(sheet, 1400),
                {"type": "text", "text": CLIP_RULES}]
    data, cost = ask(config, "You are a careful film continuity reviewer.", content, f"shot {n} clip")
    return _record(run_dir, "clips", n, clip, data, cost,
                   {"frames": times, "window": list(window) if window else None, "seconds": round(duration, 2)})


# ----------------------------------------------------------- run the checks ----

def _shots(script: dict, only: set[int] | None, want) -> list[dict]:
    return [s for s in script.get("shots") or []
            if isinstance(s, dict) and isinstance(s.get("n"), int)
            and (only is None or s["n"] in only) and want(s)]


def _run_checks(run_dir: Path, config: dict, shots: list[dict], fn, what: str, again: bool, key: str, path_of) -> dict:
    from common import read_script
    script = read_script(run_dir)
    data = load(run_dir)
    todo = [s for s in shots if path_of(run_dir, s["n"]).is_file()
            and (again or not current(data[key].get(str(s["n"])), path_of(run_dir, s["n"])))]
    if not todo:
        return {"checked": 0, "redo": [], "failed": []}
    print(f"[review] checking {len(todo)} {what}{'s' if len(todo) != 1 else ''} "
          f"(about ${0.02 * len(todo):.2f})")
    results: dict[int, dict | None] = {}
    failed: list[int] = []

    def one(s):
        try:
            results[s["n"]] = fn(run_dir, config, script, s)
        except Exception as e:                       # one check failing never stops the rest
            failed.append(s["n"])
            print(f"  shot {s['n']}: the {what} could not be checked ({e})")

    with ThreadPoolExecutor(max_workers=settings(config)["workers"]) as pool:
        list(pool.map(one, todo))
    redo = []
    for s in todo:
        r = results.get(s["n"])
        if not r:
            continue
        if r["verdict"] == "redo":
            redo.append(s["n"])
            print(f"  shot {s['n']}: REDO {what}: " + " / ".join(p["what"] for p in r["problems"] if p["severity"] == "redo"))
        elif r["problems"]:
            print(f"  shot {s['n']}: ok ({len(r['problems'])} note{'s' if len(r['problems']) != 1 else ''})")
        else:
            print(f"  shot {s['n']}: ok")
    return {"checked": len(todo) - len(failed), "redo": redo, "failed": sorted(failed)}


def check_pictures(run_dir: Path, config: dict, only: set[int] | None = None, again: bool = False) -> dict:
    from common import read_script
    from steps.images import needs_keyframe, shot_path
    script = read_script(run_dir)
    shots = _shots(script, only, lambda s: not s.get("card") and not s.get("app_screen")
                   and not s.get("texts") and needs_keyframe(s))
    return _run_checks(run_dir, config, shots, check_picture, "picture", again, "pictures", shot_path)


def check_clips(run_dir: Path, config: dict, only: set[int] | None = None, again: bool = False) -> dict:
    from common import read_script
    from steps.video import video_path
    script = read_script(run_dir)
    shots = _shots(script, only, lambda s: bool(s.get("animate") or s.get("talk")))
    return _run_checks(run_dir, config, shots, check_clip, "clip", again, "clips", video_path)


# ------------------------------------------------------------- the final cut ----

def _detect(path: Path, vf: str | None, af: str | None) -> str:
    """ffmpeg's log for a detect filter run over the file (no output written)."""
    import common
    import media
    cmd = [media.tool_path("ffmpeg") or common.TOOLS["ffmpeg"], "-hide_banner", "-nostdin", "-i", str(path)]
    if vf:
        cmd += ["-vf", vf]
    if af:
        cmd += ["-af", af]
    if not af:
        cmd += ["-an"]
    if not vf:
        cmd += ["-vn"]
    cmd += ["-f", "null", "-"]
    proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=900)
    return proc.stderr or ""


def spans(log: str, start_key: str, end_key: str) -> list[tuple[float, float]]:
    """(start, end) pairs from a detect filter's log lines."""
    out, start = [], None
    for line in log.splitlines():
        m = re.search(rf"{start_key}[:=]\s*(-?[\d.]+)", line)
        if m:
            start = float(m.group(1))
        m = re.search(rf"{end_key}[:=]\s*(-?[\d.]+)", line)
        if m and start is not None:
            out.append((max(0.0, start), float(m.group(1))))
            start = None
    return out


def _timeline(run_dir: Path) -> list[dict]:
    try:
        items = read_json(Path(run_dir) / TIMELINE)
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []
    except (OSError, ValueError):
        return []


def _shot_at(timeline: list[dict], t: float) -> dict | None:
    return next((i for i in timeline if float(i.get("start", 0)) <= t < float(i.get("end", 0))), None)


def _quiet_kind(item: dict | None) -> bool:
    """Shots that are black or still on purpose: time cards, app screens, messages."""
    return bool(item) and item.get("kind") in ("card", "app_screen", "texts")


def measure_final(run_dir: Path, config: dict) -> list[dict]:
    """The free checks: black, frozen and silent stretches (ffmpeg), and shots that sit too long."""
    final = Path(run_dir) / "final.mp4"
    timeline = _timeline(run_dir)
    issues = []
    for a, b in spans(_detect(final, "blackdetect=d=0.4:pix_th=0.08", None), "black_start", "black_end"):
        item = _shot_at(timeline, (a + b) / 2)
        if not _quiet_kind(item):
            issues.append({"kind": "black", "at": round(a, 2), "until": round(b, 2), "severity": "redo",
                           "shot": item.get("n") if item else None,
                           "what": f"{b - a:.1f}s of black picture" + (f" in shot {item['n']}" if item else "")})
    for a, b in spans(_detect(final, "freezedetect=n=0.002:d=1.5", None), "freeze_start", "freeze_end"):
        item = _shot_at(timeline, (a + b) / 2)
        if not _quiet_kind(item) and (item is None or item.get("kind") == "clip"):
            issues.append({"kind": "frozen", "at": round(a, 2), "until": round(b, 2), "severity": "minor",
                           "shot": item.get("n") if item else None,
                           "what": f"the picture stands still for {b - a:.1f}s" + (f" in shot {item['n']}" if item else "")})
    import media
    if media.has_audio_stream(final):
        for a, b in spans(_detect(final, None, "silencedetect=noise=-45dB:d=1.2"), "silence_start", "silence_end"):
            item = _shot_at(timeline, (a + b) / 2)
            issues.append({"kind": "silence", "at": round(a, 2), "until": round(b, 2), "severity": "minor",
                           "shot": item.get("n") if item else None,
                           "what": f"{b - a:.1f}s with no sound at all"})
    slow = float(settings(config)["slow_shot_seconds"])
    for item in timeline:
        length = float(item.get("end", 0)) - float(item.get("start", 0))
        if length > slow and item.get("kind") not in ("card",):
            issues.append({"kind": "slow", "at": round(float(item["start"]), 2), "until": round(float(item["end"]), 2),
                           "severity": "minor", "shot": item.get("n"),
                           "what": f"shot {item.get('n')} stays on screen {length:.1f}s; a short usually cuts every 2 to 4s"})
    return issues


def eyes_command(config: dict) -> str | None:
    s = settings(config)
    if str(s.get("eyes") or "auto").lower() in ("off", "false", "no", "0"):
        return None
    return shutil.which(str(s.get("eyes_command") or "eyes"))


def eyes_measure(run_dir: Path, config: dict) -> dict | None:
    """Claude Eyes' measured editing style of the cut: pacing, speech speed, captions and
    loudness. None when Eyes is not installed or does not run. Eyes runs on this computer; it
    is not given any API key, so nothing is sent anywhere."""
    exe = eyes_command(config)
    if not exe:
        return None
    final = Path(run_dir) / "final.mp4"
    import os
    env = {k: v for k, v in os.environ.items() if not k.endswith(("_API_KEY", "_KEY", "_TOKEN"))}
    try:
        subprocess.run([exe, "index", str(final), "--title", f"vidgen {Path(run_dir).name}", "--force", "--json"],
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=900, env=env,
                       cwd=str(run_dir), encoding="utf-8", errors="replace", check=True)
        proc = subprocess.run([exe, "dna", str(final), "--json"], stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=300, env=env, cwd=str(run_dir), encoding="utf-8",
                              errors="replace", check=True)
        dna = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        print(f"[review] Claude Eyes did not measure the cut ({type(e).__name__}); the other checks still ran")
        return None
    return summarize_dna(dna)


def summarize_dna(dna: dict) -> dict:
    pacing = dna.get("pacing") or {}
    speech = dna.get("speech") or {}
    caps = ((dna.get("text") or {}).get("captions") or {})
    audio = dna.get("audio") or {}
    keep = {
        "cuts_per_min": pacing.get("cuts_per_min"), "median_shot": pacing.get("median_shot"),
        "longest_shot": pacing.get("longest_shot"), "cuts_first_3s": pacing.get("cuts_first_3s"),
        "words_per_minute": speech.get("words_per_minute"), "first_word_at": speech.get("first_word_at"),
        "words_per_caption": caps.get("words_per_caption"), "caption_position": caps.get("position"),
        "lufs": audio.get("lufs"), "silence_share": audio.get("silence_share"),
    }
    return {k: v for k, v in keep.items() if v is not None}


def eyes_issues(m: dict) -> list[dict]:
    """What the measurements say a viewer would feel."""
    out = []
    wpm = m.get("words_per_minute")
    if isinstance(wpm, (int, float)) and wpm > 200:
        out.append({"kind": "pace", "severity": "minor", "what": f"the voice runs at {wpm:.0f} words a minute; "
                    "above about 190 viewers miss words"})
    first = m.get("first_word_at")
    if isinstance(first, (int, float)) and first > 2.0:
        out.append({"kind": "pace", "severity": "minor", "at": 0.0,
                    "what": f"the first word is heard at {first:.1f}s; the hook should start in the first second or two"})
    lufs = m.get("lufs")
    if isinstance(lufs, (int, float)) and (lufs < -20 or lufs > -9):
        out.append({"kind": "sound", "severity": "minor",
                    "what": f"the cut is {'quiet' if lufs < -20 else 'loud'} ({lufs:.1f} LUFS); phones play shorts at about -14"})
    return out


def final_sheet(run_dir: Path) -> Path | None:
    """A strip of the finished cut: one frame from the middle of each shot (at most 16)."""
    import media
    final = Path(run_dir) / "final.mp4"
    timeline = [i for i in _timeline(run_dir) if i.get("kind") != "card"]
    if timeline:
        times = [round((float(i["start"]) + float(i["end"])) / 2, 2) for i in timeline]
        if len(times) > 16:
            step = len(times) / 16
            times = [times[int(k * step)] for k in range(16)]
    else:
        times = frame_times(media.probe_duration(final), 12)
    return contact_sheet(final, times, Path(run_dir) / "review" / "final.jpg", None, cols=4, tile=(270, 480))


def check_final(run_dir: Path, config: dict, again: bool = False) -> dict | None:
    final = Path(run_dir) / "final.mp4"
    if not final.is_file():
        return None
    old = load(run_dir).get("final")
    if not again and isinstance(old, dict) and current(old, final):
        return old
    s = settings(config)
    print("[review] checking the finished video (black, frozen and silent stretches, slow shots)")
    issues = measure_final(run_dir, config)
    eyes = eyes_measure(run_dir, config)
    if eyes:
        issues += eyes_issues(eyes)
    cost = 0.0
    look_failed = None
    if s["final_look"]:
        try:
            sheet = final_sheet(run_dir)
            content = [{"type": "text", "text": BRIEF + FINAL_RULES}, image_block(sheet, 1600)]
            data, cost = ask(config, "You are a careful reviewer of short vertical videos.", content, "the final cut")
            for p in clean_problems(data, keep_at=True):
                issues.append({"kind": "look", **p})
        except Exception as e:
            look_failed = str(e)
            print(f"[review] the look at the finished video failed ({e}); the measured checks still count")
    issues.sort(key=lambda i: (i.get("severity") != "redo", float(i.get("at") or 0)))
    entry = {"mtime": _mtime(final), "issues": issues, "eyes": eyes, "cost": round(cost, 4), "checked": _now()}
    if look_failed:
        entry["look_failed"] = look_failed[:200]

    def change(d):
        d["final"] = entry
        d["cost"] = round(float(d.get("cost") or 0) + cost, 4)
    _update(run_dir, change)
    for i in issues:
        at = f"{i['at']:.1f}s: " if isinstance(i.get("at"), (int, float)) else ""
        print(f"  {i['severity'].upper():5} {at}{i['what']}")
    if not issues:
        print("  nothing found")
    return entry


# -------------------------------------------------------------------- fixes ----

def clip_cost(config: dict) -> float:
    fal = config["fal"]
    return float(fal["video_seconds"]) * float(fal["video_cost_per_second"])


def fix_note(config: dict, what: str, n: int) -> str:
    """The reviewer's fix for this shot, said to the picture or video model when it is made
    again ("" when there is none)."""
    note = ((config.get("_fix_notes") or {}).get(what) or {}).get(n)
    return f" FIX FROM REVIEW: {note}" if note else ""


def fixes_for(run_dir: Path, what: str, shots: list[int]) -> dict[int, str]:
    key = "pictures" if what == "picture" else "clips"
    data = load(run_dir)
    out = {}
    for n in shots:
        entry = data[key].get(str(n)) or {}
        text = " ".join(p["fix"] for p in entry.get("problems") or [] if p.get("fix") and p.get("severity") == "redo")
        if not text:
            text = " ".join(p["fix"] for p in entry.get("problems") or [] if p.get("fix"))
        if text:
            out[n] = text[:600]
    return out


def _count_fix(run_dir: Path, what: str, shots: list[int]) -> None:
    key = "pictures" if what == "picture" else "clips"

    def change(d):
        for n in shots:
            entry = d[key].setdefault(str(n), {})
            entry["fixes"] = int(entry.get("fixes") or 0) + 1
    _update(run_dir, change)


def fix(run_dir: Path, config: dict, shots: list[int], what: str, recheck: bool = True) -> None:
    """Make these shots' pictures ("picture": picture, then its clip if it had one) or clips
    ("clip") again, with the reviewer's fixes in the prompts; then check them again."""
    import commands
    from common import read_script
    from steps.video import video_path
    if not shots:
        return
    only = ",".join(str(n) for n in sorted(set(shots)))
    notes = fixes_for(run_dir, what, shots)
    config = {**config, "_fix_notes": {**(config.get("_fix_notes") or {}), what: notes}}
    _count_fix(run_dir, what, shots)
    script = read_script(run_dir)
    animated = {s["n"] for s in script["shots"] if s.get("animate") or s.get("talk")}
    if what == "picture":
        commands.run_step("images", run_dir, config, only=only)
        had_clips = [n for n in shots if n in animated and video_path(run_dir, n).exists()]
        if had_clips:                      # a clip made from the old picture is out of date now
            commands.step(run_dir.name, "video", config, only=",".join(map(str, had_clips)), review_after=False)
    else:
        commands.step(run_dir.name, "video", config, only=only, review_after=False)
    if recheck:
        wanted = set(shots)
        if what == "picture":
            check_pictures(run_dir, config, wanted)
        check_clips(run_dir, config, wanted)


def auto_fix_round(run_dir: Path, config: dict, what: str, only: set[int] | None = None) -> list[int]:
    """Make again what the review flagged, up to max_fixes takes per shot. Returns the shots
    still flagged when it stops."""
    from steps.images import image_cost
    key = "pictures" if what == "picture" else "clips"
    limit = settings(config)["max_fixes"]
    for _ in range(limit):
        data = load(run_dir)
        todo = [n for n in flagged(run_dir, key, only) if int((data[key].get(str(n)) or {}).get("fixes") or 0) < limit]
        if not todo:
            break
        if what == "picture":
            price = f"about ${image_cost(config) * len(todo):.2f}"
        else:
            price = f"about ${clip_cost(config) * len(todo):.2f}"
        print(f"\n[review] auto-fix: making {len(todo)} {what}{'s' if len(todo) != 1 else ''} again "
              f"with the reviewer's fixes (shot{'s' if len(todo) != 1 else ''} {', '.join(map(str, todo))}; {price})")
        fix(run_dir, config, todo, what)
    left = flagged(run_dir, key, only)
    if left:
        print(f"[review] still flagged after {limit} new take{'s' if limit != 1 else ''}: shot"
              f"{'s' if len(left) != 1 else ''} {', '.join(map(str, left))}. Look at "
              f"{'them' if len(left) != 1 else 'it'} on the video's page.")
    return left


def after_step(step: str, run_dir: Path, config: dict, only: set[int] | None = None) -> None:
    """What the pipeline calls after a step. Does nothing when the review is off for this
    video; never raises (a failed review must not stop the video)."""
    from common import run_engine
    if not on(config, run_dir) or run_engine(run_dir) == "claude_code":
        return
    s = settings(config)
    try:
        if step == "images" and s["pictures"]:
            check_pictures(run_dir, config, only)
            if auto_fix(config, run_dir):
                auto_fix_round(run_dir, config, "picture", only)
        elif step == "video" and s["clips"]:
            check_clips(run_dir, config, only)
            if auto_fix(config, run_dir):
                auto_fix_round(run_dir, config, "clip", only)
        elif step == "assemble" and s["final"]:
            check_final(run_dir, config)
    except Exception as e:
        print(f"[review] the review could not finish ({e}); the video carries on without it")


def review(run_dir: Path, config: dict, what: str = "all", only: set[int] | None = None,
           again: bool = False, fix_flagged: bool = False) -> dict:
    """A whole review of a video on demand: `what` is all, pictures, clips or final."""
    out: dict = {}
    if what in ("all", "pictures"):
        out["pictures"] = check_pictures(run_dir, config, only, again)
        if fix_flagged:
            auto_fix_round(run_dir, config, "picture", only)
    if what in ("all", "clips"):
        out["clips"] = check_clips(run_dir, config, only, again)
        if fix_flagged:
            auto_fix_round(run_dir, config, "clip", only)
    if what in ("all", "final") and only is None:
        out["final"] = check_final(run_dir, config, again)
    data = load(run_dir)
    print(f"\n[review] report: {report_path(run_dir)}  (review cost so far ${float(data.get('cost') or 0):.2f})")
    return out
