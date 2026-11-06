"""Assemble step: shots + voice-over + captions (+ music, outro) -> runs/<id>/final.mp4 via ffmpeg."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

from common import ROOT, StepError, read_json, read_script
from media import has_audio_stream, probe_duration, require_ffmpeg, run_ffmpeg
from steps.images import shot_path
from steps.video import video_path
from steps.voice import audio_path, timing_path


# ----------------------------------------------------------------- timing ----

def shot_durations(run_dir: Path, script: dict, asm: dict) -> list[dict]:
    """Per-shot: duration, start offset, VO path (or None)."""
    pad = float(asm["vo_pad_seconds"])
    minimum = float(asm["min_shot_seconds"])
    plan = []
    t = 0.0
    for shot in script["shots"]:
        n = shot["n"]
        if shot.get("card"):
            # Time-jump card: fixed length, black, no voice.
            duration = float(asm["card_seconds"])
            plan.append({"shot": shot, "n": n, "start": t, "duration": duration, "vo": None, "vo_len": 0.0})
            t += duration
            continue
        vo = audio_path(run_dir, n)
        vo_len = 0.0
        if shot["vo_line"].strip():
            if not vo.exists():
                raise StepError(f"shot {n} has a vo_line but {vo} is missing; run the voice step first")
            vo_len = probe_duration(vo)
        else:
            vo = None
        duration = max(minimum, vo_len + pad) if vo else minimum
        plan.append({"shot": shot, "n": n, "start": t, "duration": duration, "vo": vo, "vo_len": vo_len})
        t += duration
    return plan


# --------------------------------------------------------------- per shot ----

def _fill_filter(w: int, h: int) -> str:
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"


def build_shot_clip(run_dir: Path, build: Path, item: dict, asm: dict) -> Path:
    n = item["n"]
    shot = item["shot"]
    w, h, fps = int(asm["width"]), int(asm["height"]), int(asm["fps"])
    duration = item["duration"]
    frames = max(1, math.ceil(duration * fps))
    out = build / f"shot_{n:02d}.mp4"
    keyframe = shot_path(run_dir, n)
    clip = video_path(run_dir, n)
    label = f"shot {n}"

    if shot.get("card"):
        # Plain black frames; the card text is drawn by the caption pass with its own fade.
        run_ffmpeg(["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}",
                    "-frames:v", str(frames), "-an", "-vf", "setsar=1",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                    str(out)], label)
        return out

    if shot.get("animate") and clip.exists():
        # Trim to length; if the clip is shorter than the VO, hold its last frame.
        vf = (f"{_fill_filter(w, h)},fps={fps},"
              f"tpad=stop_mode=clone:stop_duration={duration + 1:.3f},setsar=1")
        run_ffmpeg(["-i", str(clip), "-t", f"{duration:.3f}", "-vf", vf, "-an",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                    str(out)], label)
        return out

    if shot.get("animate"):
        print(f"  shot {n}: animate is true but {clip.name} is missing; using a push-in on the keyframe")
    if not keyframe.exists():
        raise StepError(f"shot {n}: keyframe {keyframe} is missing; run the images step first")

    # Slow push-in. Oversample first so zoompan's integer sampling does not jitter.
    zoom_end = float(asm["zoom_end"])
    ow, oh = w * 2, h * 2
    vf = (f"{_fill_filter(ow, oh)},"
          f"zoompan=z='min(1+({zoom_end:.4f}-1)*on/{frames},{zoom_end:.4f})'"
          f":d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps},setsar=1")
    run_ffmpeg(["-i", str(keyframe), "-vf", vf, "-frames:v", str(frames), "-an",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                str(out)], label)
    return out


# --------------------------------------------------------------- captions ----

def _fc_families() -> set[str]:
    if shutil.which("fc-list") is None:
        return set()
    proc = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True)
    fams: set[str] = set()
    for line in proc.stdout.splitlines():
        for fam in line.split(","):
            fams.add(fam.strip().lower())
    return fams


def pick_caption_font(asm: dict) -> str:
    """Return the font family to name in the .ass style. Warns when falling back."""
    wanted = str(asm["caption_font"])
    fallback = str(asm["caption_fallback_font"])
    fams = _fc_families()
    if not fams:
        return wanted  # no fontconfig to ask; let libass resolve it
    base = wanted.lower().replace(" italic", "")
    if any(base in f or f in base for f in fams):
        return wanted.replace(" Italic", "")
    if any(fallback.lower() in f for f in fams):
        print(f"  captions: '{wanted}' not installed, using '{fallback}'")
        return fallback
    print(f"  captions: neither '{wanted}' nor '{fallback}' is installed; libass will substitute a bold "
          f"sans. Install Montserrat for the intended look.")
    return wanted.replace(" Italic", "")


MAX_CHUNK_WORDS = 2
POP_MS = 80                    # pop-in: scale 85% -> 100% over this many milliseconds
POP_FROM = 85
_BREAK_AFTER = tuple(".,!?;:\u2014\u2013")   # a chunk always ends after a word ending in these
_QUOTES = "\"'\u201c\u201d\u2018\u2019()[]"
_DROP_TRAILING = ".,;:\u2014\u2013-"       # dropped from display; ! and ? are kept for tone


def _display(word: str) -> str:
    """Caption text for one spoken token: all caps, wrapping quotes and soft punctuation removed."""
    text = word.strip().strip(_QUOTES).rstrip(_DROP_TRAILING).strip(_QUOTES)
    return text.upper()


def _ends_clause(word: str) -> bool:
    return word.strip().rstrip(_QUOTES).endswith(_BREAK_AFTER)


def chunk_words(words: list[dict]) -> list[dict]:
    """Group timed words into chunks of at most MAX_CHUNK_WORDS, breaking after punctuation.

    Returns [{"text": "THE WINDOW", "start": seconds into the clip}]. A token that is pure
    punctuation (a standalone dash, an ellipsis) shows nothing and ends the current chunk."""
    chunks: list[dict] = []
    cur: list[str] = []
    cur_start = 0.0
    for w in words:
        text = _display(w["word"])
        if not text:
            if cur:
                chunks.append({"text": " ".join(cur), "start": cur_start})
                cur = []
            continue
        if not cur:
            cur_start = float(w["start"])
        cur.append(text)
        if len(cur) >= MAX_CHUNK_WORDS or _ends_clause(w["word"]):
            chunks.append({"text": " ".join(cur), "start": cur_start})
            cur = []
    if cur:
        chunks.append({"text": " ".join(cur), "start": cur_start})
    return chunks


def _spread_words(text: str, length: float) -> list[dict]:
    """Even timing for a clip whose timing json is missing (fallback only)."""
    toks = text.split()
    if not toks or length <= 0:
        return []
    step = length / len(toks)
    return [{"word": t, "start": round(i * step, 3), "end": round((i + 1) * step, 3)}
            for i, t in enumerate(toks)]


def card_event(item: dict) -> tuple[float, float, str] | None:
    """A card shot's text for its whole length, or None for any other shot."""
    card = (item["shot"].get("card") or "").strip().upper()
    if not card:
        return None
    return (item["start"], item["start"] + item["duration"], card)


