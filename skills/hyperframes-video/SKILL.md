# HyperFrames video: a vertical film made of HTML scenes, one per beat

Every frame of the video is an HTML page with a paused GSAP timeline that HyperFrames seeks frame
by frame and records to MP4. You write one scene per beat; VidGen writes the page that mounts
them (`index.html`), puts the voice and the music under them, renders, and adds the captions.

HyperFrames' own instructions are in `hf-docs/` (version-matched to the installed CLI). Read
`hf-docs/hyperframes/SKILL.md` (the contract) and `hf-docs/hyperframes/references/format.md` first,
then the references the format's brief names. Ignore their advice about asking the person
questions, previewing in Studio, the desktop app, telemetry, `events`, `usage`, `feedback`,
rendering and installing: VidGen does those.

## The files

| File | What it is | Yours to edit |
|---|---|---|
| `story.json` | the beats: `style`, `seconds`, `line` | no |
| `timing.json` | each beat's id, start and length in the video, the voice's words in it, the music's beats | no (VidGen writes it) |
| `compositions/beat_NN.html` | one scene per beat | yes |
| `assets/theme.css` | the film's palette and type as CSS variables, shared by every scene | yes |
| `assets/` | `vendor/gsap.min.js`, `vendor/three/` (three.js), `lib/toon.js` (the toon look's toolkit), `screens/` (Iro's real app screens), `cast/` (the cast's pictures), `voice.mp3`, `music.mp3` | add files, never edit these |
| `index.html` | the root page that mounts the scenes | no (VidGen writes it) |
| `looks/<look>.md` | the format's look: palette, type, motion, what to avoid | no; read it |
| `examples/` | a worked example scene | no; read it |

## A scene

```html
<template>
  <style>
    #root { position: absolute; inset: 0; background: var(--ground); }
    #beat_03-title { position: absolute; left: 90px; right: 90px; top: 560px; font: 900 112px/1.02 var(--font-display); color: var(--ink); }
  </style>
  <div id="root" data-composition-id="beat_03" data-width="1080" data-height="1920">
    <h1 id="beat_03-title" class="clip" data-start="0" data-duration="2.4">Your path, built for you</h1>
  </div>
  <script>
    const tl = gsap.timeline({ paused: true });
    tl.fromTo("#beat_03-title", { y: 60, opacity: 0 }, { y: 0, opacity: 1, duration: 0.45, ease: "power3.out" }, 0.1);
    window.__timelines["beat_03"] = tl;
  </script>
</template>
```

- The scene's id, its root's `data-composition-id` and its timeline key are all `beat_NN`, the
  beat's number with two digits. A mismatch makes every render wait 45 seconds per scene.
- Times inside a scene start at 0 when the beat starts. The beat lasts exactly `seconds` from
  `timing.json` (the voice set it); land every animation before then. A clip's `data-duration`
  never runs past the beat.
- Prefix every id with the beat (`#beat_03-title`): all scenes share one page.
- `fromTo`, never `from`. Animate transforms and opacity, never `left`/`top`/`width`/`height`.
- No `Date.now()`, unseeded `Math.random()`, timers, network, `repeat: -1`. Everything visible is
  a function of timeline time.
- Pictures: `assets/screens/<name>.jpg`, `assets/cast/<name>.png` (no leading `/`).

## The frame: 1080 x 1920, for a phone

- Nothing that matters in the top 168 px or below 1330 px: the app draws its own buttons there.
- Every word and the product sit between 168 and 1330 px. When the video is narrated, keep the
  band from 1100 to 1300 px clear of your own text: VidGen's captions go there.
- Frame 0 is the thumbnail and the hook: something bold already on screen, never black.
- Type is big: nothing under 28 px, a headline 90 to 140 px, at most about 5 words a line.
- A new thing every 2 to 4 seconds; shots of 1 to 2 seconds.

## A canvas scene (3D, characters)

A look drawn on a `<canvas>` (the `toon` look) does not animate elements with GSAP: it draws the
whole frame from the beat's time. Copy the wiring block at the bottom of
`examples/compositions/toon_beat.html` exactly (it loads `assets/lib/toon.js`, registers a
`window.__hf.buildReady` promise so the render waits for the build, and redraws on every seek), set
its `ID` and `DUR`, and write `build(T, canvas)`: make the scene once, return `draw(t)`.

## Look at your work

```
npx hyperframes check --json          the gate: lint, runtime, layout, contrast. Fix every error.
npx hyperframes snapshot --at 1.2,4.8 pictures at those seconds of the whole video (timing.json has each beat's start)
npx hyperframes timeline --json       what plays when
npx hyperframes catalog --json        ready-made blocks (transitions, kinetic type, charts); `npx hyperframes add <name>` installs one
```

Snapshots land in `.hyperframes/artifacts/snapshots/<run>/frame-*.png` with a `contact-sheet.jpg`:
**read them**. Check the middle and the end of every beat, and every transition. Type exactly
these commands; nothing else may run.

## Motion

`skill/motion-rules/` holds the motion rules every Claude Code format follows (timing, easing,
choreography, the twelve principles, the taste checks). Read them before the first scene, and
check your snapshots against their self-check list.

## Sound

The voice (`assets/voice.mp3`) and the music (`assets/music.mp3`) are mounted by VidGen; do not
add them. `timing.json` has the music's beat times (`music.beats`, in seconds of the whole video):
land cuts and hits on them. You may add short sound effects of your own only as files you make
(never downloaded), each an `<audio>` with an `id` inside its scene.
