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

# pick a caption style for a new video, or change it on a finished one (then assemble again)
python main.py new "A laid-off line cook buys a food truck" --captions yellow_pop
python main.py captions 20261103-201530-a-laid-off-line-cook headline
python main.py step 20261103-201530-a-laid-off-line-cook assemble
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

### Installed formats

| format | look | story |
|---|---|---|
| `pixar_arc` | 3D animated feature | the dumped-and-fired hero arc, dialogue, flex montage (default) |
| `pixar_mirror` | the same look and cast | one small scene played twice: brushed off, opens Iro, three progress shots with his rank and a climbing number, a time card, the same scene with the roles reversed |
| `pixel_art`, `ps2`, `comic`, `brick`, `claymation`, `paper_cutout`, `retro_anime`, `low_poly`, `risograph`, `miniature` | one look each | a narrated 15-25 s story ad: someone wants something, it goes wrong, they open Iro, it pays off, a twist, SEARCH IRO AI |
| `style_switch` | a different look every shot, on hard cuts | the same narrated story |

Every format above except `pixar_arc` and `pixar_mirror` can also use the Claude Code engine (below).

Six more, from the formats ad buyers rank highest right now:

| format | what it is | what it adds |
|---|---|---|
| `letter_ad` | a personal letter, handwritten line by line on a paper card over a quiet photo, read aloud | letter shots |
| `confession` | a person admits something to their phone camera, then what fixed it | talking shots |
| `talking_head` | one person, straight to camera, a bold opinion and three quick points | talking shots |
| `street_interview` | a host with a mic stops strangers; the sharp answer is the ad | talking shots |
| `founder_podcast` | a podcast clip where the founder tells the story behind the app | talking shots |
| `song_ad` | a 3D animated mini-story told as a song, karaoke lyrics on screen | song mode |

And seven modelled on formats from Fastlane's gallery:

| format | what it is | built on |
|---|---|---|
| `explainer_3d` | a fast narrated 3D explainer ad in the Zack D Films style: one idea about AI as a chain of things you can see | narrator + clips |
| `true_story_3d` | one strange true event in the same style ("He tied 42 balloons to a lawn chair"); no ad, no call to action | narrator + clips |
| `skeleton` | a glowing skeleton lives your day while a narrator explains what your brain is doing | narrator + a locked skeleton |
| `felt`, `fashion_doll` | the narrated story ad in needle-felted wool, or with plastic fashion dolls (the Barbie look) | same as claymation |
| `news_anchor` | a deadpan anchor breaks the viewer's problem as tonight's top story, red banner on screen | talking shots + labels |
| `podcast` | two hosts at their mics, back-and-forth | talking shots |
| `beginner_expert` | three people pass a mic, each with a sharper take, with BEGINNER / INTERMEDIATE / EXPERT tags | talking shots + labels |

(The Lego look is the `brick` format.)

The two 3D formats share one story craft: line 1 is the odd physical act ("He ..."), every
sentence after it starts with a hinge word (Then, Suddenly, So, Because, But, Later) and is one
visible action, the context arrives late after "You see,", and there is a new picture for every
line from a fixed shot kit (macro insert, hero low angle, top-down, glow highlight, a big 3D
number, a thought bubble ...), with calm shots only. For `true_story_3d` the premise is the
event; the script is told to use only facts it is sure of, and it rejects questions and calls to
action, but check the facts yourself before posting.

Each adds one capability a format can switch on in its `rules`:

- **Labels** (`rules.labels: true`). A shot may carry `"label"`: a tag of up to three words shown
  at the top of the screen for the whole shot, on a coloured box. The format's `labels:` block
  sets size, position, the default box colour and a colour per label text.

- **Letter shots** (`rules.letter: true`). Every shot carries `"letter"`: its line of the letter.
  The assemble step draws the letter so far, in a handwriting font (Caveat, `assets/fonts/`), on
  a ruled paper card over the shot's picture; the letter grows line by line and scrolls when the
  card is full. A shot with `"image_prompt": ""` keeps the previous background, so a letter ad
  needs only a few images. Card look: the `letter:` block in the format (paper, ink, font size).