def shot_caption_events(run_dir: Path, item: dict) -> list[tuple[float, float, str]]:
    """(start, end, text) in seconds on the final timeline for one shot's captions.

    Spoken shot: every word, in chunks synced to the voice timing; each chunk holds until the
    next one starts, the last until the shot ends. Silent shot: the caption field for the whole
    shot (nothing if it is empty)."""
    shot_start = item["start"]
    shot_end = item["start"] + item["duration"]
    if item["shot"].get("card"):
        return []
    if item["vo"] is None:
        caption = (item["shot"].get("caption") or "").strip().upper()
        return [(shot_start, shot_end, caption)] if caption else []

    tp = timing_path(run_dir, item["n"])
    words = read_json(tp).get("words", []) if tp.exists() else []
    if not words:
        print(f"  shot {item['n']}: no word timings in {tp.name}; spreading the words evenly over the VO")
        words = _spread_words(item["shot"]["vo_line"], item["vo_len"])

    chunks = chunk_words(words)
    events = []
    for i, ch in enumerate(chunks):
        start = min(shot_start + ch["start"], shot_end)
        end = shot_start + chunks[i + 1]["start"] if i + 1 < len(chunks) else shot_end
        end = min(max(end, start + 0.05), shot_end)
        if end > start:
            events.append((start, end, ch["text"]))
    return events


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def write_captions(run_dir: Path, build: Path, plan: list[dict], asm: dict) -> tuple[Path, int]:
    w, h = int(asm["width"]), int(asm["height"])
    font = pick_caption_font(asm)
    size = int(asm["caption_size"])
    cy = int(round(h * float(asm["caption_y"])))
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {w}",
        f"PlayResY: {h}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # white fill, pink-white outline (&HAABBGGRR), bold italic, outline 5 + \\blur6 = soft glow
        f"Style: Caption,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00E6C8FF,&H00000000,"
        f"-1,-1,0,0,100,100,0,0,1,5,0,5,40,40,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    # Pop-in on every chunk: start at 85% scale, animate to 100% over the first 80ms.
    pop = f"\\fscx{POP_FROM}\\fscy{POP_FROM}\\t(0,{POP_MS},\\fscx100\\fscy100)"
    # Time-jump cards: same style, centred on the black frame, a quick fade in and out, no pop.
    fade = int(asm["card_fade_ms"])
    count = 0
    for item in plan:
        card = card_event(item)
        if card is not None:
            start, end, text = card
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,"
                         f"{{\\an5\\pos({w // 2},{h // 2})\\blur6\\fad({fade},{fade})}}{_ass_escape(text)}")
            count += 1
            continue
        for start, end, text in shot_caption_events(run_dir, item):
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,"
                         f"{{\\an5\\pos({w // 2},{cy})\\blur6{pop}}}{_ass_escape(text)}")
            count += 1
    path = build / "captions.ass"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, count


