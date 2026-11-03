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
| `locked_characters`  | recurring cast: `id`, `role`, `description`, `image_path`      |
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

### Story formula

Every script follows the same 10 beats in order: loss + diss (with a quoted insult),
rock bottom, mentor (Iro appears and the hero opens the Iro AI app), the bet, grind with a
climbing counter (streak days and Bronze/Silver/Gold/Diamond rank, at least one failure first),
overshoot win, flex, the ex returns, reversal ("i'm good", Iro says "that's my boy"), and a
closing CTA shot of the app with the caption `SEARCH IRO AI`.

The hero, love interest, rival and mentor come from `locked_characters` in `config.yaml` and
are reused by id with their descriptions copied word for word. Descriptions are physical identity
only; each image prompt adds a scene-fitting outfit (work clothes in setbacks, upgraded clothes in
wins). Jess leaves Marcus for Tyler in beat 1, and the insult comes from her or Tyler, never the
boss. Iro is always the penguin mascot.
New characters are only invented for minor roles. Setbacks are cold office light, wins are
golden hour. A real AI tool (Claude or ChatGPT) is named at least once.

### Validation

Rules enforced by the prompt and checked by the validator:

- 15 to 22 shots, numbered from 1 with no gaps
- every locked character is present and its description matches config exactly
- total `vo_line` words across the script is 90 to 130 (a 40-55 second video); shots may be silent
- the last shot's caption is exactly `SEARCH IRO AI`
- the style line opens every `image_prompt` (prepended if the model forgets)
- no more than `max_animated_shots` shots are `animate: true`, reserved for shots where motion is the beat
- `speaker` is `narrator` or a known character id; captions are at most two words (except the CTA)

If the JSON is invalid or fails validation, the errors are sent back to the model and it gets
one retry. The result is saved to `runs/<run_id>/script.json` and printed as a shot table.
