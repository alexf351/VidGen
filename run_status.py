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


def app_preview(run_dir: Path, n: int, shot: dict) -> Path | None:
    """What an app-screen shot looks like in the video: the screenshot on the phone in the
    hand picture, once the images step has drawn the hand. Made on first look and kept in the
    run's app/ folder; None while there is no hand picture (or it has no clean green screen)."""
    import phone_hand
    from common import ROOT
    try:
        hand = phone_hand.run_path(run_dir)
        if shot.get("texts"):
            import phone_texts
            src = run_dir / "app" / f"texts_{n:02d}.png"
            shape = phone_hand.screen_shape(hand, 540, 960) if hand.is_file() else None
            key = f"v2 {shape} {shot['texts']!r}"          # drawn again when the words or the phone change
            note = src.with_suffix(".txt")
            if not src.is_file() or not note.is_file() or note.read_text(encoding="utf-8") != key:
                phone_texts.render(shot["texts"], src, shape=shape)
                note.write_text(key, encoding="utf-8")
            if not hand.is_file():
                return src                 # no hand yet: the screen on its own
        else:
            src = ROOT / str(shot.get("app_screen") or "")
        if not hand.is_file() or not src.is_file():
            return None
        out = run_dir / "app" / f"preview_{n:02d}_{src.stem}.jpg"
        if not out.is_file() or out.stat().st_mtime < max(hand.stat().st_mtime, src.stat().st_mtime):
            if phone_hand.compose(hand, src, out, 540, 960) is None:
                return None
        return out
    except Exception:          # a preview must never break the run page
        return None


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
            "engine": "ai", "cast": [], "screens": [], "ready_script": None}
    try:
        if (run_dir / "run.json").is_file():
            data = read_json(run_dir / "run.json")
            meta.update({k: data.get(k) for k in ("premise", "created_at") if data.get(k)})
            meta["format"] = data.get("format") or "pixar_arc"
            meta["engine"] = data.get("engine") or "ai"
            meta["cast"] = data.get("cast") or []
            meta["screens"] = [p for p in (data.get("screens") or []) if isinstance(p, str)]
            meta["ready_script"] = data.get("ready_script") if isinstance(data.get("ready_script"), str) else None
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
    return bool(shot.get("card") or shot.get("app_screen") or shot.get("texts"))


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


def _view(run_dir: Path, config: dict | None) -> dict | None:
    """script.json as the steps will treat it: with "every shot is a clip" on, every drawn shot
    counts as animated even if the script was written before that (nothing is saved here)."""
    script = load_script(run_dir)
    from steps.script import apply_animate_all
    apply_animate_all(script, config)
    return script


def summary(run_dir: Path, config: dict | None) -> dict:
    meta = run_meta(run_dir)
    if meta["engine"] == "claude_code":
        return code_summary(run_dir, meta, config)
    script = _view(run_dir, config)
    c = cost(run_dir, script, config)
    return {**meta, "steps": step_status(run_dir, script),
            "shots": len(script["shots"]) if script else 0,
            "final_video": file_url(run_dir / "final.mp4"), "est_cost": c["total"]}


def _caption_style(run_dir: Path, config: dict | None) -> str:
    import caption_styles
    return caption_styles.for_run(run_dir, config or {})


def _caption_words(run_dir: Path, config: dict | None) -> int:
    """How many words a caption shows at a time in this video (its own choice, else the format's)."""
    try:
        import caption_styles
        return caption_styles.words_for_run(run_dir, (config or {}).get("assemble") or {})
    except Exception:
        return 1


def _caption_size(run_dir: Path) -> float:
    try:
        import caption_styles
        return caption_styles.size_for_run(run_dir)
    except Exception:
        return 1.0


def _clip_sound_on(run_dir: Path, config: dict | None) -> bool:
    try:
        import clip_sound
        return clip_sound.on(config or {}, run_dir)
    except Exception:
        return False


def detail(run_dir: Path, config: dict | None) -> dict:
    meta = run_meta(run_dir)
    if meta["engine"] == "claude_code":
        return code_detail(run_dir, meta, config)
    try:
        import shot_order
        shot_order.repair(run_dir)          # files a cut-short move left parked go back first
    except Exception:
        pass
    script = _view(run_dir, config)
    shots = []
    for s in (script or {}).get("shots", []):
        if not isinstance(s, dict) or not isinstance(s.get("n"), int):
            continue
        n = s["n"]
        timing = None
        own_voice = False                     # the line is the clip's own (clip_sound.py)
        stumble = None                        # ... but the clip did not say it cleanly
        clip_said = None                      # the clip said something else, so a voice was added
        trusted = False                       # the clip's voice is used because you said so
        tp = timing_path(run_dir, n)
        if tp.is_file():
            try:
                data = read_json(tp)
                timing = data.get("words")
                own_voice = data.get("source") == "clip"
                if own_voice and isinstance(data.get("stumble"), str) and data["stumble"]:
                    stumble = {"why": data["stumble"], "said": str(data.get("said") or "")}
                trusted = bool(own_voice and data.get("trusted"))
                if not own_voice and isinstance(data.get("clip_said"), str):
                    clip_said = data["clip_said"]
            except (OSError, ValueError, AttributeError):
                timing = None
        kind = ("card" if s.get("card") else "app_screen" if s.get("app_screen") else "texts" if s.get("texts")
                else "montage" if s.get("montage") else "flash" if s.get("flash")
                else "letter" if s.get("letter") else "shot")
        preview = app_preview(run_dir, n, s) if kind in ("app_screen", "texts") else None
        shots.append({"n": n, "kind": kind, "shot": s, "own_voice": own_voice, "stumble": stumble, "clip_said": clip_said, "trusted": trusted,
                      "image": file_url(preview) if preview else file_url(shot_path(run_dir, n)),
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
            "caption_style": _caption_style(run_dir, config),
            "caption_words": _caption_words(run_dir, config),
            "caption_size": _caption_size(run_dir),
            "animate_all": bool((config or {}).get("animate_all")),
            # app-screen shots go on a phone in the hero's hand (the hand is drawn by the images step)
            "app_hand": bool((config or {}).get("app_screen_hand")),
            # clips made with their own sound, lines taken from them (clip_sound.py)
            "clip_sound": _clip_sound_on(run_dir, config),
            "sfx": bool(((config or {}).get("sfx") or {}).get("enabled")),
            # ranks and units for the progress overlay, when the format has one
            "stats": (((config or {}).get("format") or {}).get("rules") or {}).get("stats"),
            "cost": cost(run_dir, script, config)}
