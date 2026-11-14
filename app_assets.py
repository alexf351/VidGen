"""The app screenshot library: the real screens a video can show in its demo beat.

    assets/screens/library.yaml     the screenshots that ship with VidGen: file, title, what
                                    it shows (the script writer reads this) and a group
    assets/screens/mine/            your own screenshots (added in the UI, or dropped in by
                                    hand); index.json holds their titles. Not in git.

Every format can use every screenshot here. A format's own `app_screens` list comes first and
keeps its wording; the rest of the library follows. A video can pin the ones it should show
(run.json "screens"); the script step then offers only those and must use them.

A screen can MOVE. Put a recording next to the picture with the same name (streak.jpg +
streak.mp4) and the video plays the recording on the phone instead of showing the still; the
picture stays as its thumbnail and as the fallback. A recording dropped into mine/ on its own
gets its picture made from one of its frames.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from common import ROOT, StepError, read_json, write_json

SCREENS_DIR = ROOT / "assets" / "screens"
LIBRARY_FILE = SCREENS_DIR / "library.yaml"
MINE_DIR = SCREENS_DIR / "mine"
MINE_INDEX = MINE_DIR / "index.json"
PICTURES = {".jpg", ".jpeg", ".png", ".webp"}
CLIPS = (".mp4", ".mov", ".m4v", ".webm")          # a recording beside a picture, in this order
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_CLIP_UPLOAD_BYTES = 80 * 1024 * 1024
MAX_CLIP_SECONDS = 12.0               # a longer recording of your own is cut to this
MAX_SIDE = 3000                       # the largest phone screenshots are 1320 x 2868
MAX_PICKS = 6

# Groups, in the order a video meets them. The UI shows the library under these headings.
GROUPS = [
    ("start", "Opening the app"),
    ("learn", "Learning"),
    ("coach", "Coach and practice"),
    ("wins", "Wins and rewards"),
    ("progress", "Progress and rank"),
    ("more", "More of the app"),
    ("mine", "Your own"),
]
GROUP_IDS = [g for g, _ in GROUPS]


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _title_from(name: str) -> str:
    words = re.sub(r"[_\-]+", " ", Path(name).stem).strip()
    return words[:1].upper() + words[1:] if words else "Screenshot"


# ------------------------------------------------------------- recordings ----

def clip_for(rel: str) -> Path | None:
    """The recording that goes with a screenshot (same folder, same name), or None."""
    if not isinstance(rel, str) or not rel.strip():
        return None
    pic = ROOT / rel
    for ext in CLIPS:
        clip = pic.with_suffix(ext)
        if clip.is_file():
            return clip
    return None


_SECONDS: dict[tuple[str, int], float | None] = {}


def clip_seconds(clip: Path) -> float | None:
    """How long a recording runs (remembered until the file changes); None if it cannot be read."""
    try:
        key = (str(clip), clip.stat().st_mtime_ns)
    except OSError:
        return None
    if key not in _SECONDS:
        try:
            from media import probe_duration
            _SECONDS[key] = round(float(probe_duration(clip)), 2)
        except (StepError, OSError, ValueError):
            _SECONDS[key] = None
    return _SECONDS[key]


def _motion(entry: dict) -> dict:
    """Add "clip" (repo path of the recording, or None) and "seconds" to a library entry."""
    clip = clip_for(entry["path"])
    seconds = clip_seconds(clip) if clip else None
    entry["clip"] = _rel(clip) if clip and seconds else None
    entry["seconds"] = seconds if clip and seconds else None
    return entry


def _poster(clip: Path, out: Path) -> bool:
    """One frame of a recording, from late in it (the settled screen), as its picture."""
    try:
        from media import probe_duration, run_ffmpeg
        at = max(0.0, probe_duration(clip) * 0.7)
        run_ffmpeg(["-ss", f"{at:.2f}", "-i", str(clip), "-frames:v", "1", "-update", "1", "-q:v", "3", str(out)],
                   f"picture for {clip.name}")
    except (StepError, OSError, ValueError):
        return False
    return out.is_file()


def builtin() -> list[dict]:
    """library.yaml's screenshots, in file order. A missing file is simply left out."""
    if not LIBRARY_FILE.is_file():
        return []
    import yaml
    try:
        raw = yaml.safe_load(LIBRARY_FILE.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise StepError(f"{_rel(LIBRARY_FILE)} is not valid YAML: {e}") from None
    out, seen = [], set()
    for i, e in enumerate(raw.get("screens") or []):
        if not isinstance(e, dict) or not isinstance(e.get("file"), str) or not e["file"].strip():
            raise StepError(f"{_rel(LIBRARY_FILE)}: screens[{i}] needs a file")
        name = e["file"].strip()
        if "/" in name or "\\" in name or name in seen:
            raise StepError(f"{_rel(LIBRARY_FILE)}: screens[{i}] file must be a unique file name "
                            f"in assets/screens, got {name!r}")
        seen.add(name)
        group = str(e.get("group") or "more")
        if group not in GROUP_IDS or group == "mine":
            raise StepError(f"{_rel(LIBRARY_FILE)}: screens[{i}] group must be one of "
                            f"{', '.join(g for g in GROUP_IDS if g != 'mine')}, got {group!r}")
        if not (SCREENS_DIR / name).is_file():
            continue
        try:
            start = max(0.0, float(e.get("clip_from") or 0))
        except (TypeError, ValueError):
            raise StepError(f"{_rel(LIBRARY_FILE)}: screens[{i}] clip_from must be a number of seconds") from None
        out.append(_motion({"path": f"assets/screens/{name}", "title": str(e.get("title") or _title_from(name)),
                            "shows": " ".join(str(e.get("shows") or "").split()), "group": group, "mine": False,
                            "clip_from": start}))
    return out


def clip_from(rel: str) -> float:
    """Where the part of a screen's recording worth showing starts (library.yaml "clip_from"),
    in seconds; 0 when it does not say. Used when the video shows less than the whole recording."""
    for e in builtin():
        if e["path"] == rel:
            return float(e.get("clip_from") or 0.0)
    return 0.0


def _mine_index() -> dict:
    if not MINE_INDEX.is_file():
        return {}
    try:
        data = read_json(MINE_INDEX)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def mine() -> list[dict]:
    """Your own screenshots: every picture in assets/screens/mine, titled from index.json or,
    for a file dropped in by hand, from its name."""
    if not MINE_DIR.is_dir():
        return []
    index = _mine_index()
    files = sorted((p for p in MINE_DIR.iterdir() if p.is_file() and not p.name.startswith(".")), key=lambda x: x.name.lower())
    # A recording dropped in on its own gets a picture made from it, once.
    have = {p.stem for p in files if p.suffix.lower() in PICTURES}
    made = False
    for p in files:
        if p.suffix.lower() in CLIPS and p.stem not in have:
            made = _poster(p, p.with_suffix(".jpg")) or made
            have.add(p.stem)
    if made:
        files = sorted((p for p in MINE_DIR.iterdir() if p.is_file() and not p.name.startswith(".")), key=lambda x: x.name.lower())
    out = []
    for p in files:
        if p.suffix.lower() not in PICTURES:
            continue
        meta = index.get(p.name) if isinstance(index.get(p.name), dict) else {}
        out.append(_motion({"path": f"assets/screens/mine/{p.name}", "title": str(meta.get("title") or _title_from(p.name)),
                            "shows": " ".join(str(meta.get("shows") or "").split()), "group": "mine", "mine": True}))
    return out


def everything() -> list[dict]:
    return builtin() + mine()


def merged(format_list: list[dict], use_library: bool = True) -> list[dict]:
    """What a format can show: its own list first (its wording wins), then the library."""
    lib = {e["path"]: e for e in everything()}
    out, seen = [], set()
    for e in format_list:
        known = lib.get(e["path"], {})
        out.append(_motion({"path": e["path"], "shows": e.get("shows") or known.get("shows", ""),
                            "title": e.get("title") or known.get("title") or _title_from(e["path"]),
                            "group": known.get("group") or "more", "mine": bool(known.get("mine"))}))
        seen.add(e["path"])
    if use_library:
        out += [dict(e) for e in lib.values() if e["path"] not in seen]
    return out


def in_library_order(screens: list[dict]) -> list[dict]:
    """The same screens in the library's own order (a group's story order), for showing them;
    the script prompt keeps the format's order. A format's extra screenshots come first."""
    rank = {e["path"]: i for i, e in enumerate(everything())}
    return sorted(screens, key=lambda e: rank.get(e["path"], -1))


def file_for(rel: str) -> Path | None:
    """The picture or recording behind a library path, or None. Only files inside assets/screens
    are served."""
    if not isinstance(rel, str) or not rel.strip():
        return None
    try:
        p = (ROOT / rel).resolve()
        p.relative_to(SCREENS_DIR.resolve())
    except (ValueError, OSError):
        return None
    return p if p.is_file() and (p.suffix.lower() in PICTURES or p.suffix.lower() in CLIPS) else None


# ------------------------------------------------------------------ your own ----

def decode_upload(data_url: str, what: str = "picture", limit: int = MAX_UPLOAD_BYTES) -> bytes:
    import base64
    if not isinstance(data_url, str) or not data_url.strip():
        raise StepError(f"no {what} was sent")
    raw = data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url
    if len(raw) > limit * 4 // 3 + 16:
        raise StepError(f"the {what} is larger than {limit // (1024 * 1024)} MB")
    try:
        return base64.b64decode(raw, validate=True)
    except (ValueError, base64.binascii.Error):
        raise StepError(f"the {what} could not be read (bad base64)") from None


def _clean_text(title: str, shows: str) -> tuple[str, str]:
    title = " ".join(str(title or "").split())[:60]
    shows = " ".join(str(shows or "").split())[:240]
    if not title:
        raise StepError("give the screenshot a short name")
    return title, shows


def _free_name(title: str) -> str:
    """A file name (no extension) for a new screenshot of yours that nothing else uses."""
    MINE_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40] or "screen"
    taken = {p.stem for p in MINE_DIR.iterdir()}
    name, n = slug, 2
    while name in taken:
        name, n = f"{slug}_{n}", n + 1
    return name


