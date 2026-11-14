"""Blender 3D on the Claude Code engine (formats whose code_render.kind is "blender").

The run's code folder holds a copy of skills/blender-3d/template: studio.py (the toolkit),
beat.py (builds and renders one beat inside Blender), preview.py (the one command Claude Code
may run) and looks/. Claude Code writes cast.py and scenes/beat_NN.py.

    story    as for the other code formats: story.json, one line and one look per beat
    scenes   four Claude Code sessions, one per pass: blockout, bevel, material, final. In each
             it edits the scenes, previews them (`python preview.py <beat> <pass>`), reads the
             census and the picture, and fixes what it finds
    voice    as for the other code formats
    render   Blender renders every frame of every beat (Cycles, on the graphics card when there
             is one), ffmpeg joins them and adds the voice, then the captions go on

Without a graphics card a 20 second video would take hours, so "mode: auto" renders one still
per beat instead and moves it with a push-in. Settings live under `blender:` in config.yaml.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from common import ROOT, StepError, read_json, write_json

PASSES = ("blockout", "bevel", "material", "final")
GPU_KINDS = ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL")
# Copied from the skill on every step, so a fix to the toolkit reaches runs made before it.
# Claude Code is told not to edit them.
TOOL_FILES = ("studio.py", "beat.py", "preview.py")
PICTURE_FILES = ("story.json", "voice.mp3", "voice.json", "studio.py", "beat.py", "cast.py")
PICTURE_DIRS = ("scenes", "looks")
DEVICE_CACHE = ROOT / "cache" / "code_engine" / "blender_devices.json"


def settings(config: dict) -> dict:
    b = dict(config.get("blender") or {})
    b.setdefault("path", "")
    b.setdefault("device", "auto")          # auto (the graphics card if there is one) | GPU | CPU
    b.setdefault("engine", "cycles")        # cycles | eevee
    b.setdefault("mode", "auto")            # auto (animate on a card, stills without) | animate | stills
    b.setdefault("fps", 24)
    b.setdefault("final_res", "1080x1920")
    b.setdefault("final_samples", 48)
    b.setdefault("preview_res", "540x960")
    b.setdefault("preview_samples", 24)
    b.setdefault("preview_timeout_s", 600)
    b.setdefault("blockout_max_turns", 150)  # the first pass writes every scene
    b.setdefault("pass_max_turns", 90)       # the other three adjust them
    b.setdefault("pass_timeout_minutes", 120)
    return b


# ------------------------------------------------------------------- blender ----

def find_blender(config: dict) -> str | None:
    """blender.path, else `blender` on PATH, else the usual install folders (newest first)."""
    want = settings(config)["path"]
    if want:
        p = Path(want).expanduser()
        return str(p) if p.is_file() else shutil.which(want)
    found = shutil.which("blender")
    if found:
        return found
    pats = ["C:/Program Files/Blender Foundation/Blender */blender.exe",
            "/Applications/Blender.app/Contents/MacOS/Blender",
            str(Path.home() / "AppData/Local/Programs/Blender Foundation/Blender */blender.exe")]
    hits = [h for pat in pats for h in glob.glob(pat)]

    def version(path: str) -> tuple:
        m = re.search(r"Blender (\d+)\.(\d+)", path)
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    return max(hits, key=version) if hits else None


def blender_version(exe: str) -> tuple[str, tuple[int, int]]:
    """("Blender 5.2.4 LTS", (5, 2)), or ("", (0, 0)) when it will not run."""
    try:
        out = subprocess.run([exe, "--background", "--factory-startup", "--version"], capture_output=True,
                             text=True, timeout=120, encoding="utf-8", errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return "", (0, 0)
    m = re.search(r"Blender (\d+)\.(\d+)[^\n]*", out or "")
    return (m.group(0).strip(), (int(m.group(1)), int(m.group(2)))) if m else ("", (0, 0))


_PROBE = """
import bpy, json
found = {}
prefs = bpy.context.preferences.addons["cycles"].preferences
for kind in %r:
    try:
        prefs.compute_device_type = kind
        prefs.get_devices()
        names = [d.name for d in prefs.devices if d.type == kind]
        if names:
            found[kind] = names
    except Exception:
        pass
