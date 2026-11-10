"""Your own characters: a library you build once and cast into any format's runs.

    library/characters/<id>/character.json   name, description, role, voice, options
    library/characters/<id>/ref.png          the reference picture (generated or uploaded)

A run picks its cast when it is created (saved in run.json as "cast"):

    [{"character": "dana", "replaces": "marcus"},     # dana takes marcus's role in the story
     {"character": "rex",  "role": "the dog"}]         # rex joins as an extra locked character

apply_cast() turns that into locked_characters entries, so the script step, the validator,
recast and the voice step all treat a library character exactly like a format's own cast.
The images step makes a reference sheet in the run's style from ref.png (cached per format),
or uses ref.png as is when the character is marked keep_as_is.
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
import shutil
from datetime import datetime
from pathlib import Path

from common import ROOT, StepError, read_json, write_json

LIBRARY_DIR = ROOT / "library" / "characters"
ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
RESERVED_IDS = {"narrator"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_SIDE = 2048
DEFAULT_ROLE = "a main character"


# ---------------------------------------------------------------- library ----

def char_dir(cid: str) -> Path:
    if not isinstance(cid, str) or not ID_RE.match(cid):
        raise StepError(f"character id must be a lowercase slug, got {cid!r}")
    return LIBRARY_DIR / cid


def ref_path(cid: str) -> Path:
    return char_dir(cid) / "ref.png"


def slug_for(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not s or not s[0].isalpha():
        s = "c_" + s
    return s[:32].rstrip("_") or "character"


def new_id(name: str) -> str:
    base = slug_for(name)
    if base in RESERVED_IDS:
        base = base + "_1"
    cid, i = base, 2
    while (LIBRARY_DIR / cid).exists():
        cid = f"{base[:29]}_{i}"
        i += 1
    return cid


def exists(cid: str) -> bool:
    try:
        return (char_dir(cid) / "character.json").is_file()
    except StepError:
        return False


def get(cid: str) -> dict:
    path = char_dir(cid) / "character.json"
    if not path.is_file():
        raise StepError(f"no character {cid!r} in the library (library/characters/)")
    try:
        data = read_json(path)
    except (OSError, ValueError) as e:
        raise StepError(f"{path} is not valid JSON: {e}") from e
    data["id"] = cid
    ref = ref_path(cid)
    data["image"] = ref if ref.is_file() else None
    return data


def list_all() -> list[dict]:
    if not LIBRARY_DIR.is_dir():
        return []
    out = []
    for d in sorted(LIBRARY_DIR.iterdir()):
        if d.is_dir() and ID_RE.match(d.name) and (d / "character.json").is_file():
            try:
                out.append(get(d.name))
            except StepError:
                continue
    out.sort(key=lambda c: c.get("created_at") or "", reverse=True)
    return out


def _clean_text(value, field: str, required: bool, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if required and not text:
        raise StepError(f"{field} is required")
    if len(text) > limit:
        raise StepError(f"{field} is too long (max {limit} characters)")
    return text


def save(cid: str | None, *, name: str, description: str, role: str = "", voice_id: str = "",
         keep_as_is: bool = False, source: str | None = None) -> dict:
    """Create (cid None) or update a character's text fields. Returns the saved character."""
    name = _clean_text(name, "name", True, 60)
    description = _clean_text(description, "description", True, 400)
    role = _clean_text(role, "role", False, 80)
    voice_id = _clean_text(voice_id, "voice id", False, 64)
    if voice_id and not re.fullmatch(r"[A-Za-z0-9_-]+", voice_id):
        raise StepError("voice id should look like an ElevenLabs voice id (letters and digits)")
    if cid is None:
        cid = new_id(name)
        data = {"created_at": datetime.now().isoformat(timespec="seconds"), "source": source or ""}
    else:
        data = {k: v for k, v in get(cid).items() if k not in ("id", "image")}
        if source:
            data["source"] = source
    data.update({"name": name, "description": description, "role": role, "voice_id": voice_id,
                 "keep_as_is": bool(keep_as_is)})
    folder = char_dir(cid)
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / "character.json", data)
    return get(cid)


def delete(cid: str) -> None:
    folder = char_dir(cid)
    if not folder.is_dir():
        raise StepError(f"no character {cid!r} in the library")
    shutil.rmtree(folder)