- **Talking shots** (`rules.talking: {max: n}`). A shot with `"talk": true` shows only its
  speaker; the video step turns its keyframe into a lip-synced clip of them saying the line, with
  fal's talking-avatar model (`fal.avatar_model`, Kling AI Avatar v2 Standard, about $0.06 a
  second of speech; always on fal, whichever video provider you pick). The shot's voice line is
  made first if it is missing, and redoing a talking shot's voice deletes its clip so the lips
  never go out of sync. Cast yourself from the Characters page (e.g. as the founder).
- **Song mode** (`rules.song: true`). The script adds `"song": {"style": "..."}` and every
  shot's `vo_line` is a lyric line. The voice step sends the lyrics and style to the ElevenLabs
  Music API (`elevenlabs.music_model`, needs a paid plan; price in `music_cost_per_minute`,
  check yours), then ElevenLabs forced alignment finds when each word is sung. Every shot lasts
  exactly as long as its line, the song is the soundtrack, and the captions follow the lyrics.

The ten looks and the narrated story shape come from the claude-animation-styles skill
(`skills/claude-animation-styles/`). That skill renders with hand-written three.js code in
Claude Code; here each look is a style line plus image rules for the image model, so it runs on
the normal pipeline. The narrated formats set `rules.narrator: true`: the narrator speaks with
`voices.narrator` (falling back to `voice_id`). `pixar_arc` has no narrator: its dialogue tells
the story. A format that wants both sets `narrator: true` with `rules.dialogue_lines_min` (how
many lines must still be spoken by characters).

A format can carry `title:` (shown in the UI), `cover.jpg` (its gallery card) and `example.mp4`
(its preview). Set the last two from any run in the UI: "Use as cover" on a shot, "Use as
example" on a finished video.

### Your characters

Make a character once and cast it in any format: on the **Characters** page of the UI (or by
hand in `library/characters/<id>/`, which git ignores). A character has a name, a one-sentence
description (identity only: age, face, hair, skin, build), an optional usual role and ElevenLabs
voice id, and a picture. Get the picture by uploading one or by drawing it from the description
in any format's style (one image call). "Describe from picture" asks Claude for the description.

On the create screen, the **Cast** section lets you swap any of the format's characters for one
of yours (yours takes over their role, and their voice if you set none) or add one of yours to
the story. From the CLI:

```bash
python main.py new "<premise>" --cast dana=marcus           # dana plays marcus's role
python main.py new "<premise>" --format claymation --cast rex   # rex joins the story
```

The cast is saved in the run's `run.json`, so step, reroll and recast keep using it. In the
images step a library character's sheet is drawn from its picture in the run's style the first
time it is used in that format (cached in `characters_cache/` as `lib-<id>@<format>-<hash>.png`;
editing the picture or description draws a fresh one). Tick "Use my picture exactly as it is"
to skip that and use the picture itself as the reference.

### Voices

A speaker with a voice id in `voices:` (config.local.yaml), or a library character with its own
voice, always uses it. Anyone else, usually the people a format invents for one video, is
**cast automatically** from the voices in your ElevenLabs account: same gender, close in age
(both read from the character's description, "a 31 year old woman with ..."), and a different
voice for each person in the video. Casting happens right after the script is written, so the
run page's **Voices** panel shows who got which voice before anything is spoken; there you can
play a preview, pick another voice for any speaker (the narrator too, for that one video) and
redo the lines already spoken. The choices are saved in the run's `voices.json`.

Reading the voice list is a free ElevenLabs call, cached for an hour. To get more variety, add
voices you like to "My Voices" on elevenlabs.io and press Refresh. `voice_casting.exclude` in
config lists voice ids never to cast; `voice_casting.enabled: false` turns it off (uncast
speakers then use the default `voice_id`).

### The Claude Code engine

The ten looks from claude-animation-styles (and `style_switch`) can also run on the skill's
own engine: Claude Code writes the story, codes every scene in three.js/canvas and the video
renders on your computer. No image or video model is called; the coding runs on your Claude
login. Pick **Engine: Claude Code** on the create screen, or `--engine claude_code`.

Set it up once: Node.js 20+ (Windows: `winget install OpenJS.NodeJS.LTS`), Claude Code, and
`claude auth login`. `python main.py doctor` checks all three. The first run installs the
template's packages into `cache/code_engine/` (puppeteer downloads its own Chrome, a few
minutes); every run after shares them.

