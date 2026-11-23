"""The sound of a choice story: the narrator, a low drone under everything, and a sound for each
thing that happens (a knock, a door, a heartbeat).

The narrator is read by ElevenLabs in one request, with the time of every word, so the pictures
and the words on screen follow the voice. Everything else is made here from sine waves and noise:
no sound model is called and no file is downloaded. Without an ElevenLabs key an episode still
gets its drone and its event sounds, and the words on screen keep an even pace.

    narrate(ep, config, voice_id)   -> (mp3 bytes, {"words": [...], "duration": seconds})
    cues(ep, timing)                -> [(seconds, sound, loudness), ...]
    mix(out, total, voice, cues)    -> a wav: voice + drone + sounds
"""

from __future__ import annotations

import array
import math
import subprocess
import wave
from pathlib import Path

from common import ROOT, StepError

import stickstory

RATE = 22050
VERSION = 3                          # bump when a synthesized sound changes
CACHE = ROOT / "cache" / "story_sound"
MAX_CUES = 18                        # one ffmpeg input each; a handful is plenty for an episode
DRONE_LEVEL = 0.20
SOUNDS = ("knock", "thud", "heartbeat", "ring", "sting", "whoosh", "pop", "swish")
EVENT_SOUNDS = {"knock": "knock", "door_open": "whoosh", "door_close": "thud", "lights_out": "thud",
                "eyes": "sting", "phone_ring": "ring", "shake": "thud", "heartbeat": "heartbeat"}


def _rand(seed: int):
    """A small repeatable noise source (the same sound every time it is made)."""
    state = [seed * 2654435761 % 4294967296 or 1]

    def nxt() -> float:
        state[0] = (state[0] * 1664525 + 1013904223) % 4294967296
        return state[0] / 2147483648.0 - 1.0
    return nxt


def _synth(name: str) -> list[float]:
    two_pi = 2 * math.pi
    if name == "knock":                                   # one knuckle on wood
        n, rnd, out, lp = int(RATE * 0.22), _rand(1), [], 0.0
        for i in range(n):
            t = i / RATE
            lp += 0.25 * (rnd() - lp)
            out.append((math.sin(two_pi * 150 * t) * 0.8 + math.sin(two_pi * 232 * t) * 0.45) * math.exp(-t * 34) + lp * 0.9 * math.exp(-t * 90))
        return out
    if name == "thud":                                    # a door slamming, a heavy step, the power going
        n, rnd, out, lp, ph = int(RATE * 1.1), _rand(2), [], 0.0, 0.0
        for i in range(n):
            t = i / RATE
            ph += two_pi * (38 + 60 * math.exp(-t * 9)) / RATE
            lp += 0.06 * (rnd() - lp)
            out.append(math.sin(ph) * math.exp(-t * 4.2) + lp * 2.4 * math.exp(-t * 14))
        return out
    if name == "heartbeat":                               # one beat: two thumps
        n, out = int(RATE / 1.15), []
        for i in range(n):
            t = i / RATE
            v = 0.0
            for at, amp in ((0.07, 1.0), (0.26, 0.7)):
                if t >= at:
                    v += math.sin(two_pi * 52 * (t - at)) * math.exp(-(t - at) * 22) * amp
            out.append(v)
        return out
    if name == "ring":                                    # a phone buzzing on a table, twice
        n, out = int(RATE * 1.5), []
        for i in range(n):
            t = i / RATE
            on = (t % 0.75) < 0.46
            edge = min(1.0, (t % 0.75) / 0.02, max(0.0, 0.46 - (t % 0.75)) / 0.03) if on else 0.0
            buzz = math.sin(two_pi * 158 * t) + 0.5 * math.sin(two_pi * 316 * t) + 0.25 * math.sin(two_pi * 474 * t)
            out.append(buzz * (0.6 + 0.4 * math.sin(two_pi * 27 * t)) * edge * 0.6)
        return out
    if name == "sting":                                   # a cold chord that should not be there
        n, rnd, out, lp = int(RATE * 1.8), _rand(3), [], 0.0
        for i in range(n):
            t = i / RATE
            env = min(1.0, t / 0.03) * math.exp(-t * 2.3)
            lp += 0.5 * (rnd() - lp)
            v = sum(math.sin(two_pi * f * (1 + 0.004 * t) * t) for f in (311.1, 329.6, 466.2, 622.3)) / 4
            out.append(v * env + lp * 0.25 * math.exp(-t * 30))
        return out
    if name == "whoosh":                                  # air moving: a door swinging open
        n, rnd, out, lo, band = int(RATE * 0.8), _rand(4), [], 0.0, 0.0
        for i in range(n):
            t = i / RATE
            f = 0.03 + 0.12 * math.sin(math.pi * t / 0.8)
            lo += f * (rnd() - lo - band * 0.6)
            band += f * lo
            out.append(band * math.sin(math.pi * t / 0.8) ** 2 * 1.4)
        return out
    if name == "pop":                                     # something landing on the page
        n, out, ph = int(RATE * 0.12), [], 0.0
        for i in range(n):
            t = i / RATE
            ph += two_pi * (520 + 520 * min(1.0, t / 0.05)) / RATE
            out.append(math.sin(ph) * min(1.0, t / 0.004) * math.exp(-t * 38))
        return out
    if name == "swish":                                   # a page turning: one part of a lesson to the next
        n, rnd, out, lo, band = int(RATE * 0.34), _rand(5), [], 0.0, 0.0
        for i in range(n):
            t = i / RATE
            f = 0.10 + 0.30 * (t / 0.34)
            lo += f * (rnd() - lo - band * 0.5)
            band += f * lo
            out.append(band * math.sin(math.pi * t / 0.34) ** 2)
        return out
    if name == "drone":                                   # eight seconds that loop without a seam
        n, out = RATE * 8, []
        for i in range(n):
            t = i / RATE
            slow, slower = math.sin(two_pi * 0.125 * t), math.sin(two_pi * 0.25 * t + 1.0)
            v = (math.sin(two_pi * 55 * t) * (0.62 + 0.2 * slow)
                 + math.sin(two_pi * 82.5 * t) * (0.34 + 0.16 * slower)
                 + math.sin(two_pi * 110.5 * t) * 0.2
                 + math.sin(two_pi * 164.75 * t) * 0.08 * (0.5 + 0.5 * slow))
            out.append(v)
        return out
    raise StepError(f"there is no story sound called {name}")


