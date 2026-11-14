"""cast.py: the characters and props that appear in more than one beat, built once here so
they are the same in every beat. Each builder takes S (studio) and returns its group, so a
scene can place, turn and animate the whole thing:

    import cast
    bot = cast.toy_robot(S, "bot", location=(0, 0, 0))
    S.key(bot, 0.0, rotation=(0, 0, -20)); S.key(bot, 1.5, rotation=(0, 0, 20))

Replace this starter with the cast of your story. Name every part after what it is.
"""
CM = 0.01


def toy_robot(S, name="robot", location=(0, 0, 0), rotation=(0, 0, 0), body="#e8692a", accent="#1f9aa0"):
    """A 45 cm tin toy robot standing at location (its feet on z = 0)."""
    root = S.group(name, location, rotation)
    paint = S.material(f"{name}_paint", body, roughness=0.32, coat=0.7, noise=0.08)
    teal = S.material(f"{name}_teal", accent, roughness=0.35, coat=0.4)
    chrome = S.material("chrome", "#eceff2", roughness=0.16, metallic=1.0)
    visor = S.material("visor", "#0b0d10", roughness=0.06, coat=1.0)
    glow = S.material("glow", "#35d6ff", emission="#35d6ff", emission_strength=3.2)
    S.box(f"{name}_torso", (15.5 * CM, 11 * CM, 16 * CM), (0, 0, 17 * CM), mat=paint, bevel=2.2 * CM, parent=root)
    S.box(f"{name}_head", (14.4 * CM, 12 * CM, 12 * CM), (0, 0, 33 * CM), mat=paint, bevel=2.0 * CM, parent=root)
    S.box(f"{name}_visor", (11 * CM, 1.2 * CM, 5 * CM), (0, -6 * CM, 34 * CM), mat=visor, bevel=0.5 * CM, parent=root)
    for side, x in (("L", -2.6), ("R", 2.6)):
        S.sphere(f"{name}_eye_{side}", 1.1 * CM, (x * CM, -6.7 * CM, 34 * CM), mat=glow, parent=root)
        S.cylinder(f"{name}_leg_{side}", 2.2 * CM, 9 * CM, (x * 1.4 * CM, 0, 4.5 * CM), mat=chrome, parent=root)
        S.box(f"{name}_foot_{side}", (5 * CM, 7 * CM, 2 * CM), (x * 1.4 * CM, -1 * CM, 1 * CM), mat=teal, bevel=0.8 * CM, parent=root)
        S.cylinder(f"{name}_arm_{side}", 1.8 * CM, 12 * CM, (x * 3.6 * CM, 0, 18 * CM), mat=chrome, parent=root)
    S.rod(f"{name}_antenna", (0, 0, 39 * CM), (0, 0, 45 * CM), 0.4 * CM, mat=chrome, parent=root)
    S.sphere(f"{name}_bulb", 1.2 * CM, (0, 0, 45.5 * CM), mat=glow, parent=root)
    S.torus(f"{name}_collar", 5 * CM, 0.9 * CM, (0, 0, 26 * CM), mat=teal, parent=root)
    return root
