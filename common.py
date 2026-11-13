"""Shared helpers: config loading, run directories, step registry."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
RUNS_DIR = ROOT / "runs"                 # replaced by output_dir when the config loads
CONFIG_PATH = ROOT / "config.yaml"
LOCAL_CONFIG_PATH = ROOT / "config.local.yaml"

# API keys: env var name for each `keys:` entry in config.local.yaml.
KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "fal": "FAL_KEY",
           "elevenlabs": "ELEVENLABS_API_KEY", "sume": "SUME_API_KEY"}
# Non-secret settings that an environment variable can override (env wins over both files).
ENV_OVERRIDES = {"VIDGEN_FFMPEG_PATH": ("ffmpeg_path",), "VIDGEN_FFPROBE_PATH": ("ffprobe_path",),
                 "VIDGEN_OUTPUT_DIR": ("output_dir",),
                 "VIDGEN_IMAGE_PROVIDER": ("providers", "images"),
                 "VIDGEN_VIDEO_PROVIDER": ("providers", "video")}
# ffmpeg / ffprobe executables, filled in by load_config (media.py reads them at call time).
TOOLS = {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe"}

# Pipeline order. Every step module exposes run(run_dir, config).
STEP_ORDER = ["script", "images", "video", "voice", "assemble"]


class StepError(Exception):
    """A step failed in a way the user needs to see, without a traceback."""


def deep_merge(base: dict, over: dict) -> dict:
    """Return base with `over` merged in: nested dicts merge key by key, anything else
    (scalars, lists) in `over` replaces the base value."""
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _is_placeholder(value) -> bool:
    text = str(value or "").strip()
    return (not text or "..." in text or text.startswith("<") or text.upper().startswith("YOUR")
            or text.lower() in ("changeme", "todo", "xxx"))


def _read_yaml(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise StepError(f"{path.name} is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise StepError(f"{path.name} must be a mapping of settings")
    return data


def _apply_local_layers(cfg: dict, local: dict, local_name: str) -> dict:
    """Merge config.local.yaml over config.yaml, then let environment variables win.

    Records where each setting came from in cfg['_sources'] (names only, never values)."""
    sources = cfg.setdefault("_sources", {"files": [CONFIG_PATH.name], "keys": {}, "env": []})
    local = dict(local)
    keys = local.pop("keys", None) or {}
    if not isinstance(keys, dict):
        raise StepError(f"{local_name}: keys must be a mapping like  fal: \"...\"")
    # Shorthands from config.local.example.yaml
    for short, kind in (("default_video_provider", "video"), ("default_image_provider", "images")):
        if short in local:
            value = local.pop(short)
            if not _is_placeholder(value):
                local.setdefault("providers", {})
                local["providers"] = {**(local["providers"] or {}), kind: value}
    if local or keys:
        cfg = deep_merge(cfg, local)
        cfg["_sources"] = sources
        if local_name not in sources["files"]:
            sources["files"].append(local_name)

    # API keys: a real environment variable (or .env) wins; otherwise export the local value so
    # the SDKs, which read the environment, see it.
    unknown = sorted(set(keys) - set(KEY_ENV))
    if unknown:
        raise StepError(f"{local_name}: unknown keys {unknown}; use {sorted(KEY_ENV)}")
    for name, var in KEY_ENV.items():
        if os.environ.get(var):
            sources["keys"][var] = "environment"
        elif not _is_placeholder(keys.get(name)):
            os.environ[var] = str(keys[name]).strip()
            sources["keys"][var] = local_name
        else:
            sources["keys"][var] = "missing"

    for var, path in ENV_OVERRIDES.items():
        value = os.environ.get(var, "").strip()
        if not value:
            continue
        node = cfg
        for part in path[:-1]:
            node = node.setdefault(part, {}) or {}
        node[path[-1]] = value
        sources["env"].append(var)
    return cfg


def sibling_ffprobe(ffmpeg: str) -> str:
    """ffprobe ships next to ffmpeg: same folder, same extension (.exe on Windows). Windows-style
    paths are handled with Windows rules whatever the OS, so this behaves the same everywhere."""
    from pathlib import PurePosixPath, PureWindowsPath
    windows = "\\" in ffmpeg or re.match(r"^[A-Za-z]:", ffmpeg) is not None
    p = (PureWindowsPath if windows else PurePosixPath)(ffmpeg)
    if str(p.parent) in ("", "."):
        return "ffprobe"                      # a bare command name: look it up on PATH too
    return str(p.with_name(re.sub("ffmpeg", "ffprobe", p.name, flags=re.IGNORECASE)))


def _resolve_tools_and_dirs(cfg: dict) -> None:
    global RUNS_DIR
    ffmpeg = str(cfg.get("ffmpeg_path") or "").strip()
    ffprobe = str(cfg.get("ffprobe_path") or "").strip()
    if ffmpeg and not ffprobe:
        ffprobe = sibling_ffprobe(ffmpeg)
    TOOLS["ffmpeg"] = ffmpeg or "ffmpeg"
    TOOLS["ffprobe"] = ffprobe or "ffprobe"
    cfg["ffmpeg_path"], cfg["ffprobe_path"] = TOOLS["ffmpeg"], TOOLS["ffprobe"]

    out = Path(str(cfg.get("output_dir") or "runs").strip()).expanduser()
    RUNS_DIR = out if out.is_absolute() else ROOT / out
    cfg["output_dir"] = str(RUNS_DIR)


def load_config(path: Path = CONFIG_PATH, local_path: Path | None = LOCAL_CONFIG_PATH,
                format_name: str | None = None, providers: dict | None = None,
                cast: list | None = None) -> dict:
    """config.yaml, then the video format's format.yaml, then config.local.yaml (if present),
    each deep-merged over the last, then env vars. cfg['format'] is the loaded format
    (default pixar_arc); cfg['_sources'] says which layers were used (names only, never
    secret values). `providers` ({"images": .., "video": ..}) overrides every layer for this
    load only; the local server uses it for a per-job provider choice. `cast` (a run's cast,
    see characters.py) swaps or adds characters from your library into locked_characters."""
    from format_loader import load_format
    fmt = load_format(format_name)
    cfg = deep_merge(_read_yaml(path), fmt["overlay"])
    cfg["_sources"] = {"files": [path.name, fmt["file"]], "keys": {}, "env": []}
    local = {}
    if local_path is not None and Path(local_path).is_file():
        local = _read_yaml(Path(local_path))
    cfg = _apply_local_layers(cfg, local, Path(local_path).name if local_path else "config.local.yaml")
    _resolve_tools_and_dirs(cfg)
    if providers:
        unknown = sorted(set(providers) - {"images", "video"})
        if unknown:
            raise StepError(f"provider override for unknown kind(s) {unknown}; use images, video")
        cfg["providers"] = {**(cfg.get("providers") or {}),
                            **{k: v for k, v in providers.items() if v}}
        cfg["_sources"]["env"].append("request (providers)")
    cfg.setdefault("max_animated_shots", 8)
    for flag in ("animate_all", "app_screen_hand"):
        if not isinstance(cfg.setdefault(flag, False), bool):
            raise StepError(f"config: {flag} must be true or false")
    import sfx as _sfx
    cfg["sfx"] = _sfx.settings(cfg)
    import clip_sound as _clip_sound
    cfg["clip_sound"] = _clip_sound.settings(cfg)
    cfg.setdefault("script", {})
    cfg["script"].setdefault("model", "claude-sonnet-5-5")
    cfg["script"].setdefault("max_tokens", 64000)
    effort = str(cfg["script"].get("effort") or "").strip().lower()
    if effort and effort not in ("low", "medium", "high", "xhigh", "max"):
        raise StepError(f"config: script.effort must be low, medium, high, xhigh or max, got {effort!r}")
    cfg["script"]["effort"] = effort
    if not cfg.get("style"):
        raise StepError(f"{fmt['file']} is missing the 'style' line")
    cfg["format"] = {k: v for k, v in fmt.items() if k != "overlay"}
    cfg["locked_characters"] = _check_locked_characters(cfg.get("locked_characters") or [], fmt["file"])
    # The format's own screenshots first, then the rest of the library (app_assets.py).
    import app_assets
    cfg["app_screens"] = app_assets.merged(_check_app_screens(cfg.get("app_screens") or [], fmt["file"]))
    cfg.setdefault("characters_cache_dir", "characters_cache")
    cfg["cast"] = []
    fal = cfg.setdefault("fal", {})
    fal.setdefault("image_model", "fal-ai/nano-banana")
    fal.setdefault("image_edit_model", "fal-ai/nano-banana/edit")
    fal.setdefault("image_cost", 0.0398)
    fal.setdefault("video_model", "bytedance/seedance-2.0/fast/image-to-video")
    fal.setdefault("video_seconds", 4)
    fal.setdefault("video_resolution", "480p")
    fal.setdefault("video_audio", False)
    fal.setdefault("video_cost_per_second", {"480p": 0.1125, "720p": 0.2419})
    fal.setdefault("avatar_model", "fal-ai/kling-video/ai-avatar/v2/standard")
    fal.setdefault("avatar_cost_per_second", 0.0562)
    _resolve_video_rate(fal)
    _apply_providers(cfg)
    cfg["voices"] = {str(k): (v or "") for k, v in (cfg.get("voices") or {}).items()}
    vc = cfg.setdefault("voice_casting", {}) or {}
    cfg["voice_casting"] = {"enabled": vc.get("enabled", True) is not False,
                            "exclude": [str(x) for x in (vc.get("exclude") or [])]}
    if cast:
        from characters import apply_cast
        apply_cast(cfg, cast)
    el = cfg.setdefault("elevenlabs", {})
    el.setdefault("model_id", "eleven_multilingual_v2")
    el.setdefault("output_format", "mp3_44100_128")
    el.setdefault("cost_per_1k_chars", 0.22)
    el.setdefault("music_model", "music_v2")
    el.setdefault("music_output_format", "mp3_44100_128")
    el.setdefault("music_cost_per_minute", 0.30)
    asm = cfg.setdefault("assemble", {})
    for key, default in [("width", 1080), ("height", 1920), ("fps", 30),
                         ("vo_pad_seconds", 0.25), ("min_shot_seconds", 1.2), ("zoom_end", 1.08),
                         ("card_seconds", 1.5), ("card_fade_ms", 200),
                         ("app_screen_seconds", 1.5), ("app_screen_zoom_end", 1.04),
                         # An app screen with a recording plays it (app_assets.py), for at most this long.
                         ("app_screen_clips", True), ("app_clip_max_seconds", 6.0),
                         # A texts shot (phone_texts.py): a beat for each message.
                         ("texts_seconds", 1.2),
                         ("montage_seconds", 0.5), ("montage_zoom_end", 1.12),
                         ("caption_font", "Montserrat Black Italic"),
                         ("caption_font_file", "assets/fonts/Montserrat-BlackItalic.ttf"),
                         ("caption_fallback_font", "Arial Black"), ("caption_size", 90),
                         ("caption_y", 0.55), ("caption_max_words", 2),
                         ("caption_fill", "&H00FFFFFF"), ("caption_outline_color", "&H00E6C8FF"),
                         ("caption_outline", 5), ("caption_blur", 6),
                         ("caption_pop_from", 85), ("caption_pop_ms", 80),
                         ("caption_style", ""),
                         ("music_volume", 0.06), ("saturation", 0.85),
                         ("label_size", 50), ("label_y", 0.12), ("label_text", "#FFFFFF"),
                         ("label_box", "#1B1E2B"), ("label_colors", {}), ("label_wrap", ""),
                         ("flash_seconds", 0.35), ("flash_zoom_end", 1.06),
                         # Progress overlay on shots with "stat": a rank card top left and a big
                         # number lower left that ticks up once during the shot.
                         ("stat_seconds", 1.7), ("stat_font_file", "assets/fonts/Poppins-Black.ttf"),
                         ("stat_x", 0.06), ("stat_rank_y", 0.15), ("stat_y", 0.66),
                         ("stat_size", 190), ("stat_unit_size", 50), ("stat_rank_size", 66),
                         ("stat_eyebrow", "RANK"), ("stat_box", "#101522"), ("stat_tick", True),
                         ("letter_font_file", "assets/fonts/Caveat.ttf"), ("letter_font_size", 66),
                         ("letter_weight", 500), ("letter_paper", "#FBF7EE"), ("letter_ink", "#26232D"),
                         ("letter_rule", "#9DB4D6"), ("letter_width", 0.84), ("letter_bg_blur", 2),
                         ("letter_bg_dim", 0.8), ("letter_read_wps", 3.0), ("letter_zoom_end", 1.03),
                         ("colorbalance", "rs=-0.03:bs=0.04:rm=-0.02:bm=0.03:rh=-0.01:bh=0.02")]:
        asm.setdefault(key, default)
    cfg["music_path"] = (cfg.get("music_path") or "").strip()
    cfg["outro_path"] = (cfg.get("outro_path") or "").strip()
    return cfg


def read_script(run_dir: Path) -> dict:
    path = run_dir / "script.json"
    if not path.exists():
        raise StepError(f"{path} is missing; run the script step first")
    return read_json(path)


def parse_only(only: str | None) -> set[int] | None:
    """'3,7' -> {3, 7}; None/'' -> None (meaning every shot)."""
    if not only:
        return None
    try:
        nums = {int(x) for x in only.replace(" ", "").split(",") if x}
    except ValueError:
        raise StepError(f"--only expects comma-separated shot numbers, got {only!r}") from None
    if not nums:
        raise StepError("--only was given but no shot numbers followed")
    return nums


def select_shots(script: dict, only: set[int] | None) -> list[dict]:
    shots = script["shots"]
    if only is None:
        return shots
    known = {s["n"] for s in shots}
    missing = sorted(only - known)
    if missing:
        raise StepError(f"shot number(s) {missing} not in script.json (has 1-{len(shots)})")
    return [s for s in shots if s["n"] in only]


def _resolve_video_rate(block: dict, section: str = "fal") -> None:
    """video_cost_per_second may be a {resolution: rate} map. Keep the map and leave the
    active resolution's rate as a plain number, so every reader of the rate stays correct."""
    rates = block["video_cost_per_second"]
    res = str(block["video_resolution"]).strip()
    block["video_resolution"] = res
    if isinstance(rates, dict):
        block["video_cost_by_resolution"] = {str(k): float(v) for k, v in rates.items()}
        if res not in block["video_cost_by_resolution"]:
            raise StepError(f"config.yaml: {section}.video_cost_per_second has no rate for "
                            f"video_resolution '{res}' (has {sorted(block['video_cost_by_resolution'])})")
        block["video_cost_per_second"] = block["video_cost_by_resolution"][res]
    else:
        block["video_cost_per_second"] = float(rates)


