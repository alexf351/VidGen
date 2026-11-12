"""Text messages on the phone in the hero's hand.

A "texts" shot shows a chat screen with one to three messages from somebody ("OMG TYLER JUST
KISSED ME", then "best wingman ever"). The screen is drawn here, not by the image model, so
every letter is right; the assemble step then puts it on the phone exactly as it puts a real
app screenshot there (phone_hand.py, or the plain phone frame when there is no hand picture).
The messages arrive one at a time, each with a soft pop.

    "texts": {"from": "Jess", "messages": ["OMG TYLER JUST KISSED ME", "best wingman ever"]}

In a message, "<3" is drawn as a red heart. Other emoji are left out: the bundled font has none.
"""

from __future__ import annotations

import re
from pathlib import Path

from common import ROOT, StepError

MAX_MESSAGES = 3
MAX_CHARS = 60
MAX_NAME = 18
SIZE = (1170, 2532)                  # the screen, in the shape of a phone screenshot
FONT = ROOT / "assets" / "fonts" / "Inter-Regular.otf"
FONT_BOLD = ROOT / "assets" / "fonts" / "Inter-SemiBold.otf"
HEART = "<3"


def is_texts(shot) -> bool:
    return isinstance(shot, dict) and bool(shot.get("texts"))


def _plain(text: str) -> str:
    """One line of text the bundled font can draw: no emoji, no control characters."""
    text = str(text).replace("❤️", HEART).replace("❤", HEART).replace("♥", HEART)
    text = "".join(ch for ch in text if ch == "’" or (" " <= ch <= "ɏ"))
    return " ".join(text.replace("’", "'").split())


def check(value, label: str) -> tuple[dict | None, list[str]]:
    """(the texts as they will be shown, problems). None with the problems when it cannot be used."""
    if not isinstance(value, dict) or set(value) - {"from", "messages"}:
        return None, [f'{label}.texts must be {{"from": name, "messages": [text, ...]}}, got {value!r}']
    errors = []
    who = _plain(value.get("from") or "") if isinstance(value.get("from"), str) else ""
    if not who:
        errors.append(f"{label}.texts.from must be the name of whoever sent the messages")
    elif len(who) > MAX_NAME:
        errors.append(f"{label}.texts.from must be at most {MAX_NAME} characters, got {who!r}")
    raw = value.get("messages")
    if not isinstance(raw, list) or not (1 <= len(raw) <= MAX_MESSAGES):
        errors.append(f"{label}.texts.messages must be a list of 1-{MAX_MESSAGES} messages")
        return None, errors
    messages = []
    for k, m in enumerate(raw, 1):
        text = _plain(m) if isinstance(m, str) else ""
        if not text:
            errors.append(f"{label}.texts.messages[{k}] must be a line of text")
        elif len(text) > MAX_CHARS:
            errors.append(f"{label}.texts.messages[{k}] must be at most {MAX_CHARS} characters, got {len(text)}")
        messages.append(text)
    return (None, errors) if errors else ({"from": who, "messages": messages}, [])


def seconds(texts: dict, asm: dict) -> float:
    """How long the shot is on: a beat for each message, never a blink."""
    return max(1.8, len(texts["messages"]) * float(asm.get("texts_seconds", 1.2)))


def arrivals(texts: dict, duration: float) -> list[float]:
    """When each message appears, in seconds from the start of the shot. The first is there
    from the first frame."""
    n = len(texts["messages"])
    return [round(duration * k / n, 3) for k in range(n)]


# ------------------------------------------------------------------ the picture ----

def _font(path: Path, size: int):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        raise StepError(f"the font for text messages is missing: {path}") from None


def _pieces(text: str) -> list[str]:
    """Words, with each heart its own piece."""
    return [p for p in re.split(rf"(\s+|{re.escape(HEART)})", text) if p and not p.isspace()]


def _wrap(draw, text: str, font, width: int) -> list[list[str]]:
    lines, line = [], []
    for piece in _pieces(text):
        if line and _width(draw, line + [piece], font) > width:
            lines.append(line)
            line = []
        line.append(piece)
    return lines + [line] if line else lines


def _width(draw, pieces: list[str], font) -> int:
    space = draw.textlength(" ", font=font)
    total = 0.0
    for i, p in enumerate(pieces):
        total += font.size if p == HEART else draw.textlength(p, font=font)
        if i:
            total += space
    return int(total + 0.5)


def _heart(draw, x: float, y: float, size: float) -> None:
    r = size * 0.27
    red = (255, 59, 48)
    draw.ellipse((x + size * 0.02, y + size * 0.10, x + size * 0.02 + 2 * r, y + size * 0.10 + 2 * r), fill=red)
    draw.ellipse((x + size * 0.98 - 2 * r, y + size * 0.10, x + size * 0.98, y + size * 0.10 + 2 * r), fill=red)
    draw.polygon([(x + size * 0.03, y + size * 0.44), (x + size * 0.97, y + size * 0.44), (x + size * 0.5, y + size * 0.95)], fill=red)


def size_for(shape: tuple[int, int] | None) -> tuple[int, int]:
    """The size to draw the screen at for a phone whose screen is `shape` (width, height) in
    the picture: as wide as a phone screenshot, as tall as that phone is. A drawn phone is
    often shorter than a real one, and a screen taller than the phone loses its top and its
    bottom (the time and the battery, half cut off)."""
    if not shape or shape[0] <= 0 or shape[1] <= 0:
        return SIZE
    return SIZE[0], max(1700, min(2800, int(round(SIZE[0] * shape[1] / shape[0]))))


