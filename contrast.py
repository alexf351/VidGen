"""Contrast videos: two kinds of people side by side, a label over each, a ten second silent story
with one prop, and the one on the right wins.

    VAGUE PROMPT            CLEAR PROMPT
       (stands at the foot     (Iro hops up the
        of the stairs)          stairs and glows)

Nothing here calls a picture, clip or voice model. A video is drawn frame by frame with Pillow
and encoded by ffmpeg, so it costs nothing and takes well under a minute. One list of scenes
makes a whole batch (contrast_batch.py):

    {"template": "stairs", "left": "VAGUE PROMPT", "right": "CLEAR PROMPT",
     "caption": "the answer is only as good as the ask. which one are you?"}

    TEMPLATES      stairs | blocks | doors | score : the prop and what each side does with it
    render(scene, out)         one mp4 (1080 x 1920, 30 fps, 10 seconds, a silent sound track)
    frame(scene, t)            one frame as a picture, for checks and previews
    check_scene(scene)         what is wrong with a scene's words, before anything is drawn
    first_second(scene)        problems a viewer would meet in the first second (labels cut off,
                               a side not moving), measured from the frames themselves

The look is VidGen's own: a dark navy stage, a soft white figure on the left, Iro the penguin on
the right. The loser never changes; the winner turns gold in the last two seconds."""

from __future__ import annotations

import math
import subprocess
import threading
from functools import lru_cache
from pathlib import Path

from common import ROOT, StepError

W, H, FPS = 1080, 1920, 30
SECONDS = 10.0
FRAMES = int(SECONDS * FPS)
SS = 2                              # the moving layer is drawn at twice the size and scaled down
BAND_TOP, FLOOR = 300, 1240         # the moving layer covers this strip; FLOOR is where feet stand
BAND_H = FLOOR - BAND_TOP + 10
LX, RX = 280, 800                   # the middle of each side
PAYOFF = 8.0                        # the second the winner turns gold
TAG_AT = 8.5                        # the end tag fades in from here
TAG_Y = 1396                        # its top; above the strip the apps cover with their own text
LABEL_Y = 470                       # the bottom of the labels
LABEL_MAX_W = 452
LABEL_SIZES = (62, 56, 50, 44, 40)

BG_TOP, BG_MID, BG_BOT = (9, 13, 30), (13, 19, 42), (5, 7, 16)
WHITE = (236, 240, 248)
SHADE = (170, 180, 202)
GOLD = (255, 196, 64)
GOLD_DEEP = (255, 150, 30)
SLATE, SLATE_TOP, SLATE_DARK = (52, 62, 96), (84, 97, 142), (36, 43, 70)
CYAN = (70, 214, 236)
LABEL_FONT = "assets/fonts/Poppins-Black.ttf"
TAG_FONT = "assets/fonts/Inter-SemiBold.otf"
IRO_PICTURE = "assets/iro.png"

TEMPLATES = {
    "stairs": "the left one stands at the foot of the stairs looking up; Iro climbs them one step at a time",
    "blocks": "the left one keeps nudging a single block; Iro builds a wall of them and stands on top",
    "doors": "the left one waits in front of one closed door; Iro knocks on door after door until one opens",
    "score": "the left one tries once and stays on a low score; Iro tries again and again until the score is 10",
}
LABEL_MAX_WORDS = 3
LABEL_MAX_CHARS = 22
CAPTION_MAX_CHARS = 180


# ------------------------------------------------------------------ little maths ----

def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def smooth(t: float) -> float:
    t = clamp(t)
    return t * t * (3 - 2 * t)


def span(t: float, a: float, b: float) -> float:
    """0 before a, 1 after b, a straight line between."""
    return clamp((t - a) / (b - a)) if b > a else float(t >= b)


def back_out(t: float) -> float:
    t = clamp(t) - 1
    return t * t * (2.70158 * t + 1.70158) + 1


def mix(c1: tuple, c2: tuple, t: float) -> tuple:
    t = clamp(t)
    return tuple(int(round(lerp(a, b, t))) for a, b in zip(c1, c2))


# ----------------------------------------------------------------------- the stage ----

