"""`python main.py doctor`: check that this machine can run VidGen, without calling any paid API."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import media
from common import KEY_ENV, ROOT, available_app_screens

STEP_KEYS = {  # which step needs which key
    "ANTHROPIC_API_KEY": "script", "ELEVENLABS_API_KEY": "voice",
    "FAL_KEY": "images/video on fal", "SUME_API_KEY": "images/video on Sume",
}


def _run(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return f"__error__ {e}"
    return proc.stdout + proc.stderr


def run_doctor(config: dict, key_sources: dict[str, str]) -> int:
    rows: list[tuple[str, str, str]] = []   # (PASS|FAIL|SKIP, item, detail)

    def add(ok: bool | None, item: str, detail: str) -> None:
        rows.append(("SKIP" if ok is None else "PASS" if ok else "FAIL", item, detail))

    v = sys.version_info
    add(v >= (3, 11), "python 3.11+", f"{v.major}.{v.minor}.{v.micro} at {sys.executable}")

    ffmpeg = media.tool_path("ffmpeg")
    ffprobe = media.tool_path("ffprobe")
    if ffmpeg:
        first = _run([ffmpeg, "-version"]).splitlines()[:1]
        add(True, "ffmpeg", f"{ffmpeg} ({first[0][:60] if first else 'version unknown'})")
        filters = _run([ffmpeg, "-hide_banner", "-filters"])
        encoders = _run([ffmpeg, "-hide_banner", "-encoders"])
        add(" ass " in filters, "ffmpeg captions (libass)",
            "ass filter available" if " ass " in filters else "this ffmpeg build has no libass; "
            "install a full build (Windows: winget install Gyan.FFmpeg)")
        add("libx264" in encoders, "ffmpeg H.264 encoder", "libx264" if "libx264" in encoders else "libx264 missing")
    else:
        add(False, "ffmpeg", f"'{config['ffmpeg_path']}' not found. Windows: winget install Gyan.FFmpeg, open a "
                             f"new terminal, or set ffmpeg_path in config.local.yaml")
    add(bool(ffprobe), "ffprobe", ffprobe or f"'{config['ffprobe_path']}' not found (it ships next to ffmpeg)")

    font_rel = str(config["assemble"].get("caption_font_file") or "")
    font = Path(font_rel) if Path(font_rel).is_absolute() else ROOT / font_rel
    if font_rel and font.is_file():
        from steps.assemble import font_names
        names = font_names(font)
        name = names.get(4) or names.get(1)
        add(bool(name), "caption font", f"{font_rel} ({name or 'unreadable name table'})")
    else:
        add(False, "caption font", f"{font_rel or '(assemble.caption_font_file not set)'} not found")

    providers = config["providers"]
    for var in KEY_ENV.values():
        source = key_sources.get(var, "missing")
        needed = (var not in ("FAL_KEY", "SUME_API_KEY")
                  or (var == "FAL_KEY" and "fal" in providers.values())
                  or (var == "SUME_API_KEY" and "sume" in providers.values()))
        present = bool(os.environ.get(var))
        if not needed and not present:
            add(None, var, f"not needed: no step uses {STEP_KEYS[var].split(' on ')[-1]}")
        else:
            add(present, var, f"from {source} ({STEP_KEYS[var]})" if present else
                f"missing, needed for {STEP_KEYS[var]}; add it to .env or keys: in config.local.yaml")

    for rel in ("assets/iro.png", "assets/app_icon.png"):
        add((ROOT / rel).is_file(), rel, "found" if (ROOT / rel).is_file() else "missing")

    listed = config.get("app_screens", [])
    found = available_app_screens(config)
    add(len(found) == len(listed), "app screenshots", f"{len(found)} of {len(listed)} listed files exist")
    try:
        import PIL  # noqa: F401
        add(True, "Pillow", "installed")
    except ImportError:
        add(False, "Pillow", "missing; pip install -r requirements.txt")

    out = Path(config["output_dir"])
    try:
        out.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=out, prefix=".doctor-", delete=True):
            pass
        add(True, "output dir writable", str(out))
    except OSError as e:
        add(False, "output dir writable", f"{out}: {e}")

    width = max(len(r[1]) for r in rows)
    print("\nVidGen doctor (no paid API calls; keys are checked for presence only)\n")
    for status, item, detail in rows:
        print(f"  {status:<4}  {item:<{width}}  {detail}")
    fails = sum(1 for r in rows if r[0] == "FAIL")
    print(f"\n{'all checks passed' if not fails else f'{fails} check(s) failed'}")
    return 1 if fails else 0
