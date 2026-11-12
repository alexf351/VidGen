"""Mixing sounds onto one track without an ffmpeg filter graph.

The voice lines, the sound effects, the music and the clips' own sound used to be mixed by one
ffmpeg command with an input per sound (forty or more) joined by `amix`. On some Windows
ffmpeg builds that command stops part of the way through and never finishes; the same command
runs in under a second elsewhere. So ffmpeg is now only asked to do what it does everywhere:
turn ONE file into a plain wav (`decode`). Putting the sounds at their places and adding them
up is done here, in plain Python, where nothing can wait on anything.

Everything is 44.1 kHz, stereo, 16 bit.
"""

from __future__ import annotations

import sys
import wave
from array import array
from operator import add
from pathlib import Path

from common import StepError

RATE = 44100
CHANNELS = 2


def decode(src: Path, dest: Path, label: str, seconds: float | None = None, filters: str = "",
           loop: bool = False) -> Path:
    """`src` (any sound or video file) as a plain wav at `dest`. `seconds` cuts it to that
    length, `filters` is an ffmpeg -af chain for this one file (a level, a fade), `loop` repeats
    the file for as long as `seconds` asks."""
    from media import run_ffmpeg
    args: list[str] = []
    if loop:
        args += ["-stream_loop", "-1"]
    args += ["-i", str(src), "-vn"]
    if filters:
        args += ["-af", filters]
    if seconds is not None:
        # A looped file comes out a little short of the length asked for (each pass through an
        # mp3 loses a few milliseconds), so ask for a little more; mix() cuts at the end anyway.
        args += ["-t", f"{max(0.01, seconds + (0.5 if loop else 0.0)):.3f}"]
    run_ffmpeg([*args, "-ar", str(RATE), "-ac", str(CHANNELS), "-c:a", "pcm_s16le", str(dest)], label)
    return dest


def read(path: Path) -> array:
    """The samples of a 44.1 kHz stereo 16 bit wav, left and right in turn."""
    try:
        with wave.open(str(path), "rb") as w:
            if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (RATE, CHANNELS, 2):
                raise StepError(f"{path.name} is not a 44.1 kHz stereo 16 bit wav")
            data = array("h")
            data.frombytes(w.readframes(w.getnframes()))
    except (wave.Error, EOFError, OSError) as e:
        raise StepError(f"{path.name} could not be read as a wav: {e}") from None
    if sys.byteorder == "big":
        data.byteswap()
    return data


def _clamp(v: int) -> int:
    return -32768 if v < -32768 else 32767 if v > 32767 else v


def mix(items: list[dict], total: float, out: Path) -> Path:
    """Write `out`: `total` seconds of sound with every item added at its place.

    An item is {"path": wav, "start": seconds into the track, "gain": level (default 1),
    "skip": seconds to leave off its beginning (default 0)}. Sound that would run past the end
    is cut off; sound louder than the track can hold is held at the limit, not wrapped."""
    n = max(1, int(round(total * RATE))) * CHANNELS
    track = array("i", bytes(4 * n))
    loaded: dict[tuple[str, float], array] = {}
    for it in items:
        gain = round(float(it.get("gain", 1.0)), 4)
        key = (str(it["path"]), gain)
        if key not in loaded:
            raw = loaded.get((key[0], 1.0)) or read(Path(it["path"]))
            loaded[(key[0], 1.0)] = raw
            loaded[key] = raw if gain == 1.0 else array("i", (int(v * gain) for v in raw))
        data = loaded[key]
        at = max(0, int(round(float(it["start"]) * RATE))) * CHANNELS
        skip = max(0, int(round(float(it.get("skip", 0.0)) * RATE))) * CHANNELS
        if at >= n or skip >= len(data):
            continue
        piece = data[skip:skip + (n - at)]
        track[at:at + len(piece)] = array("i", map(add, track[at:at + len(piece)], piece))
    if track and (max(track) > 32767 or min(track) < -32768):
        pcm = array("h", map(_clamp, track))
    else:
        pcm = array("h", track)
    if sys.byteorder == "big":
        pcm.byteswap()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return out
