"""Script step: premise -> runs/<run_id>/script.json via the Claude Messages API."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import anthropic

from common import StepError, available_app_screens, read_premise, write_json
from format_loader import DEFAULT_FORMAT, load_format, render

SHOT_KEYS = {"n", "characters", "image_prompt", "motion_prompt", "vo_line",
             "speaker", "caption", "animate"}
OPTIONAL_SHOT_KEYS = {"card", "app_screen", "montage",   # card / app screenshot / flex montage
                      "letter", "talk",                    # a line of the letter / a lip-synced clip
                      "label",                             # a short tag on screen for the whole shot
                      "same_scene",                        # continues the previous shot's scene
                      "sfx",                               # a sound effect on the shot's first frame
                      "stat"}                              # progress overlay: {"rank", "value", "unit"}
LABEL_MAX_WORDS = 3
LETTER_MAX_WORDS = 40
SONG_STYLE_MAX = 300

# The story, the rules and the prompt text come from the video format (formats/<name>/).


def _format(fmt: dict | None) -> dict:
    return fmt if fmt is not None else load_format(DEFAULT_FORMAT)


# ---------------------------------------------------------------- prompt ----

def _cast_block(locked: list[dict]) -> str:
    lines = []
    for c in locked:
        role = c.get("role", "")
        role = f" ({role})" if role else ""
        lines.append(f'  - id "{c["id"]}"{role}: "{c["description"]}"')
        if c.get("outfit"):
            lines.append(f'      {c["id"]} ALWAYS dresses like this, in every scene (it replaces the '
                         f'outfit rules below for this character): {c["outfit"]}')
    return "\n".join(lines) if lines else "  (none)"


def _app_screens_block(screens: list[dict], fmt: dict | None = None) -> str:
    fmt = _format(fmt)
    blocks, prompt = fmt["blocks"], fmt["prompt"]
    where = f"formats/{fmt['name']}/blocks"
    if not screens:
        return render(blocks.get("no_app_screens", ""), {}, where) + "\n"
    lines = "\n".join(render(prompt["app_screen_line"],
                             {"PATH": e["path"], "SHOWS": e["shows"] or prompt["app_screen_unknown"]},
                             f"{fmt['file']}: prompt.app_screen_line") for e in screens)
    values = {"SCREEN_LIST": lines, "APP_SCREENS_MAX": fmt["rules"]["app_screens"]["max"]}
    return render(blocks.get("app_screens", ""), values, where) + "\n"


def prompt_values(fmt: dict) -> dict:
    """The format's rule numbers, as the prompt's {{NAME}} placeholders."""
    r = fmt["rules"]
    v = {"SHOT_MIN": r["story_shots"][0], "SHOT_MAX": r["story_shots"][1],
         "VO_WORDS_MIN": r["vo_words"][0], "VO_WORDS_MAX": r["vo_words"][1],
         "CTA_CAPTION": r["cta_caption"], "APP_SCREENS_MAX": r["app_screens"]["max"],
         "DIALOGUE_MIN": r.get("dialogue_lines_min", 0),
         "SILENT_RUN_MAX": r.get("silent_run_max", 0)}
    if r["montage"]:
        v["MONTAGE_MIN"], v["MONTAGE_MAX"] = r["montage"]["count"]
    if r.get("talking"):
        v["TALK_MAX"] = r["talking"]["max"]
    v["LETTER_MAX_WORDS"] = LETTER_MAX_WORDS
    v["LABEL_MAX_WORDS"] = r.get("label_max_words") or LABEL_MAX_WORDS
    v["MIRROR_MIN"] = r.get("mirror_lines_min", 0)
    if r.get("stats"):
        v["STAT_MIN"], v["STAT_MAX"] = r["stats"]["count"]
        v["STAT_RANKS"] = ", ".join(r["stats"]["ranks"])
        v["STAT_UNITS"] = ", ".join(f'"{u}"' for u in r["stats"]["units"])
    if r["cards"]:
        v["CARDS_MIN"], v["CARDS_MAX"] = r["cards"]["count"]
        v["CARD_WORDS_MIN"], v["CARD_WORDS_MAX"] = r["cards"]["words"]
    return v


SCENE_NOTE = """

SCENE CONTINUITY
Several shots in a row often show the same scene: the same place at the same moment, seen from
a new angle (a conversation, a reaction, an answer). On every such shot after the first, add
"same_scene": true. The picture for that shot is then drawn with the scene's first shot as a
visual reference, so the place, the light and everyone's clothes stay the same. In its
image_prompt, describe the place and each character's outfit in the SAME words as the scene's
first shot, and change only the framing and what the people do. Leave "same_scene" out on the
first shot of a scene, whenever the place or the time changes, and on montage shots."""


SFX_NOTE = """

