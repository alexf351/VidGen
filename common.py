"""Shared helpers: config loading, run directories, step registry."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
RUNS_DIR = ROOT / "runs"
CONFIG_PATH = ROOT / "config.yaml"

# Pipeline order. Every step module exposes run(run_dir, config).
STEP_ORDER = ["script", "images", "video", "voice", "assemble"]


class StepError(Exception):
    """A step failed in a way the user needs to see, without a traceback."""


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("max_animated_shots", 8)
    cfg.setdefault("script", {})
    cfg["script"].setdefault("model", "claude-sonnet-5-5")
    cfg["script"].setdefault("max_tokens", 16000)
    if not cfg.get("style"):
        raise StepError("config.yaml is missing the 'style' line")
    cfg["locked_characters"] = _check_locked_characters(cfg.get("locked_characters") or [])
    cfg.setdefault("characters_cache_dir", "characters_cache")
    fal = cfg.setdefault("fal", {})
    fal.setdefault("image_model", "fal-ai/nano-banana")
    fal.setdefault("image_edit_model", "fal-ai/nano-banana/edit")
    fal.setdefault("image_cost", 0.0398)
    fal.setdefault("video_model", "bytedance/seedance-2.0/fast/image-to-video")
    fal.setdefault("video_seconds", 4)
    fal.setdefault("video_resolution", "480p")
    fal.setdefault("video_audio", False)
    fal.setdefault("video_cost_per_second", {"480p": 0.1125, "720p": 0.2419})
    _resolve_video_rate(fal)
    _apply_providers(cfg)
    cfg["voices"] = {str(k): (v or "") for k, v in (cfg.get("voices") or {}).items()}
    el = cfg.setdefault("elevenlabs", {})
    el.setdefault("model_id", "eleven_multilingual_v2")
    el.setdefault("output_format", "mp3_44100_128")
    el.setdefault("cost_per_1k_chars", 0.22)
    asm = cfg.setdefault("assemble", {})
    for key, default in [("width", 1080), ("height", 1920), ("fps", 30),
                         ("vo_pad_seconds", 0.25), ("min_shot_seconds", 1.2), ("zoom_end", 1.08),
                         ("card_seconds", 1.5), ("card_fade_ms", 200),
                         ("caption_font", "Montserrat Black Italic"),
                         ("caption_fallback_font", "Arial Black"), ("caption_size", 90),
                         ("caption_y", 0.55), ("music_volume", 0.15), ("saturation", 0.85)]:
        asm.setdefault(key, default)
    cfg["music_path"] = (cfg.get("music_path") or "").strip()
    cfg["outro_path"] = (cfg.get("outro_path") or "").strip()
    return cfg


def read_script(run_dir: Path) -> dict:
    path = run_dir / "script.json"
    if not path.exists():
        raise StepError(f"{path} is missing; run the script step first")
    return read_json(path)


def parse_only(only: str | None) -> set[int] | None:
    """'3,7' -> {3, 7}; None/'' -> None (meaning every shot)."""
    if not only:
        return None
    try:
        nums = {int(x) for x in only.replace(" ", "").split(",") if x}
    except ValueError:
        raise StepError(f"--only expects comma-separated shot numbers, got {only!r}") from None
    if not nums:
        raise StepError("--only was given but no shot numbers followed")
    return nums


def select_shots(script: dict, only: set[int] | None) -> list[dict]:
    shots = script["shots"]
    if only is None:
        return shots
    known = {s["n"] for s in shots}
    missing = sorted(only - known)
    if missing:
        raise StepError(f"shot number(s) {missing} not in script.json (has 1-{len(shots)})")
    return [s for s in shots if s["n"] in only]


def _resolve_video_rate(block: dict, section: str = "fal") -> None:
    """video_cost_per_second may be a {resolution: rate} map. Keep the map and leave the
    active resolution's rate as a plain number, so every reader of the rate stays correct."""
    rates = block["video_cost_per_second"]
    res = str(block["video_resolution"]).strip()
    block["video_resolution"] = res
    if isinstance(rates, dict):
        block["video_cost_by_resolution"] = {str(k): float(v) for k, v in rates.items()}
        if res not in block["video_cost_by_resolution"]:
            raise StepError(f"config.yaml: {section}.video_cost_per_second has no rate for "
                            f"video_resolution '{res}' (has {sorted(block['video_cost_by_resolution'])})")
        block["video_cost_per_second"] = block["video_cost_by_resolution"][res]
    else:
        block["video_cost_per_second"] = float(rates)


