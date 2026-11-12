"""Clip sound: the video model makes each clip with its own sound.

Without it a clip is silent: the picture moves, an ElevenLabs voice is laid on top afterwards,
and the mouth was animated without ever hearing the line. With it the model is asked for the
clip and its sound together, so a character says the line with lips that match, and a door
slams when it shuts.

    clip_sound:
      enabled: false     # true = clips are made with sound and the video uses it
      level: 0.8         # how loud a shot's own sound plays when nobody speaks in it
      match: 0.7         # how much of the line must be heard in the clip (0-1); below this the
                         # shot falls back to the ElevenLabs voice
      model: scribe_v2   # the ElevenLabs model that finds the words in a clip

One video can also decide for itself: "clip_sound": true or false in its run.json (the switch on
the run page). What happens with it on:

  video     every clip is requested with sound; the prompt says who speaks and in what kind of
            voice, asks for the sound of the scene and no music
  voice     for a spoken shot, the words in the clip are found (ElevenLabs Speech to Text, word
            by word). If they are the line, the stretch of the clip where it is said becomes the
            shot's voice file and the captions follow those words. If the clip says something
            else, or nothing, the line is spoken by the ElevenLabs voice as before
  assemble  a shot that speaks from its clip shows the same stretch of the clip, so sound and
            picture stay together; a shot where nobody speaks plays its clip's own sound

The voices are the model's own, not the ElevenLabs ones picked in the Voices panel; a
character's `voice_style` (format.yaml) is sent with every line to keep them alike.
"""

from __future__ import annotations

import difflib
import os
import re
from pathlib import Path

from common import StepError, read_json

API_BASE = "https://api.elevenlabs.io"
LEAD = 0.12            # seconds kept before the first word
TAIL = 0.28            # and after the last
MIN_WINDOW = 0.7       # a spoken stretch is never cut shorter than this
FADE = 0.05            # the cut ends of a stretch are faded this long, so they do not click


# ------------------------------------------------------------------ settings ----

def settings(config: dict) -> dict:
    """The checked clip_sound settings: {"enabled", "level", "match", "model"}."""
    raw = config.get("clip_sound")
    if isinstance(raw, bool):
        raw = {"enabled": raw}
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise StepError("config: clip_sound must be true, false, or a block with enabled / level / match / model")
    unknown = sorted(set(raw) - {"enabled", "level", "match", "model"})
    if unknown:
        raise StepError(f"config: clip_sound has unknown keys {unknown}; use enabled, level, match, model")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise StepError("config: clip_sound.enabled must be true or false")
    out = {"enabled": enabled, "model": str(raw.get("model") or "scribe_v2").strip()}
    for key, default, low, high in (("level", 0.8, 0.0, 2.0), ("match", 0.7, 0.0, 1.0)):
        try:
            value = float(raw.get(key, default))
        except (TypeError, ValueError):
            raise StepError(f"config: clip_sound.{key} must be a number") from None
        if not low <= value <= high:
            raise StepError(f"config: clip_sound.{key} must be between {low:g} and {high:g}")
        out[key] = value
    return out


def run_choice(run_dir: Path | None) -> bool | None:
    """What this video's run.json says: True, False, or None when it does not say."""
    if run_dir is None:
        return None
    try:
        value = read_json(Path(run_dir) / "run.json").get("clip_sound")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, bool) else None


def on(config: dict, run_dir: Path | None = None) -> bool:
    """Is clip sound on for this video? The run's own choice wins over the config."""
    mine = run_choice(run_dir)
    return settings(config)["enabled"] if mine is None else mine


def set_for_run(run_dir: Path, value: bool | None) -> bool | None:
    """Save this video's choice in run.json. None takes the config's setting again."""
    from common import write_json
    path = Path(run_dir) / "run.json"
    meta = read_json(path)
    if value is None:
        meta.pop("clip_sound", None)
    else:
        meta["clip_sound"] = bool(value)
    write_json(path, meta)
    return run_choice(run_dir)


# ------------------------------------------------------- what the model is told ----

SILENT_NOTE = "Nobody speaks. Only the natural sound of the scene, no music."
SPOKEN_NOTE = "Only that one line is spoken, once, in clear English. The natural sound of the scene under it, no music."


def voice_hint(speaker: str, characters: list[dict] | None) -> str:
    """How the speaker sounds, for the video model: the character's `voice_style` when the
    format gives one, else a plain guess from the description ("a young man's voice")."""
    who = next((c for c in characters or [] if isinstance(c, dict) and c.get("id") == speaker), None)
    if who is None:
        return ""
    style = " ".join(str(who.get("voice_style") or "").split())
    if style:
        return style
    import voice_cast
    t = voice_cast.traits(str(who.get("description") or ""))
    age = {"young": "young ", "middle_aged": "middle-aged ", "old": "older "}.get(t["age"], "")
    person = {"male": "man", "female": "woman"}.get(t["gender"], "")
    return f"a {age}{person}'s voice" if person else ""


def sound_note(shot: dict, characters: list[dict] | None) -> str:
    """The sentences added to a clip's prompt when it is made with sound."""
    line = " ".join(str(shot.get("vo_line") or "").split())
    speaker = shot.get("speaker") or ""
    if not line or speaker not in (shot.get("characters") or []):
        return SILENT_NOTE
    hint = voice_hint(speaker, characters)
    return (f"The voice is {hint}, the same voice every time this character speaks. " if hint else "") + SPOKEN_NOTE


