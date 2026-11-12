"""Video step: image-to-video on each animated shot's keyframe (Seedance 2.0 Fast on fal or Sume),
and a lip-synced clip for each talking shot (a talking-avatar model on fal: the keyframe + the
shot's voice line, so the voice step's audio for that shot is made first if it is missing)."""

from __future__ import annotations

import threading
from pathlib import Path

import fal_api
import sume_api
from common import StepError, parse_only, read_script, select_shots, write_json
import downloads
import progress
from parallel import TaskRunner
from steps.images import shot_path

ASPECT = "9:16"
RESOLUTIONS = ("480p", "720p")   # what Seedance 2.0 Fast accepts on both providers


def video_provider(config: dict) -> str:
    return config["providers"]["video"]


def _block(config: dict) -> dict:
    """The settings block of the active video provider."""
    return config[video_provider(config)]


def video_resolution(config: dict) -> str:
    res = str(_block(config)["video_resolution"])
    if res not in RESOLUTIONS:
        raise StepError(f"config.yaml: {video_provider(config)}.video_resolution must be one of "
                        f"{', '.join(RESOLUTIONS)}, got '{res}'")
    return res


# Said to the video model after every motion prompt. A clip is one shot: the cuts are made when
# the video is put together. Without this, a motion that does not match the picture (two people
# drawn facing the camera, told to "walk off down the corridor") came back as a turn-around, a
# cut to their backs and a different corridor.
ONE_TAKE = ("One continuous take that starts on this exact picture: no cut, no jump to another angle "
            "or place, and nobody turns to face the other way unless the action says so.")


def _motion(config: dict, shot: dict, descriptions: dict[str, str] | None, sound: bool = False) -> str:
    # mouths_move (config, on by default): spoken shots tell the video model who is talking.
    # `sound`: the clip is made with its own sound (clip_sound.py), so the model is also told
    # what should be heard: the line in the speaker's kind of voice, or nobody speaking.
    if config.get("mouths_move", True) is False and not sound:
        return f"{shot['motion_prompt'].strip()} {ONE_TAKE}"
    text = clip_prompt(shot, descriptions)
    if sound:
        import clip_sound
        text = f"{text} {clip_sound.sound_note(shot, config.get('locked_characters'))}"
    return f"{text} {ONE_TAKE}"


def _workers(config: dict) -> int:
    # fal runs one request at a time, as it always has; Sume runs up to its concurrency cap.
    return int(config["sume"]["max_concurrent"]) if video_provider(config) == "sume" else 1


def video_path(run_dir: Path, n: int) -> Path:
    return shot_path(run_dir, n).with_suffix(".mp4")


def talk_seconds(run_dir: Path, n: int) -> float:
    """Length of a talking shot's voice line (from the voice step's timing file), or 0."""
    from common import read_json
    from steps.voice import timing_path
    tp = timing_path(run_dir, n)
    if not tp.exists():
        return 0.0
    try:
        return float(read_json(tp).get("duration") or 0.0)
    except (OSError, ValueError):
        return 0.0


def generate_talk_clip(run_dir: Path, config: dict, shot: dict) -> Path:
    """The keyframe speaking this shot's voice line, lip-synced (fal talking-avatar model)."""
    from steps.voice import audio_path, generate_voice, require_key as voice_key
    n = shot["n"]
    keyframe = shot_path(run_dir, n)
    if not keyframe.exists():
        raise StepError(f"shot {n}: keyframe {keyframe} is missing; run the images step first")
    audio = audio_path(run_dir, n)
    if not audio.exists():
        voice_key()
        print(f"  shot {n}: making its voice line first (the talking clip is lip-synced to it)")
        generate_voice(run_dir, config, shot)
    fal = config["fal"]
    label = f"shot {n} (talking)"
    dest = video_path(run_dir, n)
    if downloads.resume(dest, fal_api.download, label):
        return dest
    prompt = (shot.get("motion_prompt") or "").strip() or "the person talks naturally to the camera"
    result = fal_api.call(fal["avatar_model"], {
        "image_url": fal_api.upload(keyframe),
        "audio_url": fal_api.upload(audio),
        "prompt": prompt,
    }, label=label)
    downloads.save(fal_api.video_url(result, label), dest, fal_api.download)
    return dest


