"""Iro explains: a 40 to 55 second lesson drawn in code. Iro stands at the bottom and talks; above
him a title and one card per point build on the word being said.

    hook    one line that names the problem, in giant letters
    points  three or four: a label, a short title, and a card that acts the point out
    close   the line that pays the hook off, and the words to search for

A card is one of:

    compare   a weak prompt and a strong one, typed in, a cross and a tick
    list      two to four things, ticked as they are said
    type      one prompt typed into a chat box
    rule      one sentence in big letters, with a stamp
    number    a number that counts up, and what it counts
    steps     two to four steps in a row, lit one after another

Nothing here calls a picture or a clip model. The narrator's words set the timing (stickstory.plan);
every reveal is placed on the word it belongs to when that word can be found in the line.

    check_lesson(lesson)              what is wrong with a lesson, before anything is drawn
    plan(lesson, voice=None)          when every part and every word happens
    frame(lesson, t, timing)          one frame as a picture
    cues(lesson, timing)              the pops and swishes, for story_sound.mix
    render(lesson, out, timing, audio)

The look is VidGen's own: pale graph paper, navy ink, white cards with a hard shadow, and Iro's orange.
"""

from __future__ import annotations

import math
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import stickstory
from common import StepError
from contrast import _font, _iro_source, back_out, clamp, lerp, mix, smooth, span

W, H, FPS = 1080, 1920, 30
SS = 2
PAPER, GRID = (240, 243, 249), (222, 228, 241)
INK, MUTED = (18, 24, 58), (112, 120, 152)
ORANGE, TEAL, CORAL = (255, 150, 31), (16, 172, 146), (238, 82, 74)
CARD, SOFT = (255, 255, 255), (229, 234, 246)
TITLE_FONT = "assets/fonts/Poppins-Black.ttf"
TEXT_FONT = "assets/fonts/Inter-SemiBold.otf"

LEFT, RIGHT = 70, 1010                 # the column everything sits in
LABEL_Y = 262                          # under the strip the apps cover at the top
TITLE_TOP = 330
CARD_TOP, CARD_BOTTOM = 650, 1130
BUBBLE_TOP, BUBBLE_BOTTOM = 1160, 1296
IRO_X, IRO_FEET, IRO_H = 226, 1596, 268
TAIL = 1.3                             # the last picture holds this long after the last word

CARDS = {
    "compare": "a weak prompt and a strong one: bad, good (and bad_label, good_label)",
    "list": "two to four things ticked as they are said: items",
    "type": "one prompt typed into a chat box: text (and label)",
    "rule": "one sentence in big letters with a stamp: text (and stamp)",
    "number": "a number that counts up: value, label (and suffix)",
    "steps": "two to four steps in a row: items",
}
POINTS_MIN, POINTS_MAX = 2, 5
SAY_MAX_WORDS = 34
TITLE_MAX_WORDS, TITLE_MAX_CHARS = 5, 34
LABEL_MAX_CHARS = 22
ITEM_MAX_CHARS = 30
PROMPT_MAX_CHARS = 120
RULE_MAX_CHARS = 70
WORDS_MIN, WORDS_MAX = 70, 135


# ------------------------------------------------------------------- the lesson ----

def _t(v) -> str:
    return " ".join(str(v or "").split())


def clean_card(raw) -> dict | None:
    if not isinstance(raw, dict) or not raw.get("type"):
        return None
    kind = str(raw["type"]).strip().lower()
    out = {"type": kind}
    if kind == "compare":
        out.update(bad=_t(raw.get("bad")), good=_t(raw.get("good")),
                   bad_label=_t(raw.get("bad_label") or "VAGUE").upper(), good_label=_t(raw.get("good_label") or "CLEAR").upper())
    elif kind in ("list", "steps"):
        out["items"] = [_t(x) for x in (raw.get("items") if isinstance(raw.get("items"), list) else []) if _t(x)]
    elif kind == "type":
        out.update(text=_t(raw.get("text")), label=_t(raw.get("label") or "TRY THIS").upper())
    elif kind == "rule":
        out.update(text=_t(raw.get("text")), stamp=_t(raw.get("stamp")).upper())
    elif kind == "number":
        out.update(value=raw.get("value"), suffix=str(raw.get("suffix") or "").strip(), label=_t(raw.get("label")))
    return out


def clean_lesson(raw: dict) -> dict:
    """A lesson with its words tidied and every default filled in."""
    e = raw if isinstance(raw, dict) else {}
    hook = e.get("hook") if isinstance(e.get("hook"), dict) else {}
    close = e.get("close") if isinstance(e.get("close"), dict) else {}
    points = []
    for p in (e.get("points") if isinstance(e.get("points"), list) else []):
        p = p if isinstance(p, dict) else {}
        item = {"label": _t(p.get("label")).upper(), "title": _t(p.get("title")).upper(), "accent": _t(p.get("accent")).upper(),
                "say": _t(p.get("say")), "card": clean_card(p.get("card"))}
        item["note"] = _t(p.get("note") or p.get("label")).upper()
        points.append(item)
    return {"title": _t(e.get("title"))[:70], "caption": _t(e.get("caption")),
            "hook": {"say": _t(hook.get("say")), "title": _t(hook.get("title")).upper(), "kicker": _t(hook.get("kicker")).upper(),
                     "stamp": _t(hook.get("stamp")).upper()},
            "points": points,
            "close": {"say": _t(close.get("say")), "title": _t(close.get("title")).upper()}}