SOUND EFFECTS
Changes of scene, time cards, app screens and the montage get their sound automatically. On top
of that, a shot may carry "sfx" for a moment that should LAND: "impact" when the shot opens on a
physical hit or a shock (a door slams, a phone hits the floor, someone snaps awake, a reveal
that drops a jaw), "pop" for a small light beat (a notification, a number ticking up, an idea).
Use it on at most {max} shots, and only where the picture shows the thing that makes the sound.
Most shots carry no "sfx"."""


def scene_anchor(shots: list[dict], i: int) -> int | None:
    """For shots[i] marked "same_scene", the index of the first shot of its scene: walk back
    over the shots it continues. App screenshots in between are cutaways and are skipped; a
    time card, a montage shot or the start of the list ends the scene (None)."""
    if not (0 <= i < len(shots)) or shots[i].get("same_scene") is not True:
        return None
    j = i - 1
    while j >= 0:
        s = shots[j]
        if not isinstance(s, dict) or s.get("card") or s.get("montage"):
            return None
        if s.get("app_screen") or not str(s.get("image_prompt") or "").strip():
            j -= 1
            continue
        if s.get("same_scene") is True:
            j -= 1
            continue
        return j
    return None


ANIMATE_ALL_NOTE = """

EVERY SHOT IS A VIDEO CLIP
This overrides any limit on "animate" above. Every shot that has an image_prompt becomes a
moving clip, montage shots included, so set "animate": true on all of them (card and app-screen
shots stay false). Each of those shots needs a motion_prompt that describes real movement for a
4 second clip, performance first and camera second: what each character does and how their
expression changes (steps back, turns away, throws up his hands, breaks into a grin, laughs,
slams the laptop shut), what moves around them (hair, clothes, traffic, a crowd, screens,
light), then one camera move that follows the action. A camera move alone is not enough: if
the only thing that moves is the camera, rewrite the shot so the people act. Never write
"static", "still", "frozen", "stands still" or "no movement"."""


def animates(shot: dict) -> bool:
    """With animate_all on, the shots that become clips: every drawn shot except talking shots
    (already clips) and letter shots (the picture is only a backdrop for the letter)."""
    return (isinstance(shot, dict) and not shot.get("card") and not shot.get("app_screen")
            and not shot.get("talk") and not shot.get("letter")
            and bool(str(shot.get("image_prompt") or "").strip()))


def apply_animate_all(script: dict | None, config: dict | None) -> int:
    """When the format (or config) says every shot is a clip, mark every drawn shot
    "animate": true. Changes `script` in place; returns how many shots it changed. Scripts
    written before the setting was on are brought up to date this way."""
    if not script or not (config or {}).get("animate_all"):
        return 0
    changed = 0
    for s in script.get("shots", []):
        if animates(s) and s.get("animate") is not True:
            s["animate"] = True
            if not str(s.get("motion_prompt") or "").strip():
                s["motion_prompt"] = "slow cinematic push in, subtle natural movement"
            changed += 1
    return changed


def build_system_prompt(style: str, max_animated: int, locked: list[dict],
                        app_screens: list[dict] | None = None, fmt: dict | None = None,
                        animate_all: bool = False, sfx: bool = False) -> str:
    """The format's script_prompt.md with shot_rules.md and the cast / app screens filled in."""
    fmt = _format(fmt)
    values = prompt_values(fmt)
    values.update({
        "STYLE": style,
        "MAX_ANIMATED": max_animated,
        "CAST": _cast_block(locked),
        "SPEAKERS": ", ".join(c["id"] for c in locked) or "the cast",
        "APP_SCREENS": _app_screens_block(app_screens or [], fmt)[:-1],
    })
    values["SHOT_RULES"] = render(fmt["shot_rules"], values, f"formats/{fmt['name']}/shot_rules.md")
    prompt = render(fmt["script_prompt"], values, f"formats/{fmt['name']}/script_prompt.md")
    # Letter formats use one backdrop for the whole video, so there are no scenes to keep.
    scenes = "" if (fmt.get("rules") or {}).get("letter") else SCENE_NOTE
    import sfx as sound
    effects = SFX_NOTE.format(max=sound.MAX_SHOT_SFX) if sfx and not (fmt.get("rules") or {}).get("song") else ""
    return prompt + scenes + (ANIMATE_ALL_NOTE if animate_all else "") + effects


def build_user_prompt(premise: str) -> str:
    return f"Premise:\n{premise.strip()}\n\nWrite the shot list JSON now."