def clip_prompt(shot: dict, descriptions: dict[str, str] | None = None) -> str:
    """The motion prompt sent to the video model. When someone in the shot speaks a line, the
    prompt also says so, so their mouth moves while the line is heard (the voice itself is
    added at assembly; this is not exact lip-sync)."""
    prompt = shot["motion_prompt"].strip()
    line = " ".join(str(shot.get("vo_line") or "").split())
    speaker = shot.get("speaker") or ""
    on_screen = shot.get("characters") or []
    if not line or not speaker or speaker not in on_screen:
        return prompt
    if len(on_screen) == 1:
        who = "The character"
    else:
        # Name the speaker by how they look: the first clause of their description
        # ("a 28 year old man with slick blond hair and a smug grin").
        parts = [x.strip() for x in str((descriptions or {}).get(speaker) or "").split(",") if x.strip()]
        first = parts[0] if parts else ""
        if first and len(first.split()) < 3 and len(parts) > 1:
            first = f"{first}, {parts[1]},"                     # "Iro, a small round robotic penguin ...,"
        words = first.split()[:18]
        if words and words[0].lower() in ("a", "an"):
            words[0] = "The"
        who = " ".join(words) or "The speaker"
    quoted = line.replace('"', "'")
    return (f'{prompt} {who} is talking throughout, mouth moving clearly with every word, saying: '
            f'"{quoted}" No subtitles or text on screen.')


def generate_clip(run_dir: Path, config: dict, shot: dict,
                  descriptions: dict[str, str] | None = None) -> Path:
    n = shot["n"]
    fal = config["fal"]
    keyframe = shot_path(run_dir, n)
    if not keyframe.exists():
        raise StepError(f"shot {n}: keyframe {keyframe} is missing; run the images step first")
    dest = video_path(run_dir, n)
    label = f"shot {n}"
    import clip_sound
    sound = clip_sound.on(config, run_dir)          # the clip comes with its own sound
    if video_provider(config) == "sume":
        video_resolution(config)
        if downloads.resume(dest, sume_api.download, label):
            return dest
        with_sound = {**config, "sume": {**config["sume"], "video_audio": True}} if sound else config
        url = sume_api.generate_video(with_sound, _motion(config, shot, descriptions, sound), keyframe, label)
        downloads.save(url, dest, sume_api.download)
        return dest
    if downloads.resume(dest, fal_api.download, label):
        return dest
    result = fal_api.call(fal["video_model"], {
        "prompt": _motion(config, shot, descriptions, sound),
        "image_url": fal_api.upload(keyframe),
        "duration": int(fal["video_seconds"]),
        "resolution": video_resolution(config),
        "aspect_ratio": ASPECT,
        "generate_audio": bool(fal["video_audio"]) or sound,
    }, label=label)
    downloads.save(fal_api.video_url(result, label), dest, fal_api.download)
    return dest


