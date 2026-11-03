"""Script step: premise -> runs/<run_id>/script.json via the Claude Messages API."""

from __future__ import annotations

import json
import os
import re
import textwrap
from pathlib import Path

import anthropic

from common import StepError, read_premise, write_json

SHOT_MIN, SHOT_MAX = 15, 22
SHOT_KEYS = {"n", "characters", "image_prompt", "motion_prompt", "vo_line",
             "speaker", "caption", "animate"}


# ---------------------------------------------------------------- prompt ----

def build_system_prompt(style: str, max_animated: int) -> str:
    return textwrap.dedent(f"""\
        You write shot lists for short vertical (9:16) 3D-animated films. You answer with
        ONLY a single JSON object. No prose, no markdown, no code fences, nothing before or
        after the JSON.

        OUTPUT SCHEMA
        {{
          "characters": [
            {{"id": "marcus", "description": "<one sentence>"}}
          ],
          "shots": [
            {{
              "n": 1,
              "characters": ["marcus"],
              "image_prompt": "...",
              "motion_prompt": "...",
              "vo_line": "...",
              "speaker": "narrator",
              "caption": "",
              "animate": false
            }}
          ]
        }}

        CHARACTERS
        - Every character is clearly an adult (state an adult age range or adult role in the description).
        - "id" is a short lowercase slug. "description" is ONE locked sentence covering face, hair,
          build, clothing and one signature detail. That exact sentence, word for word, is pasted
          into the image_prompt of EVERY shot the character appears in. Never paraphrase it.

        SHOTS
        - Produce between {SHOT_MIN} and {SHOT_MAX} shots, numbered "n" from 1 upward with no gaps.
        - Story arc, in this order: a doubter or early setback -> a mentor appears -> a grind
          montage with a VISIBLE counter that climbs across several shots (a number on a
          whiteboard, a tally, a jar filling, a scoreboard, a day count) -> the win -> a payoff
          that calls back to the opening doubt.
        - "image_prompt" must begin with this exact style line, then a comma, then the scene:
          "{style}"
          After the style line: camera framing, setting, lighting, the locked description sentence
          of every character in the shot, what they are doing, and the visible counter value when
          one is in frame. Vertical composition. No text in the image except the counter.
        - "characters" lists the ids of every character visible in the shot (may be empty).
        - "motion_prompt" is one sentence describing the camera and subject motion for a 3-5
          second clip. Keep it short even for still shots (a slow push-in or drift is fine).
        - "vo_line" is the voice-over spoken during the shot: one or two spoken sentences,
          8-25 words, natural and punchy. "speaker" is "narrator" or a character id.
        - "caption" is either an empty string or ONE OR TWO WORDS IN ALL CAPS that hit the beat
          (examples: "DAY 1", "NO.", "AGAIN", "300 DOWN"). Use captions on roughly a third of shots.
        - "animate" is true for AT MOST {max_animated} shots. Reserve it for shots where motion IS
          the beat: vehicles moving, someone walking away, crowds, something thrown or dropped,
          a counter climbing, a door slamming. Dialogue close-ups and establishing shots stay false.

        Return only the JSON object.""")


def build_user_prompt(premise: str) -> str:
    return f"Premise:\n{premise.strip()}\n\nWrite the shot list JSON now."


# ------------------------------------------------------------ API client ----

def create_client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise StepError("ANTHROPIC_API_KEY is not set; put it in .env (see .env.example)")
    return anthropic.Anthropic()


def call_model(client: anthropic.Anthropic, model: str, max_tokens: int,
               system: str, messages: list) -> anthropic.types.Message:
    """One Messages API request. Streams so long shot lists never hit HTTP timeouts."""
    try:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        ) as stream:
            response = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise StepError(f"Anthropic rejected the API key: {e.message}") from e
    except anthropic.RateLimitError as e:
        raise StepError(f"Anthropic rate limit hit: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise StepError(f"Anthropic API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise StepError(f"could not reach the Anthropic API: {e}") from e

    if response.stop_reason == "refusal":
        detail = ""
        if response.stop_details:
            detail = f" ({response.stop_details.category}: {response.stop_details.explanation})"
        raise StepError(f"the model declined to write this script{detail}")
    if response.stop_reason == "max_tokens":
        raise StepError(f"response was cut off at max_tokens={max_tokens}; raise script.max_tokens in config.yaml")
    return response


def response_text(response) -> str:
    return "".join(block.text for block in response.content if block.type == "text")


# --------------------------------------------------------- parse/validate ----

def strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```[a-zA-Z0-9_-]*\s*\n(.*?)\n?```\s*$", text, flags=re.S)
    if m:
        return m.group(1).strip()
    # Fallback: take the outermost {...} if there is leading/trailing chatter.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    return text


def parse_json(text: str) -> dict:
    try:
        data = json.loads(strip_fences(text))
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e.msg} at line {e.lineno} col {e.colno}") from e
    if not isinstance(data, dict):
        raise ValueError("top level must be a JSON object")
    return data


def _is_str(v) -> bool:
    return isinstance(v, str)