# ------------------------------------------------------------ API client ----

def create_client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise StepError("ANTHROPIC_API_KEY is not set; put it in .env (see .env.example)")
    return anthropic.Anthropic()


def call_model(client: anthropic.Anthropic, model: str, max_tokens: int,
               system: str, messages: list, effort: str | None = None) -> anthropic.types.Message:
    """One Messages API request. Streams so long shot lists never hit HTTP timeouts.

    max_tokens covers the model's thinking as well as its answer (current models think before
    they write), so it needs room for both. `effort` (low | medium | high | xhigh | max) sets
    how much it thinks; None leaves the model's default."""
    extra = {"output_config": {"effort": effort}} if effort else {}
    try:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            **extra,
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
        raise StepError(f"the model's reply was cut off at max_tokens={max_tokens} (its thinking counts "
                        f"toward that limit too); raise script.max_tokens in config.local.yaml, or set "
                        f"script.effort: medium so it thinks less")
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


STAT_DIVISIONS = ("", "I", "II", "III")
STAT_VALUE_MAX = 9_999_999


def stat_rank(text, ranks: list[str]) -> tuple[int, str] | None:
    """(position in the format's rank ladder, tidy text) for a rank such as "gold ii", or None
    when it is not one of the format's ranks. A division (I, II, III) after the name is kept."""
    words = " ".join(str(text or "").upper().split())
    for i, name in enumerate(ranks):
        if words == name:
            return i, name
        if words.startswith(name + " ") and words[len(name) + 1:] in STAT_DIVISIONS[1:]:
            return i, words
    return None


def same_line_key(line) -> str:
    """A spoken line reduced to its words, for telling whether two lines are the same line."""
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", str(line or "").lower().replace("’", "'")).split())


