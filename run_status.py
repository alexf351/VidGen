"""Read-only view of a run folder for the local server: what each step has produced, file URLs,
and the cost estimate. It only looks at the files the steps write; it never runs a step."""

from __future__ import annotations

from pathlib import Path

from common import read_json, runs_dir
from steps.assemble import cost_report
from steps.images import needs_keyframe, sheet_path, shot_path
from steps.video import video_path
from steps.voice import audio_path, timing_path

STEP_NAMES = ("script", "images", "video", "voice", "assemble")


def file_url(path: Path) -> str | None:
    """/files/<path under the output dir>?v=<mtime>, or None if the file does not exist."""
    try:
        rel = path.resolve().relative_to(runs_dir().resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    return f"/files/{rel.as_posix()}?v={int(path.stat().st_mtime)}"


def is_run_dir(path: Path) -> bool:
    return path.is_dir() and not path.name.startswith(".") and (
        (path / "run.json").is_file() or (path / "premise.txt").is_file())


def run_meta(run_dir: Path) -> dict:
    meta = {"run_id": run_dir.name, "premise": "", "format": "pixar_arc", "created_at": None,
            "engine": "ai", "cast": []}
    try:
        if (run_dir / "run.json").is_file():
            data = read_json(run_dir / "run.json")
            meta.update({k: data.get(k) for k in ("premise", "created_at") if data.get(k)})
            meta["format"] = data.get("format") or "pixar_arc"
            meta["engine"] = data.get("engine") or "ai"
            meta["cast"] = data.get("cast") or []
        elif (run_dir / "premise.txt").is_file():
            meta["premise"] = (run_dir / "premise.txt").read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        pass
    if not meta["created_at"]:
        from datetime import datetime
        meta["created_at"] = datetime.fromtimestamp(run_dir.stat().st_mtime).isoformat(timespec="seconds")
    return meta


def load_script(run_dir: Path) -> dict | None:
    path = run_dir / "script.json"
    if not path.is_file():
        return None
    try:
        data = read_json(path)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("shots"), list) else None


def _special(shot: dict) -> bool:
    return bool(shot.get("card") or shot.get("app_screen"))


def _status(done: int, total: int) -> dict:
    status = ("n/a" if total == 0 else "done" if done >= total else "partial" if done else "pending")
    return {"status": status, "done": done, "total": total}


def step_status(run_dir: Path, script: dict | None) -> dict:
    final = run_dir / "final.mp4"
    if script is None:
        out = {name: _status(0, 1) for name in STEP_NAMES}
        out["script"] = _status(0, 1)
        if final.is_file():
            out["assemble"] = _status(1, 1)
        return out
    shots = [s for s in script["shots"] if isinstance(s, dict) and isinstance(s.get("n"), int)]
    drawn = [s for s in shots if not _special(s) and needs_keyframe(s)]
    moving = [s for s in shots if not _special(s) and (s.get("talk") or (s.get("animate") and needs_keyframe(s)))]
    spoken = [s for s in shots if not _special(s) and str(s.get("vo_line") or "").strip()]
    if isinstance(script.get("song"), dict):
        from steps.song import song_plan
        voice = _status(int(song_plan(run_dir) is not None), 1)
    else:
        voice = _status(sum(audio_path(run_dir, s["n"]).is_file() for s in spoken), len(spoken))
    return {
        "script": _status(1, 1),
        "images": _status(sum(shot_path(run_dir, s["n"]).is_file() for s in drawn), len(drawn)),
        "video": _status(sum(video_path(run_dir, s["n"]).is_file() for s in moving), len(moving)),
        "voice": voice,
        "assemble": _status(int(final.is_file()), 1),
    }


def cost(run_dir: Path, script: dict | None, config: dict | None) -> dict:
    """The assemble step's estimate for what has been generated so far, at today's prices."""
    if script is None or config is None:
        return {"rows": [], "total": 0.0}
    try:
        rows = cost_report(run_dir, script, config)
    except (OSError, ValueError, KeyError, TypeError):
        return {"rows": [], "total": None}
    return {"rows": [{"item": name, "usd": round(usd, 4)} for name, usd in rows],
            "total": round(sum(u for _, u in rows), 4)}


# ------------------------------------------------------- Claude Code engine ----