class Stage:
    """The moving layer of one frame. Everything is given in final pixels (1080 x 1920) and
    drawn at SS times the size."""

    def __init__(self):
        from PIL import Image, ImageDraw
        self.im = Image.new("RGBA", (W * SS, BAND_H * SS), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.im)

    def _p(self, x: float, y: float) -> tuple[float, float]:
        return x * SS, (y - BAND_TOP) * SS

    def rect(self, x0, y0, x1, y1, fill, radius: float = 0):
        a, b = self._p(min(x0, x1), min(y0, y1)), self._p(max(x0, x1), max(y0, y1))
        if b[0] - a[0] < 1 or b[1] - a[1] < 1:
            return
        if radius:
            self.d.rounded_rectangle([a, b], radius * SS, fill=fill)
        else:
            self.d.rectangle([a, b], fill=fill)

    def poly(self, pts, fill):
        self.d.polygon([self._p(x, y) for x, y in pts], fill=fill)

    def dot(self, x, y, r, fill):
        cx, cy = self._p(x, y)
        r *= SS
        self.d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)

    def ring(self, x, y, r, width, fill, start: float = 0, end: float = 360):
        cx, cy = self._p(x, y)
        r *= SS
        self.d.arc([cx - r, cy - r, cx + r, cy + r], start, end, fill=fill, width=int(width * SS))

    def limb(self, x0, y0, x1, y1, width, fill):
        """A thick line with round ends."""
        a, b = self._p(x0, y0), self._p(x1, y1)
        w = width * SS
        self.d.line([a, b], fill=fill, width=int(w))
        for cx, cy in (a, b):
            self.d.ellipse([cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2], fill=fill)

    def paste(self, picture, x, y):
        """`picture` (already at SS size) with its bottom middle at (x, y)."""
        px, py = self._p(x, y)
        self.im.alpha_composite(picture, (int(round(px - picture.width / 2)), int(round(py - picture.height))))

    def text(self, x, y, words, font, fill, spacing: float = 0, anchor: str = "ms"):
        """Text with its baseline middle at (x, y), letters `spacing` final pixels apart."""
        px, py = self._p(x, y)
        if not spacing:
            self.d.text((px, py), words, font=font, fill=fill, anchor=anchor)
            return
        widths = [self.d.textlength(ch, font=font) for ch in words]
        total = sum(widths) + spacing * SS * (len(words) - 1)
        cx = px - total / 2
        for ch, wd in zip(words, widths):
            self.d.text((cx, py), ch, font=font, fill=fill, anchor="ls")
            cx += wd + spacing * SS


_fonts = threading.local()


def _font(path: str, size: int):
    """A font at a size, one copy per thread: several videos are drawn at once, and a font
    object must not be used by two threads at the same moment."""
    from PIL import ImageFont
    cache = getattr(_fonts, "cache", None)
    if cache is None:
        cache = _fonts.cache = {}
    if (path, size) not in cache:
        file = ROOT / path
        if not file.is_file():
            raise StepError(f"the font {path} is missing from the repo")
        cache[(path, size)] = ImageFont.truetype(str(file), size)
    return cache[(path, size)]


@lru_cache(maxsize=64)
def _iro(height: int, squash: int = 100, gold: int = 0):
    """Iro at `height` layer pixels, squashed to `squash` percent of that height (and a little
    wider), warmed toward gold by `gold` percent."""
    from PIL import Image, ImageEnhance
    file = ROOT / IRO_PICTURE
    if not file.is_file():
        raise StepError(f"{IRO_PICTURE} is missing from the repo")
    src = _iro_source()
    h = max(8, int(height * squash / 100))
    w = max(8, int(src.width * height / src.height * (2 - squash / 100) ** 0.6))
    pic = src.resize((w, h), Image.Resampling.BILINEAR)
    if gold:
        pic = ImageEnhance.Brightness(pic).enhance(1 + 0.22 * gold / 100)
        warm = Image.new("RGBA", pic.size, GOLD + (0,))
        warm.putalpha(pic.split()[3].point(lambda v: int(v * 0.20 * gold / 100)))
        pic = Image.alpha_composite(pic, warm)
    return pic


@lru_cache(maxsize=1)
def _iro_source():
    from PIL import Image
    im = Image.open(ROOT / IRO_PICTURE).convert("RGBA")
    im = im.crop(im.getbbox())
    return im.resize((int(im.width * 640 / im.height), 640), Image.Resampling.LANCZOS)


@lru_cache(maxsize=8)
def _halo(size: int, color: tuple):
    """A soft round glow, `size` layer pixels across."""
    from PIL import Image
    small = 64
    im = Image.new("L", (small, small), 0)
    px = im.load()
    for y in range(small):
        for x in range(small):
            d = math.hypot(x - small / 2 + 0.5, y - small / 2 + 0.5) / (small / 2)
            px[x, y] = int(255 * max(0.0, 1 - d) ** 1.8)
    alpha = im.resize((size, size), Image.Resampling.BICUBIC)
    out = Image.new("RGBA", (size, size), color + (0,))
    out.putalpha(alpha)
    return out


