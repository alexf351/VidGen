# VidGen

A Python CLI that turns a one-line story premise into a finished 9:16 animated short.
Each pipeline step writes its output to `runs/<run_id>/`, so any step can be re-run on its
own without redoing the others.

**Status:** all five steps are built. `python main.py new "<premise>"` runs script, images,
video, voice and assemble in order and leaves `runs/<run_id>/final.mp4`.

## Setup

Requires Python 3.11.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in the keys
```

`.env` holds `ANTHROPIC_API_KEY`, `FAL_KEY` and `ELEVENLABS_API_KEY`. It is loaded with
python-dotenv and ignored by git. The script step needs the Anthropic key, images and video
need the fal key (or `SUME_API_KEY` when Sume is selected, see below), and voice needs the
ElevenLabs key. Assembly needs `ffmpeg` and `ffprobe`
on your PATH.

## Usage

```bash
# create a run and execute every step in order
python main.py new "A laid-off line cook opens a food truck and nobody shows up on day one"

# re-run a single step on an existing run
python main.py step 20261103-201530-a-laid-off-line-cook script

# regenerate only specific shots (images, video or voice)
python main.py step 20261103-201530-a-laid-off-line-cook images --only 3,7

# regenerate one shot's image + video
python main.py reroll 20261103-201530-a-laid-off-line-cook 7

# after editing locked_characters in config.yaml: update an existing run's script.json,
# drop the stale reference sheets, and print the images --only command to regenerate
python main.py recast 20261103-201530-a-laid-off-line-cook
```

Every step skips shots whose output file already exists. `--only` and `reroll` override that
for the shots they name.

Step names, in pipeline order: `script`, `images`, `video`, `voice`, `assemble`.

## Run layout

```
runs/<run_id>/
  premise.txt           the premise as given
  run.json              run metadata
  script.json           output of the script step
  characters/<id>.png   reference sheet per character
  shots/<n>.png         keyframe per shot
  shots/<n>.mp4         clip, only for shots with animate: true
  audio/<n>.mp3         voice-over per spoken shot
  audio/<n>.json        per-word timings for that clip
  build/                intermediate clips, captions.ass, the pre-outro mix
  final.mp4             the finished short