# ------------------------------------------------------------------- mix ----

def render_main(build: Path, cut: Path, captions: Path, plan: list[dict], total: float,
                config: dict) -> Path:
    asm = config["assemble"]
    w, h, fps = int(asm["width"]), int(asm["height"]), int(asm["fps"])
    out = build / "main.mp4"

    args: list[str] = ["-i", str(cut)]
    vo_items = [it for it in plan if it["vo"] is not None]
    for it in vo_items:
        args += ["-i", str(it["vo"])]
    music = config.get("music_path") or ""
    music_file = (ROOT / music) if music else None
    if music_file and not music_file.exists():
        print(f"  music: {music} not found, skipping the music bed")
        music_file = None
    if music_file:
        args += ["-stream_loop", "-1", "-i", str(music_file)]

    # Video: burn captions, then a light grade (desaturate + a slight cool tint).
    sat = float(asm["saturation"])
    vchain = (f"[0:v]ass=captions.ass,eq=saturation={sat:.3f},"
              f"colorbalance=rs=-0.03:bs=0.04:rm=-0.02:bm=0.03:rh=-0.01:bh=0.02,"
              f"format=yuv420p[v]")

    # Audio: VO clips at their shot start times, optional music bed, padded to the cut length.
    parts = [vchain]
    labels: list[str] = []
    for i, it in enumerate(vo_items, start=1):
        ms = int(round(it["start"] * 1000))
        parts.append(f"[{i}:a]aresample=44100,adelay={ms}:all=1[vo{i}]")
        labels.append(f"[vo{i}]")
    if music_file:
        mi = len(vo_items) + 1
        parts.append(f"[{mi}:a]aresample=44100,volume={float(asm['music_volume']):.3f},"
                     f"atrim=0:{total:.3f}[mu]")
        labels.append("[mu]")
    if labels:
        if len(labels) == 1:
            parts.append(f"{labels[0]}apad,atrim=0:{total:.3f}[a]")
        else:
            parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,"
                         f"apad,atrim=0:{total:.3f}[a]")
    else:
        parts.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{total:.3f}[a]")

    run_ffmpeg([*args, "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
                "-t", f"{total:.3f}", "-r", str(fps), "-s", f"{w}x{h}",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                "-movflags", "+faststart", str(out)], "final mix", cwd=build)
    return out


