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
    fal.setdefault("video_resolution", "720p")
    fal.setdefault("video_audio", False)
    fal.setdefault("video_cost_per_second", 0.2419)
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
