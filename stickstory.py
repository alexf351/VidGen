"""Choice stories: a narrated story told with stick figures in dark flat rooms, where "you" are the
one in the picture and every episode ends on a choice the comments get to make.

    Imagine you wake up at 3 a.m. to a knock on your window...
    ...Do you STAY or RUN?            (the next episode opens with what the vote was)

Nothing here calls a picture or a clip model. An episode is a list of shots; each shot names a set,
a light, where you stand and what you do, who else is there, and one thing that happens:

    {"say": "Imagine you wake up at three a.m. to a knock on your window.",
     "set": "bedroom", "light": "moon", "you": {"pose": "lie", "at": "bed"},
     "event": "knock", "target": "window"}

    SETS, LIGHTS, POSES, KINDS, EVENTS, CAMERAS   what a shot may say
    check_episode(ep)          what is wrong with an episode's script, before anything is drawn
    plan(ep, words=None)       when every shot and every word happens (from the voice, or estimated)
    frame(ep, t, timing)       one frame as a picture
    render(ep, out, timing, audio)   the mp4 (1080 x 1920, 30 fps)

The look is VidGen's own: a white figure for you, dark figures with lit eyes for whatever is out
there, one source of light in the room, and Iro glowing at your side. The words on screen are the
narrator's, three at a time, the one being said in gold.
"""

from __future__ import annotations

import math
import subprocess
from functools import lru_cache
from pathlib import Path

from common import StepError
from contrast import (GOLD, _font, _halo, _iro_source, back_out, clamp, lerp, mix, smooth, span)

W, H, FPS = 1080, 1920, 30
SS = 2                              # the moving layer is drawn at twice the size and scaled down
FLOOR = 1250                        # where feet stand
CEILING = 400                       # where a room's wall starts
BAND_TOP, BAND_BOT = 300, 1340      # the strip the moving layer covers
BAND_H = BAND_BOT - BAND_TOP
CAPTION_Y = 1420                    # the middle of the words; the apps cover what is below ~1500
BANNER_Y = 262                      # under the strip the apps cover at the top
LMW, LMH = W // 8, H // 8           # the light is worked out at this size and scaled up

CAPTION_FONT = "assets/fonts/Poppins-Black.ttf"
SMALL_FONT = "assets/fonts/Inter-SemiBold.otf"

YOU, YOU_SHADE = (240, 243, 250), (178, 186, 206)
FRIEND, FRIEND_SHADE = (150, 176, 214), (104, 128, 170)
STRANGER, STRANGER_SHADE = (126, 130, 146), (88, 92, 108)
SHADOW, SHADOW_RIM = (10, 12, 20), (58, 64, 92)
EYES = {"red": (255, 70, 60), "green": (110, 255, 140), "white": (245, 248, 255), "none": None}

WORDS_PER_SECOND = 2.7              # how fast the narrator is taken to speak when there is no voice
SHOT_PAD = 0.35                     # quiet after each line when there is no voice
TAIL = 2.2                          # the last picture holds this long after the last word

SETS = {
    "bedroom": "your bedroom at night: a bed on the left, a door in the middle, a window on the right",
    "hallway": "a long hallway with three doors and one ceiling lamp",
    "living_room": "a living room: a couch under a window, a door on the right",
    "stairwell": "a concrete stairwell with a door on the left",
    "basement": "a basement: pipes, crates, a small high window, a door on the left",
    "street": "a street at night: houses, a front door, one street lamp",
    "forest": "a forest at night under the moon",
    "office": "an office after hours: desks, dark monitors, a door on the right",
    "rooftop": "a rooftop above the city, with the door to the stairs on the left",
    "elevator": "inside an elevator, the doors in the middle",
}
LIGHTS = {
    "lamp": "one warm lamp, the rest of the room dim",
    "moon": "cold moonlight through the window or from the sky",
    "flashlight": "nearly dark; a beam from the flashlight in your hand",
    "red": "a red emergency light, pulsing",
    "green": "a sick green glow from where the danger is",
    "flicker": "a lamp that keeps cutting out",
    "dark": "almost black; only eyes and screens show",
    "dawn": "warm morning light: it is over, for now",
}
POSES = ("stand", "walk", "run", "crouch", "sit", "lie", "reach", "hands_up", "hide", "phone",
         "point", "knock", "listen", "wave", "fall")
KINDS = {
    "shadow": "a tall dark figure with lit eyes",
    "crowd": "several dark figures with lit eyes (count 2 to 6)",
    "stranger": "a grey person in a hat: could be help, could be trouble",
    "friend": "someone on your side, in blue",
}
EVENTS = {
    "none": "nothing sudden",
    "knock": "three knocks on the door or the window (target)",
    "door_open": "the door swings open",
    "door_close": "the door slams shut",
    "lights_out": "the light goes out",
    "lights_on": "the light comes back",
    "eyes": "eyes open in the dark where they are (or at the target)",
    "phone_ring": "your phone lights up and rings",
    "shake": "the whole place shakes",
    "heartbeat": "everything throbs with your pulse",
}
CAMERAS = ("push", "still", "pull", "shake")
SPOTS = {"off_left": -0.16, "far_left": 0.12, "left": 0.28, "center": 0.5, "right": 0.72,
         "far_right": 0.88, "off_right": 1.16}
SAY_MAX_WORDS = 24
SHOTS_MIN, SHOTS_MAX = 5, 14
OPTION_MAX_CHARS = 12


# ------------------------------------------------------------------- the layer ----

class Layer:
    """A see-through picture drawn at SS times the size. Everything is given in final pixels."""

    def __init__(self, top: int = BAND_TOP, height: int = BAND_H, ss: int = SS):
        from PIL import Image, ImageDraw
        self.top, self.ss = top, ss
        self.im = Image.new("RGBA", (W * ss, height * ss), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.im)

    def _p(self, x: float, y: float) -> tuple[float, float]:
        return x * self.ss, (y - self.top) * self.ss

    def rect(self, x0, y0, x1, y1, fill, radius: float = 0):
        a, b = self._p(min(x0, x1), min(y0, y1)), self._p(max(x0, x1), max(y0, y1))
        if b[0] - a[0] < 1 or b[1] - a[1] < 1:
            return
        if radius:
            self.d.rounded_rectangle([a, b], radius * self.ss, fill=fill)
        else:
            self.d.rectangle([a, b], fill=fill)

    def poly(self, pts, fill):
        self.d.polygon([self._p(x, y) for x, y in pts], fill=fill)

    def dot(self, x, y, r, fill):
        cx, cy = self._p(x, y)
        r *= self.ss
        self.d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)

    def oval(self, x0, y0, x1, y1, fill):
        self.d.ellipse([self._p(x0, y0), self._p(x1, y1)], fill=fill)

    def line(self, x0, y0, x1, y1, width, fill):
        self.d.line([self._p(x0, y0), self._p(x1, y1)], fill=fill, width=max(1, int(width * self.ss)))

    def limb(self, x0, y0, x1, y1, width, fill):
        """A thick line with round ends."""
        a, b = self._p(x0, y0), self._p(x1, y1)
        w = width * self.ss
        self.d.line([a, b], fill=fill, width=max(1, int(w)))
        for cx, cy in (a, b):
            self.d.ellipse([cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2], fill=fill)

    def grad(self, y0, y1, top, bottom, x0: float = 0, x1: float = W):
        """A box filled top to bottom from one colour to another."""
        a, b = self._p(x0, y0), self._p(x1, y1)
        n = max(1, int(b[1] - a[1]))
        for i in range(n):
            self.d.line([(a[0], a[1] + i), (b[0], a[1] + i)], fill=mix(top, bottom, i / n))

    def flat(self):
        """The layer at final size."""
        return self.im if self.ss == 1 else self.im.reduce(self.ss)


# ------------------------------------------------------------------- the figure ----

def _pose(name: str, p: float, t: float) -> dict:
    """The angles of a pose. `p` is how far through a step the figure is (radians), `t` the
    seconds into the shot. Angles are degrees from straight down, + = toward where it faces."""
    s, c = math.sin(p), math.cos(p)
    breathe = math.sin(t * 2.1) * 1.2
    if name == "walk":
        return {"lean": 4, "leg_f": (26 * s, 26 * s - 30 * max(0.0, c)), "leg_b": (-26 * s, -26 * s - 30 * max(0.0, -c)),
                "arm_f": (-22 * s, -22 * s + 16), "arm_b": (22 * s, 22 * s + 16)}
    if name == "run":
        return {"lean": 16, "leg_f": (48 * s, 48 * s - 78 * max(0.0, c)), "leg_b": (-48 * s, -48 * s - 78 * max(0.0, -c)),
                "arm_f": (-52 * s, -52 * s + 78), "arm_b": (52 * s, 52 * s + 78)}
    if name == "crouch":
        return {"lean": 24, "leg_f": (72, -42), "leg_b": (60, -50), "arm_f": (30, 62 + breathe), "arm_b": (14, 40)}
    if name == "hide":
        return {"lean": 34, "leg_f": (78, -48), "leg_b": (68, -54), "arm_f": (128, 214), "arm_b": (110, 200), "head": -10}
    if name == "sit":
        return {"lean": -4, "seat": 104, "leg_f": (84, 4), "leg_b": (80, 0), "arm_f": (22, 64), "arm_b": (10, 50)}
    if name == "reach":
        return {"lean": 9, "leg_f": (12, 4), "leg_b": (-10, -4), "arm_f": (82, 86 + breathe), "arm_b": (-10, 4)}
    if name == "hands_up":
        return {"lean": -3, "leg_f": (6, 2), "leg_b": (-6, -2), "arm_f": (158, 176), "arm_b": (-158, -176)}
    if name == "phone":
        return {"lean": 3, "leg_f": (5, 2), "leg_b": (-5, -2), "arm_f": (34, 148), "arm_b": (-6, 6), "head": -6}
    if name == "point":
        return {"lean": 4, "leg_f": (8, 3), "leg_b": (-8, -3), "arm_f": (78, 80), "arm_b": (-8, 4)}
    if name == "knock":
        k = math.sin(t * 15) * 14
        return {"lean": 8, "leg_f": (10, 3), "leg_b": (-8, -3), "arm_f": (72, 118 + k), "arm_b": (-8, 4)}
    if name == "listen":
        return {"lean": 15, "leg_f": (14, 4), "leg_b": (-10, -4), "arm_f": (44, 158), "arm_b": (-4, 10), "head": 8}
    if name == "wave":
        k = math.sin(t * 9) * 20
        return {"lean": 0, "leg_f": (5, 2), "leg_b": (-5, -2), "arm_f": (150, 168 + k), "arm_b": (-6, 4)}
    # stand, and the poses that only turn the whole body (lie, fall)
    return {"lean": breathe * 0.4, "leg_f": (5, 2), "leg_b": (-5, -2), "arm_f": (7, 12 + breathe), "arm_b": (-7, 3)}


