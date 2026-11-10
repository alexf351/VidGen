"""Song mode (formats with rules.song): the voice step sings instead of speaking.

The script's lyric lines (one per shot, in vo_line) and its "song": {"style": ...} become ONE song
from the ElevenLabs Music API. Then ElevenLabs forced alignment finds when each word is sung, and
every shot is timed to its line: a shot starts when its line starts and ends when the next one
does. Files, next to the usual voice files:

    audio/song.mp3    the whole song (the soundtrack; no music bed is added on top)
    audio/song.json   model, length, style, and each shot's start/end in the song
    audio/<n>.json    the shot's sung words, timed from the shot's start (captions read these)
"""

from __future__ import annotations

import re
from pathlib import Path

import requests

from common import StepError, read_json, read_script, write_json
from steps.voice import API_BASE, audio_dir, require_key, timing_path

LINES_PER_CHUNK = 4
INTRO_MS = 1500
OUTRO_MS = 2500
TAIL_SECONDS = 1.6          # the last shot holds this long after the last sung word


def song_path(run_dir: Path) -> Path:
    return audio_dir(run_dir) / "song.mp3"


def song_info_path(run_dir: Path) -> Path:
    return audio_dir(run_dir) / "song.json"


def is_song(config: dict) -> bool:
    return bool((config.get("format") or {}).get("rules", {}).get("song"))


def sung_shots(script: dict) -> list[dict]:
    return [s for s in script["shots"] if str(s.get("vo_line") or "").strip()]


def _line_ms(line: str) -> int:
    words = len(line.split())
    return int(max(1.8, words * 0.42 + 0.5) * 1000)