PROVIDERS = ("fal", "sume")


def _apply_providers(cfg: dict) -> None:
    prov = cfg.setdefault("providers", {}) or {}
    cfg["providers"] = prov
    for kind in ("images", "video"):
        value = str(prov.get(kind) or "sume").strip().lower()
        if value not in PROVIDERS:
            raise StepError(f"config.yaml: providers.{kind} must be one of {', '.join(PROVIDERS)}, got '{value}'")
        prov[kind] = value

    sume = cfg.setdefault("sume", {}) or {}
    cfg["sume"] = sume
    for key, default in [("base_url", "https://api.sume.com"), ("image_model", "nano-banana"),
                         ("image_cost", 0.039), ("video_model", "seedance-2-fast"),
                         ("video_seconds", 4), ("video_resolution", "480p"), ("video_audio", False),
                         ("video_cost_per_second", {"480p": 0.056246, "720p": 0.12096}),
                         ("max_concurrent", 2), ("max_reference_images", 3), ("retry_window_seconds", 600),
                         ("retry_base_seconds", 5), ("job_timeout_seconds", 900)]:
        sume.setdefault(key, default)
    if int(sume["max_concurrent"]) < 1:
        raise StepError("config.yaml: sume.max_concurrent must be at least 1")
    _resolve_video_rate(sume, "sume")

    # The assemble step's cost report reads image_cost / video_seconds / video_cost_per_second
    # from the fal block. When Sume generates a kind, point those keys at Sume's numbers so the
    # final estimate prices what was actually used. fal's settings for that kind are not read
    # by anything else while Sume is selected.
    fal = cfg["fal"]
    if prov["images"] == "sume":
        fal["image_cost"] = float(sume["image_cost"])
    if prov["video"] == "sume":
        fal["video_seconds"] = int(sume["video_seconds"])
        fal["video_cost_per_second"] = float(sume["video_cost_per_second"])


