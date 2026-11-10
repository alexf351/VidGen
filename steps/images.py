"""Images step: character reference sheets + one keyframe per shot, via fal.ai nano-banana."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import threading

import fal_api
import sume_api
from common import ROOT, StepError, parse_only, read_script, select_shots
from parallel import TaskRunner

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


def needs_keyframe(shot: dict) -> bool:
    """Cards and app screens are drawn at assembly; a letter shot with an empty image_prompt
    keeps the previous shot's picture. Everything else gets its own keyframe."""
    if shot.get("card") or shot.get("app_screen"):
        return False
    return bool(str(shot.get("image_prompt") or "").strip())


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


# -------------------------------------------------------------- provider ----

def image_provider(config: dict) -> str:
    return config["providers"]["images"]


def image_cost(config: dict) -> float:
    block = config["sume"] if image_provider(config) == "sume" else config["fal"]
    return float(block["image_cost"])


def _workers(config: dict) -> int:
    # fal runs one request at a time, as it always has; Sume runs up to its concurrency cap.
    return int(config["sume"]["max_concurrent"]) if image_provider(config) == "sume" else 1


def _require_key(config: dict) -> None:
    if image_provider(config) == "sume":
        sume_api.require_key()
    else:
        fal_api.require_key()


def _generate_image(config: dict, prompt: str, aspect: str, refs: list[Path], label: str,
                    dest: Path) -> None:
    """One image to `dest`: an edit when reference images are given, else text-to-image."""
    if image_provider(config) == "sume":
        sume_api.download(sume_api.generate_image(config, prompt, aspect, refs, label), dest)
        return
    if refs:
        result = fal_api.call(config["fal"]["image_edit_model"], {
            "prompt": prompt,
            "image_urls": [fal_api.upload(p) for p in refs],
            "num_images": 1,
            "aspect_ratio": aspect,
            "output_format": "png",
        }, label=label)
    else:
        result = fal_api.call(config["fal"]["image_model"], {
            "prompt": prompt,
            "num_images": 1,
            "aspect_ratio": aspect,
            "output_format": "png",
        }, label=label)
    fal_api.download(fal_api.first_image_url(result, label), dest)


# ------------------------------------------------------- reference sheets ----

def ensure_sheets(run_dir: Path, config: dict, script: dict, needed: set[str] | None = None) -> dict[str, Path]:
    """Make sure runs/<id>/characters/<cid>.png exists for every needed character.

    Priority: config image_path -> characters_cache -> existing run sheet -> generate.
    Generated sheets for locked characters are copied into characters_cache for later runs.
    Characters from your library (characters.py) get a sheet in this run's style, drawn from
    their picture once per format and cached."""
    locked = _locked_by_id(config)
    style = config["style"]
    out: dict[str, Path] = {}
    runner = TaskRunner(_workers(config))

    def generate_sheet(c: dict, dest: Path, lock: dict | None) -> None:
        cid = c["id"]
        print(f"  [{cid}] generating reference sheet...")
        _generate_image(config, sheet_prompt(c["description"], style), SHEET_ASPECT, [],
                        f"sheet {cid}", dest)
        if lock:
            cache = cache_path(config, cid)
            cache.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(dest, cache)
            print(f"  [{cid}] cached at {cache.relative_to(ROOT)}")

    def library_sheet(c: dict, dest: Path, lock: dict) -> None:
        import characters
        cid = c["id"]

        def generate(prompt: str, refs: list[Path], to: Path) -> None:
            print(f"  [{cid}] drawing a reference sheet from your character's picture...")
            _generate_image(config, prompt, SHEET_ASPECT, refs, f"sheet {cid}", to)

        print(f"  [{cid}] {characters.library_sheet(config, lock, dest, generate)}")

    for c in script["characters"]:
        cid = c["id"]
        if needed is not None and cid not in needed:
            continue
        dest = sheet_path(run_dir, cid)
        dest.parent.mkdir(parents=True, exist_ok=True)
        lock = locked.get(cid)

        if lock and lock.get("library"):
            runner.submit(library_sheet, c, dest, lock)
        elif lock and lock.get("image_path"):
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
            runner.submit(generate_sheet, c, dest, lock)
        out[cid] = dest
    runner.join()
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

    _generate_image(config, shot_prompt(shot, ref_ids), SHOT_ASPECT,
                    [sheets[cid] for cid in ref_ids], f"shot {n}", dest)

    video = dest.with_suffix(".mp4")
    if (shot.get("animate") or shot.get("talk")) and video.exists():
        print(f"  shot {n}: note {video.relative_to(run_dir)} was made from the old keyframe; "
              f"rerun video --only {n} to refresh it")
    return dest


def _run(run_dir: Path, config: dict, only: set[int] | None, force: bool) -> None:
    _require_key(config)
    script = read_script(run_dir)
    shots = select_shots(script, only)
    if image_provider(config) == "sume":
        print(f"[images] provider: Sume ({config['sume']['image_model']}), "
              f"up to {_workers(config)} at once")

    print(f"[images] reference sheets ({len(script['characters'])} characters)")
    needed = None if only is None else {cid for s in shots for cid in s["characters"]}
    sheets = ensure_sheets(run_dir, config, script, needed)

    print(f"[images] keyframes ({len(shots)} shots)")
    runner = TaskRunner(_workers(config))
    done = []
    lock = threading.Lock()

    def make(shot: dict) -> None:
        who = ", ".join(shot["characters"]) or "no characters"
        print(f"  shot {shot['n']}: generating ({who})...")
        generate_keyframe(run_dir, config, shot, sheets)
        with lock:
            done.append(shot["n"])

    for shot in shots:
        n = shot["n"]
        if shot.get("card"):
            print(f"  shot {n}: time card \"{shot['card']}\", no image needed")
            continue
        if shot.get("app_screen"):
            print(f"  shot {n}: real app screenshot {shot['app_screen']}, no image needed")
            continue
        if not needs_keyframe(shot):
            print(f"  shot {n}: keeps the previous background, no image needed")
            continue
        dest = shot_path(run_dir, n)
        if dest.exists() and not force:
            print(f"  shot {n}: exists, skipping")
            continue
        runner.submit(make, shot)
    runner.join()
    generated = len(done)
    cost = generated * image_cost(config)
    print(f"[images] generated {generated} keyframe(s), est. ${cost:.2f} -> {shots_dir(run_dir)}")


def run(run_dir: Path, config: dict, only: str | None = None) -> None:
    """Full step. `only` is a comma-separated shot list; those shots are regenerated even if present."""
    only_set = parse_only(only)
    _run(run_dir, config, only_set, force=only_set is not None)


def reroll_shot(run_dir: Path, config: dict, shot_number: int) -> None:
    _run(run_dir, config, {shot_number}, force=True)