def stick(L: Layer, x: float, ground: float, pose: dict, face: int = 1, color=YOU, shade=YOU_SHADE,
          scale: float = 1.0, rot: float = 0.0, rim=None, hat: bool = False) -> dict:
    """A stick figure with its feet at (x, ground), facing right (1) or left (-1), turned `rot`
    degrees about its feet (90 = lying on its back). Returns where its head, hand and hip are."""
    s = scale
    thigh, shin, torso, upper, lower = 84 * s, 84 * s, 136 * s, 68 * s, 64 * s
    width = 36 * s
    ra = math.radians(rot)

    def seg(origin, angle_deg, length):
        a = math.radians(angle_deg)
        return origin[0] + math.sin(a) * length, origin[1] + math.cos(a) * length

    # the body in its own space: the hip at (0, 0), +x forward, +y down
    legs = []
    for key, dx in (("leg_b", -9 * s), ("leg_f", 9 * s)):
        up, lo = pose.get(key, (0, 0))
        knee = seg((dx, 0), up, thigh)
        foot = seg(knee, lo, shin)
        legs.append(((dx, 0), knee, foot))
    seat = pose.get("seat")
    hip_h = seat * s if seat else max(max(f[1] for _, _, f in legs), 20 * s)
    lean = math.radians(pose.get("lean", 0.0))
    neck = (math.sin(lean) * torso, -math.cos(lean) * torso)
    shoulder = (neck[0] * 0.9, neck[1] * 0.9)
    ha = lean - math.radians(pose.get("head", 0.0) * 0.5)
    head = (neck[0] + math.sin(ha) * 56 * s, neck[1] - math.cos(ha) * 56 * s)
    arms = {}
    for key in ("arm_b", "arm_f"):
        up, lo = pose.get(key, (0, 0))
        elbow = seg(shoulder, up, upper)
        arms[key] = (shoulder, elbow, seg(elbow, lo, lower))

    def place(pt):
        """From the body's space to the picture: stand it on the ground, face it, turn it."""
        px, py = pt[0] * face, pt[1] - hip_h
        if rot:
            px, py = px * math.cos(ra) - py * math.sin(ra) * face, px * math.sin(ra) * face + py * math.cos(ra)
        return x + px, ground + py

    def body(col, sh, grow):
        def limb(a, b, w, tone):
            (ax, ay), (bx, by) = place(a), place(b)
            L.limb(ax, ay, bx, by, w + grow, tone)
        o, knee, foot = legs[0]
        limb(o, knee, width, sh); limb(knee, foot, width * 0.92, sh)
        sh_, el, hand = arms["arm_b"]
        limb(sh_, el, width * 0.8, sh); limb(el, hand, width * 0.74, sh)
        o, knee, foot = legs[1]
        limb(o, knee, width, col); limb(knee, foot, width * 0.92, col)
        limb((0, 0), neck, width * 1.3, col)
        hx, hy = place(head)
        L.dot(hx, hy, 46 * s + grow / 2, col)
        sh_, el, hand = arms["arm_f"]
        limb(sh_, el, width * 0.8, col); limb(el, hand, width * 0.74, col)

    if rim:
        body(rim, rim, 7 * s)                                # a dark figure needs an edge to be seen
    body(color, shade, 0)
    hx, hy = place(head)
    if hat:
        bx, by = place((head[0] - 0, head[1] - 34 * s))
        L.rect(bx - 62 * s, by - 6 * s, bx + 62 * s, by + 8 * s, shade, radius=4)
        L.rect(bx - 38 * s, by - 52 * s, bx + 38 * s, by + 2 * s, shade, radius=8)
    return {"head": (hx, hy), "hand": place(arms["arm_f"][2]), "hip": place((0, 0)), "r": 46 * s}


# ----------------------------------------------------------------------- the sets ----

def _ground(B: Layer, top, bottom, lines=None):
    """The floor from where feet stand down to the bottom of the picture, with boards running
    away from the camera so it reads as a floor and not a wall."""
    B.grad(FLOOR, H, top, bottom)
    tone = lines or mix(top, (0, 0, 0), 0.32)
    for k in range(-7, 8):
        x0 = W / 2 + k * 150
        B.line(x0, FLOOR, W / 2 + k * 420, H, 3, tone)
    B.line(0, FLOOR, W, FLOOR, 3, mix(top, (255, 255, 255), 0.18))


def _room(B: Layer, wall_top, wall_bot, floor_top, floor_bot):
    """A room seen flat on: the wall up to the top of the picture, the floor, the board between."""
    B.grad(0, FLOOR, mix(wall_top, (0, 0, 0), 0.25), wall_bot)
    _ground(B, floor_top, mix(floor_top, floor_bot, 0.45))
    B.rect(0, FLOOR - 22, W, FLOOR, mix(wall_bot, (0, 0, 0), 0.35))          # skirting board


def _doorway(B: Layer, x: float, w: float = 220, h: float = 540, frame=(26, 28, 44), inside=(4, 5, 10)):
    """The frame of a door and the dark beyond it. The door itself moves, so it is drawn later."""
    B.rect(x - w / 2 - 16, FLOOR - h - 16, x + w / 2 + 16, FLOOR, frame, radius=4)
    B.rect(x - w / 2, FLOOR - h, x + w / 2, FLOOR, inside)


def _window(B: Layer, E: Layer, x: float, y0: float, w: float, h: float, frame=(24, 26, 42), sky=(150, 176, 232), glow: int = 150):
    B.rect(x - w / 2 - 14, y0 - 14, x + w / 2 + 14, y0 + h + 14, frame, radius=4)
    B.rect(x - w / 2, y0, x + w / 2, y0 + h, mix(sky, (0, 0, 0), 0.72))
    E.rect(x - w / 2, y0, x + w / 2, y0 + h, sky + (glow,))
    B.rect(x - 5, y0, x + 5, y0 + h, frame); E.rect(x - 5, y0, x + 5, y0 + h, frame + (255,))
    B.rect(x - w / 2, y0 + h / 2 - 5, x + w / 2, y0 + h / 2 + 5, frame); E.rect(x - w / 2, y0 + h / 2 - 5, x + w / 2, y0 + h / 2 + 5, frame + (255,))


def _lamp(B: Layer, E: Layer, x: float, warm=(255, 222, 170)):
    """A ceiling lamp's fitting. Its bulb is lit later, only while the lamp is on."""
    B.line(x, 0, x, CEILING + 46, 4, (16, 17, 28))
    B.poly([(x - 46, CEILING + 84), (x + 46, CEILING + 84), (x + 26, CEILING + 44), (x - 26, CEILING + 44)], (30, 32, 50))


def _set_bedroom(B, E, F):
    _room(B, (54, 56, 96), (40, 42, 76), (44, 40, 66), (14, 13, 24))
    _lamp(B, E, 560)
    _doorway(B, 620, 200, 520)
    _window(B, E, 900, 590, 230, 300)
    B.rect(1020, 560, 1052, 930, (30, 32, 58), radius=6)                    # the curtain, pulled back
    B.rect(40, FLOOR - 330, 84, FLOOR, (26, 26, 46), radius=8)              # headboard
    B.rect(60, FLOOR - 150, 480, FLOOR - 30, (86, 90, 138), radius=18)      # mattress
    B.rect(60, FLOOR - 96, 480, FLOOR - 26, (58, 62, 108), radius=10)       # blanket
    B.rect(84, FLOOR - 190, 200, FLOOR - 140, (128, 134, 180), radius=20)   # pillow
    B.rect(70, FLOOR - 30, 96, FLOOR, (22, 22, 40)); B.rect(444, FLOOR - 30, 470, FLOOR, (22, 22, 40))
    return {"door": 620, "door_w": 200, "door_h": 520, "window": 900, "window_y": 740, "lamp": 560,
            "bed": 270, "bed_y": FLOOR - 150, "seat": 430, "seat_h": 150, "spots": {"bed": 430}}


