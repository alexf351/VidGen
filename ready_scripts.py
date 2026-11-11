"""Ready-made scripts: shot lists written by hand for a format, used instead of the script step.

    formats/<format>/scripts/<id>.json

    {
      "title":   "The standup",                      shown in the UI
      "premise": "one or two sentences",             saved as the run's premise
      "shots": [ {...}, ... ]
    }

A shot is written the way the script step writes one, with three shortcuts so a file stays
readable and survives a change to the cast:

  - "image_prompt" leaves out the style line; it is put in front when the script is built.
  - "{marcus}" (any locked character's id in braces) stands for that character's locked
    description, word for word. It is filled in from the format's cast, so recasting a role
    or rewording a description does not break the script.
  - "n", the "characters" list at the top, and the empty fields of a shot ("caption": "",
    "animate": false, ...) are filled in.

The built script goes through the same check as one Claude wrote (steps/script.py), so a
ready-made script can never break a format's rules. Making a video from one costs nothing
for the script: no model is called.
"""

from __future__ import annotations

import re
from pathlib import Path

from common import ROOT, StepError, available_app_screens, read_json

SHOT_DEFAULTS = {"characters": [], "image_prompt": "", "motion_prompt": "", "vo_line": "",
                 "speaker": "", "caption": "", "animate": False}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,40}$")


def _dirs(fmt: dict) -> list[Path]:
    """Where a format's ready-made scripts live: its own scripts/ folder only (a format that
    extends another has its own story shape, so it does not take the base's scripts)."""
    return [ROOT / "formats" / fmt["name"] / "scripts"]


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def _load(path: Path) -> dict:
    try:
        data = read_json(path)
    except (OSError, ValueError) as e:
        raise StepError(f"{_rel(path)} could not be read: {e}") from None
    if not isinstance(data, dict) or not isinstance(data.get("shots"), list) or not data["shots"]:
        raise StepError(f"{_rel(path)} needs a \"shots\" list")
    return data


def listing(fmt: dict) -> list[dict]:
    """The ready-made scripts of a format, for the UI and the command line: id, title, premise
    and a few counts. A file that cannot be read is left out."""
    out = []
    for d in _dirs(fmt):
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            if not ID_RE.match(p.stem):
                continue
            try:
                data = _load(p)
            except StepError:
                continue
            shots = [s for s in data["shots"] if isinstance(s, dict)]
            out.append({
                "id": p.stem,
                "title": str(data.get("title") or p.stem.replace("_", " ").capitalize()),
                "premise": " ".join(str(data.get("premise") or "").split()),
                "shots": len(shots),
                "words": sum(len(str(s.get("vo_line") or "").split()) for s in shots),
                "drawn": sum(1 for s in shots if str(s.get("image_prompt") or "").strip()),
                "app_screens": [str(s["app_screen"]) for s in shots if s.get("app_screen")],
            })
    return out


def _fill(text: str, people: dict[str, str], where: str) -> str:
    def one(m):
        key = m.group(1)
        if key not in people:
            raise StepError(f"{where}: {{{key}}} is not one of this format's characters "
                            f"({', '.join(sorted(people)) or 'it has none'})")
        return people[key]
    return re.sub(r"\{([a-z0-9_]+)\}", one, text)


def build(config: dict, script_id: str) -> tuple[dict, dict]:
    """(script, info) for one ready-made script, built for this config (its style and cast) and
    checked like any other script. info is its listing() entry."""
    fmt = config["format"]
    if not isinstance(script_id, str) or not ID_RE.match(script_id):
        raise StepError(f"ready-made script {script_id!r} is not a valid name")
    path = next((d / f"{script_id}.json" for d in _dirs(fmt) if (d / f"{script_id}.json").is_file()), None)
    if path is None:
        have = ", ".join(e["id"] for e in listing(fmt)) or "none"
        raise StepError(f"the {fmt.get('title') or fmt['name']} format has no ready-made script "
                        f"called {script_id!r} (it has: {have})")
    data = _load(path)
    rel = _rel(path)
    locked = config.get("locked_characters", [])
    people = {c["id"]: c["description"] for c in locked}
    style = str(config["style"]).strip()
    shots = []
    for i, raw in enumerate(data["shots"]):
        if not isinstance(raw, dict):
            raise StepError(f"{rel}: shot {i + 1} must be an object")
        shot = {**SHOT_DEFAULTS, **raw, "n": i + 1}
        picture = _fill(str(shot.get("image_prompt") or "").strip(), people, f"{rel}: shot {i + 1}")
        shot["image_prompt"] = f"{style}, {picture}" if picture else ""
        shot["motion_prompt"] = _fill(str(shot.get("motion_prompt") or "").strip(), people, f"{rel}: shot {i + 1}")
        shot["characters"] = list(shot.get("characters") or [])
        shots.append(shot)
    script = {"characters": [{"id": c["id"], "description": c["description"]} for c in locked], "shots": shots}
    import steps.script as S
    try:
        script = S.validate_and_normalize(script, style, int(config["max_animated_shots"]), locked,
                                          available_app_screens(config), fmt["rules"],
                                          animate_all=bool(config.get("animate_all")))
    except ValueError as e:
        raise StepError(f"{rel} does not pass the {fmt.get('title') or fmt['name']} rules:\n{e}") from None
    info = next(e for e in listing(fmt) if e["id"] == script_id)
    return script, info
