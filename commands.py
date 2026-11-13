"""The CLI's commands as plain functions, shared by main.py and the local server (server.py).

Each takes an already-loaded config (see common.load_config) and prints its progress exactly as
the CLI always has. Errors are raised as StepError.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import progress
from common import STEP_ORDER, StepError, create_run, run_dir_for, run_engine

STEPS_WITH_ONLY = {"images", "video", "voice"}


def step_module(name: str):
    return importlib.import_module(f"steps.{name}")


def run_step(name: str, run_dir: Path, config: dict, only: str | None = None) -> None:
    progress.step(name)
    if run_engine(run_dir) == "claude_code":
        import code_engine
        if only:
            raise StepError("--only is for the image pipeline's steps; a Claude Code run's steps "
                            "work on the whole video")
        code_engine.run_step(name, run_dir, config)
        return
    if name not in STEP_ORDER:
        raise StepError(f"'{name}' is a Claude Code engine step; this run uses the image pipeline "
                        f"({', '.join(STEP_ORDER)})")
    print(f"\n=== step: {name} ({run_dir.name}) ===")
    module = step_module(name)
    if only is None:
        module.run(run_dir, config)
    elif name in STEPS_WITH_ONLY:
        module.run(run_dir, config, only=only)
    else:
        raise StepError(f"--only is supported for {sorted(STEPS_WITH_ONLY)}, not '{name}'")


def pick_screens(config: dict, screens) -> list[str]:
    """The app screenshots a new video pins, checked against the library and the format."""
    if not screens:
        return []
    import app_assets
    from common import available_app_screens
    picks = app_assets.resolve_picks(screens, available_app_screens(config))
    cap = int(config["format"]["rules"]["app_screens"]["max"])
    title = config["format"].get("title") or config["format"]["name"]
    if not cap:
        raise StepError(f"the {title} format shows no app screens, so none can be picked for it")
    if len(picks) > cap:
        raise StepError(f"the {title} format shows at most {cap} app screen{'s' if cap != 1 else ''}; "
                        f"pick {cap} or fewer, got {len(picks)}")
    return picks


def create_new_run(premise: str, config: dict, log=print, engine: str | None = None,
                   captions: str | None = None, screens=None, ready: str | None = None) -> Path:
    """Make the run folder for `new` (premise.txt, run.json with the format, cast, engine,
    caption style and any pinned app screens). With `ready`, the run starts from a ready-made
    script (ready_scripts.py): script.json is written now and the script step is not run."""
    import caption_styles
    captions = caption_styles.check(captions) if captions else None
    script = None
    if ready:
        if engine == "claude_code":
            raise StepError("ready-made scripts are for the image pipeline, not the Claude Code engine")
        if screens:
            raise StepError("a ready-made script already says which app screens it shows; "
                            "swap one in the script editor after the run is made")
        import ready_scripts
        script, info = ready_scripts.build(config, ready)
        premise = (premise or "").strip() or info["premise"] or info["title"]
    screens = pick_screens(config, screens)
    if screens and engine == "claude_code":
        raise StepError("app screens are for the image pipeline; the Claude Code engine does not show them")
    if engine not in (None, "ai", "claude_code"):
        raise StepError(f"engine must be ai or claude_code, got {engine!r}")
    if engine == "claude_code":
        import code_engine
        if not code_engine.offered(config):
            raise StepError(f"the {config['format']['name']} format does not offer the Claude Code "
                            f"engine (its format.yaml has no code_render block)")
    run_dir = create_run(premise, config["format"]["name"], cast=config.get("cast") or None,
                         engine=engine, captions=captions, screens=screens, ready=ready or None)
    if script is not None:
        from common import write_json
        write_json(run_dir / "script.json", script)
    if engine != "claude_code":
        import music
        start_with = music.default()                   # "use for new videos" in the Music panel
        if start_with is not None:
            music.set_for_run(run_dir, start_with)
    log(f"created run {run_dir.name} (format {config['format']['name']}"
        + (", Claude Code engine)" if engine == "claude_code" else ")"))
    log(f"  {run_dir}")
    if screens:
        log(f"  app screens: {', '.join(Path(p).stem for p in screens)}")
    if script is not None:
        log(f"  ready-made script: {info['title']} ({len(script['shots'])} shots, {info['words']} spoken words); "
            f"no script step")
    return run_dir


def run_rest(run_dir: Path, config: dict, names: list[str]) -> None:
    """Run these steps in order. A clip that cannot be made does not throw the others away: the
    clips that were made are kept (video.py), their lines are still read, and the error says
    what is left. One refused clip out of 33 used to stop a video with no voices and no cut."""
    for i, name in enumerate(names):
        try:
            run_step(name, run_dir, config)
        except StepError as e:
            if name != "video" or "voice" not in names[i + 1:]:
                raise
            print(f"error: {e}")
            print("\nNot every clip could be made. The ones that were made are kept: recording the voices now, "
                  "so the shots that failed are all that is left.")
            run_step("voice", run_dir, config)
            raise StepError(f"{e}\nEverything else is made. Reroll the shot that failed (its card on the "
                            f"video's page), then press Finish the video.") from e


def finish(run_id: str, config: dict) -> None:
    """Every step after the script that still has work to do, as one job: the pictures, clips
    and lines that are missing, then the cut. What exists is kept."""
    run_dir = run_dir_for(run_id)
    _image_pipeline_only(run_dir, "finishing the video")
    if not (run_dir / "script.json").is_file():
        raise StepError("this video has no script yet: write the script first")
    rest = [n for n in STEP_ORDER if n != "script"]
    print(f"\n=== finish the video ({run_dir.name}) ===")
    progress.start(rest)
    run_rest(run_dir, config, rest)
    print(f"\nrun {run_dir.name} complete")


def execute_new(run_dir: Path, config: dict, dry_run: bool = False) -> None:
    """Run every step of a new run in order, or only the script step for a dry run."""
    if run_engine(run_dir) == "claude_code":
        import code_engine
        progress.start(code_engine.CODE_STEPS[:1] if dry_run else list(code_engine.CODE_STEPS))
        code_engine.execute(run_dir, config, dry_run)
        return
    from common import run_ready_script
    if run_ready_script(run_dir) and (run_dir / "script.json").is_file():
        # Started from a ready-made script: it is already written and checked. Cast the voices
        # (the script step does that after writing) and carry on with the rest.
        import steps.script as S
        from common import read_json
        script = read_json(run_dir / "script.json")
        print(f"\n=== ready-made script: {run_ready_script(run_dir)} ({run_dir.name}) ===")
        S.print_shot_table(script, config["style"])
        rest = [n for n in STEP_ORDER if n != "script"]
        progress.start([] if dry_run else rest)
        S.cast_voices(run_dir, config, script)
        if dry_run:
            print("\nscript only: the ready-made script is in place; no images, video or voice were generated.")
            print(f"continue this run with:  python main.py step {run_dir.name} images  (then video, voice, assemble)")
            return
        run_rest(run_dir, config, rest)
        print(f"\nrun {run_dir.name} complete")
        return
    progress.start(STEP_ORDER[:1] if dry_run else list(STEP_ORDER))
    if dry_run:
        # Only the script step runs. It calls Claude (a few cents) to write the shot list;
        # nothing is sent to fal, Sume or ElevenLabs.
        run_step("script", run_dir, config)
        print(f"\ndry run: stopped after the script step; no images, video or voice were generated.")
        print(f"continue this run with:  python main.py step {run_dir.name} images  (then video, voice, assemble)")
        return
    run_rest(run_dir, config, list(STEP_ORDER))
    print(f"\nrun {run_dir.name} complete")


def new(premise: str, config: dict, dry_run: bool = False, captions: str | None = None) -> Path:
    run_dir = create_new_run(premise, config, captions=captions)
    execute_new(run_dir, config, dry_run)
    return run_dir


def _spoken_among(run_dir: Path, only: str) -> str:
    """Of the shots named in `only` ("2,4"), the ones that say a line in their own clip."""
    from run_status import load_script
    want = {int(x) for x in only.split(",") if x.strip().isdigit()}
    shots = [s for s in (load_script(run_dir) or {}).get("shots", []) if isinstance(s, dict)]
    return ",".join(str(s["n"]) for s in shots
                    if s.get("n") in want and str(s.get("vo_line") or "").strip() and not s.get("app_screen"))


def step(run_id: str, step_name: str, config: dict, only: str | None = None) -> None:
    run_dir = run_dir_for(run_id)
    run_step(step_name, run_dir, config, only=only)
    # Clip sound: a spoken shot's voice is cut from its clip, so shots whose clip was just made
    # again have their line read again, the same as a reroll does.
    if step_name == "video" and only and run_engine(run_dir) != "claude_code":
        import clip_sound
        if clip_sound.on(config, run_dir):
            spoken = _spoken_among(run_dir, only)
            if spoken:
                print(f"\nClip sound: reading the line again from the new clip of shot{'s' if ',' in spoken else ''} {spoken}.")
                run_step("voice", run_dir, config, only=spoken)


def _image_pipeline_only(run_dir: Path, what: str) -> None:
    if run_engine(run_dir) == "claude_code":
        raise StepError(f"{what} is for the image pipeline; this run uses the Claude Code engine "
                        f"(re-run its scenes step instead)")


def reroll(run_id: str, shot_number: int, config: dict) -> None:
    run_dir = run_dir_for(run_id)
    _image_pipeline_only(run_dir, "reroll")
    print(f"\n=== reroll shot {shot_number} ({run_dir.name}) ===")
    # Clip sound: a spoken shot's voice is cut from its clip, so a new clip needs its line read again.
    import clip_sound
    revoice = False
    if clip_sound.on(config, run_dir):
        from run_status import load_script
        shot = next((s for s in (load_script(run_dir) or {}).get("shots", [])
                     if isinstance(s, dict) and s.get("n") == shot_number), {})
        revoice = bool(str(shot.get("vo_line") or "").strip()) and not shot.get("app_screen")
    progress.start(["images", "video"] + (["voice"] if revoice else []))
    progress.step("images")
    step_module("images").reroll_shot(run_dir, config, shot_number)
    progress.step("video")
    step_module("video").reroll_shot(run_dir, config, shot_number)
    if revoice:
        progress.step("voice")
        step_module("voice").run(run_dir, config, only=str(shot_number))


def remix(run_id: str, config: dict) -> None:
    """The sound of a finished video again, on the picture it already has: new music or new
    levels without waiting for the whole assembly (steps/assemble.py, sound_only)."""
    run_dir = run_dir_for(run_id)
    _image_pipeline_only(run_dir, "the sound mix")
    print(f"\n=== new sound mix ({run_dir.name}) ===")
    progress.start(["assemble"])
    progress.step("assemble")
    step_module("assemble").run(run_dir, config, sound_only=True)


DELETING = ".deleting-"        # a run folder on its way out; hidden from the list of videos


def sweep_deleted(root: Path) -> int:
    """Finish deletions that could not be finished at the time (a file was still open)."""
    import shutil
    gone = 0
    if root.is_dir():
        for d in root.iterdir():
            if d.is_dir() and d.name.startswith(DELETING):
                shutil.rmtree(d, ignore_errors=True)
                gone += not d.exists()
    return gone


def delete_run(run_dir: Path, free_leftovers: bool = False) -> None:
    """Delete a video: its whole folder, with the pictures, clips, voices and the finished cut.

    The folder is first renamed out of the list in one step. On Windows that fails while any
    file in it is open, so nothing is ever half deleted: either the video is gone from the
    list, or it is untouched and the error says what still has it open. `free_leftovers`: no
    job is working on this run, so an ffmpeg of VidGen's own that holds a file may be ended."""
    import shutil
    import shot_order
    run_dir = Path(run_dir)
    parked = run_dir.with_name(f"{DELETING}{run_dir.name}")
    if parked.exists():
        shutil.rmtree(parked, ignore_errors=True)
    for attempt in (1, 2):
        try:
            shot_order._rename(run_dir, parked, tries=5)
            break
        except PermissionError:
            who, freed = "another program", False
            for f in sorted(p for p in run_dir.rglob("*") if p.is_file()):
                import winlock
                if winlock.holders(f):
                    who, freed = shot_order._why_locked(f, free_leftovers)
                    break
            if freed and attempt == 1:
                continue
            raise StepError(f"this video was not deleted: one of its files is held open by {who}. Close the "
                            f"video or clip that is playing and delete it again.") from None
        except OSError as e:
            raise StepError(f"this video was not deleted: {e}") from None
    shutil.rmtree(parked, ignore_errors=True)       # anything that will not go now goes at the next start


