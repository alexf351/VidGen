"""Assemble step: shots + voice-over + captions (+ sound effects, music, outro) -> runs/<id>/final.mp4
via ffmpeg."""

from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
from pathlib import Path

from common import ROOT, StepError, read_json, read_script
from media import ffmpeg_version, has_audio_stream, probe_duration, require_ffmpeg, run_ffmpeg
from steps.images import shot_path
from steps.video import video_path
from steps.voice import audio_path, timing_path


# ----------------------------------------------------------------- timing ----

def song_durations(run_dir: Path, script: dict) -> list[dict]:
    """Song mode: every shot spans its lyric line in the song (steps/song.py)."""
    from steps.song import song_plan
    info = song_plan(run_dir)
    if info is None:
        raise StepError("this format is a song and audio/song.mp3 is missing; run the voice step first")
    spans = {s["n"]: s for s in info["shots"]}
    plan = []
    for shot in script["shots"]:
        n = shot["n"]
        if n not in spans:
            raise StepError(f"shot {n} has no place in the song (audio/song.json); run the voice step again")
        start, end = float(spans[n]["start"]), float(spans[n]["end"])
        plan.append({"shot": shot, "n": n, "start": start, "duration": end - start, "vo": None,
                     "vo_len": end - start, "sung": True})
    return plan


def letter_seconds(shot: dict, asm: dict) -> float:
    """How long a silent letter shot stays up: long enough to read its line."""
    words = len(str(shot.get("letter") or "").split())
    return words / float(asm["letter_read_wps"]) + 0.8 if words else 0.0


def app_clip_file(shot: dict, asm: dict) -> Path | None:
    """The recording an app screen shot plays, or None when it shows the still: the screenshot
    has no recording, the shot asks for the still ("app_still"), or recordings are switched off."""
    if not shot.get("app_screen") or shot.get("app_still") is True or not asm.get("app_screen_clips", True):
        return None
    import app_assets
    clip = app_assets.clip_for(str(shot["app_screen"]).strip())
    return clip if clip and app_assets.clip_seconds(clip) else None


def app_screen_length(shot: dict, asm: dict) -> float:
    """Seconds an app screen is on with no line said over it: the usual length for a still,
    the recording's own length for a recording (never longer than app_clip_max_seconds)."""
    base = float(asm["app_screen_seconds"])
    clip = app_clip_file(shot, asm)
    if clip is None:
        return base
    import app_assets
    return max(base, min(float(app_assets.clip_seconds(clip)), float(asm.get("app_clip_max_seconds", 6.0))))


def shot_durations(run_dir: Path, script: dict, asm: dict, song: bool = False) -> list[dict]:
    """Per-shot: duration, start offset, VO path (or None)."""
    if song:
        return song_durations(run_dir, script)
    pad = float(asm["vo_pad_seconds"])
    minimum = float(asm["min_shot_seconds"])
    plan = []
    t = 0.0
    for shot in script["shots"]:
        n = shot["n"]
        if shot.get("app_screen") and str(shot.get("vo_line") or "").strip():
            # An app screen with a line said over it: as long as the line, never shorter than usual.
            vo = audio_path(run_dir, n)
            if not vo.exists():
                raise StepError(f"shot {n} has a vo_line but {vo} is missing; run the voice step first")
            vo_len = probe_duration(vo)
            duration = max(app_screen_length(shot, asm), vo_len + pad)
            plan.append({"shot": shot, "n": n, "start": t, "duration": duration, "vo": vo, "vo_len": vo_len})
            t += duration
            continue
        if shot.get("card") or shot.get("app_screen") or shot.get("montage") or shot.get("flash"):
            # Time-jump card, app screen, flex montage or flash: fixed length, no voice.
            duration = float(asm["card_seconds"] if shot.get("card") else
                             app_screen_length(shot, asm) if shot.get("app_screen") else
                             asm["flash_seconds"] if shot.get("flash") else asm["montage_seconds"])
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
        if shot.get("stat") and not vo:
            duration = max(duration, float(asm["stat_seconds"]))    # long enough to read the number
        if shot.get("letter"):
            duration = max(duration, letter_seconds(shot, asm))
        plan.append({"shot": shot, "n": n, "start": t, "duration": duration, "vo": vo, "vo_len": vo_len})
        t += duration
    return plan


# --------------------------------------------------------------- per shot ----

def _fill_filter(w: int, h: int) -> str:
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"


def _push_in(src: Path, out: Path, frames: int, zoom_end: float, asm: dict, label: str,
             ease_out: bool = False, video: bool = False) -> None:
    """Centred zoom 1.00 -> zoom_end over `frames` frames, on a still or (video=True) on the
    first `frames` frames of a clip. ease_out makes it a punch: fast at first, then settling."""
    w, h, fps = int(asm["width"]), int(asm["height"]), int(asm["fps"])
    if ease_out:
        p = f"min(on/{max(1, frames - 1)},1)"
        z = f"1+({zoom_end:.4f}-1)*(1-pow(1-{p},2))"
    else:                                   # the original linear push-in, unchanged
        z = f"min(1+({zoom_end:.4f}-1)*on/{frames},{zoom_end:.4f})"
    # A still is one input frame held for `frames` outputs; a clip maps one frame to one.
    hold = 1 if video else frames
    prep = f"fps={fps}," if video else ""
    # Oversample first so zoompan's integer sampling does not jitter.
    vf = (f"{prep}{_fill_filter(w * 2, h * 2)},"
          f"zoompan=z='{z}':d={hold}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps},setsar=1")
    run_ffmpeg(["-i", str(src), "-vf", vf, "-frames:v", str(frames), "-an",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                str(out)], label)


def last_frame(clip: Path, out_png: Path, label: str) -> Path:
    run_ffmpeg(["-sseof", "-0.1", "-i", str(clip), "-frames:v", "1", "-update", "1", str(out_png)], label)
    return out_png