A Claude Code run keeps its work in `runs/<id>/code/` and has four steps:

| step | what happens |
|---|---|
| `story` | Claude Code writes `story.json` (one line per beat, a style each) and `story.md` with `copywriter.md` |
| `scenes` | Claude Code rewrites each style file for the story and checks stills (`node render.cjs stills`) |
| `voice` | VidGen reads the lines with ElevenLabs and times the beats to the voice (skipped without a key) |
| `render` | VidGen runs `node render.cjs video` and copies `out/video.mp4` to `final.mp4` |

"Story only" stops after the story so you can edit the lines in the UI before the scenes are
coded. How Claude Code is run: headless (`claude -p`) in the run's `code/` folder, with the
skill's instructions and the format's prompt copied in so it never needs another folder. Its
environment has no API keys (VidGen removes `ANTHROPIC_API_KEY`, so Claude Code uses your
subscription login, and the fal / Sume / ElevenLabs keys stay with VidGen). It may read and edit
files in that folder and run exactly one command, `node render.cjs stills ...`; anything else
is denied, never prompted. Settings live under `code_engine:` in `config.yaml` (model, turn
limits, timeouts). It counts toward your Claude plan's usage limits; a run that hits one stops
with a message saying so. On Windows and Linux the 3D styles render in software, so a 20 second
video can take several minutes.

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
and in the terminal are the same runs in the same output folder. Interactive API docs are at
`/api/docs`.

While a job runs, a progress bar on the run's page shows what it is doing ("Drawing images, 12
of 29"), which step of how many, an overall percentage and the time so far. The same bar, in
small, sits in the job bar at the bottom and under the run in the sidebar. The steps report it
through `progress.py`; `GET /api/jobs` returns it as `progress` on the running job.

The editor (`ui/`: `index.html`, `app.css`, `app.js`; plain HTML/CSS/JS, no build step) has:

- **Sidebar**: New video, and every run with its state (video ready, script only, in progress,
  running, last job failed).
- **Studio** (New video): every format as a card with its cover, description and an "about $X a
  video" estimate from the format's own limits. Pick one to open its create screen: premise,
  output (full video or script only), provider, format details (length, shots, clips, cast, beats)
  and the cost, next to the format's example video or cover. Setup problems from `doctor` show on
  top.
- **Run**: the step pipeline with per-step progress (click a step to run it), the provider for
  actions, the estimated cost so far; the cast sheets; a 9:16 card per shot (keyframe, clip
  plays on hover, play button for the line, Reroll / Image / Voice, ★ to use it as the format's
  cover); select several shots to
  redo images, video or voice for just those; the final video with Download; and the script
  editor (dialogue, speaker, caption, time-card text) that validates on save and offers to
  redo the voice for changed lines.
- **Jobs drawer**: the live log of the running job, the queue, and recent jobs with the error
  line of any that failed.

Every paid action asks first with an estimate (keyframes × image price, clips × clip length ×
price per second, voice characters × price), using the prices in `config.yaml` (served by
`/api/config`).
Dry runs, Assemble and Recast make no paid calls and do not ask. Buttons on a run are disabled
while it has a queued or running job, and the run refreshes (with fresh media) when a job ends.

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
  build/                intermediate clips, captions.ass, sfx.wav + sfx.json, the pre-outro mix
  final.mp4             the finished short