def _check_app_screens(raw, where: str = "config.yaml") -> list[dict]:
    """app_screens: [{path, shows}]. Paths are repo-relative; files may be added later."""
    if not isinstance(raw, list):
        raise StepError(f"{where}: app_screens must be a list")
    out, seen = [], set()
    for i, e in enumerate(raw):
        if isinstance(e, str):
            e = {"path": e}
        if not isinstance(e, dict) or not isinstance(e.get("path"), str) or not e["path"].strip():
            raise StepError(f"{where}: app_screens[{i}] needs a path")
        path = e["path"].strip()
        if path in seen:
            raise StepError(f"{where}: app_screens lists {path!r} twice")
        seen.add(path)
        out.append({"path": path, "shows": str(e.get("shows") or "").strip(),
                    "title": str(e.get("title") or "").strip()})
    return out


def available_app_screens(config: dict) -> list[dict]:
    """The configured screenshots whose files exist."""
    return [e for e in config.get("app_screens", []) if (ROOT / e["path"]).is_file()]


def _check_locked_characters(raw, where: str = "config.yaml") -> list[dict]:
    """Validate locked_characters and fill in defaults (image_path -> "", outfit -> "")."""
    if not isinstance(raw, list):
        raise StepError(f"{where}: locked_characters must be a list")
    seen: set[str] = set()
    out = []
    for i, c in enumerate(raw):
        if not isinstance(c, dict):
            raise StepError(f"{where}: locked_characters[{i}] must be a mapping")
        cid, desc = c.get("id"), c.get("description")
        if not isinstance(cid, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", cid):
            raise StepError(f"{where}: locked_characters[{i}].id must be a lowercase slug, got {cid!r}")
        if cid in seen:
            raise StepError(f"config.yaml: duplicate locked character id {cid!r}")
        if not isinstance(desc, str) or not desc.strip():
            raise StepError(f"{where}: locked_characters[{i}] ({cid}) needs a description")
        seen.add(cid)
        entry = dict(c)
        entry["description"] = desc.strip()
        entry["image_path"] = (c.get("image_path") or "").strip()
        outfit = c.get("outfit")
        if outfit is not None and not isinstance(outfit, str):
            raise StepError(f"{where}: locked_characters[{i}] ({cid}).outfit must be text")
        entry["outfit"] = (outfit or "").strip()
        out.append(entry)
    return out


def slugify(text: str, max_len: int = 32) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "run"


def new_run_id(premise: str) -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{slugify(premise)}"


def runs_dir() -> Path:
    """Where runs live (config output_dir, default <repo>/runs)."""
    return RUNS_DIR


def run_dir_for(run_id: str, must_exist: bool = True) -> Path:
    run_dir = RUNS_DIR / run_id
    if must_exist and not run_dir.is_dir():
        raise StepError(f"run '{run_id}' not found under {RUNS_DIR}")
    return run_dir


def create_run(premise: str, format_name: str, cast: list | None = None,
               engine: str | None = None, captions: str | None = None,
               screens: list[str] | None = None, ready: str | None = None) -> Path:
    run_id = new_run_id(premise)
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "premise.txt").write_text(premise.strip() + "\n", encoding="utf-8")
    meta = {
        "run_id": run_id,
        "premise": premise.strip(),
        "format": format_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if cast:
        meta["cast"] = cast
    if engine and engine != "ai":
        meta["engine"] = engine
    if captions:
        meta["captions"] = captions          # a caption style id, see caption_styles.py
    if screens:
        meta["screens"] = list(screens)      # app screenshots pinned for this video (app_assets.py)
    if ready:
        meta["ready_script"] = ready         # written by hand (ready_scripts.py): no script step
    write_json(run_dir / "run.json", meta)
    return run_dir


def peek_runs_dir(path: Path = CONFIG_PATH, local_path: Path | None = LOCAL_CONFIG_PATH) -> Path:
    """Where runs live, read without loading the whole config (which needs the run's format)."""
    value = os.environ.get("VIDGEN_OUTPUT_DIR", "").strip()
    if not value and local_path is not None and Path(local_path).is_file():
        value = str(_read_yaml(Path(local_path)).get("output_dir") or "").strip()
    if not value:
        value = str(_read_yaml(path).get("output_dir") or "").strip() or "runs"
    out = Path(value).expanduser()
    return out if out.is_absolute() else ROOT / out


def run_format(run_dir: Path) -> str | None:
    """The format a run was made with (run.json). Runs from before formats existed have none
    recorded; they were all made with the original pipeline, pixar_arc. None if the run is
    missing (the caller reports that once the config is loaded)."""
    path = Path(run_dir) / "run.json"
    if not Path(run_dir).is_dir():
        return None
    if not path.is_file():
        return "pixar_arc"
    try:
        return str(read_json(path).get("format") or "pixar_arc")
    except (OSError, ValueError) as e:
        raise StepError(f"{path} is not valid JSON: {e}") from e


def _run_meta(run_dir: Path) -> dict:
    path = Path(run_dir) / "run.json"
    if not path.is_file():
        return {}
    try:
        data = read_json(path)
    except (OSError, ValueError) as e:
        raise StepError(f"{path} is not valid JSON: {e}") from e
    return data if isinstance(data, dict) else {}


def run_cast(run_dir: Path) -> list:
    """The library characters a run was cast with (run.json "cast"), [] if none."""
    return list(_run_meta(run_dir).get("cast") or [])


def run_ready_script(run_dir: Path) -> str | None:
    """The ready-made script a run was started from (run.json "ready_script"), or None."""
    value = _run_meta(run_dir).get("ready_script")
    return value if isinstance(value, str) and value else None


def run_engine(run_dir: Path) -> str:
    """"ai" (the image/video/voice pipeline) or "claude_code" (Claude Code writes and renders)."""
    return str(_run_meta(run_dir).get("engine") or "ai")


def read_premise(run_dir: Path) -> str:
    path = run_dir / "premise.txt"
    if not path.exists():
        raise StepError(f"{path} is missing; was this run created with 'main.py new'?")
    return path.read_text(encoding="utf-8").strip()


def read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def not_implemented(step_name: str) -> None:
    print(f"[{step_name}] not implemented yet")
