"""Images step: character reference sheets + one keyframe per shot, via fal.ai nano-banana."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import threading

import fal_api
import sume_api
from common import ROOT, StepError, parse_only, read_script, select_shots
import downloads
import progress
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
    if shot.get("card") or shot.get("app_screen") or shot.get("texts"):
        return False
    return bool(str(shot.get("image_prompt") or "").strip())


def _locked_by_id(config: dict) -> dict[str, dict]:
    return {c["id"]: c for c in config.get("locked_characters", [])}


def _sheet_style(style: str) -> str:
    # The sheet is a landscape line-up, so drop the vertical framing from the style line.
    return re.sub(r",?\s*vertical\s*9:16", "", style, flags=re.I).strip(" ,")


def sheet_prompt(description: str, style: str, outfit: str = "") -> str:
    """`outfit` is a locked character's fixed way of dressing (format.yaml `outfit:`). The sheet
    then shows a plain black version of it instead of the usual grey, so the reference picture
    does not pull every shot back toward a grey t-shirt."""
    clothes = ("Simple plain black outfit (a fitted long-sleeved black top and black trousers)"
               if outfit else "Neutral plain grey outfit (a simple t-shirt and trousers)")
    return (
        f"{_sheet_style(style)}, character reference sheet of {description}. "
        "Three full-body views of the same character standing side by side: front view, "
        f"three-quarter view, side profile view. {clothes}; if the character is a mascot or "
        "robot, show its design exactly as described. "
        "Relaxed neutral pose, plain light grey studio background, even soft lighting, no text."
    )


def _cache_note(config: dict, char_id: str) -> Path:
    return cache_path(config, char_id).with_suffix(".txt")


def _look(c: dict) -> str:
    """What a cached sheet was drawn from: the description, plus the fixed outfit if any."""
    return "\n".join(x for x in (c.get("description", "").strip(), (c.get("outfit") or "").strip()) if x)


# Sheets cached before the notes existed have no <id>.txt. They are kept (so a recurring
# character keeps the same face from video to video), except for characters whose look changed
# while there were no notes: sofia went from blonde to goth.
_REDRAW_WITHOUT_NOTE = {"sofia"}


def cache_is_current(config: dict, lock: dict) -> bool:
    """True when characters_cache/<id>.png was drawn from this character's current look.
    characters_cache/<id>.txt records the look the sheet was drawn from; a different look
    means the sheet is redrawn."""
    if not cache_path(config, lock["id"]).exists():
        return False
    note = _cache_note(config, lock["id"])
    if not note.exists():
        return lock["id"] not in _REDRAW_WITHOUT_NOTE
    try:
        return note.read_text(encoding="utf-8").strip() == _look(lock)
    except OSError:
        return False


MAX_WARDROBE_REFS = 2


def wardrobe_shots(shots: list[dict], i: int) -> list[tuple[list[str], dict]]:
    """For shots[i] marked "same_scene": the earlier pictures that show what its people wear
    in this scene, for everyone the scene's first shot does not show.

    The first shot of a scene carries the place and the clothes of whoever is in it. Someone
    who walks in later (the hero arriving at the meeting) is not in that picture, so nothing
    held his clothes from shot to shot: he came out in his sheet's clothes in one shot and in
    another man's waistcoat in the next. For each such person this finds the first shot of the
    scene that has them, which every later shot then copies their clothes from.

    Returns [(character ids, that shot), ...], one entry per picture, at most MAX_WARDROBE_REFS."""
    from steps.script import scene_anchor
    a = scene_anchor(shots, i)
    if a is None:
        return []
    shown = set(shots[a].get("characters") or [])
    found: dict[int, list[str]] = {}
    for cid in shots[i].get("characters") or []:
        if cid in shown:
            continue
        for j in range(a + 1, i):
            s = shots[j]
            if (isinstance(s, dict) and cid in (s.get("characters") or []) and scene_anchor(shots, j) == a
                    and str(s.get("image_prompt") or "").strip() and not s.get("flash")):
                found.setdefault(j, []).append(cid)
                break
    return [(ids, shots[j]) for j, ids in sorted(found.items())][:MAX_WARDROBE_REFS]


def shot_prompt(shot: dict, ref_ids: list[str], scene: bool = False,
                wardrobe: list[list[str]] | None = None) -> str:
    """The keyframe prompt. `scene`: the next reference image after the sheets is the first shot
    of the scene this shot continues (shot "same_scene"), given so the place and the clothes
    carry over. `wardrobe`: after that come earlier shots of the scene, one per entry, each
    showing the clothes of the characters listed (see wardrobe_shots)."""
    prompt = shot["image_prompt"].strip()
    wardrobe = wardrobe or []
    if not ref_ids and not scene and not wardrobe:
        return prompt
    parts = [prompt, ""]
    if ref_ids:
        order = ", ".join(f"{i + 1}) {cid}" for i, cid in enumerate(ref_ids))
        parts.append(
            f"Reference images, in order: {order}. Each reference is a character sheet; keep that "
            "character's face, hair, skin and build identical to its sheet. The sheet's plain grey "
            "clothes, layout and background are placeholders: dress everyone as described above.")
    at = len(ref_ids)
    if scene:
        at += 1
        which = f"Reference image {at}" if at > 1 or wardrobe else "The reference image"
        parts.append(
            f"{which} is an earlier shot of this same scene: keep its place, time of day and "
            "lighting, and the clothes of the people in it (on those it wins over the description "
            "above). Anyone not in it is dressed as described above, never in another person's "
            "clothes. Faces and bodies come from each character's own sheet. New camera angle and "
            "poses, as described above.")
    for ids in wardrobe:
        at += 1
        who = " and ".join(ids)
        parts.append(
            f"Reference image {at} is an earlier shot of this scene with {who}: {who} "
            f"{'wear' if len(ids) > 1 else 'wears'} exactly the same clothes here, whatever the description "
            f"says. Take only the clothes from it.")
    if scene or wardrobe:
        # An earlier shot shows other people too (the scene's first shot has whoever opened the
        # scene), and the model would carry one of them into a shot meant for one person.
        names = " and ".join(shot.get("characters") or [])
        parts.append(f"Only {names or 'the people described above'} {'is' if len(shot.get('characters') or []) == 1 else 'are'} "
                     "in this picture: bring nobody else over from the earlier shots, not even in the background.")
    return "\n".join(parts) if len(parts) > 2 else prompt


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
        if downloads.resume(dest, sume_api.download, label):
            return
        downloads.save(sume_api.generate_image(config, prompt, aspect, refs, label), dest, sume_api.download)
        return
    if downloads.resume(dest, fal_api.download, label):
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
    downloads.save(fal_api.first_image_url(result, label), dest, fal_api.download)


# ------------------------------------------------------- reference sheets ----

def ensure_sheets(run_dir: Path, config: dict, script: dict, needed: set[str] | None = None) -> dict[str, Path]:
    """Make sure runs/<id>/characters/<cid>.png exists for every needed character.

    Priority: config image_path -> existing run sheet -> characters_cache -> generate.
    Generated sheets for locked characters are copied into characters_cache for later runs,
    with a note of the look they were drawn from; change the look and the sheet is redrawn.
    Characters from your library (characters.py) get a sheet in this run's style, drawn from
    their picture once per format and cached."""
    locked = _locked_by_id(config)
    style = config["style"]
    out: dict[str, Path] = {}
    runner = TaskRunner(_workers(config))

    def generate_sheet(c: dict, dest: Path, lock: dict | None) -> None:
        cid = c["id"]
        print(f"  [{cid}] generating reference sheet...")
        _generate_image(config, sheet_prompt(c["description"], style, (lock or {}).get("outfit", "")),
                        SHEET_ASPECT, [], f"sheet {cid}", dest)
        if lock:
            cache = cache_path(config, cid)
            cache.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(dest, cache)
            _cache_note(config, cid).write_text(_look(lock) + "\n", encoding="utf-8")
            print(f"  [{cid}] cached at {cache.relative_to(ROOT)}")
        progress.tick()

    def library_sheet(c: dict, dest: Path, lock: dict) -> None:
        import characters
        cid = c["id"]

        def generate(prompt: str, refs: list[Path], to: Path) -> None:
            print(f"  [{cid}] drawing a reference sheet from your character's picture...")
            _generate_image(config, prompt, SHEET_ASPECT, refs, f"sheet {cid}", to)

        print(f"  [{cid}] {characters.library_sheet(config, lock, dest, generate)}")
        progress.tick()

    for c in script["characters"]:
        cid = c["id"]
        if needed is not None and cid not in needed:
            continue
        dest = sheet_path(run_dir, cid)
        dest.parent.mkdir(parents=True, exist_ok=True)
        lock = locked.get(cid)

        if lock and lock.get("library"):
            progress.add()
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
        elif lock and cache_is_current(config, lock):
            shutil.copyfile(cache_path(config, cid), dest)
            if not _cache_note(config, cid).exists():      # an older sheet: record its look now
                _cache_note(config, cid).write_text(_look(lock) + "\n", encoding="utf-8")
            print(f"  [{cid}] reference sheet from cache")
        else:
            if lock and cache_path(config, cid).exists():
                print(f"  [{cid}] the cached sheet was drawn from an older description, redrawing it")
            progress.add()
            runner.submit(generate_sheet, c, dest, lock)
        out[cid] = dest
    runner.join()
    return out


# ------------------------------------------------- the hand for app screens ----

def ensure_hand(run_dir: Path, config: dict, script: dict) -> None:
    """For formats with app_screen_hand: the picture of a hand holding a green-screen phone that
    the assemble step puts the real screenshot on. Drawn once per format and cached. Never fails
    the step: without it, app screens use the plain phone frame."""
    import phone_hand
    if not phone_hand.enabled(config) or not any(s.get("app_screen") or s.get("texts") for s in script["shots"]):
        return
    dest = phone_hand.run_path(run_dir)
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    cache = phone_hand.cache_path(config, script)
    if cache.exists() and phone_hand.usable(cache):
        shutil.copyfile(cache, dest)
        print("[images] app screen: the hand holding the phone comes from the cache")
        return
    print("[images] app screen: drawing the hand that holds the phone...")
    progress.add()
    tmp = dest.with_name("hand.try.png")
    try:
        for attempt in (1, 2):
            _generate_image(config, phone_hand.prompt(config, script), SHOT_ASPECT, [], "hand", tmp)
            if phone_hand.usable(tmp):
                tmp.replace(dest)
                cache.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(dest, cache)
                print(f"  hand: ready, cached at {cache.relative_to(ROOT)}")
                break
            tmp.unlink(missing_ok=True)
            print("  hand: the picture has no clean green screen" +
                  (", trying once more" if attempt == 1 else "; app screens will use the plain phone frame"))
    except StepError as e:
        tmp.unlink(missing_ok=True)
        print(f"  hand: could not be drawn ({e}); app screens will use the plain phone frame")
    progress.tick()


# --------------------------------------------------------------- keyframes ----

def generate_keyframe(run_dir: Path, config: dict, shot: dict, sheets: dict[str, Path],
                      scene_ref: Path | None = None,
                      wardrobe: list[tuple[list[str], Path]] | None = None) -> Path:
    """`scene_ref`: the keyframe of the first shot of the scene this shot continues.
    `wardrobe`: [(character ids, keyframe of an earlier shot of the scene with them)], so people
    the scene's first shot does not show keep their clothes too (wardrobe_shots)."""
    n = shot["n"]
    dest = shot_path(run_dir, n)
    dest.parent.mkdir(parents=True, exist_ok=True)
    ref_ids = [cid for cid in shot["characters"] if cid in sheets]
    missing = [cid for cid in shot["characters"] if cid not in sheets]
    if missing:
        raise StepError(f"shot {n}: no reference sheet for {missing}")
    own = [sheets[cid] for cid in ref_ids]
    limit = int(config[image_provider(config)].get("max_reference_images") or 0)
    if scene_ref is not None and limit and len(own) + 1 > limit:
        print(f"  shot {n}: {len(own)} characters plus the scene picture is more reference pictures than "
              f"{image_provider(config)} takes ({limit}), so the scene picture is left out")
        scene_ref = None
    wardrobe = list(wardrobe or []) if scene_ref is not None else []
    if wardrobe and limit and len(own) + 1 + len(wardrobe) > limit:
        wardrobe = wardrobe[:max(0, limit - len(own) - 1)]
    if scene_ref is not None:
        try:
            _generate_image(config, shot_prompt(shot, ref_ids, scene=True, wardrobe=[ids for ids, _ in wardrobe]),
                            SHOT_ASPECT, own + [scene_ref] + [p for _, p in wardrobe], f"shot {n}", dest)
        except StepError as e:
            # A refused request costs nothing. Draw the shot the way it was drawn before scene
            # references existed, rather than failing the step.
            if "HTTP 400" not in str(e):
                raise
            print(f"  shot {n}: the scene picture was refused ({e}); drawing this shot without it")
            scene_ref = None
    if scene_ref is None:
        _generate_image(config, shot_prompt(shot, ref_ids), SHOT_ASPECT, own, f"shot {n}", dest)

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

    progress.plan(sum(1 for s in shots if not s.get("card") and not s.get("app_screen")
                      and needs_keyframe(s) and (force or not shot_path(run_dir, s["n"]).exists())),
                  "images")
    print(f"[images] reference sheets ({len(script['characters'])} characters)")
    needed = None if only is None else {cid for s in shots for cid in s["characters"]}
    sheets = ensure_sheets(run_dir, config, script, needed)
    if only is None:
        ensure_hand(run_dir, config, script)

    print(f"[images] keyframes ({len(shots)} shots)")
    done = []
    lock = threading.Lock()

    # A shot marked "same_scene" is drawn with the first shot of its scene as a reference, so
    # the place and the clothes carry over. Scene starters are drawn first, then the rest.
    from steps.script import scene_anchor
    every = script["shots"]
    anchor_of: dict[int, dict] = {}
    for i, s in enumerate(every):
        a = scene_anchor(every, i)
        if a is not None:
            anchor_of[s["n"]] = every[a]

    # People the scene's first shot does not show take their clothes from the first shot of the
    # scene that has them (wardrobe_shots), so that shot has to be drawn before the ones after it.
    index_of = {s["n"]: i for i, s in enumerate(every)}
    clothes_of: dict[int, list[tuple[list[str], dict]]] = {
        n: wardrobe_shots(every, index_of[n]) for n in anchor_of}

    def make(shot: dict) -> None:
        who = ", ".join(shot["characters"]) or "no characters"
        anchor = anchor_of.get(shot["n"])
        scene_ref = shot_path(run_dir, anchor["n"]) if anchor else None
        if scene_ref is not None and not scene_ref.exists():
            print(f"  shot {shot['n']}: shot {anchor['n']} (the start of its scene) has no image yet, "
                  f"so this one is drawn without it")
            scene_ref = None
        same = f", same scene as shot {anchor['n']}" if scene_ref else ""
        wardrobe = [(ids, shot_path(run_dir, w["n"])) for ids, w in clothes_of.get(shot["n"], [])
                    if scene_ref and shot_path(run_dir, w["n"]).exists()]
        for ids, w in clothes_of.get(shot["n"], []) if scene_ref else []:
            if shot_path(run_dir, w["n"]).exists():
                same += f", {' and '.join(ids)} dressed as in shot {w['n']}"
        print(f"  shot {shot['n']}: generating ({who}{same})...")
        generate_keyframe(run_dir, config, shot, sheets, scene_ref, wardrobe)
        progress.tick()
        with lock:
            done.append(shot["n"])

    todo: list[dict] = []
    for shot in shots:
        n = shot["n"]
        if shot.get("card"):
            print(f"  shot {n}: time card \"{shot['card']}\", no image needed")
            continue
        if shot.get("app_screen"):
            print(f"  shot {n}: real app screenshot {shot['app_screen']}, no image needed")
            continue
        if shot.get("texts"):
            print(f"  shot {n}: text messages from {shot['texts']['from']}, no image needed")
            continue
        if not needs_keyframe(shot):
            print(f"  shot {n}: keeps the previous background, no image needed")
            continue
        dest = shot_path(run_dir, n)
        if dest.exists() and not force:
            print(f"  shot {n}: exists, skipping")
            continue
        todo.append(shot)
    # Scene starters first, then the shots that continue a scene, and among those the ones that
    # copy someone's clothes from another shot of the scene after the shot they copy from.
    level: dict[int, int] = {}

    def level_of(n: int) -> int:
        if n not in level:
            level[n] = 0 if n not in anchor_of else 1 + max([level_of(w["n"]) for _, w in clothes_of.get(n, [])] or [0])
        return level[n]

    for lv in sorted({level_of(s["n"]) for s in todo}):
        runner = TaskRunner(_workers(config))
        for shot in todo:
            if level_of(shot["n"]) == lv:
                runner.submit(make, shot)
        runner.join()
    redrawn = {s["n"] for s in todo}
    for start in sorted({a["n"] for n, a in anchor_of.items()} & redrawn):
        rest = sorted(n for n, a in anchor_of.items() if a["n"] == start and n not in redrawn
                      and shot_path(run_dir, n).exists())
        if rest:
            print(f"  shot {start} starts a scene that shot(s) {', '.join(map(str, rest))} continue; if its "
                  f"place or clothes changed, redo them too: images --only {','.join(map(str, rest))}")
    generated = len(done)
    cost = generated * image_cost(config)
    print(f"[images] generated {generated} keyframe(s), est. ${cost:.2f} -> {shots_dir(run_dir)}")


def run(run_dir: Path, config: dict, only: str | None = None) -> None:
    """Full step. `only` is a comma-separated shot list; those shots are regenerated even if present."""
    only_set = parse_only(only)
    _run(run_dir, config, only_set, force=only_set is not None)


def reroll_shot(run_dir: Path, config: dict, shot_number: int) -> None:
    _run(run_dir, config, {shot_number}, force=True)
