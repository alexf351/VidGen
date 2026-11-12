"""Sound effects under the cut: a whoosh on a scene change, a hit on a time card, a riser into
the montage, a pop when the phone comes up.

Where each sound comes from, first match wins:

    assets/sfx/<name>.wav|mp3|m4a|ogg     your own file (drop it in and it is used from then on)
    cache/sfx/el-<name>-<hash>.mp3        made once with ElevenLabs Sound Effects, then reused
    built in                              synthesized here, no service needed

Every source is brought to the same loudness and trimmed to start on the sound, so a whoosh from
a sample pack sits at the same level as a built-in one.

    sfx:
      enabled: true
      source: auto        # auto = ElevenLabs when a key is set, else built in | elevenlabs | builtin
      volume: 1.0         # all effects together

The assemble step asks `cues()` what plays when, and `render_track()` writes them as one audio
track that is mixed under the voice.
"""

from __future__ import annotations

import array
import hashlib
import json
import math
import random
import wave
from pathlib import Path

from common import ROOT, StepError

RATE = 44100
SOURCES = ("auto", "elevenlabs", "builtin")
EXTS = (".wav", ".mp3", ".m4a", ".ogg")
PEAK_DB = -3.0                    # every sound is brought to this peak before its own level

# name -> what it is for, how loud it plays against the voice (0-1), where it sits on the cut
# ("center" = its loudest point lands on the cut, "start" = it begins on the cut, "end" = it
# finishes on the cut), and the ElevenLabs prompt and length for it.
SOUNDS: dict[str, dict] = {
    # Light and high: the first whoosh was a low cinematic rush that sat under the voices like
    # a rumble. "shape" is applied to the generated sound whatever comes back: everything under
    # `highpass` Hz is cut and the pitch is raised by `pitch`. Your own assets/sfx file is never
    # shaped.
    "whoosh": {"level": 0.28, "at": "center", "seconds": 0.7,
               "prompt": "One very short light airy whoosh, a quick high-pitched swish of air like a fast "
                         "page flick, thin and bright, no bass, no rumble, clean and dry, no music",
               "shape": {"highpass": 650, "pitch": 1.15}},
    "swish":  {"level": 0.36, "at": "center", "seconds": 0.5,
               "prompt": "One very short light swish, a quick fast air movement, clean and dry, no music",
               "shape": {"highpass": 500, "pitch": 1.1}},
    "impact": {"level": 0.50, "at": "start", "seconds": 1.5,
               "prompt": "A single deep cinematic boom impact, one low hit with a short tail, no music"},
    "pop":    {"level": 0.30, "at": "start", "seconds": 0.5,
               "prompt": "One short soft bubble pop, a single clean user interface pop sound"},
    "riser":  {"level": 0.26, "at": "end", "seconds": 2.0,
               "prompt": "A short tension riser, a rising whoosh that builds and stops abruptly, no music"},
}
NAMES = tuple(SOUNDS)
SHOT_VALUES = NAMES + ("none",)   # what a shot's "sfx" key may say
MAX_SHOT_SFX = 5                  # at most this many shots carry their own "sfx"
MIN_GAP = 0.9                     # two scene whooshes are never closer than this (seconds)
CUT_GAP = 0.45                    # nor two swishes on ordinary cuts closer than this
CUT_GAIN = 0.6                    # a swish on an ordinary cut plays this much quieter than on a montage cut
BUILTIN_VERSION = 2               # bump when the synthesized sounds change
STAT_TICK_AT = 0.55               # how far into a progress shot its number ticks up (0-1)


# ------------------------------------------------------------------ settings ----

def settings(config: dict) -> dict:
    """The checked sfx settings: {"enabled", "source", "volume", "cuts"}."""
    raw = config.get("sfx")
    if isinstance(raw, bool):
        raw = {"enabled": raw}
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise StepError("config: sfx must be true, false, or a block with enabled / source / volume")
    unknown = sorted(set(raw) - {"enabled", "source", "volume", "cuts"})
    if unknown:
        raise StepError(f"config: sfx has unknown keys {unknown}; use enabled, source, volume, cuts")
    every_cut = raw.get("cuts", True)
    if not isinstance(every_cut, bool):
        raise StepError("config: sfx.cuts must be true or false")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise StepError("config: sfx.enabled must be true or false")
    source = str(raw.get("source") or "auto").strip().lower()
    if source not in SOURCES:
        raise StepError(f"config: sfx.source must be one of {', '.join(SOURCES)}, got {source!r}")
    try:
        volume = float(raw.get("volume", 1.0))
    except (TypeError, ValueError):
        raise StepError("config: sfx.volume must be a number (1.0 = normal, 0 = silent)") from None
    if not 0 <= volume <= 3:
        raise StepError("config: sfx.volume must be between 0 and 3")
    return {"enabled": enabled, "source": source, "volume": volume, "cuts": every_cut}


