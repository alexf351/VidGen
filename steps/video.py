"""Video step. Not built yet."""

from pathlib import Path

from common import not_implemented


def run(run_dir: Path, config: dict) -> None:
    not_implemented("video")


def reroll_shot(run_dir: Path, config: dict, shot_number: int) -> None:
    not_implemented(f"video reroll shot {shot_number}")
