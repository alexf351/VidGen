"""import-skill: turn a Claude skill folder (SKILL.md + the files it references) into a VidGen
format under formats/<name>/.

Claude maps the skill onto the format schema, keeping the skill's wording; this module writes
the files, appends the part of the script prompt VidGen depends on (the JSON shot-list
contract), validates the result and reports what was filled, guessed and unsupported.
Import tooling only: nothing here changes how the pipeline runs a format.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

import anthropic
import yaml

from common import ROOT, StepError
from format_loader import DEFAULT_FORMAT, FORMATS_DIR, _PLACEHOLDER, load_format, render

PROTECTED = {DEFAULT_FORMAT}            # built-in formats an import never replaces, even with --force
MAX_FILES = 60                          # referenced files read from the skill
MAX_FILE_CHARS = 100_000
MAX_TOTAL_CHARS = 400_000
ASPECT = "9:16"                         # images and video are generated 9:16 only
RESOLUTION = [1080, 1920]
COOL_TINT = "rs=-0.03:bs=0.04:rm=-0.02:bm=0.03:rh=-0.01:bh=0.02"   # pixar_arc's grade
WARM_TINT = "rs=0.03:bs=-0.04:rm=0.02:bm=-0.03:rh=0.01:bh=-0.02"
TINTS = {"none": "", "cool": COOL_TINT, "warm": WARM_TINT}
# Placeholders a format's prompt may use (format_loader fills these; anything else is an error).
BASE_PLACEHOLDERS = {"STYLE", "MAX_ANIMATED", "CAST", "SPEAKERS", "APP_SCREENS", "SHOT_RULES",
                     "SHOT_MIN", "SHOT_MAX", "VO_WORDS_MIN", "VO_WORDS_MAX", "CTA_CAPTION",
                     "APP_SCREENS_MAX"}
CARD_PLACEHOLDERS = {"CARDS_MIN", "CARDS_MAX", "CARD_WORDS_MIN", "CARD_WORDS_MAX"}
MONTAGE_PLACEHOLDERS = {"MONTAGE_MIN", "MONTAGE_MAX"}
CONTRACT_MARKER = "{{VIDGEN_CONTRACT}}"
FORMAT_KEYS = {"name", "description", "duration_target", "aspect", "resolution", "fps",
               "clip_seconds", "cast", "beats", "style", "max_animated_shots", "rules", "prompt",
               "captions", "grade", "timing", "app_screens", "locked_characters"}


# ------------------------------------------------------------------ read ----

def _split_frontmatter(text: str) -> tuple[dict, str, str | None]:
    """(frontmatter, body, warning). A missing or broken frontmatter is not fatal."""
    m = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", text, flags=re.S)
    if not m:
        return {}, text, None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        return {}, text[m.end():], f"SKILL.md frontmatter is not valid YAML ({e}); ignored it"
    if not isinstance(meta, dict):
        return {}, text[m.end():], "SKILL.md frontmatter is not a mapping; ignored it"
    return meta, text[m.end():], None


_REF_PATTERNS = [
    r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)",          # [text](path) / [text](<path>)
    r"`([^`\s]+)`",                                           # `path`
    r"(?<![\w/.-])((?:\.{0,2}/)?[\w.-]+(?:/[\w.-]+)*\.[A-Za-z0-9]{1,6})(?![\w/])",   # bare a/b.md
    r"(?<![\w/.-])((?:\.{0,2}/)?[\w.-]+(?:/[\w.-]+)*/)(?![\w/])",                      # bare dir/
]


def find_references(text: str, base: Path, root: Path) -> list[Path]:
    """Files under `root` that `text` points at, by relative path (a directory means its files)."""
    found: list[Path] = []
    for pat in _REF_PATTERNS:
        for m in re.finditer(pat, text):
            raw = m.group(1).split("#")[0].split("?")[0].strip()
            if not raw or re.match(r"^[a-z][a-z0-9+.-]*:", raw, flags=re.I) or raw.startswith("/"):
                continue                                   # URLs, mailto:, absolute paths
            for start in (base, root):
                p = (start / raw).resolve()
                try:
                    p.relative_to(root)
                except ValueError:
                    continue                               # outside the skill folder
                if p.is_file():
                    found.append(p)
                    break
                if p.is_dir():
                    found.extend(sorted(q for q in p.rglob("*") if q.is_file()))
                    break
    out, seen = [], set()
    for p in found:
        if p not in seen and not any(part.startswith(".") for part in p.relative_to(root).parts):
            seen.add(p)
            out.append(p)
    return out


def read_skill(path: str | Path) -> dict:
    """SKILL.md (frontmatter + body) and the files it references, two levels deep."""
    p = Path(path).expanduser()
    if p.is_dir():
        skill_md = p / "SKILL.md"
        if not skill_md.is_file():
            cands = [q for q in p.iterdir() if q.is_file() and q.name.lower() == "skill.md"]
            if not cands:
                raise StepError(f"{p} has no SKILL.md")
            skill_md = cands[0]
    elif p.is_file():
        skill_md = p
    else:
        raise StepError(f"{p} not found; pass a skill folder or its SKILL.md")
    root = skill_md.parent.resolve()
    try:
        text = skill_md.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise StepError(f"{skill_md} is not UTF-8 text: {e}") from e
    meta, body, warning = _split_frontmatter(text)
    warnings = [warning] if warning else []

    files: list[dict] = []
    seen = {skill_md.resolve()}
    queue = [(skill_md.resolve(), text, 0)]
    total = len(text)
    while queue:
        src, src_text, depth = queue.pop(0)
        if depth >= 2:
            continue
        for ref in find_references(src_text, src.parent, root):
            if ref in seen:
                continue
            seen.add(ref)
            if len(files) >= MAX_FILES:
                warnings.append(f"more than {MAX_FILES} referenced files; read the first {MAX_FILES}")
                queue.clear()
                break
            rel = ref.relative_to(root).as_posix()
            entry = {"path": rel, "abs": ref, "size": ref.stat().st_size, "text": None}
            try:
                content = ref.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                content = None                             # binary: listed, not sent
            if content is not None:
                if len(content) > MAX_FILE_CHARS or total + len(content) > MAX_TOTAL_CHARS:
                    warnings.append(f"{rel} is too large to send ({len(content):,} chars); listed by name only")
                else:
                    entry["text"] = content
                    total += len(content)
                    if ref.suffix.lower() in (".md", ".markdown", ".txt"):
                        queue.append((ref, content, depth + 1))
            files.append(entry)
    return {"skill_md": skill_md, "root": root, "text": text, "meta": meta, "body": body,
            "files": files, "warnings": warnings}


def format_name_for(skill: dict, name: str | None) -> str:
    raw = name or str(skill["meta"].get("name") or "") or skill["root"].name
    slug = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")
    if not slug:
        raise StepError(f"cannot make a format name from {raw!r}; pass --name")
    if name and slug != name:
        raise StepError(f"--name must be lowercase letters, digits and underscores, got {name!r} "
                        f"(try {slug!r})")
    return slug


# ------------------------------------------------------------ the model ----

def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


INT, NUM, STR, BOOL = {"type": "integer"}, {"type": "number"}, {"type": "string"}, {"type": "boolean"}
PAIR = {"type": "array", "items": INT, "description": "[min, max]"}

IMPORT_SCHEMA = _obj({
    "description": STR,
    "duration_target": STR,
    "aspect_requested": STR,
    "clip_seconds": INT,
    "cast": {"type": "string", "enum": ["locked", "none"]},
    "beats": {"type": "array", "items": STR},
    "style": STR,
    "max_animated_shots": INT,
    "rules": _obj({
        "story_shots": PAIR,
        "vo_words": PAIR,
        "caption_max_words": INT,
        "cta_caption": STR,
        "narrator": BOOL,
        "cards": _nullable(_obj({"count": PAIR, "words": PAIR})),
        "montage": _nullable(_obj({"name": STR, "count": PAIR})),
        "banned_image_prompt": _obj({
            "fix": STR,
            "patterns": {"type": "array", "items": _obj({"regex": STR, "label": STR})},
        }),
    }),
    "locked_characters": {"type": "array", "items": _obj({"id": STR, "role": STR, "description": STR})},
    "captions": _obj({"max_words": _nullable(INT), "size": _nullable(INT), "y": _nullable(NUM),
                      "fill_rgb": _nullable(STR), "outline_rgb": _nullable(STR)}),
    "grade": _obj({"saturation": _nullable(NUM),
                   "tint": _nullable({"type": "string", "enum": ["none", "cool", "warm"]})}),
    "timing": _obj({"min_shot_seconds": _nullable(NUM), "card_seconds": _nullable(NUM),
                    "montage_seconds": _nullable(NUM), "zoom_end": _nullable(NUM)}),
    "script_prompt": STR,
    "shot_rules": STR,
    "examples": {"type": "array", "items": STR},
    "sample_premise": STR,
    "report": _obj({
        "filled": {"type": "array", "items": _obj({"field": STR, "from_skill": STR})},
        "guessed": {"type": "array", "items": _obj({"field": STR, "why": STR})},
        "unsupported": {"type": "array", "items": _obj({"feature": STR, "why": STR})},
    }),
})

IMPORT_SYSTEM = """\
You convert a Claude skill (a SKILL.md and the files it references) into a VidGen video format.
VidGen is a command-line pipeline that turns a one-line story premise into a finished vertical
short. Fill every field of the JSON schema. Keep the skill's own wording wherever you can:
copy its instructions, rules and phrasing into script_prompt and shot_rules rather than
paraphrasing, and only add what VidGen needs to work.