def _set_hallway(B, E, F):
    _room(B, (50, 62, 78), (36, 46, 60), (52, 42, 46), (16, 12, 14))
    for x in (170, 520, 880):
        _doorway(B, x, 190, 500, frame=(24, 30, 40))
    _lamp(B, E, 350)
    B.rect(676, 640, 742, 730, (22, 28, 38), radius=4); B.rect(684, 648, 734, 722, (64, 78, 96))   # a picture
    B.poly([(0, FLOOR + 60), (W, FLOOR + 60), (W, FLOOR + 190), (0, FLOOR + 190)], (72, 40, 46))    # the runner
    B.line(0, FLOOR + 60, W, FLOOR + 60, 3, (104, 62, 66)); B.line(0, FLOOR + 190, W, FLOOR + 190, 3, (40, 22, 26))
    return {"door": 880, "door_w": 190, "door_h": 500, "lamp": 350, "doors": (170, 520), "spots": {}}


def _set_living_room(B, E, F):
    _room(B, (74, 60, 66), (54, 44, 52), (58, 46, 44), (18, 14, 14))
    _window(B, E, 330, 560, 380, 260)
    _lamp(B, E, 640)
    _doorway(B, 900, 200, 520, frame=(34, 26, 30))
    B.rect(110, FLOOR - 210, 570, FLOOR - 40, (40, 44, 78), radius=26)      # couch back
    B.rect(90, FLOOR - 120, 590, FLOOR - 20, (56, 62, 104), radius=22)      # couch seat
    B.rect(80, FLOOR - 170, 140, FLOOR - 16, (46, 50, 90), radius=20); B.rect(540, FLOOR - 170, 600, FLOOR - 16, (46, 50, 90), radius=20)
    B.poly([(140, FLOOR + 70), (720, FLOOR + 70), (800, FLOOR + 200), (60, FLOOR + 200)], (70, 50, 56))   # rug
    B.rect(690, FLOOR - 96, 780, FLOOR, (30, 24, 28), radius=4)             # side table
    return {"door": 900, "door_w": 200, "door_h": 520, "window": 330, "window_y": 690, "lamp": 640,
            "seat": 340, "spots": {"couch": 340}}


def _set_stairwell(B, E, F):
    _room(B, (62, 70, 70), (40, 48, 50), (48, 52, 52), (12, 14, 14))
    _doorway(B, 170, 200, 520, frame=(28, 34, 34))
    _lamp(B, E, 520, warm=(226, 240, 220))
    for i in range(9):                                                      # the flight going up to the right
        x0 = 420 + i * 78
        B.rect(x0, FLOOR - 52 * (i + 1), W, FLOOR - 52 * i, mix((70, 80, 80), (44, 52, 54), i / 9))
        B.line(x0, FLOOR - 52 * (i + 1), W, FLOOR - 52 * (i + 1), 3, (96, 108, 108))
    B.line(430, FLOOR - 190, 1080, FLOOR - 640, 10, (20, 24, 26))            # the rail
    for i in range(5):
        x0 = 470 + i * 140
        B.line(x0, FLOOR - 218 - i * 97, x0, FLOOR - 52 - i * 97, 6, (20, 24, 26))
    E.rect(84, CEILING + 60, 256, CEILING + 116, (90, 255, 150, 210), radius=6)   # the exit sign
    B.rect(84, CEILING + 60, 256, CEILING + 116, (30, 90, 50), radius=6)
    return {"door": 170, "door_w": 200, "door_h": 520, "lamp": 520, "spots": {"stairs": 0.62 * W}}


def _set_basement(B, E, F):
    _room(B, (52, 56, 48), (32, 36, 32), (40, 40, 36), (10, 10, 9))
    for row in range(8):                                                    # brick courses
        y = CEILING + 60 + row * 100
        B.line(0, y, W, y, 2, (38, 42, 36))
        for col in range(8):
            B.line(col * 150 + (75 if row % 2 else 0), y, col * 150 + (75 if row % 2 else 0), y + 100, 2, (38, 42, 36))
    _doorway(B, 160, 190, 500, frame=(22, 24, 20))
    _window(B, E, 820, 470, 220, 110, frame=(20, 22, 18), sky=(120, 150, 190), glow=120)
    B.rect(0, CEILING + 20, W, CEILING + 52, (70, 74, 66)); B.line(0, CEILING + 52, W, CEILING + 52, 3, (26, 28, 24))   # a pipe
    B.rect(600, CEILING + 20, 632, FLOOR - 300, (70, 74, 66))
    _lamp(B, E, 420, warm=(255, 214, 150))
    B.rect(880, FLOOR - 320, 1010, FLOOR, (82, 86, 80), radius=40); B.rect(880, FLOOR - 60, 1010, FLOOR, (50, 52, 48))   # the boiler
    B.rect(640, FLOOR - 130, 790, FLOOR, (66, 52, 36), radius=4); B.rect(668, FLOOR - 240, 800, FLOOR - 130, (78, 62, 42), radius=4)
    B.line(640, FLOOR - 66, 790, FLOOR - 66, 3, (40, 30, 20))
    F.rect(-40, FLOOR - 170, 96, FLOOR + 40, (18, 15, 11, 255), radius=6)   # a crate close to the camera
    return {"door": 160, "door_w": 190, "door_h": 500, "window": 820, "window_y": 525, "lamp": 420, "spots": {"crates": 560}}


def _set_street(B, E, F):
    B.grad(0, FLOOR, (10, 14, 34), (30, 38, 72))
    for i, (sx, sy) in enumerate(((120, 190), (310, 120), (520, 260), (700, 150), (930, 220), (60, 380), (860, 420), (430, 420))):
        E.dot(sx, sy, 2.5 + (i % 3), (220, 228, 255, 150))
    for x0, x1, top, lit in ((-20, 300, 700, (1,)), (330, 640, 610, (0, 2)), (680, 1100, 740, ())):   # houses
        B.rect(x0, top, x1, FLOOR, (22, 25, 44))
        B.poly([(x0 - 14, top), ((x0 + x1) / 2, top - 130), (x1 + 14, top)], (16, 18, 34))
        for k in range(3):
            wx = x0 + 44 + k * ((x1 - x0 - 88) / 2.6)
            B.rect(wx, top + 70, wx + 70, top + 170, (12, 14, 26), radius=3)
            if k in lit:
                E.rect(wx, top + 70, wx + 70, top + 170, (255, 214, 130, 215), radius=3)
    _doorway(B, 250, 150, 330, frame=(14, 16, 30), inside=(6, 7, 14))
    B.grad(FLOOR, H, (44, 48, 68), (16, 18, 28))
    B.rect(0, FLOOR - 4, W, FLOOR + 26, (66, 70, 94))                        # the kerb
    for x0 in range(40, W, 240):
        B.rect(x0, FLOOR + 230, x0 + 130, FLOOR + 246, (120, 124, 140))
    B.line(830, FLOOR, 830, 520, 12, (14, 15, 26)); B.line(830, 520, 760, 500, 10, (14, 15, 26))   # the street lamp
    B.rect(716, 492, 780, 520, (20, 22, 36), radius=6)
    return {"door": 250, "door_w": 150, "door_h": 330, "lamp": 748, "lamp_y": 520, "outdoor": True, "spots": {"house": 250}}


def _set_forest(B, E, F):
    B.grad(0, FLOOR, (8, 16, 30), (22, 42, 52))
    E.dot(820, 330, 74, (214, 226, 255, 235)); E.dot(852, 310, 62, (10, 18, 34, 255))    # a crescent moon
    for i, (sx, sy) in enumerate(((150, 170), (360, 250), (560, 130), (700, 300), (250, 400), (980, 200))):
        E.dot(sx, sy, 2.5 + (i % 2), (220, 232, 255, 140))
    for x0, wd, tone in ((70, 54, (22, 38, 44)), (250, 40, (24, 42, 48)), (470, 62, (20, 36, 42)), (660, 44, (24, 42, 48)), (840, 58, (22, 38, 44)), (990, 40, (24, 42, 48))):
        B.rect(x0, 0, x0 + wd, FLOOR, tone)                                  # far trunks
        B.poly([(x0 - 90, 620), (x0 + wd / 2, 240), (x0 + wd + 90, 620)], mix(tone, (0, 0, 0), 0.2))
    for x0, wd in ((170, 84), (560, 96), (900, 80)):
        B.rect(x0, 0, x0 + wd, FLOOR, (12, 22, 26))                          # nearer trunks
    B.grad(FLOOR, H, (26, 44, 40), (8, 14, 14))
    for x0 in range(0, W, 46):
        B.poly([(x0, FLOOR + 6), (x0 + 12, FLOOR - 26 - (x0 * 7) % 22), (x0 + 24, FLOOR + 6)], (16, 30, 28))   # grass
    F.rect(-70, 0, 64, FLOOR + 90, (4, 8, 10, 255)); F.rect(1010, 0, 1150, FLOOR + 90, (4, 8, 10, 255))   # trunks close to the camera
    return {"outdoor": True, "moon": (820, 330), "spots": {"trees": 560}}


def _set_office(B, E, F):
    _room(B, (52, 62, 84), (36, 44, 62), (40, 44, 56), (10, 12, 16))
    for i in range(4):                                                      # the wall of windows, blinds down
        x0 = 60 + i * 170
        B.rect(x0, 520, x0 + 140, 900, (16, 22, 40)); E.rect(x0, 520, x0 + 140, 900, (70, 100, 160, 70))
        for k in range(12):
            B.line(x0, 532 + k * 31, x0 + 140, 532 + k * 31, 5, (30, 38, 58)); E.line(x0, 532 + k * 31, x0 + 140, 532 + k * 31, 5, (30, 38, 58, 255))
    _doorway(B, 920, 190, 510, frame=(24, 30, 44))
    B.rect(300, CEILING + 6, 620, CEILING + 30, (40, 46, 60)); E.rect(316, CEILING + 22, 604, CEILING + 34, (220, 236, 255, 220))   # ceiling panel
    for x0 in (90, 480):                                                    # desks with monitors
        B.rect(x0, FLOOR - 190, x0 + 330, FLOOR - 166, (70, 62, 54), radius=4)
        B.rect(x0 + 14, FLOOR - 166, x0 + 30, FLOOR, (30, 30, 36)); B.rect(x0 + 300, FLOOR - 166, x0 + 316, FLOOR, (30, 30, 36))
        B.rect(x0 + 110, FLOOR - 330, x0 + 250, FLOOR - 226, (14, 16, 24), radius=6); E.rect(x0 + 118, FLOOR - 322, x0 + 242, FLOOR - 234, (60, 120, 200, 110), radius=4)
        B.rect(x0 + 170, FLOOR - 226, x0 + 190, FLOOR - 190, (14, 16, 24))
    return {"door": 920, "door_w": 190, "door_h": 510, "lamp": 460, "spots": {"desk": 420}}


