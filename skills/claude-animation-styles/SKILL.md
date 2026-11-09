---
name: claude-animation-styles
description: Make animated story videos in 10 styles that do big numbers on Reels and TikTok: pixel art, PS2 style, comic art, lego style, claymation, paper cutout, retro anime, low poly 3D, risograph and miniature diorama. Claude writes the story, codes every scene, and renders an mp4 on the user's own computer, with no credits or image models. Use one style for a whole video or switch style every beat. Use when asked for an animated video, a story video, a video in any of these styles, "make it look like claymation / paper / pixel art", an animated ad for an app or SaaS, or when someone wants story copy for a video.
---

# Claude animation styles

Ten looks, each one a file of real code that Claude can point at any story. Nothing here calls an image or video model, so the same story renders the same way every time and costs nothing.

The template comes with a finished 22-second example: Claude flies a homemade rocket to the moon, in a new style every beat. Run it first to see every look moving, then replace the story.

## Styles

| File | Style | The look in one line |
|---|---|---|
| `pixel.js` | Pixel art | Drawn at about 120 pixels wide and scaled up with no smoothing. Small palette, dithered sky, game HUD |
| `ps2.js` | PS2 style | Few polygons, muddy little textures, fog, a low-res picture stretched up, mission HUD |
| `comic.js` | Comic art | Thick ink lines, flat color, Ben-Day dots, action lines, caption boxes, a big BOOM |
| `brick.js` | Lego style | Everything is plastic bricks with studs, under soft sun |
| `clay.js` | Claymation | Soft shapes with thumbprints, soft light, 12 poses a second |
| `paper.js` | Paper cutout | Layers of cut card with small shadows, paper fiber, 8 poses a second |
| `anime.js` | Retro anime | 80s cels: gradient sky, big sun disc, speed lines, an inverted frame on the hit, film grain |
| `poly.js` | Low poly 3D | Flat faces and hard light, nothing round |
| `riso.js` | Risograph | Two inks on off-white paper, each with its own halftone dots, printed slightly out of line |
| `mini.js` | Miniature diorama | A tiny handmade set on a desk, cardboard and cotton, tilt-shift blur |

`styles.md` has the rules for each one: what makes it read as that style, what to change for a new subject, and what breaks it. Read the part for a style before writing its scene.

## Steps

1. **Get the brief.** What's the story or the app, vertical (Reels, TikTok) or wide (X, YouTube), and which styles? No preference means 3 to 5 styles that suit the beats, or all 10 to show them off. One style for the whole video is fine too.
2. **Write the story** with `copywriter.md`. One line per beat. Show the user the lines with the style next to each, and wait for a yes.
3. **Copy the template:** `cp -r ~/.claude/skills/claude-animation-styles/template ~/my-video && cd ~/my-video && npm i`. Check it runs before changing anything: `node render.cjs stills 2,6,12` and open the pictures. They show the example story, so delete `stills/` before you start on yours.
4. **Write story.json.** `format` is `vertical` or `wide`. Each beat has a `style` (the file name), `seconds` and its `line`. The same style can be used for more than one beat, and each one gets its own scene (see below).
5. **Rewrite the scene in each style file you're using.** Keep the look, replace the subject. See "Changing the subject" below.
6. **Check stills** after every style: `node render.cjs stills 1,3.5,6`. The numbers are seconds into the whole video, not into the beat, and it prints the file name of each picture. Open each one. Is the subject recognizable with the sound off? Does it read as that style? Is anything cut off by the frame?
7. **Add a voice, if the user wants one:** `ELEVENLABS_API_KEY=... python3 voice.py [voice_id]`. It reads the lines, writes `voice.mp3` and retimes the beats in story.json to match. No key means no voice, so set the seconds by hand and add music.
8. **Render:** `node render.cjs video --audio voice.mp3`, or plain `node render.cjs video` for no sound. It writes `out/video.mp4`. A 20-second video takes a few minutes.
9. **Look at the whole thing** before handing it over: `ffmpeg -i out/video.mp4 -vf "fps=1,scale=240:-1,tile=8x4" -frames:v 1 out/sheet.jpg` (one picture a second, so empty cells at the end are normal). You can't hear it, so tell the user to check the sound.

To put music under a voice, 14 dB quieter than the voice:
`ffmpeg -i voice.mp3 -i music.mp3 -filter_complex "[1]volume=0.2[m];[0][m]amix=inputs=2:duration=first:normalize=0" audio.wav`
Measure both with `-af ebur128` and adjust the volume, since tracks differ a lot in loudness.

## Changing the subject

Each style file has one `create` that builds the world once, and one `render(t, ctx, dur)` that draws any moment, where `t` is seconds into the beat and `dur` is the length of the beat. It only ever looks at `t`, so any frame can be drawn in any order.

**A style used twice.** `create` gets `index` (the beat's position in story.json), `line` and `beat`. Save `this.index = index` and draw a different scene for each one. Don't test `start` for this, because it changes whenever the timing does.

**2D styles (pixel, comic, paper, anime, riso).** The subject is drawn through a little painter: `paint.fill(path, key)` and `paint.lines(segments, width, key)`, with each style deciding what those do. In comic they add ink lines. In paper they add a shadow. In riso they lay down ink density. `lib/common.js` has the example subjects, `drawClaude` and `drawRocket`. Write a `drawCat`, `drawPhone` or `drawFounder` the same way, using the same piece names in every style, and it picks up each look for free. A new piece name (`fur`, `apron`) has to be added to that style's palette, which is `PAL` in comic, paper and anime and `toneA` and `toneB` in riso, or it paints in the wrong color with no error. Pixel art plots its own sprite, so write that one by hand.

**3D styles (ps2, brick, clay, poly, mini).** `lib/three-claude.js` builds the subject out of simple shapes, with a `kit` deciding how many polygons and what material. Build your subject the same way: `makeCat(kit)`. The lego style is the exception, since everything has to be built from bricks, so copy its `add` helper.

**Keep the subject the same in every style.** Same silhouette, same two or three colors. That's what makes a style change read as the same story instead of a new clip. One simple recognizable shape beats a detailed character.

## What makes these work

- **Change the style on a hard cut.** Cut straight to the next look. The surprise of it is the transition.
- **One big thing moving in the middle.** People need to get each beat in under a second, often on a phone with the sound off.
- **Each beat 1.5 to 3 seconds.** Long enough to see the look, short enough that they stay for the next one.
- **Keep the story moving through the cut.** If the rocket is climbing at the end of one beat, it's still climbing at the start of the next.
- **Text belongs to the style.** A HUD in the game looks, a caption box in the comic look. Skip subtitles on top.

## If something goes wrong

- **Puppeteer or Three.js missing:** `npm i` in the folder with `render.cjs`.
- **ffmpeg missing:** `brew install ffmpeg` on a Mac. Stills work without it, the video needs it.
- **Black 3D frames or very slow renders:** the render uses the GPU on a Mac and a software renderer elsewhere (`render.cjs`, the `gl` line). Software rendering works and takes much longer.
- **Headlines in the wrong font:** the page loads Inter Tight and Bangers from Google Fonts, so it needs internet while rendering.
- **A word in the comic style lands late:** the countdown reads word times from `voice.json` when there's a voice. Change the words it looks for in `comic.js`.

## Keep it yours

Copy the looks, and make your own subjects. Don't use a brand's logo, a game's characters or a real company's set pieces on screen, and don't copy another creator's scene shot for shot.
