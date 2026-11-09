# VidGen

A Python CLI that turns a one-line story premise into a finished 9:16 animated short.
Each pipeline step writes its output to `runs/<run_id>/`, so any step can be re-run on its
own without redoing the others.

**Status:** all five steps are built. `python main.py new "<premise>"` runs script, images,
video, voice and assemble in order and leaves `runs/<run_id>/final.mp4`.

## Setup

Requires Python 3.11+ and ffmpeg (with libass, which every common build has).

macOS / Linux:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.local.example.yaml config.local.yaml   # then fill in your keys
python main.py doctor
```

Windows (PowerShell):

```powershell
winget install Python.Python.3.11
winget install Gyan.FFmpeg          # then open a NEW terminal so ffmpeg is on PATH
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
copy config.local.example.yaml config.local.yaml   # then fill in your keys
python main.py doctor
```

`python main.py doctor` checks ffmpeg and ffprobe (and that the build has libass and libx264),
the caption font, each API key, `assets/iro.png`, `assets/app_icon.png`, the app screenshots and
that the output folder is writable, and prints PASS / FAIL / SKIP per item. It makes no API calls.

On Windows, quote premises with single quotes in PowerShell if they contain `$` (inside double
quotes PowerShell replaces `$500` with an empty variable): `python main.py new 'He lost $500'`.

### Configuration layers

1. `config.yaml`: committed project settings (models, prices, providers, voices, music).
2. `formats/<name>/format.yaml`: the video format picked with `--format` (default
   `pixar_arc`): style line, cast, aspect, clip length, captions, grade, shot timing and
   the script rules. See [Video formats](#video-formats).
3. `config.local.yaml`: your machine. Not committed. Deep-merged over `config.yaml`, so it only
   needs the settings you change: API keys, `ffmpeg_path`, `default_video_provider`,
   `default_image_provider`, `output_dir`, or any other key. Start from
   `config.local.example.yaml`. Format settings can be overridden here too (for example
   `assemble: {caption_size: 80}`).
4. Environment variables win over all files: the API keys (`ANTHROPIC_API_KEY`, `FAL_KEY`,
   `ELEVENLABS_API_KEY`, `SUME_API_KEY`, also loaded from `.env`), and `VIDGEN_FFMPEG_PATH`,
   `VIDGEN_OUTPUT_DIR`, `VIDGEN_VIDEO_PROVIDER`, `VIDGEN_IMAGE_PROVIDER`.

Every command starts by printing which of these were loaded and where each key came from,
never the values. Nano Banana runs through fal or Sume, so it uses `FAL_KEY` or `SUME_API_KEY`;
there is no separate Gemini key.

Captions use the bundled `assets/fonts/Montserrat-BlackItalic.ttf` (SIL Open Font License,
`assets/fonts/OFL-Montserrat.txt`), loaded by libass directly, so nothing needs to be installed.

## Usage

```bash
# create a run and execute every step in order
python main.py new "A laid-off line cook opens a food truck and nobody shows up on day one"

# pick a video format (default pixar_arc); list the installed ones
python main.py new "A laid-off line cook opens a food truck" --format pixar_arc
python main.py formats

# script only: write and print the shot list, nothing sent to fal, Sume or ElevenLabs
# (it still calls Claude to write the script, a few cents)
python main.py new "A laid-off line cook opens a food truck" --dry-run

# re-run a single step on an existing run
python main.py step 20261103-201530-a-laid-off-line-cook script

# regenerate only specific shots (images, video or voice)
python main.py step 20261103-201530-a-laid-off-line-cook images --only 3,7

# regenerate one shot's image + video
python main.py reroll 20261103-201530-a-laid-off-line-cook 7

