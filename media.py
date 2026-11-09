"""ffmpeg / ffprobe helpers shared by the assembly step."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import common
from common import StepError

# ffmpeg writes UTF-8; never decode its output with the Windows code page.
_TEXT = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace"}


def tool_path(name: str) -> str | None:
    """Resolved path of ffmpeg/ffprobe (config ffmpeg_path, else PATH), or None if not found."""
    configured = common.TOOLS.get(name, name)
    found = shutil.which(configured)
    if found:
        return found
    p = Path(configured)
    return str(p) if p.is_file() else None


def require_ffmpeg() -> None:
    missing = [t for t in ("ffmpeg", "ffprobe") if tool_path(t) is None]
    if missing:
        where = ", ".join(f"{t} ({common.TOOLS.get(t, t)})" for t in missing)
        raise StepError(f"{where} not found. Install ffmpeg (Windows: winget install Gyan.FFmpeg, then "
                        f"open a new terminal) or set ffmpeg_path in config.local.yaml to the full path "
                        f"of ffmpeg.exe")


def run_ffmpeg(args: list[str], label: str, cwd: Path | None = None) -> None:
    cmd = [tool_path("ffmpeg") or common.TOOLS["ffmpeg"], "-y", "-hide_banner", "-loglevel", "error", *args]
    proc = subprocess.run(cmd, cwd=cwd, **_TEXT)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        raise StepError(f"{label}: ffmpeg failed (exit {proc.returncode})\n{tail}")


def _probe(path: Path, entries: str, stream: str | None = None) -> str:
    cmd = [tool_path("ffprobe") or common.TOOLS["ffprobe"], "-v", "error"]
    if stream:
        cmd += ["-select_streams", stream]
    cmd += ["-show_entries", entries, "-of", "csv=p=0", str(path)]
    proc = subprocess.run(cmd, **_TEXT)
    if proc.returncode != 0:
        raise StepError(f"ffprobe failed on {path}: {proc.stderr.strip()[-300:]}")
    return proc.stdout.strip()


def probe_duration(path: Path) -> float:
    out = _probe(path, "format=duration")
    try:
        return float(out.splitlines()[0])
    except (ValueError, IndexError):
        raise StepError(f"could not read duration of {path}") from None


def has_audio_stream(path: Path) -> bool:
    return bool(_probe(path, "stream=codec_type", stream="a"))


def has_video_stream(path: Path) -> bool:
    return bool(_probe(path, "stream=codec_type", stream="v"))