def _styles(style: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[,;]", style) if p.strip()]
    return parts[:10] or ["catchy pop song"]


def composition_plan(script: dict, model: str) -> dict:
    """The lyric lines grouped into sections (4 lines each), with durations that leave room for
    each line to be sung plus a short intro and outro."""
    lines = [s["vo_line"].strip() for s in sung_shots(script)]
    if not lines:
        raise StepError("this song has no lyric lines (every shot's vo_line is empty)")
    style = _styles(str((script.get("song") or {}).get("style") or ""))
    chunks = [lines[i:i + LINES_PER_CHUNK] for i in range(0, len(lines), LINES_PER_CHUNK)]
    sections = []
    for i, chunk in enumerate(chunks):
        name = "Chorus" if i == len(chunks) - 1 and len(chunks) > 1 else f"Verse {i + 1}"
        ms = sum(_line_ms(line) for line in chunk)
        if i == 0:
            ms += INTRO_MS
        if i == len(chunks) - 1:
            ms += OUTRO_MS
        sections.append({"name": name, "lines": chunk, "duration_ms": max(3000, min(120000, ms))})
    if model == "music_v1":
        return {"positive_global_styles": style, "negative_global_styles": ["spoken word"],
                "sections": [{"section_name": s["name"], "positive_local_styles": [],
                              "negative_local_styles": [], "duration_ms": s["duration_ms"],
                              "lines": s["lines"]} for s in sections]}
    return {"chunks": [{"text": f"[{s['name']}]\n" + "\n".join(s["lines"]),
                        "duration_ms": s["duration_ms"], "positive_styles": style,
                        "negative_styles": ["spoken word"]} for s in sections]}


def compose(plan: dict, config: dict, label: str = "song") -> bytes:
    el = config["elevenlabs"]
    try:
        r = requests.post(f"{API_BASE}/v1/music", params={"output_format": el["music_output_format"]},
                          headers={"xi-api-key": require_key(), "Content-Type": "application/json"},
                          json={"model_id": el["music_model"], "composition_plan": plan}, timeout=600)
    except requests.RequestException as e:
        raise StepError(f"{label}: could not reach ElevenLabs: {e}") from e
    if r.status_code != 200:
        hint = (" (music needs a paid ElevenLabs plan)" if r.status_code in (401, 402, 403) else "")
        raise StepError(f"{label}: ElevenLabs Music returned HTTP {r.status_code}{hint}: {r.text[:400]}")
    if not r.content or r.headers.get("content-type", "").startswith("application/json"):
        raise StepError(f"{label}: ElevenLabs Music returned no audio: {r.text[:300]}")
    return r.content


def align(audio: Path, text: str, label: str = "lyrics") -> dict:
    """ElevenLabs forced alignment: when each word of `text` is heard in `audio`."""
    try:
        with open(audio, "rb") as f:
            r = requests.post(f"{API_BASE}/v1/forced-alignment", headers={"xi-api-key": require_key()},
                              files={"file": (audio.name, f, "audio/mpeg")}, data={"text": text}, timeout=600)
    except requests.RequestException as e:
        raise StepError(f"{label}: could not reach ElevenLabs: {e}") from e
    if r.status_code != 200:
        raise StepError(f"{label}: ElevenLabs forced alignment returned HTTP {r.status_code}: {r.text[:400]}")
    try:
        return r.json()
    except ValueError:
        raise StepError(f"{label}: forced alignment returned non-JSON: {r.text[:200]}") from None


def _norm(token: str) -> str:
    return re.sub(r"[^\w']", "", token.lower())


def shot_timings(script: dict, words: list[dict], song_seconds: float) -> list[dict]:
    """Give each sung shot its words (in order) and its span in the song. Shot 1 starts at 0
    (it covers the intro); each later shot starts on its first word; the last one ends a moment
    after the last word, or when the song ends."""
    aligned = [w for w in words if _norm(str(w.get("text", "")))]
    shots = sung_shots(script)
    out, k = [], 0
    for s in shots:
        need = len([t for t in s["vo_line"].split() if _norm(t)])
        mine = aligned[k:k + need]
        k += need
        out.append({"n": s["n"], "line": s["vo_line"].strip(),
                    "words": [{"word": str(w["text"]), "start": float(w["start"]),
                               "end": float(w["end"])} for w in mine]})
    if k < len(aligned) - 2 or k > len(aligned):
        print(f"  note: the lyrics have {k} words and the alignment found {len(aligned)}; timings may drift")
    # Shots whose words were not found share the gap evenly.
    for i, t in enumerate(out):
        if not t["words"]:
            prev_end = out[i - 1]["words"][-1]["end"] if i and out[i - 1]["words"] else 0.0
            t["words"] = [{"word": w, "start": prev_end, "end": prev_end} for w in t["line"].split()]
    for i, t in enumerate(out):
        t["start"] = 0.0 if i == 0 else t["words"][0]["start"]
    for i, t in enumerate(out):
        if i + 1 < len(out):
            t["end"] = out[i + 1]["start"]
        else:
            t["end"] = min(song_seconds, t["words"][-1]["end"] + TAIL_SECONDS) if song_seconds else \
                t["words"][-1]["end"] + TAIL_SECONDS
        if t["end"] - t["start"] < 0.4:
            t["end"] = t["start"] + 0.4
    return out


def run(run_dir: Path, config: dict, only: str | None = None) -> None:
    from media import probe_duration
    require_key()
    script = read_script(run_dir)
    if only:
        print("[voice] a song is one piece of audio, so the whole song is made again")
    el = config["elevenlabs"]
    model = el["music_model"]
    plan = composition_plan(script, model)
    seconds_planned = sum(c["duration_ms"] for c in plan.get("chunks", plan.get("sections", []))) / 1000
    rate = float(el["music_cost_per_minute"])
    style = (script.get("song") or {}).get("style", "")
    print(f"[voice] song mode: {len(sung_shots(script))} lyric lines, ~{seconds_planned:.0f}s, "
          f"model {model}, style \"{style}\"")
    print(f"  composing (est. ${seconds_planned / 60 * rate:.2f})...")
    audio_dir(run_dir).mkdir(parents=True, exist_ok=True)
    song = song_path(run_dir)
    tmp = song.with_suffix(".part.mp3")
    tmp.write_bytes(compose(plan, config))
    tmp.replace(song)
    seconds = probe_duration(song)
    print(f"  song: {seconds:.1f}s -> {song}")

    lyrics = "\n".join(s["vo_line"].strip() for s in sung_shots(script))
    print("  aligning the lyrics to the song...")
    data = align(song, lyrics)
    timings = shot_timings(script, data.get("words") or [], seconds)
    for t in timings:
        rel = [{"word": w["word"], "start": round(max(0.0, w["start"] - t["start"]), 3),
                "end": round(max(0.0, w["end"] - t["start"]), 3)} for w in t["words"]]
        write_json(timing_path(run_dir, t["n"]), {
            "shot": t["n"], "speaker": "song", "text": t["line"], "characters": 0, "song": True,
            "start": round(t["start"], 3), "end": round(t["end"], 3),
            "duration": round(t["end"] - t["start"], 3), "words": rel})
        print(f"  shot {t['n']}: {t['start']:6.2f}s - {t['end']:6.2f}s  \"{t['line']}\"")
    write_json(song_info_path(run_dir), {
        "model": model, "style": style, "seconds": round(seconds, 3),
        "alignment_loss": data.get("loss"),
        "shots": [{"n": t["n"], "start": round(t["start"], 3), "end": round(t["end"], 3)} for t in timings]})
    print(f"[voice] song ready, est. ${seconds / 60 * rate:.2f}")


def song_plan(run_dir: Path) -> dict | None:
    p = song_info_path(run_dir)
    if not p.exists() or not song_path(run_dir).exists():
        return None
    try:
        return read_json(p)
    except (OSError, ValueError):
        return None