def compose_phone_mockup(screen: Path, background: Path | None, out: Path, w: int, h: int) -> Path:
    """The real screenshot inside a rounded phone frame, centred on a blurred, darkened
    background (the previous shot's last frame, or a plain dark fill if there is none)."""
    try:
        from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
    except ImportError:
        raise StepError("app_screen shots need Pillow: pip install -r requirements.txt") from None
    lanczos = Image.Resampling.LANCZOS

    if background is not None and background.exists():
        bg = Image.open(background).convert("RGB")
        scale = max(w / bg.width, h / bg.height)
        bg = bg.resize((math.ceil(bg.width * scale), math.ceil(bg.height * scale)), lanczos)
        left, top = (bg.width - w) // 2, (bg.height - h) // 2
        bg = bg.crop((left, top, left + w, top + h)).filter(ImageFilter.GaussianBlur(36))
        bg = ImageEnhance.Brightness(bg).enhance(0.55)
    else:
        bg = Image.new("RGB", (w, h), (12, 16, 26))

    shot = Image.open(screen).convert("RGB")
    sw = round(w * 0.62)
    sh = round(sw * shot.height / shot.width)
    if sh > h * 0.84:
        sh = round(h * 0.84)
        sw = round(sh * shot.width / shot.height)
    shot = shot.resize((sw, sh), lanczos)
    bezel = max(10, round(sw * 0.035))
    r_screen = round(sw * 0.12)
    r_body = r_screen + bezel
    bw, bh = sw + 2 * bezel, sh + 2 * bezel
    x0, y0 = (w - bw) // 2, (h - bh) // 2

    canvas = bg.convert("RGBA")
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([x0, y0 + 26, x0 + bw, y0 + bh + 26], r_body, fill=(0, 0, 0, 170))
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(30)))
    body = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(body).rounded_rectangle([x0, y0, x0 + bw - 1, y0 + bh - 1], r_body,
                                           fill=(20, 20, 24, 255), outline=(82, 84, 94, 255), width=3)
    canvas = Image.alpha_composite(canvas, body)
    mask = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, sw - 1, sh - 1], r_screen, fill=255)
    canvas.paste(shot, (x0 + bezel, y0 + bezel), mask)
    # Dynamic-island pill, centred at the top of the screen (the status bar keeps its sides).
    iw, ih = round(sw * 0.30), round(sw * 0.088)
    ix, iy = x0 + bezel + (sw - iw) // 2, y0 + bezel + round(sw * 0.028)
    ImageDraw.Draw(canvas).rounded_rectangle([ix, iy, ix + iw, iy + ih], ih // 2, fill=(0, 0, 0, 255))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out)
    return out


def _hex(color: str) -> tuple[int, int, int]:
    c = str(color).lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) if len(c) == 6 else (0, 0, 0)


def letter_font(asm: dict, size: int):
    from PIL import ImageFont
    rel = str(asm.get("letter_font_file") or "")
    path = Path(rel) if Path(rel).is_absolute() else ROOT / rel
    if not rel or not path.is_file():
        raise StepError(f"letter font {rel or '(assemble.letter_font_file not set)'} not found")
    font = ImageFont.truetype(str(path), size)
    try:
        font.set_variation_by_axes([int(asm.get("letter_weight", 500))])
    except (OSError, ValueError, AttributeError):
        pass                                  # a static font: use it as it is
    return font