print("DEVICES " + json.dumps(found))
"""


def gpus(exe: str) -> dict[str, list[str]]:
    """{"OPTIX": ["NVIDIA GeForce RTX 4070"], "CUDA": [...]}: what Cycles can render on. Asked
    of Blender once per Blender install and remembered."""
    try:
        key = f"{exe}|{os.path.getmtime(exe)}"
    except OSError:
        return {}
    try:
        cached = read_json(DEVICE_CACHE)
        if cached.get("key") == key:
            return cached.get("devices") or {}
    except (OSError, ValueError, AttributeError):
        pass
    probe = DEVICE_CACHE.with_name("probe_devices.py")
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text(_PROBE % (GPU_KINDS,), encoding="utf-8")
    try:
        out = subprocess.run([exe, "--background", "--factory-startup", "--python", str(probe)],
                             capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace").stdout
        line = next((ln for ln in (out or "").splitlines() if ln.startswith("DEVICES ")), "DEVICES {}")
        found = json.loads(line[len("DEVICES "):])
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    write_json(DEVICE_CACHE, {"key": key, "devices": found})
    return found


def device(config: dict, exe: str) -> str:
    """The Cycles device kind to render on: OPTIX, CUDA, HIP, ONEAPI, METAL or CPU."""
    want = str(settings(config)["device"]).upper()
    if want == "CPU":
        return "CPU"
    found = gpus(exe)
    for kind in GPU_KINDS:
        if found.get(kind):
            return kind
    if want == "GPU":
        print("[blender] blender.device is GPU, but Blender found no graphics card it can render on; using the CPU")
    return "CPU"


def mode(config: dict, dev: str) -> str:
    m = str(settings(config)["mode"]).lower()
    if m in ("animate", "stills"):
        return m
    return "animate" if dev != "CPU" else "stills"


def doctor_rows(config: dict) -> list[tuple[bool | None, str, str]]:
    need = " (only needed for the Blender 3D format)"
    exe = find_blender(config)
    if not exe:
        return [(None, "blender", "not found" + need + ". Install Blender 5.2 LTS from blender.org "
                 "(Windows: winget install BlenderFoundation.Blender), or set blender.path in config.local.yaml")]
    name, ver = blender_version(exe)
    if not name:
        return [(False, "blender", f"{exe} did not run")]
    rows = [((ver >= (4, 2)) or False, "blender", f"{exe} ({name})" + ("" if ver >= (5, 0) else
             "; the toolkit is written for 5.2 LTS, so some scenes may fail on this version"))]
    found = gpus(exe)
    best = next((k for k in GPU_KINDS if found.get(k)), None)
    if best:
        rows.append((True, "blender graphics card", f"{best}: {', '.join(found[best])} (full animation)"))
    else:
        rows.append((None, "blender graphics card", "none found: Blender 3D videos render one still per beat "
                     "with a push-in (every frame on a CPU would take hours)"))
    return rows


# ----------------------------------------------------------------- workspace ----

def _copy_if_changed(src: Path, dest: Path) -> None:
    if dest.is_file() and dest.read_bytes() == src.read_bytes():
        return                       # keep its time: an unchanged toolkit must not force a new render
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)


def prepare(ws: Path, skill: dict, config: dict) -> None:
    """The template in the run's code folder, blender.json, and Iro's app screens in refs/screens."""
    tpl = skill["template"]
    ws.mkdir(parents=True, exist_ok=True)
    for name in TOOL_FILES:
        _copy_if_changed(tpl / name, ws / name)
    for src in sorted((tpl / "looks").glob("*.py")):
        if not (ws / "looks" / src.name).is_file():         # a look Claude extended stays as it is
            _copy_if_changed(src, ws / "looks" / src.name)
    if not (ws / "cast.py").is_file():
        shutil.copyfile(tpl / "cast.py", ws / "cast.py")
    (ws / "scenes").mkdir(exist_ok=True)
    for src in sorted((tpl / "scenes").glob("*.py")):        # examples to read, never rendered
        _copy_if_changed(src, ws / "examples" / "scenes" / src.name)
    _copy_if_changed(tpl / "story.json", ws / "examples" / "story.json")
    _copy_if_changed(tpl / "cast.py", ws / "examples" / "cast.py")
    for item in config.get("app_screens") or []:
        src = ROOT / str(item.get("path") or "")
        if src.is_file() and src.suffix.lower() in (".jpg", ".jpeg", ".png"):
            _copy_if_changed(src, ws / "refs" / "screens" / src.name)
    write_blender_json(ws, config)


def write_blender_json(ws: Path, config: dict) -> dict:
    exe = find_blender(config)
    b = settings(config)
    data = {"blender": exe or "", "device": device(config, exe) if exe else "CPU",
            "engine": "EEVEE" if str(b["engine"]).lower().startswith("eevee") else "CYCLES",
            "fps": int(b["fps"]), "preview_res": str(b["preview_res"]),
            "preview_samples": int(b["preview_samples"]), "preview_timeout_s": int(b["preview_timeout_s"])}
    write_json(ws / "blender.json", data)
    return data


def screens_note(ws: Path, config: dict) -> str:
    lines = []
    for item in config.get("app_screens") or []:
        name = Path(str(item.get("path") or "")).name
        if (ws / "refs" / "screens" / name).is_file():
            lines.append(f"  - refs/screens/{name}: {item.get('shows') or 'an Iro app screen'}")
    return ("Iro's real app screens, for a phone in a hand (S.image_plane):\n" + "\n".join(lines)) if lines else ""


# -------------------------------------------------------------------- scenes ----

HEADLESS = (
    "You are running unattended inside VidGen, a video tool. Nobody can answer questions or "
    "approve anything, so never ask: make the call yourself and keep going. The current folder is "
    "this video's Blender project. The instructions are skill/SKILL.md (read it first, all of it) "
    "and skill/copywriter.md. examples/ has a worked example of a cast and three scenes, one per "
    "look. Work only inside this folder. The one command you may run is `python preview.py ...`, "
    "exactly like that, never chained with && or cd. Do not edit studio.py, beat.py or preview.py."
)

PASS_FOCUS = {
    "blockout": "silhouette, proportion, pose and framing in grey: does every beat read with the "
                "sound off, is the subject big enough in a tall phone frame, does the cast look the "
                "same in every beat, does every beat move",
    "bevel": "edge highlights, and anything that looks pinched, melted or collapsed",
    "material": "palette and finish: one main colour, an accent, a few neutrals, and roughness that "
                "varies so nothing looks like plastic",
    "final": "light balance, exposure and framing at the start and the end of each beat's movement "
             "(--t), and anything hidden, blown out or overlapping",
}


def pass_prompt(run_dir: Path, config: dict, stage: str, brief: str) -> str:
    n = PASSES.index(stage) + 1
    steps = []
    if stage == "blockout":
        steps.append(
            "story.json and story.md are final; read them and skill/motion-rules/README.md (the motion "
            "rules every video follows), then look at refs/ (the cast's pictures). "
            "Write cast.py (every character or prop that appears in more than one beat) and "
            "scenes/beat_NN.py for EVERY beat in story.json (beat_01.py, beat_02.py, ...), using the "
            "beat's look (its style). Before writing a scene, list its parts with their sizes in cm "
            "and positions in a comment at the top of the file. Give every hard part a bevel= width and "
            "every part its material now, even though this pass shows clay and no bevels: the later "
            "passes switch them on.")
    else:
        steps.append(
            f"The scenes exist and passed the earlier passes. Keep every part, every name and the "
            f"structure; change numbers and add what this pass needs.")
    steps.append(
        f"For each beat: `python preview.py <beat> {stage}`, read the REPORT line and the picture. "
        f"The census must read zero; fix that first. Then judge this pass only: {PASS_FOCUS[stage]}. "
        f"Make at most five fixes per beat, preview again, and stop when it is right (two or three "
        f"rounds is normal).")
    if stage == "final":
        steps.append("Also preview each beat at --t 0.1 and near its end, so the whole movement is "
                     "seen. End with `python preview.py all final`.")
    steps.append(f"Finish with one short line per beat saying what it shows and what you changed in this pass.")
    return "\n\n".join([
        HEADLESS,
        "THE BRIEF\n" + brief,
        f"THIS STEP: PASS {n} OF 4, {stage.upper()}\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)),
    ])


def claude_env() -> dict:
    """Claude Code's environment, with this Python first on PATH so `python preview.py` works."""
    import code_engine
    env = code_engine.claude_env()
    env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), env.get("PATH", "")])
    return env


