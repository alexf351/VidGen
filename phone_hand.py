"""App screenshots shown on a phone held in a hand.

An app-screen shot shows the real screenshot, never a drawing of the app. To put it in a hand
without the image model touching the app's pixels, the image step draws ONE picture per format:
a hand holding a phone whose screen is plain chroma-key green. The assemble step then finds the
green rectangle and puts the real screenshot there. Anything in front of the green (a thumb
over the edge of the screen) stays in front.

    characters_cache/hand@<format>-<hash>.png    the hand picture, reused by every run
    runs/<id>/app/hand.png                       this run's copy

If the picture has no clean green screen (the image model sometimes ignores the instruction),
it is not kept, and assembly falls back to the plain phone frame on a blurred background.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from common import ROOT, StepError

GREEN = "#00FF00"


def enabled(config: dict) -> bool:
    return bool(config.get("app_screen_hand"))


def run_path(run_dir: Path) -> Path:
    return Path(run_dir) / "app" / "hand.png"


def _holder(config: dict, script: dict | None) -> str:
    """Whose hand it is: the format's hero, else the first character of the script."""
    for c in config.get("locked_characters", []):
        if "hero" in str(c.get("role") or "").lower():
            return c["description"]
    for c in (script or {}).get("characters", []):
        if isinstance(c, dict) and c.get("description"):
            return c["description"]
    return "an adult"


def prompt(config: dict, script: dict | None = None) -> str:
    style = str(config.get("style") or "").strip()
    return (
        f"{style}, close-up of one hand holding a smartphone upright, the phone facing the camera "
        f"straight on and filling most of the frame. The hand is the hand of {_holder(config, script)}; "
        "only the hand and the wrist are in the picture. It grips the phone from below, fingers "
        "wrapped around the side edges, and no finger covers the screen. "
        f"The phone's screen is ONE flat rectangle of solid pure bright green (chroma key green, {GREEN}): "
        "no reflection, no glare, no gradient, no icons, no text, nothing on it. "
        "Thin dark bezel. Dark, softly blurred room behind, warm light on the hand. No text anywhere."
    )


def cache_path(config: dict, script: dict | None = None) -> Path:
    key = hashlib.sha1(prompt(config, script).encode()).hexdigest()[:12]
    # A format that extends another shares its cast, so it shares the hand too.
    fmt = config.get("format") or {}
    name = re.sub(r"[^a-z0-9_-]", "", str(fmt.get("extends") or fmt.get("name") or "format").lower())
    return ROOT / config["characters_cache_dir"] / f"hand@{name}-{key}.png"


# ----------------------------------------------------------- finding the screen ----

def find_screen(img):
    """(box, mask) for the green screen in a hand picture, or None when there is no clean one.
    `box` is (left, top, right, bottom); `mask` is an "L" image the size of `img`, white where
    the screenshot goes."""
    from PIL import ImageChops, ImageFilter
    rgb = img.convert("RGB")
    r, g, b = rgb.split()
    # Green wins over both other channels by a clear margin, and is bright.
    lead = ImageChops.subtract(g, ImageChops.lighter(r, b))
    mask = ImageChops.multiply(lead.point(lambda v: 255 if v > 70 else 0),
                               g.point(lambda v: 255 if v > 110 else 0))
    core = mask.filter(ImageFilter.MinFilter(9))           # drop specks and thin green fringes
    box = core.getbbox()
    if box is None:
        return None
    left, top, right, bottom = box
    bw, bh = right - left, bottom - top
    w, h = rgb.size
    if bw < w * 0.28 or bh < h * 0.30 or not (1.35 <= bh / bw <= 2.6):
        return None                                        # too small, or not phone-shaped
    filled = sum(1 for v in core.crop(box).getdata() if v) / float(bw * bh)
    if filled < 0.80:
        return None                                        # not a rectangle (or mostly covered)
    # Grow the area back out, and a little more, so no green rim is left around the screenshot.
    grown = mask.filter(ImageFilter.MaxFilter(7))
    pad = 6
    box = (max(0, left - pad), max(0, top - pad), min(w, right + pad), min(h, bottom + pad))
    keep = grown.crop(box)
    full = grown.point(lambda v: 0)
    full.paste(keep, box[:2])
    return box, full.filter(ImageFilter.GaussianBlur(1.2))


def usable(path: Path) -> bool:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return find_screen(im) is not None
    except (OSError, ValueError):
        return False


def _framed(template: Path, w: int, h: int):
    """The hand picture filling a w x h frame, as it is seen in the video."""
    from PIL import Image
    hand = Image.open(template).convert("RGB")
    scale = max(w / hand.width, h / hand.height)
    hand = hand.resize((math.ceil(hand.width * scale), math.ceil(hand.height * scale)), Image.Resampling.LANCZOS)
    left, top = (hand.width - w) // 2, (hand.height - h) // 2
    return hand.crop((left, top, left + w, top + h))


def screen_shape(template: Path, w: int, h: int) -> tuple[int, int] | None:
    """(width, height) of the phone's screen in the hand picture at w x h, or None when it has
    no clean one. A screen drawn for the phone (phone_texts.py) is made in this shape, so none
    of it is cropped away: a drawn phone is rarely as tall as a real screenshot."""
    try:
        found = find_screen(_framed(template, w, h))
    except (OSError, ValueError):
        return None
    if found is None:
        return None
    box = found[0]
    return box[2] - box[0], box[3] - box[1]


def compose(template: Path, screenshot: Path, out: Path, w: int, h: int) -> Path | None:
    """The screenshot on the phone in the hand picture, at w x h. None when the hand picture
    has no clean green screen (the caller then uses the plain phone frame)."""
    try:
        from PIL import Image
    except ImportError:
        raise StepError("app_screen shots need Pillow: pip install -r requirements.txt") from None
    lanczos = Image.Resampling.LANCZOS
    hand = _framed(template, w, h)
    found = find_screen(hand)
    if found is None:
        return None
    box, mask = found
    bw, bh = box[2] - box[0], box[3] - box[1]
    shot = Image.open(screenshot).convert("RGB")
    s = max(bw / shot.width, bh / shot.height)               # cover the screen, crop the overflow
    shot = shot.resize((math.ceil(shot.width * s), math.ceil(shot.height * s)), lanczos)
    sl, st = (shot.width - bw) // 2, (shot.height - bh) // 2
    shot = shot.crop((sl, st, sl + bw, st + bh))
    layer = hand.copy()
    layer.paste(shot, box[:2])
    result = Image.composite(layer, hand, mask)
    out.parent.mkdir(parents=True, exist_ok=True)
    result.save(out)
    return out