def _wrap(text: str, font, width: int, draw) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def compose_letter(background: Path | None, paragraphs: list[str], out: Path, asm: dict) -> Path:
    """The letter so far, handwritten on a paper card over the shot's picture. The newest
    paragraph is the last one; when the card is full the oldest paragraphs scroll off the top."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
    w, h = int(asm["width"]), int(asm["height"])
    lanczos = Image.Resampling.LANCZOS
    if background is not None and background.exists():
        bg = Image.open(background).convert("RGB")
        scale = max(w / bg.width, h / bg.height)
        bg = bg.resize((math.ceil(bg.width * scale), math.ceil(bg.height * scale)), lanczos)
        left, top = (bg.width - w) // 2, (bg.height - h) // 2
        bg = bg.crop((left, top, left + w, top + h))
        blur = float(asm["letter_bg_blur"])
        if blur:
            bg = bg.filter(ImageFilter.GaussianBlur(blur))
        bg = ImageEnhance.Brightness(bg).enhance(float(asm["letter_bg_dim"]))
    else:
        bg = Image.new("RGB", (w, h), (24, 22, 28))

    card_w = round(w * float(asm["letter_width"]))
    pad = round(card_w * 0.09)
    max_card_h = round(h * 0.74)
    size = int(asm["letter_font_size"])
    probe = ImageDraw.Draw(bg)
    while True:
        font = letter_font(asm, size)
        line_h = round(size * 1.18)
        gap = 0                               # a new paragraph starts on the next ruled line
        blocks = [_wrap(p, font, card_w - 2 * pad, probe) for p in paragraphs]
        shown = list(blocks)
        def height(bs):
            return sum(len(b) * line_h for b in bs) + gap * max(0, len(bs) - 1) + 2 * pad
        while len(shown) > 1 and height(shown) > max_card_h:
            shown.pop(0)                      # scroll: drop the oldest paragraph
        if height(shown) <= max_card_h or size <= 34:
            break
        size -= 4                             # one very long paragraph: write smaller
    card_h = max(height(shown), round(h * 0.22))
    x0, y0 = (w - card_w) // 2, round((h - card_h) * 0.42)

    canvas = bg.convert("RGBA")
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([x0, y0 + 18, x0 + card_w, y0 + card_h + 18], 26,
                                             fill=(0, 0, 0, 150))
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(24)))
    paper = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(paper).rounded_rectangle([x0, y0, x0 + card_w, y0 + card_h], 22,
                                            fill=(*_hex(asm["letter_paper"]), 255))
    canvas = Image.alpha_composite(canvas, paper)
    # Faint ruled lines, like notepaper, each one under a line of handwriting (on its own layer,
    # so the paper stays opaque).
    rules = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rules)
    ascent = font.getmetrics()[0]
    yy = y0 + pad + ascent + round(size * 0.06)
    while yy < y0 + card_h - pad // 3:
        rd.line([(x0 + pad // 2, yy), (x0 + card_w - pad // 2, yy)], fill=(*_hex(asm["letter_rule"]), 90), width=2)
        yy += line_h
    canvas = Image.alpha_composite(canvas, rules)
    draw = ImageDraw.Draw(canvas)
    ink = (*_hex(asm["letter_ink"]), 255)
    y = y0 + pad
    for i, block in enumerate(shown):
        for line in block:
            draw.text((x0 + pad, y), line, font=font, fill=ink)
            y += line_h
        y += gap
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out)
    return out


def screen_window(compose, build: Path, n: int, size: tuple[int, int]):
    """Where the screen is in a phone picture, found by composing it twice: once with a black
    screenshot, once with a white one. Whatever differs is the screen (so a thumb over its edge,
    the rounded corners and the camera pill are all kept). `compose(picture, out)` makes the
    phone picture, or returns None.

    Returns (frame, box): `frame` is the phone picture as a PNG with the screen cut out, to lay
    over a recording; `box` is (left, top, width, height) of the screen, even-sized. None when
    there is no screen to find."""
    from PIL import Image, ImageChops
    made = []
    for name, color in (("k", (0, 0, 0)), ("w", (255, 255, 255))):
        src = build / f"app_{n:02d}_{name}_src.png"
        Image.new("RGB", size, color).save(src)
        out = compose(src, build / f"app_{n:02d}_{name}.png")
        if out is None:
            return None
        made.append(Image.open(out).convert("RGB"))
    dark, light = made
    mask = ImageChops.difference(light, dark).convert("L")
    solid = mask.point(lambda v: 255 if v > 24 else 0).getbbox()
    if solid is None:
        return None
    left, top, right, bottom = solid
    # Even sizes for the encoder; the frame covers anything the recording does not.
    right += (right - left) % 2
    bottom += (bottom - top) % 2
    frame = dark.convert("RGBA")
    frame.putalpha(ImageChops.invert(mask))
    path = build / f"app_{n:02d}_frame.png"
    frame.save(path)
    return path, (left, top, right - left, bottom - top)


def compose_app_clip(clip: Path, frame: Path, box: tuple[int, int, int, int], out: Path,
                     frames: int, asm: dict, label: str) -> Path:
    """The recording playing on the phone: scaled to cover the screen, under the phone picture.
    A recording shorter than the shot holds its last frame."""
    w, h, fps = int(asm["width"]), int(asm["height"]), int(asm["fps"])
    left, top, bw, bh = box
    seconds = frames / fps
    graph = (f"[0:v]fps={fps},scale={bw}:{bh}:force_original_aspect_ratio=increase:flags=lanczos,"
             f"crop={bw}:{bh},setsar=1,tpad=stop_mode=clone:stop_duration={seconds + 1:.2f}[scr];"
             f"color=c=black:s={w}x{h}:r={fps}[bg];"
             f"[bg][scr]overlay={left}:{top}[on];"
             f"[on][1:v]overlay=0:0,format=yuv420p[out]")
    run_ffmpeg(["-i", str(clip), "-loop", "1", "-framerate", str(fps), "-i", str(frame),
                "-filter_complex", graph, "-map", "[out]", "-frames:v", str(frames), "-an",
                "-c:v", "libx264", "-preset", "fast", "-crf", "14", "-pix_fmt", "yuv420p", str(out)], label)
    return out


def _video_size(path: Path) -> tuple[int, int]:
    from media import _probe
    try:
        w, h = _probe(path, "stream=width,height", stream="v:0").splitlines()[0].split(",")[:2]
        return int(w), int(h)
    except (ValueError, IndexError):
        raise StepError(f"could not read the size of {path}") from None


def app_screen_file(shot: dict) -> Path:
    rel = str(shot["app_screen"]).strip()
    path = Path(rel) if Path(rel).is_absolute() else ROOT / rel
    if not path.is_file():
        raise StepError(f"shot {shot['n']}: app_screen {rel} not found; add the screenshot or edit "
                        f"script.json")
    return path


def build_shot_clip(run_dir: Path, build: Path, item: dict, asm: dict,
                    background: Path | None = None) -> Path:
    n = item["n"]
    shot = item["shot"]
    w, h, fps = int(asm["width"]), int(asm["height"]), int(asm["fps"])
    duration = item["duration"]
    frames = max(1, math.ceil(duration * fps))
    out = build / f"shot_{n:02d}.mp4"
    keyframe = shot_path(run_dir, n)
    clip = video_path(run_dir, n)
    label = f"shot {n}"

    if shot.get("montage") or shot.get("flash"):
        # Flex montage: a quick punch-in on the keyframe (or the clip, if one was made), no motion
        # beyond that; the concat joins montage shots with hard cuts. A flash is the same thing,
        # shorter, and always the still.
        zoom = float(asm["flash_zoom_end"] if shot.get("flash") else asm["montage_zoom_end"])
        if shot.get("animate") and clip.exists() and not shot.get("flash"):
            _push_in(clip, out, frames, zoom, asm, label, ease_out=True, video=True)
            return out
        if not keyframe.exists():
            raise StepError(f"shot {n}: keyframe {keyframe} is missing; run the images step first")
        _push_in(keyframe, out, frames, zoom, asm, label, ease_out=True)
        return out

    if shot.get("app_screen"):
        # The real screenshot on a phone: in the hero's hand when the images step drew one
        # (phone_hand.py), else in a plain phone frame on the previous shot, blurred. Slight push-in.
        import phone_hand
        mock = None
        hand = phone_hand.run_path(run_dir)
        bg_png = None
        recording = app_clip_file(shot, asm)
        if recording is not None:
            # A recording plays on the same phone: find the screen, put the recording under it.
            found = None
            if hand.is_file():
                found = screen_window(lambda pic, to: phone_hand.compose(hand, pic, to, w, h), build, n, _video_size(recording))
                if found is None:
                    print(f"  shot {n}: the hand picture has no clean green screen; using the plain phone frame")
            if found is None:
                bg_png = last_frame(background, build / f"bg_{n:02d}.png", label) if background else None
                found = screen_window(lambda pic, to: compose_phone_mockup(pic, bg_png, to, w, h), build, n, _video_size(recording))
            if found is not None:
                raw = compose_app_clip(recording, found[0], found[1], build / f"app_{n:02d}_raw.mp4", frames, asm, label)
                _push_in(raw, out, frames, float(asm["app_screen_zoom_end"]), asm, label, video=True)
                return out
            print(f"  shot {n}: could not place the recording on the phone; showing the still")
        if hand.is_file():
            mock = phone_hand.compose(hand, app_screen_file(shot), build / f"app_{n:02d}.png", w, h)
            if mock is None:
                print(f"  shot {n}: the hand picture has no clean green screen; using the plain phone frame")
        if mock is None:
            bg_png = last_frame(background, build / f"bg_{n:02d}.png", label) if background else None
            mock = compose_phone_mockup(app_screen_file(shot), bg_png, build / f"app_{n:02d}.png", w, h)
        _push_in(mock, out, frames, float(asm["app_screen_zoom_end"]), asm, label)
        return out

    if shot.get("card"):
        # Plain black frames; the card text is drawn by the caption pass with its own fade.
        run_ffmpeg(["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}",
                    "-frames:v", str(frames), "-an", "-vf", "setsar=1",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                    str(out)], label)
        return out

    if item.get("letter_page"):
        # The letter so far on its paper card, with a gentle push-in.
        _push_in(item["letter_page"], out, frames, float(asm["letter_zoom_end"]), asm, label)
        return out

    if (shot.get("animate") or shot.get("talk")) and clip.exists():
        # Trim to length; if the clip is shorter than the VO, hold its last frame. A talking clip
        # is as long as its voice line and starts with it, so its lips stay in sync.
        vf = (f"{_fill_filter(w, h)},fps={fps},"
              f"tpad=stop_mode=clone:stop_duration={duration + 1:.3f},setsar=1")
        run_ffmpeg(["-i", str(clip), "-t", f"{duration:.3f}", "-vf", vf, "-an",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                    str(out)], label)
        return out

    if shot.get("talk"):
        print(f"  shot {n}: talk is true but {clip.name} is missing; using a push-in on the keyframe "
              f"(run the video step for a lip-synced clip)")
    elif shot.get("animate"):
        print(f"  shot {n}: animate is true but {clip.name} is missing; using a push-in on the keyframe")
    if not keyframe.exists():
        raise StepError(f"shot {n}: keyframe {keyframe} is missing; run the images step first")

    _push_in(keyframe, out, frames, float(asm["zoom_end"]), asm, label)
    return out


# --------------------------------------------------------------- captions ----

FONTS_SUBDIR = "fonts"   # inside the build dir; libass loads caption fonts from here


def caption_font_file(asm: dict) -> Path | None:
    """The bundled caption font (assemble.caption_font_file), or None if it is not there."""
    rel = str(asm.get("caption_font_file") or "").strip()
    if not rel:
        return None
    path = Path(rel) if Path(rel).is_absolute() else ROOT / rel
    return path if path.is_file() else None


def font_names(path: Path) -> dict[int, str]:
    """Strings from a TrueType/OpenType 'name' table (1 = family, 4 = full name)."""
    data = path.read_bytes()
    try:
        num_tables = struct.unpack(">H", data[4:6])[0]
        for i in range(num_tables):
            tag, _, offset, _ = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
            if tag != b"name":
                continue
            _, count, str_off = struct.unpack(">HHH", data[offset:offset + 6])
            names: dict[int, str] = {}
            for j in range(count):
                pid, _, lid, nid, length, off = struct.unpack(
                    ">HHHHHH", data[offset + 6 + 12 * j: offset + 18 + 12 * j])
                raw = data[offset + str_off + off: offset + str_off + off + length]
                if pid == 3 and lid == 0x409:          # Windows, English (preferred)
                    names[nid] = raw.decode("utf-16-be", "replace")
                elif pid == 1 and nid not in names:    # Macintosh, as a fallback
                    names[nid] = raw.decode("mac_roman", "replace")
            return names
    except struct.error:
        pass
    return {}


def _fc_families() -> set[str]:
    if shutil.which("fc-list") is None:
        return set()
    proc = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    fams: set[str] = set()
    for line in proc.stdout.splitlines():
        for fam in line.split(","):
            fams.add(fam.strip().lower())
    return fams


def pick_caption_font(asm: dict, build: Path | None = None) -> str:
    """The font name for the .ass style. With the bundled font file (the normal case, and the
    only one that works on Windows) the file is copied into build/fonts for libass and its own
    full name is used. Otherwise fall back to a system font by name."""
    bundled = caption_font_file(asm)
    if bundled is not None:
        names = font_names(bundled)
        name = names.get(4) or names.get(1)
        if name:
            if build is not None:
                (build / FONTS_SUBDIR).mkdir(parents=True, exist_ok=True)
                shutil.copyfile(bundled, build / FONTS_SUBDIR / bundled.name)
            return name
        print(f"  captions: could not read the font name in {bundled.name}; using a system font")
    elif asm.get("caption_font_file"):
        print(f"  captions: {asm['caption_font_file']} not found; using a system font")
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


# Caption chunking and pop-in come from the format (assemble.caption_max_words / _pop_*);
# these are only the defaults for callers that pass none.
MAX_CHUNK_WORDS = 2
_BREAK_AFTER = tuple(".,!?;:\u2014\u2013")   # a chunk always ends after a word ending in these
_QUOTES = "\"'\u201c\u201d\u2018\u2019()[]"
_DROP_TRAILING = ".,;:\u2014\u2013-"       # dropped from display; ! and ? are kept for tone


def _display(word: str) -> str:
    """Caption text for one spoken token: all caps, wrapping quotes and soft punctuation removed."""
    text = word.strip().strip(_QUOTES).rstrip(_DROP_TRAILING).strip(_QUOTES)
    return text.upper()


def _ends_clause(word: str) -> bool:
    return word.strip().rstrip(_QUOTES).endswith(_BREAK_AFTER)


def chunk_words(words: list[dict], max_words: int = MAX_CHUNK_WORDS) -> list[dict]:
    """Group timed words into chunks of at most max_words, breaking after punctuation.

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
        if len(cur) >= max_words or _ends_clause(w["word"]):
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