# ------------------------------------------------------------ hearing the clip ----

def _norm(word: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", str(word or "").lower().replace("’", "'"))


def line_words(line: str) -> list[str]:
    return [w for w in str(line or "").split() if _norm(w)]


def transcribe(clip: Path, config: dict, label: str) -> list[dict]:
    """The words spoken in a clip: [{"word", "start", "end"}] in seconds from the clip's start.
    One ElevenLabs Speech to Text call (billed by the length of the audio: a few seconds)."""
    import requests
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise StepError("ELEVENLABS_API_KEY is not set (finding the words in a clip uses ElevenLabs Speech to Text)")
    cfg = settings(config)
    try:
        with open(clip, "rb") as f:
            r = requests.post(f"{API_BASE}/v1/speech-to-text", headers={"xi-api-key": key},
                              data={"model_id": cfg["model"], "language_code": "en", "tag_audio_events": "false",
                                    "diarize": "false", "timestamps_granularity": "word"},
                              files={"file": (clip.name, f, "video/mp4")}, timeout=180)
    except requests.RequestException as e:
        raise StepError(f"{label}: could not reach ElevenLabs Speech to Text: {e}") from e
    if r.status_code != 200:
        raise StepError(f"{label}: ElevenLabs Speech to Text returned HTTP {r.status_code}: {r.text[:300]}")
    try:
        raw = r.json().get("words") or []
    except (ValueError, AttributeError):
        raise StepError(f"{label}: ElevenLabs Speech to Text returned something unreadable") from None
    words = []
    for w in raw:
        if not isinstance(w, dict) or w.get("type") not in (None, "word"):
            continue
        text = str(w.get("text") or "").strip()
        try:
            start, end = float(w.get("start")), float(w.get("end"))
        except (TypeError, ValueError):
            continue
        if _norm(text) and end >= start >= 0:
            words.append({"word": text, "start": round(start, 3), "end": round(end, 3)})
    return words


def match(line: str, heard: list[dict]) -> float:
    """How much of the line is in what was heard, 0 to 1 (1 = every word, in order)."""
    want = [_norm(w) for w in line_words(line)]
    got = [_norm(w["word"]) for w in heard]
    if not want or not got:
        return 0.0
    same = sum(b.size for b in difflib.SequenceMatcher(None, want, got, autojunk=False).get_matching_blocks())
    extra = max(0, len(got) - len(want))                    # words said that are not in the line
    return round(max(0.0, same / len(want) - 0.5 * extra / len(want)), 3)


def align(line: str, heard: list[dict]) -> list[dict]:
    """The line's own words (its spelling and punctuation, for the captions) with the times at
    which they were heard. Where the clip said a word differently, or swallowed one, the time of
    that stretch is shared out between the line's words there."""
    want = line_words(line)
    if not want or not heard:
        return []
    a, b = [_norm(w) for w in want], [_norm(w["word"]) for w in heard]
    out: list[dict | None] = [None] * len(want)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out[i1 + k] = {"word": want[i1 + k], "start": heard[j1 + k]["start"], "end": heard[j1 + k]["end"]}
        elif i2 > i1:
            if j2 > j1:
                t0, t1 = heard[j1]["start"], heard[j2 - 1]["end"]
            else:                                          # nothing heard here: a point between its neighbours
                t0 = t1 = heard[j1 - 1]["end"] if j1 > 0 else heard[0]["start"]
            step = (t1 - t0) / (i2 - i1)
            for k in range(i2 - i1):
                out[i1 + k] = {"word": want[i1 + k], "start": round(t0 + k * step, 3), "end": round(t0 + (k + 1) * step, 3)}
    return [w for w in out if w]


def window(words: list[dict], clip_seconds: float) -> tuple[float, float]:
    """(start, length) of the stretch of the clip that holds the words, with a little room."""
    start = max(0.0, min(w["start"] for w in words) - LEAD)
    end = min(clip_seconds, max(w["end"] for w in words) + TAIL)
    if end - start < MIN_WINDOW:
        end = min(clip_seconds, start + MIN_WINDOW)
        start = max(0.0, end - MIN_WINDOW)
    return round(start, 3), round(end - start, 3)


def cut_voice(clip: Path, start: float, length: float, dest: Path, label: str) -> None:
    """The clip's sound from `start` for `length` seconds, as the shot's voice file."""
    from media import run_ffmpeg
    dest.parent.mkdir(parents=True, exist_ok=True)
    fade_at = max(0.0, length - FADE)
    run_ffmpeg(["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(clip), "-vn",
                "-af", f"aresample=44100,afade=t=in:d={FADE},afade=t=out:st={fade_at:.3f}:d={FADE}",
                "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", str(dest)], f"{label} (its own sound)")


def timing_source(timing_file: Path) -> dict:
    """{"source": "clip", "clip_offset": seconds} for a shot that speaks from its clip, else {}."""
    try:
        data = read_json(timing_file)
    except (OSError, ValueError):
        return {}
    if isinstance(data, dict) and data.get("source") == "clip":
        try:
            return {"source": "clip", "clip_offset": max(0.0, float(data.get("clip_offset") or 0.0))}
        except (TypeError, ValueError):
            return {}
    return {}