def run_scenes(run_dir: Path, config: dict) -> None:
    """The four passes, each its own Claude Code session. A run stopped part way (a usage limit)
    starts again at the pass it stopped in; a finished one starts again at the blockout."""
    import code_engine as CE
    ws = CE.prepare_workspace(run_dir, config)
    if not find_blender(config):
        raise StepError("Blender was not found. Install Blender 5.2 LTS from blender.org (Windows: "
                        "winget install BlenderFoundation.Blender), or set blender.path in config.local.yaml")
    b = settings(config)
    st = CE.read_status(run_dir)
    done = [] if "scenes" in st else list((st.get("scenes_passes") or {}).get("value") or [])
    brief = CE._brief(run_dir, config)
    allowed = ["Read", "Write", "Edit", "Glob", "Grep", "Bash(python preview.py *)"]
    for stage in PASSES:
        if stage in done:
            print(f"[scenes] pass {stage}: done earlier")
            continue
        turns = b["blockout_max_turns"] if stage == "blockout" else b["pass_max_turns"]
        print(f"\n[scenes] pass {PASSES.index(stage) + 1} of 4: {stage}")
        CE.run_claude(ws, config, pass_prompt(run_dir, config, stage, brief), allowed, int(turns),
                      "scenes", env=claude_env(), timeout_minutes=float(b["pass_timeout_minutes"]))
        done.append(stage)
        CE._mark(run_dir, "scenes_passes", done)
    CE._mark(run_dir, "scenes", "claude", clear=("voice", "scenes_passes"))
    print(f"[scenes] done; {len(list((ws / 'stills').glob('*.jpg')))} preview(s) in code/stills/")


