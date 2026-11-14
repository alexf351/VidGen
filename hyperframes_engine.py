"""HyperFrames on the Claude Code engine (formats whose code_render.kind is "hyperframes").

HyperFrames (HeyGen, Apache-2.0, https://github.com/heygen-com/hyperframes) renders HTML with a
paused GSAP timeline to MP4, frame by frame, in headless Chrome. The run's code folder is a
HyperFrames project:

    compositions/beat_NN.html   one scene per beat (Claude Code writes them)
    index.html                  the root page that mounts them, with the voice and the music
                                (VidGen writes it from story.json, so the timing follows the voice)
    timing.json                 each beat's start and length, the voice's words, the music's beats
    assets/                     gsap, three.js, lib/toon.js, theme.css, Iro's screens, the cast's pictures,
                                voice, music
    hf-docs/                    HyperFrames' own skill docs, from the installed version

The steps run in another order than the other code formats: story, VOICE, scenes, render. The
scenes are timed in HTML, so the voice has to set each beat's length before they are written.

Telemetry is off for every HyperFrames command VidGen or Claude Code runs (HYPERFRAMES_NO_TELEMETRY
and DO_NOT_TRACK). The CLI is installed once into cache/code_engine/hyperframes at a pinned version.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from common import ROOT, StepError, read_json, write_json

STEPS = ["story", "voice", "scenes", "render"]
PINNED = {"hyperframes": "0.8.225", "gsap": "3.15.1", "three": "0.187.0"}
CACHE = ROOT / "cache" / "code_engine" / "hyperframes"
QUIET_ENV = {"HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1"}
PICTURE_DIRS = ("compositions", "assets")
PICTURE_FILES = ("story.json", "timing.json")
ALLOWED = ["Read", "Write", "Edit", "Glob", "Grep",
           "Bash(npx hyperframes check *)", "Bash(npx hyperframes lint *)",
           "Bash(npx hyperframes snapshot *)", "Bash(npx hyperframes timeline *)",
           "Bash(npx hyperframes catalog *)", "Bash(npx hyperframes add *)"]


def settings(config: dict) -> dict:
    h = dict(config.get("hyperframes") or {})
    h.setdefault("quality", "looks")           # draft | looks | delivery
    h.setdefault("scenes_max_turns", 160)
    h.setdefault("scenes_timeout_minutes", 120)
    h.setdefault("render_timeout_minutes", 30)
    return h


def env(base: dict | None = None) -> dict:
    """An environment with HyperFrames' telemetry switched off."""
    import code_engine as CE
    e = dict(base if base is not None else CE.tool_env({}))
    e.update(QUIET_ENV)
    return e


def _bin(folder: Path) -> Path:
    name = "hyperframes.cmd" if os.name == "nt" else "hyperframes"
    return folder / "node_modules" / ".bin" / name


def ensure_installed(config: dict) -> Path:
    """npm install the pinned CLI, gsap and three.js once into cache/code_engine/hyperframes, and fetch the
    headless Chrome it renders with. Returns the node_modules folder."""
    import code_engine as CE
    npm = CE.npm_path(config)
    if not npm:
        raise StepError("npm was not found; install Node.js 22+ (Windows: winget install OpenJS.NodeJS.LTS)")
    CACHE.mkdir(parents=True, exist_ok=True)
    pkg = json.dumps({"name": "vidgen-hyperframes", "private": True, "dependencies": PINNED}, indent=2) + "\n"
    stamp = CACHE / "package.json"
    ready = _bin(CACHE).is_file() and all((CACHE / "node_modules" / n).is_dir() for n in ("gsap", "three"))
    if not (ready and stamp.is_file() and stamp.read_text(encoding="utf-8") == pkg):
        stamp.write_text(pkg, encoding="utf-8")
        print(f"[code] installing HyperFrames {PINNED['hyperframes']} once into {CACHE}...")
        rc = CE._run_streamed([npm, "install", "--no-audit", "--no-fund"], CACHE, env(), "npm install", 20 * 60)
        if rc != 0 or not _bin(CACHE).is_file():
            raise StepError(f"installing HyperFrames failed (exit {rc}); see the log above")
        (CACHE / "browser.ok").unlink(missing_ok=True)
    if not (CACHE / "browser.ok").is_file():
        print("[code] fetching the headless Chrome HyperFrames renders with (once, a few minutes)...")
        rc = CE._run_streamed([str(_bin(CACHE)), "browser", "ensure"], CACHE, env(), "hyperframes browser", 20 * 60)
        if rc != 0:
            raise StepError(f"HyperFrames could not fetch its browser (exit {rc}); see the log above")
        (CACHE / "browser.ok").write_text("ok\n", encoding="utf-8")
    return CACHE / "node_modules"


