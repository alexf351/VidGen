"""Video formats: one folder per format under formats/<name>/.

A format bundles everything that makes one kind of video: the story and its validation rules,
the prompt text sent to Claude, the cast, and the look of the cut (aspect, clip length,
captions, grade, shot timing).

    formats/<name>/format.yaml        settings (see formats/pixar_arc/format.yaml)
    formats/<name>/script_prompt.md   system prompt for the script step
    formats/<name>/shot_rules.md      image / video prompt rules, inserted at {{SHOT_RULES}}
    formats/<name>/blocks/*.md        optional prompt pieces a step picks between
    formats/<name>/examples/          optional example scripts

A format can build on another one with `extends: <name>` in its format.yaml: it starts from that
format's settings and changes only what it lists (mappings are merged key by key, lists and
plain values are replaced), and any prompt file it does not have comes from the format it
extends. That is how several story shapes share one cast and one look.

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
        # Does the story end on a call-to-action shot carrying cta_caption (true, the default),
        # or on its last story shot, the montage's smirk, with no ad at the end (false)?
        "closing_shot": raw.get("closing_shot", True) is not False,
        "narrator": bool(raw.get("narrator", False)),
        # With a narrator: at least this many lines must still be spoken by characters.
        "dialogue_lines_min": max(0, int(raw.get("dialogue_lines_min") or 0)),
        # At most this many story shots in a row may be silent (0 = no limit).
        "silent_run_max": max(0, int(raw.get("silent_run_max") or 0)),
        "cards": None, "montage": None,
        "app_screens": {"max": 0, "hint": ""},
        "banned_image_prompt": {"fix": "", "patterns": []},
        "banned_vo_line": {"fix": "", "patterns": []},
        # Shot capabilities a format can switch on (all off by default):
        "letter": bool(raw.get("letter", False)),   # every story shot carries a line of an on-screen letter
        "talking": None,                             # {"max": n}: shots may be lip-synced talking clips
        "song": bool(raw.get("song", False)),       # the lines are sung as one song
        "labels": bool(raw.get("labels", False)),   # shots may carry a short on-screen tag
        "label_max_words": max(1, int(raw.get("label_max_words") or 3)),
        # Progress overlays ("stat") on the grind shots: {count: [min, max], ranks: [...], units: [...]}
        "stats": None,
        # At least this many lines after the last time card repeat, word for word, a line said
        # before it (the opening scene replayed with the roles reversed). 0 = no such rule.
        "mirror_lines_min": max(0, int(raw.get("mirror_lines_min") or 0)),
        # A run of very short silent stills in the middle of the story (the grind in flashes):
        # {name: ..., count: [min, max]}.
        "flashes": None,
        # An app-screen shot may carry a spoken line (said over the phone in the hand).
        "app_screen_voice": bool(raw.get("app_screen_voice", False)),
    }
    if raw.get("flashes"):
        fl = raw["flashes"]
        if not isinstance(fl, dict):
            raise StepError(f"{where}: rules.flashes must be a mapping with count: [min, max]")
        r["flashes"] = {"name": str(fl.get("name") or "FLASHES"),
                        "count": _pair(fl.get("count"), f"{where}: rules.flashes.count")}
    if raw.get("stats"):
        st = raw["stats"]
        ranks = st.get("ranks") if isinstance(st, dict) else None
        units = st.get("units") if isinstance(st, dict) else None
        if (not isinstance(st, dict) or not isinstance(ranks, list) or not ranks
                or not all(isinstance(x, str) and x.strip() for x in ranks)
                or not isinstance(units, list) or not units
                or not all(isinstance(x, str) and x.strip() for x in units)):
            raise StepError(f"{where}: rules.stats must be a mapping with count: [min, max], "
                            f"ranks: [names, lowest first] and units: [what the number counts]")
        r["stats"] = {"count": _pair(st.get("count"), f"{where}: rules.stats.count"),
                      "ranks": [" ".join(x.upper().split()) for x in ranks],
                      "units": [" ".join(x.upper().split()) for x in units]}
    if raw.get("talking"):
        t = raw["talking"]
        if not isinstance(t, dict) or not isinstance(t.get("max"), int) or t["max"] < 1:
            raise StepError(f"{where}: rules.talking must be a mapping like {{max: 12}}")
        r["talking"] = {"max": int(t["max"])}
    if r["song"] and r["letter"]:
        raise StepError(f"{where}: rules.song and rules.letter cannot both be on")
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
    for key in ("animate_all", "app_screen_hand"):
        if key in f:
            if not isinstance(f[key], bool):
                raise StepError(f"{where}: {key} must be true or false")
            out[key] = f[key]
    if "sfx" in f:
        # true / false, or a block (enabled / source / volume). Always handed on as a block, so
        # config.local.yaml can change one setting without switching the effects off.
        if isinstance(f["sfx"], bool):
            out["sfx"] = {"enabled": f["sfx"]}
        elif isinstance(f["sfx"], dict):
            out["sfx"] = dict(f["sfx"])
        else:
            raise StepError(f"{where}: sfx must be true, false, or a block with enabled / source / volume")
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
    stat = f.get("stat") or {}
    if stat:
        if not isinstance(stat, dict):
            raise StepError(f"{where}: stat must be a mapping of progress-overlay settings")
        for key, value in stat.items():
            asm[f"stat_{key}"] = value
    labels = f.get("labels") or {}
    if labels:
        if not isinstance(labels, dict):
            raise StepError(f"{where}: labels must be a mapping of label settings")
        for key, value in labels.items():
            asm[f"label_{key}"] = value
    letter = f.get("letter") or {}
    if letter:
        if not isinstance(letter, dict):
            raise StepError(f"{where}: letter must be a mapping of letter-card settings")
        for key, value in letter.items():
            asm[f"letter_{key}"] = value
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


# Never taken from the format a format extends: these describe the format itself.
_OWN_KEYS = ("name", "title", "description", "duration_target", "beats", "extends", "references")


def _references(raw, where: str) -> list[dict]:
    """references: the videos a format is modelled on, as [{url, note}] (a bare URL is fine).
    Shown in the UI and the README; nothing in the pipeline reads them."""
    out = []
    for i, item in enumerate(raw or []):
        if isinstance(item, str):
            url, note = item, ""
        elif isinstance(item, dict):
            url, note = item.get("url"), item.get("note") or ""
        else:
            url, note = None, ""
        if not isinstance(url, str) or not re.match(r"https?://\S+$", url.strip()):
            raise StepError(f"{where}: references[{i}] must be a web address, or {{url: ..., note: ...}}")
        out.append({"url": url.strip(), "note": " ".join(str(note).split())})
    return out


def _merge(base: dict, over: dict) -> dict:
    """`over` on top of `base`: mappings merge key by key, everything else is replaced."""
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _read_yaml(name: str) -> tuple[dict, Path, str]:
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
    return f, folder, where


def load_format(name: str | None = None) -> dict:
    name = (name or DEFAULT_FORMAT).strip()
    f, folder, where = _read_yaml(name)

    # extends: start from another format's settings and files. One level only, so a format's
    # full definition is never more than two files away.
    folders = [folder]
    base_name = f.get("extends")
    if base_name is not None:
        if not isinstance(base_name, str) or not base_name.strip() or base_name.strip() == name:
            raise StepError(f"{where}: extends must name another installed format, got {base_name!r}")
        base_name = base_name.strip()
        try:
            base, base_folder, _ = _read_yaml(base_name)
        except StepError as e:
            raise StepError(f"{where}: extends {base_name!r}: {e}") from e
        if base.get("extends") is not None:
            raise StepError(f"{where}: extends {base_name!r}, which extends another format itself; "
                            f"extend {base['extends']!r} directly")
        f = _merge({k: v for k, v in base.items() if k not in _OWN_KEYS}, f)
        folders.append(base_folder)

    texts = {}
    for key, file in (("script_prompt", "script_prompt.md"), ("shot_rules", "shot_rules.md")):
        path = next((d / file for d in folders if (d / file).is_file()), None)
        if path is None:
            raise StepError(f"formats/{name}/{file} is missing")
        texts[key] = _read_text(path)
    blocks = {}
    for d in reversed(folders):                 # its own blocks win over the ones it inherits
        blocks.update({p.stem: _read_text(p) for p in sorted((d / "blocks").glob("*.md"))})
    examples = sorted(p.name for p in (folder / "examples").glob("*")) if (folder / "examples").is_dir() else []
    cover = next((d / f"cover.{ext}" for d in folders for ext in COVER_EXTS
                  if (d / f"cover.{ext}").is_file()), None)
    example_video = folder / "example.mp4" if (folder / "example.mp4").is_file() else None

    return {
        "name": name,
        "dir": folder,
        "file": where,
        "extends": base_name,
        "title": str(f.get("title") or name.replace("_", " ").title()),
        "description": " ".join(str(f.get("description") or "").split()),
        "duration_target": str(f.get("duration_target") or ""),
        "aspect": str(f.get("aspect") or ""),
        "clip_seconds": f.get("clip_seconds"),
        "cast": f.get("cast", "locked"),
        "beats": [str(b) for b in (f.get("beats") or [])],
        "references": _references(f.get("references"), where),
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
