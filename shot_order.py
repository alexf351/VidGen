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


EDIT_MAX_SHOTS = 60          # story shots a hand-edited script may grow to
EDIT_MAX_WORDS = 400         # and spoken words


def edit_rules(rules: dict) -> dict:
    """The format's rules as they bind a script someone is editing by hand. How many shots and
    words a script has, and how many silent shots may follow each other, are targets for
    whoever WRITES it; once it is your script you may add a scene or a line past them. What
    makes the format what it is (its one time card, its progress shots, its montage, the lines
    that come back) still holds. The closing call-to-action shot is yours to keep or remove."""
    out = dict(rules)
    out["story_shots"] = [1, max(int(rules["story_shots"][1]), EDIT_MAX_SHOTS)]
    out["vo_words"] = [0, max(int(rules["vo_words"][1]), EDIT_MAX_WORDS)]
    out["silent_run_max"] = 0
    out["closing_free"] = True                 # the closing call-to-action shot may be taken off, or kept
    return out


def validate_for_run(run_dir: Path, config: dict, script: dict) -> dict:
    """The format's check for a script that is being edited (edit_rules), with the cast
    descriptions this run was written with (a run keeps its own; Recast is how it takes a
    format's new description). Raises ValueError."""
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
        available_app_screens(config), edit_rules(config["format"]["rules"]), animate_all=bool(config.get("animate_all")))


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
            if f.is_file() and f.name.startswith(".removed-"):
                try:
                    f.unlink()                 # a removed shot's file that could not be deleted then
                except OSError:
                    pass
                continue
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


def _why_locked(target: Path, free_leftovers: bool) -> tuple[str, bool]:
    """What has `target` open, in words, and whether something was done about it. With
    `free_leftovers` (no job is working on this run), an ffmpeg of VidGen's own that still
    holds the file is one a hung job left behind, and it is ended."""
    import os
    import winlock
    found = winlock.holders(target)
    if not found:
        return ("a clip or a voice still open in the browser, a virus scanner, or another program", False)
    if free_leftovers and all(winlock.is_ours(name) for _, name in found):
        ended = winlock.end_leftovers(found)
        if ended:
            print(f"  {target.name} was held open by {winlock.describe(ended)}, left running by an earlier job; ended it")
            return (winlock.describe(ended), True)
    if any(pid == os.getpid() for pid, _ in found):
        return ("VidGen itself, for a clip or voice a browser tab is still loading (close other VidGen tabs, "
                "or restart VidGen)", False)
    return (winlock.describe(found), False)


def move(run_dir: Path, config: dict, n: int, to: int, free_leftovers: bool = False) -> dict:
    """Shot `n` becomes shot `to`; the shots between shift by one. Returns
    {"moved": n, "to": to, "files": how many files were renamed, "script": the new script}.
    `free_leftovers`: the caller knows no job is working on this run, so an ffmpeg that still
    has one of its files open may be ended (see _why_locked)."""
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
    files = _apply(run_dir, clean, new_of, set(), free_leftovers, f"shot {n} was not moved")
    return {"moved": n, "to": to, "files": files, "script": clean}


def _apply(run_dir: Path, clean: dict, new_of: dict[int, int], drop: set[int], free_leftovers: bool, failed: str) -> int:
    """Renumber a run's files and write its script, whole or not at all. `new_of` maps a shot's
    old number to its new one; the files of the shots in `drop` are deleted. `failed` opens the
    error message ("shot 3 was not moved"). Returns how many files were renamed or deleted."""
    path = run_dir / "script.json"
    plan: list[tuple[Path, Path, Path | None]] = []          # (file now, parked name, final name or None = delete)
    for folder in _folders(run_dir):
        if not folder.is_dir():
            continue
        for f in sorted(folder.iterdir()):
            m = NUMBERED.match(f.name)
            if not f.is_file() or not m:
                continue
            old = int(m.group(1))
            if old in drop:
                plan.append((f, f.with_name(f".removed-{f.name}"), None))
            elif old in new_of:
                plan.append((f, f.with_name(f".moving-{f.name}"), f.with_name(f"{new_of[old]}{m.group(2)}")))
    repair(run_dir)                                          # a change that was cut short earlier
    # Two passes, so 1 -> 2 and 2 -> 1 never land on each other. If any file cannot be renamed
    # (Windows refuses while a clip is still open in the browser or another program), every
    # rename already made is undone: a change happens whole or not at all.
    done: list[tuple[Path, Path]] = []

    def undo() -> None:
        for before, after in reversed(done):
            try:
                _rename(after, before, tries=3)
            except OSError:
                pass                                         # repair() picks it up on the next look
        done.clear()

    def go() -> None:
        for src, parked, _ in plan:
            _rename(src, parked)
            done.append((src, parked))
        for _, parked, dest in plan:
            if dest is not None:
                _rename(parked, dest)
                done.append((parked, dest))
        write_json(path, clean)

    try:
        go()
    except OSError as e:
        undo()
        stuck = Path(getattr(e, "filename", "") or "")
        who, freed = _why_locked(stuck, free_leftovers) if stuck.name else ("another program", False)
        if freed:
            import time
            time.sleep(0.6)                                  # Windows lets go of the file a moment after
            try:
                go()
            except OSError as again:
                undo()
                stuck = Path(getattr(again, "filename", "") or stuck)
                freed = False
                who = _why_locked(stuck, False)[0]
        if not freed:
            raise StepError(f"{failed}: {stuck.name or 'one of its files'} is held open by {who}. "
                            f"Nothing was changed. Close that program (Task Manager, End task) or reload "
                            f"this page, then try again.") from None
    for _, parked, dest in plan:
        if dest is None:
            try:
                parked.unlink()
            except OSError:
                pass                                         # repair() deletes it on the next look
    # In-hand previews and drawn chat screens are named by shot number; they are remade on the next look.
    app = run_dir / "app"
    if app.is_dir():
        for f in app.iterdir():
            if f.is_file() and re.match(r"^(preview_\d+_.*\.jpg|texts_\d+\.(png|txt))$", f.name):
                f.unlink()
    return len(plan)