def segments(lesson: dict) -> list[dict]:
    """The parts of a lesson in the order they are said: the hook, each point, the close."""
    out = [{"kind": "hook", **lesson["hook"]}]
    out += [{"kind": "point", "n": k + 1, **p} for k, p in enumerate(lesson["points"])]
    out.append({"kind": "close", **lesson["close"]})
    return out


def _check_card(card: dict | None, where: str) -> list[str]:
    if card is None:
        return [f"{where}: a point needs a card"]
    kind = card["type"]
    if kind not in CARDS:
        return [f"{where}: a card is one of {', '.join(CARDS)}, got {kind!r}"]
    out = []
    if kind == "compare":
        for side in ("bad", "good"):
            if not card[side]:
                out.append(f"{where}: the compare card needs its {side} line")
            elif len(card[side]) > PROMPT_MAX_CHARS:
                out.append(f"{where}: the {side} line is at most {PROMPT_MAX_CHARS} letters")
        for side in ("bad_label", "good_label"):
            if len(card[side]) > 14:
                out.append(f"{where}: {side} is at most 14 letters")
    elif kind in ("list", "steps"):
        n = len(card["items"])
        if not 2 <= n <= 4:
            out.append(f"{where}: a {kind} card has 2 to 4 items, this one has {n}")
        limit = ITEM_MAX_CHARS if kind == "list" else 16
        for item in card["items"]:
            if len(item) > limit:
                out.append(f"{where}: {item!r} is too long for a {kind} card (at most {limit} letters)")
    elif kind == "type":
        if not card["text"]:
            out.append(f"{where}: the type card needs its text")
        elif len(card["text"]) > PROMPT_MAX_CHARS:
            out.append(f"{where}: the typed text is at most {PROMPT_MAX_CHARS} letters")
    elif kind == "rule":
        if not card["text"]:
            out.append(f"{where}: the rule card needs its text")
        elif len(card["text"]) > RULE_MAX_CHARS:
            out.append(f"{where}: a rule is at most {RULE_MAX_CHARS} letters")
        if len(card["stamp"]) > 12:
            out.append(f"{where}: a stamp is at most 12 letters")
    elif kind == "number":
        v = card["value"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 9999:
            out.append(f"{where}: the number card needs a value from 0 to 9999, got {v!r}")
        if not card["label"]:
            out.append(f"{where}: the number card needs a label saying what it counts")
        elif len(card["label"]) > 44:
            out.append(f"{where}: the number's label is at most 44 letters")
        if len(card["suffix"]) > 4:
            out.append(f"{where}: the number's suffix is at most 4 letters")
    return out


def check_lesson(raw: dict) -> list[str]:
    """What is wrong with a lesson. An empty list means it can be drawn."""
    lesson = clean_lesson(raw)
    out = []
    hook, close, points = lesson["hook"], lesson["close"], lesson["points"]
    if not hook["say"]:
        out.append("the hook needs a line for Iro to say")
    if not hook["title"]:
        out.append("the hook needs a title (the few words shown in giant letters)")
    elif len(hook["title"].split()) > 6 or len(hook["title"]) > 40:
        out.append("the hook's title is at most 6 words and 40 letters")
    if len(hook["kicker"]) > 30:
        out.append("the hook's kicker is at most 30 letters")
    if len(hook["stamp"]) > 12:
        out.append("the hook's stamp is at most 12 letters")
    if not POINTS_MIN <= len(points) <= POINTS_MAX:
        out.append(f"a lesson has {POINTS_MIN} to {POINTS_MAX} points, this one has {len(points)}")
    for n, p in enumerate(points, 1):
        where = f"point {n}"
        if not p["say"]:
            out.append(f"{where}: Iro needs a line to say")
        elif len(p["say"].split()) > SAY_MAX_WORDS:
            out.append(f"{where}: the line is {len(p['say'].split())} words; keep a point to {SAY_MAX_WORDS}")
        if not p["title"]:
            out.append(f"{where}: needs a title")
        elif len(p["title"].split()) > TITLE_MAX_WORDS or len(p["title"]) > TITLE_MAX_CHARS:
            out.append(f"{where}: the title is at most {TITLE_MAX_WORDS} words and {TITLE_MAX_CHARS} letters, got {p['title']!r}")
        if len(p["label"]) > LABEL_MAX_CHARS:
            out.append(f"{where}: the label is at most {LABEL_MAX_CHARS} letters")
        if p["accent"] and p["accent"] not in p["title"]:
            out.append(f"{where}: the accent {p['accent']!r} must be words from the title")
        out += _check_card(p["card"], where)
    if not close["say"]:
        out.append("the close needs a line for Iro to say")
    if len(close["title"].split()) > 7 or len(close["title"]) > 44:
        out.append("the close's title is at most 7 words and 44 letters")
    for seg in (hook, close):
        if len(seg["say"].split()) > SAY_MAX_WORDS:
            out.append(f"a line is at most {SAY_MAX_WORDS} words")
    return out


def lines(lesson: dict) -> dict:
    """The lesson as the thing stickstory.plan and story_sound.narrate read: one line a part."""
    return {"shots": [{"say": s["say"]} for s in segments(clean_lesson(lesson))]}


def plan(raw: dict, voice: dict | None = None) -> dict:
    """When every part and every word happens (from the voice, or at an even pace)."""
    return stickstory.plan(lines(raw), voice, tail=TAIL)


# ------------------------------------------------------------ what happens when ----

def _norm(word: str) -> str:
    return re.sub(r"[^a-z0-9']", "", word.lower())


def _cue_times(texts: list[str], words: list[dict], t0: float, t1: float, first: float = 0.18, last: float = 0.86) -> list[float]:
    """When each of `texts` shows up in a part that runs t0 to t1: on the word of the line that
    names it when there is one, in order, else spread evenly."""
    n = len(texts)
    if n == 0:
        return []
    even = [lerp(t0 + (t1 - t0) * first, t0 + (t1 - t0) * last, k / max(1, n - 1)) if n > 1 else t0 + (t1 - t0) * 0.35 for k in range(n)]
    out, at = [], 0
    for k, text in enumerate(texts):
        keys = [_norm(w) for w in text.split()]
        keys = [w for w in keys if len(w) > 3] or [w for w in keys if w]
        found = None
        for j in range(at, len(words)):
            if _norm(words[j]["say"]) in keys:
                found = j
                break
        if found is None:
            out.append(None)
        else:
            out.append(float(words[found]["t"]))
            at = found + 1
    # a cue that is missing, or out of order, falls back to its even place between its neighbours
    times, floor = [], t0
    for k in range(n):
        t = out[k]
        if t is None or t < floor:
            t = max(even[k], floor)
        times.append(min(t, t1 - 0.15))
        floor = times[-1] + 0.12
    return times


def beats(raw: dict, timing: dict) -> list[dict]:
    """For every part: when it starts and ends, and when each thing in it happens."""
    lesson = clean_lesson(raw)
    out = []
    for i, (seg, when) in enumerate(zip(segments(lesson), timing["shots"])):
        t0, t1 = when["start"], when["end"]
        words = [w for w in timing["words"] if w["shot"] == i]
        said = words[-1]["end"] if words else t1
        b = {"kind": seg["kind"], "t0": t0, "t1": t1, "said": said}
        if seg["kind"] == "hook":
            b["words"] = _cue_times(seg["title"].split(), words, t0, min(t1, said), 0.04, 0.6)
            b["words"][0] = min(b["words"][0], t0 + 0.12)            # something is on screen at once
            b["stamp"] = min(said, max(b["words"][-1] + 0.35, t0 + (said - t0) * 0.72)) if seg["stamp"] else None
        elif seg["kind"] == "point":
            card = seg["card"] or {"type": ""}
            b["title"] = t0 + 0.08
            b["card"] = t0 + 0.34
            kind = card["type"]
            if kind in ("list", "steps"):
                b["items"] = _cue_times(card["items"], words, t0 + 0.5, said, 0.12, 0.9)
            elif kind == "compare":
                span_ = max(0.8, said - t0 - 0.5)
                b["bad"] = (t0 + 0.5, t0 + 0.5 + span_ * 0.32)
                b["cross"] = t0 + 0.5 + span_ * 0.40
                b["good"] = (t0 + 0.5 + span_ * 0.50, t0 + 0.5 + span_ * 0.86)
                b["tick"] = t0 + 0.5 + span_ * 0.92
            elif kind == "type":
                b["typed"] = (t0 + 0.6, max(t0 + 1.2, said - 0.5))
                b["send"] = max(t0 + 1.3, said - 0.3)
            elif kind == "rule":
                b["stamp"] = max(t0 + 0.9, t0 + (said - t0) * 0.62) if card.get("stamp") else None
            elif kind == "number":
                b["count"] = (t0 + 0.5, t0 + 1.6)
            b["note"] = lerp(t0, t1, 0.7)
        else:
            b["title"] = t0 + 0.08
            b["tag"] = t0 + max(0.5, (said - t0) * 0.45)
        out.append(b)
    return out


def cues(raw: dict, timing: dict) -> list[tuple[float, str, float]]:
    """The sounds of a lesson: a swish on every change of part, a pop on every reveal, a thud on
    every stamp. For story_sound.mix."""
    out = []
    for k, b in enumerate(beats(raw, timing)):
        if k:
            out.append((max(0.0, b["t0"] - 0.12), "swish", 0.32))
        if b["kind"] == "hook":
            out.append((b["words"][0], "pop", 0.5))
            if b.get("stamp") is not None:
                out.append((b["stamp"], "thud", 0.55))
        elif b["kind"] == "point":
            for t in b.get("items", []):
                out.append((t, "pop", 0.45))
            for key in ("cross", "tick", "send"):
                if key in b:
                    out.append((b[key], "pop", 0.5))
            if b.get("stamp") is not None:
                out.append((b["stamp"], "thud", 0.55))
        else:
            out.append((b["tag"], "pop", 0.55))
    out.sort()
    return out[:18]


# ----------------------------------------------------------------------- drawing ----

class Canvas:
    """One frame, drawn at SS times the size. Everything is given in final pixels."""

    def __init__(self):
        from PIL import ImageDraw
        self.im = _paper().copy()
        self.d = ImageDraw.Draw(self.im)

    def box(self, x0, y0, x1, y1, fill=None, outline=None, width: float = 0, radius: float = 0):
        if x1 - x0 < 1 or y1 - y0 < 1:
            return
        self.d.rounded_rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], radius * SS, fill=fill, outline=outline, width=int(width * SS))

    def card(self, x0, y0, x1, y1, fill=CARD, radius: float = 26, shadow: float = 12, border: float = 5):
        self.box(x0 + shadow, y0 + shadow, x1 + shadow, y1 + shadow, fill=INK, radius=radius)
        self.box(x0, y0, x1, y1, fill=fill, outline=INK, width=border, radius=radius)

    def line(self, pts, fill, width: float):
        self.d.line([(x * SS, y * SS) for x, y in pts], fill=fill, width=max(1, int(width * SS)), joint="curve")

    def dot(self, x, y, r, fill, outline=None, width: float = 0):
        self.d.ellipse([(x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS], fill=fill, outline=outline, width=int(width * SS))

    def poly(self, pts, fill):
        self.d.polygon([(x * SS, y * SS) for x, y in pts], fill=fill)

    def font(self, path: str, size: float):
        return _font(path, int(round(size * SS)))

    def width(self, words: str, font) -> float:
        return self.d.textlength(words, font=font) / SS

    def text(self, x, y, words: str, font, fill, anchor: str = "ls"):
        self.d.text((x * SS, y * SS), words, font=font, fill=fill, anchor=anchor)

    def wrap(self, words: str, font, max_w: float) -> list[str]:
        out, cur = [], ""
        for w in words.split():
            trial = f"{cur} {w}".strip()
            if cur and self.width(trial, font) > max_w:
                out.append(cur)
                cur = w
            else:
                cur = trial
        return out + ([cur] if cur else [])

    def flat(self):
        return self.im.reduce(SS)


@lru_cache(maxsize=1)
def _paper():
    """Pale graph paper, at drawing size."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (W * SS, H * SS), PAPER)
    d = ImageDraw.Draw(im)
    step = 54 * SS
    for x in range(0, W * SS, step):
        d.line([(x, 0), (x, H * SS)], fill=GRID, width=SS)
    for y in range(0, H * SS, step):
        d.line([(0, y), (W * SS, y)], fill=GRID, width=SS)
    return im


def _ink(k: float, color=INK):
    """A colour that is still coming out of the paper (`k` from 0 to 1)."""
    return mix(PAPER, color, clamp(k))


def _fit_title(c: Canvas, words: str, sizes: tuple, max_w: float, max_lines: int, max_h: float = 9999):
    """The biggest size at which a title fits its lines and its height. Returns (font size, lines)."""
    for size in sizes:
        font = c.font(TITLE_FONT, size)
        lines_ = c.wrap(words, font, max_w)
        if len(lines_) <= max_lines and len(lines_) * size * 1.04 <= max_h and all(c.width(l, font) <= max_w for l in lines_):
            return size, lines_
    font = c.font(TITLE_FONT, sizes[-1])
    return sizes[-1], c.wrap(words, font, max_w)[:max_lines]


def _title(c: Canvas, words: str, accent: str, t: float, at: float, top: float = TITLE_TOP, max_lines: int = 2, max_h: float = 292):
    """A title that drops in, with a marker stroke drawn behind its accent words."""
    k = span(t, at, at + 0.2)
    if k <= 0 or not words:
        return
    size, rows = _fit_title(c, words, (150, 132, 116, 100, 88, 76, 64), RIGHT - LEFT, max_lines, max_h)
    font = c.font(TITLE_FONT, size)
    drop = (1 - back_out(k)) * -46
    accent_words = set(accent.split()) if accent else set()
    mark = smooth(span(t, at + 0.16, at + 0.44))
    y = top + size * 0.92 + drop
    for row in rows:
        x = LEFT
        for word in row.split():
            wd = c.width(word, font)
            if word in accent_words and mark > 0:
                c.box(x - 10, y - size * 0.80, x - 10 + (wd + 20) * mark, y + size * 0.10, fill=ORANGE, radius=10)
            c.text(x, y, word, font, _ink(k))
            x += wd + c.width(" ", font)
        y += size * 1.04
    return y


def _mark(c: Canvas, x: float, y: float, r: float, good: bool, k: float):
    """A tick or a cross in a disc, popping in."""
    if k <= 0:
        return
    s = back_out(clamp(k))
    r *= s
    c.dot(x, y, r, TEAL if good else CORAL, outline=INK, width=4)
    if good:
        c.line([(x - r * 0.46, y + r * 0.02), (x - r * 0.12, y + r * 0.36), (x + r * 0.48, y - r * 0.34)], (255, 255, 255), r * 0.22)
    else:
        c.line([(x - r * 0.36, y - r * 0.36), (x + r * 0.36, y + r * 0.36)], (255, 255, 255), r * 0.22)
        c.line([(x + r * 0.36, y - r * 0.36), (x - r * 0.36, y + r * 0.36)], (255, 255, 255), r * 0.22)


def _typed(text: str, k: float) -> str:
    return text[:int(round(len(text) * clamp(k)))]


def _tag(c: Canvas, x: float, y: float, words: str, color):
    font = c.font(TEXT_FONT, 28)
    wd = sum(c.width(ch, font) for ch in words) + 4 * (len(words) - 1)
    c.box(x, y - 34, x + wd + 32, y + 12, fill=color, radius=10)
    cx = x + 16
    for ch in words:
        c.text(cx, y, ch, font, (255, 255, 255))
        cx += c.width(ch, font) + 4


def _card(c: Canvas, card: dict, b: dict, t: float):
    """One point's card. Returns the stamps to lay on top afterwards (they are turned, so they are
    drawn at final size): [(words, x, y, how far in)]."""
    kind = card["type"]
    rise = (1 - back_out(span(t, b["card"], b["card"] + 0.3))) * 70
    if t < b["card"]:
        return []
    stamps = []
    if kind == "compare":
        y0 = CARD_TOP + rise
        font = c.font(TEXT_FONT, 42)
        for row, (key, label, color, fill, mark_key, good) in enumerate((("bad", card["bad_label"], CORAL, SOFT, "cross", False),
                                                                          ("good", card["good_label"], TEAL, CARD, "tick", True))):
            top = y0 + row * 250
            t_a, t_b = b[key]
            if row == 1 and t < t_a - 0.15:
                continue
            c.card(LEFT, top, RIGHT - 30, top + 228, fill=fill)
            _tag(c, LEFT + 28, top + 56, label, color)
            shown = _typed(card[key], span(t, t_a, t_b))
            for n, line in enumerate(c.wrap(shown, font, RIGHT - LEFT - 130)[:3]):
                c.text(LEFT + 30, top + 110 + n * 50, line, font, INK if good else MUTED)
            _mark(c, RIGHT - 44, top + 36, 38, good, span(t, b[mark_key], b[mark_key] + 0.22))
    elif kind == "list":
        items = card["items"]
        height = 76 + len(items) * 96
        y0 = (CARD_TOP + CARD_BOTTOM - height) / 2 + rise
        c.card(LEFT, y0, RIGHT - 30, y0 + height)
        font = c.font(TEXT_FONT, 46)
        for n, (item, at) in enumerate(zip(items, b["items"])):
            k = span(t, at, at + 0.2)
            y = y0 + 96 + n * 96
            done = span(t, at + 0.14, at + 0.34)
            c.box(LEFT + 36, y - 46, LEFT + 92, y + 10, fill=TEAL if done > 0 else CARD, outline=INK, width=4, radius=12)
            if done > 0:
                r = 28 * back_out(done)
                cx, cy = LEFT + 64, y - 18
                c.line([(cx - r * 0.46, cy + r * 0.02), (cx - r * 0.12, cy + r * 0.36), (cx + r * 0.5, cy - r * 0.36)], (255, 255, 255), 7)
            c.text(LEFT + 118 + math.sin(clamp(k) * math.pi) * 14, y, item, font, mix((176, 182, 204), INK, k))
    elif kind == "steps":
        items = card["items"]
        n = len(items)
        y0 = (CARD_TOP + CARD_BOTTOM) / 2 - 130 + rise
        gap = 26
        wd = (RIGHT - 30 - LEFT - gap * (n - 1)) / n
        font = c.font(TITLE_FONT, 44 if n <= 3 else 36)
        small = c.font(TEXT_FONT, 30)
        for k_, (item, at) in enumerate(zip(items, b["items"])):
            x0 = LEFT + k_ * (wd + gap)
            lit = span(t, at, at + 0.22)
            pop = (1 - back_out(lit)) * 26 if lit > 0 else 0
            c.card(x0, y0 + pop, x0 + wd, y0 + 230 + pop, fill=mix(SOFT, ORANGE, smooth(lit)), radius=22, shadow=9)
            c.text(x0 + 24, y0 + 62 + pop, f"STEP {k_ + 1}", small, mix(MUTED, INK, lit))
            rows = c.wrap(item.upper(), font, wd - 40)[:2]
            for r_, row in enumerate(rows):
                c.text(x0 + 24, y0 + 136 + r_ * 50 + pop, row, font, INK)
    elif kind == "type":
        y0 = CARD_TOP + 60 + rise
        c.card(LEFT, y0, RIGHT - 30, y0 + 330)
        _tag(c, LEFT + 28, y0 + 60, card["label"], ORANGE)
        font = c.font(TEXT_FONT, 46)
        shown = _typed(card["text"], span(t, *b["typed"]))
        rows = c.wrap(shown, font, RIGHT - LEFT - 200)[:4]
        for n, line in enumerate(rows):
            c.text(LEFT + 30, y0 + 128 + n * 56, line, font, INK)
        if t < b["typed"][1] + 0.4 and int(t * 3) % 2 == 0:               # the caret
            last = rows[-1] if rows else ""
            cx = LEFT + 34 + c.width(last, font)
            cy = y0 + 128 + (max(1, len(rows)) - 1) * 56
            c.box(cx, cy - 44, cx + 5, cy + 8, fill=ORANGE)
        sent = span(t, b["send"], b["send"] + 0.2)
        r = 42 * (1 + 0.16 * math.sin(sent * math.pi))
        c.dot(RIGHT - 96, y0 + 262, r, ORANGE if sent > 0 else SOFT, outline=INK, width=4)
        c.line([(RIGHT - 96, y0 + 284), (RIGHT - 96, y0 + 242)], INK, 7)
        c.line([(RIGHT - 114, y0 + 258), (RIGHT - 96, y0 + 240), (RIGHT - 78, y0 + 258)], INK, 7)
    elif kind == "rule":
        font = c.font(TITLE_FONT, 70)
        rows = c.wrap(card["text"].upper(), font, RIGHT - LEFT - 110)[:4]
        height = 110 + len(rows) * 84
        y0 = (CARD_TOP + CARD_BOTTOM - height) / 2 + rise
        c.card(LEFT, y0, RIGHT - 30, y0 + height)
        c.box(LEFT + 5, y0 + 5, LEFT + 26, y0 + height - 5, fill=ORANGE, radius=0)
        for n, row in enumerate(rows):
            c.text(LEFT + 58, y0 + 124 + n * 84, row, font, INK)
        if card.get("stamp") and b.get("stamp") is not None and t >= b["stamp"]:
            stamps.append((card["stamp"], RIGHT - 200, y0 + height - 6, span(t, b["stamp"], b["stamp"] + 0.2)))
    elif kind == "number":
        y0 = CARD_TOP + 50 + rise
        c.card(LEFT, y0, RIGHT - 30, y0 + 380)
        k = smooth(span(t, *b["count"]))
        value = card["value"]
        shown = f"{value * k:.1f}" if isinstance(value, float) and not float(value).is_integer() else str(int(round(value * k)))
        font = c.font(TITLE_FONT, 210)
        c.text(LEFT + 44, y0 + 232, shown, font, ORANGE)
        wd = c.width(shown, font)
        if card["suffix"]:
            c.text(LEFT + 54 + wd, y0 + 232, card["suffix"], c.font(TITLE_FONT, 110), INK)
        lab = c.font(TEXT_FONT, 44)
        for n, row in enumerate(c.wrap(card["label"], lab, RIGHT - LEFT - 120)[:2]):
            c.text(LEFT + 48, y0 + 300 + n * 52, row, lab, INK)
    return stamps


def _bubble(c: Canvas, timing: dict, t: float):
    """Iro's speech bubble with the words he is saying, three at a time."""
    c.card(60, BUBBLE_TOP, 950, BUBBLE_BOTTOM, radius=34, shadow=9)
    c.poly([(196, BUBBLE_BOTTOM - 4), (268, BUBBLE_BOTTOM - 4), (220, BUBBLE_BOTTOM + 46)], INK)
    c.poly([(204, BUBBLE_BOTTOM - 8), (258, BUBBLE_BOTTOM - 8), (222, BUBBLE_BOTTOM + 32)], CARD)
    for g in timing["groups"]:
        if not g["start"] <= t < g["end"]:
            continue
        words = [timing["words"][k] for k in g["words"]]
        shown = [stickstory._say(w["say"]) for w in words]
        if not any(shown):
            return
        size = 78
        font = c.font(TITLE_FONT, size)
        while size > 46 and c.width(" ".join(shown), font) > 820:
            size -= 4
            font = c.font(TITLE_FONT, size)
        total = c.width(" ".join(shown), font)
        x = 505 - total / 2
        current = max((k for k, w in enumerate(words) if w["t"] <= t + 0.02), default=0)
        y = (BUBBLE_TOP + BUBBLE_BOTTOM) / 2 + size * 0.34
        for k, s in enumerate(shown):
            c.text(x, y, s, font, ORANGE if k == current else INK)
            x += c.width(s, font) + c.width(" ", font)
        return


