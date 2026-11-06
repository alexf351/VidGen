"""Script step: premise -> runs/<run_id>/script.json via the Claude Messages API."""

from __future__ import annotations

import json
import os
import re
import textwrap
from pathlib import Path

import anthropic

from common import StepError, available_app_screens, read_premise, write_json

SHOT_MIN, SHOT_MAX = 15, 22
VO_WORDS_MIN, VO_WORDS_MAX = 60, 100   # total spoken words across all shots
CTA_CAPTION = "SEARCH IRO AI"          # required caption on the final shot
SHOT_KEYS = {"n", "characters", "image_prompt", "motion_prompt", "vo_line",
             "speaker", "caption", "animate"}
OPTIONAL_SHOT_KEYS = {"card", "app_screen", "montage"}   # card / app screenshot / flex montage
MONTAGE_MIN, MONTAGE_MAX = 6, 8        # flex montage shots, right before the CTA
APP_SCREENS_MAX = 2
# Wording that asks the image model to draw the Iro app. The mascot's own name is fine.
APP_UI_PATTERNS = [
    (r"\biro\s*ai\b", "the app name 'Iro AI'"), (r"\biro\s+app\b", "'Iro app'"),
    (r"\bapp('s)?\s+(ui|interface|screen|logo|icon|name|home ?screen|menu|dashboard)\b", "app UI"),
    (r"\buser interface\b", "'user interface'"), (r"\bui\b", "'UI'"), (r"\blogos?\b", "a logo"),
    (r"\bscreen\s+(shows|showing|displays|displaying|reads|reading)\b", "what a screen shows"),
]
CARDS_MIN, CARDS_MAX = 1, 3
CARD_WORDS_MAX = 4


# ---------------------------------------------------------------- prompt ----

def _cast_block(locked: list[dict]) -> str:
    lines = []
    for c in locked:
        role = c.get("role", "")
        role = f" ({role})" if role else ""
        lines.append(f'  - id "{c["id"]}"{role}: "{c["description"]}"')
    return "\n".join(lines) if lines else "  (none)"


def _app_screens_block(screens: list[dict]) -> str:
    if not screens:
        return ("        - No real app screenshots are available, so do not add any \"app_screen\" "
                "shots.\n")
    lines = "\n".join(f'            * "{e["path"]}": {e["shows"] or "an Iro app screen"}' for e in screens)
    return (
        "        - The real app is shown with app screen shots, which put a real screenshot in a\n"
        "          phone mockup. Add exactly one app screen shot RIGHT AFTER the hero opens the app\n"
        f"          in the mentor beat, and optionally one more during the grind (at most {APP_SCREENS_MAX}).\n"
        "          Pick the screenshot whose content fits the moment, using its exact path:\n"
        f"{lines}\n"
        '        - An app screen shot has "app_screen": "<path>", "characters": [],\n'
        '          "image_prompt": "", "motion_prompt": "", "vo_line": "", "speaker": "",\n'
        '          "caption": "", "animate": false. It is never the first or last shot, and it counts\n'
        "          toward the shot total.\n")


