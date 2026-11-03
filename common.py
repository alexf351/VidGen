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
    return cfg


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