def _set_rooftop(B, E, F):
    B.grad(0, FLOOR, (14, 12, 40), (52, 40, 84))
    E.dot(250, 300, 60, (236, 232, 255, 230))
    for i, (x0, x1, top) in enumerate(((0, 150, 760), (130, 300, 620), (290, 430, 820), (430, 640, 560), (640, 780, 700), (770, 960, 640), (950, 1100, 800))):
        tone = mix((20, 18, 44), (30, 26, 60), (i % 3) / 2)
        B.rect(x0, top, x1, FLOOR, tone)
        for k in range(18):
            wx, wy = x0 + 18 + (k % 3) * 40, top + 30 + (k // 3) * 62
            if wx + 22 < x1 and wy + 30 < FLOOR - 120 and (i * 7 + k * 5) % 4 == 0:
                E.rect(wx, wy, wx + 22, wy + 30, (255, 220, 140, 190))
    B.rect(0, FLOOR - 120, W, FLOOR, (24, 22, 46)); B.rect(0, FLOOR - 132, W, FLOOR - 112, (44, 40, 76))     # the parapet
    B.rect(60, FLOOR - 560, 300, FLOOR, (30, 28, 56)); B.rect(48, FLOOR - 580, 312, FLOOR - 552, (44, 40, 76))   # the stair head
    _doorway(B, 180, 170, 430, frame=(18, 16, 36))
    B.line(880, FLOOR - 120, 880, FLOOR - 470, 8, (16, 14, 32)); B.line(840, FLOOR - 400, 920, FLOOR - 400, 6, (16, 14, 32))
    E.dot(880, FLOOR - 478, 8, (255, 70, 60, 240))
    _ground(B, (44, 40, 68), (16, 14, 28))
    return {"door": 180, "door_w": 170, "door_h": 430, "outdoor": True, "moon": (250, 300), "spots": {"edge": 0.8 * W}}


def _set_elevator(B, E, F):
    _room(B, (76, 80, 92), (52, 56, 68), (40, 42, 50), (12, 12, 15))
    for x0 in (60, 880):
        B.rect(x0, CEILING + 40, x0 + 140, FLOOR - 40, (62, 66, 78), radius=6)   # side panels
    B.rect(300, FLOOR - 640, 780, FLOOR, (30, 32, 40), radius=4)            # the door frame
    B.rect(318, FLOOR - 622, 762, FLOOR, (5, 6, 10))
    B.rect(440, FLOOR - 730, 640, FLOOR - 662, (12, 13, 18), radius=8); E.rect(452, FLOOR - 720, 628, FLOOR - 672, (255, 90, 60, 210), radius=6)   # the floor display
    B.rect(820, FLOOR - 420, 862, FLOOR - 250, (24, 26, 32), radius=6)
    for k in range(4):
        E.dot(841, FLOOR - 396 + k * 40, 9, (255, 214, 130, 200 if k == 1 else 90))
    B.rect(60, FLOOR - 300, 1020, FLOOR - 284, (120, 126, 140), radius=6)   # the hand rail
    B.rect(300, FLOOR - 300, 780, FLOOR - 284, (30, 32, 40))
    E.rect(380, CEILING + 8, 700, CEILING + 26, (230, 240, 255, 220))
    return {"door": 540, "door_w": 444, "door_h": 622, "split": True, "lamp": 540, "spots": {}}


_SET_FUNCS = {"bedroom": _set_bedroom, "hallway": _set_hallway, "living_room": _set_living_room,
              "stairwell": _set_stairwell, "basement": _set_basement, "street": _set_street,
              "forest": _set_forest, "office": _set_office, "rooftop": _set_rooftop, "elevator": _set_elevator}


@lru_cache(maxsize=len(_SET_FUNCS))
def build_set(name: str):
    """A set, drawn once: (what the light falls on, what glows by itself, what stands in front
    of the people, where its door, window and lamp are). The set is painted as it looks under
    a work light; the light of each shot then darkens and tints it."""
    from PIL import ImageEnhance
    B, E, F = Layer(0, H), Layer(0, H), Layer(0, H)
    B.rect(0, 0, W, H, (0, 0, 0, 255))
    info = _SET_FUNCS[name](B, E, F)
    front = F.flat() if F.im.getbbox() else None
    base = ImageEnhance.Brightness(B.flat().convert("RGB")).enhance(1.25 if info.get("outdoor") else 1.6)
    return base, E.flat(), front, info


def leaf(L: Layer, x: float, w: float, h: float, open_: float, color=(74, 64, 60), split: bool = False, dx: float = 0.0):
    """A door in its frame: shut at 0, swung wide at 1. An elevator's two halves slide apart."""
    o = clamp(open_)
    dark = mix(color, (0, 0, 0), 0.4)
    if split:
        half = w / 2 * (1 - 0.94 * o)
        L.rect(x - w / 2, FLOOR - h, x - w / 2 + half, FLOOR, color)
        L.rect(x + w / 2 - half, FLOOR - h, x + w / 2, FLOOR, color)
        if half > 6:
            L.line(x - w / 2 + half, FLOOR - h, x - w / 2 + half, FLOOR, 3, dark)
            L.line(x + w / 2 - half, FLOOR - h, x + w / 2 - half, FLOOR, 3, dark)
        return
    x0 = x - w / 2 + dx
    wd = w * (1 - 0.84 * o)
    skew = 26 * o
    tone = mix(color, (0, 0, 0), 0.3 * o)
    L.poly([(x0, FLOOR - h), (x0 + wd, FLOOR - h + skew), (x0 + wd, FLOOR - skew * 0.3), (x0, FLOOR)], tone)
    if wd > 60:
        L.poly([(x0 + wd * 0.14, FLOOR - h * 0.9 + skew * 0.2), (x0 + wd * 0.86, FLOOR - h * 0.9 + skew * 0.9),
                (x0 + wd * 0.86, FLOOR - h * 0.56), (x0 + wd * 0.14, FLOOR - h * 0.56)], dark)
        L.poly([(x0 + wd * 0.14, FLOOR - h * 0.48), (x0 + wd * 0.86, FLOOR - h * 0.48),
                (x0 + wd * 0.86, FLOOR - h * 0.1 - skew * 0.2), (x0 + wd * 0.14, FLOOR - h * 0.1)], dark)
    L.dot(x0 + wd - 22 * (1 - 0.6 * o), FLOOR - h * 0.46, 9, (176, 150, 96))


LEAF_COLORS = {"bedroom": (86, 78, 92), "hallway": (92, 74, 62), "living_room": (96, 76, 62), "stairwell": (74, 84, 84),
               "basement": (70, 64, 50), "street": (84, 44, 42), "office": (70, 78, 96), "rooftop": (64, 58, 92),
               "elevator": (104, 108, 122)}


# ------------------------------------------------------------------ the script ----

def clean_actor(raw, default_pose: str = "stand", default_at: str = "center") -> dict | None:
    if raw in (None, False, "", "none"):
        return None
    if raw is True:
        raw = {}
    if isinstance(raw, str):
        raw = {"pose": raw}
    if not isinstance(raw, dict):
        return {"pose": "?", "at": default_at}
    out = {"pose": str(raw.get("pose") or default_pose).strip().lower(), "at": raw.get("at", default_at)}
    for key in ("to", "face", "kind", "eyes", "count"):
        if raw.get(key) not in (None, ""):
            out[key] = raw[key]
    for key in ("at", "to", "face", "kind", "eyes"):
        if isinstance(out.get(key), str):
            out[key] = out[key].strip().lower()
    return out


def clean_shot(raw: dict) -> dict:
    s = raw if isinstance(raw, dict) else {}
    out = {"say": " ".join(str(s.get("say") or "").split()),
           "set": str(s.get("set") or "").strip().lower(),
           "light": str(s.get("light") or "lamp").strip().lower(),
           "you": clean_actor(s.get("you", True)),
           "them": clean_actor(s.get("them"), default_at="right"),
           "iro": bool(s.get("iro", False)),
           "event": str(s.get("event") or "none").strip().lower(),
           "camera": str(s.get("camera") or "push").strip().lower(),
           "door": str(s.get("door") or "closed").strip().lower()}
    if out["them"] is not None:
        out["them"].setdefault("kind", "shadow")
    for key in ("target", "banner"):
        if s.get(key):
            out[key] = " ".join(str(s[key]).split())
    if "target" in out:
        out["target"] = out["target"].lower()
    if "banner" in out:
        out["banner"] = out["banner"].upper()
    return out


def clean_episode(raw: dict) -> dict:
    """An episode with its words tidied and every default filled in."""
    e = raw if isinstance(raw, dict) else {}
    out = {"title": " ".join(str(e.get("title") or "").split())[:60],
           "question": " ".join(str(e.get("question") or "").split()),
           "a": " ".join(str(e.get("a") or "").upper().split()),
           "b": " ".join(str(e.get("b") or "").upper().split()),
           "recap": " ".join(str(e.get("recap") or "").split()),
           "caption": " ".join(str(e.get("caption") or "").split()),
           "shots": [clean_shot(s) for s in (e.get("shots") if isinstance(e.get("shots"), list) else [])]}
    for key in ("part", "voted"):
        if e.get(key):
            out[key] = int(e[key]) if key == "part" else " ".join(str(e[key]).upper().split())
    return out


def _spot_ok(v, info: dict) -> bool:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return -0.3 <= v <= 1.3
    return isinstance(v, str) and (v in SPOTS or v in ("door", "window", "lamp") or v in info.get("spots", {}))


def check_episode(raw: dict) -> list[str]:
    """What is wrong with an episode's script. An empty list means it can be drawn."""
    ep = clean_episode(raw)
    out = []
    shots = ep["shots"]
    if not SHOTS_MIN <= len(shots) <= SHOTS_MAX:
        out.append(f"an episode has {SHOTS_MIN} to {SHOTS_MAX} shots, this one has {len(shots)}")
    for side in ("a", "b"):
        if not ep[side]:
            out.append(f"choice {side.upper()} is missing")
        elif len(ep[side]) > OPTION_MAX_CHARS or len(ep[side].split()) > 2:
            out.append(f"choice {side.upper()} must be one or two short words (at most {OPTION_MAX_CHARS} letters), got {ep[side]!r}")
    if ep["a"] and ep["a"] == ep["b"]:
        out.append("the two choices are the same")
    if not ep["question"]:
        out.append("the question that ends the episode is missing")
    for n, s in enumerate(shots, 1):
        where = f"shot {n}"
        if not s["say"]:
            out.append(f"{where}: the narrator needs a line")
        elif len(s["say"].split()) > SAY_MAX_WORDS:
            out.append(f"{where}: the line is {len(s['say'].split())} words; keep a shot to {SAY_MAX_WORDS}")
        if s["set"] not in SETS:
            out.append(f"{where}: set must be one of {', '.join(SETS)}, got {s['set']!r}")
            continue
        info = build_set(s["set"])[3]
        if s["light"] not in LIGHTS:
            out.append(f"{where}: light must be one of {', '.join(LIGHTS)}, got {s['light']!r}")
        if s["event"] not in EVENTS:
            out.append(f"{where}: event must be one of {', '.join(EVENTS)}, got {s['event']!r}")
        if s["camera"] not in CAMERAS:
            out.append(f"{where}: camera must be one of {', '.join(CAMERAS)}, got {s['camera']!r}")
        if s["door"] not in ("closed", "open"):
            out.append(f"{where}: door is closed or open, got {s['door']!r}")
        if s.get("target") and s["target"] not in ("door", "window"):
            out.append(f"{where}: target is door or window, got {s['target']!r}")
        if s.get("banner") and len(s["banner"]) > 18:
            out.append(f"{where}: the banner is at most 18 letters, got {s['banner']!r}")
        for who in ("you", "them"):
            a = s[who]
            if a is None:
                continue
            if a["pose"] not in POSES:
                out.append(f"{where}: {who} pose must be one of {', '.join(POSES)}, got {a['pose']!r}")
            for key in ("at", "to"):
                if key in a and not _spot_ok(a[key], info):
                    out.append(f"{where}: {who}.{key} {a[key]!r} is not a place in the {s['set']} "
                               f"(use {', '.join(list(SPOTS) + ['door', 'window'] + list(info.get('spots', {})))} or a number from 0 to 1)")
            if a.get("face") not in (None, "left", "right"):
                out.append(f"{where}: {who}.face is left or right, got {a['face']!r}")
        t = s["them"]
        if t is not None:
            if t["kind"] not in KINDS:
                out.append(f"{where}: them.kind must be one of {', '.join(KINDS)}, got {t['kind']!r}")
            if t.get("eyes", "red") not in EYES:
                out.append(f"{where}: them.eyes must be one of {', '.join(EYES)}, got {t.get('eyes')!r}")
            try:
                if not 1 <= int(t.get("count", 2)) <= 6:
                    out.append(f"{where}: them.count is 1 to 6")
            except (TypeError, ValueError):
                out.append(f"{where}: them.count must be a number")
    return out


# ------------------------------------------------------------------- the timing ----

def _line_words(line: str) -> list[str]:
    return line.split()


def plan(raw: dict, voice: dict | None = None) -> dict:
    """When every shot and every word happens. `voice` is {"words": [{"say", "t", "end"}, ...],
    "duration": seconds} from the narrator's recording; without it the narrator is taken to
    speak at an even pace, so a silent episode still reads well."""
    ep = clean_episode(raw)
    lines = [_line_words(s["say"]) for s in ep["shots"]]
    count = sum(len(l) for l in lines)
    shots, words = [], []
    if voice and len(voice.get("words") or []) == count and count:
        vw = voice["words"]
        k = 0
        starts = []
        for l in lines:
            starts.append(max(0.0, float(vw[k]["t"]) - 0.10) if l else (starts[-1] if starts else 0.0))
            k += len(l)
        starts[0] = 0.0
        end = float(voice.get("duration") or vw[-1].get("end") or vw[-1]["t"] + 0.4)
        k = 0
        for i, l in enumerate(lines):
            stop = starts[i + 1] if i + 1 < len(lines) else end + TAIL
            shots.append({"start": round(starts[i], 3), "end": round(max(stop, starts[i] + 0.5), 3)})
            for w in l:
                item = vw[k]
                words.append({"say": w, "t": round(float(item["t"]), 3),
                              "end": round(float(item.get("end") or item["t"] + 0.25), 3), "shot": i})
                k += 1
        voiced = True
    else:
        t = 0.0
        for i, l in enumerate(lines):
            dur = max(1.6, len(l) / WORDS_PER_SECOND + SHOT_PAD)
            for j, w in enumerate(l):
                wt = t + 0.12 + j / WORDS_PER_SECOND
                words.append({"say": w, "t": round(wt, 3), "end": round(wt + 1 / WORDS_PER_SECOND, 3), "shot": i})
            shots.append({"start": round(t, 3), "end": round(t + dur, 3)})
            t += dur
        if shots:
            shots[-1]["end"] = round(shots[-1]["end"] + TAIL, 3)
        voiced = False
    # the words on screen: up to three at a time, never across a full stop, a comma or a cut
    groups, cur = [], []
    for k, w in enumerate(words):
        cur.append(k)
        nxt = words[k + 1] if k + 1 < len(words) else None
        if len(cur) >= 3 or nxt is None or nxt["shot"] != w["shot"] or w["say"][-1:] in ".,!?;:":
            groups.append(cur)
            cur = []
    spans = []
    for g, idx in enumerate(groups):
        start = words[idx[0]]["t"]
        stop = words[groups[g + 1][0]]["t"] if g + 1 < len(groups) else words[idx[-1]]["end"] + 0.6
        spans.append({"words": idx, "start": start, "end": min(stop, words[idx[-1]]["end"] + 0.9)})
    total = shots[-1]["end"] if shots else 0.0
    return {"shots": shots, "words": words, "groups": spans, "total": round(total, 3), "voiced": voiced,
            "said_until": words[-1]["end"] if words else 0.0}


def _shot_at(timing: dict, t: float) -> int:
    shots = timing["shots"]
    for i, s in enumerate(shots):
        if t < s["end"]:
            return i
    return len(shots) - 1


# -------------------------------------------------------------------- one shot ----

def _noise(t: float, seed: float = 0.0) -> float:
    """A wobble between -1 and 1 that is the same every time it is asked for the same moment."""
    return math.sin(t * 12.9898 + seed * 78.233) * 0.5 + math.sin(t * 39.3468 + seed * 11.135) * 0.3 + math.sin(t * 93.989 + seed * 4.1) * 0.2


def _beat(t: float) -> float:
    """A heartbeat: two thumps close together, about seventy a minute."""
    u = (t * 1.15) % 1.0
    return max(math.exp(-((u - 0.08) / 0.045) ** 2), 0.7 * math.exp(-((u - 0.30) / 0.05) ** 2))


def _x(v, info: dict, default: float = 0.5) -> float:
    """A place as a pixel across the picture."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) * W
    if isinstance(v, str):
        if v in SPOTS:
            return SPOTS[v] * W
        if v in info.get("spots", {}):
            return float(info["spots"][v])
        if v in ("door", "window", "lamp") and v in info:
            return float(info[v])
    return default * W


def event_at(dur: float) -> float:
    """How far into a shot of `dur` seconds its event happens (the sound uses the same moment)."""
    return clamp(0.42 * dur, 0.5, 2.2)


def _state(shot: dict, info: dict, u: float, dur: float) -> dict:
    """Where everything is `u` seconds into a shot that lasts `dur`."""
    ev = shot["event"]
    te = event_at(dur)
    k = clamp(u / dur) if dur > 0 else 1.0
    st = {"te": te, "power": 1.0, "door": 1.0 if shot["door"] == "open" else 0.0, "jolt": 0.0, "eyes": 1.0,
          "ring": 0.0, "shake": 0.0, "pulse": 0.0, "impact": None}
    target = shot.get("target") or ("door" if "door" in info else "window" if "window" in info else None)
    if target and target not in info:
        target = "door" if "door" in info else "window" if "window" in info else None
    st["target"] = target
    if ev == "knock":
        for j in range(3):
            a = u - (te + j * 0.26)
            if 0 <= a < 0.2:
                st["jolt"] = (1 - a / 0.2) * (6 if j % 2 == 0 else -6)
                st["impact"] = a / 0.2
    elif ev == "door_open":
        st["door"] = back_out(span(u, te, te + 0.75))
    elif ev == "door_close":
        st["door"] = 1 - smooth(span(u, te, te + 0.16))
        st["shake"] = max(0.0, 1 - (u - te - 0.14) / 0.45) if u >= te + 0.14 else 0.0
    elif ev == "lights_out":
        if u >= te:
            st["power"] = 0.0 if (u - te) > 0.3 or int((u - te) * 20) % 2 else 0.8
    elif ev == "lights_on":
        st["power"] = 0.0 if u < te else (1.0 if (u - te) > 0.25 or int((u - te) * 24) % 2 else 0.2)
    elif ev == "eyes":
        st["eyes"] = smooth(span(u, te, te + 0.35))
    elif ev == "phone_ring":
        st["ring"] = (0.55 + 0.45 * math.sin((u - te) * 16)) if u >= te else 0.0
    elif ev == "shake":
        st["shake"] = max(0.0, 1 - (u - te) / 0.8) if u >= te else 0.0
    elif ev == "heartbeat":
        st["pulse"] = _beat(u)
    if shot["light"] == "flicker" and st["power"] > 0:
        st["power"] *= 1.0 if (_noise(u * 0.9, 3.0) > -0.42 or int(u * 22) % 3 == 0) else 0.12
    if shot["camera"] == "shake":
        st["shake"] = max(st["shake"], 0.35)

    def raw_at(a):
        return a.get("at")

    def actor(a, who):
        if a is None:
            return None
        pose = a["pose"]
        x0 = _x(a.get("at"), info, 0.5 if who == "you" else 0.72)
        if pose == "lie" and "bed" in info and raw_at(a) in (None, "center", "bed", "left", "far_left"):
            x0 = info["bed"] + 200
        moving = "to" in a
        x1 = _x(a["to"], info) if moving else x0
        if not moving and pose in ("walk", "run"):
            x1 = x0 + (1 if a.get("face", "right") == "right" else -1) * (170 if pose == "walk" else 420)
            moving = True
        x = lerp(x0, x1, k if pose == "run" else smooth(k))
        if moving and pose == "stand":
            pose = "walk"
        return {"pose": pose, "x": x, "x0": x0, "x1": x1, "moving": moving and abs(x1 - x0) > 4,
                "face": a.get("face"), "raw": a}
    st["you"], st["them"] = actor(shot["you"], "you"), actor(shot["them"], "them")
    you, them = st["you"], st["them"]
    tx = info.get(target) if target else None
    for a, other in ((you, them), (them, you)):
        if a is None:
            continue
        if a["face"] in ("left", "right"):
            a["dir"] = 1 if a["face"] == "right" else -1
        elif a["moving"]:
            a["dir"] = 1 if a["x1"] >= a["x0"] else -1
        elif other is not None:
            a["dir"] = 1 if other["x"] >= a["x"] else -1
        elif tx is not None and abs(tx - a["x"]) > 30:
            a["dir"] = 1 if tx >= a["x"] else -1
        else:
            a["dir"] = 1
    return st


def _draw_actor(L: Layer, a: dict, info: dict, u: float, who: str, st: dict, k_index: int = 0) -> dict:
    """Draw one figure and return where its head and hand ended up."""
    pose, x, face = a["pose"], a["x"], a["dir"]
    raw = a["raw"]
    kind = raw.get("kind", "shadow") if who == "them" else "you"
    look = {"you": (YOU, YOU_SHADE, 1.0, None, False), "friend": (FRIEND, FRIEND_SHADE, 0.94, None, False),
            "stranger": (STRANGER, STRANGER_SHADE, 1.04, None, True),
            "shadow": (SHADOW, SHADOW, 1.16, SHADOW_RIM, False), "crowd": (SHADOW, SHADOW, 1.04, SHADOW_RIM, False)}[kind]
    color, shade, scale, rim, hat = look
    if kind == "crowd":
        scale *= 1.0 + 0.12 * ((k_index * 37) % 5) / 4
    stride = 74 * scale * (1.9 if pose == "run" else 1.0)
    phase = (x - a["x0"]) / stride * math.pi * (1 if face >= 0 else -1) + k_index * 1.7
    if pose in ("walk", "run") and not a["moving"]:
        phase = u * (9 if pose == "run" else 5)
    angles = _pose(pose, phase, u + k_index * 0.6)
    ground, rot = FLOOR, 0.0
    if pose == "lie":
        on_bed = "bed" in info and abs(x - (info["bed"] + 200)) < 30
        ground = (info["bed_y"] - 14) if on_bed else FLOOR - 16
        rot, face, scale = -90.0, 1, scale * (0.86 if on_bed else 1.0)
        angles = {"leg_f": (2, 0), "leg_b": (-2, 0), "arm_f": (4, 6), "arm_b": (-4, 2), "lean": 0}
    elif pose == "fall":
        f = smooth(span(u, st["te"] * 0.6, st["te"] * 0.6 + 0.42))
        rot = -84.0 * f * face
        ground = FLOOR - 16 * f
        angles = {"leg_f": (10 - 8 * f, 2), "leg_b": (-10 + 8 * f, -2), "arm_f": (120 - 110 * f, 140 - 130 * f), "arm_b": (-120 + 110 * f, -140 + 130 * f), "lean": -6 * (1 - f)}
    elif pose == "sit" and "seat" in info and abs(x - info["seat"]) < 170:
        angles = dict(angles, seat=info.get("seat_h", 124))
    if who == "you" and st.get("light") == "flashlight" and pose in ("stand", "walk", "listen", "point"):
        angles = dict(angles, arm_f=(72, 78))
    pts = stick(L, x, ground, angles, face=face, color=color, shade=shade, scale=scale, rot=rot, rim=rim, hat=hat)
    pts.update(x=x, face=face, kind=kind, scale=scale)
    return pts


def _light_mask(shot: dict, info: dict, st: dict, pts: dict, u: float):
    """How bright and what colour every part of the picture is, as a picture to multiply by."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    light = shot["light"]
    power = st["power"]
    outdoor = info.get("outdoor")
    if light in ("lamp", "flicker") and "lamp" not in info:
        light = "moon"
    amb, tint = {"lamp": (0.36, (255, 236, 206)), "flicker": (0.36, (255, 236, 206)), "moon": (0.40, (176, 198, 255)),
                 "flashlight": (0.15, (170, 180, 224)), "red": (0.34, (255, 84, 70)), "green": (0.22, (150, 224, 172)),
                 "dark": (0.19, (150, 162, 214)), "dawn": (0.84, (255, 228, 194))}[light]
    if light in ("lamp", "flicker"):
        amb = lerp(0.13, amb, power)
    elif power < 1 and light not in ("dark",):
        amb = lerp(0.12, amb, power)
    if light == "red":
        amb *= 0.72 + 0.28 * math.sin(u * 5.2)
    amb *= 1 - 0.22 * st["pulse"]
    mask = Image.new("RGB", (LMW, LMH), tuple(int(c * amb) for c in tint))
    src = Image.new("RGB", (LMW, LMH), (0, 0, 0))
    d = ImageDraw.Draw(src)

    def q(pts_):
        return [(x / 8, y / 8) for x, y in pts_]

    def tone(color, k):
        return tuple(int(clamp(c * k / 255) * 255) for c in color)

    you = pts.get("you")
    if light in ("lamp", "flicker") and power > 0:
        lx, ly = info["lamp"], info.get("lamp_y", CEILING + 90)
        d.polygon(q([(lx - 50, ly), (lx + 50, ly), (lx + 400, FLOOR + 150), (lx - 400, FLOOR + 150)]), fill=tone((255, 240, 212), 0.86 * power))
        d.ellipse([(lx - 380) / 8, (FLOOR - 40) / 8, (lx + 380) / 8, (FLOOR + 200) / 8], fill=tone((255, 240, 212), 1.0 * power))
    elif light == "moon":
        if "window" in info and not outdoor:
            wx, wy = info["window"], info["window_y"]
            d.polygon(q([(wx - 110, wy - 150), (wx + 110, wy - 150), (wx - 250, FLOOR + 170), (wx - 620, FLOOR + 170)]), fill=tone((190, 212, 255), 0.82))
        else:
            mx = info.get("moon", (W / 2, 300))[0]
            d.ellipse([(mx - 620) / 8, 20, (mx + 620) / 8, (FLOOR + 260) / 8], fill=tone((180, 204, 255), 0.5))
            d.ellipse([10, (FLOOR - 60) / 8, LMW - 10, (FLOOR + 190) / 8], fill=tone((180, 204, 255), 0.42))
    elif light == "flashlight":
        if you:
            hx, hy = you["hand"]
            f = you["face"]
            sway = math.sin(u * 1.7) * 26
            d.polygon(q([(hx, hy - 14), (hx + f * 980, hy - 300 + sway), (hx + f * 980, hy + 360 + sway), (hx, hy + 14)]), fill=tone((255, 246, 222), 1.0))
        else:
            d.polygon(q([(0, FLOOR - 320), (W, FLOOR - 620), (W, FLOOR + 160), (0, FLOOR - 250)]), fill=tone((255, 246, 222), 0.9))
    elif light == "red":
        d.ellipse([10, 10, LMW - 10, 110], fill=tone((255, 70, 60), 0.5 + 0.2 * math.sin(u * 5.2)))
    elif light == "green":
        them = pts.get("them")
        gx = them[0]["x"] if them else info.get(st["target"] or "door", W * 0.74)
        k = 0.8 + 0.12 * math.sin(u * 3.1)
        d.ellipse([(gx - 360) / 8, (FLOOR - 720) / 8, (gx + 360) / 8, (FLOOR + 170) / 8], fill=tone((110, 255, 150), k))
    elif light == "dawn":
        sx = info.get("window", W * 0.78)
        d.ellipse([(sx - 760) / 8, 10, (sx + 760) / 8, (FLOOR + 320) / 8], fill=tone((255, 234, 200), 0.9))
    if you:                                              # a little light always finds you
        cx, cy = (you["head"][0] + you["hip"][0]) / 2, (you["head"][1] + you["hip"][1]) / 2
        d.ellipse([(cx - 230) / 8, (cy - 260) / 8, (cx + 230) / 8, (cy + 280) / 8], fill=tone((200, 210, 240), 0.34))
    iro = pts.get("iro")
    if iro:                                              # Iro lights what is around it
        ix, iy = iro
        d.ellipse([(ix - 230) / 8, (iy - 330) / 8, (ix + 230) / 8, (iy + 120) / 8], fill=tone((255, 196, 116), 0.62))
    if you and (you.get("phone") or st["ring"] > 0):
        hx, hy = you["hand"]
        k = max(0.55 if you.get("phone") else 0.0, st["ring"] * 0.7)
        d.ellipse([(hx - 150) / 8, (hy - 170) / 8, (hx + 150) / 8, (hy + 130) / 8], fill=tone((140, 216, 255), k))
    src = src.filter(ImageFilter.GaussianBlur(5.5 if light == "flashlight" else 8))
    mask = ImageChops.multiply(ImageChops.add(mask, src), _vignette())
    k = {"flashlight": 0.2, "green": 0.2, "dawn": 0.1, "red": 0.16}.get(light, 0.13)
    haze = src.point(lambda v: int(v * k)).resize((W, H), Image.Resampling.BILINEAR)   # the light in the air
    return mask.resize((W, H), Image.Resampling.BILINEAR), haze


@lru_cache(maxsize=1)
def _vignette():
    from PIL import Image
    im = Image.new("RGB", (LMW, LMH))
    px = im.load()
    for y in range(LMH):
        for x in range(LMW):
            dx, dy = (x - LMW / 2) / (LMW / 2), (y - LMH * 0.58) / (LMH * 0.74)
            v = int(255 * clamp(1.06 - 0.42 * (dx * dx + dy * dy) ** 0.9, 0.34, 1.0))
            px[x, y] = (v, v, v)
    return im


def _glow(E, x: float, y: float, size: float, color: tuple, k: float = 1.0):
    """A soft light pasted onto the picture of things that glow."""
    if k <= 0.01 or size < 4:
        return
    halo = _halo(int(size), color)
    if k < 0.999:
        halo = halo.copy()
        halo.putalpha(halo.getchannel("A").point(lambda v: int(v * clamp(k))))
    E.alpha_composite(halo, (int(x - size / 2), int(y - size / 2)))


@lru_cache(maxsize=8)
def _iro_pic(height: int):
    from PIL import Image
    src = _iro_source()
    return src.resize((max(8, int(src.width * height / src.height)), height), Image.Resampling.LANCZOS)


def scene(shot: dict, u: float, dur: float):
    """The picture of one shot `u` seconds in, before any words go on it. Returns (picture, state)."""
    from PIL import Image, ImageChops, ImageDraw
    base, glows, front, info = build_set(shot["set"])
    st = _state(shot, info, u, dur)
    st["light"] = shot["light"]
    L = Layer()
    pts = {}
    # the door, behind everyone
    if "door" in info:
        color = LEAF_COLORS.get(shot["set"], (74, 64, 60))
        leaf(L, info["door"], info["door_w"], info["door_h"], st["door"], color, split=info.get("split", False),
             dx=st["jolt"] if st["target"] == "door" else 0.0)
    for x in info.get("doors", ()):
        leaf(L, x, info["door_w"], info["door_h"], 0.0, LEAF_COLORS.get(shot["set"], (74, 64, 60)))
    them = st["them"]
    if them is not None:
        n = int(them["raw"].get("count", 3 if them["raw"].get("kind") == "crowd" else 1)) if them["raw"].get("kind") == "crowd" else 1
        heads = []
        for j in range(n):
            a = dict(them)
            off = (j - (n - 1) / 2) * 104
            a["x"], a["x0"] = them["x"] + off, them["x0"] + off
            heads.append(_draw_actor(L, a, info, u, "them", st, j))
        pts["them"] = heads
    you = st["you"]
    if you is not None:
        p = _draw_actor(L, you, info, u, "you", st)
        p["phone"] = you["pose"] == "phone"
        pts["you"] = p
        if shot["iro"]:
            bob = math.sin(u * 3.2) * 5
            pts["iro"] = (p["x"] - p["face"] * 150, FLOOR - 6 + bob)
    pic = base.copy()
    moving = L.flat()
    pic.paste(moving, (0, BAND_TOP), moving)
    solid = Image.new("L", (W, H), 0)                    # where a person, a door or something in front is
    solid.paste(moving.getchannel("A"), (0, BAND_TOP))
    if front is not None:
        pic.paste(front, (0, 0), front)
        solid = ImageChops.lighter(solid, front.getchannel("A"))
    mask, haze = _light_mask(shot, info, st, pts, u)
    pic = ImageChops.add(ImageChops.multiply(pic, mask), haze)

    # what glows by itself: windows and signs, the lamp, eyes, screens, Iro
    E = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dim = {"dark": 0.5, "flashlight": 0.6, "green": 0.7, "red": 0.6}.get(shot["light"], 1.0)
    if st["power"] < 0.5 and shot["light"] in ("lamp", "flicker"):
        dim = 0.6
    g = glows.copy()
    alpha = ImageChops.multiply(g.getchannel("A"), ImageChops.invert(solid))
    g.putalpha(alpha if dim >= 0.999 else alpha.point(lambda v: int(v * dim)))
    E.alpha_composite(g)
    d = ImageDraw.Draw(E)
    light = shot["light"] if "lamp" in info or shot["light"] not in ("lamp", "flicker") else "moon"
    if light in ("lamp", "flicker") and st["power"] > 0.3:
        lx, ly = info["lamp"], info.get("lamp_y", CEILING + 90)
        _glow(E, lx, ly + 6, 300, (255, 226, 170), 0.7 * st["power"])
        d.ellipse([lx - 30, ly - 12, lx + 30, ly + 12], fill=(255, 238, 200, int(245 * st["power"])))
    if shot["light"] == "green" and "door" in info and st["door"] > 0.05 and not pts.get("them"):
        dx, dw, dh = info["door"], info["door_w"], info["door_h"]
        _glow(E, dx, FLOOR - dh * 0.5, dh * 1.5, (90, 255, 140), 0.55 * st["door"])
    eyes_on = st["eyes"]
    for h in pts.get("them", []):
        col = EYES.get(them["raw"].get("eyes", "red" if h["kind"] in ("shadow", "crowd") else "none"))
        if col is None or eyes_on <= 0.02:
            continue
        hx, hy = h["head"]
        r = 6.5 * h["scale"]
        for ex in (hx + h["face"] * 8 * h["scale"], hx + h["face"] * 30 * h["scale"]):
            _glow(E, ex, hy - 4, 74 * h["scale"], col, 0.85 * eyes_on)
            d.ellipse([ex - r, hy - 4 - r, ex + r, hy - 4 + r], fill=col + (int(255 * eyes_on),))
    if shot["event"] == "eyes" and them is None and st["target"]:
        tx = info[st["target"]]
        ty = (FLOOR - 400) if st["target"] == "door" else info.get("window_y", 700) - 20
        for j, (ox, oy, sc) in enumerate(((0, 0, 1.0), (-46, 70, 0.7), (52, 110, 0.8))):
            k = smooth(span(u, st["te"] + j * 0.22, st["te"] + j * 0.22 + 0.3))
            for ex in (tx + ox - 15 * sc, tx + ox + 15 * sc):
                _glow(E, ex, ty + oy, 70 * sc, (255, 70, 60), 0.9 * k)
                d.ellipse([ex - 6 * sc, ty + oy - 6 * sc, ex + 6 * sc, ty + oy + 6 * sc], fill=(255, 90, 76, int(255 * k)))
    if st["impact"] is not None and st["target"]:
        tx = info[st["target"]]
        ty = (FLOOR - 330) if st["target"] == "door" else info.get("window_y", 700)
        k = st["impact"]
        for ang in (-50, -18, 18, 50, 130, 162, 198, 230):
            a = math.radians(ang)
            r0, r1 = 70 + 60 * k, 110 + 90 * k
            d.line([(tx + math.cos(a) * r0, ty + math.sin(a) * r0), (tx + math.cos(a) * r1, ty + math.sin(a) * r1)],
                   fill=(255, 255, 255, int(230 * (1 - k))), width=7)
    p = pts.get("you")
    if p and (p.get("phone") or st["ring"] > 0):
        hx, hy = p["hand"]
        k = max(0.8 if p.get("phone") else 0.0, st["ring"])
        _glow(E, hx, hy, 170, (140, 216, 255), 0.75 * k)
        d.rounded_rectangle([hx - 13, hy - 24, hx + 13, hy + 24], 5, fill=(200, 236, 255, int(255 * clamp(k + 0.2))))
    if p and shot["light"] == "flashlight":
        hx, hy = p["hand"]
        _glow(E, hx + p["face"] * 16, hy, 90, (255, 246, 222), 0.9)
    if "iro" in pts:
        ix, iy = pts["iro"]
        _glow(E, ix, iy - 96, 440, (255, 190, 96), 0.42)
        pic_i = _iro_pic(190)
        E.alpha_composite(pic_i, (int(ix - pic_i.width / 2), int(iy - pic_i.height)))
    pic = pic.convert("RGBA")
    pic.alpha_composite(E)
    pic = pic.convert("RGB")

    # the camera
    k = clamp(u / dur) if dur > 0 else 1.0
    zoom = {"push": 1.10 + 0.08 * k, "pull": 1.18 - 0.08 * k}.get(shot["camera"], 1.12)
    zoom *= 1 + 0.014 * st["pulse"]
    sx = sy = 0.0
    if st["shake"] > 0:
        sx, sy = _noise(u * 2.3, 1.0) * 22 * st["shake"], _noise(u * 2.3, 2.0) * 16 * st["shake"]
    if zoom > 1.0005 or sx or sy:
        fx = lerp(W / 2, p["x"] if p else (them["x"] if them else W / 2), 0.7)
        fy = FLOOR - 200
        cw, ch = W / zoom, H / zoom
        x0 = clamp(fx - cw * (fx / W) + sx, 0, W - cw)
        y0 = clamp(fy - ch * (fy / H) + sy, 0, H - ch)
        pic = pic.resize((W, H), Image.Resampling.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch))
    return pic, st