def build_system_prompt(style: str, max_animated: int, locked: list[dict],
                        app_screens: list[dict] | None = None) -> str:
    return textwrap.dedent(f"""\
        You write shot lists for short vertical (9:16) 3D-animated films that advertise the
        Iro AI app. You answer with ONLY a single JSON object. No prose, no markdown, no code
        fences, nothing before or after the JSON.

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
              "speaker": "marcus",
              "caption": "",
              "animate": false
            }},
            {{
              "n": 6,
              "card": "6 MONTHS LATER",
              "characters": [],
              "image_prompt": "",
              "motion_prompt": "",
              "vo_line": "",
              "speaker": "",
              "caption": "",
              "animate": false
            }}
          ]
        }}
        "card" appears ONLY on time-jump card shots and "app_screen" ONLY on app screen shots;
        leave both out of every other shot.

        LOCKED CAST
        These characters are fixed. Reuse their ids and copy their descriptions WORD FOR WORD
        into the "characters" list, and paste the description into the image_prompt of every
        shot they appear in. Never paraphrase, shorten or extend them.
        {{CAST}}
        - The locked description is physical IDENTITY only (face, hair, skin, build). It
          contains no clothing. In every image_prompt, write the identity word for word, then
          add an outfit that fits the scene:
            * Setback / office scenes: work clothes. Marcus wears a white button-down shirt
              and a blue company lanyard.
            * Win scenes: upgraded clothes. Fitted black tee, sunglasses, a watch, a nice
              jacket.
          Keep each character's outfit consistent across every shot in the same scene or
          location; change it only when the scene changes.
        - The hero is the locked hero. The love interest / ex is the locked love interest.
          The rival / doubter is the locked rival. The mentor is ALWAYS Iro, the penguin mascot.
          Never invent a new mentor and never make Iro human.
        - The boss is ALWAYS the locked boss (id "boss") and the new partner in the reversal
          is ALWAYS the locked sofia (id "sofia"). Never invent a different boss or partner.
        - You may invent extra characters only for background roles (onlookers, a crowd, a
          coworker with no lines). Every character is clearly an adult, mid-20s or older, with
          an adult age stated in the description. The hero is young, attractive and
          aspirational, never tired or frumpy. Background characters also get one locked
          sentence each.

        STORY FORMULA
        Every script follows these 11 beats, in this order. Spread beats 1-9 and 11 across
        {SHOT_MIN}-{SHOT_MAX} story shots; the {MONTAGE_MIN}-{MONTAGE_MAX} flex montage shots of beat 10
        come on top of that. Number every shot "n" from 1 upward with no gaps.
          1. LOSS + DISS: the love interest leaves the hero FOR the rival. Show her getting
             into the rival's car or walking off with him in this beat. The hero is also
             rejected or fired. Must include a quoted direct insult ("loser" or equivalent) as a
             vo_line spoken by the love interest or the rival. The boss NEVER insults him; the
             boss only delivers the firing.
          2. ROCK BOTTOM: the hero alone and humiliated, others laughing at him or filming him.
          3. MENTOR: Iro appears and tells him to lock in. In this same beat the hero opens the
             app on his phone and starts his first lesson.
          4. THE BET: the doubter raises the stakes; the hero answers with a time-bound
             challenge (for example "give me 30 days").
          5. GRIND + COUNTER: 3-4 shots with a floating on-screen counter that climbs. The
             counter is streak days and AI rank (Bronze -> Silver -> Gold -> Diamond), or money
             (monthly revenue, clients signed), or both. Show at least one failure before the
             progress. Put the current counter value in each image_prompt. As the hero levels
             up, the work setting upgrades shot by shot: dark apartment -> modern office ->
             rooftop at sunset -> luxury villa.
          6. OVERSHOOT WIN: the result smashes the goal (for example a promotion plus a salary
             number far above what anyone expected).
          7. FLEX: luxury car, a nice city or beach setting, warm golden light.
          8. EX RETURNS: the person who left sees his success and wants him back.
          9. REVERSAL: the hero declines ("i'm good"), is with sofia, his new partner, and
             Iro approves ("that's my boy").
         10. FLEX MONTAGE: {MONTAGE_MIN}-{MONTAGE_MAX} rapid shots of the hero living the life (see FLEX
             MONTAGE below), right after the reversal and right before the CTA.
         11. CTA: the final shot is the hero (or Iro) holding up the phone with its BACK toward
             the camera, the screen glow on their face, caption exactly "{CTA_CAPTION}".

        TONE AND LOOK
        - Setback scenes (beats 1-4): office, cold or dim lighting, grey and blue tones.
        - Win scenes (beats 6-9): sunsets, beaches, parties, warm golden light.
        - Name a real AI tool (Claude or ChatGPT) at least once, usually in the rival's or the
          boss's line (for example the rival bragging that he "just lets ChatGPT do it").
        - Whenever the hero uses AI, show it cinematically: glowing holographic screens and
          dashboards floating around him, multiple monitors, notification cards floating in the
          air around him ("payment received", "new client"), never on a phone screen. After the
          mentor beat, never show a plain laptop on a desk.

        SHOT FIELDS
        - "image_prompt" must begin with this exact style line, then a comma, then the scene:
          "{style}"
          After the style line: camera framing, setting, lighting, then for every character in
          the shot the locked identity word for word followed by their outfit for this scene,
          what they are doing, and the counter value when one is in frame. Vertical
          composition. No text in the image except the counter.
        - "characters" lists the ids of every character visible in the shot (may be empty).
        - "motion_prompt" is one sentence of camera and subject motion for a 3-5 second clip.
          Keep it short even for still shots (a slow push-in or drift is fine).
        - "vo_line" is a line of dialogue spoken by one of the cast: {{SPEAKERS}}.
          There is NO narrator: no voice-over that describes events, explains the story or
          talks about the hero in the third person. Every spoken line is a character talking.
          Shots with no dialogue have "vo_line": "" and let the visual carry the beat; MOST
          shots should be silent. Spoken lines are short, usually 2-8 words. The TOTAL word
          count of all vo_lines across the script must be {VO_WORDS_MIN}-{VO_WORDS_MAX} words.
          Count before you answer.
        - "speaker" is the id of the character who speaks the vo_line (one of {{SPEAKERS}}),
          or "" when vo_line is "". Never "narrator".
        - "caption" is "" or ONE OR TWO WORDS IN ALL CAPS that hit the beat ("LOSER", "DAY 1",
          "DIAMOND", "I'M GOOD"). The only three-word caption allowed is "{CTA_CAPTION}" on the
          last shot.
        - "animate" is true for AT MOST {max_animated} shots. Reserve it for shots where motion
          IS the beat: a car pulling away, someone walking out, a crowd, a thrown phone, the
          counter climbing, a door slamming. Dialogue close-ups and establishing shots stay false.

        THE APP ON SCREEN
        - The image model must never draw the app. Whenever a character uses the app (or any
          phone), the image_prompt shows the BACK of the phone toward the camera, with the
          screen's glow lighting their face. Never describe the app's UI, what a phone screen
          shows, menus, buttons, logos or the words "Iro AI" in any image_prompt.
{{APP_SCREENS}}
        FLEX MONTAGE
        - Right after the reversal ("that's my boy") and right before the final CTA shot, add
          {MONTAGE_MIN}-{MONTAGE_MAX} consecutive montage shots of the hero living the life, each one a
          single striking image, about half a second on screen. Pick from: the luxury car, a
          watch close-up on his wrist, him in a sharp suit outside a glass tower, a rooftop at
          night over the city, holographic AI dashboards around him with Iro, a private jet,
          a beach sunset with sofia; the LAST montage shot is always a final smirk at camera.
        - Every montage shot has "montage": true, "vo_line": "", "speaker": "", "caption": ""
          and "animate": false. No dialogue. Upgraded outfits, warm golden-hour or neon-night
          lighting. Write image_prompt and motion_prompt as for any other shot, with the
          locked identity of everyone in frame.
        - "montage" appears ONLY on these shots.

        TIME-JUMP CARDS
        - Use {CARDS_MIN}-{CARDS_MAX} time-jump card shots per video, at the natural jumps in time:
          after rock bottom, during the grind (between counter shots), and before the payoff.
        - A card shot is a black screen with white text. Give it "card": a short span of time
          in ALL CAPS, 2-{CARD_WORDS_MAX} words ("30 DAYS LATER", "6 MONTHS LATER",
          "2 YEARS LATER"), and "characters": [], "image_prompt": "", "motion_prompt": "",
          "vo_line": "", "speaker": "", "caption": "", "animate": false.
        - Card times must fit the story: they never contradict the hero's bet (a "give me 30
          days" grind can show "2 WEEKS LATER", not "2 YEARS LATER"). A card is never the first
          or the last shot, and cards count toward the {SHOT_MIN}-{SHOT_MAX} shots.

        Return only the JSON object.""").replace("{CAST}", _cast_block(locked)) \
        .replace("{SPEAKERS}", ", ".join(c["id"] for c in locked) or "the cast") \
        .replace("{APP_SCREENS}", _app_screens_block(app_screens or []))


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