def shot_caption_events(run_dir: Path, item: dict, max_words: int = MAX_CHUNK_WORDS,
                        spoken: bool = True) -> list[tuple[float, float, str]]:
    """(start, end, text) in seconds on the final timeline for one shot's captions.

    Spoken shot: every word, in chunks synced to the voice timing; each chunk holds until the
    next one starts, the last until the shot ends. Silent shot: the caption field for the whole
    shot (nothing if it is empty). spoken=False (the "off" caption style) leaves out the
    word-by-word captions and keeps the rest."""
    shot_start = item["start"]
    shot_end = item["start"] + item["duration"]
    if item["shot"].get("card") or item["shot"].get("montage") or item["shot"].get("flash"):
        return []
    if item["shot"].get("app_screen") and item.get("vo") is None:
        return []
    if item["shot"].get("letter"):
        # The letter is the text on screen; only a CTA caption goes on top.
        caption = (item["shot"].get("caption") or "").strip().upper()
        return [(shot_start, shot_end, caption)] if caption else []
    if item.get("sung"):
        tp = timing_path(run_dir, item["n"])
        words = read_json(tp).get("words", []) if tp.exists() else []
        if not words:
            caption = (item["shot"].get("caption") or "").strip().upper()
            return [(shot_start, shot_end, caption)] if caption else []
        item = {**item, "vo": tp}
    elif item["vo"] is None:
        caption = (item["shot"].get("caption") or "").strip().upper()
        return [(shot_start, shot_end, caption)] if caption else []

    if not spoken:
        # No word-by-word captions: a spoken shot shows only its own caption (the closing one).
        caption = (item["shot"].get("caption") or "").strip().upper()
        return [(shot_start, shot_end, caption)] if caption else []
    tp = timing_path(run_dir, item["n"])
    words = read_json(tp).get("words", []) if tp.exists() else []
    if not words:
        print(f"  shot {item['n']}: no word timings in {tp.name}; spreading the words evenly over the VO")
        words = _spread_words(item["shot"]["vo_line"], item["vo_len"])

    chunks = chunk_words(words, max_words)
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


