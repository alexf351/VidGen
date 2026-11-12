"""A new shot for a script that is already written, from a few plain answers.

The script editor's "Add a shot" asks who is in the shot, what we see, how it moves and what is
said, and this turns the answers into a shot the rest of the pipeline can draw: the cast's
locked descriptions word for word, the place taken from the shot before it when the new shot
continues that scene, and nobody called by name in the picture prompt (the image model does
not know who "Marcus" is; it knows "the man with messy dark brown hair").

Three kinds:
    {"kind": "scene", "characters": ["marcus"], "sees": "...", "moves": "...", "line": "...",
     "speaker": "marcus", "framing": "close" | "medium" | "wide", "same_place": true}
    {"kind": "texts", "from": "Jess", "messages": ["...", "..."]}
    {"kind": "card", "text": "3 WEEKS LATER"}
"""

from __future__ import annotations

import re

from common import StepError

FRAMINGS = {"close": "close shot, chest up", "medium": "medium shot", "wide": "wide shot"}
END = "Vertical composition, no text anywhere in the image."
MAX_TEXT = 600
_FRAMING = re.compile(
    r"^(?:(?:extreme|medium|low angle|high angle|wide|close|over-the-shoulder)\s+)*(?:(?:two|three)\s+)?shot"
    r"(?:\s+(?:from|across|down|of|over|along)\b[^,]*)?(?:,\s*(?:chest up|waist up|centred|centered))?\s*,\s*", re.I)
EMPTY = {"characters": [], "image_prompt": "", "motion_prompt": "", "vo_line": "", "speaker": "", "caption": "",
         "animate": False}


def _text(value, what: str, required: bool = False) -> str:
    text = " ".join(str(value or "").split()) if isinstance(value, (str, type(None))) else ""
    if value is not None and not isinstance(value, str):
        raise StepError(f"{what} must be text")
    if required and not text:
        raise StepError(f"{what} is needed")
    if len(text) > MAX_TEXT:
        raise StepError(f"{what} is too long ({len(text)} characters, at most {MAX_TEXT})")
    return text


def place_of(image_prompt: str, style: str, descriptions: list[str]) -> str:
    """The place and light of a shot, read out of its picture prompt: what stands between the
    framing ("close shot, chest up,") and the first person's description. "" when the prompt is
    not built that way."""
    text = str(image_prompt or "").strip()
    if style and text.lower().startswith(style.lower()):
        text = text[len(style):].lstrip(" ,")
    cuts = [text.find(d) for d in descriptions if d and d in text]
    if not cuts:
        return ""
    head = text[:min(cuts)].rstrip(" ,;")
    head = _FRAMING.sub("", head + ", ", count=1).rstrip(" ,;")
    return head if 3 <= len(head.split()) <= 60 else ""


def _scene_before(shots: list[dict], after: int) -> dict | None:
    """The drawn shot a new shot at this place would continue: the nearest one before it, not
    past a time card or a montage shot."""
    for s in reversed(shots[:after]):
        if not isinstance(s, dict) or s.get("card") or s.get("montage") or s.get("flash"):
            return None
        if str(s.get("image_prompt") or "").strip():
            return s
    return None


def _sentence(text: str) -> str:
    text = text.strip()
    text = text[:1].upper() + text[1:]
    return text if text[-1:] in ".!?" else text + "."


def build(config: dict, script: dict, after: int, spec: dict) -> dict:
    """The shot to add after shot `after`, from the form's answers. Raises StepError with a
    plain reason when an answer is missing or does not fit."""
    if not isinstance(spec, dict):
        raise StepError("the new shot must be an object")
    kind = spec.get("kind") or "scene"
    if kind == "card":
        return {**EMPTY, "card": _text(spec.get("text"), "the card's text", required=True).upper()}
    if kind == "texts":
        import phone_texts
        texts, problems = phone_texts.check({"from": spec.get("from"), "messages": spec.get("messages")}, "the new shot")
        if problems:
            raise StepError("; ".join(p.replace("the new shot.texts.", "") for p in problems))
        return {**EMPTY, "texts": texts}
    if kind != "scene":
        raise StepError(f"kind must be scene, texts or card, got {kind!r}")

    import clip_sound
    shots = [s for s in (script.get("shots") or []) if isinstance(s, dict)]
    cast = [c for c in (script.get("characters") or []) if isinstance(c, dict) and isinstance(c.get("id"), str)]
    by_id = {c["id"]: str(c.get("description") or "") for c in cast}
    who = spec.get("characters") or []
    if not isinstance(who, list) or any(not isinstance(c, str) for c in who):
        raise StepError("who is in the shot must be a list of character ids")
    who = list(dict.fromkeys(who))
    unknown = [c for c in who if c not in by_id]
    if unknown:
        raise StepError(f"{', '.join(unknown)} is not in this video's cast ({', '.join(by_id)})")
    sees = _text(spec.get("sees"), "what we see", required=True)
    if len(sees.split()) < 3:
        raise StepError("say a little more about what we see: who is where, doing what, with what look on their face")
    moves = _text(spec.get("moves"), "how it moves")
    line = _text(spec.get("line"), "the line")
    speaker = spec.get("speaker") or ""
    if line:
        if speaker not in by_id:
            raise StepError("a line needs someone to say it: pick the speaker")
        if speaker not in who:
            who.append(speaker)                       # whoever speaks is in the shot
    else:
        speaker = ""
    framing = FRAMINGS.get(spec.get("framing") or ("close" if len(who) <= 1 else "medium"))
    if not framing:
        raise StepError(f"framing must be one of {', '.join(FRAMINGS)}")

    before = _scene_before(shots, after) if spec.get("same_place", True) else None
    place = place_of(before["image_prompt"], str(config.get("style") or ""), list(by_id.values())) if before else ""
    people = "; ".join(by_id[c] for c in who)
    # In the picture prompt people are told apart by their look, never by name.
    seen = clip_sound.unname(sees, {"characters": who}, cast)
    head = ", ".join(x for x in (framing, place, people) if x)
    shot = {**EMPTY, "characters": who,
            "image_prompt": f"{head}. {_sentence(seen)} {END}",
            "motion_prompt": _sentence(moves) if moves else "Small natural movement: a breath, a blink, a shift of weight. Slow push-in.",
            "vo_line": line, "speaker": speaker}
    if before is not None:
        shot["same_scene"] = True
    return shot