def _speaking(timing: dict, t: float) -> bool:
    return any(w["t"] <= t < w["end"] + 0.05 for w in timing["words"])


@lru_cache(maxsize=16)
def _iro(height: int, squash: int):
    """Iro at a height, squashed to `squash` percent of it (and a little wider)."""
    from PIL import Image
    src = _iro_source()
    h = max(8, int(height * squash / 100))
    w = max(8, int(src.width * height / src.height * (2 - squash / 100) ** 0.6))
    return src.resize((w, h), Image.Resampling.BILINEAR)


@lru_cache(maxsize=24)
def _stamp(words: str, color: tuple):
    """A stamp as a picture: the words in a box, tilted."""
    from PIL import Image, ImageDraw
    font = _font(TITLE_FONT, 76)
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    wd = int(probe.textlength(words, font=font))
    im = Image.new("RGBA", (wd + 96, 150), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([6, 6, im.width - 7, im.height - 7], 18, fill=(255, 255, 255, 235), outline=color + (255,), width=9)
    d.text((im.width / 2, im.height / 2 + 4), words, font=font, fill=color + (255,), anchor="mm")
    return im.rotate(7, expand=True, resample=Image.Resampling.BICUBIC)


def _lay_stamp(pic, words: str, x: float, y: float, k: float, color=CORAL):
    """Put a stamp on the finished frame, centred on (x, y), slamming down as `k` goes to 1."""
    from PIL import Image
    if k <= 0:
        return
    im = _stamp(words, color)
    scale = 1 + 0.75 * (1 - smooth(clamp(k)))
    if scale > 1.01:
        im = im.resize((int(im.width * scale), int(im.height * scale)), Image.Resampling.BILINEAR)
    if k < 1:
        im = im.copy()
        im.putalpha(im.getchannel("A").point(lambda v: int(v * clamp(0.3 + 0.7 * k))))
    pic.paste(im, (int(x - im.width / 2), int(y - im.height / 2)), im)


def frame(raw: dict, t: float, timing: dict | None = None, end_tag: str = "SEARCH IRO AI", bubble: bool = True):
    """One frame of a lesson at `t` seconds, as an RGB picture. `bubble=False` leaves Iro's speech
    bubble out (for a cover, where half a sentence reads as a mistake)."""
    from PIL import Image
    lesson = clean_lesson(raw)
    timing = timing or plan(lesson)
    segs = segments(lesson)
    t = clamp(t, 0.0, max(0.0, timing["total"] - 1 / FPS))
    i = stickstory._shot_at(timing, t)
    seg, b = segs[i], beats(lesson, timing)[i]
    c = Canvas()
    stamps = []
    out_k = span(t, b["t1"] - 0.16, b["t1"]) if i < len(segs) - 1 else 0.0       # the part leaves upward
    lift = -smooth(out_k) * 60
    if seg["kind"] == "hook":
        if seg["kicker"]:
            c.text(LEFT, 420 + lift, seg["kicker"], c.font(TEXT_FONT, 50), _ink(span(t, b["t0"], b["t0"] + 0.2), MUTED))
        size, rows = _fit_title(c, seg["title"], (210, 190, 170, 150, 132, 116, 100, 88), RIGHT - LEFT, 4, 620)
        font = c.font(TITLE_FONT, size)
        y, n = 470 + size * 0.9 + lift, 0
        widths = [c.width(row, font) for row in rows]
        short = min(range(len(rows)), key=lambda r_: widths[r_])
        stamp_at = (min(RIGHT - 170, max(LEFT + widths[short] + 210, 700)), 470 + size * 0.5 + short * size * 1.02 + lift)
        if widths[short] > RIGHT - LEFT - 380:                       # no room beside any line: under the title
            stamp_at = (RIGHT - 200, min(1070, 470 + len(rows) * size * 1.02 + 70) + lift)
        for row in rows:
            x = LEFT
            for word in row.split():
                at = b["words"][min(n, len(b["words"]) - 1)]
                k = span(t, at, at + 0.16)
                if k > 0:
                    c.text(x, y + (1 - back_out(k)) * -50, word, font, _ink(k, ORANGE if n == len(seg["title"].split()) - 1 else INK))
                x += c.width(word, font) + c.width(" ", font)
                n += 1
            y += size * 1.02
        if seg["stamp"] and b.get("stamp") is not None and t >= b["stamp"]:
            stamps.append((seg["stamp"], stamp_at[0], stamp_at[1], span(t, b["stamp"], b["stamp"] + 0.2)))
    elif seg["kind"] == "point":
        total = len(lesson["points"])
        num = c.font(TITLE_FONT, 38)
        c.text(LEFT, LABEL_Y + 14, f"{seg['n']:02d}", num, ORANGE)
        wd = c.width(f"{seg['n']:02d}", num)
        c.text(LEFT + wd + 12, LABEL_Y + 14, f"/ {total:02d}", c.font(TEXT_FONT, 32), MUTED)
        if seg["label"]:
            lab = c.font(TEXT_FONT, 32)
            x = LEFT + wd + 12 + c.width(f"/ {total:02d}", lab) + 30
            for ch in seg["label"]:
                c.text(x, LABEL_Y + 14, ch, lab, INK)
                x += c.width(ch, lab) + 5
        for k in range(total):                                       # how far through the lesson this is
            x0 = LEFT + k * ((RIGHT - LEFT + 14) / total)
            x1 = x0 + (RIGHT - LEFT + 14) / total - 14
            c.box(x0, LABEL_Y + 34, x1, LABEL_Y + 46, fill=SOFT, radius=6)
            done = 1.0 if k < seg["n"] - 1 else span(t, b["t0"], b["t1"]) if k == seg["n"] - 1 else 0.0
            if done > 0:
                c.box(x0, LABEL_Y + 34, x0 + (x1 - x0) * done, LABEL_Y + 46, fill=ORANGE, radius=6)
        if out_k < 1:
            _title(c, seg["title"], seg["accent"], t, b["title"], TITLE_TOP + lift * 0.6)
            if seg["card"]:
                if out_k > 0:
                    b = dict(b, card=b["card"])
                stamps += _card(c, seg["card"], b, t)
    else:
        _title(c, seg["title"], seg["title"].split()[-1] if seg["title"] else "", t, b["title"], TITLE_TOP + 40, max_lines=3, max_h=450)
        tag = str(end_tag or "").strip().upper()
        k = span(t, b["tag"], b["tag"] + 0.26)
        if tag and k > 0:
            font = c.font(TITLE_FONT, 84)
            wd = c.width(tag, font)
            while wd > RIGHT - LEFT - 120 and font.size > 80:
                font = c.font(TITLE_FONT, font.size / SS - 6)
                wd = c.width(tag, font)
            pop = (1 - back_out(k)) * 70
            y0 = 860 + pop
            c.card(540 - wd / 2 - 54, y0, 540 + wd / 2 + 54, y0 + 170, fill=ORANGE, radius=40, shadow=14, border=6)
            c.text(540, y0 + 88, tag, font, INK, anchor="mm")
    if bubble:
        _bubble(c, timing, t)
    # the notes: every point already made stays on the page beside Iro
    all_beats = beats(lesson, timing)
    notes = [(p["note"], all_beats[k + 1]["note"]) for k, p in enumerate(lesson["points"]) if p["note"]]
    small = c.font(TEXT_FONT, 36)
    row = 0
    for words, at in notes[:4]:
        k = span(t, at, at + 0.22)
        if k <= 0:
            continue
        y = 1384 + row * 62
        x = 424 + (1 - back_out(k)) * 36
        c.dot(x + 20, y - 13, 20, TEAL, outline=INK, width=3)
        c.line([(x + 11, y - 12), (x + 18, y - 4), (x + 30, y - 21)], (255, 255, 255), 4.5)
        c.text(x + 54, y, words[:24], small, _ink(k))
        row += 1
    # the change from one part to the next: a band of ink crosses the page
    for k, bb in enumerate(all_beats[1:], 1):
        u = (t - (bb["t0"] - 0.16)) / 0.34
        if 0 < u < 1:
            x = lerp(-W * 1.15, W * 1.05, smooth(u))
            c.poly([(x, 0), (x + W * 1.05, 0), (x + W * 1.05 - 120, H), (x - 120, H)], INK)
            c.poly([(x + W * 1.05, 0), (x + W * 1.05 + 26, 0), (x + W * 1.05 - 94, H), (x + W * 1.05 - 120, H)], ORANGE)
    pic = c.flat()
    # Iro, who talks: he bobs all the time and bounces on every word
    talk = _speaking(timing, t)
    squash = 100 + (int(round(math.sin(t * 22) * 4)) if talk else 0)
    bob = math.sin(t * 2.4) * 5 + (abs(math.sin(t * 11)) * -8 if talk else 0)
    hop = 0.0
    for bb in all_beats:
        u = (t - bb["t0"]) / 0.36
        if 0 <= u <= 1:
            hop = -math.sin(u * math.pi) * 38
    iro = _iro(IRO_H, squash)
    shadow = Image.new("RGBA", (260, 44), (0, 0, 0, 0))
    from PIL import ImageDraw
    ImageDraw.Draw(shadow).ellipse([0, 0, 259, 43], fill=INK + (46,))
    pic.paste(shadow, (IRO_X - 130, IRO_FEET - 26), shadow)
    pic.paste(iro, (int(IRO_X - iro.width / 2), int(IRO_FEET - iro.height + bob + hop)), iro)
    for words, x, y, k in stamps:
        _lay_stamp(pic, words, x, y, k)
    return pic


# ------------------------------------------------------------------------ videos ----

def render(raw: dict, out: Path, timing: dict | None = None, audio: Path | None = None,
           end_tag: str = "SEARCH IRO AI", workers: int = 4, on_frame=None) -> Path:
    """Draw a lesson and write it to `out` (H.264, with `audio` as its sound or a silent track)."""
    import media
    from concurrent.futures import ThreadPoolExecutor
    lesson = clean_lesson(raw)
    problems = check_lesson(lesson)
    if problems:
        raise StepError("this lesson cannot be drawn: " + "; ".join(problems[:4]))
    timing = timing or plan(lesson)
    media.require_ffmpeg()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.stem + ".part.mp4")
    total = int(round(timing["total"] * FPS))
    _paper()
    cmd = [media.tool_path("ffmpeg"), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if audio and Path(audio).is_file():
        cmd += ["-i", str(audio)]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    cmd += ["-t", f"{total / FPS:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-movflags", "+faststart", str(part)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def one(k: int) -> bytes:
        return frame(lesson, k / FPS, timing, end_tag).tobytes()

    try:
        with media._alive(proc), ThreadPoolExecutor(max(1, int(workers))) as pool:
            step = max(8, int(workers) * 6)
            for start in range(0, total, step):
                for j, data in enumerate(pool.map(one, range(start, min(total, start + step)))):
                    proc.stdin.write(data)
                    if on_frame:
                        on_frame(start + j + 1, total)
            proc.stdin.close()
            err = proc.stderr.read().decode("utf-8", "replace")
            if proc.wait() != 0:
                raise StepError(f"ffmpeg could not write {out.name}: {err.strip()[-300:]}")
    except (BrokenPipeError, OSError) as e:
        err = b""
        try:
            err = proc.stderr.read()
        except (OSError, ValueError):
            pass
        part.unlink(missing_ok=True)
        raise StepError(f"ffmpeg stopped while writing {out.name}: {(err.decode('utf-8', 'replace').strip() or str(e))[-300:]}") from None
    part.replace(out)
    return out
