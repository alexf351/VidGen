#!/usr/bin/env python3
"""VidGen: turn a story premise into a 9:16 animated short.

Commands:
  python main.py new "<premise>"            create a run and execute every step in order
  python main.py new "<premise>" --dry-run  script step only: print the shot list, nothing else
  python main.py doctor                     check ffmpeg, font, API keys and assets (no API calls)
  python main.py step <run_id> <step_name>  re-run a single step on an existing run
      ... images --only 3,7                 regenerate only those shots (images, video, voice)
  python main.py reroll <run_id> <shot_n>   regenerate one shot's image + video
  python main.py recast <run_id>            sync script.json with config's locked characters
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys

from dotenv import load_dotenv

from common import KEY_ENV, STEP_ORDER, StepError, create_run, load_config, run_dir_for


def _step_module(name: str):
    return importlib.import_module(f"steps.{name}")


STEPS_WITH_ONLY = {"images", "video", "voice"}


def run_step(name: str, run_dir, config, only: str | None = None) -> None:
    print(f"\n=== step: {name} ({run_dir.name}) ===")
    module = _step_module(name)
    if only is None:
        module.run(run_dir, config)
    elif name in STEPS_WITH_ONLY:
        module.run(run_dir, config, only=only)
    else:
        raise StepError(f"--only is supported for {sorted(STEPS_WITH_ONLY)}, not '{name}'")


def cmd_new(args, config) -> None:
    run_dir = create_run(args.premise)
    print(f"created run {run_dir.name}")
    print(f"  {run_dir}")
    if args.dry_run:
        # Only the script step runs. It calls Claude (a few cents) to write the shot list;
        # nothing is sent to fal, Sume or ElevenLabs.
        run_step("script", run_dir, config)
        print(f"\ndry run: stopped after the script step; no images, video or voice were generated.")
        print(f"continue this run with:  python main.py step {run_dir.name} images  (then video, voice, assemble)")
        return
    for name in STEP_ORDER:
        run_step(name, run_dir, config)
    print(f"\nrun {run_dir.name} complete")


def cmd_step(args, config) -> None:
    run_dir = run_dir_for(args.run_id)
    run_step(args.step_name, run_dir, config, only=args.only)


def cmd_reroll(args, config) -> None:
    run_dir = run_dir_for(args.run_id)
    n = args.shot_number
    print(f"\n=== reroll shot {n} ({run_dir.name}) ===")
    _step_module("images").reroll_shot(run_dir, config, n)
    _step_module("video").reroll_shot(run_dir, config, n)


def cmd_recast(args, config) -> None:
    run_dir = run_dir_for(args.run_id)
    print(f"\n=== recast ({run_dir.name}) ===")
    importlib.import_module("recast").run(run_dir, config)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="main.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="create a run and execute all steps")
    p_new.add_argument("premise", help="story premise, in quotes")
    p_new.add_argument("--dry-run", action="store_true",
                       help="run only the script step and print the shot list (no image/video/voice calls)")
    p_new.set_defaults(func=cmd_new)

    p_step = sub.add_parser("step", help="re-run one step on an existing run")
    p_step.add_argument("run_id")
    p_step.add_argument("step_name", choices=STEP_ORDER)
    p_step.add_argument("--only", metavar="N,N", default=None,
                        help="comma-separated shot numbers to (re)generate; images, video and voice only")
    p_step.set_defaults(func=cmd_step)

    p_reroll = sub.add_parser("reroll", help="regenerate one shot's image and video")
    p_reroll.add_argument("run_id")
    p_reroll.add_argument("shot_number", type=int)
    p_reroll.set_defaults(func=cmd_reroll)

    p_recast = sub.add_parser("recast", help="apply config's locked character descriptions to a run")
    p_recast.add_argument("run_id")
    p_recast.set_defaults(func=cmd_recast)

    p_doctor = sub.add_parser("doctor", help="check ffmpeg, the caption font, API keys and assets")
    p_doctor.set_defaults(func=None)
    return p


def _utf8_console() -> None:
    """Windows consoles and redirected output default to a legacy code page, which crashes on
    the shot table's ellipsis or curly quotes from the model. Always write UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _key_sources(config: dict, from_dotenv: set[str]) -> dict[str, str]:
    sources = dict(config["_sources"]["keys"])
    for var in sources:
        if var in from_dotenv:
            sources[var] = ".env"
    return sources


def print_config_sources(config: dict, key_sources: dict[str, str]) -> None:
    src = config["_sources"]
    line = " + ".join(src["files"])
    if src["env"]:
        line += " + env (" + ", ".join(src["env"]) + ")"
    keys = ", ".join(f"{var}: {where}" for var, where in key_sources.items())
    print(f"[config] {line}")
    print(f"[config] keys: {keys}")
    print(f"[config] providers: images={config['providers']['images']}, video={config['providers']['video']}; "
          f"output: {config['output_dir']}")


def main(argv=None) -> int:
    _utf8_console()
    before = set(os.environ)
    load_dotenv()
    from_dotenv = {v for v in KEY_ENV.values() if v in os.environ and v not in before}
    args = build_parser().parse_args(argv)
    try:
        config = load_config()
        key_sources = _key_sources(config, from_dotenv)
        print_config_sources(config, key_sources)
        if args.command == "doctor":
            from doctor import run_doctor
            return run_doctor(config, key_sources)
        args.func(args, config)
    except StepError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