WHAT VIDGEN DOES (and nothing else)
1. Script: Claude, using the format's script_prompt as its system prompt, turns the premise into
   a JSON shot list. Each shot has an image_prompt (one still), a motion_prompt, at most one
   spoken line (vo_line) with its speaker, a short caption and an animate flag.
2. Images: one keyframe per shot from Nano Banana, with the format's style line prepended and
   reference sheets for locked characters so they stay consistent. Always 9:16.
3. Video: only shots marked animate (up to max_animated_shots) become image-to-video clips
   (Seedance 2.0 fast, clip_seconds long, 4-15, no generated audio). Other shots are stills with
   a slow push-in.
4. Voice: ElevenLabs text-to-speech, one voice per speaker, with word timings.
5. Assembly (ffmpeg): shots cut in order, hard cuts only; each shot lasts its spoken line plus a
   pad (or a minimum); burned-in captions, 1-few words at a time in all caps synced to speech
   (silent shots show their caption field); optional time-jump cards (black screen, white text)
   between shots; an optional montage of quick consecutive shots right before the last shot;
   a colour grade (saturation + optional cool/warm tint); an optional music file and outro clip
   the user supplies in config (never generated).
Not available: other aspect ratios than 9:16, music or sound-effect generation, lip sync or
talking avatars, stock or real footage, screen recordings, the user's own photos or videos as
shots, on-screen text other than the captions and cards, transitions other than hard cuts,
split screens or picture-in-picture, real people's likeness, web research, uploading or
posting, several videos per run, voice cloning. Put anything the skill needs from this list in
report.unsupported with the closest VidGen behaviour, and map the rest as well as you can.

