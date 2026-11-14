"""A video made from a ready-made script keeps its own copy of that script. When the ready-made
script is improved afterwards (a shot rewritten, one added, one taken out), this brings the
video up to date with it and keeps every picture, clip and voice line of the shots that did not
change. Nothing is generated here: what is new is made by the steps afterwards.

    plan(run_dir, config)     what an update would do, or None when there is nothing to update
    apply(run_dir, config)    do it: swap the script, renumber the files, drop what is out of date

A shot is the same shot when its picture is described the same way (and it has the same people,
card, app screen or messages). Its picture is then kept. Its clip and its line are kept too when
the movement and the words are the same; when only those changed, the clip and the line are
made again from the picture it already has.

Changes you made to the video's own script by hand are not carried over: the video gets the
ready-made script as it is now."""

from __future__ import annotations

import difflib
import json
from pathlib import Path

from common import StepError, read_json, run_ready_script, write_json


def _picture_key(shot: dict) -> str:
    return json.dumps([str(shot.get("image_prompt") or "").strip(), list(shot.get("characters") or []),
                       str(shot.get("card") or ""), str(shot.get("app_screen") or ""), shot.get("texts") or None,
                       bool(shot.get("flash")), bool(shot.get("montage"))], sort_keys=True)


def _clip_key(shot: dict) -> str:
    return json.dumps([str(shot.get("motion_prompt") or "").strip(), str(shot.get("vo_line") or "").strip(),
                       str(shot.get("speaker") or "")])


def _other_key(shot: dict) -> str:
    """Everything else that is only read when the video is put together (a label, a caption)."""
    skip = {"n", "image_prompt", "characters", "card", "app_screen", "texts", "flash", "montage",
            "motion_prompt", "vo_line", "speaker"}
    return json.dumps({k: v for k, v in shot.items() if k not in skip}, sort_keys=True, default=str)


def plan(run_dir: Path, config: dict | None) -> dict | None:
    """What bringing this video up to date with its ready-made script would do, or None when it
    was not made from one, the script is gone, or the two are already the same.

    {"id", "title", "script": the new script, "new_of": {old shot: new shot} for the shots kept,
     "kept": how many shots keep their picture, "pictures": [new shots that need a picture],
     "clips": [new shots whose clip and line are made again from the picture they have],
     "removed": [old shots that are gone], "shots": how many shots the new script has}"""
    script_id = run_ready_script(run_dir)
    path = Path(run_dir) / "script.json"
    if not script_id or config is None or not path.is_file():
        return None
    import ready_scripts
    try:
        new, info = ready_scripts.build(config, script_id)
        old = read_json(path)
    except (StepError, OSError, ValueError):
        return None                                   # the script was renamed or no longer passes: nothing to offer
    old_shots = [s for s in (old.get("shots") or []) if isinstance(s, dict)]
    new_shots = new["shots"]
    a, b = [_picture_key(s) for s in old_shots], [_picture_key(s) for s in new_shots]
    new_of: dict[int, int] = {}
    for block in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(block.size):
            new_of[old_shots[block.a + k]["n"]] = new_shots[block.b + k]["n"]
    by_old = {s["n"]: s for s in old_shots}
    by_new = {s["n"]: s for s in new_shots}
    clips = sorted(n2 for n1, n2 in new_of.items() if _clip_key(by_old[n1]) != _clip_key(by_new[n2]))
    kept_new = set(new_of.values())
    drawn = lambda s: bool(str(s.get("image_prompt") or "").strip())
    pictures = sorted(s["n"] for s in new_shots if s["n"] not in kept_new and drawn(s))
    added = sorted(s["n"] for s in new_shots if s["n"] not in kept_new)
    removed = sorted(n for n in by_old if n not in new_of)
    moved = any(n1 != n2 for n1, n2 in new_of.items())
    other = any(_other_key(by_old[n1]) != _other_key(by_new[n2]) for n1, n2 in new_of.items())
    if not (added or removed or clips or moved or other):
        return None
    return {"id": script_id, "title": info.get("title") or script_id, "script": new, "new_of": new_of,
            "kept": len(new_of), "pictures": pictures, "added": added, "clips": clips, "removed": removed,
            "shots": len(new_shots)}


_SEEN: dict[str, tuple[tuple, dict | None]] = {}       # the page asks every second or two while a job runs


def _stamp(run_dir: Path, config: dict | None) -> tuple:
    """Changes whenever the answer could: the video's script, the ready-made script, the format."""
    from common import ROOT
    name = ((config or {}).get("format") or {}).get("name") or ""
    files = [Path(run_dir) / "script.json", Path(run_dir) / "run.json",
             ROOT / "formats" / name / "scripts" / f"{run_ready_script(run_dir)}.json",
             ROOT / "formats" / name / "format.yaml"]
    out = []
    for f in files:
        try:
            out.append(f.stat().st_mtime_ns)
        except OSError:
            out.append(0)
    return tuple(out)


def summary(run_dir: Path, config: dict | None) -> dict | None:
    """plan() without the script, for the page: counts and shot numbers only."""
    if not run_ready_script(run_dir) or config is None:
        return None
    key, stamp = str(run_dir), _stamp(run_dir, config)
    if key in _SEEN and _SEEN[key][0] == stamp:
        return _SEEN[key][1]
    try:
        p = plan(run_dir, config)
    except Exception:                                 # a page must never fail because of an offer on it
        p = None
    out = None if p is None else {k: p[k] for k in ("id", "title", "kept", "pictures", "added", "clips", "removed", "shots")}
    _SEEN[key] = (stamp, out)
    return out


def apply(run_dir: Path, config: dict, free_leftovers: bool = False) -> dict:
    """Bring the video up to date. Returns the summary of what was done, with "files": how many
    files were renamed or deleted."""
    import shot_order
    from steps.images import shots_dir
    from steps.voice import audio_dir
    p = plan(run_dir, config)
    if p is None:
        raise StepError("this video already has its ready-made script as it is now")
    renumber = {old: new for old, new in p["new_of"].items() if old != new}
    files = shot_order._apply(run_dir, p["script"], renumber, set(p["removed"]), free_leftovers,
                              "the video was not updated")
    # The same picture with a new movement or a new line: its clip and its line are out of date.
    for n in p["clips"]:
        stale = [shots_dir(run_dir) / f"{n}.mp4", shots_dir(run_dir) / f"{n}.mp4.url",
                 audio_dir(run_dir) / f"{n}.mp3", audio_dir(run_dir) / f"{n}.json"]
        for f in stale:
            if f.is_file():
                f.unlink()
                files += 1
    # "Use the clip's voice" was said of a shot by its old number.
    meta_path = Path(run_dir) / "run.json"
    meta = read_json(meta_path)
    if isinstance(meta.get("clip_voice"), list):
        still = sorted({p["new_of"][n] for n in meta["clip_voice"] if n in p["new_of"] and p["new_of"][n] not in p["clips"]})
        if still:
            meta["clip_voice"] = still
        else:
            meta.pop("clip_voice")
        write_json(meta_path, meta)
    return {**{k: p[k] for k in ("id", "title", "kept", "pictures", "added", "clips", "removed", "shots")}, "files": files}