# after editing locked_characters in the format: update an existing run's script.json,
# drop the stale reference sheets, and print the images --only command to regenerate
python main.py recast 20261103-201530-a-laid-off-line-cook
```

Every step skips shots whose output file already exists. `--only` and `reroll` override that
for the shots they name.

Step names, in pipeline order: `script`, `images`, `video`, `voice`, `assemble`.

`step`, `reroll` and `recast` reuse the format the run was created with (saved in `run.json`);
runs made before formats existed use `pixar_arc`.

## Video formats

A format is a folder under `formats/` that holds everything specific to one kind of video. The
pipeline (steps, providers, ffmpeg) is shared; the format supplies the settings and the prompt
text.

```
formats/<name>/
  format.yaml        name, description, duration target, aspect + resolution, fps,
                     clip_seconds, cast (locked | none), beats, style line,
                     max_animated_shots, rules (shot counts, word budget, CTA caption,
                     cards, montage, app screens, banned image_prompt wording),
                     captions, grade, timing, app_screens, locked_characters
  script_prompt.md   system prompt for the script step
  shot_rules.md      image / video prompt rules, inserted at {{SHOT_RULES}}
  blocks/*.md        prompt pieces the script step picks between (app screens / none)
  examples/          optional example scripts
```

Prompt files are sent as written, with `{{NAME}}` placeholders filled from the format's
rules (`{{SHOT_MIN}}`, `{{CTA_CAPTION}}`, `{{STYLE}}`, `{{CAST}}`, ...); an unknown
placeholder is an error. `python main.py formats` lists what is installed.

`pixar_arc` is the original pipeline moved into this shape with nothing changed: the same
prompt bytes, validation, captions, grade and timing. To make a new format, copy
`formats/pixar_arc`, rename the folder and `name:`, and edit.

### Importing a Claude skill as a format

```bash
python main.py import-skill path/to/my-skill            # a folder with SKILL.md, or the SKILL.md itself
python main.py import-skill path/to/my-skill --name drama --premise "She finds a letter"
python main.py import-skill path/to/my-skill --force    # replace formats/<name> if it exists
python main.py import-skill path/to/my-skill --no-dry-run
```

1. Reads SKILL.md (frontmatter and body) and the files it references inside its folder (links,
   `backticked` paths, bare relative paths and folders, followed two levels deep). URLs and paths
   outside the folder are ignored; binary files are listed by name only.
2. One Claude call (`import_skill.model` in `config.yaml`, default `claude-opus-5-5`, with
   structured output) maps the skill onto the format schema, keeping the skill's wording in
   `script_prompt.md` and `shot_rules.md` and choosing example files. If the result does not fit
   the schema, the problems are sent back once for a corrected version. The importer appends
   VidGen's own output section (the JSON shot list the script step validates) to the prompt.
3. Writes `formats/<name>/` with `format.yaml`, the two prompts, `examples/`, and `source/`
   (the original SKILL.md and its referenced files). The name comes from `--name`, else the
   skill's `name`, else the folder. An existing format is never replaced without `--force`,
   and `pixar_arc` is never replaced.
4. Prints what was filled from the skill, what was guessed (`[?]`, including VidGen defaults
   kept and anything the importer adjusted), and what the skill wants that VidGen cannot do
   (`[x]`, for example another aspect ratio, music generation or on-screen graphics).
5. Validates `format.yaml` against the schema, loads the format the way the pipeline does,
   then runs `new --format <name> --dry-run` on a sample premise (one more Claude call) to
   confirm it produces a valid shot list. If that fails, the format is kept for you to edit.

Imported formats are always 9:16 (the image and video models are called at 9:16) and use no
app screenshots. A skill's `{{VARIABLES}}` that VidGen does not fill are written as `<VARIABLES>`.

## Local web UI and HTTP API

```bash
python main.py ui                 # http://127.0.0.1:8765/, opens your browser
python main.py ui --port 9000 --no-browser
```

A FastAPI server on **127.0.0.1 only** (it holds your API keys; nothing else on the network
can reach it). It calls the same functions as the CLI (`commands.py`), so runs made in the UI
and in the terminal are the same runs in the same output folder. `ui/` is served at `/`
(a placeholder page for now); interactive API docs are at `/api/docs`.

Commands run as **jobs**, one at a time on a background thread; the rest wait in a queue. Each
job has an id, the run it belongs to, an action (`new`, `step`, `reroll`, `recast`), a status
(`queued`, `running`, `done`, `failed`), start and finish times, and its log: everything the
pipeline prints while it runs. Job history is kept in `jobs.json` in the output folder; a job
that was running or queued when the server stopped is marked failed on the next start.

| endpoint | does |
|---|---|
| `GET /api/formats` | installed formats, descriptions, beats, cast |
| `GET /api/config` | default providers, available providers, which keys are set (never their values), locked cast |
| `GET /api/doctor` | the `doctor` checks as JSON |
| `POST /api/runs` `{premise, format, provider, dry_run}` | creates the run and queues `new`; returns `job_id` and `run_id` |
| `GET /api/runs` | every run: premise, format, created, status per step, final video, estimated cost |
| `GET /api/runs/{run_id}` | the script, per-shot image / clip / audio URLs and word timings, step status, cost rows |
| `POST /api/runs/{run_id}/step` `{step, only, provider}` | reruns one step (`only`: shot numbers, for images / video / voice) |
| `POST /api/runs/{run_id}/reroll` `{shot, provider}` | new image + clip for one shot |
| `POST /api/runs/{run_id}/recast` | recast |
| `PUT /api/runs/{run_id}/script` | saves an edited script.json after validating it with the run's format (422 with the errors otherwise; 409 while a job is working on that run) |
| `GET /api/jobs`, `GET /api/jobs/{id}?since=N` | job status and log (from line N) |
| `GET /api/jobs/{id}/stream` | Server-Sent Events: `log` events (one per line, `id` = line number, resumable with `Last-Event-ID`) and `status` events; ends when the job does |
| `GET /files/<run_id>/...` | images, clips, audio, captions, final.mp4 from the output folder (supports Range for video seeking) |

`provider` is `"fal"`, `"sume"` or `{"images": "...", "video": "..."}` and applies to that job
only; leave it out to use the configured providers. Writes must be JSON
(`content-type: application/json`), requests must use the `127.0.0.1` / `localhost` host name,
and requests from other web pages are refused, so a website you visit cannot drive the server.
`/files` only serves media and text files inside the output folder.

## Run layout

```
runs/<run_id>/
  premise.txt           the premise as given
  run.json              run metadata, including the format it was made with
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
| `voice_id`           | default ElevenLabs voice                                       |
| `script.model`       | Claude model for the script step (`claude-sonnet-5-5`)         |
| `script.max_tokens`  | output cap for the script request                              |
| `characters_cache_dir` | where generated locked-character sheets are cached           |
| `fal.image_model`    | text-to-image endpoint (`fal-ai/nano-banana`)                  |
| `fal.image_edit_model` | reference-image endpoint (`fal-ai/nano-banana/edit`)         |
| `fal.video_model`    | image-to-video endpoint (`bytedance/seedance-2.0/fast/image-to-video`) |
| `fal.video_resolution` / `fal.video_audio` | clip size (480p or 720p, default 480p), audio (off); clip length is the format's `clip_seconds` |
| `fal.image_cost` | USD per image for the printed estimates |
| `fal.video_cost_per_second` | USD per second of video, keyed by resolution; the active one is used |
| `providers.images` / `providers.video` | `fal` (default) or `sume`, chosen separately |
| `sume.*`             | Sume models, settings, prices, `max_concurrent` and retry/poll limits |
| `voices`             | speaker id to ElevenLabs voice id; empty entries fall back to `voice_id` |
| `elevenlabs.model_id` / `output_format` / `cost_per_1k_chars` | TTS model, audio format, rate for the estimate |
| `music_path`         | music bed under the whole cut; empty = none (add it on-platform) |
| `outro_path`         | clip appended after the last shot; empty = none |
| `assemble.music_volume` | level of the music bed under the voice                     |

Set by the format (`formats/<name>/format.yaml`), overridable in `config.local.yaml`:

| format key           | becomes                                                        |
|----------------------|---------------------------------------------------------------|
| `style`              | style line prepended word-for-word to every `image_prompt`     |
| `max_animated_shots` | cap on shots marked `animate: true`                            |
| `app_screens`        | real Iro app screenshots (`path`, `shows`) the script may put in app_screen shots |
| `locked_characters` (with `cast: locked`) | recurring cast: `id`, `role`, `description`, `image_path` |
| `resolution`, `fps`  | `assemble.width` / `height` / `fps`                            |
| `clip_seconds`       | `fal.video_seconds` and `sume.video_seconds`                   |
| `captions.*`         | `assemble.caption_*` (font, size, y, max_words, colours, outline, blur, pop) and `assemble.card_fade_ms` |
| `grade.*`            | `assemble.saturation`, `assemble.colorbalance`                 |
| `timing.*`           | `assemble.*` shot lengths and zooms                            |
| `rules`              | what the script validator enforces                             |

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
(sofia) come from `locked_characters` in `formats/pixar_arc/format.yaml` and are reused by id with their
descriptions copied word for word. Iro's reference image is `assets/iro.png`, the gold mascot
from the Kiro app; `assets/app_icon.png` is the app icon for the CTA shot. Descriptions are physical identity
only; each image prompt adds a scene-fitting outfit (work clothes in setbacks, upgraded clothes in
wins). Jess leaves Marcus for Tyler in beat 1, and the insult comes from her or Tyler, never the
boss. Iro is always the penguin mascot.
New characters are only invented for minor roles. Setbacks are cold office light, wins are
golden hour. A real AI tool (Claude or ChatGPT) is named at least once.

### Validation

Rules enforced by the prompt and checked by the validator (the numbers and wording are the
`pixar_arc` format's `rules`):

- 15 to 22 shots, numbered from 1 with no gaps
- every locked character is present and its description matches config exactly
- there is no narrator: every `vo_line` is dialogue spoken by a cast member (marcus, jess,
  tyler, boss, sofia, iro), `speaker` names who says it, and silent shots have an empty
  `vo_line` and `speaker`; a `narrator` speaker fails validation
- total `vo_line` words across the script is 60 to 100, and most shots are silent
- the image model never draws the Iro app: a character using a phone is shown with the back
  of the phone toward camera and the screen glow on their face, and an `image_prompt` that
  names "Iro AI", the app's UI, a logo or what a screen shows fails validation (the mascot's
  own name is fine). The closing CTA shot is a back-of-phone shot under `SEARCH IRO AI`
- the real app appears in `app_screen` shots (optional `"app_screen": "assets/screens/lesson.jpg"`
  field): exactly one right after the hero opens the app in the mentor beat and optionally one
  in the grind, using a path from the format's `app_screens`. An app_screen shot has no
  characters, no `vo_line`, `animate: false`, and is never the first or last shot. If no listed
  screenshot exists, none are asked for
- a FLEX MONTAGE of 6 to 8 consecutive shots right before the CTA (after the "that's my boy"
  reversal): the hero living the life (luxury car, watch close-up, suit outside a glass tower,
  rooftop at night, holographic AI dashboards with Iro, private jet, beach sunset with sofia,
  ending on a smirk at camera), warm golden or neon-night light, no dialogue. Montage shots
  carry the optional `"montage": true` field and `animate: false`, sit outside the 15-22 story
  shots, and never count toward the word budget. Scripts without montage shots still assemble
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
- App screen shots are 1.5 s (`assemble.app_screen_seconds`) of the real screenshot inside a
  rounded phone frame, centred on a blurred, darkened copy of the previous scene's last frame,
  with a slight push-in from 1.00 to 1.04 (`assemble.app_screen_zoom_end`). No captions are drawn
  over them. The images, video and voice steps make nothing for these shots.
- Flex montage shots are 0.5 s each (`assemble.montage_seconds`) with hard cuts and a quick
  eased punch-in from 1.00 to 1.12 (`assemble.montage_zoom_end`), and no captions. If a montage
  shot was animated anyway, its clip gets the same punch-in.
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