# ---------------------------------------------------------------- words on top ----

def _say(word: str) -> str:
    """A word as it is shown: capitals, no commas or full stops."""
    return word.upper().strip(".,;:\"“”()").replace("—", "").replace("–", "")


def _tracked(d, x: float, y: float, words: str, font, fill, spacing: float, stroke: int = 0, stroke_fill=(0, 0, 0, 255)):
    """Text centred on x with its letters `spacing` pixels apart, its baseline at y."""
    widths = [d.textlength(ch, font=font) for ch in words]
    total = sum(widths) + spacing * (len(words) - 1)
    cx = x - total / 2
    for ch, wd in zip(words, widths):
        d.text((cx, y), ch, font=font, fill=fill, anchor="ls", stroke_width=stroke, stroke_fill=stroke_fill)
        cx += wd + spacing
    return total


def _fit(d, words: str, path: str, size: int, max_w: float, floor: int = 40):
    font = _font(path, size)
    while size > floor and d.textlength(words, font=font) > max_w:
        size -= 4
        font = _font(path, size)
    return font


def _captions(d, timing: dict, t: float):
    for g in timing["groups"]:
        if not g["start"] <= t < g["end"]:
            continue
        words = [timing["words"][k] for k in g["words"]]
        shown = [_say(w["say"]) for w in words]
        shown = [s for s in shown if s]
        if not shown:
            return
        line = " ".join(shown)
        font = _fit(d, line, CAPTION_FONT, 88, 980, 52)
        total = d.textlength(line, font=font)
        gap = d.textlength(" ", font=font)
        rise = 10 * (1 - smooth(span(t, g["start"], g["start"] + 0.09)))
        x = (W - total) / 2
        current = max((k for k, w in enumerate(words) if w["t"] <= t + 0.02), default=0)
        for k, s in enumerate(shown):
            fill = GOLD if k == current else (255, 255, 255)
            d.text((x, CAPTION_Y + rise), s, font=font, fill=fill + (255,), anchor="lm", stroke_width=9, stroke_fill=(4, 5, 10, 255))
            x += d.textlength(s, font=font) + gap
        return