@lru_cache(maxsize=1)
def _background():
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(im)
    for y in range(H):
        if y < FLOOR:
            c = mix(BG_TOP, BG_MID, y / FLOOR)
        else:
            c = mix((10, 14, 32), BG_BOT, span(y, FLOOR, FLOOR + 420))
        d.line([(0, y), (W, y)], fill=c)
    # A pool of light on the floor under each side, and the line where the floor starts.
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for cx in (LX, RX):
        gd.ellipse([cx - 300, FLOOR - 26, cx + 300, FLOOR + 60], fill=(26, 36, 78))
    glow = glow.filter(ImageFilter.GaussianBlur(46))
    from PIL import ImageChops
    im = ImageChops.add(im, glow)
    d = ImageDraw.Draw(im)
    d.line([(0, FLOOR), (W, FLOOR)], fill=(44, 56, 104), width=2)
    return im


# ---------------------------------------------------------------- the two players ----

def figure(st: Stage, x: float, ground: float, pose: dict, color=WHITE, shade=SHADE, scale: float = 1.0):
    """The plain figure, feet at (x, ground). `pose`: lean (degrees, + = forward to the right),
    head (degrees, + = looking up), arm_f / arm_b = (upper, lower) angles of the front and back
    arm in degrees from straight down (+ = forward), leg_f / leg_b the same for the legs,
    kneel (0..1), drop (pixels the whole body sinks)."""
    s = scale
    kneel = pose.get("kneel", 0.0)
    thigh, shin, torso, upper, lower = 92 * s, 92 * s, 150 * s, 74 * s, 70 * s
    width = 40 * s
    hip_y = ground - (thigh + shin) * (1 - 0.46 * kneel) + pose.get("drop", 0)
    hip = (x, hip_y)

    def seg(origin, angle_deg, length):
        a = math.radians(angle_deg)
        return origin[0] + math.sin(a) * length, origin[1] + math.cos(a) * length

    def leg(angles, tone, dx):
        up, lo = angles
        o = (hip[0] + dx, hip[1])
        knee = seg(o, up, thigh)
        foot = seg(knee, lo, shin)
        if foot[1] > ground:                               # feet never go through the floor
            foot = (foot[0], ground)
        st.limb(o[0], o[1], knee[0], knee[1], width, tone)
        st.limb(knee[0], knee[1], foot[0], foot[1] - width * 0.1, width * 0.92, tone)

    def arm(origin, angles, tone):
        up, lo = angles
        elbow = seg(origin, up, upper)
        hand = seg(elbow, lo, lower)
        st.limb(origin[0], origin[1], elbow[0], elbow[1], width * 0.8, tone)
        st.limb(elbow[0], elbow[1], hand[0], hand[1], width * 0.74, tone)
        return hand

    lean = pose.get("lean", 0.0)
    a = math.radians(lean)
    neck = (hip[0] + math.sin(a) * torso, hip[1] - math.cos(a) * torso)
    shoulder = (lerp(hip[0], neck[0], 0.9), lerp(hip[1], neck[1], 0.9))
    if kneel > 0.5:
        leg(pose.get("leg_b", (70, 170)), shade, -8 * s)
        leg(pose.get("leg_f", (95, 178)), color, 8 * s)
    else:
        leg(pose.get("leg_b", (-4, -2)), shade, -10 * s)
    arm(shoulder, pose.get("arm_b", (-6, 4)), shade)
    if kneel <= 0.5:
        leg(pose.get("leg_f", (5, 2)), color, 10 * s)
    st.limb(hip[0], hip[1], neck[0], neck[1], width * 1.34, color)
    ha = math.radians(lean - pose.get("head", 0.0) * 0.5)
    head = (neck[0] + math.sin(ha) * 62 * s + pose.get("head", 0.0) * 0.5 * s, neck[1] - math.cos(ha) * 62 * s)
    st.dot(head[0], head[1], 50 * s, color)
    hand = arm(shoulder, pose.get("arm_f", (8, 12)), color)
    return {"head": head, "hand": hand, "hip": hip}


def iro(st: Stage, x: float, ground: float, height: float = 250, squash: float = 1.0, gold: float = 0.0):
    """Iro with its feet at (x, ground)."""
    pic = _iro(int(height * SS), int(round(clamp(squash, 0.7, 1.25) * 20)) * 5, int(round(clamp(gold) * 4)) * 25)
    st.paste(pic, x, ground + height * 0.02)


