"""studio.py: everything that is the same in every Blender scene of this video.

Scene files (scenes/beat_NN.py) import it as S and describe only their model. Blender 5.2 LTS,
headless. Units are metres: write every size with CM = 0.01 ("14.4 * S.CM").

The stage decides how much is switched on, so one scene file serves all four passes:

    blockout   one clay material, no bevels, the fixed studio lights, no depth of field
    bevel      + bevels (clamped under half the part's thinnest side) and smooth shading
    material   + the scene's own materials
    final      + the scene's own lights, world, colour look and depth of field

Build with these helpers only (bpy.data and bmesh, never bpy.ops): box, cylinder, cone, sphere,
torus, plane, rod, custom, image_plane, backdrop, group; material; area_light, point_light, spot_light,
sun, world, sky; camera, aim; key, bob. beat.py calls begin() before the scene's build(ctx) and
finish() after it; census() and report() print the one REPORT line the loop reads.
"""

from __future__ import annotations

import json
import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

CM = 0.01
STAGES = ("blockout", "bevel", "material", "final")
STAGE = "final"
CTX = None                  # the beat being built (beat.py sets it)
FLAT = False                # low-poly look: triangulate and shade flat every solid
WARNINGS: list[str] = []
_PENDING_LIGHTS: list[tuple] = []
_WORLD = None               # ("color", ...) or ("sky", ...), applied in the final pass
_LOOK = {"look": "None", "exposure": 0.0}
_TARGET = Vector((0, 0, 0))
_MATS: dict[str, bpy.types.Material] = {}


def at_least(stage: str) -> bool:
    return STAGES.index(STAGE) >= STAGES.index(stage)


class Ctx:
    """The beat: index (1-based), line, style, seconds, fps, stage. frame(t) is the frame at t seconds."""

    def __init__(self, index, line, style, seconds, fps, stage, seed=7):
        self.index, self.line, self.style = index, line, style
        self.seconds, self.fps, self.stage = float(seconds), int(fps), stage
        self.frames = max(1, round(self.seconds * self.fps))
        self.rng = random.Random(seed * 1000 + index)

    def frame(self, t: float) -> int:
        return 1 + max(0, min(self.frames - 1, round(float(t) * self.fps)))


# ------------------------------------------------------------------ begin / end ----

def begin(ctx: Ctx) -> None:
    global STAGE, CTX, FLAT, _WORLD, _LOOK, _TARGET
    STAGE, CTX, FLAT = ctx.stage, ctx, False
    WARNINGS.clear()
    _PENDING_LIGHTS.clear()
    _MATS.clear()
    _WORLD, _LOOK, _TARGET = None, {"look": "None", "exposure": 0.0}, Vector((0, 0, 0))
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.lights, bpy.data.cameras,
                 bpy.data.materials, bpy.data.images, bpy.data.worlds):
        for item in list(coll):
            coll.remove(item)
    scene = bpy.context.scene
    scene.render.fps = ctx.fps
    scene.frame_start, scene.frame_end = 1, ctx.frames
    bpy.context.preferences.edit.keyframe_new_interpolation_type = "BEZIER"


def finish() -> None:
    """Lights, world and colour for this stage. Before the final pass the scene's own lights
    are not made: a fixed studio rig lights the clay, so form is the only thing judged."""
    scene = bpy.context.scene
    if scene.camera is None:
        raise RuntimeError("the scene made no camera: call S.camera(...)")
    vs = scene.view_settings
    vs.view_transform = "AgX"
    if at_least("final"):
        made = {}
        for kind, args in _PENDING_LIGHTS:
            if kind == "_noshadow":
                made[args[0]].data.use_shadow = False
            elif kind == "_cone":
                made[args[0]].data.spot_size = math.radians(args[1])
            else:
                made[args[0]] = _make_light(kind, *args)
        if _WORLD is None:
            _world_color("#1a1d24", 0.2)
        elif _WORLD[0] == "color":
            _world_color(*_WORLD[1:])
        else:
            _world_sky(*_WORLD[1:])
        vs.look = _LOOK["look"]
        vs.exposure = _LOOK["exposure"]
    else:
        _studio_rig()
        _world_color("#9a9a9a", 0.35)
        vs.look = "None"
        vs.exposure = 0.0