def _ass_bgr(color: str) -> str:
    """#RRGGBB -> &HBBGGRR& (an inline ASS colour override)."""
    r, g, b = _hex(color)
    return f"&H{b:02X}{g:02X}{r:02X}&"


def _ass_color(color: str) -> str:
    """#RRGGBB -> &H00BBGGRR (an ASS style colour); ASS colours pass through."""
    if str(color).startswith("&H"):
        return str(color)
    r, g, b = _hex(color)
    return f"&H00{b:02X}{g:02X}{r:02X}"


def stat_font(asm: dict, build: Path | None, fallback: str) -> str:
    """The font for the progress overlay: the bundled upright heavy face, copied next to the
    caption font for libass; the caption font when that file is missing."""
    rel = str(asm.get("stat_font_file") or "").strip()
    path = (Path(rel) if Path(rel).is_absolute() else ROOT / rel) if rel else None
    if path is None or not path.is_file():
        return fallback
    names = font_names(path)
    name = names.get(4) or names.get(1)
    if not name:
        return fallback
    if build is not None:
        (build / FONTS_SUBDIR).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, build / FONTS_SUBDIR / path.name)
    return name


def stat_events(item: dict, asm: dict, w: int, h: int) -> list[str]:
    """The .ass lines for one shot's progress overlay ("stat"): the rank on a dark card top left
    with a small heading over it, and lower left a big number with what it counts. The number
    starts one lower and ticks up partway through the shot (sfx.STAT_TICK_AT), with a small pop."""
    stat = item["shot"].get("stat")
    if not isinstance(stat, dict):
        return []
    import sfx
    start, end = item["start"], item["start"] + item["duration"]
    x = int(round(w * float(asm["stat_x"])))
    ry = int(round(h * float(asm["stat_rank_y"])))
    ny = int(round(h * float(asm["stat_y"])))
    pad = max(8, int(asm["stat_rank_size"]) // 3)
    fade = "\\fad(120,0)"
    t0, t1 = _ass_time(start), _ass_time(end)
    out = []
    heading = str(asm.get("stat_eyebrow") or "").strip().upper()
    if heading:
        out.append(f"Dialogue: 2,{t0},{t1},StatHead,,0,0,0,,{{\\an1\\pos({x + pad},{ry - pad - 6}){fade}}}{_ass_escape(heading)}")
    out.append(f"Dialogue: 2,{t0},{t1},StatRank,,0,0,0,,{{\\an7\\pos({x + pad},{ry}){fade}}}{_ass_escape(str(stat.get('rank') or ''))}")
    value = int(stat.get("value") or 0)
    unit = _ass_escape(str(stat.get("unit") or ""))
    big, small = int(asm["stat_size"]), int(asm["stat_unit_size"])

    def number(v: int, tags: str) -> str:
        return f"{{\\an1\\pos({x},{ny}){tags}}}{{\\fs{big}}}{v:,}{{\\fs{small}}} {unit}"

    if asm.get("stat_tick", True) and value > 0 and end - start > 0.6:
        mid = start + (end - start) * sfx.STAT_TICK_AT
        out.append(f"Dialogue: 2,{t0},{_ass_time(mid)},StatNum,,0,0,0,,{number(value - 1, fade)}")
        pop = "\\fscx116\\fscy116\\t(0,140,\\fscx100\\fscy100)"
        out.append(f"Dialogue: 2,{_ass_time(mid)},{t1},StatNum,,0,0,0,,{number(value, pop)}")
    else:
        out.append(f"Dialogue: 2,{t0},{t1},StatNum,,0,0,0,,{number(value, fade)}")
    return out


def ass_head(asm: dict, font: str, w: int, h: int, stat_face: str | None = None) -> list[str]:
    """The .ass file up to the [Events] header: the Caption and Label styles for these settings."""
    size = int(asm["caption_size"])
    fill, outline_color = _ass_color(asm["caption_fill"]), _ass_color(asm["caption_outline_color"])
    outline = int(asm["caption_outline"])
    bold = -1 if asm.get("caption_bold", True) else 0
    italic = -1 if asm.get("caption_italic", True) else 0
    box = bool(asm.get("caption_box"))
    shadow = 0 if box else int(asm.get("caption_shadow", 0))
    back = _ass_color(asm.get("caption_shadow_color") or "&H00000000")
    spacing = int(asm.get("caption_spacing", 0))
    return [
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
        # Fill, outline and shadow colours are &HAABBGGRR. BorderStyle 1 = outline plus drop
        # shadow (an outline with a blur is a soft glow); 3 = the text sits on an opaque box in
        # the outline colour, and the outline width is the padding.
        f"Style: Caption,{font},{size},{fill},{fill},{outline_color},{back},"
        f"{bold},{italic},0,0,100,100,{spacing},0,{3 if box else 1},{outline},{shadow},5,40,40,0,1",
        # On-screen labels (shot "label"): bold text on an opaque box, top-centred.
        f"Style: Label,{font},{int(asm['label_size'])},{_ass_color(asm['label_text'])},"
        f"{_ass_color(asm['label_text'])},{_ass_color(asm['label_box'])},&H00000000,"
        f"-1,-1,0,0,100,100,1,0,3,{max(6, int(asm['label_size']) // 4)},0,8,40,40,0,1",
        # Progress overlay (shot "stat"): a big number, the rank on a dark see-through card, and
        # a small heading. Upright heavy face, white, with a soft dark edge so it reads on any shot.
        f"Style: StatNum,{stat_face or font},{int(asm.get('stat_size', 190))},&H00FFFFFF,&H00FFFFFF,&H30000000,&H70000000,"
        f"-1,0,0,0,100,100,0,0,1,5,5,1,40,40,0,1",
        f"Style: StatRank,{stat_face or font},{int(asm.get('stat_rank_size', 54))},&H00FFFFFF,&H00FFFFFF,"
        f"&H38{_ass_color(asm.get('stat_box', '#101522'))[4:]},&H00000000,"
        f"-1,0,0,0,100,100,1,0,3,{max(8, int(asm.get('stat_rank_size', 54)) // 3)},0,7,40,40,0,1",
        f"Style: StatHead,{stat_face or font},{max(18, int(asm.get('stat_rank_size', 54)) // 2)},&H10FFFFFF,&H10FFFFFF,&H40000000,&H70000000,"
        f"-1,0,0,0,100,100,3,0,1,3,2,1,40,40,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]


def caption_pop(asm: dict) -> str:
    """Inline tags for the pop-in: start at pop_from% scale, grow to 100% over the first pop_ms."""
    pop_from, pop_ms = int(asm["caption_pop_from"]), int(asm["caption_pop_ms"])
    return f"\\fscx{pop_from}\\fscy{pop_from}\\t(0,{pop_ms},\\fscx100\\fscy100)"


def write_captions(run_dir: Path, build: Path, plan: list[dict], asm: dict) -> tuple[Path, int]:
    w, h = int(asm["width"]), int(asm["height"])
    font = pick_caption_font(asm, build)
    cy = int(round(h * float(asm["caption_y"])))
    blur = int(asm["caption_blur"])
    max_words = int(asm["caption_max_words"])
    spoken = asm.get("caption_style") != "off"
    lines = ass_head(asm, font, w, h, stat_face=stat_font(asm, build, font))
    wrap = str(asm.get("label_wrap") or "")
    pop = caption_pop(asm)
    # Time-jump cards: same style, centred on the black frame, a quick fade in and out, no pop.
    fade = int(asm["card_fade_ms"])
    count = 0
    for item in plan:
        card = card_event(item)
        if card is not None:
            start, end, text = card
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,"
                         f"{{\\an5\\pos({w // 2},{h // 2})\\blur{blur}\\fad({fade},{fade})}}{_ass_escape(text)}")
            count += 1
            continue
        tag = str(item["shot"].get("label") or "").strip().upper()
        if tag:
            colors = {str(k).upper(): v for k, v in (asm.get("label_colors") or {}).items()}
            box = f"\\3c{_ass_bgr(colors[tag])}" if tag in colors else ""
            ly = int(round(h * float(asm["label_y"])))
            lines.append(f"Dialogue: 1,{_ass_time(item['start'])},{_ass_time(item['start'] + item['duration'])},"
                         f"Label,,0,0,0,,{{\\an8\\pos({w // 2},{ly}){box}}}{_ass_escape(wrap + tag + wrap)}")
        lines.extend(stat_events(item, asm, w, h))
        for start, end, text in shot_caption_events(run_dir, item, max_words, spoken=spoken):
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,"
                         f"{{\\an5\\pos({w // 2},{cy})\\blur{blur}{pop}}}{_ass_escape(text)}")
            count += 1
    path = build / "captions.ass"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, count


