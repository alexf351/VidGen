# Blender 3D: a narrated video made of Blender scenes, one per beat

Every frame of the video comes out of Python that Blender 5.2 runs headless. You write that
Python; VidGen adds the voice, renders every frame and puts the captions on.

The work goes in four passes over the whole video, the order a 3D artist follows: shape, then
edges, then materials, then light. One-shot scripts do all four at once and finish none of them.

## The files

| File | What it is | Yours to edit |
|---|---|---|
| `story.json` | the beats: `style` (the look), `seconds`, `line` | no (the story step wrote it) |
| `scenes/beat_NN.py` | one scene per beat: `def build(ctx):` builds it | yes |
| `cast.py` | characters and props that appear in more than one beat | yes |
| `looks/<look>.py` | the look's rig and camera (`ctx.look.rig(...)`, `ctx.look.shot(...)`) | only if a look needs a new helper |
| `studio.py` | the toolkit every scene uses (`import studio as S`) | no |
| `beat.py`, `preview.py` | how Blender builds and renders a beat | no |
| `refs/` | pictures of the cast (`refs/iro.png`) and Iro's app screens (`refs/screens/`) | no |

A scene file:

```python
"""Beat 4 (product): Rex drops the wrench and the bolt rolls away."""
import cast
import studio as S

CM = S.CM


def build(ctx):                     # ctx.index, ctx.line, ctx.seconds, ctx.fps, ctx.rng, ctx.look
    L = ctx.look
    L.rig(height=45 * CM)           # the look's lights (and backdrop)
    cam = L.shot(height=45 * CM)    # the look's camera, framed for that size
    rex = cast.toy_robot(S, "rex")
    bolt = S.cylinder("bolt", 1.2 * CM, 2 * CM, (6 * CM, -4 * CM, 1 * CM), mat=S.material("steel", "#c9ccd1", 0.3, metallic=1))
    S.key(bolt, 0.0, location=(6 * CM, -4 * CM, 1 * CM))
    S.key(bolt, ctx.seconds, location=(22 * CM, -9 * CM, 1 * CM), rotation=(90, 0, 720))
    S.aim(cam, 0.0)
    S.aim(cam, ctx.seconds, location=tuple(cam.location * 0.9))
```

## Look at your work

```
python preview.py 4 blockout          one beat, one pass, mid-beat
python preview.py 4 final --t 0.3     a moment inside the beat
python preview.py all bevel           every beat
```

It prints one REPORT line per beat and saves `stills/bNN_<pass>.jpg`. **Read every picture it
saves.** The REPORT has:

- `census`: defects a render can't show (open, non-manifold or flipped edges, zero-area faces,
  loose vertices, inside-out solids), with `where` naming the objects. **It must read zero before
  you judge the picture.** Most zero-area faces come from a bevel wider than the part allows.
- `outside_frame`: objects entirely out of the picture at that moment. Usually a mistake.
- `warnings`: bevels that were clamped, two objects with one name.

Then judge the picture for what a census can't count, for this pass only (below). At most five
fixes per look, each one concrete: part, what's wrong, which number, new value. Make them, preview
again. Two or three rounds per pass is normal.

## The four passes

The stage switches things on, so a scene file is the same in every pass:

1. **blockout**: every part in clay, no bevels, a fixed studio rig. Judge **silhouette,
   proportion, pose, framing**. Does each beat read in grey with the sound off? Is the subject
   big enough in a tall phone frame? Does the cast look the same in every beat?
2. **bevel**: bevels and smooth shading come on. Judge **edge highlights** and anything that
   looks pinched or melted. Give every hard part a `bevel=` width; the toolkit clamps a bevel
   wider than half the part's thinnest side and warns, but set it right yourself.
3. **material**: your `S.material(...)` colours and finishes come on. Judge **palette and
   plastic**. One main colour, an accent from the opposite side of the wheel, two or three
   neutrals. Roughness does as much as colour: paint 0.3 with `coat=0.7, noise=0.08`, chrome
   0.16 metallic, rubber 0.65, glass-like 0.06 with coat. One roughness on everything is the
   signature of cheap CG.
4. **final**: your lights, world, colour look and depth of field come on. Judge **light balance,
   exposure, framing, anything hidden or overlapping**. Check two moments per beat (`--t`):
   the start and the end of its movement.

## House rules

- `import studio as S` and build only with its helpers. Never `bpy.ops`.
- One unit is one metre. Write every size with `CM` (`14.4 * CM`). Bevel widths, light falloff
  and depth of field all depend on real size: a toy built 100 times too big needs other light.
- Name each object after the part it is: `visor`, `claw_R`, `book_07`. Names must be unique.
- Counted things come from loops, random things from `ctx.rng` (seeded per beat, so a rerun
  gives the same scene and "book 7 is too tall" means the same book next time).
- Pose limbs with joints: build an arm hanging straight down in its own group and rotate the
  group at the shoulder, then the elbow. Signs on rotations are where poses go wrong.
- Two faces in one plane flicker black (z-fighting): never let parts share a face plane; leave
  a millimetre between them or overlap them clearly.
- No text in the 3D scene: the captions are added on top later. A screen shows a real picture
  from `refs/screens/` with `S.image_plane(...)`, never invented UI.
- A glowing part that must keep its colour keeps its emission strength low (1 to 3); let the
  lights supply the brightness. AgX turns bright emitters white on purpose.

## Motion: every beat moves

`skill/motion-rules/README.md` holds the motion rules every video follows (easing, timing,
holds, one focal point); in Blender, BEZIER keys are the eased curves and LINEAR the steady ones.

A beat is `ctx.seconds` long (the voice sets it). Something happens inside every beat, keyed in
seconds with `S.key(obj, t, location=..., rotation=..., scale=...)`:

- The camera always moves a little: a slow push in, a drift sideways, a tilt (`S.aim`).
- One action per beat, big enough to see on a phone: a part drops, a character turns, a door
  opens, a thing pops in (`scale` from 0.01 to 1 with `ease="BEZIER"`), a light switches on.
- `S.bob(obj, t0, t1)` gives a standing character idle life.
- Keep motion simple and readable. A beat is two or three seconds; nobody sees a subtle move.
- `ease`: `BEZIER` eases in and out, `LINEAR` for steady travel, `CONSTANT` for a snap.

## The cast

Build every character that appears twice in `cast.py`, once, as a function that takes `S` and
returns its group. Each beat calls it, so the character is identical everywhere. Iro, the app's
mascot, is a small round robot penguin: glossy black and gold armour, big round eyes, a glowing
orange core on its chest. Look at `refs/iro.png` before you build it. It is never a human.

## Size and speed

The final render is 1080 x 1920 at 24 frames a second, every frame, usually on a graphics card.
Keep each beat under about 200,000 triangles: spheres 32 x 16 unless they fill the frame, loops
for repeated parts, no hidden detail. Previews are small and quick on purpose; trust them.

## Blender 5.2 traps (the toolkit handles these; know them if you write node code)

- Principled BSDF inputs have 4.0+ names: `Base Color`, `Coat Weight`, `Emission Color`,
  `Transmission Weight`, `Specular IOR Level`. `inputs['Emission']` is a KeyError.
- Colour looks start with `AgX - `: `'AgX - Medium High Contrast'`, `'AgX - Punchy'`.
- Smooth shading is `mesh.shade_smooth()` + `mesh.set_sharp_from_angle(...)`; auto smooth is gone.
- A Python error makes Blender exit with an error here, and preview.py prints the traceback.