def hop(t: float, t0: float, t1: float, a: tuple, b: tuple, height: float = 90) -> tuple[float, float, float]:
    """Where a hop from a to b is at time t: (x, y, squash). Lands with a small squash."""
    if t <= t0:
        return a[0], a[1], 1.0
    if t >= t1:
        land = span(t, t1, t1 + 0.14)
        return b[0], b[1], 1.0 - 0.10 * math.sin(land * math.pi)
    u = (t - t0) / (t1 - t0)
    return lerp(a[0], b[0], smooth(u)), lerp(a[1], b[1], u) - height * 4 * u * (1 - u), 1.0 + 0.10 * math.sin(u * math.pi)


def hops(t: float, stops: list[tuple[float, tuple]], air: float = 0.34, height: float = 90):
    """A run of hops: `stops` is [(time it lands, (x, y)), ...], the first one where it starts."""
    x, y = stops[0][1]
    for (t_prev, a), (t_land, b) in zip(stops, stops[1:]):
        if t < t_land - air:
            return a[0], a[1], 1.0 - 0.05 * math.sin(span(t, t_land - air - 0.16, t_land - air) * math.pi)
        if t < t_land + 0.14:
            return hop(t, t_land - air, t_land, a, b, height)
        x, y = b
    return x, y, 1.0


def celebrate(t: float, x: float, y: float) -> tuple[float, float, float]:
    """Two happy jumps on the spot after the payoff."""
    for start in (PAYOFF + 0.05, PAYOFF + 0.75):
        if start <= t < start + 0.6:
            u = (t - start) / 0.6
            return x, y - 70 * 4 * u * (1 - u), 1.0 + 0.12 * math.sin(u * math.pi)
    return x, y, 1.0


def block(st: Stage, x0, y0, x1, y1, front=SLATE, top=SLATE_TOP, lip: float = 9):
    """A solid block: a front face and a lighter top edge."""
    st.rect(x0, y0, x1, y1, front, radius=4)
    st.rect(x0, y0, x1, y0 + lip, top, radius=4)


# ------------------------------------------------------------------- the stories ----

def _idle(t: float, phase: float = 0.0) -> float:
    return math.sin((t + phase) * 2 * math.pi / 2.6)


def _loser_end(t: float) -> float:
    """0 until the payoff, then 1: the loser's shoulders drop."""
    return smooth(span(t, PAYOFF + 0.1, PAYOFF + 0.7))


def story_stairs(st: Stage, t: float, win: float):
    n, step_h = 5, 80
    lw, rw = 60, 68                                        # the left stairs are a little narrower
    lx0, rx0 = 172, 640
    for i in range(n):
        block(st, lx0 + i * lw, FLOOR - (i + 1) * step_h, lx0 + n * lw, FLOOR - i * step_h)
        block(st, rx0 + i * rw, FLOOR - (i + 1) * step_h, rx0 + n * rw, FLOOR - i * step_h,
              mix(SLATE, GOLD_DEEP, win * 0.55), mix(SLATE_TOP, GOLD, win * 0.8))
    # the left one: at the foot of the stairs, hand on chin, looking up
    end = _loser_end(t)
    sway = _idle(t)
    figure(st, 92, FLOOR, {
        "lean": 3 + sway * 1.5 - end * 2, "head": lerp(26 + sway * 4, -22, end),
        "arm_f": (lerp(34, 6, end), lerp(152 + sway * 5, 8, end)), "arm_b": (-8, 6),
        "leg_f": (6, 0), "leg_b": (-6, 0)})
    # Iro: one step at a time
    start = (584, FLOOR)
    stops = [(0.0, start)] + [(0.85 + i * 1.3, (rx0 + i * rw + rw * 0.5 + 4, FLOOR - (i + 1) * step_h)) for i in range(n)]
    x, y, sq = hops(t, stops, height=78)
    if t >= PAYOFF:
        x, y, sq = celebrate(t, stops[-1][1][0], stops[-1][1][1])
    return {"iro": (x, y, sq, 212)}


