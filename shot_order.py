"""Move a shot to another place in a run, keeping everything already made for it.

A run's files are named by shot number (shots/3.png, shots/3.mp4, audio/3.mp3, audio/3.json),
so changing the order in script.json alone would put every picture on the wrong line. This
renumbers the script and renames the files together. Nothing is generated and nothing is paid
for; assemble again to get the video in the new order.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

from common import StepError, available_app_screens, read_json, write_json

NUMBERED = re.compile(r"^(\d+)(\..+)$")


def validate_for_run(run_dir: Path, config: dict, script: dict) -> dict:
    """The format's check, with the cast descriptions this run was written with (a run keeps
    its own; Recast is how it takes a format's new description). Raises ValueError."""
    import steps.script as S
    try:
        current = read_json(run_dir / "script.json")
    except (OSError, ValueError):
        current = {}
    mine = {c.get("id"): c.get("description") for c in (current.get("characters") or [])
            if isinstance(c, dict) and isinstance(c.get("description"), str) and c["description"].strip()}
    locked = [{**c, "description": mine.get(c["id"], c["description"])} for c in config.get("locked_characters", [])]
    return S.validate_and_normalize(
        script, config["style"], int(config["max_animated_shots"]), locked,
        available_app_screens(config), config["format"]["rules"], animate_all=bool(config.get("animate_all")))


def _folders(run_dir: Path) -> list[Path]:
    from steps.images import shots_dir
    from steps.voice import audio_dir
    return [shots_dir(run_dir), audio_dir(run_dir)]


def _keep_scenes(old: list[dict], order: list[int], new: list[dict]) -> None:
    """A scene stays a scene after a move. "same_scene" says a shot continues the scene of the
    shot before it, so swapping a scene's first two shots would otherwise cut the scene in two
    (and a picture redone later would lose its reference). Each shot keeps the scene it was in:
    it continues the one before it when they were in the same scene, and starts one otherwise."""
    import steps.script as S

    def drawn(s: dict) -> bool:
        return (isinstance(s, dict) and not s.get("card") and not s.get("app_screen") and not s.get("montage")
                and bool(str(s.get("image_prompt") or "").strip()))

    scene_of: dict[int, int] = {}                  # old index -> index of its scene's first shot
    for i, s in enumerate(old):
        if drawn(s):
            anchor = S.scene_anchor(old, i) if s.get("same_scene") is True else None
            scene_of[i] = i if anchor is None else anchor
    current = None
    for pos, s in enumerate(new):
        if not isinstance(s, dict) or s.get("card") or s.get("montage"):
            current = None
            continue
        if not drawn(s):
            continue                                # an app screenshot is a cutaway
        mine = scene_of.get(order[pos] - 1)
        if current is not None and mine == current and not s.get("flash"):
            s["same_scene"] = True
        else:
            s.pop("same_scene", None)
            current = mine


def _rename(src: Path, dest: Path, tries: int = 10, wait: float = 0.4) -> None:
    """Rename, waiting out a short lock. On Windows a file cannot be renamed while something
    has it open: the server while the browser is still loading a clip, a virus scanner, a
    media player. Most of those let go within a second or two."""
    import time
    for attempt in range(tries):
        try:
            src.replace(dest)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(wait)


def repair(run_dir: Path) -> int:
    """Put back files a move left parked (".moving-3.mp4") when it was cut short: the server
    was closed mid-move, or an older version failed half way. Each goes back to its own name
    when that name is free. Returns how many were put back."""
    back = 0
    for folder in _folders(run_dir):
        if not folder.is_dir():
            continue
        for f in sorted(folder.iterdir()):
            if not f.is_file() or not f.name.startswith(".moving-"):
                continue
            home = f.with_name(f.name[len(".moving-"):])
            if NUMBERED.match(home.name) and not home.exists():
                try:
                    f.replace(home)
                    back += 1
                except OSError:
                    pass
    return back


def move(run_dir: Path, config: dict, n: int, to: int) -> dict:
    """Shot `n` becomes shot `to`; the shots between shift by one. Returns
    {"moved": n, "to": to, "files": how many files were renamed, "script": the new script}."""
    path = run_dir / "script.json"
    if not path.is_file():
        raise StepError("this run has no script yet")
    script = read_json(path)
    shots = script.get("shots") or []
    count = len(shots)
    for name, value in (("shot", n), ("new place", to)):
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= count:
            raise StepError(f"{name} must be a number from 1 to {count}")
    if n == to:
        raise StepError(f"shot {n} is already there")

    order = list(range(1, count + 1))          # order[i] = the old number of the shot now at i + 1
    order.insert(to - 1, order.pop(n - 1))
    moved = copy.deepcopy(script)
    moved["shots"] = [copy.deepcopy(shots[old - 1]) for old in order]
    for i, s in enumerate(moved["shots"], start=1):
        s["n"] = i
    _keep_scenes(shots, order, moved["shots"])
    try:
        clean = validate_for_run(run_dir, config, moved)
    except ValueError as e:
        why = "; ".join(line[2:] if line.startswith("- ") else line for line in str(e).splitlines() if line.strip())
        raise StepError(f"shot {n} cannot go to place {to}: the script would no longer pass the "
                        f"{config['format'].get('title') or config['format']['name']} rules ({why})") from None

    new_of = {old: new for new, old in enumerate(order, start=1) if old != new}
    plan: list[tuple[Path, Path, Path]] = []                 # (file now, parked name, final name)
    for folder in _folders(run_dir):
        if not folder.is_dir():
            continue
        for f in sorted(folder.iterdir()):
            m = NUMBERED.match(f.name)
            if not f.is_file() or not m or int(m.group(1)) not in new_of:
                continue
            new = new_of[int(m.group(1))]
            plan.append((f, f.with_name(f".moving-{f.name}"), f.with_name(f"{new}{m.group(2)}")))
    repair(run_dir)                                          # a move that was cut short earlier
    # Two passes, so 1 -> 2 and 2 -> 1 never land on each other. If any file cannot be renamed
    # (Windows refuses while a clip is still open in the browser or another program), every
    # rename already made is undone: a move happens whole or not at all.
    done: list[tuple[Path, Path]] = []
    try:
        for src, parked, _ in plan:
            _rename(src, parked)
            done.append((src, parked))
        for _, parked, dest in plan:
            _rename(parked, dest)
            done.append((parked, dest))
        write_json(path, clean)
    except OSError as e:
        for before, after in reversed(done):
            try:
                _rename(after, before, tries=3)
            except OSError:
                pass                                         # repair() picks it up on the next look
        stuck = Path(getattr(e, "filename", "") or "").name
        raise StepError(f"shot {n} was not moved: {stuck or 'one of its files'} is in use (a clip still open in the "
                        f"browser, or another program). Nothing was changed. Reload the page and try again.") from None
    # In-hand previews are named by shot number; they are remade on the next look.
    app = run_dir / "app"
    if app.is_dir():
        for f in app.iterdir():
            if f.is_file() and re.match(r"^preview_\d+_.*\.jpg$", f.name):
                f.unlink()
    return {"moved": n, "to": to, "files": len(plan), "script": clean}