def decode_image(data_url: str) -> bytes:
    """A data: URL or bare base64 from the browser -> bytes (size-checked)."""
    if not isinstance(data_url, str) or not data_url.strip():
        raise StepError("no image was sent")
    raw = data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url
    if len(raw) > MAX_UPLOAD_BYTES * 4 // 3 + 16:
        raise StepError(f"the image is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    try:
        return base64.b64decode(raw, validate=True)
    except (ValueError, base64.binascii.Error):
        raise StepError("the image could not be read (bad base64)") from None


def store_image(cid: str, data: bytes) -> Path:
    """Save an uploaded picture as the character's ref.png (any format PIL reads, max 2048px)."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise StepError(f"that file is not an image VidGen can read ({e})") from None
    img = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    dest = ref_path(cid)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="PNG")
    return dest


# ------------------------------------------------------------- generation ----

def generate_reference(cid: str, config: dict) -> Path:
    """Draw the character from its description, in the config's format style, to ref.png.
    One image model call (the images provider's price)."""
    from steps.images import SHEET_ASPECT, _generate_image, _require_key, sheet_prompt
    c = get(cid)
    _require_key(config)
    dest = ref_path(cid)
    tmp = dest.with_name("ref.new.png")
    print(f"[character] drawing {c['name']} ({cid}) in the {config['format']['name']} style...")
    _generate_image(config, sheet_prompt(c["description"], config["style"]), SHEET_ASPECT, [],
                    f"character {cid}", tmp)
    tmp.replace(dest)
    data = {k: v for k, v in c.items() if k not in ("id", "image")}
    data.update({"source": "generated", "drawn_in": config["format"]["name"]})
    write_json(char_dir(cid) / "character.json", data)
    print(f"[character] saved {dest}")
    return dest


DESCRIBE_PROMPT = (
    "Look at this picture of a character and write ONE sentence that describes what they look "
    "like, for an image model that must redraw the same character in every shot of a video. "
    "Describe identity only: apparent age, gender presentation, face, hair (style and color), "
    "skin tone, build, and at most one distinctive feature (glasses, freckles, a scar). For an "
    "animal, mascot or object, describe its shape, colors and markings. Do NOT describe clothing, "
    "pose, background, expression or lighting. Start with \"a\" or \"an\", no name, no quotes, "
    "under 40 words. Example: a 26 year old man with messy dark brown hair, light stubble, warm "
    "tan skin, an athletic build"
)


def describe_image(image: Path, config: dict, client=None) -> str:
    """One short Claude call: an identity-only description of the picture."""
    from steps.script import call_model, create_client, response_text
    from PIL import Image
    img = Image.open(image)
    img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=88)
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.b64encode(buf.getvalue()).decode()}},
        {"type": "text", "text": DESCRIBE_PROMPT},
    ]
    client = client or create_client()
    model = config["script"]["model"]
    print(f"[character] describing {image.name} with {model}...")
    # Room for the model's thinking as well as the one sentence; low effort keeps it quick.
    response = call_model(client, model, 4000, "You write short, literal character descriptions.",
                          [{"role": "user", "content": content}], effort="low")
    text = re.sub(r"\s+", " ", response_text(response)).strip().strip('"').strip()
    text = text.rstrip(".")
    if not text:
        raise StepError("Claude returned no description; write one by hand")
    return text[:400]


# ------------------------------------------------------------------ casting ----