def story_blocks(st: Stage, t: float, win: float):
    bw, bh = 96, 60
    end = _loser_end(t)
    # the left one: on one knee, nudging one block a little this way, a little that way
    nudge = math.sin(t * 2 * math.pi / 1.3) * 8 * (1 - end)
    bx = 352 + nudge
    block(st, bx - bw / 2, FLOOR - bh, bx + bw / 2, FLOOR)
    reach = 58 + nudge * 1.3
    figure(st, 150, FLOOR, {
        "kneel": 1.0, "lean": 26 - end * 20, "head": -14 - end * 16,
        "arm_f": (lerp(reach, 14, end), lerp(74, 8, end)), "arm_b": (lerp(reach - 14, 4, end), lerp(66, 4, end)),
        "leg_f": (82, 2), "leg_b": (-8, -93)})
    # Iro: a wall, one block at a time
    wx, rows = 772, 5
    bricks = []
    for r in range(rows):
        cells = [(0, bw), (bw, bw), (2 * bw, bw)] if r % 2 == 0 else [(0, bw / 2), (bw / 2, bw), (bw * 1.5, bw), (bw * 2.5, bw / 2)]
        bricks += [(wx + off, FLOOR - r * bh, wide) for off, wide in cells]
    first, last = 0.3, 6.5
    each = (last - first) / len(bricks)
    home = (650, FLOOR)
    c1, c2 = mix(SLATE, GOLD_DEEP, win * 0.55), mix(SLATE_TOP, GOLD, win * 0.8)
    for k, (tx, ty, wide) in enumerate(bricks):
        t0 = first + k * each
        if t < t0:
            continue
        u = span(t, t0, t0 + 0.30)                         # each block flies in from Iro in an arc
        x = lerp(home[0] + 20, tx, smooth(u))
        y = lerp(home[1] - 170, ty, u) - 110 * 4 * u * (1 - u) * 0.5
        block(st, x + 2, y - bh + 2, x + wide - 2, y, c1, c2)
    top = (wx + bw * 1.5, FLOOR - rows * bh)
    if t < 6.85:
        beat = ((t - first) / each) % 1.0 if first <= t < last else 1.0
        toss = math.sin(clamp(beat * 1.6) * math.pi)
        x, y, sq = home[0], home[1] - 18 * toss, 1.0 + 0.06 * toss
    else:
        x, y, sq = hop(t, 6.85, 7.5, home, top, height=170)
    if t >= PAYOFF:
        x, y, sq = celebrate(t, top[0], top[1])
    return {"iro": (x, y, sq, 226)}


def _door(st: Stage, x: float, open_: float = 0.0, shake: float = 0.0, win: float = 0.0, w: float = 150, h: float = 390):
    x += shake
    st.rect(x - w / 2 - 12, FLOOR - h - 12, x + w / 2 + 12, FLOOR, SLATE_DARK, radius=8)
    if open_ > 0:
        st.rect(x - w / 2, FLOOR - h, x + w / 2, FLOOR, mix((255, 230, 160), GOLD, 0.35), radius=4)
    leaf = w * (1 - 0.86 * open_)
    if leaf > 2:
        st.rect(x - w / 2, FLOOR - h, x - w / 2 + leaf, FLOOR, SLATE, radius=4)
        st.rect(x - w / 2, FLOOR - h, x - w / 2 + leaf, FLOOR - h + 12, SLATE_TOP, radius=4)
        st.rect(x - w / 2 + leaf * 0.14, FLOOR - h * 0.86, x - w / 2 + leaf * 0.86, FLOOR - h * 0.56, SLATE_DARK, radius=4)
        st.dot(x - w / 2 + leaf * 0.82, FLOOR - h * 0.44, 9, mix(SLATE_TOP, GOLD, win))


def story_doors(st: Stage, t: float, win: float):
    end = _loser_end(t)
    _door(st, 386)
    tap = max(0.0, math.sin(t * 2 * math.pi / 0.9)) * 16 * (1 - end)
    look = smooth(span(t, 3.6, 4.0)) - smooth(span(t, 5.0, 5.4))     # he checks the time once
    figure(st, 150, FLOOR, {
        "lean": 1 - end * 3, "head": lerp(4 - look * 26, -22, end),
        "arm_f": (lerp(lerp(30, 56, look), 6, end), lerp(lerp(-112, -128, look), 8, end)),
        "arm_b": (lerp(-26, -6, end), lerp(112, 6, end)),
        "leg_f": (8 + tap * 0.9, -tap * 0.5), "leg_b": (-6, 0)})
    xs = [650, 806, 962]
    knocks = [1.5, 3.9, 6.3]
    opened = smooth(span(t, knocks[2] + 0.45, knocks[2] + 1.05))
    for i, x in enumerate(xs):
        k = knocks[i]
        shake = math.sin((t - k) * 46) * 7 * math.exp(-(t - k) * 7) if k <= t < k + 0.6 else 0.0
        _door(st, x, open_=opened if i == 2 else 0.0, shake=shake, win=win if i == 2 else 0.0, w=122, h=350)
    stops = [(0.0, (584, FLOOR)), (1.1, (xs[0], FLOOR)), (3.5, (xs[1], FLOOR)), (5.9, (xs[2], FLOOR))]
    x, y, sq = hops(t, stops, air=0.5, height=90)
    for k in knocks:                                       # a little bump into each knock
        if k - 0.12 <= t < k + 0.25:
            y -= 16 * math.sin(span(t, k - 0.12, k + 0.25) * math.pi)
    if t >= PAYOFF:
        x, y, sq = celebrate(t, xs[2], FLOOR)
    return {"iro": (x, y, sq, 232), "light": (xs[2], FLOOR - 175, opened * 0.85)}


