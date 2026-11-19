"""Batches of Contrast videos (contrast.py): one list of scenes in, a folder of numbered videos
and a captions file out.

    runs/_contrast/<batch id>/
        batch.json          the scenes, what was drawn from each, what the checks found
        videos/01.mp4 ...   one ten second video per scene
        captions.csv        number, file, labels, template and caption, for any scheduler
        captions.txt        the same captions to copy by hand
        first_second.jpg    every video half a second in, side by side: the three-second check

    create(name, scenes)            a new batch from a list of scenes
    starter()                       the scenes that ship with VidGen (assets/contrast_scenes.json)
    render(batch_id, only, workers) draw what is missing or out of date, several at once
    write_scenes(n, about, config)  Claude writes n scenes (a few cents)
    variations(batch_id, of, each, config)   Claude varies the scenes that did best
    add_scenes / edit_scene / remove_scene / delete

Drawing costs nothing. Only write_scenes and variations call a model, and only when asked."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

import contrast
from common import ROOT, StepError, read_json, runs_dir, slugify, write_json

STARTER_FILE = ROOT / "assets" / "contrast_scenes.json"
DEFAULT_TAG = "SEARCH IRO AI"
DEFAULT_ABOUT = ("people who want to get good at using AI at work: writing clear prompts, giving context, "
                 "checking answers, asking follow-up questions and practising a few minutes a day")
MAX_SCENES = 120
MAX_WRITE = 60
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,80}$")


def root() -> Path:
    return runs_dir() / "_contrast"


def batch_dir(batch_id: str, must_exist: bool = True) -> Path:
    if not isinstance(batch_id, str) or not ID_RE.match(batch_id):
        raise StepError(f"{batch_id!r} is not a batch")
    path = root() / batch_id
    if must_exist and not (path / "batch.json").is_file():
        raise StepError(f"there is no Contrast batch called {batch_id}")
    return path


def video_path(batch_id: str, n: int) -> Path:
    return batch_dir(batch_id) / "videos" / f"{int(n):02d}.mp4"


def _key(scene: dict, tag: str) -> str:
    """Changes whenever the video a scene makes would change."""
    s = contrast.clean_scene(scene)
    return hashlib.sha1(json.dumps([s["template"], s["left"], s["right"], str(tag or "").upper(), contrast.SECONDS],
                                   sort_keys=True).encode()).hexdigest()[:16]


def clean_scenes(scenes, limit: int = MAX_SCENES) -> tuple[list[dict], list[str]]:
    """(the scenes that can be drawn, why the others cannot). Doubles are dropped."""
    good, bad, seen = [], [], set()
    if not isinstance(scenes, list):
        raise StepError("scenes must be a list")
    for i, raw in enumerate(scenes, 1):
        if not isinstance(raw, dict):
            bad.append(f"scene {i} is not a scene")
            continue
        s = contrast.clean_scene(raw)
        problems = contrast.check_scene(s)
        if problems:
            bad.append(f"scene {i} ({s['left'] or '?'} vs {s['right'] or '?'}): {problems[0]}")
            continue
        pair = (s["left"], s["right"])
        if pair in seen:
            bad.append(f"scene {i} ({s['left']} vs {s['right']}) is in the list twice")
            continue
        seen.add(pair)
        item = {"template": s["template"], "left": s["left"], "right": s["right"], "caption": s["caption"]}
        if isinstance(raw.get("from"), str) and raw["from"].strip():
            item["from"] = raw["from"].strip()[:60]          # the scene this is a variation of
        good.append(item)
        if len(good) >= limit:
            break
    return good, bad


def starter() -> list[dict]:
    """The scenes that ship with VidGen."""
    if not STARTER_FILE.is_file():
        return []
    good, _ = clean_scenes((read_json(STARTER_FILE) or {}).get("scenes") or [])
    return good


# ------------------------------------------------------------------- the batch ----

def load(batch_id: str) -> dict:
    data = read_json(batch_dir(batch_id) / "batch.json")
    data.setdefault("scenes", [])
    data.setdefault("made", {})
    data.setdefault("checks", {})
    return data


def _save(batch_id: str, data: dict) -> None:
    path = batch_dir(batch_id, must_exist=False)
    path.mkdir(parents=True, exist_ok=True)
    tmp = path / "batch.json.tmp"
    write_json(tmp, data)
    tmp.replace(path / "batch.json")
    _write_captions(batch_id, data)


def _number(scenes: list[dict]) -> list[dict]:
    return [{**{k: v for k, v in s.items() if k != "n"}, "n": i} for i, s in enumerate(scenes, 1)]


def create(name: str, scenes: list[dict], end_tag: str | None = DEFAULT_TAG) -> dict:
    """A new batch. Nothing is drawn yet."""
    good, bad = clean_scenes(scenes)
    if not good:
        raise StepError("none of the scenes can be drawn" + (": " + "; ".join(bad[:3]) if bad else ""))
    name = " ".join(str(name or "").split())[:60] or "Contrast batch"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    batch_id = f"{stamp}-{slugify(name, 28) or 'batch'}"
    k = 2
    while (root() / batch_id).exists():
        batch_id = f"{stamp}-{slugify(name, 24) or 'batch'}-{k}"
        k += 1
    tag = "" if end_tag is None else " ".join(str(end_tag).upper().split())[:28]
    data = {"id": batch_id, "name": name, "created_at": datetime.now().isoformat(timespec="seconds"),
            "end_tag": tag, "scenes": _number(good), "made": {}, "checks": {}, "skipped": bad}
    _save(batch_id, data)
    return data


def create_pending(name: str, end_tag: str | None, writing: dict) -> dict:
    """A batch whose scenes are still being written (the page shows it while Claude works)."""
    name = " ".join(str(name or "").split())[:60] or "Contrast batch"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    batch_id = f"{stamp}-{slugify(name, 28) or 'batch'}"
    k = 2
    while (root() / batch_id).exists():
        batch_id = f"{stamp}-{slugify(name, 24) or 'batch'}-{k}"
        k += 1
    tag = "" if end_tag is None else " ".join(str(end_tag).upper().split())[:28]
    data = {"id": batch_id, "name": name, "created_at": datetime.now().isoformat(timespec="seconds"),
            "end_tag": tag, "scenes": [], "made": {}, "checks": {}, "skipped": [], "writing": dict(writing or {})}
    _save(batch_id, data)
    return data


def set_note(batch_id: str, writing: dict | None = None, error: str | None = None) -> dict:
    """Mark a batch as waiting for scenes, done waiting, or failed with a reason."""
    data = load(batch_id)
    if writing:
        data["writing"] = dict(writing)
    else:
        data.pop("writing", None)
    if error:
        data["error"] = str(error)[:400]
    else:
        data.pop("error", None)
    _save(batch_id, data)
    return data


def batches() -> list[dict]:
    """Every batch, the newest first, as a short summary."""
    out = []
    base = root()
    if not base.is_dir():
        return out
    for d in sorted((p for p in base.iterdir() if p.is_dir() and (p / "batch.json").is_file()), key=lambda p: p.name, reverse=True):
        try:
            out.append(summary(load(d.name)))
        except (OSError, ValueError, StepError):
            continue
    return out


def is_made(batch_id: str, data: dict, scene: dict) -> bool:
    """True when this scene's video is there and was drawn from the scene as it is now."""
    return (data["made"].get(str(scene["n"])) == _key(scene, data.get("end_tag", ""))
            and video_path(batch_id, scene["n"]).is_file())


