#!/usr/bin/env python3
"""VidGen: turn a story premise into a 9:16 animated short.

Commands:
  python main.py new "<premise>"            create a run and execute every step in order
  python main.py step <run_id> <step_name>  re-run a single step on an existing run
      ... images --only 3,7                 regenerate only those shots (images, video, voice)
  python main.py reroll <run_id> <shot_n>   regenerate one shot's image + video
  python main.py recast <run_id>            sync script.json with config's locked characters
"""

from __future__ import annotations

import argparse
import importlib
import sys

from dotenv import load_dotenv

from common import STEP_ORDER, StepError, create_run, load_config, run_dir_for


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
    return p


def main(argv=None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    try:
        config = load_config()
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