def _run(run_dir: Path, config: dict, only: set[int] | None, force: bool) -> None:
    script = read_script(run_dir)
    from steps.script import apply_animate_all
    more = apply_animate_all(script, config)
    if more:
        write_json(run_dir / "script.json", script)
        print(f"[video] every shot is a video clip in this format: {more} more shot(s) marked to animate")
    selected = select_shots(script, only)
    descriptions = {c["id"]: c.get("description", "") for c in script.get("characters", []) if isinstance(c, dict)}
    animated = [s for s in selected if s.get("animate") and not s.get("talk")]
    talking = [s for s in selected if s.get("talk")]
    if animated:
        if video_provider(config) == "sume":
            sume_api.require_key()
        else:
            fal_api.require_key()
    if talking:
        fal_api.require_key()                # talking clips are made on fal whatever the provider
        import voice_cast
        voice_cast.ensure_cast(run_dir, config, script)   # before any talking shot's voice line
    resolution = video_resolution(config)   # fail before any spend on a bad value
    block = _block(config)
    seconds = int(block["video_seconds"])
    rate = float(block["video_cost_per_second"])
    talk_rate = float(config["fal"]["avatar_cost_per_second"])

    skipped_static = [s["n"] for s in selected if not s.get("animate") and not s.get("talk")]
    if only is not None and skipped_static:
        print(f"[video] shot(s) {skipped_static} are animate: false, nothing to render")
    via = "" if video_provider(config) == "fal" else \
        f" via Sume ({block['video_model']}, up to {_workers(config)} at once)"
    import clip_sound
    sound = clip_sound.on(config, run_dir)
    print(f"[video] {len(animated)} animated shot(s), {seconds}s each at {resolution}, "
          f"${rate:.4f}/s{via}" + (", each with its own sound" if sound else ""))
    if talking:
        print(f"[video] {len(talking)} talking shot(s), lip-synced on fal ({config['fal']['avatar_model']}), "
              f"${talk_rate:.4f}/s of speech")

    totals = {"cost": 0.0, "count": 0}
    lock = threading.Lock()
    progress.plan(sum(1 for s in [*animated, *talking]
                      if force or not video_path(run_dir, s["n"]).exists()), "clips")

    def make(shot: dict) -> None:
        n = shot["n"]
        print(f"  shot {n}: generating...")
        generate_clip(run_dir, config, shot, descriptions)
        if sound and str(shot.get("vo_line") or "").strip() and not shot.get("app_screen"):
            # The new clip says the line itself, so whatever voice file the shot had (cut from
            # the old clip, or spoken by ElevenLabs before clip sound was on) is out of date.
            from steps.voice import audio_path, timing_path
            if audio_path(run_dir, n).exists() or timing_path(run_dir, n).exists():
                audio_path(run_dir, n).unlink(missing_ok=True)
                timing_path(run_dir, n).unlink(missing_ok=True)
                print(f"  shot {n}: new clip, so its line will be read again: run the voice step for it")
        progress.tick()
        cost = seconds * rate
        with lock:
            totals["cost"] += cost
            totals["count"] += 1
            print(f"  shot {n}: {seconds}s  est. ${cost:.2f}  (running total ${totals['cost']:.2f})")

    def make_talk(shot: dict) -> None:
        n = shot["n"]
        print(f"  shot {n}: generating talking clip ({shot['speaker']})...")
        generate_talk_clip(run_dir, config, shot)
        progress.tick()
        secs = talk_seconds(run_dir, n)
        cost = secs * talk_rate
        with lock:
            totals["cost"] += cost
            totals["count"] += 1
            print(f"  shot {n}: {secs:.1f}s talking  est. ${cost:.2f}  (running total ${totals['cost']:.2f})")

    runner = TaskRunner(_workers(config))
    for shot in animated:
        n = shot["n"]
        dest = video_path(run_dir, n)
        if dest.exists() and not force:
            print(f"  shot {n}: exists, skipping")
            continue
        runner.submit(make, shot)
    runner.join()
    for shot in talking:                     # one at a time on fal
        n = shot["n"]
        if video_path(run_dir, n).exists() and not force:
            print(f"  shot {n}: talking clip exists, skipping")
            continue
        make_talk(shot)
    print(f"[video] generated {totals['count']} clip(s), est. total ${totals['cost']:.2f}")


def run(run_dir: Path, config: dict, only: str | None = None) -> None:
    """Full step. `only` is a comma-separated shot list; those shots are regenerated even if present."""
    only_set = parse_only(only)
    _run(run_dir, config, only_set, force=only_set is not None)


def reroll_shot(run_dir: Path, config: dict, shot_number: int) -> None:
    script = read_script(run_dir)
    shot = next((s for s in script["shots"] if s["n"] == shot_number), None)
    if shot is None:
        raise StepError(f"shot {shot_number} not in script.json")
    if not shot.get("animate") and not shot.get("talk"):
        print(f"[video] shot {shot_number} is animate: false, no clip to reroll")
        return
    _run(run_dir, config, {shot_number}, force=True)