def append_outro(build: Path, main: Path, config: dict) -> Path:
    asm = config["assemble"]
    outro = config.get("outro_path") or ""
    if not outro:
        return main
    src = ROOT / outro
    if not src.exists():
        print(f"  outro: {outro} not found, skipping")
        return main
    w, h, fps = int(asm["width"]), int(asm["height"]), int(asm["fps"])
    outro_len = probe_duration(src)
    audio_in = ["-i", str(src)]
    if not has_audio_stream(src):
        # anullsrc is endless: bound it to the outro's length or the concat never finishes.
        audio_in = ["-i", str(src), "-f", "lavfi", "-t", f"{outro_len:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
    out = build / "with_outro.mp4"
    vf = f"[1:v]{_fill_filter(w, h)},fps={fps},setsar=1,format=yuv420p,trim=0:{outro_len:.3f}[ov]"
    outro_audio = "[2:a]" if len(audio_in) > 2 else "[1:a]"
    run_ffmpeg(["-i", str(main), *audio_in, "-filter_complex",
                f"{vf};{outro_audio}aresample=44100,aformat=channel_layouts=stereo,"
                f"atrim=0:{outro_len:.3f}[oa];"
                f"[0:v][0:a][ov][oa]concat=n=2:v=1:a=1[v][a]",
                "-map", "[v]", "-map", "[a]", "-r", str(fps),
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-movflags", "+faststart", str(out)],
               "outro", cwd=build)
    print(f"  outro: appended {outro}")
    return out


# ------------------------------------------------------------------ cost ----

def cost_report(run_dir: Path, script: dict, config: dict) -> list[tuple[str, float]]:
    fal = config["fal"]
    locked = {c["id"]: c for c in config.get("locked_characters", [])}
    keyframes = sum(1 for s in script["shots"] if shot_path(run_dir, s["n"]).exists())
    sheets = sum(1 for c in script["characters"]
                 if (run_dir / "characters" / f"{c['id']}.png").exists()
                 and not (locked.get(c["id"], {}).get("image_path")))
    clips = sum(1 for s in script["shots"] if video_path(run_dir, s["n"]).exists())
    chars = 0
    for s in script["shots"]:
        tp = timing_path(run_dir, s["n"])
        if tp.exists():
            chars += int(read_json(tp).get("characters", 0))
    return [
        (f"images ({keyframes} keyframes + {sheets} sheets)", (keyframes + sheets) * float(fal["image_cost"])),
        (f"video ({clips} clips x {fal['video_seconds']}s)", clips * float(fal["video_seconds"]) * float(fal["video_cost_per_second"])),
        (f"voice ({chars} chars)", chars / 1000 * float(config["elevenlabs"]["cost_per_1k_chars"])),
    ]


# ------------------------------------------------------------------- run ----

def run(run_dir: Path, config: dict) -> None:
    require_ffmpeg()
    script = read_script(run_dir)
    asm = config["assemble"]
    build = run_dir / "build"
    build.mkdir(parents=True, exist_ok=True)

    plan = shot_durations(run_dir, script, asm)
    total = sum(it["duration"] for it in plan)
    print(f"[assemble] {len(plan)} shots, {total:.1f}s at {asm['width']}x{asm['height']} {asm['fps']}fps")

    clips = []
    for it in plan:
        if it["shot"].get("card"):
            kind = f"card \"{it['shot']['card']}\""
        else:
            kind = "clip" if (it["shot"].get("animate") and video_path(run_dir, it["n"]).exists()) else "push-in"
        print(f"  shot {it['n']}: {kind} {it['duration']:.2f}s" + (f" (VO {it['vo_len']:.2f}s)" if it["vo"] else ""))
        clips.append(build_shot_clip(run_dir, build, it, asm))

    concat_list = build / "concat.txt"
    concat_list.write_text("".join(f"file '{c.name}'\n" for c in clips), encoding="utf-8")
    cut = build / "cut.mp4"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", cut.name],
               "concat", cwd=build)

    captions, n_caps = write_captions(run_dir, build, plan, asm)
    print(f"[assemble] {n_caps} caption(s) -> {captions.relative_to(run_dir)}")

    main = render_main(build, cut, captions, plan, total, config)
    final_src = append_outro(build, main, config)
    final = run_dir / "final.mp4"
    shutil.copyfile(final_src, final)

    print(f"\n[assemble] final: {final}  ({probe_duration(final):.1f}s)")
    rows = cost_report(run_dir, script, config)
    print("[assemble] estimated cost:")
    for name, usd in rows:
        print(f"  {name:<40} ${usd:.2f}")
    print(f"  {'total':<40} ${sum(u for _, u in rows):.2f}")