def doctor_rows(config: dict) -> list[tuple[bool | None, str, str]]:
    import code_engine as CE
    node = CE.node_path(config)
    if not node:
        return []                      # the node row already says it is missing
    try:
        import subprocess
        ver = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
        major = int(ver.lstrip("v").split(".")[0])
    except (OSError, ValueError):
        return []
    if major < 22:
        return [(None, "node for HyperFrames", f"{ver}: the HyperFrames formats need Node.js 22 or newer")]
    if _bin(CACHE).is_file():
        return [(True, "hyperframes", f"{PINNED['hyperframes']} in {CACHE}")]
    return [(None, "hyperframes", "not installed yet; the first HyperFrames video installs it (a few minutes)")]


# ----------------------------------------------------------------- workspace ----

def _write_if_changed(path: Path, data) -> None:
    """write_json, but only when the contents change: a rewrite with the same contents must not
    look like a change to the picture (render_is_current compares times)."""
    try:
        if path.is_file() and read_json(path) == data:
            return
    except (OSError, ValueError):
        pass
    write_json(path, data)


def _copy_if_changed(src: Path, dest: Path) -> None:
    if dest.is_file() and dest.read_bytes() == src.read_bytes():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)


def prepare(ws: Path, skill: dict, config: dict, run_dir: Path) -> None:
    import code_engine as CE
    tpl = skill["template"]
    ws.mkdir(parents=True, exist_ok=True)
    modules = ensure_installed(config)
    CE._link_dir(modules, ws / "node_modules")
    _copy_if_changed(tpl / "hyperframes.json", ws / "hyperframes.json")
    if not (ws / "assets" / "theme.css").is_file():
        _copy_if_changed(tpl / "assets" / "theme.css", ws / "assets" / "theme.css")
    _copy_if_changed(modules / "gsap" / "dist" / "gsap.min.js", ws / "assets" / "vendor" / "gsap.min.js")
    for name in ("three.module.js", "three.core.js"):          # the toon look's 3D (MIT)
        if (modules / "three" / "build" / name).is_file():
            _copy_if_changed(modules / "three" / "build" / name, ws / "assets" / "vendor" / "three" / name)
    for src in sorted((tpl / "lib").glob("*.js")):
        _copy_if_changed(src, ws / "assets" / "lib" / src.name)
    wanted = set(skill.get("styles") or [])
    for src in sorted((tpl / "looks").glob("*.md")):      # the format's looks only
        if not wanted or src.stem in wanted:
            _copy_if_changed(src, ws / "looks" / src.name)
    for src in sorted((tpl / "examples").rglob("*.*")):
        _copy_if_changed(src, ws / "examples" / src.relative_to(tpl / "examples"))
    (ws / "compositions").mkdir(exist_ok=True)
    docs = modules / "hyperframes" / "dist" / "skills"
    for name in ("hyperframes", "hyperframes-cli", "hyperframes-registry"):
        if (docs / name).is_dir():
            shutil.copytree(docs / name, ws / "hf-docs" / name, dirs_exist_ok=True)
    for item in config.get("app_screens") or []:
        src = ROOT / str(item.get("path") or "")
        if src.is_file() and src.suffix.lower() in (".jpg", ".jpeg", ".png"):
            _copy_if_changed(src, ws / "assets" / "screens" / src.name)
        clip = ROOT / str(item.get("clip") or "")
        if item.get("clip") and clip.is_file() and clip.suffix.lower() == ".mp4":
            _copy_if_changed(clip, ws / "assets" / "screens" / clip.name)      # a real recording of the screen
    if (ROOT / "assets" / "app_icon.png").is_file():
        _copy_if_changed(ROOT / "assets" / "app_icon.png", ws / "assets" / "brand" / "app_icon.png")
    refs = ws / "refs"
    if refs.is_dir():
        for p in refs.iterdir():
            if p.is_file():
                _copy_if_changed(p, ws / "assets" / "cast" / p.name)
    write_project(run_dir, ws, config)


def screens_note(ws: Path, config: dict) -> str:
    lines = []
    for item in config.get("app_screens") or []:
        name = Path(str(item.get("path") or "")).name
        if (ws / "assets" / "screens" / name).is_file():
            clip = Path(str(item.get("clip") or "")).name
            rec = (f" (also a {item.get('seconds') or ''}s recording of it in use: assets/screens/{clip})"
                   if clip and (ws / "assets" / "screens" / clip).is_file() else "")
            lines.append(f"  - assets/screens/{name}: {item.get('shows') or 'an Iro app screen'}{rec}")
    if not lines:
        return ""
    brand = ("\nThe app's icon: assets/brand/app_icon.png. Iro, the mascot: assets/cast/iro.png."
             if (ws / "assets" / "brand" / "app_icon.png").is_file() else "")
    return ("Iro's real app screens (show the product only through these, never a made-up UI; the "
            "recordings are 860x1864, play them muted in a <video> with class \"clip\"):\n" + "\n".join(lines) + brand)