# -------------------------------------------------------------------- render ----

def signature(config: dict, audio: bool) -> dict:
    """What a render depends on besides the files: a change re-renders."""
    b = settings(config)
    exe = find_blender(config)
    dev = device(config, exe) if exe else "CPU"
    return {"kind": "blender", "audio": audio, "mode": mode(config, dev), "res": str(b["final_res"]),
            "samples": int(b["final_samples"]), "fps": int(b["fps"]),
            "engine": "EEVEE" if str(b["engine"]).lower().startswith("eevee") else "CYCLES"}


def picture_changed_at(ws: Path) -> float:
    times = [(ws / f).stat().st_mtime for f in PICTURE_FILES if (ws / f).is_file()]
    for d in PICTURE_DIRS:
        if (ws / d).is_dir():
            times += [p.stat().st_mtime for p in (ws / d).rglob("*.py")]
    return max(times, default=0.0)


def _blender_cmd(exe: str, beat: int, extra: list[str]) -> list[str]:
    return [exe, "--background", "--factory-startup", "--python-exit-code", "1", "--python", "beat.py",
            "--", "--beat", str(beat), *extra]


def _run_blender(cmd: list[str], ws: Path, label: str, timeout_s: float, on_frame=None) -> None:
    import code_engine as CE
    tail: list[str] = []

    def line(text: str) -> None:
        tail.append(text)
        del tail[:-30]
        if text.startswith("FRAME ") and on_frame:
            on_frame(text)
        elif text.startswith("REPORT "):
            try:
                data = json.loads(text[7:])
                c = data.get("census") or {}
                bad = {k: v for k, v in c.items() if k not in ("objects", "triangles", "where") and v}
                print(f"  {label}: {c.get('objects', 0)} objects, {c.get('triangles', 0):,} triangles"
                      + (f", census {bad} in {c.get('where')}" if bad else "")
                      + (f", {data.get('render_seconds')}s on {data.get('device')}" if data.get("render_seconds") else ""))
            except ValueError:
                pass
    rc = CE._run_streamed(cmd, ws, CE.tool_env({}), label, timeout_s, on_line=line)
    if rc != 0:
        keep = [t for t in tail if t.strip() and "CUEW" not in t and "HIPEW" not in t]
        raise StepError(f"{label}: Blender failed (exit {rc}):\n" + "\n".join(keep[-15:]))


