"""Voice step: one ElevenLabs text-to-speech call per spoken shot, with per-word timings."""

from __future__ import annotations

import base64
import os
from pathlib import Path

import requests

from common import StepError, parse_only, read_script, select_shots, write_json

API_BASE = "https://api.elevenlabs.io"


def audio_dir(run_dir: Path) -> Path:
    return run_dir / "audio"


def audio_path(run_dir: Path, n: int) -> Path:
    return audio_dir(run_dir) / f"{n}.mp3"


def timing_path(run_dir: Path, n: int) -> Path:
    return audio_dir(run_dir) / f"{n}.json"


def voice_for(speaker: str, config: dict) -> str:
    voice = (config.get("voices") or {}).get(speaker, "")
    return voice or config["voice_id"]


def require_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise StepError("ELEVENLABS_API_KEY is not set; put it in .env (see .env.example)")
    return key


def tts_with_timestamps(text: str, voice_id: str, config: dict, label: str) -> dict:
    """POST /v1/text-to-speech/{voice_id}/with-timestamps. Returns the parsed JSON body."""
    el = config["elevenlabs"]
    url = f"{API_BASE}/v1/text-to-speech/{voice_id}/with-timestamps"
    try:
        r = requests.post(
            url,
            params={"output_format": el["output_format"]},
            headers={"xi-api-key": require_key(), "Content-Type": "application/json"},
            json={"text": text, "model_id": el["model_id"]},
            timeout=180,
        )
    except requests.RequestException as e:
        raise StepError(f"{label}: could not reach ElevenLabs: {e}") from e
    if r.status_code != 200:
        raise StepError(f"{label}: ElevenLabs returned HTTP {r.status_code}: {r.text[:400]}")
    try:
        data = r.json()
    except ValueError:
        raise StepError(f"{label}: ElevenLabs returned non-JSON: {r.text[:200]}") from None
    if not data.get("audio_base64"):
        raise StepError(f"{label}: ElevenLabs response had no audio: {str(data)[:300]}")
    return data


def words_from_alignment(alignment: dict | None) -> list[dict]:
    """Group character-level timings into words (split on whitespace)."""
    if not alignment:
        return []
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    words: list[dict] = []
    buf: list[str] = []
    w_start = 0.0
    w_end = 0.0
    for ch, st, en in zip(chars, starts, ends):
        if ch.isspace():
            if buf:
                words.append({"word": "".join(buf), "start": round(w_start, 3), "end": round(w_end, 3)})
                buf = []
            continue
        if not buf:
            w_start = float(st)
        buf.append(ch)
        w_end = float(en)
    if buf:
        words.append({"word": "".join(buf), "start": round(w_start, 3), "end": round(w_end, 3)})
    return words


def generate_voice(run_dir: Path, config: dict, shot: dict) -> Path:
    n = shot["n"]
    text = shot["vo_line"].strip()
    speaker = shot.get("speaker") or "narrator"
    import voice_cast
    voice_id = voice_cast.voice_for(run_dir, speaker, config)
    label = f"shot {n}"
    data = tts_with_timestamps(text, voice_id, config, label)

    audio_dir(run_dir).mkdir(parents=True, exist_ok=True)
    mp3 = audio_path(run_dir, n)
    mp3.write_bytes(base64.b64decode(data["audio_base64"]))

    words = words_from_alignment(data.get("alignment")) or words_from_alignment(data.get("normalized_alignment"))
    duration = max((w["end"] for w in words), default=0.0)
    write_json(timing_path(run_dir, n), {
        "shot": n,
        "speaker": speaker,
        "voice_id": voice_id,
        "text": text,
        "characters": len(text),
        "duration": round(duration, 3),
        "words": words,
    })
    return mp3


def _run(run_dir: Path, config: dict, only: set[int] | None, force: bool) -> None:
    require_key()
    script = read_script(run_dir)
    rate = float(config["elevenlabs"]["cost_per_1k_chars"])
    shots = select_shots(script, only)
    spoken = [s for s in shots if s["vo_line"].strip()]
    silent = [s["n"] for s in shots if not s["vo_line"].strip()]
    if silent:
        print(f"[voice] silent shot(s) {silent}, nothing to synthesize")
    print(f"[voice] {len(spoken)} spoken shot(s), model {config['elevenlabs']['model_id']}, "
          f"${rate:.2f}/1k chars")
    import voice_cast
    voice_cast.ensure_cast(run_dir, config, script)     # a fitting voice for anyone without one

    import progress
    progress.plan(sum(1 for s in spoken if force or not (audio_path(run_dir, s["n"]).exists()
                                                        and timing_path(run_dir, s["n"]).exists())), "lines")
    generated = 0
    chars = 0
    for shot in spoken:
        n = shot["n"]
        if audio_path(run_dir, n).exists() and timing_path(run_dir, n).exists() and not force:
            print(f"  shot {n}: exists, skipping")
            continue
        speaker = shot.get("speaker") or "narrator"
        print(f"  shot {n}: {speaker} ({voice_cast.voice_for(run_dir, speaker, config)}) \"{shot['vo_line'].strip()}\"")
        generate_voice(run_dir, config, shot)
        progress.tick()
        clip = run_dir / "shots" / f"{n}.mp4"
        if shot.get("talk") and clip.exists():
            clip.unlink()      # its lips followed the old line
            print(f"  shot {n}: removed its talking clip (made for the old line); rerun video --only {n}")
        generated += 1
        chars += len(shot["vo_line"].strip())
    print(f"[voice] generated {generated} clip(s), {chars} chars, est. ${chars / 1000 * rate:.2f} "
          f"-> {audio_dir(run_dir)}")


def run(run_dir: Path, config: dict, only: str | None = None) -> None:
    """Full step. `only` is a comma-separated shot list; those shots are regenerated even if present.
    A song format (rules.song) sings the whole script as one song instead (steps/song.py)."""
    from steps import song
    if song.is_song(config):
        song.run(run_dir, config, only)
        return
    only_set = parse_only(only)
    _run(run_dir, config, only_set, force=only_set is not None)