def _pill(d, x: float, y: float, words: str, alpha: float, size: int = 38, gold: bool = False):
    font = _font(SMALL_FONT, size)
    widths = [d.textlength(ch, font=font) for ch in words]
    total = sum(widths) + 6 * (len(words) - 1)
    a = int(255 * clamp(alpha))
    d.rounded_rectangle([x - total / 2 - 30, y - size * 0.86, x + total / 2 + 30, y + size * 0.86], size * 0.86,
                        fill=(6, 8, 16, int(a * 0.78)), outline=(GOLD if gold else (255, 255, 255)) + (int(a * 0.55),), width=3)
    _tracked(d, x, y + size * 0.36, words, font, ((GOLD if gold else (255, 255, 255)) + (a,)), 6)


def _overlays(pic, ep: dict, timing: dict, t: float, i: int, end_tag: str):
    """Everything written on top of the picture: the vote, the part, the banner, the words, the choice."""
    from PIL import Image, ImageDraw
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    shot = ep["shots"][i]
    part = int(ep.get("part") or 1)
    voted = ep.get("voted")
    opener = 2.6 if voted else 2.0
    a = smooth(span(t, 0.05, 0.3)) * (1 - smooth(span(t, opener - 0.35, opener)))
    if a > 0.01:
        if voted:
            _pill(d, W / 2, BANNER_Y, f"PART {part}  ·  YOU VOTED", a, 36)
            font = _fit(d, voted, CAPTION_FONT, 170, 940, 80)
            pop = back_out(span(t, 0.12, 0.5))
            d.text((W / 2, BANNER_Y + 170 + 26 * (1 - pop)), voted, font=font, fill=GOLD + (int(255 * a),), anchor="mm",
                   stroke_width=12, stroke_fill=(4, 5, 10, int(255 * a)))
        else:
            _pill(d, W / 2, BANNER_Y, f"PART {part}", a, 38, gold=True)
    elif shot.get("banner") and t >= opener:
        s0 = timing["shots"][i]["start"]
        _pill(d, W / 2, BANNER_Y, shot["banner"], smooth(span(t, max(s0, opener), max(s0, opener) + 0.25)), 38)
    last = len(ep["shots"]) - 1
    said = timing["said_until"]
    if i == last and ep.get("a") and ep.get("b"):
        s0, s1 = timing["shots"][i]["start"], timing["shots"][i]["end"]
        t0 = s0 + min(0.9, (s1 - s0) * 0.2)
        k = back_out(span(t, t0, t0 + 0.4))
        if k > 0.01:
            alpha = clamp(span(t, t0, t0 + 0.2))
            y0 = 470 + 40 * (1 - k)
            beat = (t - t0) * 1.25
            for side, x0, x1, words in ((0, 70, 500, ep["a"]), (1, 580, 1010, ep["b"])):
                hot = 0.5 + 0.5 * math.sin(beat * math.pi * 2 + side * math.pi)
                edge = mix((150, 120, 50), GOLD, hot)
                d.rounded_rectangle([x0, y0, x1, y0 + 190], 34, fill=(8, 10, 20, int(232 * alpha)), outline=edge + (int(255 * alpha),), width=6)
                font = _fit(d, words, CAPTION_FONT, 96, x1 - x0 - 56, 44)
                d.text(((x0 + x1) / 2, y0 + 95), words, font=font, fill=(255, 255, 255, int(255 * alpha)), anchor="mm")
            d.ellipse([W / 2 - 46, y0 + 49, W / 2 + 46, y0 + 141], fill=(8, 10, 20, int(255 * alpha)), outline=GOLD + (int(255 * alpha),), width=4)
            d.text((W / 2, y0 + 95), "OR", font=_font(CAPTION_FONT, 40), fill=GOLD + (int(255 * alpha),), anchor="mm")
            _tracked(d, W / 2, y0 + 262, "COMMENT YOUR CHOICE", _font(SMALL_FONT, 40), (255, 255, 255, int(235 * alpha)), 7,
                     stroke=5, stroke_fill=(4, 5, 10, int(255 * alpha)))
    tag = str(end_tag or "").strip().upper()
    if tag and t >= said + 0.35:
        k = smooth(span(t, said + 0.35, said + 0.85))
        _tracked(d, W / 2, CAPTION_Y + 18 - 12 * (1 - k), tag, _font(SMALL_FONT, 56), GOLD + (int(255 * k),), 11,
                 stroke=6, stroke_fill=(4, 5, 10, int(255 * k)))
    else:
        _captions(d, timing, t)
    out = pic.convert("RGBA")
    out.alpha_composite(over)
    return out.convert("RGB")


