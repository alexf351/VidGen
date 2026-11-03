"""ffmpeg / ffprobe helpers shared by the assembly step."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from common import StepError


def require_ffmpeg() -> None:
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        raise StepError(f"{' and '.join(missing)} not found on PATH; install ffmpeg "
                        "(https://ffmpeg.org/download.html) and retry")


def run_ffmpeg(args: list[str], label: str, cwd: Path | None = None) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        raise StepError(f"{label}: ffmpeg failed (exit {proc.returncode})\n{tail}")


def _probe(path: Path, entries: str, stream: str | None = None) -> str:
    cmd = ["ffprobe", "-v", "error"]
    if stream:
        cmd += ["-select_streams", stream]
    cmd += ["-show_entries", entries, "-of", "csv=p=0", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
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