characters_cache/<id>.png   generated sheets for locked characters, reused by every run
characters_cache/<id>.txt   the description each sheet was drawn from
```

`<run_id>` is a timestamp plus a slug of the premise.

## Configuration (`config.yaml`)

| key                  | purpose                                                       |
|----------------------|---------------------------------------------------------------|
| `voice_id`           | default ElevenLabs voice                                       |
| `script.model`       | Claude model for the script step (`claude-sonnet-5-5`)         |
| `script.max_tokens`  | cap on one script reply, the model's thinking included (64000) |
| `script.effort`      | how hard the model thinks: `low` to `max`; empty = its default |
| `characters_cache_dir` | where generated locked-character sheets are cached           |
| `fal.image_model`    | text-to-image endpoint (`fal-ai/nano-banana`)                  |
| `fal.image_edit_model` | reference-image endpoint (`fal-ai/nano-banana/edit`)         |
| `fal.video_model`    | image-to-video endpoint (`bytedance/seedance-2.0/fast/image-to-video`) |
| `fal.video_resolution` / `fal.video_audio` | clip size (480p or 720p, default 480p), audio (off); clip length is the format's `clip_seconds` |
| `fal.image_cost` | USD per image for the printed estimates |
| `fal.video_cost_per_second` | USD per second of video, keyed by resolution; the active one is used |
| `providers.images` / `providers.video` | `sume` (default) or `fal`, chosen separately |
| `sume.*`             | Sume models, settings, prices, `max_concurrent` and retry/poll limits |
| `voices`             | speaker id to ElevenLabs voice id; empty entries fall back to `voice_id` |
| `elevenlabs.model_id` / `output_format` / `cost_per_1k_chars` | TTS model, audio format, rate for the estimate |
| `music_path`         | music bed under the whole cut; empty = none (add it on-platform) |
| `outro_path`         | clip appended after the last shot; empty = none |
| `assemble.music_volume` | level of the music bed under the voice                     |
| `sfx.source` / `sfx.volume` | where sound effects come from (`auto`, `elevenlabs`, `builtin`) and how loud they are together |

Set by the format (`formats/<name>/format.yaml`), overridable in `config.local.yaml`:

| format key           | becomes                                                        |
|----------------------|---------------------------------------------------------------|
| `style`              | style line prepended word-for-word to every `image_prompt`     |
| `max_animated_shots` | cap on shots marked `animate: true` (when `animate_all` is off) |
| `extends`            | another format to start from; this file then lists only what differs |
| `animate_all`        | `true`: every drawn shot becomes a video clip (set by the format; Pixar Arc: on) |
| `sfx`                | `true`: sound effects under the cut (set by the format; Pixar Arc: on). `sfx: false` or `sfx: {enabled: true}` in `config.local.yaml` decides for every format |
| `assemble.caption_style` | caption style for new videos (see Caption styles); empty = the format's own |
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
(sofia, a goth girl who always dresses in black) come from `locked_characters` in `formats/pixar_arc/format.yaml` and are reused by id with their
descriptions copied word for word. Iro's reference image is `assets/iro.png`, the gold mascot
from the Kiro app; `assets/app_icon.png` is the app icon for the CTA shot. Descriptions are physical identity
only; each image prompt adds a scene-fitting outfit (work clothes in setbacks, upgraded clothes in
wins). A character can also have an `outfit:` line in `locked_characters` for a look they keep in
every scene (sofia's all-black goth style). Jess leaves Marcus for Tyler in beat 1, and the insult comes from her or Tyler, never the
boss. Iro is always the penguin mascot.
New characters are only invented for minor roles. Setbacks are cold office light, wins are
golden hour. A real AI tool (Claude or ChatGPT) is named at least once.

### Validation

Rules enforced by the prompt and checked by the validator (the numbers and wording are the
`pixar_arc` format's `rules`):

- 15 to 22 shots, numbered from 1 with no gaps
- every locked character is present and its description matches config exactly
- there is no narrator: every `vo_line` is dialogue spoken by a cast member (marcus, jess, tyler,
  boss, sofia, iro) who is in the shot, and the dialogue tells the story: lines answer each
  other, each beat's key fact is said out loud, and Iro acts as the running commentary. A
  `narrator` speaker fails validation
- at most 2 story shots in a row are silent (`rules.silent_run_max`)
- a shot's `sfx` is a sound name or `none`; anything else is dropped, and so are sounds past the
  fifth (see Sound effects)
- total `vo_line` words across the script is 70 to 120
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
- no more than `max_animated_shots` shots are `animate: true`, reserved for shots where motion is the beat;
  with `animate_all` on (the default for this format) every drawn shot is `animate: true` instead
- `speaker` is a known character id (never `narrator`); captions are at most two words (except the CTA)
- dialogue sounds spoken, not written by AI: a `vo_line` with an em dash, a semicolon, "it's not X,
  it's Y", "not just X but Y", filler ("here's the thing", "let that sink in"), fake suspense
  ("plot twist:") or an AI word (unlock, game-changer, next level, ...) fails validation
  (`rules.banned_vo_line` in the format, taken from the viral-video-writing skill's checker)

The prompt also asks for: a hook in shot 1 (open mid-action on the insult or the firing, readable
on mute, an immediate camera move), something new at least every 8 seconds with the strongest
grind moment in the middle, and at most one one-word line. These come from the
viral-video-writing skill in `skills/`.

If the JSON is invalid or fails validation, the errors are sent back to the model and it gets
one retry. The result is saved to `runs/<run_id>/script.json` and printed as a shot table.

## The images step

`steps/images.py` first makes sure every character in `script.json` has a reference sheet at
`runs/<run_id>/characters/<id>.png`. The source is, in order: the `image_path` set in
`locked_characters`, a cached sheet in `characters_cache/`, a sheet already in the run, or a
freshly generated sheet (front, three-quarter and side view on a plain light grey background).
**App screens in a hand.** With `app_screen_hand: true` (Pixar Arc), an app-screen shot shows
the real screenshot on a phone held in the hero's hand, not a bare phone frame. The image model
never draws the app: the images step draws one picture of a hand holding a phone with a plain
green screen (once per format, cached as `characters_cache/hand@<format>-<hash>.png`, copied to
`runs/<id>/app/hand.png`), and the assemble step puts the real screenshot on the green area, so
a thumb over the edge of the screen stays in front. A picture with no clean green screen is
thrown away and tried once more; if that fails too, the shot uses the plain phone frame. To get
the hand on a run made earlier, run its images step again, then assemble.

**Scene continuity.** Each picture is drawn from its own text, so three shots of one
conversation can come out with three different outfits and backgrounds. A shot marked
`"same_scene": true` in `script.json` continues the previous shot's scene (same place, same
moment); it is drawn with the scene's first shot as an extra reference image, so the place, the
light and everyone's clothes carry over. The script step marks these shots itself; scene
starters are drawn first, then the shots that continue them. An app screenshot in between does
not break a scene; a time card or a montage shot does. In the UI the shot shows a "scene" badge,
and "Picture and motion" in the script panel has a checkbox to turn it on or off for a shot
(then redo that shot's image and video). Redoing a scene's first shot prints which shots follow
it, in case they need redoing too.

New sheets for locked characters are copied into `characters_cache/` for later runs, with a
note (`<id>.txt`) of the look they were drawn from. Change a locked character's description or
`outfit` and their cached sheet is redrawn the next time it is needed (the Cast list in the UI
shows "New look" until then). For a run that already
exists, `python main.py recast <run_id>` applies the new description to it.

Then it generates one 9:16 keyframe per shot at `runs/<run_id>/shots/<n>.png`. Shots with
characters go through the edit endpoint with those characters' sheets attached as references
and a note telling the model which reference is which. Shots with no characters use plain
text-to-image. A running cost estimate is printed at the end.

## The video step

**Every shot is a clip (`animate_all`).** A format with `animate_all: true` (Pixar Arc) turns
every drawn shot into a video clip, flex-montage shots included, so nothing in the video is a
still picture with a slow zoom. Only time-jump cards and app screenshots are not clips. It is
the main cost of a video: about 26 clips instead of 8. The script prompt then asks for real
movement in every `motion_prompt`, and a run whose script was written earlier is brought up
to date when its video step next runs. Set `animate_all: false` in the format, or in
`config.local.yaml` for every format, to animate only the key shots (at most
`max_animated_shots`) and keep the rest as stills; `animate_all: true` in `config.local.yaml`
turns it on for every format.

**Mouths move.** When a shot has a line and its speaker is in the picture, the motion prompt
sent to the video model also says who is talking and what they say, so the character's mouth
moves while the line is heard. This is not exact lip-sync (the voice is added at assembly); set
`mouths_move: false` in `config.local.yaml` to send the motion prompt as written.

**Dropped downloads.** A provider can finish a clip and then drop the connection while the file
is downloaded. Downloads are tried five times, and the file's address is kept next to where it
will be saved (`shots/18.mp4.url`) until it is safely on disk. If every try fails, running the
step again downloads the finished file first and only generates again when that address no
longer works, so a clip you paid for is not made twice.

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

### Caption styles

A format sets its own captions. A caption style swaps the look (font, colours, outline, shadow)
and keeps the format's size, position and words per caption, so any style works with any format.

| style        | look                                              |
|--------------|---------------------------------------------------|
| `format`     | the format's own (Pixar Arc: white with a pink glow) |
| `classic`    | bold white with a soft shadow                     |
| `outline`    | bold white with a thick black edge                |
| `yellow_pop` | yellow with a black edge and a bigger pop         |
| `comic`      | comic-book lettering with a hard shadow           |
| `headline`   | tall condensed capitals                           |
| `banner`     | white text on a black bar                         |
| `off`        | no word-by-word captions; time cards and a shot's own caption (the closing one) stay |

Pick one on the create screen, with `new --captions <style>`, or for every new video with
`assemble: {caption_style: yellow_pop}` in `config.local.yaml`. The choice is saved in the run's
`run.json`. To change a finished video, pick another style on its page (or
`python main.py captions <run_id> <style>`) and run the assemble step again; assembling makes no
API calls, so it costs nothing. The presets live in `caption_styles.py`; the fonts (Poppins,
Anton, Bangers, Montserrat) are bundled in `assets/fonts/` under the SIL Open Font License.

- Each shot lasts its voice-over length plus 0.25 s, with a 1.2 s minimum.
- Animated shots are trimmed to that length (the last frame is held if the clip is shorter).
  Still shots get a slow push-in from 1.00 to 1.08 on the keyframe.
- Every shot is scaled and cropped to fill 1080x1920 with no black bars, then all shots are
  concatenated and the voice-over clips are placed at their shot start times.
- Captions come from a generated `.ass` file and are burned in. Every spoken word is shown,
  one word at a time in all caps for `pixar_arc` (the format's `captions.max_words`; set it to
  2 for two-word chunks), built from the word timings in `audio/<n>.json`: a chunk never holds
  more than `max_words` words and always breaks after punctuation, appears when its first
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
- Sound effects, when the format has them, are mixed under the voice (see Sound effects below).
- A music bed is mixed under the cut only when `music_path` is set, and the outro is appended
  only when `outro_path` is set. The result is `runs/<run_id>/final.mp4`, H.264 + AAC at 30 fps,
  and the step ends with an estimated cost breakdown for images, video and voice.

### Sound effects

With `sfx: true` (Pixar Arc), the assemble step lays short effects under the voice. `sfx.py`
decides where from the cut itself:

| where                                   | sound                                      |
|-----------------------------------------|--------------------------------------------|
| a change of scene                       | `whoosh`, its loudest point on the cut     |
| a time-jump card                        | `impact`                                   |
| an app screen                           | `pop`                                      |
| the first montage shot                  | `riser` that ends on the cut, then `impact` |
| every montage cut after it              | `swish` (a short whoosh)                   |

A change of scene is a drawn shot that does not carry `"same_scene": true`, so cuts inside a
conversation stay clean; a script with no `same_scene` at all gets no scene whooshes. Two scene
whooshes are never closer than 0.9 s.

A shot can also carry its own `"sfx"` in `script.json`: `whoosh`, `swish`, `impact`, `pop` or
`riser` plays that sound on the shot's first frame in place of the automatic one, and `none`
keeps the shot silent. The script step may set `impact` or `pop` on up to five shots where the
picture shows something that makes the sound (a door slams, a notification lands). In the UI it
is the Sound choice under Picture, motion and sound on each shot; after changing it, assemble
again.

Each sound comes from the first of these that exists:

1. your own file: `assets/sfx/<name>.wav` (or `.mp3`, `.m4a`, `.ogg`), for example
   `assets/sfx/whoosh.mp3`
2. ElevenLabs Sound Effects, when `ELEVENLABS_API_KEY` is set and `sfx.source` is `auto` or
   `elevenlabs`: five short sounds, generated the first time they are needed and kept in
   `cache/sfx/` for every later video
3. a built-in sound, synthesized locally (`sfx.source: builtin` uses these only)

Whatever the source, a sound is trimmed to start on the sound and brought to one level, so a
file from a sample pack sits where a built-in one would. If ElevenLabs cannot make a sound, the
built-in one is used and the log says so; the step does not fail. `sfx.volume` scales all
effects together (1.0 = normal). The effects are written to `build/sfx.wav`, and `build/sfx.json`
lists each one with its time. Song formats never get effects.

### Pixar Mirror: one scene, played twice

`pixar_mirror` is a second story shape for the Pixar cast, modelled on short app ads that tell
their story twice (about 45-55 seconds, 55-90 spoken words):

1. a small public brush-off, 5-7 lines, opening on the line that stings
2. "Enough is enough", alone
3. the app in his hand, with a small `*OPENS IRO*` label
4. three progress shots, each with the rank and a number drawn over it
5. one time card
6. the same place and people again, with at least two lines repeated word for word and now
   meaning the opposite; he is polite, brief and leaves
7. the flex montage, then the `SEARCH IRO AI` shot

Pick it like any format: `python main.py new "..." --format pixar_mirror`, or its card in the
UI. A premise only needs the small scene: who brushes him off, where, and over what.

It is defined by `extends: pixar_arc` in `formats/pixar_mirror/format.yaml`, so the cast, the
look, the captions and the app screenshots are Pixar Arc's and are edited there once. A format
that extends another starts from its settings (mappings merge key by key; lists and single
values are replaced) and uses its prompt files wherever it has none of its own. Title,
description and beats are never inherited, and a format cannot extend one that itself extends.

**Progress overlay.** A shot with `"stat": {"rank": "GOLD II", "value": 40, "unit": "DAY STREAK"}`
gets the rank on a dark card top left and the number, large, lower left. The number starts one
lower and ticks up partway through the shot, with a pop on the sound track. The image model
draws none of it, so the digits are always right. The format's `rules.stats` lists how many
such shots a script has (`count`), the ranks from lowest to highest (`ranks`; a division I, II
or III may follow the name) and what the number may count (`units`). The validator checks that
the number climbs and the rank never drops. In the UI, each progress shot has Rank, Number and
Counts fields under Picture, motion and sound; after changing them, assemble again. The
format's `stat:` block sets the look (`eyebrow`, `size`, `rank_size`, `x`, `y`, `rank_y`,
`seconds`, `tick`).

**Labels.** With `rules.labels: true` a shot may carry a short `label`, shown for the whole
shot: here dark text on a white box with an asterisk either side, on the app screen and on one
stage direction (`*DROPS THEM ON PURPOSE*`). `rules.label_max_words` caps its length and the
format's `labels:` block sets `y`, `size`, `text`, `box` and `wrap`.

**Mirrored lines.** `rules.mirror_lines_min: 2` makes the validator count the lines after the
time card that repeat a line from before it (capitals and punctuation aside) and reject a
script with fewer than two.

## Providers: fal or Sume

Images and video can each run on [Sume](https://sume.com/docs) (the default, about half the
price for the same models) or on [fal.ai](https://fal.ai). Switch them independently in
`config.yaml` or `config.local.yaml`:

```yaml
providers:
  images: sume
  video: fal
```

`default_video_provider` / `default_image_provider` in `config.local.yaml` (from the example
file) are the same settings and win over `config.yaml`, so a `fal` left there keeps fal as your
default. The provider menu on a run's page and on the create screen overrides it for one job.

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