# ------------------------------------------------------------------- mix ----

def _encode_watch(label: str, total: float, quiet: bool = False):
    """Progress for a long encode: the bar's note ("final mix 40%") and a log line each quarter.
    `quiet`: the note only, for a pass that takes seconds."""
    import progress
    last = [-1]

    def on(seconds: float) -> None:
        pct = max(0, min(100, int(seconds / total * 100))) if total > 0 else 0
        progress.note(f"{label} {pct}%")
        if not quiet and pct // 25 > last[0]:
            last[0] = pct // 25
            print(f"  {label}: {pct}%")
    return on


def mix_sound(build: Path, plan: list[dict], total: float, config: dict,
              sfx_track: Path | None = None) -> Path:
    """build/mix.wav: every voice line at its shot's start, the music bed or the song, and the
    sound effects, exactly as long as the cut. Sound only: no picture is read here."""
    asm = config["assemble"]
    out = build / "mix.wav"
    args: list[str] = []
    vo_items = [it for it in plan if it["vo"] is not None]
    for it in vo_items:
        args += ["-i", str(it["vo"])]
    song = song_file(build.parent) if any(it.get("sung") for it in plan) else None
    music = "" if song else (config.get("music_path") or "")
    music_file = (ROOT / music) if music else None
    if music_file and not music_file.exists():
        print(f"  music: {music} not found, skipping the music bed")
        music_file = None
    if music_file:
        args += ["-stream_loop", "-1", "-i", str(music_file)]
    if song:
        args += ["-i", str(song)]
    if sfx_track:
        args += ["-i", str(sfx_track)]

    # VO clips at their shot start times, optional music bed, padded to the cut length.
    parts: list[str] = []
    labels: list[str] = []
    for i, it in enumerate(vo_items):
        ms = int(round(it["start"] * 1000))
        parts.append(f"[{i}:a]aresample=44100,adelay={ms}:all=1[vo{i}]")
        labels.append(f"[vo{i}]")
    if music_file:
        mi = len(vo_items)
        parts.append(f"[{mi}:a]aresample=44100,volume={float(asm['music_volume']):.3f},"
                     f"atrim=0:{total:.3f}[mu]")
        labels.append("[mu]")
    if song:
        si = len(vo_items)
        fade = min(1.2, total / 4)
        parts.append(f"[{si}:a]aresample=44100,atrim=0:{total:.3f},"
                     f"afade=t=out:st={max(0.0, total - fade):.3f}:d={fade:.3f}[song]")
        labels.append("[song]")
    if sfx_track:
        # Already at its own level and as long as the cut (sfx.py); it goes in as it is.
        xi = len(vo_items) + (1 if (music_file or song) else 0)
        parts.append(f"[{xi}:a]aresample=44100[sfx]")
        labels.append("[sfx]")
    if labels:
        if len(labels) == 1:
            parts.append(f"{labels[0]}apad,atrim=0:{total:.3f}[a]")
        else:
            parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,"
                         f"apad,atrim=0:{total:.3f}[a]")
    else:
        parts.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{total:.3f}[a]")
    run_ffmpeg([*args, "-filter_complex", ";".join(parts), "-map", "[a]", "-t", f"{total:.3f}",
                "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", out.name], "sound mix", cwd=build,
               on_progress=_encode_watch("sound mix", total, quiet=True))
    return out


