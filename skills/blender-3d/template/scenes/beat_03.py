"""Beat 3 (lowpoly): a small floating island, the robot on top."""
import math

import cast
import studio as S


def build(ctx):
    L = ctx.look
    L.rig()
    L.shot(distance=4.2, target=(0, 0, 0.1))
    rng = ctx.rng
    grass = S.material("grass", "#6cbf4a", roughness=0.8)
    rock = S.material("rock", "#8a6e55", roughness=0.9)
    n = 18
    rim = [(1.0 + 0.12 * math.sin(3 * a) + rng.uniform(-0.05, 0.05)) for a in (2 * math.pi * i / n for i in range(n))]
    top = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n), 0.0) for i, r in enumerate(rim)]
    verts = [(0, 0, 0.0)] + top + [(0, 0, -1.2)]
    faces = [(0, 1 + i, 1 + (i + 1) % n) for i in range(n)] + [(n + 1, 1 + (i + 1) % n, 1 + i) for i in range(n)]
    island = S.custom("island", verts, faces, mat=grass)
    island.data.materials.append(rock)
    for f in island.data.polygons:
        f.material_index = 1 if f.center.z < -0.01 else 0
    for i in range(6):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0.4, 0.8)
        S.cone(f"tree_{i:02d}", 0.12, 0.0, 0.4, (r * math.cos(a), r * math.sin(a), 0.2), mat=S.material("pine", "#2f7d4a"), segments=6)
    rex = cast.toy_robot(S, "rex", location=(0, -0.2, 0))
    S.bob(rex, 0.0, ctx.seconds, height=3 * S.CM)
