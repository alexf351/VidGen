# Motion rules

Every Claude Code format (three.js, Blender, HyperFrames) follows these. They are taste with
numbers: defaults you depart from on purpose, never by accident. `lottiefiles/` has the long form
(timing and easing tables, choreography, the twelve principles adapted for screens); read
`lottiefiles/SKILL.md` and `lottiefiles/reference/timing-easing-tables.md` once.

## 1. Every animation has a reason

Before any number: what should the viewer feel (urgency, calm, delight), what is the small story
of this move (setup, action, settle), and what makes it believable (weight, follow-through).
Motion that only decorates is noise.

## 2. Easing

| Moving | Curve | GSAP | Blender keys |
|---|---|---|---|
| Arriving: entrances, reveals | fast out of the gate, long gentle settle: `cubic-bezier(0.16, 1, 0.3, 1)` | `expo.out` or `power4.out` | BEZIER, the end handle long |
| Leaving: exits | starts slow, leaves fast: `cubic-bezier(0.6, 0, 0.9, 0.35)` | `power3.in` | BEZIER |
| Between two states: a morph, a flip, a dock | `cubic-bezier(0.65, 0, 0.35, 1)` | `power3.inOut` | BEZIER |
| A value that lands: a slider, a counter | a small overshoot | `back.out(1.4)` | a key past the target, then the target |
| Continuous: rotation, drift, grain | linear | `none` | LINEAR |

Linear on anything that starts or stops looks mechanical. Things that feel physical (a card, a
phone, a character) get springy overshoot; type and camera moves get smooth curves.

## 3. Timing

- A small UI move 0.2 to 0.35 s; a card or a phone 0.5 to 0.8 s; a camera move 0.6 to 1.2 s.
- **Exits take about half as long as entrances** (0.35 to 0.55 s against 0.7 to 1.25 s).
- **Stagger**: words about 0.09 s apart, list items or chips 0.2 to 0.25 s, dots 0.06 s. Never
  everything at once, never everything on the same duration.
- **Reading holds**: once something is readable, hold it at least 1 s for a short phrase, plus
  about 0.25 s per word beyond three, and 2 s for the last line. When in doubt, hold longer and
  animate less. Text never moves while it is meant to be read.
- **Overlap scenes**: the next scene starts arriving before the last one has fully left. A gap
  reads as loading.
- Typing: about 0.035 s per character.

## 4. Composition

- One focal point per frame. If two things compete, one of them waits its turn.
- One accent colour, and it means something: the thing that changed, the answer, the winner.
  If everything is the accent, nothing is.
- Nothing important within about 60 px of an edge (on a phone: see the format's frame rules).
- Frame 0 is the thumbnail: a real image, never black, never a logo alone.
- The phone test: shrink a frame to 360 px wide. The key message must still read.

## 5. Nothing is dead-still

- Idle things breathe: a slow drift of a few px a second, a gentle float, a blinking caret.
- A little texture: grain or a soft vignette at low strength.
- One hero moment per video (a big reveal, an impact). Build to it; don't spend it early.

## 6. Continuity

- Prefer one object that travels and changes role over a cut: the button becomes the menu, the
  card becomes the screen, the dot becomes the logo.
- Every transition has a cause on screen (something moves, opens, is clicked). No generic wipes.
- The same thing looks the same in every scene it appears in.

## 7. Check your own frames

You can't watch the video, but you can look at frames. After every change, look at stills from
the middle and the end of each beat and every transition, then go through this list:

- One focal point? Anything colliding or overlapping by mistake, especially mid-transition?
- Is anything clipped by the frame or a container when it shouldn't be?
- Is any text still moving in a frame where it should be held and readable?
- Does the key message read at phone width?
- Are exits faster than entrances? Does each scene overlap the next instead of cutting to empty?
- Is frame 0 a real picture?

Say what you checked and what you fixed. Never claim a fix you haven't looked at again.

## Sources

Adapted from two MIT-licensed projects:

- LottieFiles, [motion-design-skill](https://github.com/LottieFiles/motion-design-skill)
  (commit f9a8a04, May 2026): copied as is in `lottiefiles/`, with its `LICENSE`.
- whaleyxbt, [claude-motion](https://github.com/whaleyxbt/claude-motion) (commit 6f80380,
  November 2026): its motion-design and review-loop rules, rewritten here for every renderer;
  its licence is in `LICENSE-claude-motion`.