# ------------------------------------------------------------- the root page ----

def _music(run_dir: Path, ws: Path, config: dict) -> dict | None:
    """The run's track in assets/music.mp3 (cut at its start, at its speed) and its beats."""
    import music
    from media import run_ffmpeg
    m = music.for_run(run_dir, config)
    dest = ws / "assets" / "music.mp3"
    note = ws / "assets" / "music.json"
    if m["file"] is None:
        dest.unlink(missing_ok=True)
        note.unlink(missing_ok=True)
        return None
    key = {"track": str(m["file"]), "mtime": m["file"].stat().st_mtime, "start": m["start"], "speed": m["speed"]}
    old = read_json(note) if note.is_file() else {}
    if old.get("key") != key or not dest.is_file():
        rate = f"asetrate=44100*{m['speed']:.4f},aresample=44100," if abs(m["speed"] - 1) > 1e-3 else ""
        run_ffmpeg(["-ss", f"{m['start']:.3f}", "-i", str(m["file"]), "-vn", "-af", f"{rate}aformat=channel_layouts=stereo",
                    "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "192k", str(dest)], "music for HyperFrames")
        beats = _beats(ws, dest)
        old = {"key": key, "beats": beats}
        write_json(note, old)
    return {"file": "assets/music.mp3", "level": m["level"], "loud": m["loud"], "voices": m["voices"],
            "beats": old.get("beats") or {}, "title": m.get("title") or ""}


def _beats(ws: Path, track: Path) -> dict:
    import subprocess
    try:
        p = subprocess.run([str(_bin(CACHE)), "beats", str(track), "--json"], cwd=ws, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=300, env=env())
        data = json.loads(p.stdout[p.stdout.index("{"):])
        return {"bpm": data.get("bpm"), "times": [round(float(t), 3) for t in data.get("beatTimes") or []]}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def snap(beats: list[dict], grid: list[float], shortest: float = 0.5) -> list[dict]:
    """Each beat's end moved to the nearest beat of the music (no beat shorter than `shortest`),
    so every cut lands on the music. The first beat starts at 0."""
    out, at = [], 0.0
    for b in beats:
        want = at + float(b.get("seconds") or 2.0)
        choices = [t for t in grid if t >= at + shortest]
        end = min(choices, key=lambda t: abs(t - want)) if choices else want
        if abs(end - want) > 0.75 * float(b.get("seconds") or 2.0):
            end = want                                  # no beat near it: keep its own length
        out.append({**b, "seconds": round(end - at, 3)})
        at = end
    return out


def write_project(run_dir: Path, ws: Path, config: dict) -> dict:
    """timing.json and index.html from story.json, the voice and the music. Returns the timing."""
    import code_engine as CE
    story = CE.read_story(run_dir) if (ws / "story.json").is_file() else None
    beats = (story or {}).get("beats") or []
    fps = int(config["assemble"]["fps"])
    voiced = (ws / "voice.mp3").is_file() and CE.read_status(run_dir).get("voice", {}).get("value") == "voiced"
    if voiced:
        _copy_if_changed(ws / "voice.mp3", ws / "assets" / "voice.mp3")
    else:
        (ws / "assets" / "voice.mp3").unlink(missing_ok=True)
    words = []
    if voiced and (ws / "voice.json").is_file():
        try:
            words = [w for w in read_json(ws / "voice.json").get("words") or [] if isinstance(w.get("t"), (int, float))]
        except (OSError, ValueError, AttributeError):
            words = []
    music = _music(run_dir, ws, config) if beats else None
    grid = (music or {}).get("beats", {}).get("times") or []
    if beats and grid and not voiced and (CE.offered(config) or {}).get("snap_to_beats"):
        beats = snap(beats, grid)
        story["beats"] = beats
        _write_if_changed(ws / "story.json", story)     # the render and the captions use the same lengths
    out, at = [], 0.0
    for i, b in enumerate(beats, 1):
        secs = round(float(b.get("seconds") or 2.0), 3)
        mine = [{"w": str(w.get("say") or w.get("w")), "t": round(float(w["t"]) - at, 3)} for w in words
                if at <= float(w["t"]) < at + secs]
        out.append({"n": i, "id": f"beat_{i:02d}", "file": f"compositions/beat_{i:02d}.html",
                    "start": round(at, 3), "seconds": secs, "line": b.get("line", ""), "style": b.get("style", ""),
                    "words": mine})
        at += secs
    total = round(at, 3)
    timing = {"fps": fps, "width": 1080, "height": 1920, "total": total, "voice": voiced, "beats": out,
              "music": ({"bpm": music["beats"].get("bpm"), "beats": [t for t in music["beats"].get("times", []) if t < total]}
                        if music else None)}
    _write_if_changed(ws / "timing.json", timing)
    hosts = "\n".join(
        f'      <div id="{b["id"]}" data-composition-id="{b["id"]}" data-composition-src="{b["file"]}" '
        f'data-start="{b["start"]}" data-duration="{b["seconds"]}" data-track-index="1" data-track-kind="graphics" '
        f'data-width="1080" data-height="1920"></div>'
        for b in out)                                 # every beat, written yet or not: check names a missing one
    audio = []
    if voiced:
        audio.append(f'      <audio id="voice" class="clip" src="assets/voice.mp3" data-start="0" data-duration="{total}" '
                     f'data-track-index="10" data-volume="{1.0 * (music["voices"] if music else 1.0):.2f}"></audio>')
    if music:
        level = music["level"] if voiced else music["loud"]
        audio.append(f'      <audio id="music" class="clip" src="{music["file"]}" data-start="0" data-duration="{total}" '
                     f'data-track-index="11" data-volume="{level:.2f}" data-fade-out="0.8"></audio>')
    page = f"""<!doctype html>
<!-- Written by VidGen from story.json, the voice and the music. Do not edit: it is rewritten. -->
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="assets/vendor/gsap.min.js"></script>
    <link rel="stylesheet" href="assets/theme.css" />
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: 1080px; height: 1920px; overflow: hidden; background: var(--ground, #0d1820); }}
      #root {{ position: relative; width: 100%; height: 100%; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{max(total, 0.1)}" data-width="1080" data-height="1920">
{hosts}
{chr(10).join(audio)}
    </div>
    <script>
      window.__timelines["main"] = gsap.timeline({{ paused: true }});
    </script>
  </body>
</html>
"""
    if not (ws / "index.html").is_file() or (ws / "index.html").read_text(encoding="utf-8") != page:
        (ws / "index.html").write_text(page, encoding="utf-8")
    return timing


# -------------------------------------------------------------------- scenes ----

HEADLESS = (
    "You are running unattended inside VidGen, a video tool. Nobody can answer questions or "
    "approve anything, so never ask: make the call yourself and keep going. The current folder is "
    "this video's HyperFrames project. Read skill/SKILL.md first, all of it, then the files it "
    "names. Work only inside this folder. The commands you may run are `npx hyperframes check`, "
    "`lint`, `snapshot`, `timeline`, `catalog` and `add`, typed exactly like that, never chained "
    "with && or cd. Do not edit index.html or timing.json: VidGen writes them."
)


def scenes_prompt(run_dir: Path, config: dict, brief: str) -> str:
    timing = read_json(workspace_of(run_dir) / "timing.json")
    rows = "\n".join(f"  {b['id']}: {b['start']:.2f}s to {b['start'] + b['seconds']:.2f}s ({b['seconds']:.2f}s) "
                     f"[{b['style']}] {b['line']}" for b in timing["beats"])
    music = timing.get("music")
    sound = (f"The music: {music['bpm']} BPM, {len(music['beats'])} beats; timing.json has their times. Land "
             f"cuts and hits on them." if music and music.get("beats") else "There is no music track.")
    return "\n\n".join([
        HEADLESS,
        "THE BRIEF\n" + brief,
        "THE BEATS (from timing.json; the voice set their lengths)\n" + rows + "\n" + sound,
        "THIS STEP: WRITE THE SCENES\n"
        "1. Read skill/SKILL.md, skill/motion-rules/, hf-docs/hyperframes/SKILL.md, "
        "hf-docs/hyperframes/references/format.md and motion.md, the look in looks/, the brief's "
        "references, and examples/. Look at the pictures in assets/screens/ and assets/cast/ you use.\n"
        "2. Set the palette and type in assets/theme.css for the whole film.\n"
        "3. Write compositions/beat_NN.html for EVERY beat above, timed to its length. Plan the "
        "film first (what each beat shows, how one beat hands over to the next), in plan.md.\n"
        "4. `npx hyperframes check --json`; fix every error.\n"
        "5. `npx hyperframes snapshot --at <times>`: the middle and the end of every beat. Read the "
        "pictures and the contact sheet. Judge them against the look, the motion rules and the "
        "frame rules in SKILL.md. Fix and snapshot again; two or three rounds is normal.\n"
        "Finish with one short line per beat saying what it shows.",
    ])


def workspace_of(run_dir: Path) -> Path:
    return run_dir / "code"


def run_scenes(run_dir: Path, config: dict) -> None:
    import code_engine as CE
    ws = CE.prepare_workspace(run_dir, config)
    if CE.settings(config)["voice"] and config["format"]["rules"].get("narrator", True) \
            and "voice" not in CE.read_status(run_dir):
        print("[scenes] note: the voice has not been made yet, so the beats keep the story's first guess "
              "at their lengths. Run the voice step first for scenes timed to the voice.")
    h = settings(config)
    CE.run_claude(ws, config, scenes_prompt(run_dir, config, CE._brief(run_dir, config)), ALLOWED,
                  int(h["scenes_max_turns"]), "scenes", env=env(CE.claude_env()),
                  timeout_minutes=float(h["scenes_timeout_minutes"]))
    missing = [b["file"] for b in read_json(ws / "timing.json")["beats"] if not (ws / b["file"]).is_file()]
    write_project(run_dir, ws, config)               # mount the scenes that now exist
    if missing:
        raise StepError(f"Claude Code did not write {', '.join(missing)}; run the scenes step again")
    _stills(ws)
    CE._mark(run_dir, "scenes", "claude")
    print(f"[scenes] done; {len(list((ws / 'stills').glob('*.jpg')))} picture(s) in code/stills/")


def _stills(ws: Path) -> None:
    """The latest snapshots as code/stills/t<seconds>.jpg, for the video's page."""
    snaps = sorted((ws / ".hyperframes" / "artifacts" / "snapshots").glob("*"), key=lambda p: p.stat().st_mtime)
    if not snaps:
        return
    from PIL import Image
    out = ws / "stills"
    out.mkdir(exist_ok=True)
    for old in out.glob("t*.jpg"):
        old.unlink()
    for png in sorted(snaps[-1].glob("frame-*.png")):
        m = re.search(r"at-([\d.]+)s", png.name)
        if m:
            with Image.open(png) as im:
                im.convert("RGB").save(out / f"t{float(m.group(1)):g}.jpg", quality=85)


# -------------------------------------------------------------------- render ----

def signature(config: dict, audio: bool, run_dir: Path) -> dict:
    import music
    m = music.for_run(run_dir, config)
    return {"kind": "hyperframes", "audio": audio, "fps": int(config["assemble"]["fps"]),
            "quality": str(settings(config)["quality"]), "version": PINNED["hyperframes"],
            "music": [m["track"], m["level"], m["loud"], m["voices"], m["speed"], m["start"]] if m["file"] else None}


def picture_changed_at(ws: Path) -> float:
    times = [(ws / f).stat().st_mtime for f in PICTURE_FILES if (ws / f).is_file()]
    for d in PICTURE_DIRS:
        if (ws / d).is_dir():
            times += [p.stat().st_mtime for p in (ws / d).rglob("*") if p.is_file()]
    return max(times, default=0.0)


def render(run_dir: Path, config: dict, ws: Path, audio: bool) -> None:
    import code_engine as CE
    import progress
    from media import require_ffmpeg
    require_ffmpeg()
    timing = write_project(run_dir, ws, config)
    missing = [b["file"] for b in timing["beats"] if not (ws / b["file"]).is_file()]
    if missing:
        raise StepError(f"{', '.join(missing)} not written yet; run the scenes step first")
    h = settings(config)
    out = ws / "out" / "video.mp4"
    out.parent.mkdir(exist_ok=True)
    cmd = [str(_bin(CACHE)), "render", "--quality", str(h["quality"]), "--fps", str(timing["fps"]), "-o", "out/video.mp4"]
    print(f"[render] HyperFrames: {timing['total']:.1f}s at {timing['fps']} fps, {len(timing['beats'])} scenes"
          + (", with the voice" if timing["voice"] else "") + (", with the music" if timing.get("music") else ""))
    progress.plan(1)
    last = [""]

    def line(text: str) -> None:
        if text.strip():
            last[0] = text
            if re.search(r"render|✗|error|warn|rendered in|frame", text, re.I):
                print(f"  {text.strip()[:200]}")
    rc = CE._run_streamed(cmd, ws, env(), "hyperframes render", float(h["render_timeout_minutes"]) * 60, on_line=line)
    if rc != 0 or not out.is_file():
        raise StepError(f"HyperFrames could not render (exit {rc}): {last[0][:300]}")
    progress.tick()
