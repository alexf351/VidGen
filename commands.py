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
    log(f"created run {run_dir.name} (format {config['format']['name']}"
        + (", Claude Code engine)" if engine == "claude_code" else ")"))
    log(f"  {run_dir}")
    if screens:
        log(f"  app screens: {', '.join(Path(p).stem for p in screens)}")
    if script is not None:
        log(f"  ready-made script: {info['title']} ({len(script['shots'])} shots, {info['words']} spoken words); "
            f"no script step")
    return run_dir


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
        for name in rest:
            run_step(name, run_dir, config)
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
    for name in STEP_ORDER:
        run_step(name, run_dir, config)
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
