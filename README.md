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

# choose the app screenshots the video shows (list them with: python main.py screens)
python main.py new "A laid-off line cook opens a food truck" --screens streak,rank_up

# skip the script step: use a script that is already written (list them with: python main.py ready)
python main.py new --format pixar_mirror --ready the_standup

# script only: write and print the shot list, nothing sent to fal, Sume or ElevenLabs
# (it still calls Claude to write the script, a few cents)
python main.py new "A laid-off line cook opens a food truck" --dry-run

# re-run a single step on an existing run
python main.py step 20261103-201530-a-laid-off-line-cook script

# regenerate only specific shots (images, video or voice)
python main.py step 20261103-201530-a-laid-off-line-cook images --only 3,7

# regenerate one shot's image + video
python main.py reroll 20261103-201530-a-laid-off-line-cook 7

# move a shot to another place (here shot 2 becomes shot 1). Its picture, clip and voice move
# with it, nothing is generated; assemble again for the video in the new order
python main.py move 20261103-201530-a-laid-off-line-cook 2 1

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

| `pixar_revenge` | the same look and cast | almost wordless: a public rejection, she leaves with a richer man, the grind in quick flashes, a time card, the reunion and one comeback line |
| `pixar_ladder` | the same look and cast | "I can fix that": doubted, he does the work on screen, gets paid, word spreads, every client is bigger than the last |
| `pixar_steps` | the same look and cast | a 90-110 s film plus tutorial: the rejection, the method shown working, then the hero gives it in numbered steps, one of them Iro |

Every format above except the five `pixar_*` ones can also use the Claude Code engine (below).

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

### App screens

The demo beat of a video shows the real app: a screenshot on a phone in the hero's hand, never
a drawing of the app. VidGen ships a library of 24 Iro screens in `assets/screens/`, described in
`assets/screens/library.yaml`:

| group | screens |
|---|---|
| Opening the app | building your path, first rank (Bronze III), learning path, choose a path |
| Learning | lesson card, lesson question, correct answer, match the tools, lesson podcast |
| Coach and practice | Ask Iro, Prompt Lab, duels |
| Wins and rewards | lesson complete, streak, reward chest, rank up, unit complete, certificate |
| Progress and rank | after a lesson, progress, weekly league, quests, awards |
| More of the app | create a path |

```bash
python main.py screens                                   # the library, with the names below
python main.py new "premise" --screens streak,rank_up    # this video shows exactly these
```

Every format can use every screen. The script writer reads each screen's `shows` line and
picks the one that fits the moment. To decide yourself, pin them: `--screens` on the command
line, or the **App screens** card on the create screen in the UI, which opens a picker with a
thumbnail of every screen. A format shows a fixed number (Pixar Arc and Pixar Steps two, the
other Pixar shapes one), so that is how many you can pin. Pinned screens are saved in the run's
`run.json` (`"screens"`); the script step then offers only those and refuses a script that leaves
one out or shows one twice.

After the script is written you can still swap a screen: in **Script and editing**, an app
screen row shows its picture and a **Change screen** button. Swapping is free, because only the
assemble step uses the screenshot; save, then assemble again.

**Your own screenshots.** In the UI, **App screens** in the sidebar lists the library, and
"Add a screenshot" under *Your own* takes a phone screenshot (PNG or JPG, upright), a name and
a line saying what it shows. You can also drop pictures straight into `assets/screens/mine/`;
they are listed under their file names. Yours are offered to every format next to the shipped
ones, can be pinned and swapped the same way, and are not in git. Give each one a real `shows`
line: it is all the script writer knows about the picture.

**Screens that move.** Twelve of the shipped screens are recordings of the app, not stills,
and play on the phone for four or five seconds:

| screen | what plays |
|---|---|
| building your path | Iro types while the web of skills and tools lights up and the percent runs to 100 |
| first rank | the Bronze III emblem is forged, the name lands, the rank ladder fills in |
| learning path | the app opens: the splash, the reveal, the map |
| correct answer | the right answer is tapped, turns green, the bar fills, "Correct!" slides up |
| match the tools | four pairs are matched one after another, then "Correct!" |
| lesson complete | three stars, the XP counts up to +88 |
| streak | the flame lights, 4 rolls to 5, the week's days tick |
| reward chest | the chest is tapped from common to legendary and opens on +100 gems |
| rank up | Silver to GOLD with the mascot in gold and confetti |
| unit complete | the checklist of what you can do now stamps in line by line |
| after a lesson | the rank bar steps up a division, the certificate and league cards land |
| create a path | topic ideas type themselves into the create box |

In the UI they carry a play mark and play when you hover over them; `python main.py screens`
marks them `[moves, 4s]`.

A screen moves when a recording with the same name sits beside its picture (`streak.jpg` +
`streak.mp4`). The picture is its thumbnail and the fallback. An app screen shot with a
recording lasts as long as the recording (up to `assemble.app_clip_max_seconds`, 6), and the
recording plays inside the same phone, in the hand or in the plain frame; a recording shorter
than the shot holds its last frame. The script writer is told which screens move.

- Show the still instead, for one shot: untick **Play the recording** on the app screen row
  in the script editor (`"app_still": true` on the shot).
- Show stills everywhere: `assemble.app_screen_clips: false` in `config.local.yaml`, or a
  format's `timing.app_screen_clips: false`.
- Your own recording: "Add your own" takes a phone screen recording too (MP4 or MOV, upright).
  It is re-encoded to a silent MP4, cut to 12 seconds, and its picture is made from one of its
  frames. Or drop the file in `assets/screens/mine/`. Trim it on your phone first so it starts
  where the action starts.