def enabled(config: dict) -> bool:
    s = config.get("sfx")
    return bool(s.get("enabled")) if isinstance(s, dict) else bool(s)


# ---------------------------------------------------------------- where they go ----

def _kind(shot: dict) -> str:
    for k in ("card", "app_screen", "texts", "montage", "flash", "letter"):
        if shot.get(k):
            return k
    return "scene"


def cues(plan: list[dict], every_cut: bool = False) -> list[dict]:
    """What plays when: [{"t": seconds on the timeline of the cut the sound belongs to,
    "sound": name, "shot": n, "why": text}], in time order.

    Automatic: an impact on a time card, a pop when the app screen comes up, a riser into the
    first montage shot with an impact on it and a swish on every montage cut after it, and a
    whoosh on every change of scene (only when the script marks its scenes with "same_scene").
    With `every_cut` (sfx.cuts, on by default) every other cut between two drawn shots gets a
    soft swish too, the way the fast-cut story ads do; without it cuts inside a scene stay
    clean. A shot's own "sfx" replaces what it would get automatically: a sound name plays that
    sound on the shot's first frame, "none" keeps the shot silent."""
    shots = [it["shot"] for it in plan]
    scenes_marked = any(s.get("same_scene") is True for s in shots)
    out: list[dict] = []
    last_whoosh = -10.0
    prev_kind = ""
    for i, it in enumerate(plan):
        shot, t, kind = it["shot"], float(it["start"]), _kind(it["shot"])
        own = str(shot.get("sfx") or "").strip().lower()

        def add(sound: str, why: str, gain: float = 1.0, after: float = 0.0) -> None:
            cue = {"t": round(t + after, 3), "sound": sound, "shot": it["n"], "why": why}
            if gain != 1.0:
                cue["gain"] = gain
            out.append(cue)

        if own == "none":
            pass
        elif own in SOUNDS:
            add(own, "set on the shot")
            if own in ("whoosh", "swish"):
                last_whoosh = t
        elif kind == "card":
            add("impact", "time card")
        elif kind == "app_screen":
            add("pop", "app screen")
        elif kind == "texts":
            import phone_texts
            for k, at in enumerate(phone_texts.arrivals(shot["texts"], float(it["duration"]))):
                add("pop", "a message arrives" if k else "the phone lights up", after=at)
        elif kind == "montage":
            if prev_kind != "montage":
                if t >= 0.6:
                    add("riser", "into the montage")
                add("impact", "montage starts")
            else:
                add("swish", "montage cut")
        elif kind == "flash":
            if prev_kind != "flash":
                add("swish", "the flashes start")
        elif kind == "scene" and i > 0 and scenes_marked and shot.get("same_scene") is not True:
            if t - last_whoosh >= MIN_GAP and prev_kind != "flash":
                add("whoosh", "new scene")
                last_whoosh = t
        elif kind == "scene" and i > 0 and every_cut and prev_kind in ("scene", "app_screen", "texts"):
            # A cut inside a scene (or back from the phone): a quick, quiet swish.
            if t - last_whoosh >= CUT_GAP:
                add("swish", "cut", CUT_GAIN)
                last_whoosh = t
        if prev_kind == "flash" and kind != "flash" and own != "none":
            # The run of flashes builds to the shot it lands on.
            add("riser", "the flashes build")
            if not any(c["shot"] == it["n"] and c["sound"] == "impact" for c in out):
                add("impact", "the flashes land")
        stat = shot.get("stat")
        if own != "none" and isinstance(stat, dict) and int(stat.get("value") or 0) > 0:
            # The number on a progress shot ticks up partway through; a pop lands with it.
            out.append({"t": round(t + STAT_TICK_AT * float(it["duration"]), 3), "sound": "pop",
                        "shot": it["n"], "why": "the number ticks up"})
        prev_kind = kind
    return sorted(out, key=lambda c: (c["t"], c["sound"]))


# ------------------------------------------------------------- built-in sounds ----