PROVIDERS = ("fal", "sume")


def _apply_providers(cfg: dict) -> None:
    prov = cfg.setdefault("providers", {}) or {}
    cfg["providers"] = prov
    for kind in ("images", "video"):
        value = str(prov.get(kind) or "fal").strip().lower()
        if value not in PROVIDERS:
            raise StepError(f"config.yaml: providers.{kind} must be one of {', '.join(PROVIDERS)}, got '{value}'")
        prov[kind] = value

    sume = cfg.setdefault("sume", {}) or {}
    cfg["sume"] = sume
    for key, default in [("base_url", "https://api.sume.com"), ("image_model", "nano-banana"),
                         ("image_cost", 0.039), ("video_model", "seedance-2-fast"),
                         ("video_seconds", 4), ("video_resolution", "480p"), ("video_audio", False),
                         ("video_cost_per_second", {"480p": 0.056246, "720p": 0.12096}),
                         ("max_concurrent", 2), ("retry_window_seconds", 600),
                         ("retry_base_seconds", 5), ("job_timeout_seconds", 900)]:
        sume.setdefault(key, default)
    if int(sume["max_concurrent"]) < 1:
        raise StepError("config.yaml: sume.max_concurrent must be at least 1")
    _resolve_video_rate(sume, "sume")

    # The assemble step's cost report reads image_cost / video_seconds / video_cost_per_second
    # from the fal block. When Sume generates a kind, point those keys at Sume's numbers so the
    # final estimate prices what was actually used. fal's settings for that kind are not read
    # by anything else while Sume is selected.
    fal = cfg["fal"]
    if prov["images"] == "sume":
        fal["image_cost"] = float(sume["image_cost"])
    if prov["video"] == "sume":
        fal["video_seconds"] = int(sume["video_seconds"])
        fal["video_cost_per_second"] = float(sume["video_cost_per_second"])


def _check_locked_characters(raw) -> list[dict]:
    """Validate config.locked_characters and fill in defaults (image_path -> "")."""
    if not isinstance(raw, list):
        raise StepError("config.yaml: locked_characters must be a list")
    seen: set[str] = set()
    out = []
    for i, c in enumerate(raw):
        if not isinstance(c, dict):
            raise StepError(f"config.yaml: locked_characters[{i}] must be a mapping")
        cid, desc = c.get("id"), c.get("description")
        if not isinstance(cid, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", cid):
            raise StepError(f"config.yaml: locked_characters[{i}].id must be a lowercase slug, got {cid!r}")
        if cid in seen:
            raise StepError(f"config.yaml: duplicate locked character id {cid!r}")
        if not isinstance(desc, str) or not desc.strip():
            raise StepError(f"config.yaml: locked_characters[{i}] ({cid}) needs a description")
        seen.add(cid)
        entry = dict(c)
        entry["description"] = desc.strip()
        entry["image_path"] = (c.get("image_path") or "").strip()
        out.append(entry)
    return out


def slugify(text: str, max_len: int = 32) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "run"


def new_run_id(premise: str) -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{slugify(premise)}"


def run_dir_for(run_id: str, must_exist: bool = True) -> Path:
    run_dir = RUNS_DIR / run_id
    if must_exist and not run_dir.is_dir():
        raise StepError(f"run '{run_id}' not found under {RUNS_DIR}")
    return run_dir


def create_run(premise: str) -> Path:
    run_id = new_run_id(premise)
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "premise.txt").write_text(premise.strip() + "\n", encoding="utf-8")
    write_json(run_dir / "run.json", {
        "run_id": run_id,
        "premise": premise.strip(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    return run_dir


def read_premise(run_dir: Path) -> str:
    path = run_dir / "premise.txt"
    if not path.exists():
        raise StepError(f"{path} is missing; was this run created with 'main.py new'?")
    return path.read_text(encoding="utf-8").strip()


def read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def not_implemented(step_name: str) -> None:
    print(f"[{step_name}] not implemented yet")