def summary(data: dict) -> dict:
    done = sum(1 for s in data["scenes"] if is_made(data["id"], data, s))
    return {"id": data["id"], "name": data.get("name") or data["id"], "created_at": data.get("created_at"),
            "scenes": len(data["scenes"]), "made": done, "end_tag": data.get("end_tag", ""),
            "problems": sum(1 for v in data.get("checks", {}).values() if v),
            "writing": bool(data.get("writing")), "error": data.get("error")}


def _write_captions(batch_id: str, data: dict) -> None:
    folder = batch_dir(batch_id, must_exist=False)
    with open(folder / "captions.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["number", "file", "left", "right", "template", "caption"])
        for s in data["scenes"]:
            w.writerow([f"{s['n']:02d}", f"{s['n']:02d}.mp4", s["left"], s["right"], s["template"], s.get("caption", "")])
    lines = [f"{s['n']:02d}  {s['left']} vs {s['right']}\n    {s.get('caption', '')}\n" for s in data["scenes"]]
    (folder / "captions.txt").write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------- changing scenes ----

def _drop_video(batch_id: str, n: int) -> None:
    video_path(batch_id, n).unlink(missing_ok=True)


def add_scenes(batch_id: str, scenes: list[dict]) -> tuple[dict, list[str]]:
    """Add scenes to the end of a batch. Returns (the batch, why some were left out)."""
    data = load(batch_id)
    have = {(s["left"], s["right"]) for s in data["scenes"]}
    good, bad = clean_scenes(scenes)
    fresh = []
    for s in good:
        if (s["left"], s["right"]) in have:
            bad.append(f"{s['left']} vs {s['right']} is already in the batch")
            continue
        have.add((s["left"], s["right"]))
        fresh.append(s)
    room = MAX_SCENES - len(data["scenes"])
    if len(fresh) > room:
        bad.append(f"a batch holds at most {MAX_SCENES} scenes; {len(fresh) - max(room, 0)} were left out")
        fresh = fresh[:max(room, 0)]
    start = len(data["scenes"])
    data["scenes"] = data["scenes"] + [{**s, "n": start + i} for i, s in enumerate(fresh, 1)]
    _save(batch_id, data)
    return data, bad


def edit_scene(batch_id: str, n: int, changes: dict) -> dict:
    """Change one scene's template, labels or caption. A change to what is drawn makes its
    video out of date; a new caption does not."""
    data = load(batch_id)
    scene = next((s for s in data["scenes"] if s["n"] == int(n)), None)
    if scene is None:
        raise StepError(f"this batch has no scene {n}")
    new = contrast.clean_scene({**scene, **{k: v for k, v in (changes or {}).items() if k in ("template", "left", "right", "caption")}})
    problems = contrast.check_scene(new)
    if problems:
        raise StepError("; ".join(problems))
    for other in data["scenes"]:
        if other["n"] != scene["n"] and (other["left"], other["right"]) == (new["left"], new["right"]):
            raise StepError(f"scene {other['n']} already has these two labels")
    scene.update({k: new[k] for k in ("template", "left", "right", "caption")})
    data["checks"].pop(str(scene["n"]), None)
    _save(batch_id, data)
    return data


def remove_scene(batch_id: str, n: int) -> dict:
    """Take a scene out. The later ones move up, and their videos with them."""
    data = load(batch_id)
    n = int(n)
    if not any(s["n"] == n for s in data["scenes"]):
        raise StepError(f"this batch has no scene {n}")
    if len(data["scenes"]) == 1:
        raise StepError("a batch needs at least one scene; delete the batch instead")
    _drop_video(batch_id, n)
    made, checks = {}, {}
    kept = [s for s in data["scenes"] if s["n"] != n]
    for new_n, s in enumerate(kept, 1):
        old = s["n"]
        if old != new_n:
            src, dest = video_path(batch_id, old), video_path(batch_id, new_n)
            if src.is_file():
                src.replace(dest)
        if str(old) in data["made"]:
            made[str(new_n)] = data["made"][str(old)]
        if data["checks"].get(str(old)):
            checks[str(new_n)] = data["checks"][str(old)]
        s["n"] = new_n
    data.update(scenes=kept, made=made, checks=checks)
    _save(batch_id, data)
    return data


def set_tag(batch_id: str, end_tag: str | None) -> dict:
    data = load(batch_id)
    data["end_tag"] = "" if end_tag is None else " ".join(str(end_tag).upper().split())[:28]
    _save(batch_id, data)
    return data


def delete(batch_id: str) -> None:
    shutil.rmtree(batch_dir(batch_id))


# ----------------------------------------------------------------------- drawing ----

def workers_default() -> int:
    import os
    return max(1, min(6, (os.cpu_count() or 2)))


def render(batch_id: str, only: set[int] | None = None, workers: int | None = None, again: bool = False,
           log=print, on_done=None) -> dict:
    """Draw every video that is missing or out of date (or all of them with `again`), several
    at once. One scene that fails does not stop the others. Returns {"made": [...],
    "failed": {n: why}, "seconds": ...}."""
    import media
    from parallel import TaskRunner
    media.require_ffmpeg()
    data = load(batch_id)
    tag = data.get("end_tag", "")
    todo = [s for s in data["scenes"] if (only is None or s["n"] in only) and (again or not is_made(batch_id, data, s))]
    if not todo:
        log("[contrast] every video is already made")
        return {"made": [], "failed": {}, "seconds": 0.0}
    n_workers = max(1, min(int(workers or workers_default()), len(todo)))
    log(f"[contrast] drawing {len(todo)} video{'s' if len(todo) != 1 else ''}, {n_workers} at a time (no model is called; this is free)")
    import progress
    progress.step("render")
    progress.plan(len(todo), "videos")
    started = time.time()
    made, failed = [], {}
    import threading
    lock = threading.Lock()

    def one(scene: dict) -> None:
        n = scene["n"]
        t0 = time.time()
        try:
            contrast.render(scene, video_path(batch_id, n), end_tag=tag)
            problems = contrast.first_second(scene)
        except Exception as e:                                # one bad scene must not stop the batch
            with lock:
                failed[n] = str(e)
            log(f"  {n:02d} failed: {e}")
            return
        with lock:
            made.append(n)
            fresh = load(batch_id)                            # another scene may have finished meanwhile
            fresh["made"][str(n)] = _key(scene, tag)
            if problems:
                fresh["checks"][str(n)] = problems
            else:
                fresh["checks"].pop(str(n), None)
            _save(batch_id, fresh)
        note = f"  CHECK: {problems[0]}" if problems else ""
        log(f"  {n:02d} {scene['left']} vs {scene['right']}: done in {time.time() - t0:.0f}s{note}")
        progress.tick()
        if on_done:
            on_done(len(made) + len(failed), len(todo))

    runner = TaskRunner(n_workers)
    for scene in todo:
        runner.submit(one, scene)
    runner.join()
    sheet(batch_id)
    took = time.time() - started
    log(f"[contrast] {len(made)} made" + (f", {len(failed)} failed" if failed else "") + f" in {took:.0f}s: {batch_dir(batch_id) / 'videos'}")
    return {"made": sorted(made), "failed": failed, "seconds": round(took, 1)}


def sheet(batch_id: str) -> Path | None:
    """Every scene half a second in, side by side with its number: one look shows a label that
    is cut off or a side with nothing on it. Drawn from the scenes, so it never needs the videos."""
    from PIL import Image, ImageDraw
    data = load(batch_id)
    scenes = data["scenes"]
    if not scenes:
        return None
    cols = min(6, len(scenes))
    rows = (len(scenes) + cols - 1) // cols
    tw, th = 270, 300
    out = Image.new("RGB", (cols * tw, rows * th), (5, 7, 16))
    d = ImageDraw.Draw(out)
    font = contrast._font(contrast.TAG_FONT, 22)
    for i, s in enumerate(scenes):
        tile = contrast.frame(s, 0.5, "").crop((0, 330, contrast.W, 1530)).resize((tw, th))
        x, y = (i % cols) * tw, (i // cols) * th
        out.paste(tile, (x, y))
        flagged = bool(data["checks"].get(str(s["n"])))
        # the number sits at the foot of the tile: at the top it would cover the left label,
        # and the labels are the thing this sheet is for
        d.rectangle([x + 6, y + th - 34, x + 46, y + th - 6], fill=(200, 60, 70) if flagged else (20, 26, 52))
        d.text((x + 26, y + th - 20), f"{s['n']:02d}", font=font, fill=(255, 255, 255), anchor="mm")
    path = batch_dir(batch_id) / "first_second.jpg"
    out.save(path, quality=86)
    return path


def export_zip(batch_id: str) -> Path:
    """The finished videos and the captions in one zip, for moving to a phone or a scheduler."""
    import zipfile
    data = load(batch_id)
    folder = batch_dir(batch_id)
    dest = folder / f"{batch_id}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_STORED) as z:
        for s in data["scenes"]:
            v = video_path(batch_id, s["n"])
            if is_made(batch_id, data, s):
                z.write(v, f"{s['n']:02d}.mp4")
        for name in ("captions.csv", "captions.txt"):
            if (folder / name).is_file():
                z.write(folder / name, name)
    return dest


# ------------------------------------------------------------ Claude writes scenes ----

WRITER = """You write scenes for a page of ten second silent videos. Every video shows two kinds of
people side by side with a short label over each. A tiny story with one prop plays out, and the
one on the RIGHT wins. Nobody speaks; the labels are the only words on screen, so the viewer
must get the contrast from two labels and the picture.

The stories you can choose from ("template"):
{templates}

Rules for a scene:
- "left" is the habit that loses, "right" is the habit that wins. One to three words each, at
  most 22 letters, plain words a fourteen year old knows. They are shown in capital letters.
- The two labels are a contrast the audience already feels and can tell apart at a glance.
  The right one is something a person can start doing today. Never an insult, never a brand.
- Pick the template whose story shows this contrast (waiting against starting is stairs,
  fussing against building is blocks, asking once against asking again is doors, one rough
  try against improving it is score). Use all four templates about equally.
- "caption" is what goes under the video: one plain sentence that says the lesson, then one
  short question that makes people answer. Lower case, no hashtags, no emoji, no dashes, no
  name of any app or product, at most 170 letters.
- No two scenes with the same idea in other words.

Reply with JSON only, no other words:
{{"scenes": [{{"template": "stairs", "left": "WAITING", "right": "STARTING", "caption": "..."}}]}}"""


def _templates_text() -> str:
    return "\n".join(f'- "{name}": {what}' for name, what in contrast.TEMPLATES.items())


def _ask(config: dict, system: str, user: str, client=None) -> list:
    import steps.script as S
    client = client or S.create_client()
    model = config["script"]["model"]
    response = S.call_model(client, model, 16000, system, [{"role": "user", "content": user}], effort="medium")
    try:
        data = S.parse_json(S.response_text(response))
    except ValueError as e:
        raise StepError(f"the scenes came back in a form that could not be read ({e})") from None
    scenes = data.get("scenes") if isinstance(data, dict) else data
    if not isinstance(scenes, list):
        raise StepError("the reply had no list of scenes")
    return scenes


def write_scenes(n: int, about: str = "", config: dict | None = None, client=None, avoid: list[dict] | None = None) -> list[dict]:
    """Claude writes `n` scenes for an audience (one request, a few cents). Scenes that cannot
    be drawn are left out, so it may return fewer."""
    from common import load_config
    n = max(1, min(int(n), MAX_WRITE))
    config = config or load_config()
    about = " ".join(str(about or "").split())[:400] or DEFAULT_ABOUT
    taken = "".join(f"\n- {s['left']} vs {s['right']}" for s in (avoid or [])[:80])
    user = (f"The page is for: {about}.\n\nWrite {n} scenes."
            + (f"\n\nThese are already made, so write different ones:{taken}" if taken else ""))
    scenes = _ask(config, WRITER.format(templates=_templates_text()), user, client)
    have = {(s["left"], s["right"]) for s in (avoid or [])}
    good, _ = clean_scenes(scenes)
    good = [s for s in good if (s["left"], s["right"]) not in have][:n]
    if not good:
        raise StepError("none of the scenes that came back could be drawn; try again")
    return good


def variations(batch_id: str, of: list[int], each: int = 10, config: dict | None = None, client=None) -> list[dict]:
    """Claude writes `each` variations of every scene in `of` (the ones that did best): the same
    contrast, new words and sometimes another story. Returns the new scenes; add_scenes puts
    them in a batch."""
    from common import load_config
    config = config or load_config()
    data = load(batch_id)
    picked = [s for s in data["scenes"] if s["n"] in {int(x) for x in of}]
    if not picked:
        raise StepError("choose at least one scene to vary")
    each = max(1, min(int(each), 20))
    if len(picked) * each > MAX_WRITE:
        raise StepError(f"that is {len(picked) * each} new scenes; ask for at most {MAX_WRITE} at a time")
    listing = "\n".join(f'{i}. [{s["template"]}] {s["left"]} vs {s["right"]}: {s.get("caption", "")}' for i, s in enumerate(picked, 1))
    taken = "".join(f"\n- {s['left']} vs {s['right']}" for s in data["scenes"][:100])
    user = (f"These scenes got the most views:\n{listing}\n\nWrite {each} variations of each one. A variation keeps the "
            f"same contrast (the same losing habit against the same winning habit) and says it in new words, for a new "
            f"everyday situation, and it may use another template when that story fits better. Add \"from\": the number "
            f"of the scene it varies (1 to {len(picked)}).\n\nNone of these, they are already made:{taken}")
    scenes = _ask(config, WRITER.format(templates=_templates_text()), user, client)
    for raw in scenes:
        if isinstance(raw, dict):
            try:
                src = picked[int(raw.get("from")) - 1]
                raw["from"] = f"{src['left']} vs {src['right']}"
            except (TypeError, ValueError, IndexError):
                raw.pop("from", None)
    have = {(s["left"], s["right"]) for s in data["scenes"]}
    good, _ = clean_scenes(scenes)
    good = [s for s in good if (s["left"], s["right"]) not in have]
    if not good:
        raise StepError("none of the variations that came back could be drawn; try again")
    return good
