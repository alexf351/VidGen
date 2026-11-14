# TOON: flat cartoon people in a painted 3D town

The look of a cartoon story short: flat 2D characters with bean heads and stick limbs, outlined in
a dark plum ink, standing in a colourful 3D world drawn with thick black ink lines under a deep
blue sky. Every scene is one `<canvas>` drawn by `assets/lib/toon.js` (three.js underneath).

Start every scene from `examples/compositions/toon_beat.html`: copy its wiring block at the bottom
unchanged, set `ID` and `DUR`, and write your own `build()`. `build(T, canvas)` makes the world once
and returns `draw(t)`, which poses everything for `t` seconds into the beat and calls `S.render()`.
Read `assets/lib/toon.js` once: every helper has its options in the comment above it.

## The world

- One street town per film (same house seeds, colours and props in every beat), so the place is
  recognisable. `T.house` with `seed` gives the same house every time.
- Houses in muted painted colours (brick, cream, ochre, terracotta, sage, rose), never lemon or
  lavender. Trees, lamps and a parked thing or two make it lived in. Clouds high and few.
- `light: "day"` for most of the film; `"golden"` (low warm sun behind, peach sky) for an ending
  or a turn; `"night"` for a late-night scene with `lit: true` windows and `on: true` lamps.
- Nothing hides a face: before a camera move, check what stands between it and the cast.

## The cast

- `T.person(S, {...})` for every human, `T.iro(S, {...})` for Iro (a small robot penguin, never a
  human). Build each character once per scene with the same options in every beat: same skin,
  hair, hairColor, shirt, pants. Keep a cast table in `plan.md` and copy from it.
- One mood change per beat at most, and it goes through a take: anticipation, the new face, a
  settle. `mood` names: neutral, happy, sad, angry, shock, smug, worried, content.
- Feet on the ground (`hop` is the only exception), eyes on what they look at (`look: 1` faces
  right of frame, `-1` left). Characters talk (`talk: true`) only while their line is spoken:
  `timing.json` has each word's time.
- People stand 1.6 to 1.9 m; Iro 0.9 m, beside a person, on the ground, not floating.

## The camera

- Phone framing: the faces sit between 30 % and 60 % of the height. Keep the lens low (1.0 to
  1.6 m) and close (3 to 6 m from the cast); a high wide camera gives half a frame of road.
- Every beat moves: a slow push in, a drift sideways, a small roll (2 to 5 degrees). `cameraPath`
  creeps by itself on a hold, so nothing freezes. Hard cuts between beats are fine.
- `cam.shake(t, 0.05)` on an impact: it flips every frame and dies in 7 frames.
- One wide establishing shot early (the town, the cast small in it), the rest medium and close.

## Words

No text in the canvas: VidGen burns the captions on top (between 1100 and 1300 px). A phone's
screen is a real picture from `assets/screens/` via `await T.screen(S, { src, ... })`, never drawn UI.

## Checks

`npx hyperframes check` warns "Canvas content touches the frame edge" on every toon scene: the
canvas is full frame on purpose, and "GPU stall due to ReadPixels" when it renders in software:
ignore those two. Everything else gets fixed. Snapshot the
middle and the end of every beat and look for: a face cut by the frame or hidden, a character
floating or sunk into the road, a road filling half the frame, the same pose held still.