def reroll_many(run_id: str, shots: list[int], config: dict) -> None:
    """Reroll several shots in one go: new pictures for all of them (drawn side by side), then
    new clips, then (with clip sound) their lines read again from the new clips."""
    run_dir = run_dir_for(run_id)
    _image_pipeline_only(run_dir, "reroll")
    only = ",".join(str(n) for n in sorted(set(shots)))
    print(f"\n=== reroll shots {only} ({run_dir.name}) ===")
    import clip_sound
    revoice = clip_sound.on(config, run_dir) and bool(_spoken_among(run_dir, only))
    progress.start(["images", "video"] + (["voice"] if revoice else []))
    run_step("images", run_dir, config, only=only)
    step(run_id, "video", config, only=only)          # with clip sound this reads the lines again too


def move_shot(run_id: str, shot_number: int, to: int, config: dict) -> dict:
    """Move a shot to another place in the run, with its picture, clip and voice (shot_order.py)."""
    run_dir = run_dir_for(run_id)
    _image_pipeline_only(run_dir, "moving a shot")
    out = importlib.import_module("shot_order").move(run_dir, config, shot_number, to)
    print(f"shot {shot_number} is now shot {to} ({out['files']} files renamed). Nothing was generated. "
          f"Assemble again for the video in the new order:  python main.py step {run_dir.name} assemble")
    return out


def recast(run_id: str, config: dict) -> None:
    run_dir = run_dir_for(run_id)
    _image_pipeline_only(run_dir, "recast")
    print(f"\n=== recast ({run_dir.name}) ===")
    importlib.import_module("recast").run(run_dir, config)