def _svf_noise(seconds: float, freq, amp, q: float, seed: int, mode: str = "band") -> list[float]:
    """White noise through a state-variable filter whose cutoff follows freq(x) and whose level
    follows amp(x), x running 0-1 over the sound."""
    rng = random.Random(seed)
    n = int(seconds * RATE)
    low = band = 0.0
    out = []
    for i in range(n):
        x = i / n
        f = 2 * math.sin(math.pi * min(freq(x), RATE / 6.5) / RATE)
        high = (rng.random() * 2 - 1) - low - q * band
        band += f * high
        low += f * band
        out.append((band if mode == "band" else low) * amp(x))
    return out


def _bell(x: float, center: float, width: float) -> float:
    return math.exp(-(((x - center) / width) ** 2))


def _sweep(a: float, b: float, x: float) -> float:
    return a * (b / a) ** x


def _synth(name: str) -> list[float]:
    if name == "whoosh":      # air rushing past: the band sweeps up and back, loudest in the middle
        return _svf_noise(0.46, lambda x: _sweep(1100, 6800, 1 - abs(2 * x - 1)),
                          lambda x: _bell(x, 0.5, 0.2), 0.6, 11)
    if name == "swish":       # the same, shorter and brighter, for fast cuts
        return _svf_noise(0.28, lambda x: _sweep(1200, 5200, 1 - abs(2 * x - 1)),
                          lambda x: _bell(x, 0.5, 0.2), 0.6, 12)
    if name == "riser":       # builds to the cut and stops
        body = _svf_noise(1.5, lambda x: _sweep(300, 6000, x ** 1.4),
                          lambda x: (x ** 2.2) * min(1.0, (1 - x) / 0.012), 0.35, 13)
        return body
    if name == "impact":      # a low drum-like hit: a falling sine with a short thud of noise on top
        n = int(0.95 * RATE)
        thud = _svf_noise(0.95, lambda x: _sweep(900, 120, min(1.0, x * 12)),
                          lambda x: math.exp(-x * 60), 0.9, 14, mode="low")
        out, phase = [], 0.0
        for i in range(n):
            t = i / RATE
            phase += 2 * math.pi * (38 + 85 * math.exp(-t * 16)) / RATE
            body = math.sin(phase) * math.exp(-t * 4.6) * min(1.0, t / 0.004)
            out.append(math.tanh(1.6 * (body + 0.5 * thud[i])))
        return out
    if name == "pop":         # a round, short blip that drops in pitch
        n = int(0.12 * RATE)
        out, phase = [], 0.0
        for i in range(n):
            t = i / RATE
            phase += 2 * math.pi * (280 + 720 * math.exp(-t * 55)) / RATE
            out.append(math.sin(phase) * math.exp(-t * 42) * min(1.0, t / 0.002))
        return out
    raise StepError(f"sfx: there is no built-in sound called {name!r}")