def burn_captions(build: Path, cut: Path, total: float, asm: dict) -> Path:
    """build/main_video.mp4: the cut with the captions burned in and the format's grade
    (pixar_arc: desaturate + a slight cool tint). Picture only: no sound is read here."""
    w, h, fps = int(asm["width"]), int(asm["height"]), int(asm["fps"])
    out = build / "main_video.mp4"
    sat = float(asm["saturation"])
    # Relative paths only (cwd is the build dir), so no Windows drive-letter colon ever
    # reaches the filter graph.
    fonts = f":fontsdir={FONTS_SUBDIR}" if (build / FONTS_SUBDIR).is_dir() else ""
    cb = str(asm.get("colorbalance") or "").strip()
    tint = f"colorbalance={cb}," if cb else ""
    run_ffmpeg(["-i", cut.name, "-vf", f"ass=captions.ass{fonts},eq=saturation={sat:.3f},{tint}format=yuv420p",
                "-an", "-t", f"{total:.3f}", "-r", str(fps), "-s", f"{w}x{h}",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", out.name],
               "final mix (captions and picture)", cwd=build, on_progress=_encode_watch("final mix", total))
    return out


def render_main(build: Path, cut: Path, captions: Path, plan: list[dict], total: float,
                config: dict, sfx_track: Path | None = None) -> Path:
    """build/main.mp4, in three plain passes: the sound alone, the picture alone, then the two
    joined without encoding the picture again.

    It used to be one ffmpeg command reading the cut and every voice file at once (twenty
    inputs into one filter graph). On some Windows ffmpeg builds that command stopped part of
    the way through and never finished. Each pass now does one thing, so there is nothing to
    wait on between picture and sound, and a pass that does stop names itself."""
    asm = config["assemble"]
    out = build / "main.mp4"
    sound = mix_sound(build, plan, total, config, sfx_track)
    picture = burn_captions(build, cut, total, asm)
    run_ffmpeg(["-i", picture.name, "-i", sound.name, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", "-t", f"{total:.3f}",
                "-movflags", "+faststart", out.name], "final mix (joining picture and sound)", cwd=build)
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
    print(f"[assemble] outro: adding {outro} ({outro_len:.1f}s); the whole video is encoded once more")
    run_ffmpeg(["-i", str(main), *audio_in, "-filter_complex",
                f"{vf};{outro_audio}aresample=44100,aformat=channel_layouts=stereo,"
                f"atrim=0:{outro_len:.3f}[oa];"
                f"[0:v][0:a][ov][oa]concat=n=2:v=1:a=1[v][a]",
                "-map", "[v]", "-map", "[a]", "-r", str(fps),
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-movflags", "+faststart", str(out)],
               "outro", cwd=build, on_progress=_encode_watch("outro", probe_duration(main) + outro_len))
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
    clips = sum(1 for s in script["shots"] if video_path(run_dir, s["n"]).exists() and not s.get("talk"))
    talk_secs = 0.0
    talk_clips = 0
    chars = 0
    for s in script["shots"]:
        tp = timing_path(run_dir, s["n"])
        timing = read_json(tp) if tp.exists() else {}
        chars += int(timing.get("characters", 0))
        if s.get("talk") and video_path(run_dir, s["n"]).exists():
            talk_clips += 1
            talk_secs += float(timing.get("duration") or 0.0)
    rows = [
        (f"images ({keyframes} keyframes + {sheets} sheets)", (keyframes + sheets) * float(fal["image_cost"])),
        (f"video ({clips} clips x {fal['video_seconds']}s)", clips * float(fal["video_seconds"]) * float(fal["video_cost_per_second"])),
    ]
    if talk_clips:
        rows.append((f"talking ({talk_clips} clips, {talk_secs:.0f}s)", talk_secs * float(fal["avatar_cost_per_second"])))
    from steps.song import song_plan
    info = song_plan(run_dir)
    if info:
        secs = float(info.get("seconds") or 0.0)
        rows.append((f"song ({secs:.0f}s)", secs / 60 * float(config["elevenlabs"]["music_cost_per_minute"])))
    else:
        rows.append((f"voice ({chars} chars)", chars / 1000 * float(config["elevenlabs"]["cost_per_1k_chars"])))
    return rows


# ------------------------------------------------------------------- run ----

def song_file(run_dir: Path) -> Path | None:
    from steps.song import song_path
    p = song_path(run_dir)
    return p if p.exists() else None


def letter_pages(run_dir: Path, build: Path, plan: list[dict], asm: dict) -> None:
    """Draw the page for every letter shot: the letter so far over the latest background."""
    paragraphs: list[str] = []
    background: Path | None = None
    for it in plan:
        shot = it["shot"]
        if not shot.get("letter"):
            continue
        own = shot_path(run_dir, it["n"])
        if str(shot.get("image_prompt") or "").strip():
            if not own.exists():
                raise StepError(f"shot {it['n']}: keyframe {own} is missing; run the images step first")
            background = own
        paragraphs.append(shot["letter"])
        it["letter_page"] = compose_letter(background, paragraphs, build / f"letter_{it['n']:02d}.png", asm)

def run(run_dir: Path, config: dict) -> None:
    require_ffmpeg()
    script = read_script(run_dir)
    import caption_styles
    style = caption_styles.for_run(run_dir, config)
    asm = caption_styles.apply(config["assemble"], style)
    config = {**config, "assemble": asm}
    build = run_dir / "build"
    build.mkdir(parents=True, exist_ok=True)

    from steps.song import is_song
    plan = shot_durations(run_dir, script, asm, song=is_song(config))
    total = sum(it["duration"] for it in plan)
    letter_pages(run_dir, build, plan, asm)
    print(f"[assemble] {len(plan)} shots, {total:.1f}s at {asm['width']}x{asm['height']} {asm['fps']}fps")

    import progress
    progress.plan(len(plan) + 2)      # every shot's clip, then the final mix, then the outro
    clips = []
    scene_clip: Path | None = None   # last real scene, the blurred background for app screens
    for it in plan:
        if it["shot"].get("flash"):
            kind = "flash"
        elif it["shot"].get("montage"):
            kind = "montage punch-in"
        elif it["shot"].get("app_screen"):
            kind = f"app screen {it['shot']['app_screen']}" + (" (recording)" if app_clip_file(it["shot"], asm) else "")
        elif it["shot"].get("card"):
            kind = f"card \"{it['shot']['card']}\""
        elif it.get("letter_page"):
            kind = "letter"
        elif it["shot"].get("talk"):
            kind = "talking clip" if video_path(run_dir, it["n"]).exists() else "push-in (no talking clip)"
        else:
            kind = "clip" if (it["shot"].get("animate") and video_path(run_dir, it["n"]).exists()) else "push-in"
        print(f"  shot {it['n']}: {kind} {it['duration']:.2f}s" + (f" (VO {it['vo_len']:.2f}s)" if it["vo"] else ""))
        clip = build_shot_clip(run_dir, build, it, asm, background=scene_clip)
        progress.tick()
        if not (it["shot"].get("card") or it["shot"].get("app_screen")):
            scene_clip = clip
        clips.append(clip)

    concat_list = build / "concat.txt"
    concat_list.write_text("".join(f"file '{c.name}'\n" for c in clips), encoding="utf-8")
    cut = build / "cut.mp4"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", cut.name],
               "concat", cwd=build)

    captions, n_caps = write_captions(run_dir, build, plan, asm)
    look = "" if style == caption_styles.FORMAT else f" ({caption_styles.title(style)} style)"
    print(f"[assemble] {n_caps} caption(s){look} -> {captions.relative_to(run_dir)}")

    import sfx
    sfx_track = None
    if not is_song(config):
        try:
            sfx_track = sfx.render_track(build, plan, total, config)
        except StepError as e:      # effects are an extra: the video is still made without them
            print(f"  sound effects: left out of this cut ({e})")
    print(f"[assemble] final mix: {total:.1f}s of video. Sound first (seconds), then captions onto the "
          f"picture (the slowest part: minutes on an older computer), then the two are joined  [{ffmpeg_version()}]")
    main = render_main(build, cut, captions, plan, total, config, sfx_track=sfx_track)
    progress.note("")
    progress.tick()
    final_src = append_outro(build, main, config)
    progress.note("")
    final = run_dir / "final.mp4"
    shutil.copyfile(final_src, final)

    print(f"\n[assemble] final: {final}  ({probe_duration(final):.1f}s)")
    rows = cost_report(run_dir, script, config)
    print("[assemble] estimated cost:")
    for name, usd in rows:
        print(f"  {name:<40} ${usd:.2f}")
    print(f"  {'total':<40} ${sum(u for _, u in rows):.2f}")
