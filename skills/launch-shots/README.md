# Launch shots: a menu of 124 shot recipes

The product launch format's shot menu. Each card in `shots/<category>/` is one technique: what it
is for, its motion core, a parameter table with timings, the traps, and the sound. Written in
Chinese; read them as they are.

| Folder | What |
|---|---|
| `shots/opening/` | first-second hooks |
| `shots/ui-entrance/` | how a screen, a card or a panel arrives |
| `shots/interaction/` | a cursor clicks, drags, types, and the UI answers |
| `shots/typography/` | words as the picture |
| `shots/transition/` | one scene becoming the next |
| `shots/camera/` | push-ins, pull-backs, whips |
| `shots/data/` | numbers, counters, charts |
| `shots/effects/` | light, blur, texture |
| `shots/rhythm/` | cutting to the music |
| `shots/outro/` | end cards and logo landings |
| `sequences/promo-energy-arc.md` | how the energy of a whole promo rises and lands |
| `aesthetic-rules.md`, `music-beat-sync.md` | the look rules and beat sync behind the cards |

The cards were written for Remotion (frames at 30 fps, `spring()`); here they are recipes: turn
frames into seconds (30 frames = 1 s) and build them with GSAP in HyperFrames. Never copy the
reference films they cite: the cards are techniques, re-implemented.

Source: Vincentwei1021, [video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft)
(commit 6700db2, November 2026), Apache License 2.0 (`LICENSE`): `references/shots`,
`references/sequences`, `aesthetic-rules.md` and `music-beat-sync.md`, copied unchanged. Its own
notes on where each technique was studied from are in `shots/ATTRIBUTION.md`.