FIELDS
- description: one or two sentences on what videos this format makes.
- duration_target: free text such as "about 30-45 seconds" (informational).
- aspect_requested: the aspect ratio the skill asks for, or "9:16" if it does not say.
- cast: "locked" when the skill has recurring named characters, otherwise "none".
  locked_characters: for "locked", each recurring character with a lowercase slug id, a role,
  and a description of physical IDENTITY only (face, hair, skin, build, age as an adult), no
  clothing. Empty for "none". Spoken lines must come from these characters; if the skill uses
  a narrator voice, add a locked character with id "narrator" (it is still drawn as a reference
  sheet) and set rules.narrator to true, or use cast "none".
- style: the line prepended word for word to every image prompt. It must end with
  "vertical 9:16".
- beats: the story beats in order, short labels.
- rules: story_shots = how many shots, not counting a montage; vo_words = total spoken words in
  the video; caption_max_words; cta_caption = exact caption on the final shot, or "" for none;
  cards = time-jump cards (count range and words per card), or null if the skill has none;
  montage = rapid shots right before the final shot, or null; banned_image_prompt = wording that
  must never appear in an image_prompt (Python regexes on lower-case text, with a label) and a
  one-line fix, or an empty list.
- captions / grade / timing: only what the skill specifies; null means VidGen's default (90 px
  white text with a soft glow at 55% height, 2 words at a time; saturation 0.85 with a cool
  tint; 1.2 s minimum shot, 1.5 s cards, 0.5 s montage shots, push-in to 1.08). Colours as
  "RRGGBB" hex.
- script_prompt: the system prompt for the script step: the role, the story and beat
  structure, the tone and every story rule from the skill, in the skill's words. Do not describe
  the JSON output format or the shot fields: VidGen adds that section itself at the marker
  {{VIDGEN_CONTRACT}}; put that marker where it belongs (usually the end). Placeholders VidGen
  fills: {{STYLE}} {{MAX_ANIMATED}} {{CAST}} (the locked cast, one per line) {{SPEAKERS}}
  {{SHOT_MIN}} {{SHOT_MAX}} {{VO_WORDS_MIN}} {{VO_WORDS_MAX}} {{CTA_CAPTION}}, plus
  {{CARDS_MIN}} {{CARDS_MAX}} {{CARD_WORDS_MIN}} {{CARD_WORDS_MAX}} when there are cards and
  {{MONTAGE_MIN}} {{MONTAGE_MAX}} when there is a montage. Use no other {{...}}: write any other
  template variable from the skill as <NAME>.
- shot_rules: the skill's rules for image prompts and motion (composition, camera, lighting,
  what must or must not be shown, when to animate), in the skill's words. Inserted into the
  script prompt at {{SHOT_RULES}}.
- examples: relative paths (exactly as listed) of the provided files that are example scripts,
  outputs or storyboards worth keeping next to the format. Empty if none.