The shipped recordings were made from the app's web build one frame at a time on a paused
clock, so they are smooth at 30 frames a second whatever the machine. Loops the app plays as
animated images (the mascot's small movements, the chest lid) show as stills in them.

To change the shipped set, replace a picture in `assets/screens/` (860 x 1864 JPEG works well)
or edit `library.yaml`: `file`, `title`, `shows`, `group`. A format's own `app_screens` list
still works and comes first in the prompt with its own wording; the library follows.

### Voices

A speaker with a voice id in `voices:` (config.local.yaml), or a library character with its own
voice, always uses it. Anyone else, usually the people a format invents for one video, is
**cast automatically** from the voices in your ElevenLabs account: same gender, close in age
(both read from the character's description, "a 31 year old woman with ..."), and a different
voice for each person in the video. Casting happens right after the script is written, so the
run page's **Voices** panel shows who got which voice before anything is spoken; there you can
play a preview, pick another voice for any speaker (the narrator too, for that one video) and
redo the lines already spoken. The choices are saved in the run's `voices.json`.

Reading the voice list is a free ElevenLabs call, cached for an hour. To get more variety, press
**Find more voices** in the Voices panel: it searches the public ElevenLabs voice library
(English voices, most used first) by gender, age and any words you type ("energetic",
"American", "casual"), plays a sample of each, and **Use for marcus** adds the voice to your
ElevenLabs voices and gives it to that speaker in one go. Adding a voice takes one of your
plan's voice slots and costs nothing by itself; if the plan has no slot left, VidGen says so.
You can also add voices on elevenlabs.io yourself and press Refresh. `voice_casting.exclude` in
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

The interface is light by default; "Dark mode" at the foot of the sidebar switches it, and the
choice is remembered in that browser. Its typeface (Inter) ships with VidGen, so it looks the
same on every computer.

A FastAPI server on **127.0.0.1 only** (it holds your API keys; nothing else on the network
can reach it). It calls the same functions as the CLI (`commands.py`), so runs made in the UI
and in the terminal are the same runs in the same output folder. Interactive API docs are at
`/api/docs`.

While a job runs, a progress bar on the run's page shows what it is doing ("Drawing images, 12
of 29"), which step of how many, an overall percentage and the time so far. The same bar, in
small, sits in the job bar at the bottom and under the run in the sidebar. The steps report it
through `progress.py`; `GET /api/jobs` returns it as `progress` on the running job.

The editor (`ui/`: `index.html`, `app.css`, `app.js`; plain HTML/CSS/JS, no build step) has:

- **Sidebar**: New video, Characters, App screens (the screenshot library, see App screens),
  and every run with its format and state (video ready, script only, in progress, running,
  last job failed).
- **Studio** (New video): the formats grouped by kind (Pixar stories, People talking, Animated
  looks, Letters and songs) with a search box. Each card shows its cover, description, length
  and an "about $X a video" estimate from the format's own limits. Pick one to open its create
  screen: a ready-made story to pick (when the format has any) or your own premise, output
  (full video or script only), the app screens to show, provider, and
  the Generate button with the cost, which stays in view as you scroll. Beside it, "How this video goes": length, shots, clips,
  cast, the beats in order, and the reference videos the format is modelled on. Setup problems
  from `doctor` show in one line on top; open Details for the list.
- **Run**: one bright button top right is always the next thing to do ("Make the images",
  "Record the voices", then "Download video"). Under it, the numbered steps with their progress
  (click any step to run it again). Two tabs:
  - **Shots**: the cast sheets and a 9:16 card per shot (keyframe, clip plays on hover, play
    button for the line, Reroll / Image / Voice, the star to use it as the format's cover).
    Select several shots to redo images, video or voice for just those.
  - **Script and editing**: every shot as a row with its picture, speaker, caption and line
    (the two arrows under a row's picture move the shot one place earlier or later; its
    picture, clip and voice move with it and nothing is generated; the bin beside them removes
    the shot, with its picture, clip and voice, after asking)
    (an app screen row has a Change screen button).
    Between any two rows, **Add a shot here** opens a short form: a scene shot (who is in it,
    what we see, how it moves, an optional line and who says it), text messages on the phone,
    or a time card. VidGen writes the shot from the answers (`shot_new.py`): the cast's
    descriptions word for word, the place carried over from the shot before when it continues
    that scene, and nobody called by name in the picture prompt. The later shots keep their
    pictures, clips and voices under their new numbers. The new shot has no picture yet;
    "Make its picture" draws just that one.
    A script you edit may go past the format's shot and word counts, which are targets for
    whoever writes it. What makes the format (its time card, its progress shots, its montage,
    the lines that come back) still has to hold, and the error says which.
    "Picture, motion and sound" under a row opens the rest (scene description, motion, sound
    effect, progress number, time-card text). Save with the button or Ctrl+S (Cmd+S on a Mac);
    it validates and offers to redo only what changed. A dot on the tab means unsaved edits.
  **Delete** in the header (and the bin beside each video in the sidebar) removes a video and
  everything made for it, after asking. It cannot be undone, and it is refused while a job is
  working on that video.
  The right column holds the final video with Download, the caption style, the voices and the
  cost so far. A run made with the Claude Code engine has the same header and steps (Story,
  Scenes, Voice, Render), its stills, and the story editor in the right column.
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
| `DELETE /api/runs/{run_id}` | deletes the video's folder (409 while a job is working on it, or while one of its files is open in another program: nothing is half deleted) |
| `POST /api/runs/{run_id}/shots` `{after, shot}` | adds a shot after shot `after` (0 = first); `shot` is the form's answers, `{kind: scene / texts / card, ...}`. 422 with the reason when an answer is missing or the format's rules refuse it |
| `DELETE /api/runs/{run_id}/shots/{n}` | removes shot `n` with its files; the later shots move up |
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
  app/                  the hand holding the phone, previews, the drawn chat screens of texts shots
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
| `clip_sound`         | clips made with their own sound, lines taken from them (see Clip sound). Off unless switched on per video or in `config.local.yaml` |
| `assemble.caption_style` | caption style for new videos (see Caption styles); empty = the format's own |
| `app_screens`        | a format's own app screenshots (`path`, `shows`); every format also gets the whole library (see App screens) |
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

### Ready-made scripts

A format can ship scripts that are already written, shot by shot. A run made from one skips
the script step: Claude is not called, the script costs nothing, and you get the same video
every time apart from what the image and video models draw.

```bash
python main.py ready                                        # what is there, with the command for each
python main.py new --format pixar_steps --ready the_cactus  # make the video
python main.py new --format pixar_steps --ready the_cactus --dry-run   # only write script.json, to read or edit first
```

In the UI the create screen shows them in a **Story** card above the premise. Pick one and
the premise fills in; pick "Write my own" to go back to Claude writing it.

| Format          | Script           | Story                                                                    |
| --------------- | ---------------- | ------------------------------------------------------------------------ |
| `pixar_mirror`  | `the_standup`    | laughed at in the Monday meeting; six months later they bring him coffee |
| `pixar_mirror`  | `two_minute_fix` | sent to another table in a coffee shop; later she slides him the laptop   |
| `pixar_mirror`  | `the_wingman`    | she makes him her wingman at a party; later he makes her his              |
| `pixar_revenge` | `the_fountain`   | she says no at the fountain; two years later his car pulls up beside theirs |
| `pixar_ladder`  | `the_cafe`       | his cafe is dead; the app he builds for it fills the room                |
| `pixar_steps`   | `the_cactus`     | four steps to a first client, and the line he used is the last step      |

After the run is made it is an ordinary run: edit lines, swap app screens, redo shots and
recast voices on the run page as usual. App screens cannot be pinned on a ready-made script
(it already says which ones it shows), and the Claude Code engine does not use them.

To write your own, add `formats/<format>/scripts/<name>.json`:

```json
{
  "title": "The Monday meeting",
  "premise": "One or two sentences. Saved as the run's premise.",
  "shots": [
    {
      "characters": ["tyler"],
      "image_prompt": "close shot, chest up, a glass-walled meeting room, {tyler}, in a navy waistcoat, leaning back with a lazy smirk. Vertical composition, no text anywhere in the image.",
      "motion_prompt": "Tyler waves his hand without looking up, his mouth moving as he drawls the line. Slow push-in on his smirk.",
      "vo_line": "That's cute, Marcus.",
      "speaker": "tyler"
    },
    { "app_screen": "assets/screens/learn.jpg", "label": "OPENS IRO" }
  ]
}
```

It is the script schema above with three shortcuts. Leave the style line off `image_prompt`;
it is put in front. Write `{tyler}` (a locked character's id in braces) where the character's
description goes, and the format's own wording is filled in, so recasting a role does not
break the script. Leave out `n`, the top `characters` list and any field that would be empty.
The name is lower case letters, digits and underscores.

The built script goes through the same check as one Claude wrote, so a script that breaks the
format's rules (too few shots, too many words, a line that does not come back) is refused with
the reason, and `python main.py ready` only lists files it can read.

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
  in the grind, using a path from the app screen library (see App screens). An app_screen shot has no
  characters, no `vo_line`, `animate: false`, and is never the first or last shot. If no listed
  screenshot exists, none are asked for
- text messages go on the same phone with a `texts` shot (see Text messages on the phone): at
  most two in a script, no characters, no `vo_line`, never first or last. It sits on top of the
  story shots like the montage, so it does not use up the format's shot count
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

The sound is mixed in Python, not by ffmpeg. `audio_mix.py` has ffmpeg turn each sound into a
plain wav on its own (one file in, one file out), then puts the voice lines, the clips' own
sound, the effects and the music at their places and adds them up. One ffmpeg command with an
input per sound (forty or more in a fast cut) is the obvious way, and some Windows ffmpeg
builds stop in the middle of it and never finish; the same command takes under a second
elsewhere. Any ffmpeg command that has no progress to watch is also stopped, and named, if it
has not finished in ten minutes, so the final cut can no longer sit at 99%.

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
- An app screen with a recording plays it for its own length (see App screens); otherwise:
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

### Clip sound: the clips speak for themselves

By default a clip is silent: the picture moves, an ElevenLabs voice is laid over it afterwards,
and the mouth was animated without ever hearing the line, so lips and words do not match. With
**clip sound** on, the video model makes each clip together with its sound: a character says
the line with lips that match, a door slams when it shuts, feet are heard on the floor.

Switch it on for one video in the **Sound** choice on the create screen or the Sound panel on
its run page, or for every video in `config.local.yaml`:

```yaml
clip_sound:
  enabled: true
  level: 0.8       # how loud a shot's own sound plays when nobody speaks in it
  match: 0.7       # how much of a line must be heard in its clip (0-1) to use the clip's voice
```

What each step then does:

| step     | with clip sound                                                                    |
|----------|------------------------------------------------------------------------------------|
| video    | every clip is requested with sound. The prompt says who speaks, the line, and how the voice sounds (the character's `voice_style` in `format.yaml`, so it stays alike from shot to shot), and asks for the sound of the scene with no music. Nobody is named in it: characters are called by their look ("the man with slick blond hair"), because a model that makes sound says a name it reads |
| voice    | for a spoken shot, the words in its clip are found with ElevenLabs Speech to Text (one short call per shot). If they are the line, that stretch of the clip becomes the shot's voice file and the captions follow those words. A stray word before or after the line ("Marcus? I could do it with AI.") is cut off and named in the log; a word in the middle of the line cannot be cut and counts against the match. If the clip says something else, or nothing, the line is spoken by the ElevenLabs voice as before, and the log says so. Redoing the video of chosen shots, or rerolling one, reads their lines again by itself |
| assemble | a shot that speaks from its clip shows the same stretch of the clip, so sound and picture stay together. A shot where nobody speaks plays its clip's own sound under the cut |

Things to know:

- The voices are the video model's own, not the ElevenLabs voices in the Voices panel. Those are
  used only for lines a clip got wrong, lines over an app screen, and narration.
- The run page shows how many spoken shots use their clip's own voice. **Reroll** on one that
  does not gives the clip another try (a reroll then also reads the line again).
- Clips made before the switch stay silent. After switching a finished video over, redo its
  clips, then the voices, then assemble; the Sound panel offers the buttons.
- A line has to fit in the clip: a long line in a 4 second clip is rushed or cut off, and then
  falls back to the ElevenLabs voice.

### Text messages on the phone

The story ads this copies cut to the hero's phone when a text lands ("OMG TYLER JUST KISSED
ME", then "best wingman ever"). A `texts` shot does that:

```json
{ "texts": { "from": "Jess", "messages": ["OMG TYLER JUST KISSED ME <3", "best wingman ever"] } }
```

- `phone_texts.py` draws the chat screen itself (bundled Inter font), so every letter is right;
  the image model is never asked to write text. The assemble step puts it on the phone exactly
  as it does a real app screenshot: in the hero's hand when the format has `app_screen_hand`,
  else in the plain phone frame over the shot before it.
- One to three messages of at most 60 characters, from a name of at most 18. They arrive one at
  a time, a beat each (`assemble.texts_seconds`, 1.2), with a soft pop when sound effects are on.
  `<3` (or a heart emoji) is drawn as a red heart; other emoji are left out.
- No picture, clip or voice is generated for it, so it costs nothing. On the run page its card
  shows the screen straight away, and under Script and editing the name and each message are
  plain text boxes: change them, save, assemble again.
- Any format can use one in a ready-made script or by editing a script. The script prompts do
  not ask Claude for them yet.

### Sound effects

With `sfx: true` (Pixar Arc), the assemble step lays short effects under the voice. `sfx.py`
decides where from the cut itself:

| where                                   | sound                                      |
|-----------------------------------------|--------------------------------------------|
| a change of scene                       | `whoosh`, its loudest point on the cut     |
| a time-jump card                        | `impact`                                   |
| an app screen                           | `pop`                                      |
| a `texts` shot                          | `pop` as the phone lights up, and one for each later message |
| the first montage shot                  | `riser` that ends on the cut, then `impact` |
| every montage cut after it              | `swish` (a short whoosh)                   |
| every other cut between two drawn shots | a quieter `swish` (`sfx.cuts`, on by default) |

A change of scene is a drawn shot that does not carry `"same_scene": true`; a script with no
`same_scene` at all gets no scene whooshes. Cuts inside a conversation get the quieter swish,
the way fast-cut story ads do; `sfx: {cuts: false}` in `config.local.yaml` keeps them clean.
The whoosh and the swish are kept light and high: whatever ElevenLabs returns for them is
pitched up a little with its low end cut (your own files in `assets/sfx/` are never changed). Two scene
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
their story twice (about 45-55 seconds, 45-90 spoken words):

1. a small public brush-off, 5-7 lines, opening inside the scene on a line that makes sense by itself, with the line that stings by shot 3 or 4
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

### The other Pixar story shapes

Three more formats extend `pixar_arc` the same way `pixar_mirror` does. Each is one proven ad
template; pick whichever fits the premise.

| format | length | spoken words | where Iro appears |
|---|---|---|---|
| `pixar_mirror` | 45-55 s | 45-90 | the app in his hand, then three shots with his rank and a climbing number |
| `pixar_revenge` | 40-45 s | 20-45 | the app in his hand at the turn; Iro beside him through the flashes |
| `pixar_ladder` | 45-50 s | 45-90 | the app with `LEARNED IT ON IRO`, before the work |
| `pixar_steps` | 90-110 s | 160-250 | one of the spoken steps, said over the app |

The videos each one is modelled on (also listed in each `format.yaml` under `references` and
shown in the UI under Format details):

| format | reference videos |
|---|---|
| `pixar_mirror` | [RepStandard, the wingman](https://www.instagram.com/reel/DexjmDmBOw0/) · [RepStandard, the keys](https://www.instagram.com/reel/De79Dn5hIfg/) |
| `pixar_revenge` | [Paris proposal, 9.8M](https://www.instagram.com/reel/DeV-XBfgvTC/) · [the wedding, 4.6M](https://www.instagram.com/reel/DehudnaAmce/) |
| `pixar_ladder` | [the car detailer, 11M](https://www.instagram.com/reel/DeukYhBBTKE/) · [the barber, 7.1M](https://www.instagram.com/reel/De4oLmjgWld/) |
| `pixar_steps` | [Higgsfield, the yacht](https://www.instagram.com/reel/DfD0qcCMqJy/) · [Higgsfield, the airport](https://www.instagram.com/reel/DfYfGF6RLCq/) |

Two more were studied and are not a format yet:
[the five-day trading bet](https://www.instagram.com/reel/DdaDED9OrPj/) (one room, one argument,
a bet with a deadline) and [the ghost of your future](https://www.instagram.com/reel/De4IALIok-C/)
(an older self shows the hero three futures).

What a premise needs:

- `pixar_revenge`: where he is rejected and what she leaves him for. "Marcus proposes on a
  rooftop. Jess says no and leaves with Tyler in his sports car."
- `pixar_ladder`: the visible problem and who is arguing over it. "Jess and Tyler are fighting
  over their empty cafe and its ugly menu. Marcus says he can fix it with AI."
- `pixar_steps`: the rejection and the METHOD the steps teach. Name a real one; without it the
  script uses the three-part prompt from Iro's first lesson (a role, a goal, what good looks
  like). The steps never promise money.

**Flash shots.** `pixar_revenge` shows the grind as 8-12 shots with `"flash": true`: stills a
third of a second long (`timing.flash_seconds`), the hero in the centre of each while the room
behind him grows. They get a picture but never a clip, so they cost an image each. They must be
consecutive and in the middle of the story (`rules.flashes`). On the sound track a swish starts
the run, a riser builds through it and a hit lands on the shot after it.

**A line over the app screen.** With `rules.app_screen_voice: true` (`pixar_steps`), an
app-screen shot may carry a `vo_line` and a `speaker`. The shot then lasts as long as the line,
with the usual word captions over the phone, so "Step three. Open Iro..." is said over the real
app. In the UI, such a shot's line and speaker can be edited like any other.

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