def _problems(e: ValueError) -> str:
    return "; ".join(line[2:] if line.startswith("- ") else line for line in str(e).splitlines() if line.strip())


def _load(run_dir: Path) -> tuple[dict, list[dict]]:
    path = run_dir / "script.json"
    if not path.is_file():
        raise StepError("this run has no script yet")
    script = read_json(path)
    return script, script.get("shots") or []


def insert(run_dir: Path, config: dict, after: int, shot: dict, free_leftovers: bool = False) -> dict:
    """Add `shot` after shot `after` (0 = before the first). Every later shot moves down one and
    keeps its picture, clip and voice. Returns {"added": its number, "files", "script"}."""
    script, shots = _load(run_dir)
    count = len(shots)
    if not isinstance(after, int) or isinstance(after, bool) or not 0 <= after <= count:
        raise StepError(f"the place must be a number from 0 to {count}")
    added = copy.deepcopy(script)
    new = copy.deepcopy(shot)
    following = shots[after] if after < count else None
    if (str(new.get("image_prompt") or "").strip() and isinstance(following, dict)
            and following.get("same_scene") is True and after > 0):
        new["same_scene"] = True            # inside a scene: the shots after it must still continue that scene
    added["shots"] = [copy.deepcopy(x) for x in shots[:after]] + [new] + [copy.deepcopy(x) for x in shots[after:]]
    for i, s in enumerate(added["shots"], start=1):
        s["n"] = i
    try:
        clean = validate_for_run(run_dir, config, added)
    except ValueError as e:
        raise StepError(f"the shot was not added: the script would no longer pass the "
                        f"{config['format'].get('title') or config['format']['name']} rules ({_problems(e)})") from None
    new_of = {old: old + 1 for old in range(after + 1, count + 1)}
    files = _apply(run_dir, clean, new_of, set(), free_leftovers, "the shot was not added")
    return {"added": after + 1, "files": files, "script": clean}


def remove(run_dir: Path, config: dict, n: int, free_leftovers: bool = False) -> dict:
    """Take shot `n` out, with its picture, clip and voice. The shots after it move up one.
    Returns {"removed": n, "files", "script"}."""
    script, shots = _load(run_dir)
    count = len(shots)
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= count:
        raise StepError(f"shot must be a number from 1 to {count}")
    order = [k for k in range(1, count + 1) if k != n]
    cut = copy.deepcopy(script)
    cut["shots"] = [copy.deepcopy(shots[old - 1]) for old in order]
    for i, s in enumerate(cut["shots"], start=1):
        s["n"] = i
    _keep_scenes(shots, order, cut["shots"])
    try:
        clean = validate_for_run(run_dir, config, cut)
    except ValueError as e:
        raise StepError(f"shot {n} was not removed: without it the script would no longer pass the "
                        f"{config['format'].get('title') or config['format']['name']} rules ({_problems(e)})") from None
    new_of = {old: old - 1 for old in range(n + 1, count + 1)}
    files = _apply(run_dir, clean, new_of, {n}, free_leftovers, f"shot {n} was not removed")
    return {"removed": n, "files": files, "script": clean}