def sound_file(name: str) -> Path:
    """A synthesized sound as a wav in the cache (made the first time it is asked for)."""
    path = CACHE / f"v{VERSION}" / f"{name}.wav"
    if path.is_file():
        return path
    samples = _synth(name)
    peak = max(1e-9, max(abs(v) for v in samples))
    data = array.array("h", (int(max(-1.0, min(1.0, v / peak * 0.9)) * 32767) for v in samples))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data.tobytes())
    tmp.replace(path)
    return path


def cues(raw: dict, timing: dict) -> list[tuple[float, str, float]]:
    """When each sound plays: (seconds into the episode, the sound, how loud from 0 to 1)."""
    ep = stickstory.clean_episode(raw)
    out = []
    for shot, when in zip(ep["shots"], timing["shots"]):
        name = EVENT_SOUNDS.get(shot["event"])
        if not name:
            continue
        dur = when["end"] - when["start"]
        te = when["start"] + stickstory.event_at(dur)
        if shot["event"] == "knock":
            out += [(te + j * 0.26, "knock", 0.9) for j in range(3)]
        elif shot["event"] == "heartbeat":
            beat = 1 / 1.15
            out += [(when["start"] + k * beat, "heartbeat", 0.8) for k in range(int(dur / beat))][:6]
        elif shot["event"] == "door_close":
            out.append((te + 0.14, "thud", 0.9))
        elif shot["event"] == "lights_out":
            out.append((te, "thud", 0.5))
        else:
            out.append((te, name, {"sting": 0.5, "ring": 0.5, "whoosh": 0.45}.get(name, 0.8)))
    out.sort()
    return out[:MAX_CUES]


