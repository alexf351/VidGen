# LAUNCH: a premium product film for the Iro app

The feel of a Linear, Apple or Arc launch film: modern, fast, exact. The product is the hero and
everything that claims to be the product is the product (the screens and recordings in
assets/screens/).

## Palette: Iro's own

| Token | Value | Use |
|---|---|---|
| ground | `#0d1820` | the canvas, a deep ink |
| surface | `#13212b` | cards and the shape's dark states |
| ink | `#ffffff` | words |
| muted | `#8fa3b3` | small labels |
| accent | `#3ef0ff` | Iro's cyan: the one thing that changed, the click, the answer |
| gold | `#ffc94a` | XP, ranks and rewards, nothing else |

No glows on UI chrome, no gradients on buttons, no particle bursts. Light lives in one soft pool
of cyan behind the hero at most.

## Type

Montserrat 800-900 for headlines (96-140 px, tracking -0.02em, line height 1.0), Inter 500-700
for labels. One accent word per line in cyan. Never more than about 5 words on a line, never more
than one line of headline on screen with the product.

## Motion

- **One shape, never cut**: a rounded panel that becomes the phone screen, then a card, then a
  pill, then the end card. Its size, radius and colour morph; its content swaps with a short blur.
- **A cursor drives every change**: big (about 60 px), enters from off-screen, its click causes
  the next thing on the same frame (a press scale of 0.85 for 0.08 s and a ring).
- **The camera fills the frame**: push in so the state being shown fills it, pull back to show
  where it lives. Never a small phone in the middle of an empty canvas.
- **Springs with at most a small overshoot** (`back.out(1.2)` to `back.out(1.6)`), never bouncy.
- **Something happens on every beat of the music.** Cuts and hits land on `timing.json`'s
  `music.beats`; the biggest moment lands on the drop.
- **Numbers roll** like odometers (XP, a streak, minutes a day), using the app's real values.

## The shape of the film

hook (a bold claim or the result, already on screen at frame 0) -> the problem in one line ->
the app in hand -> three proof moments, each one real feature doing one thing -> the payoff ->
the end card: the app icon lands, "Iro AI" wipes in beside it, then "Search Iro AI". The end card
beat lasts at least 3 seconds, so "Search Iro AI" holds 2 seconds once it has landed.

## Tells to avoid

Typing into a prompt box as the opener. A feature list as three cards. A title over a dimmed
screenshot. Any invented button or screen. The logo docked in a corner. Dead frames.