def check_cast(raw) -> list[dict]:
    """Validate a run's cast list (from the UI or run.json). Characters must exist."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise StepError("cast must be a list of {character, replaces?, role?}")
    out, used, replaced = [], set(), set()
    for i, e in enumerate(raw):
        if not isinstance(e, dict):
            raise StepError(f"cast[{i}] must be an object")
        cid = e.get("character")
        if not exists(cid):
            raise StepError(f"cast[{i}]: no character {cid!r} in the library")
        if cid in used:
            raise StepError(f"cast lists {cid!r} twice")
        used.add(cid)
        rep = e.get("replaces") or None
        if rep is not None:
            if not isinstance(rep, str):
                raise StepError(f"cast[{i}].replaces must be a character id")
            if rep in replaced:
                raise StepError(f"cast replaces {rep!r} twice")
            replaced.add(rep)
        role = _clean_text(e.get("role"), f"cast[{i}].role", False, 80)
        out.append({"character": cid, "replaces": rep, "role": role})
    return out


def apply_cast(cfg: dict, cast: list[dict]) -> None:
    """Swap/add library characters into cfg['locked_characters'] (and their voices)."""
    cast = check_cast(cast)
    if not cast:
        return
    locked = list(cfg.get("locked_characters") or [])
    ids = [c["id"] for c in locked]
    voices = dict(cfg.get("voices") or {})
    fmt = cfg["format"]["name"]
    for e in cast:
        c = get(e["character"])
        cid = c["id"]
        rep = e["replaces"]
        if rep is not None and rep not in ids:
            raise StepError(f"the {fmt} format has no character {rep!r} to replace "
                            f"(its cast: {', '.join(ids) or 'none'})")
        clash = [x for x in ids if x == cid and x != rep]
        if clash:
            raise StepError(f"{fmt} already has a character with id {cid!r}; rename yours or "
                            f"swap it for that one")
        entry = {"id": cid, "description": c["description"], "image_path": "",
                 "library": cid, "keep_as_is": bool(c.get("keep_as_is")), "name": c["name"]}
        if rep is not None:
            i = ids.index(rep)
            old = locked[i]
            entry["role"] = e["role"] or old.get("role") or c.get("role") or DEFAULT_ROLE
            entry["replaced"] = rep
            locked[i] = entry
            ids[i] = cid
            voices[cid] = c.get("voice_id") or voices.get(rep, "")
        else:
            entry["role"] = e["role"] or c.get("role") or DEFAULT_ROLE
            locked.append(entry)
            ids.append(cid)
            voices[cid] = c.get("voice_id") or ""
    cfg["locked_characters"] = locked
    cfg["voices"] = voices
    cfg["cast"] = cast


def describe_cast(cfg: dict) -> list[str]:
    lines = []
    for c in cfg.get("locked_characters", []):
        if c.get("library"):
            how = f"in place of {c['replaced']}" if c.get("replaced") else "added"
            lines.append(f"{c['id']} ({c.get('role', '')}) from your library, {how}")
    return lines


# --------------------------------------------------------- reference sheets ----

def restyle_prompt(description: str, style: str) -> str:
    from steps.images import _sheet_style
    return (
        f"{_sheet_style(style)}, character reference sheet of {description}. Redraw the character "
        "in the reference picture in this exact art style, keeping who they are: same face, hair, "
        "skin tone, build and distinctive features. Three full-body views side by side: front, "
        "three-quarter, side profile. Neutral plain grey outfit unless the character is a mascot, "
        "animal or object. Relaxed neutral pose, plain light grey studio background, even soft "
        "lighting, no text."
    )


def sheet_cache_path(config: dict, lock: dict) -> Path:
    """characters_cache/lib-<id>@<format>-<hash>.png; the hash covers the picture and description,
    so editing either draws a fresh sheet."""
    src = ref_path(lock["library"])
    h = hashlib.sha1()
    h.update(src.read_bytes())
    h.update(lock["description"].encode())
    h.update(config["style"].encode())
    name = f"lib-{lock['library']}@{config['format']['name']}-{h.hexdigest()[:10]}.png"
    return ROOT / config["characters_cache_dir"] / name


def library_sheet(config: dict, lock: dict, dest: Path, generate) -> str:
    """Put this library character's sheet at dest. Returns what was done (for the log).
    `generate(prompt, refs, dest)` draws one image."""
    src = ref_path(lock["library"])
    if not src.is_file():
        raise StepError(f"library character {lock['library']!r} has no picture yet; draw or upload "
                        f"one on the Characters page")
    if lock.get("keep_as_is"):
        if not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime:
            shutil.copyfile(src, dest)
            return "picture from your library, used as is"
        return "reference sheet exists, skipping"
    cache = sheet_cache_path(config, lock)
    marker = dest.with_suffix(".src")            # which cached sheet this run's copy came from
    if dest.exists() and marker.is_file() and marker.read_text(encoding="utf-8").strip() == cache.name:
        return "reference sheet exists, skipping"
    if cache.exists():
        shutil.copyfile(cache, dest)
        how = "sheet in this style from cache"
    else:
        generate(restyle_prompt(lock["description"], config["style"]), [src], dest)
        cache.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dest, cache)
        how = f"drew a sheet in the {config['format']['name']} style from your picture"
    marker.write_text(cache.name + "\n", encoding="utf-8")
    return how