def mix(out: Path, total: float, voice: Path | None, cue_list: list[tuple[float, str, float]], drone: bool = True) -> Path:
    """Voice + drone + sounds as one stereo wav `total` seconds long."""
    import media
    media.require_ffmpeg()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [media.tool_path("ffmpeg"), "-y", "-loglevel", "error"]
    parts, labels, n = [], [], 0
    if voice and Path(voice).is_file():
        cmd += ["-i", str(voice)]
        parts.append(f"[{n}:a]aresample=44100,aformat=channel_layouts=stereo,volume=1.0[v{n}]")
        labels.append(f"[v{n}]")
        n += 1
    if drone:
        cmd += ["-stream_loop", "-1", "-i", str(sound_file("drone"))]
        fade = max(0.1, total - 1.2)
        parts.append(f"[{n}:a]aresample=44100,aformat=channel_layouts=stereo,volume={DRONE_LEVEL},"
                     f"afade=t=in:st=0:d=0.6,afade=t=out:st={fade:.2f}:d=1.2,atrim=0:{total:.3f}[v{n}]")
        labels.append(f"[v{n}]")
        n += 1
    for at, name, level in cue_list[:MAX_CUES]:
        if at >= total:
            continue
        cmd += ["-i", str(sound_file(name))]
        ms = int(max(0.0, at) * 1000)
        parts.append(f"[{n}:a]aresample=44100,aformat=channel_layouts=stereo,volume={level:.2f},adelay={ms}|{ms}[v{n}]")
        labels.append(f"[v{n}]")
        n += 1
    if not labels:
        cmd += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100", str(out)]
    else:
        graph = ";".join(parts) + ";" + "".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,alimiter=limit=0.95,apad[a]"
        cmd += ["-filter_complex", graph, "-map", "[a]", "-t", f"{total:.3f}", "-ar", "44100", "-ac", "2", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise StepError(f"ffmpeg could not mix the sound: {r.stderr.strip()[-300:]}")
    return out


PAUSE_CAP = 0.24                     # a silence between two words is cut down to this
PAUSE_CAP_SENTENCE = 0.45            # after a full stop, a question or an exclamation: room for the line to land
PAUSE_LEAD = 0.10                    # silence kept before the first word
TIGHTEN_VERSION = 1


def tighten_plan(words: list[dict], duration: float, cap: float = PAUSE_CAP, sentence_cap: float = PAUSE_CAP_SENTENCE,
                 lead: float = PAUSE_LEAD) -> tuple[list[tuple[float, float]], list[dict], float]:
    """Which stretches of the narration to keep so that no silence runs longer than its cap, and
    when each word is said afterwards. Returns (stretches to keep, the words with new times, the
    new length). A cut is made in the middle of a silence, never against a word."""
    if not words:
        return [(0.0, duration)], [], duration
    cuts = []                                             # (from, to) stretches of silence to remove
    first = float(words[0]["t"])
    if first > lead:
        cuts.append((0.0, first - lead))
    for cur, nxt in zip(words, words[1:]):
        limit = sentence_cap if str(cur["say"])[-1:] in ".!?" else cap
        gap = float(nxt["t"]) - float(cur["end"])
        if gap > limit + 0.02:
            cuts.append((float(cur["end"]) + limit / 2, float(nxt["t"]) - limit / 2))
    keep, at = [], 0.0
    for a, b in cuts:
        if a > at:
            keep.append((at, a))
        at = b
    if duration > at:
        keep.append((at, duration))

    def moved(x: float) -> float:
        return x - sum(min(x, b) - a for a, b in cuts if x > a)
    out = [{**w, "t": round(moved(float(w["t"])), 3), "end": round(moved(float(w["end"])), 3)} for w in words]
    return keep, out, round(moved(duration), 3)


def tighten(voice: Path, voice_data: dict, out: Path) -> dict:
    """The narration with its long silences cut down, written to `out` (a wav). Returns the
    voice data for the tightened recording, with "saved": the seconds that were cut."""
    import media
    words, duration = voice_data.get("words") or [], float(voice_data.get("duration") or 0)
    keep, new_words, new_duration = tighten_plan(words, duration)
    saved = round(duration - new_duration, 3)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [media.tool_path("ffmpeg"), "-y", "-loglevel", "error", "-i", str(voice)]
    if saved > 0.02 and keep:
        expr = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in keep)
        cmd += ["-af", f"aselect='{expr}',asetpts=N/SR/TB"]
    cmd += ["-ar", "44100", "-ac", "1", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise StepError(f"ffmpeg could not tighten the narration: {r.stderr.strip()[-300:]}")
    return {**voice_data, "words": new_words, "duration": new_duration, "saved": max(0.0, saved)}


def narrate(raw: dict, config: dict, voice_id: str) -> tuple[bytes, dict]:
    """The narrator reading the whole episode (one ElevenLabs request). Returns the mp3 and
    {"words": [{"say", "t", "end"}, ...], "duration": seconds} for stickstory.plan()."""
    import base64
    from steps.voice import tts_with_timestamps
    ep = stickstory.clean_episode(raw)
    text = " ".join(s["say"] for s in ep["shots"])
    if not text.strip():
        raise StepError("this episode has nothing for the narrator to say")
    data = tts_with_timestamps(text, voice_id, config, "story voice")
    a = data.get("alignment") or {}
    chars, starts, ends = a.get("characters") or [], a.get("character_start_times_seconds") or [], a.get("character_end_times_seconds") or []
    words, w0 = [], None
    for k, c in enumerate(list(chars) + [" "]):
        if c.isspace():
            if w0 is not None:
                words.append({"say": "".join(chars[w0:k]), "t": round(float(starts[w0]), 3), "end": round(float(ends[k - 1]), 3)})
            w0 = None
        elif w0 is None:
            w0 = k
    duration = float(ends[-1]) if ends else 0.0
    return base64.b64decode(data["audio_base64"]), {"words": words, "duration": round(duration, 3), "voice_id": voice_id}