def validate_and_normalize(data: dict, style: str, max_animated: int) -> dict:
    """Raise ValueError listing every schema problem. Returns a normalized copy on success.

    Soft issues are fixed in place rather than failed: a missing style prefix on image_prompt
    is prepended, and captions are uppercased."""
    errors: list[str] = []

    characters = data.get("characters")
    shots = data.get("shots")
    if not isinstance(characters, list):
        errors.append("'characters' must be a list")
        characters = []
    if not isinstance(shots, list):
        errors.append("'shots' must be a list")
        shots = []

    ids: list[str] = []
    for i, c in enumerate(characters):
        if not isinstance(c, dict):
            errors.append(f"characters[{i}] must be an object")
            continue
        cid, desc = c.get("id"), c.get("description")
        if not _is_str(cid) or not re.fullmatch(r"[a-z][a-z0-9_-]*", cid or ""):
            errors.append(f"characters[{i}].id must be a lowercase slug, got {cid!r}")
        elif cid in ids:
            errors.append(f"duplicate character id {cid!r}")
        else:
            ids.append(cid)
        if not _is_str(desc) or not desc.strip():
            errors.append(f"characters[{i}].description must be a non-empty sentence")
    id_set = set(ids)

    if not (SHOT_MIN <= len(shots) <= SHOT_MAX):
        errors.append(f"need {SHOT_MIN}-{SHOT_MAX} shots, got {len(shots)}")

    animated = 0
    normalized_shots = []
    for i, s in enumerate(shots):
        label = f"shots[{i}]"
        if not isinstance(s, dict):
            errors.append(f"{label} must be an object")
            continue
        missing = SHOT_KEYS - set(s)
        extra = set(s) - SHOT_KEYS
        if missing:
            errors.append(f"{label} missing keys: {sorted(missing)}")
        if extra:
            errors.append(f"{label} has unknown keys: {sorted(extra)}")
        if s.get("n") != i + 1:
            errors.append(f"{label}.n must be {i + 1}, got {s.get('n')!r}")
        chars = s.get("characters")
        if not isinstance(chars, list) or not all(_is_str(c) for c in chars):
            errors.append(f"{label}.characters must be a list of character ids")
        else:
            for c in chars:
                if c not in id_set:
                    errors.append(f"{label}.characters references unknown id {c!r}")
        for key in ("image_prompt", "motion_prompt", "vo_line"):
            if not _is_str(s.get(key)) or not s.get(key).strip():
                errors.append(f"{label}.{key} must be a non-empty string")
        speaker = s.get("speaker")
        if not _is_str(speaker) or (speaker != "narrator" and speaker not in id_set):
            errors.append(f"{label}.speaker must be 'narrator' or a character id, got {speaker!r}")
        caption = s.get("caption")
        if not _is_str(caption):
            errors.append(f"{label}.caption must be a string (may be empty)")
        elif len(caption.split()) > 2:
            errors.append(f"{label}.caption must be 1-2 words or empty, got {caption!r}")
        if not isinstance(s.get("animate"), bool):
            errors.append(f"{label}.animate must be true or false")
        elif s["animate"]:
            animated += 1

        shot = dict(s)
        if _is_str(shot.get("image_prompt")):
            prompt = shot["image_prompt"].strip()
            if not prompt.lower().startswith(style.lower()):
                prompt = f"{style}, {prompt}"
            shot["image_prompt"] = prompt
        if _is_str(shot.get("caption")):
            shot["caption"] = shot["caption"].strip().upper()
        normalized_shots.append(shot)

    if animated > max_animated:
        errors.append(f"at most {max_animated} shots may have animate: true, got {animated}")

    if errors:
        raise ValueError("\n".join(f"- {e}" for e in errors))

    return {"characters": characters, "shots": normalized_shots}


# ------------------------------------------------------------- reporting ----

def _clip(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def print_shot_table(script: dict, style: str) -> None:
    print("\ncharacters:")
    for c in script["characters"]:
        print(f"  {c['id']:<12} {c['description']}")

    animated = sum(1 for s in script["shots"] if s["animate"])
    print(f"\nshots: {len(script['shots'])}  animated: {animated}\n")
    header = f"{'#':>2}  {'A':1}  {'speaker':<10} {'caption':<10} {'vo_line':<44} scene"
    print(header)
    print("-" * len(header) + "-" * 40)
    for s in script["shots"]:
        scene = s["image_prompt"]
        if scene.lower().startswith(style.lower()):
            scene = scene[len(style):].lstrip(" ,")
        print(f"{s['n']:>2}  {'*' if s['animate'] else ' '}  "
              f"{_clip(s['speaker'], 10):<10} {_clip(s['caption'], 10):<10} "
              f"{_clip(s['vo_line'], 44):<44} {_clip(scene, 40)}")
    print("\n(A = animate)")


# ------------------------------------------------------------------- run ----

def generate_script(premise: str, config: dict, client=None) -> dict:
    style = config["style"]
    max_animated = int(config["max_animated_shots"])
    model = config["script"]["model"]
    max_tokens = int(config["script"]["max_tokens"])
    client = client or create_client()

    system = build_system_prompt(style, max_animated)
    messages = [{"role": "user", "content": build_user_prompt(premise)}]

    last_error = None
    for attempt in (1, 2):
        print(f"[script] calling {model} (attempt {attempt}/2)...")
        response = call_model(client, model, max_tokens, system, messages)
        text = response_text(response)
        try:
            return validate_and_normalize(parse_json(text), style, max_animated)
        except ValueError as e:
            last_error = e
            print(f"[script] attempt {attempt} failed validation:\n{e}")
            if attempt == 1:
                # Feed the failure back so the retry can correct it.
                messages = messages + [
                    {"role": "assistant", "content": response.content},
                    {"role": "user", "content":
                        "That output failed validation:\n"
                        f"{e}\n\n"
                        "Return the corrected shot list as ONLY a JSON object that follows the "
                        "schema exactly. No fences, no commentary."},
                ]
    raise StepError(f"script JSON still invalid after 2 attempts:\n{last_error}")


def run(run_dir: Path, config: dict) -> None:
    premise = read_premise(run_dir)
    print(f"[script] premise: {premise}")
    script = generate_script(premise, config)
    out = run_dir / "script.json"
    write_json(out, script)
    print(f"[script] saved {out}")
    print_shot_table(script, config["style"])