def _gauge(st: Stage, x: float, y: float, value: float | None, color, pop: float = 0.0):
    r = 112 * (1 + 0.08 * pop)
    st.ring(x, y, r, 20, (46, 56, 92))
    if value:
        st.ring(x, y, r, 20, color, start=-90, end=-90 + 360 * clamp(value / 10))
    words = "?" if value is None else str(int(round(value)))
    st.text(x, y + 30 * (1 + 0.1 * pop), words, _font(LABEL_FONT, int(98 * SS * (1 + 0.14 * pop))), color)
    st.text(x, y + 72, "/ 10", _font(TAG_FONT, 30 * SS), (150, 162, 196))


def _button(st: Stage, x: float, pressed: float, front=SLATE, top=SLATE_TOP, color=CYAN):
    """A stand with one big button on it."""
    block(st, x - 62, FLOOR - 150, x + 62, FLOOR, front, top)
    st.rect(x - 34, FLOOR - 176 + 14 * pressed, x + 34, FLOOR - 150, color, radius=10)


def story_score(st: Stage, t: float, win: float):
    end = _loser_end(t)
    gy = 664
    # the left one: tries once, gets a 4, and waits with his hands on his hips
    press = math.sin(span(t, 0.45, 0.95) * math.pi)
    scored = t >= 0.8
    red = (232, 98, 112)
    _gauge(st, LX, gy, 4 if scored else None, red if scored else SHADE, pop=math.sin(span(t, 0.8, 1.2) * math.pi))
    _button(st, 356, press, color=red)
    sway = _idle(t, 0.7)
    hips = smooth(span(t, 1.0, 1.5))
    figure(st, 190, FLOOR, {
        "lean": 2 + sway - end * 3, "head": lerp(lerp(-8, 22, hips), -24, end),
        "arm_f": (lerp(lerp(62, 28, hips), 6, end), lerp(lerp(52, -86, hips), 8, end)),
        "arm_b": (lerp(lerp(-6, -30, hips), -6, end), lerp(lerp(6, 84, hips), 6, end)),
        "leg_f": (7, 0), "leg_b": (-7, 0)})
    # Iro: again, and again, and again
    tries = [(0.9, 4), (2.9, 6), (4.9, 8), (6.9, 10)]
    value, pop, press_r = None, 0.0, 0.0
    for when, v in tries:
        if t >= when:
            value = v
            pop = math.sin(span(t, when, when + 0.4) * math.pi)
        press_r = max(press_r, math.sin(span(t, when - 0.1, when + 0.25) * math.pi))
    color = mix(CYAN, GOLD, max(win, float(value == 10) * span(t, 6.9, 7.3)))
    _gauge(st, RX, gy, value, color if value else SHADE, pop=pop)
    bx = 954
    _button(st, bx, press_r, mix(SLATE, GOLD_DEEP, win * 0.55), mix(SLATE_TOP, GOLD, win * 0.8), color)
    home = (716, FLOOR)
    x, y, sq = home[0], home[1], 1.0
    for when, _ in tries:                                  # a hop toward the button for every try
        if when - 0.46 <= t < when + 0.14:
            x, y, sq = hop(t, when - 0.46, when, home, (home[0] + 44, FLOOR), height=70)
        elif when + 0.14 <= t < when + 0.6:
            x = lerp(home[0] + 44, home[0], smooth(span(t, when + 0.14, when + 0.6)))
    if t >= PAYOFF:
        x, y, sq = celebrate(t, home[0], FLOOR)
    return {"iro": (x, y, sq, 262)}


STORIES = {"stairs": story_stairs, "blocks": story_blocks, "doors": story_doors, "score": story_score}


# ------------------------------------------------------------------------ labels ----