def frame(raw: dict, t: float, timing: dict | None = None, end_tag: str = "SEARCH IRO AI"):
    """One frame of an episode at `t` seconds, as an RGB picture."""
    ep = clean_episode(raw)
    timing = timing or plan(ep)
    if not ep["shots"]:
        raise StepError("this episode has no shots")
    t = clamp(t, 0.0, max(0.0, timing["total"] - 1 / FPS))
    i = _shot_at(timing, t)
    s = timing["shots"][i]
    pic, _ = scene(ep["shots"][i], t - s["start"], s["end"] - s["start"])
    return _overlays(pic, ep, timing, t, i, end_tag)


# ------------------------------------------------------------------------ videos ----

def render(raw: dict, out: Path, timing: dict | None = None, audio: Path | None = None,
           end_tag: str = "SEARCH IRO AI", workers: int = 4, on_frame=None) -> Path:
    """Draw an episode and write it to `out`: H.264, with `audio` as its sound (the narrator and
    the sound bed) or a silent track when there is none. Several frames are drawn at once."""
    import media
    from concurrent.futures import ThreadPoolExecutor
    ep = clean_episode(raw)
    problems = check_episode(ep)
    if problems:
        raise StepError("this episode cannot be drawn: " + "; ".join(problems[:4]))
    timing = timing or plan(ep)
    media.require_ffmpeg()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.stem + ".part.mp4")
    total = int(round(timing["total"] * FPS))
    for name in {s["set"] for s in ep["shots"]}:          # drawn once here, not by eight threads at once
        build_set(name)
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
        return frame(ep, k / FPS, timing, end_tag).tobytes()

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
