#!/usr/bin/env python3
"""VidGen: turn a story premise into a 9:16 animated short.

Commands:
  python main.py new "<premise>"            create a run and execute every step in order
      ... --format <name>                   video format to use (default pixar_arc)
      ... --cast dana=marcus                cast a character from your library (repeatable)
  python main.py new "<premise>" --dry-run  script step only: print the shot list, nothing else
      ... --engine claude_code              Claude Code codes the scenes and renders locally
  python main.py formats                    list the installed video formats
  python main.py screens                    list the app screenshots a video can show
  python main.py ready                      list the ready-made scripts (python main.py new --ready NAME)
  python main.py ui [--port 8765]           local web UI + HTTP API on 127.0.0.1 (opens the browser)
  python main.py import-skill <skill>       turn a Claude skill folder (or its SKILL.md) into a format
      ... --name <name> --force             format name / replace an existing format
      ... --premise "<p>" --no-dry-run      test premise / skip the test script run
  python main.py doctor                     check ffmpeg, font, API keys and assets (no API calls)
  python main.py step <run_id> <step_name>  re-run a single step on an existing run
      ... images --only 3,7                 regenerate only those shots (images, video, voice)
  python main.py reroll <run_id> <shot_n>   regenerate one shot's image + video
  python main.py recast <run_id>            sync script.json with the format's locked characters
  python main.py move <run_id> <shot> <to>  move a shot to another place (its files move with it)
  python main.py captions <run_id> [style]  show or change a run's caption style (then: step assemble)

step, reroll and recast reuse the format the run was created with (saved in run.json).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

import commands
from code_engine import CODE_STEPS
from common import (KEY_ENV, STEP_ORDER, StepError, load_config, peek_runs_dir, run_cast,
                    run_format)
from format_loader import DEFAULT_FORMAT, format_summaries


# The command logic lives in commands.py (shared with the local server); these adapt argparse.
_step_module = commands.step_module
STEPS_WITH_ONLY = commands.STEPS_WITH_ONLY
run_step = commands.run_step


def cmd_new(args, config) -> None:
    picks = [x.strip() for x in (getattr(args, "screens", None) or "").split(",") if x.strip()]
    ready = getattr(args, "ready", None)
    if not (args.premise or "").strip() and not ready:
        raise StepError("give a premise in quotes, or --ready NAME to use a ready-made script")
    run_dir = commands.create_new_run(args.premise or "", config, engine=getattr(args, "engine", None),
                                      captions=getattr(args, "captions", None), screens=picks, ready=ready)
    commands.execute_new(run_dir, config, args.dry_run)


def cmd_step(args, config) -> None:
    commands.step(args.run_id, args.step_name, config, only=args.only)


def cmd_reroll(args, config) -> None:
    commands.reroll(args.run_id, args.shot_number, config)


def cmd_captions(args, config) -> None:
    """captions <run_id> [style]: show or set a run's caption style."""
    import caption_styles
    run_dir = commands.run_dir_for(args.run_id)
    if args.style is None:
        current = caption_styles.for_run(run_dir, config)
        print(f"\n{args.run_id} uses the caption style: {current}")
        for c in caption_styles.catalog():
            print(f"  {c['id']:<11} {c['title']}: {c['note']}")
        return
    saved = caption_styles.set_for_run(run_dir, args.style)
    print(f"\ncaption style for {args.run_id} is now: {saved}")
    print(f"apply it (free, no API calls):  python main.py step {args.run_id} assemble")


def cmd_move(args, config) -> None:
    commands.move_shot(args.run_id, args.shot, args.to, config)


