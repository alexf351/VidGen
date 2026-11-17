"""Which video model makes a video's clips: Seedance 2.0 Mini, 2.0 Fast, 2.0, 2.5, or Grok Imagine 1.5.

The config says which one every video uses (`sume.video_model`, `fal.video_model`); a video's own
choice is kept in its run.json as "video_model" and wins over the config. Each model has its own
price per second at each resolution, on each provider, so the cost estimates follow the choice.

    MODELS                       the models, with their ids and prices on Sume and on fal
    of(config)                   the model this config makes clips with ("fast", "standard", "2.5"...)
    run_choice(run_dir)          the video's own choice, or None (the config's)
    set_for_run(run_dir, value)  save it (None = follow the config again)
    apply(config, run_dir|model) the config a job on this video uses, with its model and prices
    available(config, model)     is this model on the provider that makes this config's clips
    makes_sound(config)          does the model in use make clips with sound

What is known about quality (November 2026): on the Artificial Analysis image-to-video board with
sound, Seedance 2.5 ranks first and 2.0 third; 2.0 Fast and 2.0 Mini are not ranked. Clips
already made keep the model they were made with: the choice is read when a clip is made.

Seedance 2.0 Mini and Grok Imagine Video 1.5 are listed on Sume only (sume.com/docs/models,
prices from sume.com/sume-api/pricing, November 2026). Mini is the cheapest: about 37% under
Fast. Grok on Sume costs more than Fast ($0.08 against $0.056 a second at 480p) and Sume lists
no sound for it, so with clip sound on its clips come back silent and the lines are spoken by
the ElevenLabs voices. (xAI sells a cheaper Grok, 1.5 Lite at $0.02 a second, only on its own
API; VidGen does not talk to that.)"""

from __future__ import annotations

from pathlib import Path

from common import StepError, read_json, write_json

MODELS = {
    "mini": {
        "title": "Seedance 2.0 Mini", "short": "2.0 Mini",
        "note": "the cheapest: about a third less than Fast, with sound; on Sume only",
        "sume": "seedance-2-mini", "fal": None,
        "rates": {"sume": {"480p": 0.035154, "720p": 0.0756}},
    },
    "fast": {
        "title": "Seedance 2.0 Fast", "short": "2.0 Fast",
        "note": "quick and cheap; not ranked on the benchmarks",
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
    "grok": {
        "title": "Grok Imagine 1.5", "short": "Grok 1.5",
        "note": "xAI's model; on Sume it costs more than Seedance Fast and its clips have no sound "
                "(lines are spoken by the added voices); on Sume only",
        "sume": "grok-imagine-video-1.5", "fal": None, "audio": False,
        "rates": {"sume": {"480p": 0.08, "720p": 0.14}},
    },
}
ORDER = list(MODELS)


def check(value) -> str:
    v = str(value or "").strip().lower()
    if v not in MODELS:
        raise StepError(f"video model must be one of {', '.join(ORDER)}, got {value!r}")
    return v


def by_id(provider: str, model_id: str) -> str | None:
    """Which listed model a provider's model id is (None for a model VidGen does not list)."""
    want = str(model_id or "").strip()
    return next((k for k, m in MODELS.items() if m[provider] and m[provider] == want), None)


def available(config: dict, model: str) -> bool:
    """Is this model on the provider that makes this config's clips?"""
    return bool(MODELS[check(model)][config["providers"]["video"]])


def makes_sound(config: dict) -> bool:
    """Does the model this config makes clips with give them sound? (True for a model VidGen
    does not list: it is asked, and a silent clip is handled where it lands.)"""
    key = of(config)
    return key is None or MODELS[key].get("audio", True)


def require_available(config: dict, run_dir: Path | None) -> None:
    """Before clips are made: the video's chosen model has to be on the provider in use."""
    want = run_choice(run_dir)
    if want and not available(config, want):
        prov = config["providers"]["video"]
        raise StepError(f"{MODELS[want]['title']} is not on {prov}: it is on Sume only. Pick another video model "
                        f"for this video (its page, Video model), or make its clips with Sume.")


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
        if not block or not m[name]:          # not on this provider: its block keeps its own model
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
    return {k: {p: dict(m["rates"][p]) for p in ("sume", "fal") if p in m["rates"]} for k, m in MODELS.items()}