def _code_cost(run_dir: Path, story: dict | None, config: dict | None) -> dict:
    import code_engine
    st = code_engine.read_status(run_dir)
    rows = [{"item": "Claude Code (your Claude plan, no per-video charge)", "usd": 0.0}]
    voiced = (st.get("voice") or {}).get("value") == "voiced"
    if voiced and story and config:
        chars = len(" ".join(b.get("line", "") for b in story.get("beats", [])))
        rows.append({"item": f"voice ({chars} chars)",
                     "usd": round(chars / 1000 * float(config["elevenlabs"]["cost_per_1k_chars"]), 4)})
    return {"rows": rows, "total": round(sum(r["usd"] for r in rows), 4)}


def code_summary(run_dir: Path, meta: dict, config: dict | None) -> dict:
    import code_engine
    story = code_engine.read_story(run_dir)
    return {**meta, "steps": code_engine.step_states(run_dir),
            "shots": len(story["beats"]) if story else 0,
            "final_video": file_url(run_dir / "final.mp4"),
            "est_cost": _code_cost(run_dir, story, config)["total"]}


def code_detail(run_dir: Path, meta: dict, config: dict | None) -> dict:
    import code_engine
    ws = code_engine.workspace(run_dir)
    story = code_engine.read_story(run_dir)
    notes = None
    if (ws / "story.md").is_file() and story is not None:
        try:
            notes = (ws / "story.md").read_text(encoding="utf-8")[:20000]
        except OSError:
            notes = None
    stills = [{"name": p.name, "url": file_url(p)} for p in sorted((ws / "stills").glob("*.jpg"))]
    styles = (((config or {}).get("format") or {}).get("code_render") or {}).get("styles") or []
    return {**meta, "steps": code_engine.step_states(run_dir), "story": story, "story_notes": notes,
            "styles": styles, "stills": stills, "voice": file_url(ws / "voice.mp3"),
            "script": None, "characters": [], "shots": [],
            "final_video": file_url(run_dir / "final.mp4"), "captions": None,
            "cost": _code_cost(run_dir, story, config)}


def summary(run_dir: Path, config: dict | None) -> dict:
    meta = run_meta(run_dir)
    if meta["engine"] == "claude_code":
        return code_summary(run_dir, meta, config)
    script = load_script(run_dir)
    c = cost(run_dir, script, config)
    return {**meta, "steps": step_status(run_dir, script),
            "shots": len(script["shots"]) if script else 0,
            "final_video": file_url(run_dir / "final.mp4"), "est_cost": c["total"]}


def detail(run_dir: Path, config: dict | None) -> dict:
    meta = run_meta(run_dir)
    if meta["engine"] == "claude_code":
        return code_detail(run_dir, meta, config)
    script = load_script(run_dir)
    shots = []
    for s in (script or {}).get("shots", []):
        if not isinstance(s, dict) or not isinstance(s.get("n"), int):
            continue
        n = s["n"]
        timing = None
        tp = timing_path(run_dir, n)
        if tp.is_file():
            try:
                timing = read_json(tp).get("words")
            except (OSError, ValueError):
                timing = None
        kind = ("card" if s.get("card") else "app_screen" if s.get("app_screen")
                else "montage" if s.get("montage") else "letter" if s.get("letter") else "shot")
        shots.append({"n": n, "kind": kind, "shot": s,
                      "image": file_url(shot_path(run_dir, n)),
                      "clip": file_url(video_path(run_dir, n)),
                      "audio": file_url(audio_path(run_dir, n)),
                      "words": timing})
    characters = []
    for c in (script or {}).get("characters", []):
        if isinstance(c, dict) and isinstance(c.get("id"), str):
            characters.append({**c, "sheet": file_url(sheet_path(run_dir, c["id"]))})
    song = None
    if isinstance((script or {}).get("song"), dict):
        from steps.song import song_path
        song = {"style": script["song"].get("style", ""), "audio": file_url(song_path(run_dir))}
    import voice_cast
    voices = voice_cast.summary(run_dir, config, script) if config else []
    return {**meta, "steps": step_status(run_dir, script), "script": script, "song": song,
            "voices": voices,
            "characters": characters, "shots": shots,
            "final_video": file_url(run_dir / "final.mp4"),
            "captions": file_url(run_dir / "build" / "captions.ass"),
            "cost": cost(run_dir, script, config)}