def cmd_recast(args, config) -> None:
    commands.recast(args.run_id, config)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="main.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="create a run and execute all steps")
    p_new.add_argument("premise", nargs="?", default="", help="story premise, in quotes (not needed with --ready)")
    p_new.add_argument("--ready", default=None, metavar="NAME",
                       help="use one of the format's ready-made scripts instead of writing one "
                            "(no script step, no Claude cost); see: python main.py ready")
    p_new.add_argument("--dry-run", action="store_true",
                       help="run only the script step and print the shot list (no image/video/voice calls)")
    p_new.add_argument("--format", default=DEFAULT_FORMAT, metavar="NAME",
                       help=f"video format, a folder under formats/ (default {DEFAULT_FORMAT}); "
                            f"see: python main.py formats")
    p_new.add_argument("--cast", action="append", default=[], metavar="ID[=REPLACES]",
                       help="put a character from your library (library/characters/) in the story: "
                            "--cast dana=marcus plays marcus's role, --cast rex adds rex; repeatable")
    p_new.add_argument("--engine", choices=["ai", "claude_code"], default="ai",
                       help="ai: image + video models (default). claude_code: Claude Code codes every "
                            "scene and renders on this computer with your Claude login (formats with "
                            "a code_render block)")
    p_new.add_argument("--screens", default=None, metavar="NAMES",
                       help="app screenshots this video must show, by name and comma-separated "
                            "(--screens learn,certificate); see: python main.py screens")
    p_new.add_argument("--captions", default=None, metavar="STYLE",
                       help="caption style: format (the format's own look), classic, outline, "
                            "yellow_pop, comic, headline, banner or off")
    p_new.set_defaults(func=cmd_new)

    p_step = sub.add_parser("step", help="re-run one step on an existing run")
    p_step.add_argument("run_id")
    p_step.add_argument("step_name", choices=STEP_ORDER + CODE_STEPS,
                        help=f"image pipeline: {', '.join(STEP_ORDER)}; Claude Code engine: {', '.join(CODE_STEPS)}")
    p_step.add_argument("--only", metavar="N,N", default=None,
                        help="comma-separated shot numbers to (re)generate; images, video and voice only")
    p_step.set_defaults(func=cmd_step)

    p_reroll = sub.add_parser("reroll", help="regenerate one shot's image and video")
    p_reroll.add_argument("run_id")
    p_reroll.add_argument("shot_number", type=int)
    p_reroll.set_defaults(func=cmd_reroll)

    p_move = sub.add_parser("move", help="move a shot to another place in a run, with its picture, clip and voice")
    p_move.add_argument("run_id")
    p_move.add_argument("shot", type=int, help="the shot to move")
    p_move.add_argument("to", type=int, help="the place it goes to (1 = first)")
    p_move.set_defaults(func=cmd_move)
    p_recast = sub.add_parser("recast", help="apply config's locked character descriptions to a run")
    p_recast.add_argument("run_id")
    p_recast.set_defaults(func=cmd_recast)

    p_cap = sub.add_parser("captions", help="show or change a run's caption style")
    p_cap.add_argument("run_id")
    p_cap.add_argument("style", nargs="?", default=None,
                       help="format, classic, outline, yellow_pop, comic, headline, banner or off; "
                            "leave out to see the current one")
    p_cap.set_defaults(func=cmd_captions)

    p_doctor = sub.add_parser("doctor", help="check ffmpeg, the caption font, API keys and assets")
    p_doctor.set_defaults(func=None)

    p_formats = sub.add_parser("formats", help="list the installed video formats")
    p_formats.set_defaults(func=None)

    p_screens = sub.add_parser("screens", help="list the app screenshots a video can show")
    p_screens.set_defaults(func=None)

    p_ready = sub.add_parser("ready", help="list the ready-made scripts of each format")
    p_ready.set_defaults(func=None)

    p_ui = sub.add_parser("ui", help="start the local web UI and HTTP API on 127.0.0.1")
    p_ui.add_argument("--port", type=int, default=8765, help="port (default 8765)")
    p_ui.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    p_ui.set_defaults(func=None)

    p_imp = sub.add_parser("import-skill", help="turn a Claude skill folder into a video format")
    p_imp.add_argument("skill", help="path to the skill folder or its SKILL.md")
    p_imp.add_argument("--name", default=None, help="format name (default: from the skill)")
    p_imp.add_argument("--force", action="store_true", help="replace formats/<name> if it exists")
    p_imp.add_argument("--premise", default=None,
                       help="premise for the test run (default: one the import suggests)")
    p_imp.add_argument("--no-dry-run", action="store_true",
                       help="skip the test run of the script step (saves one Claude call)")
    p_imp.set_defaults(func=cmd_import_skill)
    return p


def cmd_import_skill(args, config) -> int:
    """import-skill: convert, write, validate, then a dry run of the new format."""
    from format_import import import_skill, print_summary
    summary = import_skill(args.skill, config, name=args.name, force=args.force)
    print_summary(summary)
    name = summary["name"]
    if summary["checks"]:
        print(f"\n[import] formats/{name} does not load cleanly:")
        for c in summary["checks"]:
            print(f"  - {c}")
        print(f"fix the files in formats/{name}/ and rerun with --force, or edit them by hand")
        return 1
    print(f"\n[import] format.yaml is valid and the script prompt renders")
    if args.no_dry_run:
        print(f"\ntry it:  python main.py new \"<premise>\" --format {name} --dry-run")
        return 0
    premise = args.premise or summary["data"]["sample_premise"].strip() or "A short test story"
    print(f"\n[import] test run: new --format {name} --dry-run")
    fmt_config = load_config(format_name=name)
    try:
        cmd_new(argparse.Namespace(premise=premise, dry_run=True, format=name), fmt_config)
    except StepError as e:
        print(f"\n[import] the test run did not produce a valid shot list:\n{e}", file=sys.stderr)
        print(f"formats/{name} was kept; adjust its rules or prompts and try "
              f"python main.py new \"{premise}\" --format {name} --dry-run", file=sys.stderr)
        return 1
    print(f"\n[import] formats/{name} produced a shot list. Make a video with:\n"
          f"  python main.py new \"<premise>\" --format {name}")
    return 0


