"""Which video model makes a video's clips: Seedance 2.0 Fast, Seedance 2.0 or Seedance 2.5.

The config says which one every video uses (`sume.video_model`, `fal.video_model`); a video's own
choice is kept in its run.json as "video_model" and wins over the config. Each model has its own
price per second at each resolution, on each provider, so the cost estimates follow the choice.

    MODELS                       the three, with their ids and prices on Sume and on fal
    of(config)                   the model this config makes clips with ("fast", "standard", "2.5")
    run_choice(run_dir)          the video's own choice, or None (the config's)
    set_for_run(run_dir, value)  save it (None = follow the config again)
    apply(config, run_dir|model) the config a job on this video uses, with its model and prices

What is known about quality (November 2026): on the Artificial Analysis image-to-video board with
sound, Seedance 2.5 ranks first and 2.0 third; 2.0 Fast is not ranked. Clips already made keep
the model they were made with: the choice is read when a clip is made."""

from __future__ import annotations

from pathlib import Path

from common import StepError, read_json, write_json

MODELS = {
    "fast": {
        "title": "Seedance 2.0 Fast", "short": "2.0 Fast",
        "note": "the cheapest and quickest; not ranked on the benchmarks",
        "sume": "seedance-2-fast", "fal": "bytedance/seedance-2.0/fast/image-to-video",
        "rates": {"sume": {"480p": 0.056246, "720p": 0.12096}, "fal": {"480p": 0.1125, "720p": 0.2419}},
    },
    "standard": {
        "title": "Seedance 2.0", "short": "2.0",
        "note": "ranked #3 for image-to-video with sound; steadier on busy motion than Fast",
        "sume": "seedance-2", "fal": "bytedance/seedance-2.0/image-to-video",
        # fal publishes 720p; 480p from its token formula at the full model's $0.014 per 1k tokens.
        "rates": {"sume": {"480p": 0.070308, "720p": 0.1512}, "fal": {"480p": 0.1406, "720p": 0.3034}},
    },
    "2.5": {
        "title": "Seedance 2.5", "short": "2.5",
        "note": "ranked #1 for image-to-video with sound (July 2026); about twice the price of Fast",
        "sume": "seedance-2.5", "fal": "bytedance/seedance-2.5/image-to-video",
        "rates": {"sume": {"480p": 0.1028, "720p": 0.23112}, "fal": {"480p": 0.2205, "720p": 0.4730}},
    },
}
ORDER = list(MODELS)


def check(value) -> str:
    v = str(value or "").strip().lower()
    if v not in MODELS:
        raise StepError(f"video model must be one of {', '.join(ORDER)}, got {value!r}")
    return v


def by_id(provider: str, model_id: str) -> str | None:
    """Which of the three a provider's model id is (None for a model VidGen does not list)."""
    return next((k for k, m in MODELS.items() if m[provider] == str(model_id or "").strip()), None)


def of(config: dict) -> str | None:
    """The model this config makes clips with, or None when config.local.yaml names another."""
    p = config["providers"]["video"]
    return by_id(p, config[p]["video_model"])


def run_choice(run_dir: Path | None) -> str | None:
    if run_dir is None:
        return None
    try:
        value = read_json(Path(run_dir) / "run.json").get("video_model")
    except (OSError, ValueError, AttributeError):
        return None
    return value if value in MODELS else None


def set_for_run(run_dir: Path, value: str | None) -> str | None:
    path = Path(run_dir) / "run.json"
    meta = read_json(path)
    if value is None:
        meta.pop("video_model", None)
    else:
        meta["video_model"] = check(value)
    write_json(path, meta)
    return run_choice(run_dir)


def apply(config: dict, run_dir: Path | None = None, model: str | None = None) -> dict:
    """`config` with this video's model in both providers' blocks, and that model's prices (by
    resolution, and the one for the resolution in use). Call it before clip_quality.apply, which
    picks the resolution from these prices. Changes and returns `config`."""
    want = model or run_choice(run_dir)
    if not want:
        return config
    m = MODELS[check(want)]
    for name in ("fal", "sume"):
        block = config.get(name)
        if not block:
            continue
        block["video_model"] = m[name]
        rates = dict(m["rates"][name])
        block["video_cost_by_resolution"] = rates
        res = str(block.get("video_resolution") or "480p")
        if res in rates:
            block["video_cost_per_second"] = float(rates[res])
    # The cost report reads the rate from the fal block whichever provider made the clips (common.py).
    if config["providers"]["video"] == "sume" and config.get("fal") and config.get("sume"):
        config["fal"]["video_cost_per_second"] = float(config["sume"]["video_cost_per_second"])
    return config


def prices() -> dict:
    """{model: {provider: {resolution: $ per second}}} for the create screen's estimates."""
    return {k: {p: dict(m["rates"][p]) for p in ("sume", "fal")} for k, m in MODELS.items()}