def _studio_rig() -> None:
    cam = bpy.context.scene.camera
    t = _TARGET
    d = max(0.5, (cam.matrix_world.translation - t).length)
    fwd = (t - cam.matrix_world.translation).normalized()
    right = fwd.cross(Vector((0, 0, 1)))
    right = right.normalized() if right.length > 1e-6 else Vector((1, 0, 0))
    up = Vector((0, 0, 1))
    scale = d * d
    _make_light("AREA", "studio_key", 40 * scale, 0.6 * d, t - fwd * d * 0.8 - right * d * 0.7 + up * d * 0.8, t, "#fff4e8")
    _make_light("AREA", "studio_fill", 12 * scale, 1.0 * d, t - fwd * d * 0.9 + right * d * 0.8 + up * d * 0.2, t, "#e8f0ff")
    _make_light("AREA", "studio_rim", 30 * scale, 0.4 * d, t + fwd * d * 0.8 + up * d * 0.9, t, "#ffffff")


# ------------------------------------------------------------------ colour ----

def rgb(color) -> tuple[float, float, float]:
    """'#ff8800' or (r, g, b) in 0-1 sRGB -> linear RGB, which is what Blender's inputs take."""
    if isinstance(color, str):
        h = color.lstrip("#")
        color = tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return tuple(lin(float(c)) for c in color[:3])


# ---------------------------------------------------------------- materials ----

def _clay() -> bpy.types.Material:
    return material("clay", "#bdb6ad", roughness=0.55, _force=True)


def material(name: str, color="#cccccc", roughness: float = 0.5, metallic: float = 0.0,
             coat: float = 0.0, emission=None, emission_strength: float = 0.0,
             transmission: float = 0.0, ior: float = 1.45, noise: float = 0.0,
             alpha: float = 1.0, _force: bool = False):
    """A Principled BSDF with the 4.0+ input names. noise: +/- that much roughness variation
    (0.05-0.1 kills the plastic look on big panels). Before the material pass every part is
    clay; the call still returns the material so the scene code is the same in every pass."""
    if not _force and not at_least("material"):
        return _MATS.get("clay") or _clay()
    if name in _MATS:
        return _MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes.get("Principled BSDF")
    p.inputs["Base Color"].default_value = (*rgb(color), 1.0)
    p.inputs["Roughness"].default_value = roughness
    p.inputs["Metallic"].default_value = metallic
    p.inputs["Coat Weight"].default_value = coat
    p.inputs["Transmission Weight"].default_value = transmission
    p.inputs["IOR"].default_value = ior
    p.inputs["Alpha"].default_value = alpha
    if emission is not None and emission_strength > 0:
        p.inputs["Emission Color"].default_value = (*rgb(emission), 1.0)
        p.inputs["Emission Strength"].default_value = emission_strength
    if noise > 0:
        tex = nt.nodes.new("ShaderNodeTexNoise")
        tex.inputs["Scale"].default_value = 140.0
        rng = nt.nodes.new("ShaderNodeMapRange")
        rng.inputs["To Min"].default_value = max(0.0, roughness - noise)
        rng.inputs["To Max"].default_value = min(1.0, roughness + noise)
        nt.links.new(tex.outputs["Fac"], rng.inputs["Value"])
        nt.links.new(rng.outputs["Result"], p.inputs["Roughness"])
    m.diffuse_color = (*rgb(color), 1.0)
    _MATS[name] = m
    return m


# ------------------------------------------------------------------- meshes ----