characters_cache/<id>.png   generated sheets for locked characters, reused by every run
```

`<run_id>` is a timestamp plus a slug of the premise.

## Configuration (`config.yaml`)

| key                  | purpose                                                       |
|----------------------|---------------------------------------------------------------|
| `style`              | style line prepended word-for-word to every `image_prompt`     |
| `voice_id`           | default ElevenLabs voice                                       |
| `music_path`         | background music file                                          |
| `outro_path`         | clip appended after the last shot                              |
| `max_animated_shots` | cap on shots marked `animate: true` (default 8)                |
| `locked_characters`  | recurring cast: `id`, `role`, `description`, `image_path`      |
| `script.model`       | Claude model for the script step (`claude-sonnet-5-5`)         |
| `script.max_tokens`  | output cap for the script request                              |
| `characters_cache_dir` | where generated locked-character sheets are cached           |
| `fal.image_model`    | text-to-image endpoint (`fal-ai/nano-banana`)                  |
| `fal.image_edit_model` | reference-image endpoint (`fal-ai/nano-banana/edit`)         |
| `fal.video_model`    | image-to-video endpoint (`bytedance/seedance-2.0/fast/image-to-video`) |
| `fal.video_seconds` / `fal.video_resolution` / `fal.video_audio` | clip length (4), size (480p or 720p, default 480p), audio (off) |
| `fal.image_cost` | USD per image for the printed estimates |
| `fal.video_cost_per_second` | USD per second of video, keyed by resolution; the active one is used |
| `providers.images` / `providers.video` | `fal` (default) or `sume`, chosen separately |
| `sume.*`             | Sume models, settings, prices, `max_concurrent` and retry/poll limits |
| `voices`             | speaker id to ElevenLabs voice id; empty entries fall back to `voice_id` |
| `elevenlabs.model_id` / `output_format` / `cost_per_1k_chars` | TTS model, audio format, rate for the estimate |
| `music_path`         | music bed under the whole cut; empty = none (add it on-platform) |
| `outro_path`         | clip appended after the last shot; empty = none |
| `assemble.*`         | output size and fps, shot timing, caption font and size, music volume, saturation |

## The script step

`steps/script.py` sends the premise to the Claude Messages API with a system prompt that
demands JSON only. The response is stripped of any code fences, parsed and validated against
this schema:

```json
{
  "characters": [{"id": "marcus", "description": "one locked sentence, reused word for word"}],
  "shots": [{
    "n": 1,
    "characters": ["marcus"],
    "image_prompt": "<style line>, <scene>",
    "motion_prompt": "...",
    "vo_line": "...",
    "speaker": "narrator | <character id>",
    "caption": "1-2 WORDS IN CAPS or empty",
    "animate": true
  }]
}
```

### Story formula

Every script follows the same 10 beats in order: loss + diss (with a quoted insult),
rock bottom, mentor (Iro appears and the hero opens the Iro AI app), the bet, grind with a
climbing counter (streak days and Bronze/Silver/Gold/Diamond rank, at least one failure first),
overshoot win, flex, the ex returns, reversal ("i'm good", Iro says "that's my boy"), and a
closing CTA shot of the app with the caption `SEARCH IRO AI`.

The hero (marcus), love interest (jess), rival (tyler), mentor (iro), boss and new partner
(sofia) come from `locked_characters` in `config.yaml` and are reused by id with their
descriptions copied word for word. Iro's reference image is `assets/iro.png`, the gold mascot
from the Kiro app; `assets/app_icon.png` is the app icon for the CTA shot. Descriptions are physical identity
only; each image prompt adds a scene-fitting outfit (work clothes in setbacks, upgraded clothes in
wins). Jess leaves Marcus for Tyler in beat 1, and the insult comes from her or Tyler, never the
boss. Iro is always the penguin mascot.
New characters are only invented for minor roles. Setbacks are cold office light, wins are
golden hour. A real AI tool (Claude or ChatGPT) is named at least once.

### Validation

Rules enforced by the prompt and checked by the validator:

- 15 to 22 shots, numbered from 1 with no gaps
- every locked character is present and its description matches config exactly
- there is no narrator: every `vo_line` is dialogue spoken by a cast member (marcus, jess,
  tyler, boss, sofia, iro), `speaker` names who says it, and silent shots have an empty
  `vo_line` and `speaker`; a `narrator` speaker fails validation
- total `vo_line` words across the script is 60 to 100, and most shots are silent
- 1 to 3 time-jump card shots (optional `"card": "6 MONTHS LATER"` field) at the natural jumps
  in time; a card shot has no characters, no `vo_line`, `animate: false`, and is never the
  first or last shot. Shots without a `card` field work exactly as before
- the last shot's caption is exactly `SEARCH IRO AI`
- the style line opens every `image_prompt` (prepended if the model forgets)
- no more than `max_animated_shots` shots are `animate: true`, reserved for shots where motion is the beat
- `speaker` is `narrator` or a known character id; captions are at most two words (except the CTA)

If the JSON is invalid or fails validation, the errors are sent back to the model and it gets
one retry. The result is saved to `runs/<run_id>/script.json` and printed as a shot table.

## The images step

`steps/images.py` first makes sure every character in `script.json` has a reference sheet at
`runs/<run_id>/characters/<id>.png`. The source is, in order: the `image_path` set in
`locked_characters`, a cached sheet in `characters_cache/`, a sheet already in the run, or a
freshly generated sheet (front, three-quarter and side view on a plain light grey background).
New sheets for locked characters are copied into `characters_cache/` for later runs.

Then it generates one 9:16 keyframe per shot at `runs/<run_id>/shots/<n>.png`. Shots with
characters go through the edit endpoint with those characters' sheets attached as references
and a note telling the model which reference is which. Shots with no characters use plain
text-to-image. A running cost estimate is printed at the end.

## The video step

`steps/video.py` turns each `animate: true` keyframe into a 4 second, silent 9:16 clip at
`fal.video_resolution` (480p by default; assembly upscales to 1080x1920 either way)
at `runs/<run_id>/shots/<n>.mp4` using the shot's `motion_prompt`. It prints the estimated cost
per shot (seconds × the per-second rate for the configured resolution) with a running total, and
a total at the end. fal publishes the 720p rate ($0.2419/s); the 480p rate ($0.1125/s) is derived
from fal's token formula, as explained in `config.yaml`.

## The voice step

`steps/voice.py` makes one ElevenLabs text-to-speech call per spoken shot through the
`with-timestamps` endpoint and writes `audio/<n>.mp3` plus `audio/<n>.json`, which holds the
clip's per-word start and end times grouped from the character alignment. The speaker is mapped
to a voice through `voices` in config, falling back to `voice_id`. Silent shots are skipped, and
existing clips are skipped unless named with `--only`.

## The assemble step

`steps/assemble.py` drives ffmpeg through subprocess and prints a clear error if ffmpeg or
ffprobe is missing.

- Each shot lasts its voice-over length plus 0.25 s, with a 1.2 s minimum.
- Animated shots are trimmed to that length (the last frame is held if the clip is shorter).
  Still shots get a slow push-in from 1.00 to 1.08 on the keyframe.
- Every shot is scaled and cropped to fill 1080x1920 with no black bars, then all shots are
  concatenated and the voice-over clips are placed at their shot start times.
- Captions come from a generated `.ass` file and are burned in. Every spoken word is shown,
  1-2 words at a time in all caps, built from the word timings in `audio/<n>.json`: a chunk
  never holds more than two words and always breaks after punctuation, appears when its first
  word starts and stays until the next chunk starts (the last one until the shot ends). Each
  chunk pops in from 85% to 100% scale over 80 ms. Commas and periods are dropped from the
  display; `!` and `?` are kept. Silent shots show the shot's `caption` field for the whole
  shot instead. Bold italic white text with a soft pink-white glow, centred at 55% height, 90 px. Montserrat
  Black Italic is used when installed, otherwise Arial Black, otherwise a substituted sans with
  a printed warning.
- Time-jump card shots are 1.5 s of black (`assemble.card_seconds`) with the card text centred
  in the caption style, fading in and out over 200 ms (`assemble.card_fade_ms`), with no zoom
  or pop. The images, video and voice steps make nothing for card shots.
- A light grade is applied to the whole cut: saturation 0.85 and a slight cool tint.
- A music bed is mixed under the cut only when `music_path` is set, and the outro is appended
  only when `outro_path` is set. The result is `runs/<run_id>/final.mp4`, H.264 + AAC at 30 fps,
  and the step ends with an estimated cost breakdown for images, video and voice.

## Providers: fal or Sume

Images and video can each run on [fal.ai](https://fal.ai) (the default) or on
[Sume](https://sume.com/docs). Switch them independently in `config.yaml`:

```yaml
providers:
  images: sume
  video: sume
```

Sume runs the same models: `nano-banana` for sheets and keyframes (one model id covers
text-to-image and reference-image edits) and `seedance-2-fast` for clips, with the video
settings in the `sume` block (4 s, 480p or 720p, 9:16, no audio). Its prices are Sume's
published rates: $0.039 per image, $0.056246/s at 480p and $0.12096/s at 720p. The step
estimates and the final cost report use the rates of whichever provider made each kind.

Sume caps how many jobs a workspace has in flight (queued and running both count), and
refuses requests over the cap without charging them. VidGen runs up to `sume.max_concurrent`
jobs at once (default 2, Sume's cap for a workspace with no funds added in the last 28 days)
and resends a refused request with the same `Idempotency-Key` after a backoff, for up to
`sume.retry_window_seconds`. A shared reference sheet is uploaded once per run. If one shot
fails, the others still finish and are saved before the step reports the error. With fal,
requests stay one at a time exactly as before.