def _write_wav(path: Path, samples: list[float]) -> None:
    peak = max((abs(s) for s in samples), default=0.0) or 1.0
    scale = 32767 * (10 ** (PEAK_DB / 20)) / peak
    fade = min(len(samples) // 2, int(0.006 * RATE))          # no click at either end
    pcm = array.array("h")
    for i, s in enumerate(samples):
        g = min(1.0, i / fade, (len(samples) - 1 - i) / fade) if fade else 1.0
        v = int(max(-32767, min(32767, s * scale * g)))
        pcm.extend((v, v))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    tmp.replace(path)


def builtin(name: str) -> Path:
    """The built-in sound as a wav in cache/sfx/, synthesized on first use."""
    path = ROOT / "cache" / "sfx" / f"builtin-{name}-v{BUILTIN_VERSION}.wav"
    if not path.exists():
        _write_wav(path, _synth(name))
    return path


# ------------------------------------------------------------------ the sources ----

def user_file(name: str) -> Path | None:
    for ext in EXTS:
        p = ROOT / "assets" / "sfx" / f"{name}{ext}"
        if p.is_file():
            return p
    return None


def _el_path(name: str) -> Path:
    spec = SOUNDS[name]
    key = hashlib.sha1(f"{spec['prompt']}|{spec['seconds']}".encode()).hexdigest()[:10]
    return ROOT / "cache" / "sfx" / f"el-{name}-{key}.mp3"


def _elevenlabs(name: str) -> Path:
    """The sound made by ElevenLabs Sound Effects, from the cache or generated now."""
    path = _el_path(name)
    if path.exists():
        return path
    import requests
    from steps.voice import API_BASE, require_key
    spec = SOUNDS[name]
    try:
        r = requests.post(f"{API_BASE}/v1/sound-generation", params={"output_format": "mp3_44100_128"},
                          headers={"xi-api-key": require_key(), "Content-Type": "application/json"},
                          json={"text": spec["prompt"], "duration_seconds": spec["seconds"],
                                "prompt_influence": 0.6}, timeout=120)
    except requests.RequestException as e:
        raise StepError(f"could not reach ElevenLabs: {e}") from e
    if r.status_code != 200:
        raise StepError(f"ElevenLabs Sound Effects returned HTTP {r.status_code}: {r.text[:300]}")
    if not r.content or r.headers.get("content-type", "").startswith("application/json"):
        raise StepError(f"ElevenLabs Sound Effects returned no audio: {r.text[:200]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(r.content)
    tmp.replace(path)
    return path


def _have_key() -> bool:
    try:
        from steps.voice import require_key
        require_key()
        return True
    except StepError:
        return False


# ------------------------------------------------- one level, starting on the sound ----

def _envelope(path: Path) -> tuple[float, float, float]:
    """(peak 0-1, seconds to the loudest 10 ms, length in seconds) of a 16-bit wav."""
    with wave.open(str(path), "rb") as w:
        ch, rate, n = w.getnchannels(), w.getframerate(), w.getnframes()
        pcm = array.array("h")
        pcm.frombytes(w.readframes(n))
    if not n:
        return 0.0, 0.0, 0.0
    block = max(1, rate // 100) * ch
    best, best_at, peak = -1, 0, 0
    for i in range(0, len(pcm), block):
        chunk = pcm[i:i + block]
        top = max(abs(min(chunk)), abs(max(chunk)))
        peak = max(peak, top)
        energy = sum(abs(v) for v in chunk)
        if energy > best:
            best, best_at = energy, i
    return peak / 32768, (best_at + block / 2) / ch / rate, n / rate


def _shape_filters(shape: dict | None) -> str:
    """ffmpeg filters for a sound's "shape": raise the pitch (the sound gets shorter by the same
    factor), then cut the lows. "" for no shaping."""
    if not shape:
        return ""
    parts = []
    pitch = float(shape.get("pitch") or 1.0)
    if abs(pitch - 1.0) > 0.001:
        parts.append(f"aresample={RATE},asetrate={int(round(RATE * pitch))},aresample={RATE}")
    cut = float(shape.get("highpass") or 0)
    if cut > 0:
        parts.append(f"highpass=f={cut:.0f}")
    return ",".join(parts)


def _prepare(name: str, src: Path, shape: dict | None = None) -> dict:
    """`src` as a 44.1 kHz stereo wav that starts on the sound and peaks at PEAK_DB, plus where its
    loudest point is. Kept in cache/sfx/ready/, keyed by the source file's contents and the shape."""
    from media import run_ffmpeg
    shaping = _shape_filters(shape)
    digest = hashlib.sha1(src.read_bytes() + shaping.encode()).hexdigest()[:12]
    folder = ROOT / "cache" / "sfx" / "ready"
    wav, note = folder / f"{name}-{digest}.wav", folder / f"{name}-{digest}.json"
    if wav.exists() and note.exists():
        try:
            info = json.loads(note.read_text(encoding="utf-8"))
            return {**info, "path": wav}
        except (ValueError, OSError):
            pass
    folder.mkdir(parents=True, exist_ok=True)
    plain = folder / f"{name}-{digest}.plain.wav"
    run_ffmpeg(["-i", str(src), "-vn", "-t", "20", *(["-af", shaping] if shaping else []),
                "-ar", str(RATE), "-ac", "2", "-c:a", "pcm_s16le", str(plain)],
               f"sound effect {name}")
    peak, _, length = _envelope(plain)
    if peak <= 0.0005 or length < 0.03:
        plain.unlink(missing_ok=True)
        raise StepError(f"{src.name} has no sound in it")
    gain = (10 ** (PEAK_DB / 20)) / peak
    # Bring it to the common level, then cut the silence before the sound (a generated effect
    # often starts late, and then it would land after the cut) and the dead air after it. Cap
    # the length so a long file cannot smear over the next shots.
    run_ffmpeg(["-i", str(plain), "-af",
                f"volume={gain:.4f},"
                "silenceremove=start_periods=1:start_threshold=-42dB:start_silence=0.01,"
                "areverse,silenceremove=start_periods=1:start_threshold=-48dB:start_silence=0.02,areverse,"
                "atrim=0:4", "-c:a", "pcm_s16le", str(wav)],
               f"sound effect {name} level")
    plain.unlink(missing_ok=True)
    _, loudest, length = _envelope(wav)
    if length < 0.03:
        wav.unlink(missing_ok=True)
        raise StepError(f"{src.name} has no sound in it")
    info = {"loudest": round(loudest, 3), "seconds": round(length, 3), "from": src.name}
    note.write_text(json.dumps(info), encoding="utf-8")
    return {**info, "path": wav}


def library(config: dict, names: list[str]) -> dict[str, dict]:
    """{name: {"path", "loudest", "seconds", "from"}} for the sounds a cut needs. Never fails the
    step for one bad source: a sound that cannot be made by ElevenLabs is built in instead."""
    source = settings(config)["source"]
    use_el = source == "elevenlabs" or (source == "auto" and _have_key())
    lib: dict[str, dict] = {}
    made, fell_back = [], []
    for name in dict.fromkeys(names):
        mine = user_file(name)
        if mine is not None:
            try:
                lib[name] = _prepare(name, mine)
                continue
            except StepError as e:
                print(f"  sound effects: your {mine.relative_to(ROOT)} could not be used ({e}); "
                      f"using the standard {name}")
        if use_el:
            fresh = not _el_path(name).exists()
            try:
                lib[name] = _prepare(name, _elevenlabs(name), SOUNDS[name].get("shape"))
                if fresh:
                    made.append(name)
                continue
            except StepError as e:
                fell_back.append(f"{name} ({e})")
        lib[name] = _prepare(name, builtin(name))
    if made:
        print(f"  sound effects: made {', '.join(made)} with ElevenLabs (one time; kept in cache/sfx "
              f"and reused by every video)")
    if fell_back:
        print("  sound effects: ElevenLabs could not make " + "; ".join(fell_back)
              + ". Using the built-in sound instead.")
    return lib


# ------------------------------------------------------------------- the track ----

def placed(cue_list: list[dict], lib: dict[str, dict], total: float) -> list[dict]:
    """Each cue with the moment its file starts playing and its level, so that the sound sits on
    its cut the way SOUNDS says. A riser that would start before the video does starts late."""
    out = []
    for c in cue_list:
        spec, info = SOUNDS[c["sound"]], lib[c["sound"]]
        if spec["at"] == "center":
            start = c["t"] - info["loudest"]
        elif spec["at"] == "end":
            start = c["t"] - info["seconds"]
        else:
            start = c["t"]
        skip = max(0.0, -start)                    # the part that falls before 0:00 is cut off
        start = max(0.0, start)
        if start >= total or skip >= info["seconds"]:
            continue
        out.append({**c, "start": round(start, 3), "skip": round(skip, 3),
                    "level": round(spec["level"] * float(c.get("gain", 1.0)), 4), "path": info["path"]})
    return out


def render_track(build: Path, plan: list[dict], total: float, config: dict) -> Path | None:
    """build/sfx.wav: every effect at its place, silence between them, as long as the cut. None
    when sound effects are off or this cut has no place for one."""
    from media import run_ffmpeg
    cfg = settings(config)
    if not cfg["enabled"] or cfg["volume"] <= 0:
        return None
    cue_list = cues(plan, every_cut=cfg["cuts"])
    if not cue_list:
        print("  sound effects: nothing in this cut calls for one")
        return None
    lib = library(config, [c["sound"] for c in cue_list])
    items = placed(cue_list, lib, total)
    if not items:
        return None
    args: list[str] = []
    parts, labels = [], []
    for i, it in enumerate(items):
        args += ["-i", str(it["path"])]
        trim = f"atrim=start={it['skip']:.3f},asetpts=PTS-STARTPTS," if it["skip"] else ""
        parts.append(f"[{i}:a]{trim}volume={it['level'] * cfg['volume']:.3f},"
                     f"adelay={int(round(it['start'] * 1000))}:all=1[s{i}]")
        labels.append(f"[s{i}]")
    mix = (f"{labels[0]}" if len(labels) == 1 else
           f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,")
    tail = f"apad,atrim=0:{total:.3f}[a]"
    parts.append(f"{mix}{tail}" if len(labels) > 1 else f"{labels[0]}{tail}")
    out = build / "sfx.wav"
    run_ffmpeg([*args, "-filter_complex", ";".join(parts), "-map", "[a]", "-ar", str(RATE), "-ac", "2",
                "-c:a", "pcm_s16le", str(out)], "sound effects track")
    counts: dict[str, int] = {}
    for it in items:
        counts[it["sound"]] = counts.get(it["sound"], 0) + 1
    print("  sound effects: " + ", ".join(f"{n} {s}" for s, n in counts.items())
          + " -> " + out.name)
    (build / "sfx.json").write_text(json.dumps(
        [{k: (str(v.name) if isinstance(v, Path) else v) for k, v in it.items()} for it in items],
        indent=1), encoding="utf-8")
    return out