def _obj(name: str, bm: bmesh.types.BMesh, location, rotation, scale, mat, bevel, smooth,
         flat, parent, open_ok=False) -> bpy.types.Object:
    xs = [v.co for v in bm.verts]
    dims = [max(c[i] for c in xs) - min(c[i] for c in xs) for i in range(3)] if xs else [0, 0, 0]
    sc = scale if isinstance(scale, (tuple, list)) else (scale, scale, scale)
    dims = [abs(d * s) for d, s in zip(dims, sc)]
    flat = FLAT if flat is None else flat
    if flat:
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if name in bpy.data.objects:
        WARNINGS.append(f"two objects are called {name!r}; Blender renamed the second")
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = tuple(math.radians(a) for a in rotation)
    obj.scale = sc
    if parent is not None:
        obj.parent = parent
    if open_ok:
        obj["open_ok"] = True
    if flat:
        me.shade_flat()
    elif smooth and at_least("bevel"):
        me.shade_smooth()
        me.set_sharp_from_angle(angle=math.radians(30))
    if mat is not None:
        me.materials.append(mat if at_least("material") or getattr(mat, "name", "") == "clay" else _MATS.get("clay") or _clay())
    else:
        me.materials.append(_MATS.get("clay") or _clay())
    if bevel and at_least("bevel"):
        thin = min([d for d in dims if d > 1e-6] or [0])
        width = float(bevel)
        if thin and width >= thin / 2:
            width = thin * 0.45
            WARNINGS.append(f"{name}: bevel {float(bevel) / CM:.2f} cm is not under half its thinnest side "
                            f"({thin / CM:.2f} cm); clamped to {width / CM:.2f} cm")
        mod = obj.modifiers.new("Bevel", "BEVEL")
        mod.width = width
        mod.segments = 4 if width < 0.6 * CM else 6
        mod.limit_method = "ANGLE"
        mod.harden_normals = True
    return obj


def group(name, location=(0, 0, 0), rotation=(0, 0, 0), parent=None):
    """An empty that parts hang from (parent=it): move, turn or key the group and the whole
    character follows. Its children are placed relative to it."""
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_size = 0.1
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = tuple(math.radians(a) for a in rotation)
    if parent is not None:
        obj.parent = parent
    return obj


