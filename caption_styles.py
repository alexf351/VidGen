"""Caption looks you can pick per video.

A format sets its own captions (font, size, position, colours) in its format.yaml. A caption
style swaps the look (font, colours, outline, shadow) and keeps the format's size, position and
words-per-caption, so any style works with any format.

    python main.py new "..." --captions yellow_pop
    python main.py captions <run_id> headline        then:  python main.py step <run_id> assemble

The choice is saved in the run's run.json ("captions"). "format" means the format's own look.
`assemble.caption_style` in config.local.yaml sets the style for every new video. Changing the
style of a finished video only needs the assemble step again, which costs nothing.

Fonts are bundled in assets/fonts (all SIL Open Font License).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from common import ROOT, StepError

FORMAT = "format"          # the format's own captions
OFF = "off"                # no spoken-word captions (cards and the closing caption stay)

_BLACK = "&H00000000"
_WHITE = "&H00FFFFFF"
_POPPINS = {"caption_font": "Poppins Black", "caption_font_file": "assets/fonts/Poppins-Black.ttf",
            "caption_fallback_font": "Arial Black", "caption_italic": False, "caption_bold": True}

# Each style: the assemble.caption_* values it sets, and `size`, a multiplier on the format's
# caption size (narrow fonts read smaller at the same point size).
STYLES: list[dict] = [
    {"id": "classic", "title": "Classic", "note": "Bold white with a soft shadow", "size": 1.0,
     "set": {**_POPPINS, "caption_fill": _WHITE, "caption_outline_color": _BLACK,
             "caption_outline": 2, "caption_blur": 3, "caption_shadow": 5,
             "caption_shadow_color": "&H50000000", "caption_box": False}},
    {"id": "outline", "title": "Outline", "note": "Bold white with a thick black edge", "size": 1.0,
     "set": {**_POPPINS, "caption_fill": _WHITE, "caption_outline_color": _BLACK,
             "caption_outline": 6, "caption_blur": 0, "caption_shadow": 0,
             "caption_shadow_color": _BLACK, "caption_box": False}},
    {"id": "yellow_pop", "title": "Yellow Pop", "note": "Yellow with a black edge and a bigger pop",
     "size": 1.05,
     "set": {**_POPPINS, "caption_fill": "&H0000E6FF", "caption_outline_color": _BLACK,
             "caption_outline": 6, "caption_blur": 0, "caption_shadow": 4,
             "caption_shadow_color": _BLACK, "caption_box": False,
             "caption_pop_from": 70, "caption_pop_ms": 110}},
    {"id": "comic", "title": "Comic", "note": "Comic-book lettering with a hard shadow", "size": 1.15,
     "set": {"caption_font": "Bangers", "caption_font_file": "assets/fonts/Bangers-Regular.ttf",
             "caption_fallback_font": "Impact", "caption_italic": False, "caption_bold": False,
             "caption_fill": _WHITE, "caption_outline_color": _BLACK, "caption_outline": 6,
             "caption_blur": 0, "caption_shadow": 7, "caption_shadow_color": _BLACK,
             "caption_box": False, "caption_spacing": 2}},
    {"id": "headline", "title": "Headline", "note": "Tall condensed capitals", "size": 1.2,
     "set": {"caption_font": "Anton", "caption_font_file": "assets/fonts/Anton-Regular.ttf",
             "caption_fallback_font": "Impact", "caption_italic": False, "caption_bold": False,
             "caption_fill": _WHITE, "caption_outline_color": _BLACK, "caption_outline": 5,
             "caption_blur": 0, "caption_shadow": 3, "caption_shadow_color": _BLACK,
             "caption_box": False, "caption_spacing": 1}},
    {"id": "banner", "title": "Banner", "note": "White text on a black bar", "size": 0.8,
     "set": {**_POPPINS, "caption_fill": _WHITE, "caption_outline_color": _BLACK,
             "caption_outline": 18, "caption_blur": 0, "caption_shadow": 0,
             "caption_shadow_color": _BLACK, "caption_box": True}},
]
_BY_ID = {s["id"]: s for s in STYLES}

# The look keys a format's own captions may leave unset (older formats): the look VidGen
# always had, bold italic with no shadow.
LOOK_DEFAULTS = {"caption_italic": True, "caption_bold": True, "caption_shadow": 0,
                 "caption_shadow_color": _BLACK, "caption_box": False, "caption_spacing": 0}


def ids() -> list[str]:
    return [FORMAT, *(_s["id"] for _s in STYLES), OFF]


def check(style: str | None) -> str:
    """A valid style id ("" and None mean the format's own)."""
    value = str(style or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not value:
        return FORMAT
    if value not in ids():
        raise StepError(f"unknown caption style {style!r}; choose one of: {', '.join(ids())}")
    return value


def catalog() -> list[dict]:
    """For the UI: every choice, in the order shown."""
    return ([{"id": FORMAT, "title": "Format's own", "note": "The look this format was designed with"}]
            + [{"id": s["id"], "title": s["title"], "note": s["note"]} for s in STYLES]
            + [{"id": OFF, "title": "Off", "note": "No word-by-word captions"}])


def title(style: str) -> str:
    return next((c["title"] for c in catalog() if c["id"] == style), style)


def apply(asm: dict, style: str | None) -> dict:
    """assemble settings with a caption style applied (a copy; `asm` is not changed)."""
    style = check(style)
    out = {**LOOK_DEFAULTS, **asm, "caption_style": style}
    if style in (FORMAT, OFF):
        return out
    preset = _BY_ID[style]
    out.update(preset["set"])
    out["caption_size"] = max(12, int(round(float(asm["caption_size"]) * float(preset["size"]))))
    return out


# ------------------------------------------------------------------ the run ----

def for_run(run_dir: Path, config: dict) -> str:
    """The style a run uses: its own choice (run.json "captions"), else assemble.caption_style
    from config, else the format's own. An unknown saved value falls back to the format's own."""
    from common import read_json
    saved = None
    try:
        if (Path(run_dir) / "run.json").is_file():
            saved = read_json(Path(run_dir) / "run.json").get("captions")
    except (OSError, ValueError, AttributeError):
        saved = None
    for value in (saved, (config.get("assemble") or {}).get("caption_style")):
        if value:
            try:
                return check(value)
            except StepError:
                continue
    return FORMAT


def set_for_run(run_dir: Path, style: str | None) -> str:
    """Save a run's caption style in run.json. Returns the saved id."""
    from common import read_json, write_json
    style = check(style)
    path = Path(run_dir) / "run.json"
    meta = read_json(path) if path.is_file() else {"run_id": Path(run_dir).name}
    meta["captions"] = style
    write_json(path, meta)
    return style


# ------------------------------------------------------------------ previews ----

PREVIEW_TEXT = "LOCK IN"
PREVIEW_SIZE = (360, 150)


def preview(config: dict, style: str) -> Path:
    """A small picture of the sample caption in this style, as the assemble step would draw it
    for this format. Rendered once with ffmpeg and kept in cache/caption_previews/."""
    from media import require_ffmpeg, run_ffmpeg
    from steps.assemble import FONTS_SUBDIR, ass_head, pick_caption_font

    style = check(style)
    asm = apply(config["assemble"], FORMAT if style == OFF else style)
    look = {k: asm[k] for k in sorted(asm) if k.startswith("caption_")}
    key = hashlib.sha1(json.dumps([look, asm["width"], PREVIEW_TEXT, PREVIEW_SIZE, 4],
                                  sort_keys=True, default=str).encode()).hexdigest()[:16]
    folder = ROOT / "cache" / "caption_previews"
    out = folder / f"{key}.png"
    if out.is_file():
        return out
    require_ffmpeg()
    work = folder / f"work-{key}"
    try:
        work.mkdir(parents=True, exist_ok=True)
        w = int(asm["width"])
        pw, ph = PREVIEW_SIZE
        cw = int(w * 0.56) // 2 * 2                 # the middle of the frame, so the text reads large
        h = int(round(cw * ph / pw)) // 2 * 2
        font = pick_caption_font(asm, work)
        lines = ass_head(asm, font, w, h)
        lines.append(f"Dialogue: 0,0:00:00.00,0:00:05.00,Caption,,0,0,0,,"
                     f"{{\\an5\\pos({w // 2},{h // 2})\\blur{int(asm['caption_blur'])}}}{PREVIEW_TEXT}")
        (work / "preview.ass").write_text("\n".join(lines) + "\n", encoding="utf-8")
        fonts = f":fontsdir={FONTS_SUBDIR}" if (work / FONTS_SUBDIR).is_dir() else ""
        run_ffmpeg(["-f", "lavfi", "-i", f"color=c=0x3A4466:s={w}x{h}:d=1",
                    "-vf", f"ass=preview.ass{fonts},crop={cw}:{h}:{(w - cw) // 2}:0,scale={pw}:{ph}",
                    "-frames:v", "1", "preview.png"],
                   "caption preview", cwd=work)
        shutil.copyfile(work / "preview.png", out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out
