"""Your own picture or clip for a shot, made somewhere else (ChatGPT, Midjourney, Grok...).

    save_picture(run_dir, n, data)           the shot's picture is yours: no picture model is called
    save_clip(run_dir, n, data, config)      the shot's clip is yours: no video model is called

A picture replaces the shot's keyframe (shots/<n>.png). A clip made from the old picture no
longer fits it, so it is taken out; make the clip again, or bring your own. A clip replaces
shots/<n>.mp4: it is re-encoded to a plain mp4 (any phone's or site's file assembles the same
way), cut to MAX_CLIP_SECONDS, and the shot is marked to move. A shot with no picture yet gets
the clip's first frame as its picture, so the images step has nothing left to draw for it.
Both cost nothing. The assemble step crops a picture or clip of another shape to fill 9:16.
"""

from __future__ import annotations

import io
import shutil
import tempfile
from pathlib import Path

from common import StepError, read_json, write_json

MAX_CLIP_SECONDS = 15.0
MIN_SIDE = 256
RECORD = "own_media.json"           # which pictures and clips are yours, so the cost leaves them out


def _mark(run_dir: Path, kind: str, n: int, path: Path) -> None:
    rec_path = run_dir / RECORD
    rec = read_json(rec_path) if rec_path.is_file() else {}
    rec.setdefault(kind, {})[str(n)] = round(path.stat().st_mtime, 3)
    write_json(rec_path, rec)


def is_own(run_dir: Path, kind: str, n: int, path: Path) -> bool:
    """Is this picture ("pictures") or clip ("clips") the one you uploaded? A file made again by
    the images or video step since has another time, so it counts as made (and paid for)."""
    rec_path = run_dir / RECORD
    if not rec_path.is_file() or not path.is_file():
        return False
    try:
        want = read_json(rec_path).get(kind, {}).get(str(n))
    except (OSError, ValueError, AttributeError):
        return False
    return want is not None and want == round(path.stat().st_mtime, 3)


def _shot(run_dir: Path, n: int) -> tuple[dict, dict]:
    path = run_dir / "script.json"
    if not path.is_file():
        raise StepError("this video has no script yet")
    script = read_json(path)
    shot = next((s for s in script.get("shots", []) if isinstance(s, dict) and s.get("n") == n), None)
    if shot is None:
        raise StepError(f"there is no shot {n}")
    if shot.get("card") or shot.get("app_screen") or shot.get("texts"):
        raise StepError(f"shot {n} is drawn by VidGen itself (a card, an app screen or messages), so it takes no picture or clip")
    return script, shot


def _shape(w: int, h: int) -> str:
    r = w / h
    return "9:16" if abs(r - 9 / 16) < 0.03 else "tall" if r < 1 else "square" if abs(r - 1) < 0.05 else "wide"


def save_picture(run_dir: Path, n: int, data: bytes) -> dict:
    from PIL import Image, UnidentifiedImageError
    from steps.images import shot_path
    from steps.video import video_path
    _shot(run_dir, n)
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except (UnidentifiedImageError, OSError, ValueError):
        raise StepError("that file is not a picture VidGen can read (use a PNG, JPEG or WebP)") from None
    w, h = im.size
    if min(w, h) < MIN_SIDE:
        raise StepError(f"the picture is {w} x {h}; it needs to be at least {MIN_SIDE} pixels on each side")
    im = im.convert("RGB")
    dest = shot_path(run_dir, n)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".upload.png")
    im.save(tmp)
    tmp.replace(dest)
    _mark(run_dir, "pictures", n, dest)
    clip = video_path(run_dir, n)
    removed = clip.is_file()
    if removed:
        clip.unlink()
    print(f"  shot {n}: your picture ({w} x {h}, {_shape(w, h)})" + (", the old clip was taken out" if removed else ""))
    return {"shot": n, "size": [w, h], "shape": _shape(w, h), "removed_clip": removed}


def save_clip(run_dir: Path, n: int, data: bytes, config: dict | None = None) -> dict:
    from media import has_video_stream, probe_duration, require_ffmpeg, run_ffmpeg
    from steps.images import shot_path
    from steps.video import video_path
    script, shot = _shot(run_dir, n)
    require_ffmpeg()
    dest = video_path(run_dir, n)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_dir:
        src = Path(tmp_dir) / "upload"
        src.write_bytes(data)
        try:
            ok = has_video_stream(src)
        except StepError:
            ok = False
        if not ok:
            raise StepError("that file is not a video VidGen can read (use an MP4 or MOV)")
        part = Path(tmp_dir) / "clip.mp4"
        run_ffmpeg(["-i", str(src), "-t", f"{MAX_CLIP_SECONDS:g}", "-map", "0:v:0", "-map", "0:a:0?",
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "18", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(part)], f"shot {n}: your clip")
        seconds = probe_duration(part)
        shutil.move(str(part), dest)
    _mark(run_dir, "clips", n, dest)
    picture = shot_path(run_dir, n)
    made_picture = not picture.is_file()
    if made_picture:
        run_ffmpeg(["-i", str(dest), "-frames:v", "1", "-update", "1", str(picture)], f"shot {n}: first frame")
        _mark(run_dir, "pictures", n, picture)
    changed = []
    if shot.get("animate") is not True:
        shot["animate"] = True
        changed.append("animate")
    if shot.get("talk"):
        shot.pop("talk")
        changed.append("talk")
    if changed:
        write_json(run_dir / "script.json", script)
    voice_dropped = False
    if str(shot.get("vo_line") or "").strip() and config is not None:
        import clip_sound
        from steps.voice import audio_path, timing_path
        if clip_sound.on(config, run_dir) and (audio_path(run_dir, n).exists() or timing_path(run_dir, n).exists()):
            audio_path(run_dir, n).unlink(missing_ok=True)
            timing_path(run_dir, n).unlink(missing_ok=True)
            voice_dropped = True
    print(f"  shot {n}: your clip ({seconds:.1f}s)" + (", its first frame is the picture" if made_picture else ""))
    return {"shot": n, "seconds": round(seconds, 2), "made_picture": made_picture, "voice_dropped": voice_dropped}
