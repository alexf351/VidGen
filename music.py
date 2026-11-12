"""Music under a video: your own tracks, and how loud everything is.

    assets/music/               the tracks you added (in the UI, or dropped in by hand);
                                index.json holds their titles. Not in git.

A video chooses a track and its levels in run.json:

    "music": {
      "track": "legacy_slowed.mp3",   # a file in assets/music/; "" = no music
      "level": 0.10,                  # the music while people talk (1 = as loud as the file)
      "loud": 0.60,                   # the music from the montage to the end
      "voices": 1.0,                  # the voices and the clips' own sound
      "speed": 1.0,                   # 0.85 = the slowed version (the pitch drops with it)
      "start": 0.0                    # seconds into the track where the music begins
    }

The stories this tool copies keep one song quiet under the talking and bring it up when the
montage starts. That is what `level` and `loud` are: the assemble step raises the music from
one to the other over the half second before the first montage shot, and fades it out at the
end. A script with no montage plays the track at `level` all the way.

A video with no "music" block uses `music_path` and `assemble.music_volume` from the config,
as before. A new video starts with the settings you marked "use for new videos".

Nothing here downloads music. A track is a file you have: an mp3, wav, m4a, ogg or flac, or a
video file whose sound is used.
"""

from __future__ import annotations

import re
from pathlib import Path

import threading

from common import ROOT, StepError, read_json, write_json

_LOCK = threading.RLock()     # one change at a time to run.json's music block and to the track list

MUSIC_DIR = ROOT / "assets" / "music"
INDEX = MUSIC_DIR / "index.json"
SOUNDS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac")
VIDEOS = (".mp4", ".mov", ".m4v", ".webm")            # a video's sound can be the track
MAX_UPLOAD_BYTES = 40 * 1024 * 1024
RAMP = 0.5                    # seconds the music takes to come up, ending on the montage's first frame
FADE_OUT = 0.8                # seconds of fade at the end of the video

# name: (default, lowest, highest)
LEVELS = {
    "level": (0.10, 0.0, 1.0),
    "loud": (0.60, 0.0, 1.5),
    "voices": (1.0, 0.0, 2.0),
    "speed": (1.0, 0.5, 1.5),
    "start": (0.0, 0.0, 3600.0),
}


# ------------------------------------------------------------------ the tracks ----

def _index() -> dict:
    try:
        data = read_json(INDEX)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_index(data: dict) -> None:
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    write_json(INDEX, data)


def _title_from(name: str) -> str:
    words = re.sub(r"[_\-]+", " ", Path(name).stem).strip()
    return words[:1].upper() + words[1:] if words else "Track"


def file_for(name: str) -> Path | None:
    """The file of a track of yours, or None. Only a plain file name inside assets/music/."""
    name = str(name or "")
    if not name or name != Path(name).name or name.startswith(".") or Path(name).suffix.lower() not in SOUNDS + VIDEOS:
        return None
    p = MUSIC_DIR / name
    return p if p.is_file() else None


def tracks() -> list[dict]:
    """Your tracks, by title: [{"name", "title", "seconds"}]. A file dropped into the folder by
    hand is listed too, named after its file."""
    if not MUSIC_DIR.is_dir():
        return []
    known = _index().get("tracks")
    known = known if isinstance(known, dict) else {}
    out = []
    for p in MUSIC_DIR.iterdir():
        if not p.is_file() or p.name.startswith(".") or p.suffix.lower() not in SOUNDS + VIDEOS:
            continue
        meta = known.get(p.name) if isinstance(known.get(p.name), dict) else {}
        seconds = meta.get("seconds")
        if not isinstance(seconds, (int, float)):
            seconds = _seconds(p)
        out.append({"name": p.name, "title": str(meta.get("title") or _title_from(p.name)), "seconds": seconds})
    return sorted(out, key=lambda t: (t["title"].lower(), t["name"]))


def _seconds(path: Path) -> float | None:
    try:
        from media import probe_duration
        return round(float(probe_duration(path)), 2)
    except Exception:
        return None


def add(title: str, filename: str, data: bytes) -> dict:
    """Keep an uploaded track. `filename` is only read for its ending (.mp3, .mp4 ...); the
    file is stored under a name made from the title. It has to hold sound that ffmpeg can read."""
    from media import has_audio_stream
    ext = Path(str(filename or "")).suffix.lower()
    if ext not in SOUNDS + VIDEOS:
        raise StepError("that file type is not supported: use an mp3, wav, m4a, ogg or flac, or a video file (mp4, mov, webm)")
    if not data:
        raise StepError("the file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise StepError(f"the file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    title = " ".join(str(title or "").split())[:60] or _title_from(str(filename or "track"))
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40] or "track"
    taken = {p.stem for p in MUSIC_DIR.iterdir()}
    stem, n = slug, 2
    while stem in taken or stem == "index":
        stem, n = f"{slug}_{n}", n + 1
    path = MUSIC_DIR / f"{stem}{ext}"
    path.write_bytes(data)
    try:
        ok = has_audio_stream(path)
    except Exception:
        ok = False
    seconds = _seconds(path) if ok else None
    if not ok or not seconds:
        path.unlink(missing_ok=True)
        raise StepError("no sound could be read from that file")
    with _LOCK:
        index = _index()
        index.setdefault("tracks", {})[path.name] = {"title": title, "seconds": seconds}
        _save_index(index)
    return {"name": path.name, "title": title, "seconds": seconds}