def add_clip(title: str, shows: str, data: bytes) -> dict:
    """Save a screen recording of yours: re-encoded to a plain silent mp4 (so any phone's
    recording assembles the same way), cut to MAX_CLIP_SECONDS, with a picture made from it."""
    from media import has_video_stream, probe_duration, require_ffmpeg, run_ffmpeg
    title, shows = _clean_text(title, shows)
    require_ffmpeg()
    name = _free_name(title)
    raw = MINE_DIR / f".{name}.upload"
    clip, pic = MINE_DIR / f"{name}.mp4", MINE_DIR / f"{name}.jpg"
    raw.write_bytes(data)
    try:
        try:
            unreadable = StepError("that file is not a video VidGen can read")
            try:
                if not has_video_stream(raw):
                    raise unreadable
                run_ffmpeg(["-i", str(raw), "-an", "-t", f"{MAX_CLIP_SECONDS}",
                            "-vf", "fps=30,scale='min(1080,iw)':-2:flags=lanczos,setsar=1",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(clip)], "your recording")
            except StepError:
                raise unreadable from None
            size = _video_size(clip)
            if size and size[0] > size[1]:
                raise StepError("that recording is wider than it is tall; use an upright phone screen recording")
            if probe_duration(clip) < 0.5:
                raise StepError("that recording is shorter than half a second")
            if not _poster(clip, pic):
                raise StepError("a picture could not be made from that recording")
        except StepError:
            for f in (clip, pic):
                f.unlink(missing_ok=True)
            raise
    finally:
        raw.unlink(missing_ok=True)
    index = _mine_index()
    index[pic.name] = {"title": title, "shows": shows}
    write_json(MINE_INDEX, index)
    return next(e for e in mine() if e["path"].endswith("/" + pic.name))