- sample_premise: one premise that fits this format, for a test run.
- report.filled: each field you took from the skill, with a short quote or section name.
  report.guessed: each field the skill does not determine that you had to choose, and why.
  report.unsupported: what the skill wants that VidGen cannot do.
"""


def _user_content(skill: dict) -> str:
    parts = [f'<file path="{skill["skill_md"].name}">\n{skill["text"]}\n</file>']
    for f in skill["files"]:
        if f["text"] is not None:
            parts.append(f'<file path="{f["path"]}">\n{f["text"]}\n</file>')
        else:
            parts.append(f'<file path="{f["path"]}" bytes="{f["size"]}">(binary or too large; not included)</file>')
    return ("Convert this skill into a VidGen format.\n\n" + "\n\n".join(parts))


def call_import_model(client, cfg: dict, messages: list) -> tuple[dict, list]:
    """One structured-output request. Returns (parsed JSON, assistant content to echo back)."""
    try:
        with client.beta.messages.stream(
            model=cfg["model"],
            max_tokens=int(cfg["max_tokens"]),
            system=IMPORT_SYSTEM,
            messages=messages,
            output_config={"effort": cfg["effort"],
                           "format": {"type": "json_schema", "schema": IMPORT_SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
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
        d = response.stop_details
        detail = f" ({d.category}: {d.explanation})" if d else ""
        raise StepError(f"the model declined to convert this skill{detail}")
    if response.stop_reason == "max_tokens":
        raise StepError(f"the conversion was cut off at max_tokens={cfg['max_tokens']}; raise "
                        f"import_skill.max_tokens in config.yaml")
    text = "".join(b.text for b in response.content if b.type == "text")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise StepError(f"the conversion was not valid JSON: {e}") from e
    return data, response.content


# --------------------------------------------------------- build format ----

def _contract(rules: dict) -> str:
    """The script-step contract VidGen's validator enforces, written for this format's rules."""
    cards, montage = rules["cards"], rules["montage"]
    optional = []
    if cards:
        optional.append('"card" ONLY on time-jump card shots')
    if montage:
        optional.append('"montage": true ONLY on montage shots')
    lines = [
        "OUTPUT",
        "Answer with ONLY a single JSON object: no prose, no markdown, no code fences.",
        "{",
        '  "characters": [{"id": "<lowercase id>", "description": "<one sentence>"}],',
        '  "shots": [',
        '    {"n": 1, "characters": ["<id>"], "image_prompt": "...", "motion_prompt": "...",',
        '     "vo_line": "...", "speaker": "<id>", "caption": "", "animate": false}',
        "  ]",
        "}",
        ("Optional shot fields: " + "; ".join(optional) + '. Leave them out of every other shot, '
         'and use no other fields (no "app_screen").'
         if optional else 'Use no other shot fields (no "card", "montage" or "app_screen").'),
        "",
        "CAST",
        "Locked characters (reuse these ids and copy each description WORD FOR WORD into",
        '"characters" and into the image_prompt of every shot they appear in):',
        "{{CAST}}",
        "You may add other characters for minor roles; every character is an adult, with one",
        "sentence of physical description that you reuse word for word.",
        "",
        "SHOT LIST RULES",
        "- {{SHOT_MIN}}-{{SHOT_MAX}} shots" + (" not counting the montage" if montage else "")
        + ', numbered "n" from 1 with no gaps.',
        '- "image_prompt" begins with this exact style line, then a comma, then the scene:',
        '  "{{STYLE}}"',
        "  then framing, setting, lighting and every character in frame with their description.",
        '- "characters" lists the ids visible in the shot (may be empty).',
        '- "motion_prompt" is one short sentence of camera and subject motion.',
        '- "vo_line" is one spoken line or "" for a silent shot. "speaker" is the id of the',
        '  character who says it (one of: {{SPEAKERS}}), or "" when vo_line is "".',
    ]
    if not rules["narrator"]:
        lines.append('  There is no narrator: every spoken line is a character talking; never "narrator".')
    lines += [
        "- The total number of words across all vo_lines is {{VO_WORDS_MIN}}-{{VO_WORDS_MAX}}."
        + (" Montage shots are silent and do not count." if montage else ""),
        f'- "caption" is "" or at most {rules["caption_max_words"]} words in ALL CAPS.',
        '- "animate" is true for at most {{MAX_ANIMATED}} shots, where motion is the point.',
    ]
    if rules["cta_caption"]:
        lines.append('- The last shot\'s caption is exactly "{{CTA_CAPTION}}".')
    if cards:
        lines += [
            "- {{CARDS_MIN}}-{{CARDS_MAX}} time-jump card shots: \"card\": a span of time in ALL CAPS,",
            '  {{CARD_WORDS_MIN}}-{{CARD_WORDS_MAX}} words, with "characters": [], "image_prompt": "",',
            '  "motion_prompt": "", "vo_line": "", "speaker": "", "caption": "", "animate": false.',
            "  A card is never the first or last shot and counts toward the shot total.",
        ]
    if montage:
        lines += [
            "- {{MONTAGE_MIN}}-{{MONTAGE_MAX}} consecutive montage shots with \"montage\": true come right",
            '  before the final shot: no dialogue ("vo_line": "", "speaker": "", "caption": "",',
            '  "animate": false), each a single striking image.',
        ]
    lines.append("")
    lines.append("Return only the JSON object.")
    return "\n".join(lines)


def _hex_to_ass(rgb: str | None, what: str, problems: list[str]) -> str | None:
    if rgb is None:
        return None
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", rgb.strip())
    if not m:
        problems.append(f"captions.{what} {rgb!r} is not RRGGBB hex; used the default")
        return None
    h = m.group(1).upper()
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}"


def _fix_placeholders(text: str, allowed: set[str], where: str, notes: list[str]) -> str:
    def sub(m):
        name = m.group(1)
        if name in allowed:
            return m.group(0)
        notes.append(f"{where}: {{{{{name}}}}} is not a VidGen placeholder; written as <{name}>")
        return f"<{name}>"
    return _PLACEHOLDER.sub(sub, text)


def build_format(data: dict, name: str, skill: dict) -> tuple[dict, dict, list[str]]:
    """Model output -> (format.yaml dict, {filename: text}, notes on what was adjusted)."""
    notes: list[str] = []
    r = data["rules"]
    rules = {
        "story_shots": r["story_shots"], "vo_words": r["vo_words"],
        "caption_max_words": r["caption_max_words"], "cta_caption": r["cta_caption"].strip(),
        "narrator": bool(r["narrator"]),
    }
    if r["cards"]:
        rules["cards"] = {"count": r["cards"]["count"], "words": r["cards"]["words"]}
    if r["montage"]:
        rules["montage"] = {"name": r["montage"]["name"].strip() or "MONTAGE", "count": r["montage"]["count"]}
    patterns = []
    for p in r["banned_image_prompt"]["patterns"]:
        try:
            re.compile(p["regex"])
            patterns.append([p["regex"], p["label"]])
        except re.error as e:
            notes.append(f"dropped banned image_prompt pattern {p['regex']!r}: not a valid regex ({e})")
    if patterns:
        rules["banned_image_prompt"] = {"fix": r["banned_image_prompt"]["fix"], "patterns": patterns}

    style = data["style"].strip()
    if not re.search(r"vertical\s*9:16", style, flags=re.I):
        style = f"{style.rstrip(' ,')}, vertical 9:16"
        notes.append('style: added "vertical 9:16" (VidGen generates 9:16 images)')

    asked = (data.get("aspect_requested") or ASPECT).strip()
    if asked.replace(" ", "") not in (ASPECT, "9x16", "vertical", "portrait"):
        notes.append(f"aspect: the skill asks for {asked}; VidGen only generates 9:16, so the format is 9:16")

    clip = int(data["clip_seconds"])
    if not 4 <= clip <= 15:
        notes.append(f"clip_seconds {clip} is outside 4-15; clamped")
        clip = min(15, max(4, clip))

    cast = data["cast"]
    locked = []
    for c in data["locked_characters"] if cast == "locked" else []:
        cid = re.sub(r"[^a-z0-9_-]+", "_", c["id"].strip().lower()).strip("_-")
        if not cid or not cid[0].isalpha():
            cid = f"c_{cid}" if cid else f"character{len(locked) + 1}"
        if cid != c["id"]:
            notes.append(f"locked character id {c['id']!r} renamed {cid!r}")
        locked.append({"id": cid, "role": c["role"].strip(), "description": c["description"].strip(),
                       "image_path": ""})
    if cast == "locked" and not locked:
        notes.append('cast was "locked" with no characters; set to "none"')
        cast = "none"

    fmt: dict = {
        "name": name,
        "description": data["description"].strip(),
        "duration_target": data["duration_target"].strip(),
        "aspect": ASPECT,
        "resolution": list(RESOLUTION),
        "fps": 30,
        "clip_seconds": clip,
        "cast": cast,
        "beats": [b.strip() for b in data["beats"] if b.strip()],
        "style": style,
        "max_animated_shots": int(data["max_animated_shots"]),
        "rules": rules,
        "prompt": {"app_screen_line": '* "{{PATH}}": {{SHOWS}}', "app_screen_unknown": "an app screen"},
    }
    cap = data["captions"]
    captions = {k: v for k, v in (("max_words", cap["max_words"]), ("size", cap["size"]), ("y", cap["y"]))
                if v is not None}
    fill = _hex_to_ass(cap["fill_rgb"], "fill_rgb", notes)
    outline = _hex_to_ass(cap["outline_rgb"], "outline_rgb", notes)
    if fill:
        captions["fill"] = fill
    if outline:
        captions["outline_color"] = outline
    if captions:
        fmt["captions"] = captions
    grade = {}
    if data["grade"]["saturation"] is not None:
        grade["saturation"] = data["grade"]["saturation"]
    if data["grade"]["tint"] is not None:
        grade["colorbalance"] = TINTS[data["grade"]["tint"]]
    if grade:
        fmt["grade"] = grade
    timing = {k: v for k, v in data["timing"].items() if v is not None}
    if timing:
        fmt["timing"] = timing
    fmt["app_screens"] = []
    if cast == "locked":
        fmt["locked_characters"] = locked

    allowed = set(BASE_PLACEHOLDERS)
    if "cards" in rules:
        allowed |= CARD_PLACEHOLDERS
    if "montage" in rules:
        allowed |= MONTAGE_PLACEHOLDERS
    prompt = data["script_prompt"].strip()
    shot_rules = data["shot_rules"].strip()
    shot_rules = _fix_placeholders(shot_rules, allowed - {"SHOT_RULES"}, "shot_rules.md", notes)
    prompt = prompt.replace(CONTRACT_MARKER, "\0CONTRACT\0")
    prompt = _fix_placeholders(prompt, allowed, "script_prompt.md", notes)
    if "{{SHOT_RULES}}" not in prompt:
        if "\0CONTRACT\0" in prompt:
            prompt = prompt.replace("\0CONTRACT\0", "{{SHOT_RULES}}\n\n\0CONTRACT\0", 1)
        else:
            prompt += "\n\n{{SHOT_RULES}}"
    if "\0CONTRACT\0" not in prompt:
        prompt += "\n\n\0CONTRACT\0"
        notes.append("script_prompt.md: VidGen's output section was added at the end")
    contract = _contract({**rules, "cards": rules.get("cards"), "montage": rules.get("montage")})
    prompt = prompt.replace("\0CONTRACT\0", contract, 1).replace("\0CONTRACT\0", "")
    files = {"script_prompt.md": prompt + "\n", "shot_rules.md": shot_rules + "\n"}
    return fmt, files, notes


# -------------------------------------------------------------- validate ----

def _is_pair(v) -> bool:
    return (isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) and not isinstance(x, bool)
                                                         for x in v) and 0 <= v[0] <= v[1])


def validate_format_yaml(f: dict) -> list[str]:
    """Schema problems in a format.yaml mapping (empty list = valid)."""
    errs: list[str] = []
    if not isinstance(f, dict):
        return ["format.yaml must be a mapping"]
    unknown = sorted(set(f) - FORMAT_KEYS)
    if unknown:
        errs.append(f"unknown keys: {unknown}")
    for key in ("name", "description", "style"):
        if not isinstance(f.get(key), str) or not f[key].strip():
            errs.append(f"{key} must be a non-empty string")
    if isinstance(f.get("name"), str) and not re.fullmatch(r"[a-z0-9_]+", f["name"]):
        errs.append("name must be lowercase letters, digits and underscores")
    if f.get("aspect") != ASPECT:
        errs.append(f"aspect must be {ASPECT} (images and video are generated 9:16)")
    res = f.get("resolution")
    if (not isinstance(res, list) or len(res) != 2 or not all(isinstance(x, int) and x > 0 for x in res)
            or res[0] * 16 != res[1] * 9):
        errs.append("resolution must be [width, height] at 9:16")
    if not isinstance(f.get("fps"), int) or not 12 <= f["fps"] <= 60:
        errs.append("fps must be a whole number 12-60")
    if not isinstance(f.get("clip_seconds"), int) or not 4 <= f["clip_seconds"] <= 15:
        errs.append("clip_seconds must be 4-15")
    if f.get("cast") not in ("locked", "none"):
        errs.append('cast must be "locked" or "none"')
    if not isinstance(f.get("beats"), list) or not f["beats"] or not all(isinstance(b, str) and b for b in f["beats"]):
        errs.append("beats must be a non-empty list of labels")
    if not isinstance(f.get("max_animated_shots"), int) or f["max_animated_shots"] < 0:
        errs.append("max_animated_shots must be a whole number >= 0")
    r = f.get("rules")
    if not isinstance(r, dict):
        errs.append("rules must be a mapping")
    else:
        for key in ("story_shots", "vo_words"):
            if not _is_pair(r.get(key)):
                errs.append(f"rules.{key} must be [min, max] with 0 <= min <= max")
        if _is_pair(r.get("story_shots")) and r["story_shots"][0] < 2:
            errs.append("rules.story_shots must allow at least 2 shots")
        if not isinstance(r.get("caption_max_words"), int) or r["caption_max_words"] < 1:
            errs.append("rules.caption_max_words must be at least 1")
        if not isinstance(r.get("cta_caption", ""), str):
            errs.append("rules.cta_caption must be a string")
        for key, sub in (("cards", ("count", "words")), ("montage", ("count",))):
            v = r.get(key)
            if v is None:
                continue
            if not isinstance(v, dict):
                errs.append(f"rules.{key} must be a mapping or absent")
                continue
            for s in sub:
                if not _is_pair(v.get(s)):
                    errs.append(f"rules.{key}.{s} must be [min, max]")
        if r.get("cards") and _is_pair(r["cards"].get("words")) and r["cards"]["words"][0] < 1:
            errs.append("rules.cards.words must start at 1 or more")
        if _is_pair(r.get("story_shots")) and isinstance(f.get("max_animated_shots"), int) \
                and f["max_animated_shots"] > r["story_shots"][1] + ((r.get("montage") or {}).get("count") or [0, 0])[1]:
            errs.append("max_animated_shots is more than the number of shots")
    if f.get("cast") == "locked":
        chars = f.get("locked_characters")
        if not isinstance(chars, list) or not chars:
            errs.append('cast "locked" needs locked_characters')
        else:
            ids = []
            for i, c in enumerate(chars):
                if not isinstance(c, dict) or not re.fullmatch(r"[a-z][a-z0-9_-]*", str(c.get("id", ""))) \
                        or not str(c.get("description", "")).strip():
                    errs.append(f"locked_characters[{i}] needs a lowercase id and a description")
                else:
                    ids.append(c["id"])
            if len(ids) != len(set(ids)):
                errs.append("locked_characters ids must be unique")
    return errs


def check_format(name: str) -> list[str]:
    """Load the written format the way the pipeline will and render its prompt."""
    from common import load_config
    import steps.script as S
    try:
        fmt = load_format(name)
        cfg = load_config(format_name=name)
        prompt = S.build_system_prompt(cfg["style"], int(cfg["max_animated_shots"]),
                                       cfg["locked_characters"], [], fmt)
    except StepError as e:
        return [str(e)]
    errs = []
    if "{{" in prompt:
        errs.append("the rendered script prompt still has a {{...}} placeholder")
    if "image_prompt" not in prompt or "vo_line" not in prompt:
        errs.append("the rendered script prompt does not describe the shot list fields")
    return errs


# ----------------------------------------------------------------- write ----

def _safe_rel(rel: str) -> Path:
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts:
        raise StepError(f"refusing to write outside the format folder: {rel}")
    return p


def write_format(name: str, fmt: dict, files: dict, skill: dict, examples: list[str],
                 force: bool) -> tuple[Path, list[str], list[str]]:
    """Write formats/<name>/ (into a temp folder first, then swap it in).
    Returns (folder, copied examples, example paths that were not provided)."""
    target = FORMATS_DIR / name
    if target.exists() and not force:
        raise StepError(f"formats/{name} already exists; pass --force to replace it or --name to pick another")
    FORMATS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".import-{name}-", dir=FORMATS_DIR))
    try:
        header = (f"# Imported from the skill {skill['skill_md'].parent.name}/{skill['skill_md'].name} by "
                  f"`python main.py import-skill`.\n# The original is in source/. Review and edit freely;"
                  f" see formats/{DEFAULT_FORMAT}/format.yaml for every setting.\n\n")
        (tmp / "format.yaml").write_text(header + yaml.safe_dump(fmt, sort_keys=False, allow_unicode=True,
                                                                 width=100), encoding="utf-8")
        for fname, text in files.items():
            (tmp / fname).write_text(text, encoding="utf-8")
        src = tmp / "source"
        src.mkdir()
        shutil.copy2(skill["skill_md"], src / "SKILL.md")
        for f in skill["files"]:
            dest = src / _safe_rel(f["path"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f["abs"], dest)
        by_path = {f["path"]: f for f in skill["files"]}
        copied, missing = [], []
        for rel in examples:
            f = by_path.get(rel.strip().removeprefix("./"))
            if f is None:
                missing.append(rel)
                continue
            out = Path(f["path"]).name
            if (tmp / "examples" / out).exists():
                out = f["path"].replace("/", "__")
            (tmp / "examples").mkdir(exist_ok=True)
            shutil.copy2(f["abs"], tmp / "examples" / out)
            copied.append(out)
        if target.exists():
            shutil.rmtree(target)
        tmp.rename(target)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return target, copied, missing


# ------------------------------------------------------------------- run ----

def _import_cfg(config: dict) -> dict:
    c = dict(config.get("import_skill") or {})
    c.setdefault("model", "claude-opus-5-5")
    c.setdefault("max_tokens", 64000)
    c.setdefault("effort", "high")
    return c


def import_skill(path: str, config: dict, name: str | None = None, force: bool = False,
                 client=None) -> dict:
    """Read the skill, convert it with Claude (one retry on validation problems), write and
    check the format. Returns a summary for print_summary()."""
    skill = read_skill(path)
    name = format_name_for(skill, name)
    if name in PROTECTED:
        raise StepError(f"'{name}' is a built-in format and is never replaced by an import; pass --name")
    if (FORMATS_DIR / name).exists() and not force:
        raise StepError(f"formats/{name} already exists; pass --force to replace it or --name to pick another")
    for w in skill["warnings"]:
        print(f"[import] warning: {w}")
    sent = [f["path"] for f in skill["files"] if f["text"] is not None]
    listed = [f["path"] for f in skill["files"] if f["text"] is None]
    print(f"[import] skill: {skill['skill_md']}")
    print(f"[import] referenced files: {len(skill['files'])} ({len(sent)} sent as text"
          + (f", {len(listed)} listed by name: {', '.join(listed)}" if listed else "") + ")")

    cfg = _import_cfg(config)
    if client is None:
        from steps.script import create_client
        client = create_client()
    messages = [{"role": "user", "content": _user_content(skill)}]
    problems: list[str] = []
    for attempt in (1, 2):
        print(f"[import] calling {cfg['model']} (attempt {attempt}/2)...")
        data, content = call_import_model(client, cfg, messages)
        fmt, files, notes = build_format(data, name, skill)
        problems = validate_format_yaml(fmt)
        if not problems:
            break
        print(f"[import] attempt {attempt} produced an invalid format:\n" + "\n".join(f"  - {p}" for p in problems))
        messages = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": "That conversion does not fit VidGen's format schema:\n"
                                        + "\n".join(f"- {p}" for p in problems)
                                        + "\n\nReturn the corrected conversion."},
        ]
    if problems:
        raise StepError("format.yaml still invalid after 2 attempts:\n" + "\n".join(f"- {p}" for p in problems))

    folder, copied, missing = write_format(name, fmt, files, skill, data["examples"], force)
    checks = check_format(name)
    return {"name": name, "folder": folder, "format": fmt, "data": data, "notes": notes,
            "examples": copied, "missing_examples": missing, "checks": checks,
            "source_files": 1 + len(skill["files"])}


def _defaults_used(data: dict) -> list[str]:
    out = []
    for group in ("captions", "grade", "timing"):
        for k, v in data[group].items():
            if v is None:
                out.append(f"{group}.{k}")
    return out


def print_summary(s: dict) -> None:
    rel = s["folder"].relative_to(ROOT) if s["folder"].is_relative_to(ROOT) else s["folder"]
    f, d = s["format"], s["data"]
    print(f"\n[import] wrote {rel}/")
    print(f"  format.yaml, script_prompt.md, shot_rules.md, source/ ({s['source_files']} file(s))"
          + (f", examples/ ({len(s['examples'])}: {', '.join(s['examples'])})" if s["examples"] else ""))
    r = f["rules"]
    print(f"\n  {f['name']}: {f['description']}")
    print(f"  cast: {f['cast']}"
          + (f" ({', '.join(c['id'] for c in f.get('locked_characters', []))})" if f["cast"] == "locked" else "")
          + f"; {r['story_shots'][0]}-{r['story_shots'][1]} shots; {r['vo_words'][0]}-{r['vo_words'][1]} spoken words;"
          f" clips {f['clip_seconds']}s; up to {f['max_animated_shots']} animated")
    print(f"  beats: {' -> '.join(f['beats'])}")

    print("\n  FILLED from the skill:")
    for x in d["report"]["filled"] or [{"field": "(none listed)", "from_skill": ""}]:
        print(f"    {x['field']}" + (f": {x['from_skill']}" if x["from_skill"] else ""))
    print("\n  GUESSED (check these) [?]:")
    guessed = d["report"]["guessed"]
    for x in guessed:
        print(f"    [?] {x['field']}: {x['why']}")
    defaults = _defaults_used(d)
    if defaults:
        print(f"    [?] VidGen defaults kept for: {', '.join(defaults)}")
    for n in s["notes"]:
        print(f"    [?] {n}")
    if not guessed and not defaults and not s["notes"]:
        print("    (nothing)")
    print("\n  NOT SUPPORTED by VidGen:")
    for x in d["report"]["unsupported"] or [{"feature": "(nothing)", "why": ""}]:
        print(f"    [x] {x['feature']}" + (f": {x['why']}" if x["why"] else ""))
    for m in s["missing_examples"]:
        print(f"    [x] example {m!r} is not among the skill's referenced files; not copied")