def render(run_dir: Path, config: dict, ws: Path, audio: bool) -> None:
    """ws/out/video.mp4: every beat rendered and joined, with the voice."""
    import code_engine as CE
    import progress
    from media import require_ffmpeg, run_ffmpeg
    require_ffmpeg()
    exe = find_blender(config)
    if not exe:
        raise StepError("Blender was not found; install Blender 5.2 LTS or set blender.path in config.local.yaml")
    b = settings(config)
    sig = signature(config, audio)
    dev = device(config, exe)
    story = CE.read_story(run_dir)
    beats = story["beats"]
    fps, w_h = int(b["fps"]), str(b["final_res"])
    w, h = (int(x) for x in w_h.lower().split("x"))
    common_args = ["--stage", "final", "--res", w_h, "--samples", str(sig["samples"]), "--fps", str(fps),
                   "--device", dev, "--engine", sig["engine"]]
    out = ws / "out"
    out.mkdir(exist_ok=True)
    total_frames = sum(max(1, round(float(x["seconds"]) * fps)) for x in beats)
    how = (f"every frame ({total_frames} at {fps} fps, {w_h}, {sig['samples']} samples)" if sig["mode"] == "animate"
           else f"one still per beat with a push-in ({len(beats)} stills, {w_h}, {sig['samples']} samples)")
    print(f"[render] Blender on {dev if dev == 'CPU' else dev + ' (graphics card)'}: {how}")
    if sig["mode"] == "stills" and str(b["mode"]).lower() == "auto":
        print("  no graphics card, so each beat is one still that moves; set blender.mode: animate to "
              "render every frame anyway (hours on a CPU)")
    progress.plan(len(beats) + 1)
    timeout = float(CE.settings(config)["render_timeout_minutes"]) * 60
    changed_at = picture_changed_at(ws)
    parts = []
    done_frames = [0]
    for i, beat in enumerate(beats, 1):
        n = max(1, round(float(beat["seconds"]) * fps))
        label = f"beat {i}/{len(beats)}"
        if sig["mode"] == "animate":
            folder = ws / "frames" / f"b{i:02d}"
            stamp = folder / "stamp.json"
            keep = stamp.is_file() and stamp.stat().st_mtime >= changed_at and _same(stamp, {**sig, "frames": n})
            if folder.is_dir() and not keep:
                shutil.rmtree(folder)                 # the scene or the settings changed: start the beat over
            folder.mkdir(parents=True, exist_ok=True)
            write_json(stamp, {**sig, "frames": n})
            have = len(list(folder.glob("[0-9][0-9][0-9][0-9].png")))
            print(f"  {label}: {n} frames" + (f" ({have} already rendered)" if have else ""))

            def frame(text: str, i=i, n=n) -> None:
                done_frames[0] += 1
                m = re.match(r"FRAME (\d+)/(\d+)", text)
                if m:
                    pct = int(int(m.group(1)) / n * 100)
                    progress.note(f"beat {i}/{len(beats)} {pct}%")
                    if int(m.group(1)) % max(1, n // 4) == 0 or int(m.group(1)) == n:
                        print(f"    {text}")
            _run_blender(_blender_cmd(exe, i, ["--mode", "frames", "--out", f"frames/b{i:02d}", *common_args]),
                         ws, label, timeout, on_frame=frame)
            clip = out / f"b{i:02d}.mp4"
            run_ffmpeg(["-framerate", str(fps), "-i", f"frames/b{i:02d}/%04d.png", "-frames:v", str(n),
                        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                        "-r", str(fps), f"out/b{i:02d}.mp4"], f"{label} encode", cwd=ws)
        else:
            still = f"frames/b{i:02d}_still.png"
            (ws / "frames").mkdir(exist_ok=True)
            print(f"  {label}: one still, {float(beat['seconds']):.2f}s")
            _run_blender(_blender_cmd(exe, i, ["--mode", "still", "--out", still, *common_args]), ws, label, timeout)
            clip = out / f"b{i:02d}.mp4"
            from steps.assemble import _push_in
            _push_in(ws / still, clip, n, 1.06, {"width": w, "height": h, "fps": fps}, f"{label} push-in")
        parts.append(clip)
        progress.tick()
    (out / "parts.txt").write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", "parts.txt", "-c", "copy", "joined.mp4"], "join the beats", cwd=out)
    final = out / "video.mp4"
    if audio:
        run_ffmpeg(["-i", "joined.mp4", "-i", "../voice.mp3", "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "video.mp4"], "add the voice", cwd=out)
    else:
        shutil.copyfile(out / "joined.mp4", final)
    progress.tick()
    print(f"[render] {len(beats)} beats joined -> {final.relative_to(run_dir)}")


def _same(path: Path, data: dict) -> bool:
    try:
        return read_json(path) == data
    except (OSError, ValueError):
        return False
