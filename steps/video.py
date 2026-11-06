"""Video step: image-to-video on each animated shot's keyframe (Seedance 2.0 Fast on fal or Sume)."""

from __future__ import annotations

import threading
from pathlib import Path

import fal_api
import sume_api
from common import StepError, parse_only, read_script, select_shots
from parallel import TaskRunner
from steps.images import shot_path

ASPECT = "9:16"
RESOLUTIONS = ("480p", "720p")   # what Seedance 2.0 Fast accepts on both providers


def video_provider(config: dict) -> str:
    return config["providers"]["video"]


def _block(config: dict) -> dict:
    """The settings block of the active video provider."""
    return config[video_provider(config)]


def video_resolution(config: dict) -> str:
    res = str(_block(config)["video_resolution"])
    if res not in RESOLUTIONS:
        raise StepError(f"config.yaml: {video_provider(config)}.video_resolution must be one of "
                        f"{', '.join(RESOLUTIONS)}, got '{res}'")
    return res


def _workers(config: dict) -> int:
    # fal runs one request at a time, as it always has; Sume runs up to its concurrency cap.
    return int(config["sume"]["max_concurrent"]) if video_provider(config) == "sume" else 1


def video_path(run_dir: Path, n: int) -> Path:
    return shot_path(run_dir, n).with_suffix(".mp4")


def generate_clip(run_dir: Path, config: dict, shot: dict) -> Path:
    n = shot["n"]
    fal = config["fal"]
    keyframe = shot_path(run_dir, n)
    if not keyframe.exists():
        raise StepError(f"shot {n}: keyframe {keyframe} is missing; run the images step first")
    dest = video_path(run_dir, n)
    label = f"shot {n}"
    if video_provider(config) == "sume":
        video_resolution(config)
        url = sume_api.generate_video(config, shot["motion_prompt"].strip(), keyframe, label)
        sume_api.download(url, dest)
        return dest
    result = fal_api.call(fal["video_model"], {
        "prompt": shot["motion_prompt"].strip(),
        "image_url": fal_api.upload(keyframe),
        "duration": int(fal["video_seconds"]),
        "resolution": video_resolution(config),
        "aspect_ratio": ASPECT,
        "generate_audio": bool(fal["video_audio"]),
    }, label=label)
    fal_api.download(fal_api.video_url(result, label), dest)
    return dest


def _run(run_dir: Path, config: dict, only: set[int] | None, force: bool) -> None:
    if video_provider(config) == "sume":
        sume_api.require_key()
    else:
        fal_api.require_key()
    resolution = video_resolution(config)   # fail before any spend on a bad value
    script = read_script(run_dir)
    block = _block(config)
    seconds = int(block["video_seconds"])
    rate = float(block["video_cost_per_second"])

    animated = [s for s in select_shots(script, only) if s.get("animate")]
    skipped_static = [s["n"] for s in select_shots(script, only) if not s.get("animate")]
    if only is not None and skipped_static:
        print(f"[video] shot(s) {skipped_static} are animate: false, nothing to render")
    via = "" if video_provider(config) == "fal" else \
        f" via Sume ({block['video_model']}, up to {_workers(config)} at once)"
    print(f"[video] {len(animated)} animated shot(s), {seconds}s each at {resolution}, "
          f"${rate:.4f}/s{via}")

    totals = {"cost": 0.0, "count": 0}
    lock = threading.Lock()

    def make(shot: dict) -> None:
        n = shot["n"]
        print(f"  shot {n}: generating...")
        generate_clip(run_dir, config, shot)
        cost = seconds * rate
        with lock:
            totals["cost"] += cost
            totals["count"] += 1
            print(f"  shot {n}: {seconds}s  est. ${cost:.2f}  (running total ${totals['cost']:.2f})")

    runner = TaskRunner(_workers(config))
    for shot in animated:
        n = shot["n"]
        dest = video_path(run_dir, n)
        if dest.exists() and not force:
            print(f"  shot {n}: exists, skipping")
            continue
        runner.submit(make, shot)
    runner.join()
    print(f"[video] generated {totals['count']} clip(s), est. total ${totals['cost']:.2f}")


def run(run_dir: Path, config: dict, only: str | None = None) -> None:
    """Full step. `only` is a comma-separated shot list; those shots are regenerated even if present."""
    only_set = parse_only(only)
    _run(run_dir, config, only_set, force=only_set is not None)


def reroll_shot(run_dir: Path, config: dict, shot_number: int) -> None:
    script = read_script(run_dir)
    shot = next((s for s in script["shots"] if s["n"] == shot_number), None)
    if shot is None:
        raise StepError(f"shot {shot_number} not in script.json")
    if not shot.get("animate"):
        print(f"[video] shot {shot_number} is animate: false, no clip to reroll")
        return
    _run(run_dir, config, {shot_number}, force=True)
