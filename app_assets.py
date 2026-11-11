"""The app screenshot library: the real screens a video can show in its demo beat.

    assets/screens/library.yaml     the screenshots that ship with VidGen: file, title, what
                                    it shows (the script writer reads this) and a group
    assets/screens/mine/            your own screenshots (added in the UI, or dropped in by
                                    hand); index.json holds their titles. Not in git.

Every format can use every screenshot here. A format's own `app_screens` list comes first and
keeps its wording; the rest of the library follows. A video can pin the ones it should show
(run.json "screens"); the script step then offers only those and must use them.
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
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
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
        out.append({"path": f"assets/screens/{name}", "title": str(e.get("title") or _title_from(name)),
                    "shows": " ".join(str(e.get("shows") or "").split()), "group": group, "mine": False})
    return out


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
    out = []
    for p in sorted(MINE_DIR.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file() or p.suffix.lower() not in PICTURES:
            continue
        meta = index.get(p.name) if isinstance(index.get(p.name), dict) else {}
        out.append({"path": f"assets/screens/mine/{p.name}", "title": str(meta.get("title") or _title_from(p.name)),
                    "shows": " ".join(str(meta.get("shows") or "").split()), "group": "mine", "mine": True})
    return out


def everything() -> list[dict]:
    return builtin() + mine()


def merged(format_list: list[dict], use_library: bool = True) -> list[dict]:
    """What a format can show: its own list first (its wording wins), then the library."""
    lib = {e["path"]: e for e in everything()}
    out, seen = [], set()
    for e in format_list:
        known = lib.get(e["path"], {})
        out.append({"path": e["path"], "shows": e.get("shows") or known.get("shows", ""),
                    "title": e.get("title") or known.get("title") or _title_from(e["path"]),
                    "group": known.get("group") or "more", "mine": bool(known.get("mine"))})
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
    """The picture behind a library path, or None. Only files inside assets/screens are served."""
    if not isinstance(rel, str) or not rel.strip():
        return None
    try:
        p = (ROOT / rel).resolve()
        p.relative_to(SCREENS_DIR.resolve())
    except (ValueError, OSError):
        return None
    return p if p.is_file() and p.suffix.lower() in PICTURES else None


# ------------------------------------------------------------------ your own ----

def decode_upload(data_url: str) -> bytes:
    import base64
    if not isinstance(data_url, str) or not data_url.strip():
        raise StepError("no picture was sent")
    raw = data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url
    if len(raw) > MAX_UPLOAD_BYTES * 4 // 3 + 16:
        raise StepError(f"the picture is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    try:
        return base64.b64decode(raw, validate=True)
    except (ValueError, base64.binascii.Error):
        raise StepError("the picture could not be read (bad base64)") from None


def add(title: str, shows: str, data: bytes) -> dict:
    """Save one of your screenshots (any picture PIL reads; stored as a JPEG) and return its entry."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    title = " ".join(str(title or "").split())[:60]
    shows = " ".join(str(shows or "").split())[:240]
    if not title:
        raise StepError("give the screenshot a short name")
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
    MINE_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40] or "screen"
    name, n = f"{slug}.jpg", 2
    while (MINE_DIR / name).exists():
        name, n = f"{slug}_{n}.jpg", n + 1
    img.save(MINE_DIR / name, "JPEG", quality=92)
    index = _mine_index()
    index[name] = {"title": title, "shows": shows}
    write_json(MINE_INDEX, index)
    return next(e for e in mine() if e["path"].endswith("/" + name))


def remove(rel: str) -> None:
    """Delete one of your own screenshots. The ones that ship with VidGen stay."""
    p = file_for(rel)
    if p is None or p.parent.resolve() != MINE_DIR.resolve():
        raise StepError("only your own screenshots can be removed")
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