def _label_lines(words: str) -> list[str]:
    """One line when it is short, else two lines of about the same length."""
    words = " ".join(str(words or "").upper().split())
    parts = words.split(" ")
    if len(parts) == 1 or len(words) <= 10:
        return [words]
    best = min(range(1, len(parts)), key=lambda i: abs(len(" ".join(parts[:i])) - len(" ".join(parts[i:]))))
    return [" ".join(parts[:best]), " ".join(parts[best:])]


def label_fit(words: str) -> tuple[int, list[str], float]:
    """(letter size, lines, widest line in final pixels) for a label, as large as fits."""
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    lines = _label_lines(words)
    for size in LABEL_SIZES:
        font = _font(LABEL_FONT, size * SS)
        track = size * 0.07 * SS
        wide = max((sum(d.textlength(ch, font=font) for ch in ln) + track * (len(ln) - 1)) / SS for ln in lines)
        if wide <= LABEL_MAX_W:
            return size, lines, wide
    return LABEL_SIZES[-1], lines, wide


def _labels(st: Stage, scene: dict, t: float, win: float):
    for side, x in (("left", LX), ("right", RX)):
        size, lines, _ = label_fit(scene[side])
        font = _font(LABEL_FONT, size * SS)
        gold = win if side == "right" else 0.0
        color = mix(WHITE, GOLD, gold) + (255,)
        pop = 1.0 + 0.06 * math.sin(span(t, PAYOFF, PAYOFF + 0.4) * math.pi) * (side == "right")
        for i, line in enumerate(lines):
            y = LABEL_Y - (len(lines) - 1 - i) * size * 1.12
            st.text(x, y - (pop - 1) * 60, line, font, color, spacing=size * 0.07)


# ------------------------------------------------------------------------ frames ----

def clean_scene(scene: dict) -> dict:
    """A scene with its words tidied: the template in lower case, the labels in capitals."""
    out = dict(scene or {})
    out["template"] = str(out.get("template") or "").strip().lower()
    for side in ("left", "right"):
        out[side] = " ".join(str(out.get(side) or "").upper().split())
    out["caption"] = " ".join(str(out.get("caption") or "").split())
    return out


def check_scene(scene: dict) -> list[str]:
    """What is wrong with a scene's words. An empty list means it can be drawn."""
    s = clean_scene(scene)
    out = []
    if s["template"] not in TEMPLATES:
        out.append(f"template must be one of {', '.join(TEMPLATES)}, got {s['template']!r}")
    for side in ("left", "right"):
        words = s[side]
        if not words:
            out.append(f"{side} needs a label")
            continue
        if len(words.split()) > LABEL_MAX_WORDS or len(words) > LABEL_MAX_CHARS:
            out.append(f"the {side} label must be at most {LABEL_MAX_WORDS} words and {LABEL_MAX_CHARS} letters, got {words!r}")
        elif label_fit(words)[2] > LABEL_MAX_W:
            out.append(f"the {side} label {words!r} is too wide to read on a phone; use shorter words")
    if s["left"] and s["left"] == s["right"]:
        out.append("the two labels are the same")
    if len(s["caption"]) > CAPTION_MAX_CHARS:
        out.append(f"the caption is longer than {CAPTION_MAX_CHARS} letters")
    return out