def validate_and_normalize(data: dict, style: str, max_animated: int,
                           locked: list[dict] | None = None,
                           app_screens: list[dict] | None = None,
                           rules: dict | None = None, animate_all: bool = False) -> dict:
    """Raise ValueError listing every schema problem. Returns a normalized copy on success.

    animate_all: every drawn shot is a clip, so the cap on animated shots does not apply and
    every such shot comes back with "animate": true.

    `rules` are the format's (format.yaml `rules`); default: the default format's.
    Soft issues are fixed in place rather than failed: a missing style prefix on image_prompt
    is prepended, and captions are uppercased."""
    rules = rules if rules is not None else _format(None)["rules"]
    SHOT_MIN, SHOT_MAX = rules["story_shots"]
    VO_WORDS_MIN, VO_WORDS_MAX = rules["vo_words"]
    CTA_CAPTION = rules["cta_caption"]
    CAPTION_MAX_WORDS = rules["caption_max_words"]
    montage_rule, card_rule = rules["montage"], rules["cards"]
    APP_SCREENS_MAX, app_hint = rules["app_screens"]["max"], rules["app_screens"]["hint"]
    banned = rules["banned_image_prompt"]
    banned_vo = rules.get("banned_vo_line") or {"fix": "", "patterns": []}
    letter_rule, talk_rule, song_rule = rules.get("letter"), rules.get("talking"), rules.get("song")
    stat_rule = rules.get("stats")
    label_max = int(rules.get("label_max_words") or LABEL_MAX_WORDS)
    stats_seen: list[tuple[int, int, int]] = []      # (shot n, rank position, value)
    errors: list[str] = []
    locked = locked or []
    locked_desc = {c["id"]: c["description"] for c in locked}

    song = data.get("song")
    if song_rule:
        if not isinstance(song, dict) or not _is_str(song.get("style")) or not song["style"].strip():
            errors.append('this format is a song: add "song": {"style": "<genre, tempo, voice>"} at the top level')
        elif len(song["style"]) > SONG_STYLE_MAX:
            errors.append(f"song.style must be at most {SONG_STYLE_MAX} characters")
    elif song not in (None, {}):
        errors.append('this format has no song, so leave out "song"')

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
        elif cid in locked_desc and desc.strip() != locked_desc[cid]:
            errors.append(f"characters[{i}] ({cid}) description must match config word for word: "
                          f"{locked_desc[cid]!r}, got {desc.strip()!r}")
    id_set = set(ids)
    for cid in locked_desc:
        if cid not in id_set:
            errors.append(f"locked character {cid!r} is missing from 'characters'")

    montage_flags = [isinstance(x, dict) and x.get("montage") is True for x in shots]
    story_count = len(shots) - sum(montage_flags)
    if not (SHOT_MIN <= story_count <= SHOT_MAX):
        on_top = f" (the {montage_rule['name'].lower()} comes on top)" if montage_rule else ""
        errors.append(f"need {SHOT_MIN}-{SHOT_MAX} story shots{on_top}, got {story_count}")

    animated = 0
    talks = 0
    letter_bg_seen = False
    vo_words = 0
    cards = 0
    montage_idx: list[int] = []
    app_paths = [e["path"] for e in (app_screens or [])]
    app_shots = 0
    # Who may speak: the locked cast (or, with no locked cast, any character in the script),
    # plus a narrator voice when the format allows one (rules.narrator).
    speakers = set(locked_desc) or set(id_set)
    if rules["narrator"]:
        speakers = speakers | {"narrator"}
    normalized_shots = []
    for i, s in enumerate(shots):
        label = f"shots[{i}]"
        if not isinstance(s, dict):
            errors.append(f"{label} must be an object")
            continue
        missing = SHOT_KEYS - set(s)
        extra = set(s) - SHOT_KEYS - OPTIONAL_SHOT_KEYS
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
        card = s.get("card", "")
        if card is None:
            card = ""
        if not _is_str(card):
            errors.append(f"{label}.card must be a string, got {card!r}")
            card = ""
        card = card.strip()
        is_card = bool(card)
        montage = s.get("montage", False)
        if montage is None:
            montage = False
        if not isinstance(montage, bool):
            errors.append(f"{label}.montage must be true or false, got {montage!r}")
            montage = False
        is_montage = montage
        app = s.get("app_screen", "")
        if app is None:
            app = ""
        if not _is_str(app):
            errors.append(f"{label}.app_screen must be a string path, got {app!r}")
            app = ""
        app = app.strip()
        is_app = bool(app)
        if is_app:
            app_shots += 1
            if is_card:
                errors.append(f"{label} cannot be both a card and an app_screen shot")
            if app not in app_paths:
                errors.append(f"{label}.app_screen must be one of {app_paths or 'the configured app_screens (none available)'}, got {app!r}")
            if chars:
                errors.append(f"{label} is an app_screen shot, so characters must be [], got {chars!r}")
            if _is_str(s.get("vo_line")) and s["vo_line"].strip():
                errors.append(f"{label} is an app_screen shot, so vo_line must be empty")
            if s.get("animate") is True:
                errors.append(f"{label} is an app_screen shot, so animate must be false")
            if i == 0 or i == len(shots) - 1:
                errors.append(f"{label}: an app_screen shot cannot be the first or last shot")
        if is_montage:
            montage_idx.append(i)
            if not montage_rule:
                errors.append(f"{label}: this format has no montage, so leave out \"montage\"")
            if is_card or (_is_str(s.get("app_screen")) and s["app_screen"].strip()):
                errors.append(f"{label} cannot be both a montage shot and a card or app_screen shot")
            if _is_str(s.get("vo_line")) and s["vo_line"].strip():
                errors.append(f"{label} is a montage shot, so vo_line must be empty (no dialogue)")
        if is_card:
            cards += 1
            if not card_rule:
                errors.append(f"{label}: this format has no time-jump cards, so leave out \"card\"")
            elif not (card_rule["words"][0] <= len(card.split()) <= card_rule["words"][1]):
                errors.append(f"{label}.card must be {card_rule['words'][0]}-{card_rule['words'][1]} "
                              f"words, got {card!r}")
            if chars:
                errors.append(f"{label} is a card shot, so characters must be [], got {chars!r}")
            if _is_str(s.get("vo_line")) and s["vo_line"].strip():
                errors.append(f"{label} is a card shot, so vo_line must be empty")
            if s.get("animate") is True:
                errors.append(f"{label} is a card shot, so animate must be false")
            if i == 0 or i == len(shots) - 1:
                errors.append(f"{label}: a card cannot be the first or last shot")
        elif not is_app:
            letter = s.get("letter", "")
            letter = letter.strip() if _is_str(letter) else letter
            if letter not in ("", None) and not _is_str(letter):
                errors.append(f"{label}.letter must be a string")
                letter = ""
            letter = letter or ""
            if letter and not letter_rule:
                errors.append(f"{label}: this format has no letter, so leave out \"letter\"")
            if letter_rule and not is_montage:
                if not letter:
                    errors.append(f"{label}.letter must be this shot's line of the letter")
                elif len(letter.split()) > LETTER_MAX_WORDS:
                    errors.append(f"{label}.letter must be at most {LETTER_MAX_WORDS} words")
            reuse_bg = bool(letter) and _is_str(s.get("image_prompt")) and not s["image_prompt"].strip()
            if reuse_bg and not letter_bg_seen:
                errors.append(f"{label}.image_prompt must describe the background: it is the first "
                              f"letter shot with a picture")
            if letter and not reuse_bg:
                letter_bg_seen = True
            if reuse_bg and s.get("animate") is True:
                errors.append(f"{label} reuses the previous background (empty image_prompt), so "
                              f"animate must be false")
            for key in ("image_prompt", "motion_prompt"):
                if reuse_bg:
                    continue          # an empty image_prompt keeps the previous shot's picture
                if not _is_str(s.get(key)) or not s.get(key).strip():
                    errors.append(f"{label}.{key} must be a non-empty string")
            if _is_str(s.get("image_prompt")):
                ip = s["image_prompt"].lower()
                hits = [what for pat, what in banned["patterns"] if re.search(pat, ip)]
                if hits:
                    fix = f"; {banned['fix']}" if banned["fix"] else ""
                    errors.append(f"{label}.image_prompt must not describe the app ({', '.join(hits)})"
                                  f"{fix}")
        vo = s.get("vo_line")
        if not _is_str(vo):
            errors.append(f"{label}.vo_line must be a string (may be empty for silent shots)")
            vo = ""
        if not is_montage:                     # the montage never counts toward the word budget
            vo_words += len(vo.split())
        if vo.strip() and banned_vo["patterns"]:
            low = vo.lower()
            hits = [what for pat, what in banned_vo["patterns"] if re.search(pat, low)]
            if hits:
                fix = f"; {banned_vo['fix']}" if banned_vo["fix"] else ""
                errors.append(f"{label}.vo_line has {', '.join(hits)}: {vo.strip()!r}{fix}")
        speaker = s.get("speaker")
        if speaker == "narrator" and not rules["narrator"]:
            errors.append(f"{label}.speaker is 'narrator'; there is no narrator, every line is "
                          f"spoken by a character ({', '.join(sorted(speakers))})")
        elif vo.strip():
            if speaker not in speakers:
                errors.append(f"{label}.speaker must be the character who says the line, one of "
                              f"{sorted(speakers)}, got {speaker!r}")
        elif not _is_str(speaker) or (speaker and speaker not in id_set and speaker not in speakers):
            errors.append(f"{label}.speaker must be \"\" for a silent shot, got {speaker!r}")
        caption = s.get("caption")
        if not _is_str(caption):
            errors.append(f"{label}.caption must be a string (may be empty)")
        elif len(caption.split()) > CAPTION_MAX_WORDS and caption.strip().upper() != CTA_CAPTION:
            errors.append(f"{label}.caption must be 1-{CAPTION_MAX_WORDS} words or empty, got {caption!r}")
        tag = s.get("label", "")
        if tag is None:
            tag = ""
        if not _is_str(tag):
            errors.append(f"{label}.label must be a string, got {tag!r}")
            tag = ""
        tag = " ".join(tag.split())
        if tag:
            if not rules.get("labels"):
                errors.append(f"{label}: this format has no on-screen labels, so leave out \"label\"")
            elif is_card:
                errors.append(f"{label}: a card shot cannot carry a label")
            elif len(tag.split()) > label_max:
                errors.append(f"{label}.label must be at most {label_max} words, got {tag!r}")
        stat = s.get("stat")
        if stat in ({}, "", False):
            stat = None
        if stat is not None:
            if not stat_rule:
                errors.append(f"{label}: this format has no progress overlay, so leave out \"stat\"")
                stat = None
            elif is_card or is_app or is_montage:
                errors.append(f"{label}: a card, app screen or montage shot cannot carry \"stat\"")
                stat = None
            elif not isinstance(stat, dict) or set(stat) - {"rank", "value", "unit"}:
                errors.append(f"{label}.stat must be {{\"rank\": ..., \"value\": ..., \"unit\": ...}}, got {stat!r}")
                stat = None
            else:
                rank = stat_rank(stat.get("rank"), stat_rule["ranks"])
                value = stat.get("value")
                unit = " ".join(str(stat.get("unit") or "").upper().split())
                if rank is None:
                    errors.append(f"{label}.stat.rank must be one of {', '.join(stat_rule['ranks'])} "
                                  f"(optionally followed by I, II or III), got {stat.get('rank')!r}")
                if isinstance(value, bool) or not isinstance(value, int) or not (0 <= value <= STAT_VALUE_MAX):
                    errors.append(f"{label}.stat.value must be a whole number, got {value!r}")
                    value = None
                if unit not in stat_rule["units"]:
                    errors.append(f"{label}.stat.unit must be one of {', '.join(stat_rule['units'])}, got {stat.get('unit')!r}")
                if vo.strip():
                    errors.append(f"{label} carries \"stat\", so vo_line must be empty: the number does the talking")
                if rank is None or value is None or unit not in stat_rule["units"]:
                    stat = None
                else:
                    stat = {"rank": rank[1], "value": value, "unit": unit}
                    stats_seen.append((i + 1, rank[0], value))
        talk = s.get("talk", False)
        if talk is None:
            talk = False
        if not isinstance(talk, bool):
            errors.append(f"{label}.talk must be true or false, got {talk!r}")
            talk = False
        if talk:
            talks += 1
            if not talk_rule:
                errors.append(f"{label}: this format has no talking shots, so leave out \"talk\"")
            if is_card or is_app or is_montage:
                errors.append(f"{label}: a card, app screen or montage shot cannot talk")
            elif not vo.strip():
                errors.append(f"{label} has talk: true, so it needs a vo_line for the speaker to say")
            elif speaker == "narrator" or speaker not in id_set:
                errors.append(f"{label} has talk: true, so the speaker must be a character in the shot, "
                              f"got {speaker!r}")
            elif chars != [speaker]:
                errors.append(f"{label} has talk: true, so it shows only the speaker: \"characters\" "
                              f"must be [{speaker!r}], got {chars!r}")
        if song_rule and not (is_card or is_app or is_montage) and not vo.strip():
            errors.append(f"{label}.vo_line must be this shot's lyric line: in a song every shot is sung")
        if not isinstance(s.get("animate"), bool):
            errors.append(f"{label}.animate must be true or false")
        elif s["animate"] and not talk:
            animated += 1

        shot = dict(s)
        if is_app and not is_card:
            # Drawn by the assembly step from the real screenshot; nothing else on the shot is used.
            shot.update({"app_screen": app, "characters": [], "vo_line": "", "speaker": "",
                         "caption": "", "animate": False, "image_prompt": "", "motion_prompt": ""})
            for key in ("card", "letter", "talk", "label", "stat"):
                shot.pop(key, None)
            if tag and rules.get("labels"):
                shot["label"] = tag.upper()
            normalized_shots.append(shot)
            continue
        shot.pop("app_screen", None)
        if is_montage:
            shot["montage"] = True
        else:
            shot.pop("montage", None)
        if is_card:
            # A card is drawn by the assembly step; nothing else on the shot is used.
            shot.pop("letter", None)
            shot.pop("talk", None)
            shot.pop("label", None)
            shot.pop("stat", None)
            shot.update({"card": card.upper(), "characters": [], "vo_line": "", "speaker": "",
                         "caption": "", "animate": False,
                         "image_prompt": (s.get("image_prompt") or "").strip() if _is_str(s.get("image_prompt")) else "",
                         "motion_prompt": (s.get("motion_prompt") or "").strip() if _is_str(s.get("motion_prompt")) else ""})
        else:
            shot.pop("card", None)
            if _is_str(shot.get("image_prompt")) and shot["image_prompt"].strip():
                prompt = shot["image_prompt"].strip()
                if not prompt.lower().startswith(style.lower()):
                    prompt = f"{style}, {prompt}"
                shot["image_prompt"] = prompt
            elif _is_str(shot.get("image_prompt")):
                shot["image_prompt"] = ""
                shot["animate"] = False
                if _is_str(shot.get("motion_prompt")):
                    shot["motion_prompt"] = shot["motion_prompt"].strip()
            if _is_str(shot.get("letter")) and shot["letter"].strip() and not is_montage:
                shot["letter"] = " ".join(shot["letter"].split())
            else:
                shot.pop("letter", None)
            if shot.get("talk") is True:
                shot["talk"] = True
                shot["animate"] = False
            else:
                shot.pop("talk", None)
            if tag:
                shot["label"] = tag.upper()
            else:
                shot.pop("label", None)
            if _is_str(shot.get("caption")):
                shot["caption"] = shot["caption"].strip().upper()
            if stat:
                shot["stat"] = stat
                shot["caption"] = ""
            else:
                shot.pop("stat", None)
            if not vo.strip() and _is_str(shot.get("speaker")):
                shot["speaker"] = ""
            if is_montage:
                shot["caption"] = ""
        normalized_shots.append(shot)

    # "same_scene" stays only where there is a scene to continue (not on a scene's first shot,
    # a montage shot, a card or an app screenshot); anything else is quietly dropped.
    for i, shot in enumerate(normalized_shots):
        if "same_scene" not in shot:
            continue
        drawn = (not shot.get("card") and not shot.get("app_screen") and not shot.get("montage")
                 and bool(str(shot.get("image_prompt") or "").strip()))
        if shot.get("same_scene") is True and drawn and scene_anchor(normalized_shots, i) is not None:
            shot["same_scene"] = True
        else:
            shot.pop("same_scene")
    # "sfx" is a sound name or "none"; anything else is quietly dropped, and so are sounds past
    # the cap (a cut where every shot booms has no boom).
    import sfx as sound
    own = 0
    for shot in normalized_shots:
        if "sfx" not in shot:
            continue
        value = shot["sfx"].strip().lower() if _is_str(shot.get("sfx")) else ""
        if value in sound.NAMES and own < sound.MAX_SHOT_SFX:
            shot["sfx"] = value
            own += 1
        elif value == "none":
            shot["sfx"] = "none"
        else:
            shot.pop("sfx")
    if animate_all:
        for shot in normalized_shots:
            if animates(shot):
                shot["animate"] = True
    elif animated > max_animated:
        errors.append(f"at most {max_animated} shots may have animate: true, got {animated}")
    if talk_rule and talks > talk_rule["max"]:
        errors.append(f"at most {talk_rule['max']} shots may have talk: true, got {talks}")
    quiet_max = int(rules.get("silent_run_max") or 0)
    if quiet_max:
        # Story shots in a row with no line. A time card starts a new stretch, the montage is
        # silent by design, and an app screenshot is a cutaway that neither counts nor resets.
        run: list[int] = []
        worst: list[int] = []
        for s in normalized_shots:
            if s.get("card") or s.get("montage") or s.get("stat"):
                run = []                       # a progress shot is silent by design, like the montage
            elif s.get("app_screen"):
                continue
            elif str(s.get("vo_line") or "").strip():
                run = []
            else:
                run = run + [s.get("n")]
                if len(run) > len(worst):
                    worst = run
        if len(worst) > quiet_max:
            errors.append(f"shots {worst[0]}-{worst[-1]} are {len(worst)} story shots in a row with no "
                          f"line; at most {quiet_max} in a row may be silent, so the dialogue keeps "
                          f"telling the story")
    if stat_rule:
        lo, hi = stat_rule["count"]
        if not (lo <= len(stats_seen) <= hi):
            errors.append(f"use {lo}-{hi} progress shots with \"stat\" (the grind), got {len(stats_seen)}")
        for (n1, r1, v1), (n2, r2, v2) in zip(stats_seen, stats_seen[1:]):
            if v2 <= v1:
                errors.append(f"shot {n2}: stat.value must climb from shot to shot, got {v1} then {v2}")
            if r2 < r1:
                errors.append(f"shot {n2}: stat.rank must never drop below the rank on shot {n1}")
    mirror = int(rules.get("mirror_lines_min") or 0)
    if mirror:
        cards_at = [k for k, s in enumerate(normalized_shots) if s.get("card")]
        if cards_at:
            before = {same_line_key(s.get("vo_line")) for s in normalized_shots[:cards_at[-1]]} - {""}
            echoed = {same_line_key(s.get("vo_line")) for s in normalized_shots[cards_at[-1] + 1:]} & before
            if len(echoed) < mirror:
                errors.append(f"the scene after the time card must replay the opening scene: at least {mirror} "
                              f"of its lines repeat, word for word, a line said before the card "
                              f"(found {len(echoed)}: {sorted(echoed) or 'none'})")
    need = int(rules.get("dialogue_lines_min") or 0)
    if need:
        said = sum(1 for s in normalized_shots if str(s.get("vo_line") or "").strip()
                   and s.get("speaker") and s.get("speaker") != "narrator")
        if said < need:
            errors.append(f"at least {need} lines must be dialogue spoken by a character (the narrator "
                          f"tells the story, the characters speak its big moments), got {said}")
    if not (VO_WORDS_MIN <= vo_words <= VO_WORDS_MAX):
        errors.append(f"total vo_line words must be {VO_WORDS_MIN}-{VO_WORDS_MAX}, got {vo_words}")
    if not montage_rule:
        pass
    elif not montage_idx:
        MONTAGE_MIN, MONTAGE_MAX = montage_rule["count"]
        errors.append(f"add the {montage_rule['name']}: {MONTAGE_MIN}-{MONTAGE_MAX} shots with \"montage\": true "
                      f"right before the final CTA shot")
    else:
        MONTAGE_MIN, MONTAGE_MAX = montage_rule["count"]
        if not (MONTAGE_MIN <= len(montage_idx) <= MONTAGE_MAX):
            errors.append(f"the {montage_rule['name'].lower()} needs {MONTAGE_MIN}-{MONTAGE_MAX} shots, "
                          f"got {len(montage_idx)}")
        contiguous = montage_idx == list(range(montage_idx[0], montage_idx[-1] + 1))
        if not contiguous or montage_idx[-1] != len(shots) - 2:
            errors.append(f"the montage shots must be consecutive and come right before the final CTA "
                          f"shot; they are at shots {[i + 1 for i in montage_idx]} of {len(shots)}")
    if card_rule and not (card_rule["count"][0] <= cards <= card_rule["count"][1]):
        errors.append(f"use {card_rule['count'][0]}-{card_rule['count'][1]} time-jump card shots, got {cards}")
    if app_paths and APP_SCREENS_MAX and not (1 <= app_shots <= APP_SCREENS_MAX):
        hint = f" ({app_hint})" if app_hint else ""
        errors.append(f"use 1-{APP_SCREENS_MAX} app_screen shots{hint}, got {app_shots}")
    if app_paths and not APP_SCREENS_MAX and app_shots:
        errors.append(f"this format uses no app_screen shots, so remove the {app_shots} app_screen shot(s)")
    if not app_paths and app_shots:
        errors.append(f"no app screenshots are available, so remove the {app_shots} app_screen shot(s)")
    if normalized_shots and CTA_CAPTION:
        last = normalized_shots[-1]
        if last.get("caption") != CTA_CAPTION:
            errors.append(f"last shot caption must be {CTA_CAPTION!r}, got {last.get('caption')!r}")

    if errors:
        raise ValueError("\n".join(f"- {e}" for e in errors))

    out = {"characters": characters, "shots": normalized_shots}
    if song_rule:
        out["song"] = {"style": " ".join(song["style"].split())}
    return out