def validate_and_normalize(data: dict, style: str, max_animated: int,
                           locked: list[dict] | None = None,
                           app_screens: list[dict] | None = None) -> dict:
    """Raise ValueError listing every schema problem. Returns a normalized copy on success.

    Soft issues are fixed in place rather than failed: a missing style prefix on image_prompt
    is prepended, and captions are uppercased."""
    errors: list[str] = []
    locked = locked or []
    locked_desc = {c["id"]: c["description"] for c in locked}

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
        errors.append(f"need {SHOT_MIN}-{SHOT_MAX} story shots (the flex montage comes on top), "
                      f"got {story_count}")

    animated = 0
    vo_words = 0
    cards = 0
    montage_idx: list[int] = []
    app_paths = [e["path"] for e in (app_screens or [])]
    app_shots = 0
    # Who may speak: the locked cast (or, with no locked cast, any character in the script).
    speakers = set(locked_desc) or set(id_set)
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
            if is_card or (_is_str(s.get("app_screen")) and s["app_screen"].strip()):
                errors.append(f"{label} cannot be both a montage shot and a card or app_screen shot")
            if _is_str(s.get("vo_line")) and s["vo_line"].strip():
                errors.append(f"{label} is a montage shot, so vo_line must be empty (no dialogue)")
        if is_card:
            cards += 1
            if not (2 <= len(card.split()) <= CARD_WORDS_MAX):
                errors.append(f"{label}.card must be 2-{CARD_WORDS_MAX} words, got {card!r}")
            if chars:
                errors.append(f"{label} is a card shot, so characters must be [], got {chars!r}")
            if _is_str(s.get("vo_line")) and s["vo_line"].strip():
                errors.append(f"{label} is a card shot, so vo_line must be empty")
            if s.get("animate") is True:
                errors.append(f"{label} is a card shot, so animate must be false")
            if i == 0 or i == len(shots) - 1:
                errors.append(f"{label}: a card cannot be the first or last shot")
        elif not is_app:
            for key in ("image_prompt", "motion_prompt"):
                if not _is_str(s.get(key)) or not s.get(key).strip():
                    errors.append(f"{label}.{key} must be a non-empty string")
            if _is_str(s.get("image_prompt")):
                ip = s["image_prompt"].lower()
                hits = [what for pat, what in APP_UI_PATTERNS if re.search(pat, ip)]
                if hits:
                    errors.append(f"{label}.image_prompt must not describe the app ({', '.join(hits)}); "
                                  f"show the back of the phone with the screen glow on their face")
        vo = s.get("vo_line")
        if not _is_str(vo):
            errors.append(f"{label}.vo_line must be a string (may be empty for silent shots)")
            vo = ""
        if not is_montage:                     # the montage never counts toward the word budget
            vo_words += len(vo.split())
        speaker = s.get("speaker")
        if speaker == "narrator":
            errors.append(f"{label}.speaker is 'narrator'; there is no narrator, every line is "
                          f"spoken by a character ({', '.join(sorted(speakers))})")
        elif vo.strip():
            if speaker not in speakers:
                errors.append(f"{label}.speaker must be the character who says the line, one of "
                              f"{sorted(speakers)}, got {speaker!r}")
        elif not _is_str(speaker) or (speaker and speaker not in id_set):
            errors.append(f"{label}.speaker must be \"\" for a silent shot, got {speaker!r}")
        caption = s.get("caption")
        if not _is_str(caption):
            errors.append(f"{label}.caption must be a string (may be empty)")
        elif len(caption.split()) > 2 and caption.strip().upper() != CTA_CAPTION:
            errors.append(f"{label}.caption must be 1-2 words or empty, got {caption!r}")
        if not isinstance(s.get("animate"), bool):
            errors.append(f"{label}.animate must be true or false")
        elif s["animate"]:
            animated += 1

        shot = dict(s)
        if is_app and not is_card:
            # Drawn by the assembly step from the real screenshot; nothing else on the shot is used.
            shot.update({"app_screen": app, "characters": [], "vo_line": "", "speaker": "",
                         "caption": "", "animate": False, "image_prompt": "", "motion_prompt": ""})
            shot.pop("card", None)
            normalized_shots.append(shot)
            continue
        shot.pop("app_screen", None)
        if is_montage:
            shot["montage"] = True
        else:
            shot.pop("montage", None)
        if is_card:
            # A card is drawn by the assembly step; nothing else on the shot is used.
            shot.update({"card": card.upper(), "characters": [], "vo_line": "", "speaker": "",
                         "caption": "", "animate": False,
                         "image_prompt": (s.get("image_prompt") or "").strip() if _is_str(s.get("image_prompt")) else "",
                         "motion_prompt": (s.get("motion_prompt") or "").strip() if _is_str(s.get("motion_prompt")) else ""})
        else:
            shot.pop("card", None)
            if _is_str(shot.get("image_prompt")):
                prompt = shot["image_prompt"].strip()
                if not prompt.lower().startswith(style.lower()):
                    prompt = f"{style}, {prompt}"
                shot["image_prompt"] = prompt
            if _is_str(shot.get("caption")):
                shot["caption"] = shot["caption"].strip().upper()
            if not vo.strip() and _is_str(shot.get("speaker")):
                shot["speaker"] = ""
            if is_montage:
                shot["caption"] = ""
        normalized_shots.append(shot)

    if animated > max_animated:
        errors.append(f"at most {max_animated} shots may have animate: true, got {animated}")
    if not (VO_WORDS_MIN <= vo_words <= VO_WORDS_MAX):
        errors.append(f"total vo_line words must be {VO_WORDS_MIN}-{VO_WORDS_MAX}, got {vo_words}")
    if not montage_idx:
        errors.append(f"add the FLEX MONTAGE: {MONTAGE_MIN}-{MONTAGE_MAX} shots with \"montage\": true "
                      f"right before the final CTA shot")
    else:
        if not (MONTAGE_MIN <= len(montage_idx) <= MONTAGE_MAX):
            errors.append(f"the flex montage needs {MONTAGE_MIN}-{MONTAGE_MAX} shots, got {len(montage_idx)}")
        contiguous = montage_idx == list(range(montage_idx[0], montage_idx[-1] + 1))
        if not contiguous or montage_idx[-1] != len(shots) - 2:
            errors.append(f"the montage shots must be consecutive and come right before the final CTA "
                          f"shot; they are at shots {[i + 1 for i in montage_idx]} of {len(shots)}")
    if not (CARDS_MIN <= cards <= CARDS_MAX):
        errors.append(f"use {CARDS_MIN}-{CARDS_MAX} time-jump card shots, got {cards}")
    if app_paths and not (1 <= app_shots <= APP_SCREENS_MAX):
        errors.append(f"use 1-{APP_SCREENS_MAX} app_screen shots (one right after the hero opens the "
                      f"app, optionally one in the grind), got {app_shots}")
    if not app_paths and app_shots:
        errors.append(f"no app screenshots are available, so remove the {app_shots} app_screen shot(s)")
    if normalized_shots:
        last = normalized_shots[-1]
        if last.get("caption") != CTA_CAPTION:
            errors.append(f"last shot caption must be {CTA_CAPTION!r}, got {last.get('caption')!r}")

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
    screens = available_app_screens(config)
    for e in config.get("app_screens", []):
        if e not in screens:
            print(f"[script] app screenshot {e['path']} is listed in config but missing; not offering it")
    client = client or create_client()

    system = build_system_prompt(style, max_animated, locked, screens)
    messages = [{"role": "user", "content": build_user_prompt(premise)}]

    last_error = None
    for attempt in (1, 2):
        print(f"[script] calling {model} (attempt {attempt}/2)...")
        response = call_model(client, model, max_tokens, system, messages)
        text = response_text(response)
        try:
            return validate_and_normalize(parse_json(text), style, max_animated, locked, screens)
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
