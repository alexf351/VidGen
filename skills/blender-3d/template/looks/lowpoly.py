"""LOWPOLY: a bright faceted world. Every solid is triangulated and shaded flat, so each face
catches the sun at its own angle. A sun and a gradient sky, 50 mm, 'AgX - Punchy'.
Keep triangle counts low: shapes read through their silhouette and a few big faces."""
import math

import studio as S


def setup(ctx):
    S.FLAT = True
    S.look("AgX - Punchy", 0.0)
    S.sky(top="#3d7fd9", horizon="#ffd9b0", strength=1.0)


def rig(elevation=40, azimuth=35, strength=3.5):
    S.sun("sun", strength, elevation, azimuth, angle_deg=3.0)


def shot(distance=6.0, elevation=22, azimuth=-25, target=(0, 0, 0.5), lens=50):
    el, az = math.radians(elevation), math.radians(azimuth)
    loc = (target[0] + distance * math.sin(az) * math.cos(el), target[1] - distance * math.cos(az) * math.cos(el),
           target[2] + distance * math.sin(el))
    return S.camera(loc, target, lens=lens)
