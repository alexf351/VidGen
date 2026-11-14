"""DIORAMA: a cut-away room seen from above through an orthographic camera, lit by the
things in it (a desk lamp, string lights, a glowing screen, moonlight through a window).
The room recipe: ortho scale ~5.4 for a room, ~30 degrees down, 'AgX - Medium High Contrast'."""
import math

import studio as S


def setup(ctx):
    S.look("AgX - Medium High Contrast", 0.0)
    S.world("#0e1220", 0.06)


def rig(size=3.0, mood="night"):
    """A soft fill so the shadows keep detail; the room's own lamps do the rest.
    mood: night (dim cool fill) or day (a sun through the window side)."""
    s = float(size)
    if mood == "day":
        S.sun("sun", 3.0, 35, 60, color="#fff1dc")
        S.area_light("fill", 60 * s * s / 9, s, (-s, -s, s * 1.4), (0, 0, 0), "#dfe8ff")
    else:
        S.area_light("fill", 12 * s * s / 9, s, (-s, -s, s * 1.4), (0, 0, 0), "#9fb4ff")


def shot(width=5.4, down=30, around=-35, target=(0, 0, 0.6)):
    """An orthographic camera `width` metres across, looking `down` degrees, from `around`
    degrees off the front (-Y). In a 9:16 frame the height shown is width * 16 / 9."""
    el, az = math.radians(down), math.radians(around)
    d = 12.0
    loc = (target[0] + d * math.sin(az) * math.cos(el), target[1] - d * math.cos(az) * math.cos(el), target[2] + d * math.sin(el))
    return S.camera(loc, target, ortho_scale=width)