def frame(scene: dict, t: float, end_tag: str = "SEARCH IRO AI"):
    """One frame of a scene's video at `t` seconds, as an RGB picture."""
    from PIL import Image, ImageChops, ImageFilter
    scene = clean_scene(scene)
    win = smooth(span(t, PAYOFF, PAYOFF + 0.45))
    st = Stage()
    state = STORIES[scene["template"]](st, t, win)
    x, y, sq, height = state["iro"]
    light = state.get("light")
    back = None                                             # what sits behind everything: light
    if win > 0 or (light and light[2] > 0):
        back = Stage()
        if win > 0:
            halo = _halo(int(height * 3.1 * SS), GOLD).copy()
            halo.putalpha(halo.split()[3].point(lambda v: int(v * 0.62 * win)))
            back.paste(halo, x, y + height * 1.05)
        if light and light[2] > 0:
            halo = _halo(int(520 * SS), (255, 214, 120)).copy()
            halo.putalpha(halo.split()[3].point(lambda v: int(v * 0.7 * light[2])))
            back.paste(halo, light[0], light[1] + 260)
    iro(st, x, y, height, sq, gold=win)
    if win > 0:                                             # sparks rising around the winner
        for k in range(9):
            life = ((t - PAYOFF) * 0.9 + k * 0.137) % 1.0
            sx = x + math.sin(k * 2.4) * (height * 0.75)
            sy = y - height * 0.2 - life * height * 1.5
            st.dot(sx, sy, 6 * (1 - life) + 2, GOLD + (int(255 * (1 - life) * win),))
    _labels(st, scene, t, win)

    full = st.im if back is None else Image.alpha_composite(back.im, st.im)
    layer = full.reduce(SS)
    out = _background_rgba().copy()
    # the glow: a small blurred copy of the layer, under the layer itself
    small = layer.resize((W // 6, BAND_H // 6), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(5))
    small.putalpha(small.getchannel("A").point(lambda v: int(v * 0.42)))
    out.alpha_composite(small.resize(layer.size, Image.Resampling.BILINEAR), (0, BAND_TOP))
    out.alpha_composite(layer, (0, BAND_TOP))
    # the reflection on the floor: the bottom of the layer, flipped, soft and fading out
    depth = 300
    strip = layer.crop((0, FLOOR - BAND_TOP - depth, W, FLOOR - BAND_TOP)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    strip = strip.resize((W // 3, depth // 3), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(2.2))
    strip.putalpha(ImageChops.multiply(strip.getchannel("A"), _fade(W // 3, depth // 3)))
    out.alpha_composite(strip.resize((W, depth), Image.Resampling.BILINEAR), (0, FLOOR + 3))

    tag = str(end_tag or "").strip().upper()
    if tag and t >= TAG_AT:
        a = smooth(span(t, TAG_AT, TAG_AT + 0.5))
        over = Image.new("RGBA", (W, 120), (0, 0, 0, 0))
        from PIL import ImageDraw
        d = ImageDraw.Draw(over)
        font = _font(TAG_FONT, 56)
        widths = [d.textlength(ch, font=font) for ch in tag]
        total = sum(widths) + 11 * (len(tag) - 1)
        cx = (W - total) / 2
        for ch, wd in zip(tag, widths):
            d.text((cx, 84), ch, font=font, fill=GOLD + (int(255 * a),), anchor="ls")
            cx += wd + 11
        out.alpha_composite(over, (0, TAG_Y - int(14 * (1 - a))))
    return out.convert("RGB")


@lru_cache(maxsize=1)
def _background_rgba():
    return _background().convert("RGBA")


@lru_cache(maxsize=4)
def _fade(width: int, depth: int):
    """How strong the reflection is from the floor line down: strongest at the top, gone at the bottom."""
    from PIL import Image
    column = Image.new("L", (1, depth))
    column.putdata([int(255 * 0.34 * (1 - y / depth) ** 1.6) for y in range(depth)])
    return column.resize((width, depth))


# ------------------------------------------------------------------------ videos ----

def render(scene: dict, out: Path, end_tag: str = "SEARCH IRO AI", on_frame=None) -> Path:
    """Draw a scene's video and write it to `out` (H.264 with a silent sound track, so every
    app takes it and a sound can be added on top)."""
    import media
    problems = check_scene(scene)
    if problems:
        raise StepError("this scene cannot be drawn: " + "; ".join(problems))
    media.require_ffmpeg()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.stem + ".part.mp4")
    cmd = [media.tool_path("ffmpeg"), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
           "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(part)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with media._alive(proc):
            for i in range(FRAMES):
                proc.stdin.write(frame(scene, i / FPS, end_tag).tobytes())
                if on_frame:
                    on_frame(i + 1, FRAMES)
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


def first_second(scene: dict, end_tag: str = "") -> list[str]:
    """Problems a viewer meets in the first second, measured from the frames: a side with
    nothing on it, a side that does not move, a label that runs off its side or into the other."""
    from PIL import ImageChops, ImageStat
    out = []
    a, b = frame(scene, 0.0, end_tag), frame(scene, 1.0, end_tag)
    bg = _background()
    for side, box in (("left", (0, LABEL_Y + 20, W // 2, FLOOR)), ("right", (W // 2, LABEL_Y + 20, W, FLOOR))):
        there = sum(ImageStat.Stat(ImageChops.difference(a.crop(box), bg.crop(box))).mean)
        moved = sum(ImageStat.Stat(ImageChops.difference(a.crop(box), b.crop(box))).mean)
        if there < 6:
            out.append(f"nothing is on the {side} side when the video opens")
        elif moved < 0.25:
            out.append(f"the {side} side does not move in the first second")
    s = clean_scene(scene)
    for side in ("left", "right"):
        if label_fit(s[side])[2] > LABEL_MAX_W:
            out.append(f"the {side} label does not fit its side")
    return out