def list_ready() -> int:
    """ready: the ready-made scripts, by format, with the command that makes a video from each."""
    import ready_scripts
    found = 0
    for f in format_summaries():
        if "error" in f:
            continue
        rows = ready_scripts.listing(f)
        if not rows:
            continue
        print(f"\n{f.get('title') or f['name']}  ({f['name']})")
        for e in rows:
            found += 1
            print(f"  {e['id']:<16} {e['title']}: {e['premise']}")
            print(f"  {'':<16} {e['shots']} shots, {e['words']} spoken words")
            print(f"  {'':<16} python main.py new --format {f['name']} --ready {e['id']}")
    if not found:
        print("no ready-made scripts found (expected formats/<format>/scripts/*.json)")
        return 1
    print("\nadd --dry-run to make the run without images, video or voice, and read the script first")
    return 0


def list_screens() -> int:
    """screens: the app screenshot library, by group, with the names --screens takes."""
    import app_assets
    screens = app_assets.everything()
    if not screens:
        print("no app screenshots found (expected pictures in assets/screens/)")
        return 1
    for gid, gtitle in app_assets.GROUPS:
        rows = [e for e in screens if e["group"] == gid]
        if not rows:
            continue
        print(f"\n{gtitle}")
        for e in rows:
            moves = f" [moves, {e['seconds']:.0f}s]" if e.get("clip") else ""
            print(f"  {Path(e['path']).stem:<14} {e['title']}{moves}: {e['shows'] or '(no description)'}")
    print("\npin some for one video:  python main.py new \"premise\" --screens learn,certificate")
    print("add your own: drop phone screenshots or screen recordings in assets/screens/mine/, or use the UI")
    return 0


def list_formats() -> int:
    formats = format_summaries()
    if not formats:
        print("no formats installed (expected folders under formats/)")
        return 1
    print("installed formats:\n")
    for f in formats:
        default = "  (default)" if f["name"] == DEFAULT_FORMAT else ""
        print(f"  {f['name']}{default}")
        if f.get("error"):
            print(f"    error: {f['error']}\n")
            continue
        if f["description"]:
            print(f"    {f['description']}")
        facts = [f"aspect {f['aspect']}" if f["aspect"] else "",
                 f"{f['duration_target']}" if f["duration_target"] else "",
                 f"{f['clip_seconds']}s clips" if f["clip_seconds"] else "",
                 f"cast: {f['cast']}"]
        print(f"    {', '.join(x for x in facts if x)}")
        if f["beats"]:
            print(f"    beats: {' -> '.join(f['beats'])}")
        if f["examples"]:
            print(f"    examples: {', '.join(f['examples'])}")
        print()
    print("use one with:  python main.py new \"<premise>\" --format <name>")
    return 0


def cast_for(args) -> list:
    """new: --cast ID[=REPLACES]. step / reroll / recast: the cast saved with the run."""
    if args.command == "new":
        out = []
        for item in args.cast:
            cid, _, rep = item.partition("=")
            out.append({"character": cid.strip(), "replaces": rep.strip() or None})
        return out
    run_id = getattr(args, "run_id", None)
    if run_id:
        return run_cast(peek_runs_dir() / run_id)
    return []


def format_for(args) -> str:
    """new: --format. step / reroll / recast: the format saved with the run."""
    if args.command == "new":
        return args.format
    run_id = getattr(args, "run_id", None)
    if run_id:
        return run_format(peek_runs_dir() / run_id) or DEFAULT_FORMAT
    return DEFAULT_FORMAT


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
    print(f"[config] format: {config['format']['name']}")
    if config.get("cast"):
        from characters import describe_cast
        for line in describe_cast(config):
            print(f"[config] cast: {line}")
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
        if args.command == "formats":
            return list_formats()
        if args.command == "screens":
            return list_screens()
        if args.command == "ready":
            return list_ready()
        config = load_config(format_name=format_for(args), cast=cast_for(args))
        key_sources = _key_sources(config, from_dotenv)
        print_config_sources(config, key_sources)
        if args.command == "doctor":
            from doctor import run_doctor
            return run_doctor(config, key_sources)
        if args.command == "ui":
            try:
                from server import serve
            except ImportError as e:
                raise StepError(f"the web UI needs {e.name}: pip install -r requirements.txt") from None
            return serve(load_config, key_sources, port=args.port, open_browser=not args.no_browser)
        rc = args.func(args, config)
        if isinstance(rc, int):
            return rc
    except StepError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