# ------------------------------------------------------------- reporting ----

def _clip(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def print_shot_table(script: dict, style: str) -> None:
    print("\ncharacters:")
    for c in script["characters"]:
        print(f"  {c['id']:<12} {c['description']}")

    animated = sum(1 for s in script["shots"] if s["animate"])
    vo_words = sum(len(s["vo_line"].split()) for s in script["shots"])
    print(f"\nshots: {len(script['shots'])}  animated: {animated}  vo words: {vo_words}\n")
    header = f"{'#':>2}  {'A':1}  {'speaker':<10} {'caption':<10} {'vo_line':<44} scene"
    print(header)
    print("-" * len(header) + "-" * 40)
    for s in script["shots"]:
        scene = s["image_prompt"]
        if scene.lower().startswith(style.lower()):
            scene = scene[len(style):].lstrip(" ,")
        if s.get("montage"):
            scene = f"[MONTAGE] {scene}"
        if s.get("card"):
            scene = f"[CARD] {s['card']}"
        elif s.get("app_screen"):
            scene = f"[APP] {s['app_screen']}"
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
    locked = config.get("locked_characters", [])
    fmt = config["format"]
    screens = available_app_screens(config)
    for e in config.get("app_screens", []):
        if e not in screens:
            print(f"[script] app screenshot {e['path']} is listed in config but missing; not offering it")
    client = client or create_client()

    animate_all = bool(config.get("animate_all"))
    import sfx as sound
    system = build_system_prompt(style, max_animated, locked, screens, fmt, animate_all=animate_all,
                                 sfx=sound.enabled(config))
    messages = [{"role": "user", "content": build_user_prompt(premise)}]

    last_error = None
    for attempt in (1, 2):
        print(f"[script] calling {model} (attempt {attempt}/2)...")
        response = call_model(client, model, max_tokens, system, messages,
                              effort=config["script"].get("effort") or None)
        text = response_text(response)
        try:
            return validate_and_normalize(parse_json(text), style, max_animated, locked, screens,
                                          fmt["rules"], animate_all=animate_all)
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
    print(f"[script] format: {config['format']['name']}")
    script = generate_script(premise, config)
    out = run_dir / "script.json"
    write_json(out, script)
    print(f"[script] saved {out}")
    print_shot_table(script, config["style"])
    cast_voices(run_dir, config, script)


def cast_voices(run_dir: Path, config: dict, script: dict) -> None:
    """A new script may have new people: drop the voices cast for the old one (your own picks
    stay) and cast again, so the run page shows who sounds like what before anything is spoken."""
    import voice_cast
    kept = {k: v for k, v in voice_cast.run_voices(run_dir).items() if v.get("source") == "manual"}
    if voice_cast.voices_path(run_dir).is_file():
        write_json(voice_cast.voices_path(run_dir), {"voices": kept})
    if os.environ.get("ELEVENLABS_API_KEY"):
        voice_cast.ensure_cast(run_dir, config, script)