def _video_size(clip: Path) -> tuple[int, int] | None:
    from media import _probe
    try:
        w, h = _probe(clip, "stream=width,height", stream="v:0").splitlines()[0].split(",")[:2]
        return int(w), int(h)
    except (StepError, ValueError, IndexError):
        return None


def add(title: str, shows: str, data: bytes) -> dict:
    """Save one of your screenshots (any picture PIL reads; stored as a JPEG) and return its entry."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    title, shows = _clean_text(title, shows)
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise StepError(f"that file is not a picture VidGen can read ({e})") from None
    if img.width < 200 or img.height < 300:
        raise StepError(f"that picture is too small ({img.width} x {img.height}); use a full phone screenshot")
    if img.width > img.height:
        raise StepError("that picture is wider than it is tall; use an upright phone screenshot")
    if img.mode in ("RGBA", "LA", "P"):
        flat = Image.new("RGB", img.size, (0, 0, 0))
        rgba = img.convert("RGBA")
        flat.paste(rgba, mask=rgba.split()[3])
        img = flat
    else:
        img = img.convert("RGB")
    if max(img.size) > MAX_SIDE:
        s = MAX_SIDE / max(img.size)
        img = img.resize((round(img.width * s), round(img.height * s)), Image.Resampling.LANCZOS)
    name = f"{_free_name(title)}.jpg"
    img.save(MINE_DIR / name, "JPEG", quality=92)
    index = _mine_index()
    index[name] = {"title": title, "shows": shows}
    write_json(MINE_INDEX, index)
    return next(e for e in mine() if e["path"].endswith("/" + name))


def remove(rel: str) -> None:
    """Delete one of your own screenshots. The ones that ship with VidGen stay."""
    p = file_for(rel)
    if p is None or p.parent.resolve() != MINE_DIR.resolve() or p.suffix.lower() not in PICTURES:
        raise StepError("only your own screenshots can be removed")
    for ext in CLIPS:                                   # its recording goes with it
        p.with_suffix(ext).unlink(missing_ok=True)
    p.unlink()
    index = _mine_index()
    if index.pop(p.name, None) is not None:
        write_json(MINE_INDEX, index)


# --------------------------------------------------------------- a video's picks ----

def resolve_picks(names, available: list[dict]) -> list[str]:
    """What the user asked for ("learn", "learn.jpg" or a full path) -> library paths, in their
    order. Anything unknown or missing is an error that lists what there is."""
    if not names:
        return []
    by_path = {e["path"]: e["path"] for e in available}
    by_name = {}
    for e in available:
        by_name.setdefault(Path(e["path"]).name.lower(), e["path"])
        by_name.setdefault(Path(e["path"]).stem.lower(), e["path"])
    out = []
    for raw in names:
        key = str(raw or "").strip()
        path = by_path.get(key) or by_name.get(key.lower())
        if not path:
            known = ", ".join(sorted({Path(p).stem for p in by_path})) or "none"
            raise StepError(f"app screen {key!r} is not in the library (there is: {known})")
        if path not in out:
            out.append(path)
    if len(out) > MAX_PICKS:
        raise StepError(f"pick at most {MAX_PICKS} app screens for one video, got {len(out)}")
    return out


def run_picks(run_dir: Path) -> list[str]:
    """The screens pinned for this run (run.json "screens"), as saved."""
    try:
        data = read_json(Path(run_dir) / "run.json")
    except (OSError, ValueError):
        return []
    picks = data.get("screens") if isinstance(data, dict) else None
    return [p for p in picks if isinstance(p, str) and p.strip()] if isinstance(picks, list) else []