def box(name, size, location=(0, 0, 0), rotation=(0, 0, 0), scale=1.0, mat=None, bevel=0.0,
        smooth=True, flat=None, parent=None):
    """A box size=(x, y, z) metres, centred on location. rotation in degrees."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
    return _obj(name, bm, location, rotation, scale, mat, bevel, smooth, flat, parent)


def cylinder(name, radius, depth, location=(0, 0, 0), rotation=(0, 0, 0), scale=1.0, mat=None,
             bevel=0.0, segments=48, smooth=True, flat=None, parent=None):
    """Upright along Z, centred on location."""
    return cone(name, radius, radius, depth, location, rotation, scale, mat, bevel, segments, smooth, flat, parent)


def cone(name, radius_bottom, radius_top, depth, location=(0, 0, 0), rotation=(0, 0, 0), scale=1.0,
         mat=None, bevel=0.0, segments=48, smooth=True, flat=None, parent=None):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                          radius1=radius_bottom, radius2=max(radius_top, 1e-5), depth=depth)
    if radius_top <= 1e-5:
        # A point, not a tiny circle: merge the tip and drop the zero-area faces it leaves.
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-4)
        bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=bm.edges[:])
    return _obj(name, bm, location, rotation, scale, mat, bevel, smooth, flat, parent)


def sphere(name, radius, location=(0, 0, 0), rotation=(0, 0, 0), scale=1.0, mat=None,
           segments=48, rings=24, smooth=True, flat=None, parent=None):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=radius)
    return _obj(name, bm, location, rotation, scale, mat, 0.0, smooth, flat, parent)


def torus(name, major, minor, location=(0, 0, 0), rotation=(0, 0, 0), scale=1.0, mat=None,
          segments=48, sides=16, smooth=True, flat=None, parent=None):
    """A ring in the XY plane: major = radius to the tube's centre, minor = the tube's radius."""
    bm = bmesh.new()
    rings = []
    for i in range(segments):
        a = 2 * math.pi * i / segments
        ring = []
        for j in range(sides):
            b = 2 * math.pi * j / sides
            r = major + minor * math.cos(b)
            ring.append(bm.verts.new((r * math.cos(a), r * math.sin(a), minor * math.sin(b))))
        rings.append(ring)
    for i in range(segments):
        for j in range(sides):
            a, b = rings[i], rings[(i + 1) % segments]
            bm.faces.new((a[j], b[j], b[(j + 1) % sides], a[(j + 1) % sides]))
    bm.normal_update()
    return _obj(name, bm, location, rotation, scale, mat, 0.0, smooth, flat, parent)


def plane(name, size, location=(0, 0, 0), rotation=(0, 0, 0), mat=None, parent=None):
    """A flat rectangle size=(x, y), facing +Z. Open on purpose (the census allows it)."""
    bm = bmesh.new()
    vs = [bm.verts.new((sx * size[0] / 2, sy * size[1] / 2, 0)) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    bm.faces.new(vs)
    return _obj(name, bm, location, rotation, 1.0, mat, 0.0, False, False, parent, open_ok=True)


def rod(name, a, b, radius, mat=None, segments=16, parent=None):
    """A cylinder from point a to point b."""
    a, b = Vector(a), Vector(b)
    d = b - a
    obj = cylinder(name, radius, max(d.length, 1e-5), location=(a + b) / 2, mat=mat, segments=segments, parent=parent)
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d.normalized()) if d.length > 1e-6 else (1, 0, 0, 0)
    return obj


def custom(name, verts, faces, location=(0, 0, 0), rotation=(0, 0, 0), scale=1.0, mat=None,
           bevel=0.0, smooth=True, flat=None, parent=None, open_ok=False):
    """Any mesh: verts [(x, y, z)], faces [(i, j, k, ...)] wound counter-clockwise seen from
    outside. A closed solid unless open_ok."""
    bm = bmesh.new()
    vs = [bm.verts.new(v) for v in verts]
    for f in faces:
        bm.faces.new([vs[i] for i in f])
    bm.normal_update()
    return _obj(name, bm, location, rotation, scale, mat, bevel, smooth, flat, parent, open_ok=open_ok)


def image_plane(name, path, height, location=(0, 0, 0), rotation=(0, 0, 0), glow: float = 1.0, parent=None):
    """A picture (a phone screen, a poster) as a glowing rectangle `height` metres tall, its
    width from the picture. It shows in every pass, so the screen reads from the blockout on."""
    img = bpy.data.images.load(str(path), check_existing=True)
    w, h = img.size
    width = height * (w / h if h else 0.5)
    m = bpy.data.materials.new(name + "_image")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = glow
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(tex.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    obj = plane(name, (width, height), location, rotation, parent=parent)
    obj.data.materials.clear()
    obj.data.materials.append(m)
    return obj


def backdrop(name="backdrop", width=3.0, depth=2.0, height=1.6, radius=0.5, color="#d9d4cc",
             location=(0, 0, 0), roughness=0.6):
    """A photo sweep: a floor that curves up into a wall behind, so there is no horizon line.
    The floor's front edge is at y = -depth/2, the wall at y = +depth/2."""
    prof = []
    y0, y1 = -depth / 2, depth / 2 - radius
    for i in range(6):
        prof.append((y0 + (y1 - y0) * i / 5, 0.0))
    for i in range(1, 13):
        a = (math.pi / 2) * i / 12
        prof.append((y1 + radius * math.sin(a), radius - radius * math.cos(a)))
    prof.append((depth / 2, height))
    verts, faces = [], []
    for x in (-width / 2, width / 2):
        verts += [(x, y, z) for y, z in prof]
    n = len(prof)
    for i in range(n - 1):
        faces.append((i, i + 1, n + i + 1, n + i))
    obj = custom(name, verts, faces, location=location, mat=material(name, color, roughness=roughness),
                 smooth=True, flat=False, open_ok=True)
    return obj


# ------------------------------------------------------------------- lights ----

def _make_light(kind, name, power, size, location, target, color):
    data = bpy.data.lights.new(name, kind)
    data.energy = power
    data.color = rgb(color)
    if kind == "AREA":
        data.shape = "DISK"
        data.size = size
    elif kind in ("POINT", "SPOT"):
        data.shadow_soft_size = size
    elif kind == "SUN":
        data.angle = math.radians(size)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    if target is not None:
        _look(obj, Vector(target))
    return obj


def area_light(name, power, size, location, target, color="#ffffff"):
    """A soft panel light, `power` watts, `size` metres wide, aimed at target. Made in the final pass."""
    _PENDING_LIGHTS.append(("AREA", (name, power, size, Vector(location), Vector(target), color)))


