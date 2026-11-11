# Recording the app for moving screens

The recordings in `assets/screens/*.mp4` were made here, from the Iro app's own web build.
Nothing in VidGen needs this folder to run; it is kept so the clips can be re-made when the
app changes.

How it works: `record.js` serves the app's dev web export, opens a screen at phone size and
pauses the clock before the page loads. It then moves the clock forward one video frame at a
time and takes a screenshot after each step. The app's animations run on that clock, so every
frame is fully drawn and the result is smooth at 30 frames a second on any machine.
`encode_clip.py` turns the frames into a small silent MP4 with a real iOS status bar on top.

Two things do not record: loops the app plays as animated images (the mascot's small
movements, the 3D chest lid) are swapped for their still pictures, because they run on the
real clock; and nothing that needs the server (sign-in, live AI replies).

## Setup, once

```bash
# in the Iro app repo
npm install
EXPO_PUBLIC_SUPABASE_URL=https://placeholder.supabase.co \
EXPO_PUBLIC_SUPABASE_ANON_KEY=placeholder-anon-key-for-headless-qa \
CI=1 npx expo export --platform web --dev --output-dir /tmp/iro-capture-web

# the recorder's own packages, kept out of both repos
mkdir -p /tmp/iro-capture-deps && cd /tmp/iro-capture-deps && npm init -y && \
  npm i playwright-core@1.56 @fontsource/inter @fontsource/noto-sans-sc
```

`record.js` reads `CAPTURE_WEB` (the export, default `/tmp/iro-capture-web`), `CAPTURE_DEPS`
(default `/tmp/iro-capture-deps`), `IRO_REPO` (the app repo, for the still posters), `CHROME`
(a Chromium binary, if Playwright's own is not installed) and `SEED` (JSON merged into the
app's saved state: XP, streak and so on).

## Record and encode

```bash
export IRO_REPO=/path/to/kiro-app
node record.js /tmp/rec streak "/dev-reward-rail?beat=streak&scenario=day%204%E2%86%925" \
  '{"boot":"stepped","ready":"day streak","ms":4000}'
python encode_clip.py /tmp/rec/streak ../../assets/screens/streak.mp4 --start 6 --hold 0.4
```

The job (the last argument) says what to record:

| key | meaning |
|---|---|
| `boot` | `"stepped"`: pause the clock before the page loads, so a screen's own entrance is caught from its first frame |
| `ready` | text that must be on screen before recording starts |
| `lead` | milliseconds to let pass after that, before the first frame (a typewriter finishing, say) |
| `ms` | how long to record |
| `actions` | taps during the recording: `{"at": 900, "tap": "exact text"}`, `{"at": 500, "tapLabel": "aria label"}` or `{"at": 2000, "tapXY": [212, 734]}` |
| `splash` | `true` keeps the app's boot splash in (the opening clip); otherwise it is hidden |
| `hideText` | exact labels of dev-only buttons to hide |
| `css` | extra CSS, for example `[aria-modal="true"]{display:none !important}` to keep pop-ups out |

`encode_clip.py` takes `--start` and `--end` (frame numbers), `--speed` (1.2 plays it a fifth
faster) and `--hold` (seconds to hold the last frame). Keep clips to about 4 to 5 seconds:
VidGen plays at most `assemble.app_clip_max_seconds` (6).

## The clips that ship

| clip | route | job | encode |
|---|---|---|---|
| `building` | `/building?outcome=work_smarter&experience=daily` | `{"boot":"stepped","ready":"%","ms":5600}` | `--start 2 --speed 1.2 --hold 0.3` |
| `first_rank` | `/dev-rank-emblems?mode=reveal` | `{"boot":"stepped","ready":"BRONZE","ms":4500}` | `--start 8` |
| `learn` | `/dev-screenshots?locale=en&scene=learn` | `{"boot":"stepped","splash":true,"ready":"Iro AI","ms":5600,"css":"[aria-modal=\"true\"]{display:none !important}"}` | `--start 45 --hold 0.5` |
| `correct` | `/lesson?pathId=foundations&lessonId=f1&skipLoading=true&startExercise=0` | `{"boot":"stepped","ready":"Finds patterns in data","lead":1500,"ms":4000,"actions":[{"at":900,"tap":"Finds patterns in data and makes predictions"}]}` | `--start 14 --hold 0.3` |
| `lesson` | `/dev-image-match` | stepped, `ready` "Perplexity", `lead` 1200, `ms` 5600, `hideText` the three dev buttons, eight taps 500 to 600 ms apart (tool, then its match) | `--start 4 --speed 1.2 --hold 0.3` |
| `lesson_done` | `/dev-reward-rail?beat=xp_hero&scenario=perfect` | `{"boot":"stepped","ready":"Locked it in","ms":9000}` | `--start 24 --end 215 --speed 1.5` |
| `streak` | `/dev-reward-rail?beat=streak&scenario=day 4→5` | `{"boot":"stepped","ready":"day streak","ms":4000}` | `--start 6 --hold 0.4` |
| `reward` | `/dev-reward-rail?beat=chest&scenario=legendary` | stepped, `ready` "cache", `lead` 900, `ms` 8000, four `tapLabel` "cache" taps at 500, 1100, 1700, 2400 | `--start 4 --end 205 --speed 1.5` |
| `rank_up` | `/dev-rank-emblems?mode=rankup&from=silver&to=gold` | `{"boot":"stepped","ready":"GOLD","ms":5500}` | `--start 6` |
| `unit_done` | `/dev-unit-complete?path=claude&unit=1` | `{"boot":"stepped","ready":"Claude","ms":4000}` | `--start 8` |
| `after_lesson` | `/dev-reward-rail?beat=progress&scenario=division step&league=up` | `{"boot":"stepped","ready":"YOUR PROGRESS","ms":6000}` | `--start 10 --end 130` |
| `create` | `/create` | `{"boot":"stepped","ready":"Create","lead":300,"ms":6000}` | `--start 10 --speed 1.2` |

The seed used for all of them: `{"xp":4600,"streak":45,"streakBest":45,"gems":1517,
"lastLessonDay":"<today>","lastPathId":"foundations","recommendedPathId":"foundations",
"whatsNewSeenVersion":"99.0","completed":[the first sixteen foundations lessons]}`.

A clip's picture (`<name>.jpg`) is separate: the stills came from the app's own screenshot
tool (`scripts/i18n/intro-shots` in the Iro repo). For a new clip with no still, take a
settled frame from the recording and save it as an 860 x 1864 JPEG with the same name.