def remove(name: str) -> None:
    path = file_for(name)
    if path is None:
        raise StepError(f"no track named {name}")
    path.unlink()
    with _LOCK:
        index = _index()
        if isinstance(index.get("tracks"), dict):
            index["tracks"].pop(name, None)
        if isinstance(index.get("default"), dict) and index["default"].get("track") == name:
            index.pop("default", None)                 # new videos cannot start with a track that is gone
        _save_index(index)


# ------------------------------------------------------------------ a video's choice ----

def check(raw) -> dict:
    """A "music" block, checked: every level a number inside its range, the track a file of
    yours or "". Missing levels take their defaults."""
    if not isinstance(raw, dict):
        raise StepError("music must be a block with track, level, loud, voices, speed, start")
    unknown = sorted(set(raw) - {"track", *LEVELS})
    if unknown:
        raise StepError(f"music has unknown keys {unknown}; use track, level, loud, voices, speed, start")
    track = raw.get("track") or ""
    if not isinstance(track, str):
        raise StepError("music.track must be the name of a track, or empty for no music")
    if track and file_for(track) is None:
        raise StepError(f"there is no track named {track}")
    out: dict = {"track": track}
    for key, (default, low, high) in LEVELS.items():
        value = raw.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise StepError(f"music.{key} must be a number")
        if not low <= float(value) <= high:
            raise StepError(f"music.{key} must be between {low:g} and {high:g}")
        out[key] = round(float(value), 3)
    return out


def default() -> dict | None:
    """The settings a new video starts with ("use for new videos"), or None."""
    raw = _index().get("default")
    if not isinstance(raw, dict):
        return None
    try:
        return check(raw)
    except StepError:
        return None                                    # its track was deleted by hand


def set_default(raw: dict | None) -> dict | None:
    with _LOCK:
        index = _index()
        if raw is None:
            index.pop("default", None)
        else:
            index["default"] = check(raw)
        _save_index(index)
        return default()


def run_choice(run_dir: Path) -> dict | None:
    """This video's own "music" block, checked, or None when it has none (or it no longer
    holds: its track was deleted)."""
    try:
        raw = read_json(Path(run_dir) / "run.json").get("music")
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return check(raw)
    except StepError:
        try:
            return check({**raw, "track": ""})         # the levels still hold; the track is gone
        except StepError:
            return None


def set_for_run(run_dir: Path, raw: dict | None) -> dict | None:
    """Save this video's music block (None goes back to the config's)."""
    path = Path(run_dir) / "run.json"
    with _LOCK:                                        # two saves at once must not read a half-written file
        meta = read_json(path)
        if raw is None:
            meta.pop("music", None)
        else:
            meta["music"] = check(raw)
        write_json(path, meta)
        return run_choice(run_dir)


def for_run(run_dir: Path | None, config: dict) -> dict:
    """What the assemble step plays: {"file": Path or None, "track", "title", "level", "loud",
    "voices", "speed", "start", "own": does this video have its own block}."""
    mine = run_choice(run_dir) if run_dir is not None else None
    if mine is not None:
        path = file_for(mine["track"]) if mine["track"] else None
        title = next((t["title"] for t in tracks() if t["name"] == mine["track"]), "") if path else ""
        return {**mine, "file": path, "title": title, "own": True}
    # No block of its own: the config's music bed, at one level all the way, as it always was.
    rel = str(config.get("music_path") or "").strip()
    path = (ROOT / rel) if rel else None
    if path is not None and not path.exists():
        print(f"  music: {rel} not found, skipping the music bed")
        path = None
    level = float((config.get("assemble") or {}).get("music_volume", LEVELS["level"][0]))
    return {"track": "", "file": path, "title": _title_from(rel) if path else "", "level": level, "loud": level,
            "voices": 1.0, "speed": 1.0, "start": 0.0, "own": False}


# ------------------------------------------------------------------ for ffmpeg ----

def loud_from(plan: list[dict]) -> float | None:
    """When the music comes up: the start of the first montage shot, or None with no montage."""
    for it in plan:
        if (it.get("shot") or {}).get("montage"):
            return float(it["start"])
    return None


def filters(settings: dict, total: float, loud_at: float | None) -> str:
    """The ffmpeg -af chain that turns the track into this video's music: where it begins, how
    fast it plays, how loud it is and when it comes up, and the fade at the end."""
    from audio_mix import RATE
    level, loud = float(settings["level"]), float(settings["loud"])
    speed, start = float(settings["speed"]), float(settings["start"])
    chain = [f"aresample={RATE}"]
    if start > 0:
        chain += [f"atrim=start={start:.3f}", "asetpts=PTS-STARTPTS"]
    if abs(speed - 1.0) > 0.001:
        # Played slower, and lower with it: what a "slowed" version of a song is.
        chain += [f"asetrate={int(round(RATE * speed))}", f"aresample={RATE}"]
    chain.append("asetpts=N/SR/TB")
    if loud_at is not None and abs(loud - level) > 0.0005:
        t0 = max(0.0, loud_at - RAMP)
        ramp = max(0.05, loud_at - t0)
        chain.append(f"volume='{level:.4f}+({loud - level:.4f})*clip((t-{t0:.3f})/{ramp:.3f},0,1)':eval=frame")
    else:
        chain.append(f"volume={level:.4f}")
    fade = min(FADE_OUT, total / 4)
    chain.append(f"afade=t=out:st={max(0.0, total - fade):.3f}:d={fade:.3f}")
    return ",".join(chain)
