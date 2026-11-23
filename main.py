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
  python main.py review <run_id>            check the pictures, clips and the cut (qa_report.json)
      ... --what clips --only 3,7 --again   just the clips / just those shots / check again
      ... --fix                             make what it flags again (a picture or clip each, max 2 a shot)
  python main.py new "<premise>" --review   check every shot as the video is made (--auto-fix: and redo)

step, reroll and recast reuse the format the run was created with (saved in run.json).
"""

from __future__ import annotations

import argparse
import json
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
                                      captions=getattr(args, "captions", None), screens=picks, ready=ready,
                                      length=getattr(args, "length", None))
    if getattr(args, "model", None):
        import video_model
        video_model.set_for_run(run_dir, args.model)
    if getattr(args, "review", False) or getattr(args, "auto_fix", False):
        import review
        review.set_for_run(run_dir, on=True, auto_fix=bool(getattr(args, "auto_fix", False)))
    commands.execute_new(run_dir, config, args.dry_run)


def cmd_review(args, config) -> None:
    import review
    from common import parse_only
    run_dir = commands.run_dir_for(args.run_id)
    commands._image_pipeline_only(run_dir, "the review")
    review.review(run_dir, config, what=args.what, only=parse_only(args.only), again=args.again,
                  fix_flagged=args.fix)


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
    p_new.add_argument("--length", choices=["short", "standard", "long"], default=None,
                       help="how long the video runs: the format's own length (default), or longer "
                            "(short 15-30 s, standard 40-60 s, long 75-100 s)")
    p_new.add_argument("--model", choices=["mini", "fast", "standard", "2.5", "grok"], default=None,
                       help="the video model for the clips: Seedance 2.0 Fast, 2.0 or 2.5 (default: the config's)")
    p_new.add_argument("--captions", default=None, metavar="STYLE",
                       help="caption style: format (the format's own look), classic, outline, "
                            "yellow_pop, comic, headline, banner or off")
    p_new.set_defaults(func=cmd_new)

    p_new.add_argument("--review", action="store_true",
                       help="Claude checks every picture, clip and the cut as they are made (qa_report.json)")
    p_new.add_argument("--auto-fix", action="store_true",
                       help="with the review: make a flagged picture or clip again (max 2 takes a shot; costs a take each)")

    p_rev = sub.add_parser("review", help="check a video's pictures, clips and cut with Claude (qa_report.json)")
    p_rev.add_argument("run_id")
    p_rev.add_argument("--what", choices=["all", "pictures", "clips", "final"], default="all")
    p_rev.add_argument("--only", metavar="N,N", default=None, help="only these shots")
    p_rev.add_argument("--again", action="store_true", help="check again what was already checked")
    p_rev.add_argument("--fix", action="store_true",
                       help="make what it flags again, with its fixes (max 2 takes a shot; costs a picture or clip each)")
    p_rev.set_defaults(func=cmd_review)

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

    p_con = sub.add_parser("contrast", help="batches of ten second Contrast videos: two sides, two labels, "
                                             "the right one wins (drawn by VidGen itself, no model calls)")
    p_con.add_argument("action", choices=["new", "render", "list", "vary", "zip"],
                       help="new: make a batch | render: draw what is missing | list: the batches | "
                            "vary: variations of the scenes that did best | zip: videos and captions in one file")
    p_con.add_argument("batch", nargs="?", default=None, help="the batch id (render, vary, zip)")
    p_con.add_argument("--name", default="", help="new: a name for the batch")
    p_con.add_argument("--write", type=int, default=0, metavar="N",
                       help="new: have Claude write N scenes (a few cents) instead of using the starter set")
    p_con.add_argument("--about", default="", help="new --write: who the page is for, in a sentence")
    p_con.add_argument("--scenes", default=None, metavar="FILE",
                       help="new: a JSON file with your own scenes ([{template, left, right, caption}, ...])")
    p_con.add_argument("--tag", default=None, help="new: the words that fade in at the end (default SEARCH IRO AI)")
    p_con.add_argument("--no-tag", action="store_true", help="new: no words at the end")
    p_con.add_argument("--no-render", action="store_true", help="new, vary: only write the scenes, draw nothing yet")
    p_con.add_argument("--only", default=None, metavar="N,N", help="render: only these scenes")
    p_con.add_argument("--again", action="store_true", help="render: draw them again even if they are there")
    p_con.add_argument("--workers", type=int, default=None, help="render: how many videos to draw at once")
    p_con.add_argument("--of", default=None, metavar="N,N", help="vary: the scenes that did best")
    p_con.add_argument("--each", type=int, default=10, help="vary: variations of each (default 10)")
    p_con.set_defaults(func=cmd_contrast)

    p_story = sub.add_parser("story", help="choice stories: a narrated stick-figure serial where every episode ends "
                             "on a choice and the next one starts from the vote; drawn here, no picture or clip model")
    p_story.add_argument("action", choices=["new", "next", "render", "list", "starters"],
                         help="new: start a series and make episode 1 | next: write and make the next episode from the "
                              "vote | render: make an episode's video (again) | list: your series | starters: the stories that ship")
    p_story.add_argument("series", nargs="?", help="the series id (next, render)")
    p_story.add_argument("--starter", help="new: one of the stories that ship (see: story starters)")
    p_story.add_argument("--premise", help="new: your own premise; Claude writes episode 1 from it (one request)")
    p_story.add_argument("--script", help="new / next: a JSON file with the episode's script, in place of Claude writing it")
    p_story.add_argument("--name", help="new: a name for the series")
    p_story.add_argument("--choice", choices=["a", "b"], help="next: which choice won the vote")
    p_story.add_argument("--episode", type=int, help="render: which episode (default: the newest)")
    p_story.add_argument("--no-iro", action="store_true", help="new: a story without Iro at the hero's side")
    p_story.add_argument("--tag", help='new: the words at the very end (default "SEARCH IRO AI")')
    p_story.add_argument("--no-tag", action="store_true", help="new: no words at the end")
    p_story.add_argument("--voice", help="new: the ElevenLabs voice id of the narrator (default: the config's narrator)")
    p_story.add_argument("--no-voice", action="store_true", help="make the video without the narrator")
    p_story.add_argument("--no-render", action="store_true", help="write the script and stop before the video")
    p_story.add_argument("--again", action="store_true", help="render: make the video again even if it is already made")
    p_story.add_argument("--workers", type=int, help="how many frames to draw at once (default 4)")
    p_story.set_defaults(func=cmd_story)

    p_explain = sub.add_parser("explain", help="Iro explains: a short lesson video where Iro says every word and a title "
                                               "and cards build above him. Drawn by VidGen itself (no picture or clip model)")
    p_explain.add_argument("action", choices=["new", "render", "list", "starters"],
                           help="new: a lesson (--starter, --topic or --script); render: make its video; "
                                "list: your lessons; starters: the lessons that ship")
    p_explain.add_argument("lesson", nargs="?", help="the lesson id (render)")
    p_explain.add_argument("--starter", help="new: one of the lessons that ship (see: explain starters)")
    p_explain.add_argument("--topic", help="new: what the lesson is about; Claude writes it (one request)")
    p_explain.add_argument("--must", help="new, with --topic: something the lesson must mention")
    p_explain.add_argument("--script", help="new: a JSON file with the lesson, in place of Claude writing it")
    p_explain.add_argument("--name", help="new: a name for the lesson")
    p_explain.add_argument("--tag", help='new: the words at the very end (default "SEARCH IRO AI")')
    p_explain.add_argument("--no-tag", action="store_true", help="new: no words at the end")
    p_explain.add_argument("--voice", help="new: the ElevenLabs voice id that reads it (default: the config's narrator)")
    p_explain.add_argument("--no-voice", action="store_true", help="make the video without the voice")
    p_explain.add_argument("--no-render", action="store_true", help="write the lesson and stop before the video")
    p_explain.add_argument("--again", action="store_true", help="render: make the video again even if it is already made")
    p_explain.add_argument("--workers", type=int, help="how many frames to draw at once (default 4)")
    p_explain.set_defaults(func=cmd_explain)

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


def _numbers(text: str | None) -> set[int] | None:
    if not text:
        return None
    try:
        return {int(x) for x in str(text).replace(" ", "").split(",") if x}
    except ValueError:
        raise StepError(f"give shot or scene numbers as 3,11,27, got {text!r}") from None


def cmd_contrast(args, config) -> int:
    import contrast
    import contrast_batch as B
    if args.action == "list":
        rows = B.batches()
        if not rows:
            print("no Contrast batches yet. Make one:  python main.py contrast new")
        for r in rows:
            print(f"{r['id']}  {r['name']}: {r['made']}/{r['scenes']} videos"
                  + (f", {r['problems']} to check" if r["problems"] else ""))
        return 0
    if args.action == "new":
        if args.scenes:
            try:
                raw = json.loads(Path(args.scenes).read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise StepError(f"could not read {args.scenes}: {e}") from None
            scenes = raw.get("scenes") if isinstance(raw, dict) else raw
        elif args.write:
            print(f"[contrast] asking {config['script']['model']} for {args.write} scenes...")
            scenes = B.write_scenes(args.write, args.about, config)
        else:
            scenes = B.starter()
        tag = None if args.no_tag else (args.tag if args.tag is not None else B.DEFAULT_TAG)
        data = B.create(args.name or ("Starter scenes" if not (args.scenes or args.write) else ""), scenes, tag)
        print(f"created Contrast batch {data['id']}: {len(data['scenes'])} scenes")
        for line in data.get("skipped") or []:
            print(f"  left out: {line}")
        for s in data["scenes"]:
            print(f"  {s['n']:02d} [{s['template']}] {s['left']} vs {s['right']}")
        if args.no_render:
            print(f"draw them with:  python main.py contrast render {data['id']}")
            return 0
        result = B.render(data["id"], workers=args.workers)
        return 1 if result["failed"] else 0
    if not args.batch:
        raise StepError(f"which batch? python main.py contrast {args.action} <batch id>  (see: python main.py contrast list)")
    if args.action == "render":
        result = B.render(args.batch, only=_numbers(args.only), workers=args.workers, again=args.again)
        return 1 if result["failed"] else 0
    if args.action == "zip":
        print(f"wrote {B.export_zip(args.batch)}")
        return 0
    if args.action == "vary":
        of = _numbers(args.of)
        if not of:
            raise StepError("say which scenes did best:  --of 3,11,27")
        print(f"[contrast] asking {config['script']['model']} for {args.each} variations of {len(of)} scene(s)...")
        new = B.variations(args.batch, sorted(of), args.each, config)
        data, left_out = B.add_scenes(args.batch, new)
        print(f"added {len(new) - len(left_out)} scenes to {args.batch}")
        for line in left_out:
            print(f"  left out: {line}")
        if not args.no_render:
            result = B.render(args.batch, workers=args.workers)
            return 1 if result["failed"] else 0
    return 0


def cmd_story(args, config) -> int:
    import story_series as SR

    def read_script(path: str) -> dict:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise StepError(f"could not read {path}: {e}") from None
        if not isinstance(raw, dict):
            raise StepError(f"{path} is not an episode script")
        return raw

    def show(ep: dict) -> None:
        print(f"part {ep['part']}: {ep['title']}" + (f"  (the vote: {ep['voted']})" if ep.get("voted") else ""))
        for k, s in enumerate(ep["shots"], 1):
            print(f"  {k:02d} [{s['set']}, {s['light']}] {s['say']}")
        print(f"  ends on: {ep['question']}  ({ep['a']} or {ep['b']})")

    def make(series_id: str, n: int) -> int:
        if args.no_render:
            print(f"make the video with:  python main.py story render {series_id}")
            return 0
        SR.produce(series_id, n, config, voice=not args.no_voice, again=args.again, workers=args.workers or 4)
        return 0

    if args.action == "starters":
        for s in SR.starters():
            print(f"{s['id']}: {s['name']}" + ("  (episode 1 is written)" if s["episode"] else "") + f"\n    {s['premise']}")
        return 0
    if args.action == "list":
        rows = SR.all_series()
        if not rows:
            print("no story series yet. Start one:  python main.py story new --starter the_knock")
        for r in rows:
            nxt = r["next_choice"]
            print(f"{r['id']}  {r['name']}: {r['made']}/{r['episodes']} videos"
                  + (f", waiting on the vote: {nxt['a']} or {nxt['b']}" if nxt else ""))
        return 0
    if args.action == "new":
        starter = None
        if args.starter:
            starter = next((s for s in SR.starters() if s["id"] == args.starter), None)
            if starter is None:
                raise StepError(f"there is no starter called {args.starter} (see: python main.py story starters)")
        premise = args.premise or (starter["premise"] if starter else "")
        if not premise and not args.script:
            raise StepError("give the story a premise:  --premise \"...\"  or pick one:  --starter the_knock")
        tag = None if args.no_tag else (args.tag if args.tag is not None else SR.DEFAULT_TAG)
        data = SR.create(args.name or (starter["name"] if starter else ""), premise, iro=not args.no_iro, end_tag=tag, voice_id=args.voice or "")
        try:
            if args.script:
                script = read_script(args.script)
            elif starter and starter["episode"] and not args.premise:
                script = starter["episode"]
            else:
                print(f"[story] asking {config['script']['model']} for episode 1...")
                script = SR.write_first(data, config)
            ep = SR.add_episode(data["id"], script)
        except StepError:
            SR.delete(data["id"])
            raise
        print(f"created story series {data['id']}")
        show(ep)
        return make(data["id"], 1)
    if not args.series:
        raise StepError(f"which series? python main.py story {args.action} <series id>  (see: python main.py story list)")
    if args.action == "next":
        data = SR.load(args.series)
        if args.script:
            last = SR.load_episode(args.series, data["episodes"]) if data["episodes"] else None
            if last and not args.choice:
                raise StepError(f"say which choice won:  --choice a ({last['a']})  or  --choice b ({last['b']})")
            ep = SR.add_episode(args.series, read_script(args.script), voted=(last["a"] if args.choice == "a" else last["b"]) if last else None)
        else:
            if not args.choice:
                last = SR.load_episode(args.series, data["episodes"])
                raise StepError(f"say which choice won:  --choice a ({last['a']})  or  --choice b ({last['b']})")
            print(f"[story] asking {config['script']['model']} for episode {data['episodes'] + 1}...")
            script, won = SR.write_next(args.series, args.choice, config)
            ep = SR.add_episode(args.series, script, voted=won)
        show(ep)
        return make(args.series, ep["part"])
    if args.action == "render":
        data = SR.load(args.series)
        n = args.episode or data["episodes"]
        if n < 1:
            raise StepError("this series has no episode yet")
        SR.produce(args.series, n, config, voice=not args.no_voice, again=args.again, workers=args.workers or 4)
    return 0


def cmd_explain(args, config) -> int:
    import explainer
    import lessons as L

    def show(lesson: dict) -> None:
        print(f"{lesson['title']}")
        for seg in explainer.segments(lesson):
            print(f"  [{seg['kind']}] {seg['title']}: {seg['say']}")
        if lesson.get("caption"):
            print(f"  caption: {lesson['caption']}")

    if args.action == "starters":
        for s in L.starters():
            print(f"{s['id']}: {s['name']}\n    {s['topic']}")
        return 0
    if args.action == "list":
        rows = L.all_lessons()
        if not rows:
            print("no lessons yet. Make one:  python main.py explain new --starter the_missing_line")
        for r in rows:
            print(f"{r['id']}  {r['name']}: " + ("video made" if r["made"] else "script changed since the video" if r["stale"]
                                                else "no video yet" if r["lesson"] else "no script yet"))
        return 0
    if args.action == "new":
        tag = None if args.no_tag else (args.tag if args.tag is not None else L.DEFAULT_TAG)
        if args.script:
            try:
                script = json.loads(Path(args.script).read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise StepError(f"could not read {args.script}: {e}") from None
            name, topic = args.name or "", args.topic or ""
        elif args.starter:
            starter = next((s for s in L.starters() if s["id"] == args.starter), None)
            if starter is None:
                raise StepError(f"there is no starter called {args.starter} (see: python main.py explain starters)")
            script, name, topic = starter["lesson"], args.name or starter["name"], starter["topic"]
        elif args.topic:
            print(f"[lesson] asking {config['script']['model']} for a lesson...")
            script = L.write(args.topic, config, must=args.must or "", end_tag=tag or "")
            name, topic = args.name or "", args.topic
        else:
            raise StepError("say what the lesson is about:  --topic \"...\"  or pick one:  --starter the_missing_line")
        data = L.create(script, name=name, topic=topic, end_tag=tag, voice_id=args.voice or "")
        print(f"created lesson {data['id']}")
        show(L.script(data["id"]))
        if args.no_render:
            print(f"make the video with:  python main.py explain render {data['id']}")
            return 0
        L.produce(data["id"], config, voice=not args.no_voice, workers=args.workers or 4)
        return 0
    if not args.lesson:
        raise StepError("which lesson? python main.py explain render <lesson id>  (see: python main.py explain list)")
    L.produce(args.lesson, config, voice=not args.no_voice, again=args.again, workers=args.workers or 4)
    return 0


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
            moves += " [wide: on a laptop]" if e.get("wide") else ""
            print(f"  {Path(e['path']).stem:<14} {e['title']}{moves}: {e['shows'] or '(no description)'}")
    print("\npin some for one video:  python main.py new \"premise\" --screens learn,certificate")
    print("add your own: drop phone screenshots or screen recordings in assets/screens/mine/, or use the UI")
    print("a wide picture or recording (the web app) is shown on a laptop, not on the phone")
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
