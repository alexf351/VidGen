"""How sharp a video's clips are made: 480p or 720p. A video can choose for itself.

Seedance makes a clip at 480p or 720p; the cut is 1080x1920 either way, so a 480p clip is scaled
up more and looks softer. 720p costs a little over twice as much per second. The config says
which one every video uses (`sume.video_resolution`, `fal.video_resolution`); a video's own choice
is kept in its run.json as "video_resolution" and wins over the config:

    run_choice(run_dir)          "480p", "720p", or None when the video does not say
    set_for_run(run_dir, value)  save it (None = follow the config again)
    apply(config, run_dir)       the config a job on this video uses, with its choice put in

Clips already made keep the resolution they were made at: the choice is read when a clip is
made."""

from __future__ import annotations

from pathlib import Path

from common import StepError, read_json, write_json

RESOLUTIONS = ("480p", "720p")


def check(value) -> str:
    v = str(value or "").strip().lower()
    if v not in RESOLUTIONS:
        raise StepError(f"clip quality must be one of {', '.join(RESOLUTIONS)}, got {value!r}")
    return v


def run_choice(run_dir: Path | None) -> str | None:
    if run_dir is None:
        return None
    try:
        value = read_json(Path(run_dir) / "run.json").get("video_resolution")
    except (OSError, ValueError, AttributeError):
        return None
    return value if value in RESOLUTIONS else None


def set_for_run(run_dir: Path, value: str | None) -> str | None:
    path = Path(run_dir) / "run.json"
    meta = read_json(path)
    if value is None:
        meta.pop("video_resolution", None)
    else:
        meta["video_resolution"] = check(value)
    write_json(path, meta)
    return run_choice(run_dir)


def of(config: dict) -> str:
    """The resolution this config makes clips at."""
    return str(config[config["providers"]["video"]]["video_resolution"])


def apply(config: dict, run_dir: Path | None) -> dict:
    """`config` with this video's choice in place of the config's, in both providers' blocks,
    with the price per second that goes with it. Changes and returns `config`."""
    mine = run_choice(run_dir)
    if mine is None:
        return config
    for name in ("fal", "sume"):
        block = config.get(name) or {}
        rates = block.get("video_cost_by_resolution")
        if isinstance(rates, dict) and mine not in rates:
            continue                                   # no price known for it here: leave this provider as it is
        block["video_resolution"] = mine
        if isinstance(rates, dict):
            block["video_cost_per_second"] = float(rates[mine])
    # The cost report reads the rate from the fal block whichever provider made the clips (common.py).
    if config["providers"]["video"] == "sume":
        config["fal"]["video_cost_per_second"] = float(config["sume"]["video_cost_per_second"])
    return config
