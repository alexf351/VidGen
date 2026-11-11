"""ffmpeg / ffprobe helpers shared by the assembly step."""

from __future__ import annotations

import atexit
import shutil
import subprocess
import threading
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


# Every ffmpeg that is running right now. A job that is cut off (the server is closed, the
# window is shut) must not leave one behind: on Windows an ffmpeg that lives on keeps every
# file it was reading open, and those files then cannot be renamed or replaced.
_live: set = set()
_live_lock = threading.Lock()


class _alive:
    def __init__(self, proc):
        self.proc = proc

    def __enter__(self):
        with _live_lock:
            _live.add(self.proc)
        return self.proc

    def __exit__(self, *exc):
        with _live_lock:
            _live.discard(self.proc)
        if exc[0] is not None and self.proc.poll() is None:      # interrupted: do not leave it running
            try:
                self.proc.kill()
            except OSError:
                pass
        return False


def stop_all() -> int:
    """End every ffmpeg still running (server shutdown, interpreter exit). Returns how many."""
    with _live_lock:
        procs = list(_live)
    n = 0
    for p in procs:
        if p.poll() is None:
            try:
                p.kill()
                n += 1
            except OSError:
                pass
    return n


atexit.register(stop_all)


# A long encode that reports no new frame for this long is taken to be stuck, and stopped.
STALL_SECONDS = 600


def run_ffmpeg(args: list[str], label: str, cwd: Path | None = None, on_progress=None) -> None:
    """Run ffmpeg. -nostdin and a closed stdin: ffmpeg must never wait on the keyboard of the
    window the server was started from.

    `on_progress(seconds)` is for the long encodes (the final mix, the outro): it is called with
    how many seconds of video are written so far, and an encode that stops advancing for
    STALL_SECONDS is killed with a clear error instead of sitting there for ever."""
    base = [tool_path("ffmpeg") or common.TOOLS["ffmpeg"], "-y", "-hide_banner", "-nostdin", "-loglevel", "error"]
    if on_progress is None:
        proc = subprocess.Popen([*base, *args], cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        with _alive(proc):
            _, err = proc.communicate()
        if proc.returncode != 0:
            tail = "\n".join((err or "").strip().splitlines()[-12:])
            raise StepError(f"{label}: ffmpeg failed (exit {proc.returncode})\n{tail}")
        return
    _run_watched([*base, "-nostats", "-progress", "pipe:1", *args], label, cwd, on_progress)


def _run_watched(cmd: list[str], label: str, cwd: Path | None, on_progress) -> None:
    import queue
    import tempfile
    import threading
    import time
    with tempfile.TemporaryFile() as errors:        # a file, so a chatty ffmpeg can never fill a pipe
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors,
                                text=True, encoding="utf-8", errors="replace")
        with _live_lock:
            _live.add(proc)
        lines: queue.Queue = queue.Queue()

        def read() -> None:
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)

        threading.Thread(target=read, daemon=True).start()
        best, moved = -1.0, time.monotonic()
        while True:
            try:
                line = lines.get(timeout=2)
            except queue.Empty:
                line = ""
            if line is None:
                break
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    done = int(line.split("=", 1)[1]) / 1_000_000      # both keys are microseconds
                except ValueError:
                    done = -1.0
                if done > best:
                    best, moved = done, time.monotonic()
                    try:
                        on_progress(done)
                    except Exception:
                        pass                                           # reporting must never stop the encode
            if time.monotonic() - moved > STALL_SECONDS:
                proc.kill()
                proc.wait()
                with _live_lock:
                    _live.discard(proc)
                raise StepError(f"{label}: ffmpeg wrote nothing new for {STALL_SECONDS // 60} minutes and was stopped. "
                                f"Run the step again; everything already made is kept.")
        code = proc.wait()
        with _live_lock:
            _live.discard(proc)
        if code != 0:
            errors.seek(0)
            text = errors.read().decode("utf-8", "replace")
            tail = "\n".join(text.strip().splitlines()[-12:])
            raise StepError(f"{label}: ffmpeg failed (exit {code})\n{tail}")


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