def _status_bar(d, S, w: int, ink) -> None:
    """The top of the phone: the time, the dark pill in the middle, then signal, wifi and
    battery. Everything sits well inside the screen's round corners."""
    mid = 98                                                 # the row's centre line
    d.text((S(196), S(mid)), "11:47", font=_font(FONT_BOLD, S(50)), fill=ink, anchor="mm")
    d.rounded_rectangle((S(w // 2 - 178), S(mid - 54), S(w // 2 + 178), S(mid + 54)), radius=S(54), fill=(0, 0, 0))
    # signal: four bars, each taller than the last
    x = w - 314
    for i, bar in enumerate((14, 21, 28, 36)):
        d.rounded_rectangle((S(x + i * 15), S(mid + 18 - bar), S(x + i * 15 + 10), S(mid + 18)), radius=S(3), fill=ink)
    # wifi: three arcs over a dot
    cx, cy = w - 216, mid + 17
    for r in (40, 27):
        d.arc((S(cx - r), S(cy - r), S(cx + r), S(cy + r)), 225, 315, fill=ink, width=S(8))
    d.pieslice((S(cx - 15), S(cy - 15), S(cx + 15), S(cy + 15)), 225, 315, fill=ink)
    # battery: an outline, its charge, the nub
    left = w - 172
    d.rounded_rectangle((S(left), S(mid - 19), S(left + 76), S(mid + 19)), radius=S(11), outline=ink, width=S(4))
    d.rounded_rectangle((S(left + 8), S(mid - 11), S(left + 58), S(mid + 11)), radius=S(5), fill=ink)
    d.rounded_rectangle((S(left + 80), S(mid - 8), S(left + 86), S(mid + 8)), radius=S(3), fill=ink)


def render(texts: dict, out: Path, shown: int | None = None, shape: tuple[int, int] | None = None) -> Path:
    """The chat screen with the first `shown` messages (all of them by default), as a picture
    in the shape of a phone screenshot, or of the phone it goes on (`shape`, see size_for)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise StepError("texts shots need Pillow: pip install -r requirements.txt") from None
    w, h = size_for(shape)
    k = 2                                                    # drawn at twice the size, then scaled down: smooth edges
    img = Image.new("RGB", (w * k, h * k), (255, 255, 255))
    d = ImageDraw.Draw(img)
    S = lambda v: int(v * k)                                 # noqa: E731
    ink, grey, blue, bubble = (17, 17, 17), (142, 142, 147), (0, 122, 255), (233, 233, 235)

    _status_bar(d, S, w, ink)
    # who it is from: a back arrow, a round picture with their initial, the name
    d.line([(S(98), S(262)), (S(70), S(292)), (S(98), S(322))], fill=blue, width=S(9), joint="curve")
    cx, cy, r = w // 2, 280, 66
    d.ellipse((S(cx - r), S(cy - r), S(cx + r), S(cy + r)), fill=(160, 164, 176))
    initial = texts["from"][:1].upper()
    f_init = _font(FONT_BOLD, S(64))
    d.text((S(cx), S(cy)), initial, font=f_init, fill=(255, 255, 255), anchor="mm")
    d.text((S(cx), S(cy + r + 44)), texts["from"], font=_font(FONT, S(38)), fill=ink, anchor="mm")
    d.line([(0, S(450)), (S(w), S(450))], fill=(226, 226, 230), width=S(2))
    # the box to write in, and the bar at the bottom
    d.rounded_rectangle((S(150), S(h - 300), S(w - 60), S(h - 196)), radius=S(52), outline=(200, 200, 205), width=S(3))
    d.text((S(196), S(h - 248)), "Message", font=_font(FONT, S(44)), fill=grey, anchor="lm")
    d.ellipse((S(48), S(h - 288), S(128), S(h - 208)), fill=(233, 233, 235))
    d.line([(S(88), S(h - 268)), (S(88), S(h - 228))], fill=grey, width=S(6))
    d.line([(S(68), S(h - 248)), (S(108), S(h - 248))], fill=grey, width=S(6))
    d.rounded_rectangle((S(w // 2 - 200), S(h - 60), S(w // 2 + 200), S(h - 44)), radius=S(8), fill=ink)

    # the messages, newest at the bottom
    font = _font(FONT, S(64))
    pad_x, pad_y, gap, line_h = S(40), S(30), S(18), S(84)
    count = len(texts["messages"]) if shown is None else max(0, min(shown, len(texts["messages"])))
    boxes = []
    for text in texts["messages"][:count]:
        lines = _wrap(d, text, font, S(int(w * 0.70)))
        bw = max(_width(d, ln, font) for ln in lines) + 2 * pad_x
        boxes.append((lines, bw, len(lines) * line_h + 2 * pad_y))
    y = S(h - 350) - sum(bh for _, _, bh in boxes) - gap * max(0, len(boxes) - 1)
    space = d.textlength(" ", font=font)
    for lines, bw, bh in boxes:
        x0 = S(54)
        d.rounded_rectangle((x0, y, x0 + bw, y + bh), radius=S(52), fill=bubble)
        ty = y + pad_y
        for ln in lines:
            tx = x0 + pad_x
            for piece in ln:
                if piece == HEART:
                    _heart(d, tx, ty + line_h * 0.14, font.size * 0.92)
                    tx += font.size + space
                else:
                    d.text((tx, ty + line_h / 2), piece, font=font, fill=ink, anchor="lm")
                    tx += d.textlength(piece, font=font) + space
            ty += line_h
        y += bh + gap
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.resize((w, h), Image.Resampling.LANCZOS).save(out)
    return out
