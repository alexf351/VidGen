"""Images step: character reference sheets + one keyframe per shot, via fal.ai nano-banana."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import fal_api
from common import ROOT, StepError, parse_only, read_script, select_shots

SHEET_ASPECT = "16:9"
SHOT_ASPECT = "9:16"


# -------------------------------------------------------------- helpers ----

def characters_dir(run_dir: Path) -> Path:
    return run_dir / "characters"


def shots_dir(run_dir: Path) -> Path:
    return run_dir / "shots"


def sheet_path(run_dir: Path, char_id: str) -> Path:
    return characters_dir(run_dir) / f"{char_id}.png"


def shot_path(run_dir: Path, n: int) -> Path:
    return shots_dir(run_dir) / f"{n}.png"


def cache_path(config: dict, char_id: str) -> Path:
    return ROOT / config["characters_cache_dir"] / f"{char_id}.png"


def _locked_by_id(config: dict) -> dict[str, dict]:
    return {c["id"]: c for c in config.get("locked_characters", [])}


def _sheet_style(style: str) -> str:
    # The sheet is a landscape line-up, so drop the vertical framing from the style line.
    return re.sub(r",?\s*vertical\s*9:16", "", style, flags=re.I).strip(" ,")


def sheet_prompt(description: str, style: str) -> str:
    return (
        f"{_sheet_style(style)}, character reference sheet of {description}. "
        "Three full-body views of the same character standing side by side: front view, "
        "three-quarter view, side profile view. Neutral plain grey outfit (a simple t-shirt and "
        "trousers); if the character is a mascot or robot, show its design exactly as described. "
        "Relaxed neutral pose, plain light grey studio background, even soft lighting, no text."
    )


def shot_prompt(shot: dict, ref_ids: list[str]) -> str:
    prompt = shot["image_prompt"].strip()
    if not ref_ids:
        return prompt
    order = ", ".join(f"{i + 1}) {cid}" for i, cid in enumerate(ref_ids))
    return (
        f"{prompt}\n\n"
        f"Reference images, in order: {order}. Each reference is a character sheet; keep that "
        "character's face, hair, skin and build identical to its sheet. Do not copy the sheet "
        "layout or grey background; render the scene described above."
    )


# ------------------------------------------------------- reference sheets ----

def ensure_sheets(run_dir: Path, config: dict, script: dict, needed: set[str] | None = None) -> dict[str, Path]:
    """Make sure runs/<id>/characters/<cid>.png exists for every needed character.

    Priority: config image_path -> characters_cache -> existing run sheet -> generate.
    Generated sheets for locked characters are copied into characters_cache for later runs."""
    locked = _locked_by_id(config)
    style = config["style"]
    out: dict[str, Path] = {}
    for c in script["characters"]:
        cid = c["id"]
        if needed is not None and cid not in needed:
            continue
        dest = sheet_path(run_dir, cid)
        dest.parent.mkdir(parents=True, exist_ok=True)
        lock = locked.get(cid)

        if lock and lock.get("image_path"):
            src = ROOT / lock["image_path"]
            if not src.exists():
                raise StepError(f"locked character {cid!r} image_path {src} does not exist")
            if not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime:
                shutil.copyfile(src, dest)
                print(f"  [{cid}] reference from config: {lock['image_path']}")
            else:
                print(f"  [{cid}] reference sheet exists, skipping")
        elif dest.exists():
            print(f"  [{cid}] reference sheet exists, skipping")
        elif lock and cache_path(config, cid).exists():
            shutil.copyfile(cache_path(config, cid), dest)
            print(f"  [{cid}] reference sheet from cache")
        else:
            print(f"  [{cid}] generating reference sheet...")
            result = fal_api.call(config["fal"]["image_model"], {
                "prompt": sheet_prompt(c["description"], style),
                "num_images": 1,
                "aspect_ratio": SHEET_ASPECT,
                "output_format": "png",
            }, label=f"sheet {cid}")
            fal_api.download(fal_api.first_image_url(result, f"sheet {cid}"), dest)
            if lock:
                cache = cache_path(config, cid)
                cache.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(dest, cache)
                print(f"  [{cid}] cached at {cache.relative_to(ROOT)}")
        out[cid] = dest
    return out


# --------------------------------------------------------------- keyframes ----

def generate_keyframe(run_dir: Path, config: dict, shot: dict, sheets: dict[str, Path]) -> Path:
    n = shot["n"]
    dest = shot_path(run_dir, n)
    dest.parent.mkdir(parents=True, exist_ok=True)
    ref_ids = [cid for cid in shot["characters"] if cid in sheets]
    missing = [cid for cid in shot["characters"] if cid not in sheets]
    if missing:
        raise StepError(f"shot {n}: no reference sheet for {missing}")

    label = f"shot {n}"
    if ref_ids:
        result = fal_api.call(config["fal"]["image_edit_model"], {
            "prompt": shot_prompt(shot, ref_ids),
            "image_urls": [fal_api.upload(sheets[cid]) for cid in ref_ids],
            "num_images": 1,
            "aspect_ratio": SHOT_ASPECT,
            "output_format": "png",
        }, label=label)
    else:
        result = fal_api.call(config["fal"]["image_model"], {
            "prompt": shot_prompt(shot, []),
            "num_images": 1,
            "aspect_ratio": SHOT_ASPECT,
            "output_format": "png",
        }, label=label)
    fal_api.download(fal_api.first_image_url(result, label), dest)

    video = dest.with_suffix(".mp4")
    if shot.get("animate") and video.exists():
        print(f"  shot {n}: note {video.relative_to(run_dir)} was made from the old keyframe; "
              f"rerun video --only {n} to refresh it")
    return dest


def _run(run_dir: Path, config: dict, only: set[int] | None, force: bool) -> None:
    fal_api.require_key()
    script = read_script(run_dir)
    shots = select_shots(script, only)

    print(f"[images] reference sheets ({len(script['characters'])} characters)")
    needed = None if only is None else {cid for s in shots for cid in s["characters"]}
    sheets = ensure_sheets(run_dir, config, script, needed)

    print(f"[images] keyframes ({len(shots)} shots)")
    generated = 0
    for shot in shots:
        n = shot["n"]
        dest = shot_path(run_dir, n)
        if dest.exists() and not force:
            print(f"  shot {n}: exists, skipping")
            continue
        who = ", ".join(shot["characters"]) or "no characters"
        print(f"  shot {n}: generating ({who})...")
        generate_keyframe(run_dir, config, shot, sheets)
        generated += 1
    cost = generated * float(config["fal"]["image_cost"])
    print(f"[images] generated {generated} keyframe(s), est. ${cost:.2f} -> {shots_dir(run_dir)}")


def run(run_dir: Path, config: dict, only: str | None = None) -> None:
    """Full step. `only` is a comma-separated shot list; those shots are regenerated even if present."""
    only_set = parse_only(only)
    _run(run_dir, config, only_set, force=only_set is not None)


def reroll_shot(run_dir: Path, config: dict, shot_number: int) -> None:
    _run(run_dir, config, {shot_number}, force=True)
