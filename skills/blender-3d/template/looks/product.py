"""PRODUCT: a toy or object on a photo sweep, three-point studio light, long lens.
The robot recipe: 70 mm at f/4, key / fill / rim, world 0.1, 'AgX - Medium High Contrast' at -0.3.
Bevels and coat + roughness noise carry this look."""
import math

import studio as S


def setup(ctx):
    S.look("AgX - Medium High Contrast", -0.3)
    S.world("#20232a", 0.1)


def rig(height=0.45, target=None, backdrop="#d6cfc4", warm="#ffe7cf", cool="#cfe0ff"):
    """The sweep and three lights for a subject `height` metres tall standing at the origin.
    Key: warm, front left, above. Fill: a quarter of the key, cool, low right. Rim: behind and
    above, the brightest, drawing the edge that lifts the subject off the backdrop."""
    h = float(height)
    tz = target or (0, 0, h * 0.5)
    S.backdrop(width=h * 9, depth=h * 6, height=h * 5, radius=h * 1.2, color=backdrop, location=(0, h * 1.2, 0))
    k = (h / 0.45) ** 2
    S.area_light("key", 24 * k, 1.2 * h, (-1.4 * h, -2.2 * h, 2.0 * h), tz, warm)
    S.area_light("fill", 6 * k, 2.0 * h, (2.0 * h, -1.8 * h, 0.7 * h), tz, cool)
    S.area_light("rim", 40 * k, 0.7 * h, (0.6 * h, 1.8 * h, 2.4 * h), tz, "#ffffff")


def shot(height=0.45, lens=70, elevation=10, azimuth=-15, fill=0.62, target=None, fstop=4.0):
    """A camera that fits a subject `height` metres tall into `fill` of the frame's height.
    azimuth 0 = straight on from -Y; negative swings to the left."""
    h = float(height)
    tgt = target or (0, 0, h * 0.5)
    half = math.atan(18.0 / lens)                       # half the vertical view (the frame is 9:16)
    d = (h / fill) / 2 / math.tan(half)
    el, az = math.radians(elevation), math.radians(azimuth)
    loc = (tgt[0] + d * math.sin(az) * math.cos(el), tgt[1] - d * math.cos(az) * math.cos(el), tgt[2] + d * math.sin(el))
    return S.camera(loc, tgt, lens=lens, fstop=fstop, focus=tgt)
