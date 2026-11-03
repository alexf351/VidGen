# VidGen

A Python CLI that turns a one-line story premise into a finished 9:16 animated short.
Each pipeline step writes its output to `runs/<run_id>/`, so any step can be re-run on its
own without redoing the others.

**Status:** scaffold + the `script` step are built. `images`, `video`, `voice` and `assemble`
print `not implemented yet` and exit cleanly.

## Setup

Requires Python 3.11.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in the keys
```

`.env` holds `ANTHROPIC_API_KEY`, `FAL_KEY` and `ELEVENLABS_API_KEY`. It is loaded with
python-dotenv and ignored by git.

## Usage

```bash
# create a run and execute every step in order
python main.py new "A laid-off line cook opens a food truck and nobody shows up on day one"

# re-run a single step on an existing run
python main.py step 20261103-201530-a-laid-off-line-cook script

# regenerate one shot's image + video
python main.py reroll 20261103-201530-a-laid-off-line-cook 7
```

Step names, in pipeline order: `script`, `images`, `video`, `voice`, `assemble`.

## Run layout

```
runs/<run_id>/
  premise.txt     the premise as given
  run.json        run metadata
  script.json     output of the script step
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
| `script.model`       | Claude model for the script step (`claude-sonnet-5-5`)         |
| `script.max_tokens`  | output cap for the script request                              |

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

Rules enforced by the prompt and checked by the validator:

- 15 to 22 shots, numbered from 1 with no gaps
- arc: doubter/setback, mentor, grind with a visible counter, win, payoff
- all characters are adults; each has one locked description sentence
- the style line opens every `image_prompt` (prepended if the model forgets)
- no more than `max_animated_shots` shots are `animate: true`, reserved for shots where motion is the beat
- `speaker` is `narrator` or a known character id; captions are at most two words

If the JSON is invalid or fails validation, the errors are sent back to the model and it gets
one retry. The result is saved to `runs/<run_id>/script.json` and printed as a shot table.