def point_light(name, power, location, radius=0.05, color="#ffffff", shadows=True):
    """A bulb. shadows=False for a bulb inside a lamp shade, or it blocks its own light."""
    _PENDING_LIGHTS.append(("POINT", (name, power, radius, Vector(location), None, color)))
    if not shadows:
        _PENDING_LIGHTS.append(("_noshadow", (name,)))


def spot_light(name, power, location, target, cone_deg=45.0, radius=0.05, color="#ffffff"):
    _PENDING_LIGHTS.append(("SPOT", (name, power, radius, Vector(location), Vector(target), color)))
    _PENDING_LIGHTS.append(("_cone", (name, cone_deg)))


def sun(name, strength, elevation_deg, azimuth_deg, angle_deg=2.0, color="#fff1dc"):
    """Sunlight from elevation (degrees above the horizon) and azimuth (0 = from -Y, the camera side; 90 = from +X)."""
    el, az = math.radians(elevation_deg), math.radians(azimuth_deg)
    direction = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
    _PENDING_LIGHTS.append(("SUN", (name, strength, angle_deg, direction * 10, Vector((0, 0, 0)), color)))


def world(color="#1a1d24", strength=0.15):
    """A flat world colour (it lights the scene a little and shows behind it)."""
    global _WORLD
    _WORLD = ("color", color, strength)


def sky(top="#4f8fe0", horizon="#ffd7a8", strength=1.0):
    """A gradient sky from horizon (bottom of the frame) to top (top of the frame). It is
    mapped to what the camera sees, so the top of the picture is always `top`."""
    global _WORLD
    _WORLD = ("sky", top, horizon, strength)


def _world_color(color, strength):
    w = bpy.data.worlds.new("world")
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (*rgb(color), 1.0)
    bg.inputs["Strength"].default_value = strength
    bpy.context.scene.world = w


