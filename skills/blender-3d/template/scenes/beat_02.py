"""Beat 2 (diorama): a corner of a room at night, a desk, a lamp, the robot beside it."""
import cast
import studio as S

CM = S.CM


def build(ctx):
    L = ctx.look
    L.rig(size=3.0)
    L.shot(width=3.2, target=(0, 0, 0.5))
    wood = S.material("floor", "#6b4a33", roughness=0.55, noise=0.06)
    wall = S.material("wall", "#2c3550", roughness=0.8)
    for i in range(11):
        S.box(f"plank_{i:02d}", (25 * CM, 3.0, 4 * CM), (-1.25 + i * 25.2 * CM, 0, -2 * CM), mat=wood, bevel=0.6 * CM)
    S.box("wall_back", (2.9, 12 * CM, 2.2), (0, 1.56, 1.1), mat=wall)
    S.box("wall_right", (12 * CM, 3.0, 2.2), (1.44, 0.06, 1.1), mat=wall)
    desk = S.material("desk", "#8a6a4a", roughness=0.45)
    S.box("desk_top", (1.2, 0.6, 4 * CM), (0.2, 1.1, 0.74), mat=desk, bevel=0.8 * CM)
    for i, (x, y) in enumerate(((-0.35, 0.85), (0.75, 0.85), (-0.35, 1.35), (0.75, 1.35))):
        S.box(f"desk_leg_{i}", (5 * CM, 5 * CM, 72 * CM), (x, y, 0.36), mat=desk)
    shade = S.material("lamp_shade", "#e9c46a", roughness=0.4)
    S.cone("lamp_shade", 9 * CM, 3 * CM, 12 * CM, (0.55, 1.15, 1.05), rotation=(180, 0, 0), mat=shade, segments=32)
    S.rod("lamp_arm", (0.55, 1.2, 0.76), (0.55, 1.15, 1.1), 0.8 * CM, mat=shade)
    S.point_light("lamp_bulb", 25, (0.55, 1.15, 1.0), radius=2 * CM, color="#ffd29a", shadows=False)
    rex = cast.toy_robot(S, "rex", location=(0.0, 1.05, 0.76))
    S.key(rex, 0.0, location=(-0.1, 1.05, 0.76))
    S.key(rex, ctx.seconds, location=(0.05, 1.05, 0.76))
