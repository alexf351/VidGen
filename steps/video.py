"""Video step: image-to-video on each animated shot's keyframe (Seedance 2.0 Fast on fal or Sume),
and a lip-synced clip for each talking shot (a talking-avatar model on fal: the keyframe + the
shot's voice line, so the voice step's audio for that shot is made first if it is missing)."""

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


def talk_seconds(run_dir: Path, n: int) -> float:
    """Length of a talking shot's voice line (from the voice step's timing file), or 0."""
    from common import read_json
    from steps.voice import timing_path
    tp = timing_path(run_dir, n)
    if not tp.exists():
        return 0.0
    try:
        return float(read_json(tp).get("duration") or 0.0)
    except (OSError, ValueError):
        return 0.0


def generate_talk_clip(run_dir: Path, config: dict, shot: dict) -> Path:
    """The keyframe speaking this shot's voice line, lip-synced (fal talking-avatar model)."""
    from steps.voice import audio_path, generate_voice, require_key as voice_key
    n = shot["n"]
    keyframe = shot_path(run_dir, n)
    if not keyframe.exists():
        raise StepError(f"shot {n}: keyframe {keyframe} is missing; run the images step first")
    audio = audio_path(run_dir, n)
    if not audio.exists():
        voice_key()
        print(f"  shot {n}: making its voice line first (the talking clip is lip-synced to it)")
        generate_voice(run_dir, config, shot)
    fal = config["fal"]
    label = f"shot {n} (talking)"
    prompt = (shot.get("motion_prompt") or "").strip() or "the person talks naturally to the camera"
    result = fal_api.call(fal["avatar_model"], {
        "image_url": fal_api.upload(keyframe),
        "audio_url": fal_api.upload(audio),
        "prompt": prompt,
    }, label=label)
    dest = video_path(run_dir, n)
    fal_api.download(fal_api.video_url(result, label), dest)
    return dest


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
    script = read_script(run_dir)
    selected = select_shots(script, only)
    animated = [s for s in selected if s.get("animate") and not s.get("talk")]
    talking = [s for s in selected if s.get("talk")]
    if animated:
        if video_provider(config) == "sume":
            sume_api.require_key()
        else:
            fal_api.require_key()
    if talking:
        fal_api.require_key()                # talking clips are made on fal whatever the provider
    resolution = video_resolution(config)   # fail before any spend on a bad value
    block = _block(config)
    seconds = int(block["video_seconds"])
    rate = float(block["video_cost_per_second"])
    talk_rate = float(config["fal"]["avatar_cost_per_second"])

    skipped_static = [s["n"] for s in selected if not s.get("animate") and not s.get("talk")]
    if only is not None and skipped_static:
        print(f"[video] shot(s) {skipped_static} are animate: false, nothing to render")
    via = "" if video_provider(config) == "fal" else \
        f" via Sume ({block['video_model']}, up to {_workers(config)} at once)"
    print(f"[video] {len(animated)} animated shot(s), {seconds}s each at {resolution}, "
          f"${rate:.4f}/s{via}")
    if talking:
        print(f"[video] {len(talking)} talking shot(s), lip-synced on fal ({config['fal']['avatar_model']}), "
              f"${talk_rate:.4f}/s of speech")

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

    def make_talk(shot: dict) -> None:
        n = shot["n"]
        print(f"  shot {n}: generating talking clip ({shot['speaker']})...")
        generate_talk_clip(run_dir, config, shot)
        secs = talk_seconds(run_dir, n)
        cost = secs * talk_rate
        with lock:
            totals["cost"] += cost
            totals["count"] += 1
            print(f"  shot {n}: {secs:.1f}s talking  est. ${cost:.2f}  (running total ${totals['cost']:.2f})")

    runner = TaskRunner(_workers(config))
    for shot in animated:
        n = shot["n"]
        dest = video_path(run_dir, n)
        if dest.exists() and not force:
            print(f"  shot {n}: exists, skipping")
            continue
        runner.submit(make, shot)
    runner.join()
    for shot in talking:                     # one at a time on fal
        n = shot["n"]
        if video_path(run_dir, n).exists() and not force:
            print(f"  shot {n}: talking clip exists, skipping")
            continue
        make_talk(shot)
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
    if not shot.get("animate") and not shot.get("talk"):
        print(f"[video] shot {shot_number} is animate: false, no clip to reroll")
        return
    _run(run_dir, config, {shot_number}, force=True)
