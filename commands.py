"""The CLI's commands as plain functions, shared by main.py and the local server (server.py).

Each takes an already-loaded config (see common.load_config) and prints its progress exactly as
the CLI always has. Errors are raised as StepError.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from common import STEP_ORDER, StepError, create_run, run_dir_for, run_engine

STEPS_WITH_ONLY = {"images", "video", "voice"}


def step_module(name: str):
    return importlib.import_module(f"steps.{name}")


def run_step(name: str, run_dir: Path, config: dict, only: str | None = None) -> None:
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


def create_new_run(premise: str, config: dict, log=print, engine: str | None = None) -> Path:
    """Make the run folder for `new` (premise.txt, run.json with the format, cast and engine)."""
    if engine not in (None, "ai", "claude_code"):
        raise StepError(f"engine must be ai or claude_code, got {engine!r}")
    if engine == "claude_code":
        import code_engine
        if not code_engine.offered(config):
            raise StepError(f"the {config['format']['name']} format does not offer the Claude Code "
                            f"engine (its format.yaml has no code_render block)")
    run_dir = create_run(premise, config["format"]["name"], cast=config.get("cast") or None,
                         engine=engine)
    log(f"created run {run_dir.name} (format {config['format']['name']}"
        + (", Claude Code engine)" if engine == "claude_code" else ")"))
    log(f"  {run_dir}")
    return run_dir


def execute_new(run_dir: Path, config: dict, dry_run: bool = False) -> None:
    """Run every step of a new run in order, or only the script step for a dry run."""
    if run_engine(run_dir) == "claude_code":
        import code_engine
        code_engine.execute(run_dir, config, dry_run)
        return
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


def new(premise: str, config: dict, dry_run: bool = False) -> Path:
    run_dir = create_new_run(premise, config)
    execute_new(run_dir, config, dry_run)
    return run_dir


def step(run_id: str, step_name: str, config: dict, only: str | None = None) -> None:
    run_step(step_name, run_dir_for(run_id), config, only=only)


def _image_pipeline_only(run_dir: Path, what: str) -> None:
    if run_engine(run_dir) == "claude_code":
        raise StepError(f"{what} is for the image pipeline; this run uses the Claude Code engine "
                        f"(re-run its scenes step instead)")


def reroll(run_id: str, shot_number: int, config: dict) -> None:
    run_dir = run_dir_for(run_id)
    _image_pipeline_only(run_dir, "reroll")
    print(f"\n=== reroll shot {shot_number} ({run_dir.name}) ===")
    step_module("images").reroll_shot(run_dir, config, shot_number)
    step_module("video").reroll_shot(run_dir, config, shot_number)


def recast(run_id: str, config: dict) -> None:
    run_dir = run_dir_for(run_id)
    _image_pipeline_only(run_dir, "recast")
    print(f"\n=== recast ({run_dir.name}) ===")
    importlib.import_module("recast").run(run_dir, config)