def _world_sky(top, horizon, strength):
    w = bpy.data.worlds.new("sky")
    w.use_nodes = True
    nt = w.node_tree
    bg = nt.nodes.get("Background")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*rgb(horizon), 1.0)
    ramp.color_ramp.elements[1].color = (*rgb(top), 1.0)
    nt.links.new(tc.outputs["Window"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Y"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = strength
    bpy.context.scene.world = w


def look(name="AgX - Medium High Contrast", exposure=0.0):
    """The colour look and exposure for the final pass. Names start with 'AgX - ' (or 'None')."""
    _LOOK["look"], _LOOK["exposure"] = name, exposure


# ------------------------------------------------------------------- camera ----

def _look(obj, target: Vector) -> None:
    d = target - obj.location
    if d.length > 1e-9:
        obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def camera(location, target, lens=50.0, ortho_scale=None, fstop=None, focus=None):
    """The camera at location, aimed at target. ortho_scale: an orthographic camera that many
    metres across. fstop + focus (a point or an object): depth of field, final pass only."""
    global _TARGET
    data = bpy.data.cameras.new("camera")
    data.lens = lens
    data.sensor_width = 36.0
    if ortho_scale:
        data.type = "ORTHO"
        data.ortho_scale = ortho_scale
    data.clip_start, data.clip_end = 0.01, 500.0
    obj = bpy.data.objects.new("camera", data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    _TARGET = Vector(target)
    _look(obj, _TARGET)
    bpy.context.scene.camera = obj
    if fstop and at_least("final"):
        data.dof.use_dof = True
        data.dof.aperture_fstop = fstop
        if isinstance(focus, bpy.types.Object):
            data.dof.focus_object = focus
        else:
            data.dof.focus_distance = ((Vector(focus) if focus is not None else _TARGET) - Vector(location)).length
    return obj


def aim(obj, t, location=None, target=None, ease="BEZIER"):
    """Key a camera (or anything) at t seconds: move it to location and point it at target."""
    if location is not None:
        obj.location = location
    if target is not None:
        _look(obj, Vector(target))
    key(obj, t, location=tuple(obj.location), rotation=tuple(math.degrees(a) for a in obj.rotation_euler), ease=ease)


# ---------------------------------------------------------------- animation ----

def key(obj, t, location=None, rotation=None, scale=None, ease="BEZIER"):
    """A keyframe at t seconds into the beat. rotation in degrees. ease: BEZIER (ease in and
    out), LINEAR or CONSTANT (a hard cut, for snaps)."""
    prefs = bpy.context.preferences.edit
    prefs.keyframe_new_interpolation_type = ease
    f = CTX.frame(t) if CTX else 1
    if location is not None:
        obj.location = location
        obj.keyframe_insert("location", frame=f)
    if rotation is not None:
        obj.rotation_mode = "XYZ"
        obj.rotation_euler = tuple(math.radians(a) for a in rotation)
        obj.keyframe_insert("rotation_euler", frame=f)
    if scale is not None:
        obj.scale = scale if isinstance(scale, (tuple, list)) else (scale,) * 3
        obj.keyframe_insert("scale", frame=f)
    prefs.keyframe_new_interpolation_type = "BEZIER"


def bob(obj, t0, t1, height=1 * CM, times=2):
    """A gentle up and down between t0 and t1 seconds: idle life for a character."""
    base = Vector(obj.location)
    steps = max(2, times * 2)
    for i in range(steps + 1):
        t = t0 + (t1 - t0) * i / steps
        key(obj, t, location=tuple(base + Vector((0, 0, height if i % 2 else 0))))


# ------------------------------------------------------------------- census ----

def census() -> dict:
    """Defects a render can't show, counted on the meshes as they render (modifiers applied)."""
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    out = {"objects": 0, "triangles": 0, "open_edges": 0, "nonmanifold_edges": 0, "flipped_edges": 0,
           "degenerate_faces": 0, "loose_verts": 0, "negative_volume": 0}
    where: dict[str, list[str]] = {}
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        out["objects"] += 1
        ev = obj.evaluated_get(deps)
        me = ev.to_mesh()
        bm = bmesh.new()
        bm.from_mesh(me)
        ev.to_mesh_clear()
        open_ok = bool(obj.get("open_ok"))
        n = {"open_edges": 0, "nonmanifold_edges": 0, "flipped_edges": 0, "degenerate_faces": 0,
             "loose_verts": 0, "negative_volume": 0}
        out["triangles"] += sum(len(f.verts) - 2 for f in bm.faces)
        for e in bm.edges:
            k = len(e.link_faces)
            if k == 1 and not open_ok:
                n["open_edges"] += 1
            elif k > 2:
                n["nonmanifold_edges"] += 1
            elif k == 2:
                l1, l2 = e.link_loops[0], e.link_loops[1]
                if l1.vert == l2.vert:
                    n["flipped_edges"] += 1
        n["degenerate_faces"] = sum(1 for f in bm.faces if f.calc_area() < 1e-10)
        n["loose_verts"] = sum(1 for v in bm.verts if not v.link_edges)
        if not open_ok and n["open_edges"] == 0 and bm.faces and bm.calc_volume(signed=True) < 0:
            n["negative_volume"] = 1
        bm.free()
        for k, v in n.items():
            out[k] += v
            if v:
                where.setdefault(k, []).append(obj.name)
    out["where"] = {k: v[:6] for k, v in where.items()}
    return out


def outside_frame() -> list[str]:
    """Objects that are entirely outside the camera's view at the current frame."""
    from bpy_extras.object_utils import world_to_camera_view
    scene, cam = bpy.context.scene, bpy.context.scene.camera
    bpy.context.view_layer.update()
    gone = []
    for obj in scene.objects:
        if obj.type != "MESH" or obj.get("open_ok"):
            continue
        pts = [world_to_camera_view(scene, cam, obj.matrix_world @ Vector(c)) for c in obj.bound_box]
        if all(p.x < 0 for p in pts) or all(p.x > 1 for p in pts) or all(p.y < 0 for p in pts) \
                or all(p.y > 1 for p in pts) or all(p.z < 0 for p in pts):
            gone.append(obj.name)
    return gone


def report(**extra) -> None:
    """The one line the loop reads."""
    data = {"stage": STAGE, **extra, "warnings": WARNINGS[:12]}
    print("REPORT " + json.dumps(data))
