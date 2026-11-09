"""Video formats: one folder per format under formats/<name>/.

A format bundles everything that makes one kind of video: the story and its validation rules,
the prompt text sent to Claude, the cast, and the look of the cut (aspect, clip length,
captions, grade, shot timing).

    formats/<name>/format.yaml        settings (see formats/pixar_arc/format.yaml)
    formats/<name>/script_prompt.md   system prompt for the script step
    formats/<name>/shot_rules.md      image / video prompt rules, inserted at {{SHOT_RULES}}
    formats/<name>/blocks/*.md        optional prompt pieces a step picks between
    formats/<name>/examples/          optional example scripts

Prompt files are read as written; {{NAME}} placeholders are filled in when the prompt is built.
A file's final newline is not part of its text.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from common import ROOT, StepError

FORMATS_DIR = ROOT / "formats"
DEFAULT_FORMAT = "pixar_arc"
COVER_EXTS = ("jpg", "jpeg", "png", "webp")
CAST_MODES = ("locked", "none")
_PLACEHOLDER = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")


def installed_formats() -> list[str]:
    if not FORMATS_DIR.is_dir():
        return []
    return sorted(p.name for p in FORMATS_DIR.iterdir() if (p / "format.yaml").is_file())


def _read_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text[:-1] if text.endswith("\n") else text


def render(template: str, values: dict, where: str = "prompt") -> str:
    """Fill {{NAME}} placeholders in one pass. An unknown name is an error, not left in."""
    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name not in values:
            raise StepError(f"{where}: unknown placeholder {{{{{name}}}}}")
        return str(values[name])
    return _PLACEHOLDER.sub(sub, template)


def _pair(value, what: str) -> list[int]:
    if (not isinstance(value, list) or len(value) != 2 or not all(isinstance(v, int) for v in value)
            or value[0] > value[1]):
        raise StepError(f"{what} must be [min, max] whole numbers, got {value!r}")
    return [int(value[0]), int(value[1])]


def _rules(raw, where: str) -> dict:
    if not isinstance(raw, dict):
        raise StepError(f"{where}: rules must be a mapping")
    r: dict = {
        "story_shots": _pair(raw.get("story_shots"), f"{where}: rules.story_shots"),
        "vo_words": _pair(raw.get("vo_words"), f"{where}: rules.vo_words"),
        "caption_max_words": int(raw.get("caption_max_words", 2)),
        "cta_caption": str(raw.get("cta_caption") or "").strip(),
        "narrator": bool(raw.get("narrator", False)),
        "cards": None, "montage": None,
        "app_screens": {"max": 0, "hint": ""},
        "banned_image_prompt": {"fix": "", "patterns": []},
        "banned_vo_line": {"fix": "", "patterns": []},
    }
    if raw.get("cards"):
        c = raw["cards"]
        r["cards"] = {"count": _pair(c.get("count"), f"{where}: rules.cards.count"),
                      "words": _pair(c.get("words"), f"{where}: rules.cards.words")}
    if raw.get("montage"):
        m = raw["montage"]
        r["montage"] = {"name": str(m.get("name") or "MONTAGE"),
                        "count": _pair(m.get("count"), f"{where}: rules.montage.count")}
    if raw.get("app_screens"):
        a = raw["app_screens"]
        r["app_screens"] = {"max": int(a.get("max", 0)), "hint": str(a.get("hint") or "")}
    for key in ("banned_image_prompt", "banned_vo_line"):
        banned = raw.get(key) or {}
        patterns = []
        for i, p in enumerate(banned.get("patterns") or []):
            if not isinstance(p, list) or len(p) != 2:
                raise StepError(f"{where}: rules.{key}.patterns[{i}] must be [regex, label]")
            try:
                re.compile(p[0])
            except re.error as e:
                raise StepError(f"{where}: rules.{key}.patterns[{i}] is not a valid regex: {e}") from e
            patterns.append((str(p[0]), str(p[1])))
        r[key] = {"fix": str(banned.get("fix") or ""), "patterns": patterns}
    return r


def _overlay(f: dict, where: str) -> dict:
    """The format's settings in config.yaml's shape, to be merged over config.yaml."""
    out: dict = {}
    for key in ("style", "max_animated_shots", "app_screens"):
        if key in f:
            out[key] = f[key]
    cast = f.get("cast", "locked")
    if cast not in CAST_MODES:
        raise StepError(f"{where}: cast must be one of {', '.join(CAST_MODES)}, got {cast!r}")
    out["locked_characters"] = (f.get("locked_characters") or []) if cast == "locked" else []

    asm: dict = {}
    res = f.get("resolution")
    if res is not None:
        if (not isinstance(res, list) or len(res) != 2
                or not all(isinstance(v, int) and v > 0 for v in res)):
            raise StepError(f"{where}: resolution must be [width, height], got {res!r}")
        asm["width"], asm["height"] = res
        aspect = str(f.get("aspect") or "").strip()
        if aspect:
            m = re.fullmatch(r"(\d+):(\d+)", aspect)
            if not m or res[0] * int(m.group(2)) != res[1] * int(m.group(1)):
                raise StepError(f"{where}: resolution {res[0]}x{res[1]} does not match aspect {aspect!r}")
    if "fps" in f:
        asm["fps"] = f["fps"]
    for key, value in (f.get("timing") or {}).items():
        asm[key] = value
    cap = f.get("captions") or {}
    for key, value in cap.items():
        asm["card_fade_ms" if key == "card_fade_ms" else f"caption_{key}"] = value
    grade = f.get("grade") or {}
    for key, value in grade.items():
        asm[key] = value
    if asm:
        out["assemble"] = asm
    if "clip_seconds" in f:
        out["fal"] = {"video_seconds": f["clip_seconds"]}
        out["sume"] = {"video_seconds": f["clip_seconds"]}
    return out


SKILLS_DIR = Path(__file__).resolve().parent / "skills"


def _code_render(raw, where: str) -> dict | None:
    """code_render: {skill, styles, mix?} -> the Claude Code engine settings, or None."""
    if raw in (None, {}, False):
        return None
    if not isinstance(raw, dict):
        raise StepError(f"{where}: code_render must be a mapping with skill and styles")
    skill = str(raw.get("skill") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", skill):
        raise StepError(f"{where}: code_render.skill must name a folder under skills/, got {skill!r}")
    template = SKILLS_DIR / skill / "template"
    styles = raw.get("styles") or []
    if not isinstance(styles, list) or not styles or not all(isinstance(x, str) for x in styles):
        raise StepError(f"{where}: code_render.styles must be a list of style names")
    if template.is_dir():
        missing = [x for x in styles if not (template / "styles" / f"{x}.js").is_file()]
        if missing:
            raise StepError(f"{where}: code_render.styles {missing} have no file in skills/{skill}/template/styles/")
    return {"skill": skill, "dir": SKILLS_DIR / skill, "template": template,
            "styles": [str(x) for x in styles], "mix": bool(raw.get("mix"))}


def load_format(name: str | None = None) -> dict:
    name = (name or DEFAULT_FORMAT).strip()
    folder = FORMATS_DIR / name
    where = f"formats/{name}/format.yaml"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or not (folder / "format.yaml").is_file():
        have = ", ".join(installed_formats()) or "none"
        raise StepError(f"unknown format '{name}' (installed: {have}); see: python main.py formats")
    try:
        f = yaml.safe_load((folder / "format.yaml").read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise StepError(f"{where} is not valid YAML: {e}") from e
    if not isinstance(f, dict):
        raise StepError(f"{where} must be a mapping of settings")
    if f.get("name", name) != name:
        raise StepError(f"{where}: name is {f.get('name')!r} but the folder is {name!r}")

    texts = {}
    for key, file in (("script_prompt", "script_prompt.md"), ("shot_rules", "shot_rules.md")):
        path = folder / file
        if not path.is_file():
            raise StepError(f"formats/{name}/{file} is missing")
        texts[key] = _read_text(path)
    blocks = {p.stem: _read_text(p) for p in sorted((folder / "blocks").glob("*.md"))}
    examples = sorted(p.name for p in (folder / "examples").glob("*")) if (folder / "examples").is_dir() else []
    cover = next((folder / f"cover.{ext}" for ext in COVER_EXTS if (folder / f"cover.{ext}").is_file()), None)
    example_video = folder / "example.mp4" if (folder / "example.mp4").is_file() else None

    return {
        "name": name,
        "dir": folder,
        "file": where,
        "title": str(f.get("title") or name.replace("_", " ").title()),
        "description": " ".join(str(f.get("description") or "").split()),
        "duration_target": str(f.get("duration_target") or ""),
        "aspect": str(f.get("aspect") or ""),
        "clip_seconds": f.get("clip_seconds"),
        "cast": f.get("cast", "locked"),
        "beats": [str(b) for b in (f.get("beats") or [])],
        "rules": _rules(f.get("rules") or {}, where),
        "prompt": {"app_screen_line": str((f.get("prompt") or {}).get("app_screen_line") or
                                          '* "{{PATH}}": {{SHOWS}}'),
                   "app_screen_unknown": str((f.get("prompt") or {}).get("app_screen_unknown") or
                                             "an app screen")},
        "script_prompt": texts["script_prompt"],
        "shot_rules": texts["shot_rules"],
        "blocks": blocks,
        "examples": examples,
        "cover": cover,                        # cover.(jpg|jpeg|png|webp) in the folder, for the UI
        "example_video": example_video,        # example.mp4 in the folder, for the UI
        "overlay": _overlay(f, where),
        "code_render": _code_render(f.get("code_render"), where),   # Claude Code engine, if offered
    }


def format_summaries() -> list[dict]:
    """Every installed format, for `main.py formats`. A broken one is listed with its error."""
    out = []
    for name in installed_formats():
        try:
            out.append(load_format(name))
        except StepError as e:
            out.append({"name": name, "error": str(e)})
    return out
