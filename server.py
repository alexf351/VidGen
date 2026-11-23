"""Local web server: VidGen's commands as an HTTP API, plus the ui/ frontend.

    python main.py ui [--port 8765] [--no-browser]

Binds to 127.0.0.1 only: the process holds the API keys. Endpoints call the same functions
the CLI does (commands.py, doctor.py, format_loader.py, steps.script) through a one-at-a-time
job runner (jobs.py); nothing shells out to main.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Union

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

import characters as lib
import commands
import review as review_mod
import run_status
import app_assets
import ready_scripts
import caption_styles
import code_engine
import video_length
import video_model
import progress
import contrast
import contrast_batch
import stickstory
import story_series
import explainer
import lessons
from common import (KEY_ENV, PROVIDERS, ROOT, STEP_ORDER, StepError, available_app_screens,
                    run_cast, run_engine, run_format, runs_dir, write_json)
from format_loader import COVER_EXTS, DEFAULT_FORMAT, format_summaries, load_format
from jobs import JobRunner

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
UI_DIR = ROOT / "ui"
SERVED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mp3", ".wav", ".m4a",
                   ".json", ".ass", ".txt"}
ProviderChoice = Union[str, dict, None]


# ----------------------------------------------------------------- models ----

class CastEntry(BaseModel):
    character: str
    replaces: str | None = None
    role: str = ""


class NewRun(BaseModel):
    premise: str
    format: str = DEFAULT_FORMAT
    provider: ProviderChoice = None
    dry_run: bool = False
    cast: list[CastEntry] = []
    engine: str = "ai"                # "ai" or "claude_code"
    captions: str | None = None       # a caption style id (caption_styles.py); None = the default
    screens: list[str] = []           # app screenshots this video must show (library paths)
    ready: str | None = None          # a ready-made script of the format (ready_scripts.py)
    clip_sound: bool | None = None    # clips made with their own sound (clip_sound.py); None = the config's setting
    quality: str | None = None        # "480p" or "720p" clips for this video (clip_quality.py); None = the config's
    length: str | None = None         # "short", "standard" or "long" (video_length.py); None = the format's own
    video_model: str | None = None    # "fast", "standard" or "2.5" (video_model.py); None = the config's
    review: bool | None = None        # Claude checks every shot as it is made (review.py); None = the config's
    auto_fix: bool | None = None      # ... and makes what it flags again


class ScreenIn(BaseModel):
    title: str
    shows: str = ""
    image: str | None = None          # data: URL of a screenshot, or
    video: str | None = None          # data: URL of a screen recording


class CharacterIn(BaseModel):
    name: str
    description: str
    role: str = ""
    voice_id: str = ""
    keep_as_is: bool = False
    image: str | None = None          # data: URL of an uploaded picture


class DrawRequest(BaseModel):
    format: str = DEFAULT_FORMAT
    provider: ProviderChoice = None


class ContrastNew(BaseModel):
    name: str = ""
    source: str = "starter"           # starter | write | scenes
    count: int = 30                   # write: how many scenes to ask Claude for
    about: str = ""                   # write: who the page is for
    scenes: list[dict] | None = None  # scenes: your own list
    end_tag: str | None = "SEARCH IRO AI"    # the words at the end; "" or null = none
    render: bool = True


class ContrastScene(BaseModel):
    template: str | None = None
    left: str | None = None
    right: str | None = None
    caption: str | None = None


class ContrastRender(BaseModel):
    only: list[int] | None = None
    again: bool = False


class ContrastVary(BaseModel):
    of: list[int]
    each: int = 10
    render: bool = True


class ContrastTag(BaseModel):
    end_tag: str | None = None


class StoryNew(BaseModel):
    name: str = ""
    starter: str | None = None        # one of the stories that ship
    premise: str = ""                 # your own; Claude writes episode 1 from it
    script: dict | None = None        # or the script of episode 1 itself
    iro: bool = True
    end_tag: str | None = "SEARCH IRO AI"
    voice_id: str = ""
    render: bool = True


class StoryNext(BaseModel):
    choice: str                       # "a" or "b": which choice won the vote
    script: dict | None = None
    render: bool = True


class StoryRender(BaseModel):
    episode: int | None = None        # default: the newest
    again: bool = False
    voice: bool = True


class StoryScript(BaseModel):
    script: dict


class StoryUpdate(BaseModel):
    name: str | None = None
    end_tag: str | None = None
    voice_id: str | None = None
    iro: bool | None = None


class LessonNew(BaseModel):
    name: str = ""
    starter: str | None = None        # one of the lessons that ship
    topic: str = ""                   # your own; Claude writes the lesson from it
    must: str = ""                    # something the lesson must mention
    script: dict | None = None        # or the lesson itself
    end_tag: str | None = "SEARCH IRO AI"
    voice_id: str = ""
    render: bool = True


class LessonWrite(BaseModel):
    topic: str = ""                   # default: the lesson's own topic
    must: str = ""
    render: bool = True


class LessonRender(BaseModel):
    again: bool = False
    voice: bool = True


class LessonUpdate(BaseModel):
    name: str | None = None
    end_tag: str | None = None
    voice_id: str | None = None


class CaptionSize(BaseModel):
    size: float | None = None         # 0.85, 1, 1.2 or 1.45 times the format's own; None = the format's own


class CaptionWords(BaseModel):
    words: int | None = None          # 1, 2 or 3 words at a time; None = the format's own


class CaptionChoice(BaseModel):
    style: str | None = None          # None or "format" = the format's own look


class VoiceChoice(BaseModel):
    speaker: str
    voice_id: str | None = None       # None or "" goes back to the config / default voice


class TrackIn(BaseModel):
    title: str = ""
    filename: str = ""                # only its ending is read (.mp3, .mp4 ...)
    file: str                         # data: URL of the sound (or of a video whose sound is used)


class MusicChoice(BaseModel):
    track: str = ""                   # a track's file name; "" = no music
    level: float = 0.10               # the music while people talk
    loud: float = 0.60                # the music from the montage on
    voices: float = 1.0               # the voices and the clips' own sound
    speed: float = 1.0                # 0.85 = slowed
    start: float = 0.0                # seconds into the track


class MusicDefault(BaseModel):
    music: MusicChoice | None = None  # None = new videos start without music again


class ClipVoiceChoice(BaseModel):
    on: bool = True                   # True = this shot's clip says its line: use its voice


class ClipSoundChoice(BaseModel):
    on: bool | None = None            # None = follow the config again


class ClipQualityChoice(BaseModel):
    quality: str | None = None        # "480p" | "720p"; None = follow the config again


class ReviewChoice(BaseModel):
    on: bool | None = None            # check this video's shots as they are made
    auto_fix: bool | None = None      # and make what it flags again


class ReviewRequest(BaseModel):
    what: str = "all"                 # all | pictures | clips | final
    shots: list[int] = []             # only these shots (empty = every shot)
    again: bool = False               # check again what was already checked
    fix: bool = False                 # make what it flags again
    provider: ProviderChoice = None


class ReviewFix(BaseModel):
    shots: list[int] = Field(min_length=1, max_length=200)
    what: str = "picture"             # picture | clip
    provider: ProviderChoice = None


class ReviewIgnore(BaseModel):
    n: int = Field(ge=1)
    what: str = "picture"             # picture | clip
    ignored: bool = True


class ClipStart(BaseModel):
    n: int = Field(ge=1)
    start: float = Field(ge=0, le=15)


class VideoModelChoice(BaseModel):
    model: str | None = None          # "fast" | "standard" | "2.5" (video_model.py); None = the config's


class LibraryVoice(BaseModel):
    public_owner_id: str
    voice_id: str
    name: str = ""


class DescribeRequest(BaseModel):
    image: str | None = None          # data: URL, or
    character: str | None = None      # a library character's own picture


class NewShot(BaseModel):
    after: int                        # the shot it comes after; 0 = before the first
    shot: dict                        # the form's answers (shot_new.py)


class MoveShot(BaseModel):
    shot: int
    to: int


class StepRequest(BaseModel):
    step: str
    only: list[int] | None = None
    provider: ProviderChoice = None


class FinishRequest(BaseModel):
    provider: ProviderChoice = None


class RerollRequest(BaseModel):
    shot: int = Field(ge=1)
    provider: ProviderChoice = None


class RerollMany(BaseModel):
    shots: list[int] = Field(min_length=1, max_length=200)
    provider: ProviderChoice = None


class CoverRequest(BaseModel):
    run_id: str
    shot: int = Field(ge=1)


class ExampleRequest(BaseModel):
    run_id: str


def _providers(choice: ProviderChoice) -> dict | None:
    """"sume" -> both kinds; {"images": "fal", "video": "sume"} -> as given; None -> config's."""
    if choice in (None, "", {}):
        return None
    if isinstance(choice, str):
        choice = {"images": choice, "video": choice}
    if not isinstance(choice, dict) or set(choice) - {"images", "video"}:
        raise HTTPException(400, 'provider must be "fal", "sume" or {"images": .., "video": ..}')
    out = {}
    for kind, value in choice.items():
        if value in (None, ""):
            continue
        value = str(value).strip().lower()
        if value not in PROVIDERS:
            raise HTTPException(400, f"provider for {kind} must be one of {', '.join(PROVIDERS)}, got {value!r}")
        out[kind] = value
    return out or None


# -------------------------------------------------------------------- app ----

def create_app(load_config: Callable[..., dict], key_sources: dict[str, str],
               port: int = DEFAULT_PORT, runner: JobRunner | None = None) -> FastAPI:
    """`load_config(format_name=..., providers=...)` is common.load_config in production."""
    load_config()                              # sets the output dir before the job history loads
    runner = runner or JobRunner(lambda: runs_dir() / "jobs.json")
    allowed_hosts = {"127.0.0.1", "localhost"}
    allowed_origins = {f"http://{h}:{port}" for h in allowed_hosts}

    @asynccontextmanager
    async def lifespan(_app):
        runner.start()
        commands.sweep_deleted(runs_dir())
        try:
            yield
        finally:
            runner.stop()
            import media
            media.stop_all()          # no ffmpeg outlives the server (it would keep run files locked)

    app = FastAPI(title="VidGen", docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json", lifespan=lifespan)
    app.state.runner = runner

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        # Anything a route did not turn into a clear error: say what it was instead of an empty
        # 500 (the UI could only show "request failed"), and leave the traceback in the console.
        import traceback
        traceback.print_exc()
        return JSONResponse({"detail": f"VidGen hit an error it did not expect: {type(exc).__name__}: "
                                       f"{str(exc)[:300]}. The window VidGen was started from has the details."},
                            status_code=500)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # DNS rebinding: only answer to our own host names. Cross-site requests from other web
        # pages: refuse writes that come from another origin or are not JSON.
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in allowed_hosts:
            return JSONResponse({"detail": "host not allowed"}, status_code=403)
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin")
            if origin and origin not in allowed_origins:
                return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
            ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return JSONResponse({"detail": "send JSON (content-type: application/json)"}, status_code=415)
        return await call_next(request)

    # ------------------------------------------------------------ helpers --
    def config_for(format_name: str | None = None, providers: dict | None = None,
                   cast: list | None = None) -> dict:
        try:
            if cast:
                return load_config(format_name=format_name, providers=providers, cast=cast)
            return load_config(format_name=format_name, providers=providers)
        except StepError as e:
            raise HTTPException(400, str(e)) from e

    def run_config(run_dir: Path, providers: dict | None = None) -> dict:
        """The config a job on this run uses: its format, plus its cast from your library."""
        import clip_quality
        cast = run_cast(run_dir)
        import video_length
        if cast:
            cfg = load_config(format_name=run_format(run_dir), providers=providers, cast=cast)
        else:
            cfg = load_config(format_name=run_format(run_dir), providers=providers)
        return video_length.apply(clip_quality.apply(video_model.apply(cfg, run_dir), run_dir), run_dir)

    def run_dir_of(run_id: str) -> Path:
        root = runs_dir().resolve()
        path = (root / run_id).resolve()
        if path.parent != root or not run_status.is_run_dir(path):
            raise HTTPException(404, f"run '{run_id}' not found")
        return path

    def config_for_run(run_dir: Path, providers: dict | None = None) -> dict:
        try:
            return run_config(run_dir, providers)
        except StepError as e:
            raise HTTPException(400, str(e)) from e

    def job_out(job, logs: bool = False) -> dict:
        d = job.to_dict(logs=logs)
        if job.status == "running":
            d["progress"] = progress.snapshot()     # where it is, for the progress bar
        return d

    def submit_run_job(action: str, run_dir: Path, params: dict, work: Callable[[dict], None],
                       providers: dict | None) -> dict:
        config_for_run(run_dir, providers)          # fail now (400) if the format is gone
        run_id = run_dir.name

        def fn(job):
            # Load the config when the job starts, so queued jobs see the current settings.
            work(run_config(run_dir, providers))

        job = runner.submit(action, run_id, params, fn)
        return {"job_id": job.id, "run_id": run_id, "status": job.status}

    # ---------------------------------------------------------- metadata --
    @app.get("/api/formats")
    def formats() -> list[dict]:
        out = []
        for f in format_summaries():
            if f.get("error"):
                out.append({"name": f["name"], "error": f["error"]})
                continue
            r = f["rules"]
            out.append({"name": f["name"], "title": f["title"], "default": f["name"] == DEFAULT_FORMAT,
                        "description": f["description"], "duration_target": f["duration_target"],
                        "lengths": lengths_of(f),
                        "aspect": f["aspect"], "clip_seconds": f["clip_seconds"], "cast": f["cast"],
                        "beats": f["beats"], "examples": f["examples"],
                        "references": f.get("references", []),
                        "locked_cast": [c["id"] for c in f["overlay"].get("locked_characters", [])],
                        "characters": [{"id": c["id"], "role": c.get("role", ""),
                                        "description": c.get("description", ""),
                                        "image": format_char_url(f["name"], c),
                                        "redraw": format_char_redraw(c)}
                                       for c in f["overlay"].get("locked_characters", [])],
                        "engines": (["claude_code"] if (f.get("code_render") or {}).get("only")
                                    else ["ai", "claude_code"] if f.get("code_render") else ["ai"]),
                        "code_kind": (f.get("code_render") or {}).get("kind"),
                        "code_styles": (f.get("code_render") or {}).get("styles", []),
                        "ready_scripts": ready_scripts.listing(f),
                        "cover": media_url(f["name"], "cover", f["cover"]),
                        "example_video": media_url(f["name"], "example", f["example_video"]),
                        "limits": limits_of(r, f["overlay"].get("max_animated_shots"), animate_all_for(f))})
        return out

    def limits_of(r: dict, max_animated, animate_all: bool) -> dict:
        """What the create screen shows and counts the cost from, for one set of rules."""
        return {"story_shots": r["story_shots"], "vo_words": r["vo_words"],
                "montage": r["montage"]["count"] if r["montage"] else None,
                "cards": r["cards"]["count"] if r["cards"] else None,
                "flashes": r["flashes"]["count"] if r.get("flashes") else None,
                "flashes_move": bool(r.get("flashes") and r["flashes"].get("animate")),
                "max_animated_shots": max_animated,
                "animate_all": animate_all,
                "narrator": r["narrator"], "cta_caption": r["cta_caption"] if r.get("closing_shot", True) else "",
                "closing_shot": bool(r.get("closing_shot", True)),
                "talking": r["talking"]["max"] if r.get("talking") else None,
                "app_screens": int(r["app_screens"]["max"]),
                "song": bool(r.get("song")), "letter": bool(r.get("letter"))}

    def lengths_of(f: dict) -> list[dict]:
        """The lengths a video of this format can pick, each with the limits it would run to."""
        import copy
        out = []
        animate_all = animate_all_for(f)                     # one config load a format, not one a length
        for item in video_length.describe(f):
            c = {"format": copy.deepcopy({k: f[k] for k in ("rules", "duration_target", "lengths", "name")}),
                 "max_animated_shots": f["overlay"].get("max_animated_shots")}
            video_length.apply(c, band=item["id"])
            out.append({**item, "duration_target": c["format"]["duration_target"],
                        "limits": limits_of(c["format"]["rules"], c["max_animated_shots"], animate_all)})
        return out

    def animate_all_for(f: dict) -> bool:
        """Whether this format makes every shot a clip, after config.local.yaml has its say."""
        try:
            return bool(config_for(f["name"]).get("animate_all"))
        except HTTPException:
            return bool(f["overlay"].get("animate_all"))

    def format_char_path(c: dict) -> Path | None:
        """A format character's picture: its image_path, else the sheet cached by an earlier run,
        but only while that sheet still shows the character's current look."""
        if c.get("image_path"):
            p = ROOT / c["image_path"]
            return p if p.is_file() else None
        from steps import images
        try:
            cfg = load_config()
        except StepError:
            return None
        return images.cache_path(cfg, c["id"]) if images.cache_is_current(cfg, c) else None

    def format_char_redraw(c: dict) -> bool:
        """True when an earlier run cached a sheet for this character, but from an older look,
        so the next video draws a new one."""
        if c.get("image_path"):
            return False
        from steps import images
        try:
            cfg = load_config()
        except StepError:
            return False
        return images.cache_path(cfg, c["id"]).exists() and not images.cache_is_current(cfg, c)

    def format_char_url(name: str, c: dict) -> str | None:
        p = format_char_path(c)
        return f"/format-char/{name}/{c['id']}?v={int(p.stat().st_mtime)}" if p else None

    @app.get("/format-char/{name}/{cid}")
    def format_char(name: str, cid: str):
        f = format_or_404(name)
        for c in f["overlay"].get("locked_characters", []):
            if c.get("id") == cid:
                p = format_char_path(c)
                if p:
                    return FileResponse(p)
        raise HTTPException(404, "not found")

    def media_url(name: str, kind: str, path: Path | None) -> str | None:
        return f"/format-media/{name}/{kind}?v={int(path.stat().st_mtime)}" if path else None

    def format_or_404(name: str) -> dict:
        try:
            return load_format(name)
        except StepError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/format-media/{name}/{kind}")
    def format_media(name: str, kind: str):
        f = format_or_404(name)
        path = {"cover": f["cover"], "example": f["example_video"]}.get(kind)
        if path is None:
            raise HTTPException(404, "not found")
        return FileResponse(path)

    @app.post("/api/formats/{name}/cover")
    def set_cover(name: str, body: CoverRequest) -> dict:
        """Use a run's keyframe as the format's cover in the gallery (formats/<name>/cover.jpg)."""
        from PIL import Image
        from steps.images import shot_path
        f = format_or_404(name)
        src = shot_path(run_dir_of(body.run_id), body.shot)
        if not src.is_file():
            raise HTTPException(404, f"shot {body.shot} has no image yet")
        img = Image.open(src).convert("RGB")
        w, h = img.size                                    # crop to 9:16, then 720x1280
        cw, ch = (w, round(w * 16 / 9)) if w * 16 / 9 <= h else (round(h * 9 / 16), h)
        left, top = (w - cw) // 2, (h - ch) // 2
        img = img.crop((left, top, left + cw, top + ch)).resize((720, 1280), Image.Resampling.LANCZOS)
        folder = f["dir"]
        for ext in COVER_EXTS:
            (folder / f"cover.{ext}").unlink(missing_ok=True)
        img.save(folder / "cover.jpg", quality=86)
        return {"cover": media_url(name, "cover", folder / "cover.jpg")}

    @app.post("/api/formats/{name}/example")
    def set_example(name: str, body: ExampleRequest) -> dict:
        """Use a run's final video as the format's example (formats/<name>/example.mp4)."""
        import shutil
        f = format_or_404(name)
        final = run_dir_of(body.run_id) / "final.mp4"
        if not final.is_file():
            raise HTTPException(404, "this run has no final video yet")
        shutil.copyfile(final, f["dir"] / "example.mp4")
        return {"example_video": media_url(name, "example", f["dir"] / "example.mp4")}

    # ------------------------------------------------------- app screens --
    def screen_out(e: dict) -> dict:
        p = app_assets.file_for(e["path"])
        rel = e["path"][len("assets/screens/"):] if e["path"].startswith("assets/screens/") else None
        url = f"/screen-media/{rel}?v={int(p.stat().st_mtime)}" if p and rel else None
        clip = app_assets.file_for(e["clip"]) if e.get("clip") else None
        clip_url = (f"/screen-media/{e['clip'][len('assets/screens/'):]}?v={int(clip.stat().st_mtime)}"
                    if clip and e["clip"].startswith("assets/screens/") else None)
        return {**e, "url": url, "clip_url": clip_url}

    @app.get("/api/screens")
    def list_screens(format: str | None = None) -> dict:
        """The app screenshots a format can show: its own, then the library and yours."""
        cfg = config_for(format)
        return {"groups": [{"id": g, "title": t} for g, t in app_assets.GROUPS],
                "max": int(cfg["format"]["rules"]["app_screens"]["max"]),
                "screens": [screen_out(e) for e in app_assets.in_library_order(available_app_screens(cfg))]}

    @app.post("/api/screens", status_code=201)
    def add_screen(body: ScreenIn) -> dict:
        try:
            if body.video:
                data = app_assets.decode_upload(body.video, "recording", app_assets.MAX_CLIP_UPLOAD_BYTES)
                return screen_out(app_assets.add_clip(body.title, body.shows, data))
            return screen_out(app_assets.add(body.title, body.shows, app_assets.decode_upload(body.image or "")))
        except StepError as e:
            raise HTTPException(400, str(e)) from e

    @app.delete("/api/screens/mine/{name}")
    def delete_screen(name: str) -> dict:
        try:
            app_assets.remove(f"assets/screens/mine/{name}")
        except StepError as e:
            raise HTTPException(404, str(e)) from e
        return {"deleted": name}

    @app.get("/screen-media/{rel:path}")
    def screen_media(rel: str):
        p = app_assets.file_for(f"assets/screens/{rel}")
        if p is None:
            raise HTTPException(404, "not found")
        return FileResponse(p)

    @app.get("/api/config")
    def config_info() -> dict:
        cfg = config_for()
        return {
            "default_format": DEFAULT_FORMAT,
            "providers": {"default": cfg["providers"], "available": list(PROVIDERS)},
            "keys_present": {var: bool(os.environ.get(var)) for var in KEY_ENV.values()},
            "locked_cast": [{"id": c["id"], "role": c.get("role", "")} for c in cfg["locked_characters"]],
            "steps": STEP_ORDER, "steps_with_only": sorted(commands.STEPS_WITH_ONLY),
            "code_steps": code_engine.CODE_STEPS,
            "output_dir": str(runs_dir()),
            "script_model": cfg["script"]["model"],
            "caption_styles": caption_styles.catalog(),
            "caption_style": caption_default(cfg),
            "video": {"clip_seconds": cfg["fal"]["video_seconds"],
                      "resolution": cfg[cfg["providers"]["video"]]["video_resolution"],
                      "model": video_model.of(cfg),
                      "models": [{"id": k, "title": m["title"], "short": m["short"], "note": m["note"]}
                                 for k, m in video_model.MODELS.items()]},
            "prices": prices(cfg),
            "clip_sound": bool(cfg["clip_sound"]["enabled"]),
            # self-review (review.py): the defaults for a new video, and whether Claude Eyes is installed
            "review": (lambda r: {"enabled": bool(r["enabled"]), "auto_fix": bool(r["auto_fix"]),
                                  "max_fixes": r["max_fixes"], "eyes": bool(review_mod.eyes_command(cfg))})(review_mod.settings(cfg)),
        }

    def caption_default(cfg: dict) -> str:
        """assemble.caption_style from config, or "format" when unset or unknown."""
        try:
            return caption_styles.check(cfg["assemble"].get("caption_style"))
        except StepError:
            return caption_styles.FORMAT

    @app.get("/caption-preview/{name}/{style}")
    def caption_preview(name: str, style: str):
        """A small picture of a caption style as this format would draw it."""
        format_or_404(name)
        try:
            path = caption_styles.preview(config_for(name), caption_styles.check(style))
        except StepError as e:
            raise HTTPException(404, str(e)) from e
        return FileResponse(path, headers={"Cache-Control": "max-age=300"})

    def prices(cfg: dict) -> dict:
        """USD rates from config, per provider. fal's block is re-read with fal selected, since
        load_config points fal's cost keys at Sume's numbers when Sume is the provider."""
        fal = cfg["fal"]
        if "sume" in cfg["providers"].values():
            fal = config_for(providers={"images": "fal", "video": "fal"})["fal"]
        sume = cfg["sume"]
        return {
            "fal": {"image": float(fal["image_cost"]), "video_per_second": fal.get("video_cost_by_resolution")
                    or {fal["video_resolution"]: float(fal["video_cost_per_second"])}},
            "sume": {"image": float(sume["image_cost"]), "video_per_second": sume.get("video_cost_by_resolution")
                     or {sume["video_resolution"]: float(sume["video_cost_per_second"])}},
            "voice_per_1k_chars": float(cfg["elevenlabs"]["cost_per_1k_chars"]),
            "talking_per_second": float(cfg["fal"]["avatar_cost_per_second"]),
            "song_per_minute": float(cfg["elevenlabs"]["music_cost_per_minute"]),
            "video_models": video_model.prices(),          # per model, per provider, per resolution
        }

    @app.get("/api/doctor")
    def doctor() -> dict:
        from doctor import doctor_checks
        rows = doctor_checks(config_for(), key_sources)
        checks = [{"status": s, "item": i, "detail": d} for s, i, d in rows]
        fails = sum(1 for c in checks if c["status"] == "FAIL")
        return {"ok": fails == 0, "failed": fails, "checks": checks}

    # -------------------------------------------------------------- runs --
    @app.post("/api/runs", status_code=202)
    def new_run(body: NewRun) -> dict:
        premise = body.premise.strip()
        if not premise and not body.ready:
            raise HTTPException(400, "premise is empty")
        providers = _providers(body.provider)
        cast = [e.model_dump() for e in body.cast]
        cfg = config_for(body.format, providers, cast)
        if body.engine not in code_engine.ENGINES:
            raise HTTPException(400, f"engine must be one of {', '.join(code_engine.ENGINES)}")
        if body.engine == "claude_code" and not code_engine.offered(cfg):
            raise HTTPException(400, f"the {cfg['format']['name']} format does not offer the Claude Code engine")
        try:
            captions = caption_styles.check(body.captions) if body.captions else None
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        preface: list[str] = []
        try:
            run_dir = commands.create_new_run(premise, cfg, log=preface.append, engine=body.engine,
                                              captions=captions, screens=body.screens, ready=body.ready,
                                              length=body.length)
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        premise = run_status.run_meta(run_dir)["premise"] or premise
        if body.clip_sound is not None and body.engine != "claude_code":
            import clip_sound
            clip_sound.set_for_run(run_dir, body.clip_sound)
            if body.clip_sound:
                preface.append("  clip sound: on (clips are made with their own sound; lines are taken from them)")
        if body.video_model is not None and body.engine != "claude_code":
            try:
                video_model.set_for_run(run_dir, body.video_model)
            except StepError as e:
                raise HTTPException(400, str(e)) from e
            preface.append(f"  video model: {video_model.MODELS[body.video_model]['title']}")
        if (body.review is not None or body.auto_fix is not None) and body.engine != "claude_code":
            import review
            choice = review.set_for_run(run_dir, on=body.review, auto_fix=body.auto_fix)
            if choice.get("on"):
                preface.append("  review: on (Claude checks every picture, clip and the cut"
                               + ("; flagged takes are made again" if choice.get("auto_fix") else "") + ")")
        if body.quality is not None and body.engine != "claude_code":
            import clip_quality
            try:
                clip_quality.set_for_run(run_dir, body.quality)
            except StepError as e:
                raise HTTPException(400, str(e)) from e
            preface.append(f"  clip quality: {body.quality}")
        if captions and captions != caption_styles.FORMAT:
            preface.append(f"  captions: {caption_styles.title(captions)}")
        for line in lib.describe_cast(cfg):
            preface.append(f"  cast: {line}")
        params = {"premise": premise, "format": cfg["format"]["name"], "provider": providers,
                  "dry_run": body.dry_run, "cast": cfg["cast"], "engine": body.engine}

        def fn(job):
            commands.execute_new(run_dir, run_config(run_dir, providers), body.dry_run)

        job = runner.submit("new", run_dir.name, params, fn, preface=preface)
        return {"job_id": job.id, "run_id": run_dir.name, "status": job.status}

    @app.get("/api/runs")
    def list_runs() -> list[dict]:
        root = runs_dir()
        if not root.is_dir():
            return []
        configs: dict[str, dict | None] = {}
        out = []
        for d in root.iterdir():
            if not run_status.is_run_dir(d):
                continue
            fmt = run_status.run_meta(d)["format"]
            if fmt not in configs:
                try:
                    configs[fmt] = load_config(format_name=fmt)
                except StepError:
                    configs[fmt] = None
            item = run_status.summary(d, configs[fmt])
            job = runner.latest_for_run(d.name)
            item["job"] = job_out(job) if job else None
            out.append(item)
        out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return out

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        run_dir = run_dir_of(run_id)
        try:
            cfg = run_config(run_dir)
        except StepError:
            cfg = None
        out = run_status.detail(run_dir, cfg)
        out["cast"] = [{"id": c["id"], "name": c.get("name", c["id"]), "role": c.get("role", ""),
                        "replaced": c.get("replaced"), "image": char_url(c["id"])}
                       for c in (cfg or {}).get("locked_characters", []) if c.get("library")]
        if out.get("engine") == "claude_code" and out.get("code_kind") == "hyperframes":
            # A HyperFrames video plays its track too: the render mounts it and cuts to its beats.
            out["music"] = {**music_out(run_dir, cfg)["music"], "loud_shot": None}
            out["can_remix"] = False
        if out.get("engine") != "claude_code":
            # The track and levels of this video, and the shot the music comes up on (music.py).
            m = music_out(run_dir, cfg)
            montage = next((s.get("n") for s in (out.get("script") or {}).get("shots", [])
                            if isinstance(s, dict) and s.get("montage")), None)
            out["music"] = {**m["music"], "loud_shot": montage}
            # The sound can be mixed again on its own once a picture has been assembled.
            out["can_remix"] = (run_dir / "build" / "main_video.mp4").is_file()
            # 480p or 720p: what this video's clips are made at from now on (clip_quality.py).
            import clip_quality
            out["clip_quality"] = clip_quality.of(cfg) if cfg else None
            out["video_model"] = video_model.of(cfg) if cfg else None
            # Made from a ready-made script that has been improved since: what an update would do.
            import ready_update
            out["script_update"] = ready_update.summary(run_dir, cfg)
        if cfg:
            band = cfg.get("_length") or video_length.native(cfg["format"])
            out["length"] = {"id": band, "title": video_length.BANDS[band][0],
                             "seconds": cfg["format"]["duration_target"]}
        job = runner.latest_for_run(run_id)
        out["job"] = job_out(job) if job else None
        out["active_job"] = job_out(runner.active_for_run(run_id)) if runner.active_for_run(run_id) else None
        return out

    @app.delete("/api/runs/{run_id}")
    def delete_run(run_id: str) -> dict:
        """Delete a video and everything made for it. Not while a job is working on it."""
        run_dir = run_dir_of(run_id)
        active = runner.active_for_run(run_id)
        if active:
            raise HTTPException(409, f"this video has a job {active.status} ({active.action}); wait for it to "
                                     f"finish, then delete it")
        try:
            commands.delete_run(run_dir, free_leftovers=True)
        except StepError as e:
            raise HTTPException(409, str(e)) from e
        runner.forget_run(run_id)
        return {"deleted": run_id}

    @app.post("/api/runs/{run_id}/step", status_code=202)
    def rerun_step(run_id: str, body: StepRequest) -> dict:
        run_dir = run_dir_of(run_id)
        steps = code_engine.CODE_STEPS if run_engine(run_dir) == "claude_code" else STEP_ORDER
        if body.step not in steps:
            raise HTTPException(400, f"step must be one of {', '.join(steps)}")
        if body.only and run_engine(run_dir) == "claude_code":
            raise HTTPException(400, "a Claude Code run's steps work on the whole video; only is not supported")
        only = None
        if body.only:
            if body.step not in commands.STEPS_WITH_ONLY:
                raise HTTPException(400, f"only is supported for {', '.join(sorted(commands.STEPS_WITH_ONLY))}")
            if any(n < 1 for n in body.only):
                raise HTTPException(400, "shot numbers start at 1")
            only = ",".join(str(n) for n in sorted(set(body.only)))
        providers = _providers(body.provider)
        params = {"step": body.step, "only": only, "provider": providers}
        return submit_run_job("step", run_dir, params,
                              lambda cfg: commands.step(run_id, body.step, cfg, only=only), providers)

    @app.post("/api/runs/{run_id}/finish", status_code=202)
    def finish_run(run_id: str, body: FinishRequest) -> dict:
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "finishing the video")
        if run_status.load_script(run_dir) is None:
            raise HTTPException(409, "this run has no script.json yet; run the script step first")
        providers = _providers(body.provider)
        return submit_run_job("finish", run_dir, {"provider": providers},
                              lambda cfg: commands.finish(run_id, cfg), providers)

    @app.post("/api/runs/{run_id}/reroll", status_code=202)
    def reroll(run_id: str, body: RerollRequest) -> dict:
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "reroll")
        script = run_status.load_script(run_dir)
        if script is None:
            raise HTTPException(409, "this run has no script.json yet; run the script step first")
        if body.shot not in {s.get("n") for s in script["shots"] if isinstance(s, dict)}:
            raise HTTPException(404, f"shot {body.shot} is not in script.json")
        providers = _providers(body.provider)
        params = {"shot": body.shot, "provider": providers}
        return submit_run_job("reroll", run_dir, params,
                              lambda cfg: commands.reroll(run_id, body.shot, cfg), providers)

    @app.post("/api/runs/{run_id}/reroll-many", status_code=202)
    def reroll_many(run_id: str, body: RerollMany) -> dict:
        """Reroll several shots as one job: their pictures, then their clips (and lines)."""
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "reroll")
        script = run_status.load_script(run_dir)
        if script is None:
            raise HTTPException(409, "this run has no script.json yet; run the script step first")
        have = {s.get("n") for s in script["shots"] if isinstance(s, dict)}
        shots = sorted(set(body.shots))
        missing = [n for n in shots if n not in have]
        if missing:
            raise HTTPException(404, f"shot {missing[0]} is not in script.json")
        providers = _providers(body.provider)
        params = {"shots": shots, "provider": providers}
        return submit_run_job("reroll", run_dir, params,
                              lambda cfg: commands.reroll_many(run_id, shots, cfg), providers)

    @app.post("/api/runs/{run_id}/recast", status_code=202)
    def recast(run_id: str) -> dict:
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "recast")
        if run_status.load_script(run_dir) is None:
            raise HTTPException(409, "this run has no script.json yet; run the script step first")
        return submit_run_job("recast", run_dir, {}, lambda cfg: commands.recast(run_id, cfg), None)

    @app.post("/api/runs/{run_id}/move")
    def move_shot(run_id: str, body: MoveShot) -> dict:
        """Move a shot to another place, with its picture, clip and voice. Nothing is generated."""
        import shot_order
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "moving a shot")
        active = runner.active_for_run(run_id)
        if active:
            raise HTTPException(409, f"job {active.id} ({active.action}) is {active.status} on this run; "
                                     f"wait for it to finish")
        try:
            # No job is working on this run (checked above), so an ffmpeg that still holds one of
            # its files is a leftover of a job that hung, and may be ended.
            out = shot_order.move(run_dir, config_for_run(run_dir), body.shot, body.to, free_leftovers=True)
        except StepError as e:
            raise HTTPException(422, str(e)) from e
        return {"moved": out["moved"], "to": out["to"], "files": out["files"]}

    def idle_or_409(run_id: str) -> None:
        active = runner.active_for_run(run_id)
        if active:
            raise HTTPException(409, f"job {active.id} ({active.action}) is {active.status} on this run; "
                                     f"wait for it to finish")

    @app.post("/api/runs/{run_id}/update-script")
    def update_from_ready_script(run_id: str) -> dict:
        """Bring a video made from a ready-made script up to date with that script as it is now,
        keeping the pictures, clips and lines of the shots that did not change (ready_update.py).
        Nothing is generated."""
        import ready_update
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "updating the script")
        idle_or_409(run_id)
        try:
            return ready_update.apply(run_dir, config_for_run(run_dir), free_leftovers=True)
        except StepError as e:
            raise HTTPException(422, str(e)) from e

    @app.post("/api/runs/{run_id}/shots")
    def add_shot(run_id: str, body: NewShot) -> dict:
        """Add a shot after shot `after` (0 = first). The shots after it keep their pictures,
        clips and voices. Nothing is generated; the new shot's picture is made by the images step."""
        import shot_new
        import shot_order
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "adding a shot")
        idle_or_409(run_id)
        cfg = config_for_run(run_dir)
        try:
            shot = shot_new.build(cfg, run_status.load_script(run_dir) or {}, body.after, body.shot)
            out = shot_order.insert(run_dir, cfg, body.after, shot, free_leftovers=True)
        except StepError as e:
            raise HTTPException(422, str(e)) from e
        return {"added": out["added"], "files": out["files"]}

    @app.delete("/api/runs/{run_id}/shots/{n}")
    def remove_shot(run_id: str, n: int) -> dict:
        """Take a shot out, with its picture, clip and voice. The shots after it move up."""
        import shot_order
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "removing a shot")
        idle_or_409(run_id)
        try:
            out = shot_order.remove(run_dir, config_for_run(run_dir), n, free_leftovers=True)
        except StepError as e:
            raise HTTPException(422, str(e)) from e
        return {"removed": out["removed"], "files": out["files"]}

    def image_pipeline_only(run_dir: Path, what: str) -> None:
        if run_engine(run_dir) == "claude_code":
            raise HTTPException(409, f"{what} is for the image pipeline; this run uses the Claude Code engine")

    @app.put("/api/runs/{run_id}/story")
    def save_story(run_id: str, story: dict = Body(...)) -> dict:
        """A Claude Code run's story.json, edited in the UI. Scenes and voice then need a re-run."""
        run_dir = run_dir_of(run_id)
        if run_engine(run_dir) != "claude_code":
            raise HTTPException(409, "this run uses the image pipeline; edit its script instead")
        active = runner.active_for_run(run_id)
        if active:
            raise HTTPException(409, f"job {active.id} ({active.action}) is {active.status} on this run; "
                                     f"wait for it to finish")
        if code_engine.read_story(run_dir) is None:
            raise HTTPException(409, "this run has no story yet; run the story step first")
        cfg = config_for_run(run_dir)
        try:
            clean = code_engine.save_story(run_dir, cfg, story)
        except ValueError as e:
            errors = [line[2:] if line.startswith("- ") else line for line in str(e).splitlines()]
            raise HTTPException(422, {"message": "the story does not pass the check", "errors": errors})
        return {"saved": True, "story": clean}

    @app.put("/api/runs/{run_id}/script")
    def save_script(run_id: str, script: dict = Body(...)) -> dict:
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "the shot-list editor")
        active = runner.active_for_run(run_id)
        if active:
            raise HTTPException(409, f"job {active.id} ({active.action}) is {active.status} on this run; "
                                     f"wait for it to finish")
        cfg = config_for_run(run_dir)
        import shot_order
        try:
            # with the cast descriptions the run was written with (shot_order.validate_for_run)
            normalized = shot_order.validate_for_run(run_dir, cfg, script)
        except ValueError as e:
            errors = [line[2:] if line.startswith("- ") else line for line in str(e).splitlines()]
            raise HTTPException(422, {"message": "the script does not pass validation", "errors": errors})
        write_json(run_dir / "script.json", normalized)
        return {"saved": True, "script": normalized}

    # ------------------------------------------------------------ voices --
    @app.get("/api/voices")
    def voices(refresh: bool = False) -> dict:
        """The voices in the ElevenLabs account (a free call, cached for an hour)."""
        import voice_cast
        try:
            return {"voices": voice_cast.list_voices(refresh=refresh), "error": None}
        except StepError as e:
            return {"voices": [], "error": str(e)}

    def music_out(run_dir: Path | None = None, cfg: dict | None = None) -> dict:
        import music
        tracks = [{**t, "url": f"/music-file/{t['name']}?v={int(music.file_for(t['name']).stat().st_mtime)}"}
                  for t in music.tracks()]
        out = {"tracks": tracks, "default": music.default(), "limits": {k: list(v) for k, v in music.LEVELS.items()},
               "max_mb": music.MAX_UPLOAD_BYTES // (1024 * 1024)}
        if run_dir is not None:
            now = music.for_run(run_dir, cfg or {})
            out["music"] = {k: now[k] for k in ("track", "title", "level", "loud", "voices", "speed", "start", "own")}
            out["music"]["playing"] = now["file"] is not None
        return out

    @app.get("/api/music")
    def list_music() -> dict:
        """Your tracks and the settings new videos start with."""
        return music_out()

    @app.post("/api/music", status_code=201)
    def add_music(body: TrackIn) -> dict:
        import music
        try:
            data = app_assets.decode_upload(body.file, "track", music.MAX_UPLOAD_BYTES)
            track = music.add(body.title, body.filename, data)
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        return {**music_out(), "added": track}

    @app.delete("/api/music/{name}")
    def delete_music(name: str) -> dict:
        import music
        try:
            music.remove(name)
        except StepError as e:
            raise HTTPException(404, str(e)) from e
        return {**music_out(), "deleted": name}

    @app.put("/api/music/default")
    def set_music_default(body: MusicDefault) -> dict:
        """The music a new video starts with (None = none)."""
        import music
        try:
            music.set_default(body.music.model_dump() if body.music else None)
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        return music_out()

    @app.get("/music-file/{name}")
    def music_file(name: str):
        import music
        p = music.file_for(name)
        if p is None:
            raise HTTPException(404, "not found")
        return FileResponse(p)

    @app.put("/api/runs/{run_id}/music")
    def set_run_music(run_id: str, body: MusicChoice) -> dict:
        """This video's track and levels. The finished video keeps its old sound until it is
        mixed again (POST .../remix: no API calls, so it costs nothing)."""
        import music
        run_dir = run_dir_of(run_id)
        if run_engine(run_dir) == "claude_code" and code_engine.kind(config_for_run(run_dir)) != "hyperframes":
            image_pipeline_only(run_dir, "music")
        active = runner.active_for_run(run_id)
        if active:
            raise HTTPException(409, f"job {active.id} ({active.action}) is {active.status} on this run; "
                                     f"wait for it to finish")
        try:
            music.set_for_run(run_dir, body.model_dump())
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        return {**music_out(run_dir, config_for_run(run_dir)), "assembled": (run_dir / "final.mp4").is_file()}

    @app.post("/api/runs/{run_id}/remix", status_code=202)
    def remix(run_id: str) -> dict:
        """Mix the sound again on the picture the video already has (new music, new levels)."""
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "the sound mix")
        if run_status.load_script(run_dir) is None:
            raise HTTPException(409, "this run has no script.json yet; run the script step first")
        return submit_run_job("assemble", run_dir, {"sound_only": True}, lambda cfg: commands.remix(run_id, cfg), None)

    @app.put("/api/runs/{run_id}/clip-quality")
    def set_run_clip_quality(run_id: str, body: ClipQualityChoice) -> dict:
        """480p or 720p clips for this video from now on. Clips already made stay as they are."""
        import clip_quality
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "clip quality")
        try:
            clip_quality.set_for_run(run_dir, body.quality)
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        return {"clip_quality": clip_quality.of(config_for_run(run_dir))}

    @app.put("/api/runs/{run_id}/video-model")
    def set_run_video_model(run_id: str, body: VideoModelChoice) -> dict:
        """The video model that makes this video's clips from now on. Clips already made stay."""
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "video model")
        try:
            video_model.set_for_run(run_dir, body.model)
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        return {"video_model": video_model.of(config_for_run(run_dir))}

    @app.put("/api/runs/{run_id}/review-settings")
    def set_run_review(run_id: str, body: ReviewChoice) -> dict:
        """Check this video's shots as they are made, and make what the check flags again."""
        import review
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "the review")
        review.set_for_run(run_dir, on=body.on, auto_fix=body.auto_fix)
        cfg = config_for_run(run_dir)
        return {"on": review.on(cfg, run_dir), "auto_fix": review.auto_fix(cfg, run_dir)}

    @app.post("/api/runs/{run_id}/review", status_code=202)
    def run_review(run_id: str, body: ReviewRequest) -> dict:
        """Check the video now: its pictures, clips and cut (a cent or three a check)."""
        import review
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "the review")
        if body.what not in ("all", "pictures", "clips", "final"):
            raise HTTPException(400, "what must be all, pictures, clips or final")
        if run_status.load_script(run_dir) is None:
            raise HTTPException(409, "this run has no script.json yet")
        only = set(body.shots) or None
        providers = _providers(body.provider)
        params = {"what": body.what, "shots": sorted(only or []), "again": body.again, "fix": body.fix,
                  "provider": providers}
        return submit_run_job("review", run_dir, params,
                              lambda cfg: review.review(run_dir, cfg, body.what, only, body.again, body.fix),
                              providers)

    @app.post("/api/runs/{run_id}/review/fix", status_code=202)
    def review_fix(run_id: str, body: ReviewFix) -> dict:
        """Make these shots' pictures (and their clips) or clips again with the reviewer's fix."""
        import review
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "the review")
        if body.what not in ("picture", "clip"):
            raise HTTPException(400, "what must be picture or clip")
        script = run_status.load_script(run_dir)
        if script is None:
            raise HTTPException(409, "this run has no script.json yet")
        have = {s.get("n") for s in script["shots"] if isinstance(s, dict)}
        shots = sorted(set(body.shots))
        missing = [n for n in shots if n not in have]
        if missing:
            raise HTTPException(404, f"shot {missing[0]} is not in script.json")
        providers = _providers(body.provider)
        params = {"shots": shots, "what": body.what, "provider": providers}
        return submit_run_job("reroll", run_dir, params,
                              lambda cfg: review.fix(run_dir, cfg, shots, body.what), providers)

    @app.post("/api/runs/{run_id}/review/ignore")
    def review_ignore(run_id: str, body: ReviewIgnore) -> dict:
        """Set a flag aside (or bring it back): the shot is left as it is."""
        import review
        run_dir = run_dir_of(run_id)
        if body.what not in ("picture", "clip"):
            raise HTTPException(400, "what must be picture or clip")
        if not review.set_ignored(run_dir, body.n, body.what, body.ignored):
            raise HTTPException(404, f"shot {body.n} has no {body.what} check")
        return {"n": body.n, "what": body.what, "ignored": body.ignored}

    @app.post("/api/runs/{run_id}/clip-start")
    def set_clip_start(run_id: str, body: ClipStart) -> dict:
        """Use a clip from a later moment (the review saw the action happen after the part the
        cut used). Saved in the script; it shows once the video is put together again."""
        from common import read_json, write_json
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "clip timing")
        active = runner.active_for_run(run_id)
        if active:
            raise HTTPException(409, f"job {active.id} ({active.action}) is {active.status} on this run; "
                                     f"wait for it to finish")
        path = run_dir / "script.json"
        if not path.is_file():
            raise HTTPException(409, "this run has no script.json yet")
        script = read_json(path)
        shot = next((s for s in script.get("shots") or [] if isinstance(s, dict) and s.get("n") == body.n), None)
        if shot is None:
            raise HTTPException(404, f"shot {body.n} is not in script.json")
        if body.start > 0:
            shot["clip_start"] = round(float(body.start), 2)
        else:
            shot.pop("clip_start", None)
        write_json(path, script)
        return {"n": body.n, "clip_start": shot.get("clip_start", 0)}

    @app.put("/api/runs/{run_id}/clip-sound")
    def set_run_clip_sound(run_id: str, body: ClipSoundChoice) -> dict:
        """Switch clip sound on or off for this video. Clips already made keep what they have:
        redo the video step for them, then the voice step, then assemble."""
        import clip_sound
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "clip sound")
        active = runner.active_for_run(run_id)
        if active:
            raise HTTPException(409, f"job {active.id} ({active.action}) is {active.status} on this run; "
                                     f"wait for it to finish")
        clip_sound.set_for_run(run_dir, body.on)
        return {"clip_sound": clip_sound.on(config_for_run(run_dir), run_dir)}

    @app.put("/api/runs/{run_id}/shots/{n}/clip-voice")
    def set_shot_clip_voice(run_id: str, n: int, body: ClipVoiceChoice) -> dict:
        """You listened to shot n's clip and it says the line: take the voice from the clip
        whatever the word finder heard. Only marks the shot; run the voice step for it after."""
        import clip_sound
        from run_status import load_script
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "clip sound")
        active = runner.active_for_run(run_id)
        if active:
            raise HTTPException(409, f"job {active.id} ({active.action}) is {active.status} on this run; "
                                     f"wait for it to finish")
        shot = next((s for s in (load_script(run_dir) or {}).get("shots", [])
                     if isinstance(s, dict) and s.get("n") == n), None)
        if shot is None or not str(shot.get("vo_line") or "").strip():
            raise HTTPException(404, f"shot {n} has no line")
        return {"clip_voice": sorted(clip_sound.trust(run_dir, n, body.on))}

    @app.get("/api/voices/library")
    def voice_library(gender: str = "", age: str = "", search: str = "", page: int = 0) -> dict:
        """Search the public ElevenLabs voice library (a free call; nothing is added)."""
        import voice_cast
        try:
            return {**voice_cast.search_library(gender, age, search, page), "error": None}
        except StepError as e:
            return {"voices": [], "has_more": False, "error": str(e)}

    @app.post("/api/voices/library/add")
    def voice_library_add(body: LibraryVoice) -> dict:
        """Add a library voice to the ElevenLabs account (a voice slot on the plan, no charge)."""
        import voice_cast
        try:
            added = voice_cast.add_from_library(body.public_owner_id, body.voice_id, body.name)
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        try:
            voices = voice_cast.list_voices(refresh=True)
        except StepError:
            voices = []
        return {**added, "voices": voices}

    @app.put("/api/runs/{run_id}/captions")
    def set_run_captions(run_id: str, body: CaptionChoice) -> dict:
        """Pick this run's caption style. The finished video keeps its old captions until the
        assemble step runs again (no API calls, so it costs nothing); for a Claude Code video,
        the render step, which only redoes the captions when the picture has not changed."""
        run_dir = run_dir_of(run_id)
        active = runner.active_for_run(run_id)
        if active:
            raise HTTPException(409, f"job {active.id} ({active.action}) is {active.status} on this run; "
                                     f"wait for it to finish")
        try:
            saved = caption_styles.set_for_run(run_dir, body.style)
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        return {"caption_style": saved, "assembled": (run_dir / "final.mp4").is_file()}

    @app.put("/api/runs/{run_id}/caption-size")
    def set_run_caption_size(run_id: str, body: CaptionSize) -> dict:
        """How big this video's captions are next to the format's own. Takes effect when the
        assemble step runs again."""
        run_dir = run_dir_of(run_id)
        active = runner.active_for_run(run_id)
        if active:
            raise HTTPException(409, f"job {active.id} ({active.action}) is {active.status} on this run; "
                                     f"wait for it to finish")
        try:
            caption_styles.set_size_for_run(run_dir, body.size)
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        return {"caption_size": caption_styles.size_for_run(run_dir), "assembled": (run_dir / "final.mp4").is_file()}

    @app.put("/api/runs/{run_id}/caption-words")
    def set_run_caption_words(run_id: str, body: CaptionWords) -> dict:
        """How many words this video's captions show at a time. Like the style, it takes effect
        when the assemble step runs again."""
        run_dir = run_dir_of(run_id)
        active = runner.active_for_run(run_id)
        if active:
            raise HTTPException(409, f"job {active.id} ({active.action}) is {active.status} on this run; "
                                     f"wait for it to finish")
        try:
            caption_styles.set_words_for_run(run_dir, body.words)
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        cfg = config_for_run(run_dir)
        return {"caption_words": caption_styles.words_for_run(run_dir, cfg["assemble"]),
                "assembled": (run_dir / "final.mp4").is_file()}

    @app.put("/api/runs/{run_id}/voices")
    def set_run_voice(run_id: str, body: VoiceChoice) -> dict:
        """Pick the voice for one speaker in this run. Lines already spoken keep their audio
        until the voice step is run again for them."""
        import voice_cast
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "voice casting")
        script = run_status.load_script(run_dir)
        if script is None:
            raise HTTPException(409, "this run has no script.json yet")
        if body.speaker not in voice_cast.speakers(script):
            raise HTTPException(404, f"{body.speaker!r} does not speak in this run")
        name = ""
        if body.voice_id:
            try:
                name = next((v["name"] for v in voice_cast.list_voices() if v["voice_id"] == body.voice_id), "")
            except StepError:
                name = ""
        try:
            voice_cast.set_voice(run_dir, body.speaker, body.voice_id, name)
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        return {"voices": voice_cast.summary(run_dir, config_for_run(run_dir), script)}

    # -------------------------------------------------------- characters --
    def char_url(cid: str) -> str | None:
        try:
            p = lib.ref_path(cid)
        except StepError:
            return None
        return f"/character-media/{cid}?v={p.stat().st_mtime_ns}" if p.is_file() else None

    def char_out(c: dict) -> dict:
        return {"id": c["id"], "name": c.get("name", c["id"]), "description": c.get("description", ""),
                "role": c.get("role", ""), "voice_id": c.get("voice_id", ""),
                "keep_as_is": bool(c.get("keep_as_is")), "source": c.get("source", ""),
                "drawn_in": c.get("drawn_in", ""), "created_at": c.get("created_at"),
                "image": char_url(c["id"])}

    def char_or_404(cid: str) -> dict:
        try:
            return lib.get(cid)
        except StepError as e:
            raise HTTPException(404, str(e)) from e

    def bad_request(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except StepError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/characters")
    def list_characters() -> list[dict]:
        return [char_out(c) for c in lib.list_all()]

    @app.get("/api/characters/{cid}")
    def get_character(cid: str) -> dict:
        return char_out(char_or_404(cid))

    def save_character(cid: str | None, body: CharacterIn) -> dict:
        data = lib.decode_image(body.image) if body.image else None
        c = bad_request(lib.save, cid, name=body.name, description=body.description, role=body.role,
                        voice_id=body.voice_id, keep_as_is=body.keep_as_is,
                        source="upload" if data else None)
        if data is not None:
            try:
                lib.store_image(c["id"], data)
            except StepError as e:
                if cid is None:
                    lib.delete(c["id"])
                raise HTTPException(400, str(e)) from e
        return char_out(lib.get(c["id"]))

    @app.post("/api/characters", status_code=201)
    def create_character(body: CharacterIn) -> dict:
        if body.image:
            bad_request(lib.decode_image, body.image)
        return save_character(None, body)

    @app.put("/api/characters/{cid}")
    def update_character(cid: str, body: CharacterIn) -> dict:
        char_or_404(cid)
        return save_character(cid, body)

    @app.delete("/api/characters/{cid}")
    def delete_character(cid: str) -> dict:
        char_or_404(cid)
        lib.delete(cid)
        return {"deleted": cid}

    @app.get("/character-media/{cid}")
    def character_media(cid: str):
        try:
            p = lib.ref_path(cid)
        except StepError:
            raise HTTPException(404, "not found")
        if not p.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(p)

    @app.post("/api/characters/{cid}/draw", status_code=202)
    def draw_character(cid: str, body: DrawRequest) -> dict:
        """Draw the character from its description in a format's style (one image model call)."""
        char_or_404(cid)
        providers = _providers(body.provider)
        cfg = config_for(body.format, providers)
        params = {"character": cid, "format": cfg["format"]["name"], "provider": providers}

        def fn(job):
            lib.generate_reference(cid, load_config(format_name=cfg["format"]["name"], providers=providers))

        job = runner.submit("draw_character", None, params, fn)
        return {"job_id": job.id, "status": job.status}

    @app.post("/api/characters/describe")
    def describe_character(body: DescribeRequest) -> dict:
        """Write an identity-only description of a picture (one short Claude call)."""
        import tempfile
        if body.character:
            c = char_or_404(body.character)
            if not c["image"]:
                raise HTTPException(400, "that character has no picture yet")
            return {"description": bad_request(lib.describe_image, c["image"], config_for())}
        if not body.image:
            raise HTTPException(400, "send an image or a character id")
        data = bad_request(lib.decode_image, body.image)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "upload"
            path.write_bytes(data)
            try:
                from PIL import Image, UnidentifiedImageError
                Image.open(path).verify()
            except (UnidentifiedImageError, OSError):
                raise HTTPException(400, "that file is not an image VidGen can read") from None
            return {"description": bad_request(lib.describe_image, path, config_for())}

    # -------------------------------------------------------------- jobs --
    # ------------------------------------------------------ contrast videos --
    def contrast_job(batch_id: str):
        """The job that is writing or drawing this batch right now, if any."""
        for j in runner.list():
            if j.action.startswith("contrast") and (j.params or {}).get("batch") == batch_id and j.status in ("queued", "running"):
                return j
        return None

    def contrast_or_404(batch_id: str) -> dict:
        try:
            return contrast_batch.load(batch_id)
        except (StepError, OSError, ValueError):
            raise HTTPException(404, f"there is no Contrast batch called {batch_id}")

    def contrast_free(batch_id: str) -> None:
        j = contrast_job(batch_id)
        if j:
            raise HTTPException(409, f"this batch is being {'written' if j.action == 'contrast_write' else 'drawn'}; wait for it to finish")

    def busy_ids(prefix: str, key: str) -> dict:
        """The queued and running jobs of one kind, by the id of what they work on. Taken before a
        list is read from disk, for the same reason as in the detail functions below."""
        return {(j.params or {}).get(key): j for j in runner.list()
                if j.action.startswith(prefix) and j.status in ("queued", "running") and (j.params or {}).get(key)}

    def contrast_detail(batch_id: str) -> dict:
        # the job is looked up before the data is read: read the other way round, a job that ends in
        # between leaves the page with old data and no job to wait for
        j = contrast_job(batch_id)
        data = contrast_or_404(batch_id)
        folder = contrast_batch.batch_dir(batch_id)
        scenes = []
        for s_ in data["scenes"]:
            made = contrast_batch.is_made(batch_id, data, s_)
            url = run_status.file_url(contrast_batch.video_path(batch_id, s_["n"])) if made else None
            if url:
                # two videos drawn in the same second have the same file time, and removing a
                # scene renames the later ones: the key keeps the browser from showing the old one
                url += "-" + str(data["made"].get(str(s_["n"])) or "")
            scenes.append({**s_, "made": made, "video": url,
                           "problems": data["checks"].get(str(s_["n"])) or []})
        return {**contrast_batch.summary(data), "scenes": scenes, "skipped": data.get("skipped") or [],
                "sheet": run_status.file_url(folder / "first_second.jpg"),
                "folder": str(folder / "videos"),
                "job": None if j is None else {"id": j.id, "action": j.action, "status": j.status}}

    @app.get("/api/contrast")
    def contrast_home() -> dict:
        busy = busy_ids("contrast", "batch")
        return {"templates": [{"id": k, "what": v} for k, v in contrast.TEMPLATES.items()],
                "starter": len(contrast_batch.starter()), "default_tag": contrast_batch.DEFAULT_TAG,
                "default_about": contrast_batch.DEFAULT_ABOUT, "max_write": contrast_batch.MAX_WRITE,
                "seconds": contrast.SECONDS, "workers": contrast_batch.workers_default(),
                "batches": [{**b, "busy": b["id"] in busy} for b in contrast_batch.batches()]}

    @app.post("/api/contrast", status_code=201)
    def contrast_new(body: ContrastNew) -> dict:
        """A new batch: the starter scenes, your own, or scenes Claude writes (one request).
        Drawing the videos costs nothing."""
        tag = body.end_tag if (body.end_tag or "").strip() else None
        try:
            if body.source == "write":
                n = max(1, min(int(body.count), contrast_batch.MAX_WRITE))
                data = contrast_batch.create_pending(body.name or "Written scenes", tag, {"count": n, "about": body.about})
            elif body.source == "scenes":
                data = contrast_batch.create(body.name or "My scenes", body.scenes or [], tag)
            elif body.source == "starter":
                data = contrast_batch.create(body.name or "Starter scenes", contrast_batch.starter(), tag)
            else:
                raise StepError("source must be starter, write or scenes")
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        batch_id = data["id"]
        if body.source == "write":
            n, about, draw = data["writing"]["count"], body.about, body.render

            def fn(job):
                try:
                    print(f"[contrast] asking Claude for {n} scenes...")
                    scenes = contrast_batch.write_scenes(n, about, load_config())
                    contrast_batch.add_scenes(batch_id, scenes)
                    contrast_batch.set_note(batch_id)
                    print(f"[contrast] {len(scenes)} scenes written")
                except Exception as e:
                    contrast_batch.set_note(batch_id, error=str(e))
                    raise
                if draw:
                    contrast_batch.render(batch_id)

            job = runner.submit("contrast_write", None, {"batch": batch_id, "count": n}, fn)
        elif body.render:
            job = runner.submit("contrast_render", None, {"batch": batch_id}, lambda job: contrast_batch.render(batch_id))
        else:
            job = None
        return {**contrast_detail(batch_id), "job_id": job.id if job else None}

    @app.get("/api/contrast/{batch_id}")
    def contrast_get(batch_id: str) -> dict:
        return contrast_detail(batch_id)

    @app.post("/api/contrast/{batch_id}/render", status_code=202)
    def contrast_render(batch_id: str, body: ContrastRender) -> dict:
        contrast_or_404(batch_id)
        contrast_free(batch_id)
        only = set(body.only) if body.only else None
        job = runner.submit("contrast_render", None, {"batch": batch_id, "only": sorted(only) if only else None},
                            lambda job: contrast_batch.render(batch_id, only=only, again=body.again))
        return {"job_id": job.id, "status": job.status}

    @app.post("/api/contrast/{batch_id}/vary", status_code=202)
    def contrast_vary(batch_id: str, body: ContrastVary) -> dict:
        """Claude writes variations of the scenes that did best (one request) and they are
        added to the batch and drawn."""
        data = contrast_or_404(batch_id)
        contrast_free(batch_id)
        of = sorted({int(n) for n in body.of})
        have = {s_["n"] for s_ in data["scenes"]}
        if not of or any(n not in have for n in of):
            raise HTTPException(400, "choose scenes that are in this batch")
        each = max(1, min(int(body.each), 20))
        if len(of) * each > contrast_batch.MAX_WRITE:
            raise HTTPException(400, f"that is {len(of) * each} new scenes; ask for at most {contrast_batch.MAX_WRITE} at a time")

        def fn(job):
            print(f"[contrast] asking Claude for {each} variations of {len(of)} scene(s)...")
            new = contrast_batch.variations(batch_id, of, each, load_config())
            _, left_out = contrast_batch.add_scenes(batch_id, new)
            print(f"[contrast] {len(new) - len(left_out)} variations added")
            if body.render:
                contrast_batch.render(batch_id)

        job = runner.submit("contrast_write", None, {"batch": batch_id, "of": of, "each": each}, fn)
        return {"job_id": job.id, "status": job.status}

    @app.put("/api/contrast/{batch_id}/scenes/{n}")
    def contrast_edit(batch_id: str, n: int, body: ContrastScene) -> dict:
        contrast_or_404(batch_id)
        contrast_free(batch_id)
        try:
            contrast_batch.edit_scene(batch_id, n, {k: v for k, v in body.model_dump().items() if v is not None})
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        return contrast_detail(batch_id)

    @app.delete("/api/contrast/{batch_id}/scenes/{n}")
    def contrast_remove(batch_id: str, n: int) -> dict:
        contrast_or_404(batch_id)
        contrast_free(batch_id)
        try:
            contrast_batch.remove_scene(batch_id, n)
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        return contrast_detail(batch_id)

    @app.put("/api/contrast/{batch_id}/tag")
    def contrast_tag(batch_id: str, body: ContrastTag) -> dict:
        """The words at the end of every video in the batch. Changing them makes the videos out of date."""
        contrast_or_404(batch_id)
        contrast_free(batch_id)
        contrast_batch.set_tag(batch_id, body.end_tag if (body.end_tag or "").strip() else None)
        return contrast_detail(batch_id)

    @app.delete("/api/contrast/{batch_id}")
    def contrast_delete(batch_id: str) -> dict:
        contrast_or_404(batch_id)
        contrast_free(batch_id)
        contrast_batch.delete(batch_id)
        return {"deleted": batch_id}

    @app.get("/api/contrast/{batch_id}/zip")
    def contrast_zip(batch_id: str):
        """Every finished video and the captions file in one zip."""
        data = contrast_or_404(batch_id)
        if not any(contrast_batch.is_made(batch_id, data, s_) for s_ in data["scenes"]):
            raise HTTPException(400, "no video of this batch is made yet")
        path = contrast_batch.export_zip(batch_id)
        return FileResponse(path, media_type="application/zip", filename=f"{batch_id}.zip")

    # -------------------------------------------------------- choice stories --
    def story_job(series_id: str):
        for j in runner.list():
            if j.action.startswith("story") and (j.params or {}).get("series") == series_id and j.status in ("queued", "running"):
                return j
        return None

    def story_or_404(series_id: str) -> dict:
        try:
            return story_series.load(series_id)
        except StepError as e:
            raise HTTPException(404, str(e)) from e

    def story_free(series_id: str) -> None:
        j = story_job(series_id)
        if j is not None:
            raise HTTPException(409, f"this series is busy ({'writing an episode' if j.action == 'story_write' else 'making a video'}); wait for it to finish")

    def story_detail(series_id: str) -> dict:
        j = story_job(series_id)                             # before the data: see contrast_detail
        data = story_or_404(series_id)
        episodes = []
        for n in range(1, data["episodes"] + 1):
            try:
                st = story_series.episode_state(series_id, n, data)
            except StepError:
                continue
            folder = Path(st.pop("folder"))
            st["video"] = run_status.file_url(folder / "final.mp4") if (st["made"] or st["stale"]) else None
            st["cover"] = run_status.file_url(folder / "cover.jpg")
            episodes.append(st)
        return {**story_series.summary(data), "episode_list": episodes, "folder": str(story_series.series_dir(series_id)),
                "job": None if j is None else {"id": j.id, "action": j.action, "status": j.status}}

    def story_produce(series_id: str, n: int, again: bool = False, voice: bool = True) -> None:
        story_series.produce(series_id, n, load_config(), voice=voice, again=again)

    @app.get("/api/stories")
    def stories_home() -> dict:
        busy = busy_ids("story", "series")
        return {"starters": [{"id": s["id"], "name": s["name"], "premise": s["premise"], "ready": bool(s["episode"])}
                             for s in story_series.starters()],
                "default_tag": story_series.DEFAULT_TAG, "has_voice_key": bool(os.environ.get("ELEVENLABS_API_KEY")),
                "sets": list(stickstory.SETS), "lights": list(stickstory.LIGHTS), "poses": list(stickstory.POSES),
                "events": list(stickstory.EVENTS),
                "series": [{**s, "busy": s["id"] in busy} for s in story_series.all_series()]}

    @app.post("/api/stories", status_code=201)
    def stories_new(body: StoryNew) -> dict:
        """A new series and its first episode: a starter's, your own script, or one Claude writes
        from the premise (one request). Drawing the video costs nothing."""
        starter = None
        if body.starter:
            starter = next((s for s in story_series.starters() if s["id"] == body.starter), None)
            if starter is None:
                raise HTTPException(400, f"there is no starter story called {body.starter}")
        premise = body.premise.strip() or (starter["premise"] if starter else "")
        if not premise and not body.script:
            raise HTTPException(400, "give the story a premise, or pick one of the starters")
        tag = body.end_tag if (body.end_tag or "").strip() else None
        data = story_series.create(body.name or (starter["name"] if starter else ""), premise, iro=body.iro, end_tag=tag, voice_id=body.voice_id)
        series_id = data["id"]
        script = body.script or (starter["episode"] if starter and starter["episode"] and not body.premise.strip() else None)
        if script is not None:
            try:
                story_series.add_episode(series_id, script)
            except StepError as e:
                story_series.delete(series_id)
                raise HTTPException(400, str(e)) from e
            job = runner.submit("story_render", None, {"series": series_id, "episode": 1},
                                lambda job: story_produce(series_id, 1)) if body.render else None
        else:
            story_series.set_note(series_id, writing={"episode": 1})
            draw = body.render

            def fn(job):
                try:
                    print("[story] asking Claude for episode 1...")
                    story_series.add_episode(series_id, story_series.write_first(story_series.load(series_id), load_config()))
                    story_series.set_note(series_id)
                except Exception as e:
                    story_series.set_note(series_id, error=str(e))
                    raise
                if draw:
                    story_produce(series_id, 1)

            job = runner.submit("story_write", None, {"series": series_id, "episode": 1}, fn)
        return {**story_detail(series_id), "job_id": job.id if job else None}

    @app.get("/api/stories/{series_id}")
    def stories_get(series_id: str) -> dict:
        return story_detail(series_id)

    @app.put("/api/stories/{series_id}")
    def stories_update(series_id: str, body: StoryUpdate) -> dict:
        story_or_404(series_id)
        story_free(series_id)
        story_series.update(series_id, {k: v for k, v in body.model_dump().items() if v is not None})
        return story_detail(series_id)

    @app.post("/api/stories/{series_id}/next", status_code=202)
    def stories_next(series_id: str, body: StoryNext) -> dict:
        """The next episode: Claude writes it from the story so far and the choice that won (one
        request), or you send its script. Then its video is made."""
        data = story_or_404(series_id)
        story_free(series_id)
        choice = body.choice.strip().lower()
        if choice not in ("a", "b"):
            raise HTTPException(400, "say which choice won: a or b")
        if data["episodes"] < 1:
            raise HTTPException(400, "this series has no episode yet")
        n = data["episodes"] + 1
        draw = body.render
        if body.script is not None:
            last = story_series.load_episode(series_id, data["episodes"])
            try:
                story_series.add_episode(series_id, body.script, voted=last[choice])
            except StepError as e:
                raise HTTPException(400, str(e)) from e
            job = runner.submit("story_render", None, {"series": series_id, "episode": n},
                                lambda job: story_produce(series_id, n)) if draw else None
            return {**story_detail(series_id), "job_id": job.id if job else None}
        story_series.set_note(series_id, writing={"episode": n, "choice": choice})

        def fn(job):
            try:
                print(f"[story] asking Claude for episode {n}...")
                script, won = story_series.write_next(series_id, choice, load_config())
                story_series.add_episode(series_id, script, voted=won)
                story_series.set_note(series_id)
            except Exception as e:
                story_series.set_note(series_id, error=str(e))
                raise
            if draw:
                story_produce(series_id, n)

        job = runner.submit("story_write", None, {"series": series_id, "episode": n, "choice": choice}, fn)
        return {**story_detail(series_id), "job_id": job.id}

    @app.post("/api/stories/{series_id}/render", status_code=202)
    def stories_render(series_id: str, body: StoryRender) -> dict:
        data = story_or_404(series_id)
        story_free(series_id)
        n = body.episode or data["episodes"]
        if not 1 <= n <= data["episodes"]:
            raise HTTPException(400, f"this series has no episode {n}")
        job = runner.submit("story_render", None, {"series": series_id, "episode": n},
                            lambda job: story_produce(series_id, n, again=body.again, voice=body.voice))
        return {"job_id": job.id, "status": job.status}

    @app.put("/api/stories/{series_id}/episodes/{n}")
    def stories_edit(series_id: str, n: int, body: StoryScript) -> dict:
        story_or_404(series_id)
        story_free(series_id)
        try:
            story_series.save_episode(series_id, n, body.script)
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        return story_detail(series_id)

    @app.delete("/api/stories/{series_id}/episodes/last")
    def stories_drop_last(series_id: str) -> dict:
        story_or_404(series_id)
        story_free(series_id)
        try:
            story_series.delete_last_episode(series_id)
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        story_series.set_note(series_id)
        return story_detail(series_id)

    @app.delete("/api/stories/{series_id}")
    def stories_delete(series_id: str) -> dict:
        story_or_404(series_id)
        story_free(series_id)
        story_series.delete(series_id)
        return {"deleted": series_id}

    # --------------------------------------------------------- Iro explains --
    def lesson_job(lesson_id: str):
        for j in runner.list():
            if j.action.startswith("lesson") and (j.params or {}).get("lesson") == lesson_id and j.status in ("queued", "running"):
                return j
        return None

    def lesson_or_404(lesson_id: str) -> dict:
        try:
            return lessons.load(lesson_id)
        except StepError as e:
            raise HTTPException(404, str(e)) from e

    def lesson_free(lesson_id: str) -> None:
        j = lesson_job(lesson_id)
        if j is not None:
            raise HTTPException(409, f"this lesson is busy ({'being written' if j.action == 'lesson_write' else 'making its video'}); wait for it to finish")

    def lesson_out(st: dict, j) -> dict:
        folder = Path(st.pop("folder"))
        has_video = st["made"] or st["stale"]
        st["video"] = run_status.file_url(folder / "final.mp4") if has_video else None
        st["cover"] = run_status.file_url(folder / "cover.jpg") if has_video and (folder / "cover.jpg").is_file() else None
        st["job"] = None if j is None else {"id": j.id, "action": j.action, "status": j.status}
        return st

    def lesson_detail(lesson_id: str) -> dict:
        j = lesson_job(lesson_id)                            # before the data: see contrast_detail
        data = lesson_or_404(lesson_id)
        return lesson_out(lessons.state(lesson_id, data), j)

    def lesson_produce(lesson_id: str, again: bool = False, voice: bool = True) -> None:
        lessons.produce(lesson_id, load_config(), voice=voice, again=again)

    def lesson_write_job(lesson_id: str, topic: str, must: str, render: bool):
        lessons.set_note(lesson_id, writing=True)

        def fn(job) -> None:
            try:
                print("[lesson] asking Claude for the lesson...")
                data = lessons.load(lesson_id)
                script = lessons.write(topic, load_config(), must=must, end_tag=data.get("end_tag", ""))
                lessons.set_script(lesson_id, script)
            except Exception as e:
                lessons.set_note(lesson_id, error=str(e))
                raise
            if render:
                lesson_produce(lesson_id)
        return runner.submit("lesson_write", None, {"lesson": lesson_id}, fn)

    @app.get("/api/lessons")
    def lessons_home() -> dict:
        busy = busy_ids("lesson", "lesson")
        return {"starters": [{"id": s["id"], "name": s["name"], "topic": s["topic"]} for s in lessons.starters()],
                "default_tag": lessons.DEFAULT_TAG, "has_voice_key": bool(os.environ.get("ELEVENLABS_API_KEY")),
                "cards": sorted(explainer.CARDS),
                "limits": {"words_min": explainer.WORDS_MIN, "words_max": explainer.WORDS_MAX,
                           "points_min": explainer.POINTS_MIN, "points_max": explainer.POINTS_MAX},
                "lessons": [lesson_out(st, busy.get(st["id"])) for st in lessons.all_lessons()]}

    @app.post("/api/lessons", status_code=201)
    def lessons_new(body: LessonNew) -> dict:
        """A new lesson: one that ships, your own script, or a topic Claude writes a lesson about
        (one request, a few cents). Drawing the video is free."""
        tag = body.end_tag
        if body.script is not None or body.starter:
            starter = None
            if body.script is None:
                starter = next((s for s in lessons.starters() if s["id"] == body.starter), None)
                if starter is None:
                    raise HTTPException(400, f"there is no starter lesson called {body.starter}")
            try:
                data = lessons.create(body.script if body.script is not None else starter["lesson"],
                                      name=body.name or (starter["name"] if starter else ""),
                                      topic=body.topic or (starter["topic"] if starter else ""), end_tag=tag, voice_id=body.voice_id)
            except StepError as e:
                raise HTTPException(422, str(e)) from e
            lesson_id = data["id"]
            job = runner.submit("lesson_render", None, {"lesson": lesson_id}, lambda job: lesson_produce(lesson_id)) if body.render else None
        else:
            topic = " ".join(body.topic.split())
            if not topic:
                raise HTTPException(400, "say what the lesson is about, or pick one of the starters")
            data = lessons.new(body.name, topic, end_tag=tag, voice_id=body.voice_id)
            lesson_id = data["id"]
            job = lesson_write_job(lesson_id, topic, body.must, body.render)
        return {**lesson_detail(lesson_id), "job_id": job.id if job else None}

    @app.get("/api/lessons/{lesson_id}")
    def lessons_get(lesson_id: str) -> dict:
        return lesson_detail(lesson_id)

    @app.put("/api/lessons/{lesson_id}")
    def lessons_update(lesson_id: str, body: LessonUpdate) -> dict:
        lesson_or_404(lesson_id)
        lesson_free(lesson_id)
        lessons.update(lesson_id, {k: v for k, v in body.model_dump().items() if v is not None})
        return lesson_detail(lesson_id)

    @app.put("/api/lessons/{lesson_id}/script")
    def lessons_edit(lesson_id: str, body: StoryScript) -> dict:
        lesson_or_404(lesson_id)
        lesson_free(lesson_id)
        try:
            lessons.set_script(lesson_id, body.script)
        except StepError as e:
            raise HTTPException(422, str(e)) from e
        return lesson_detail(lesson_id)

    @app.post("/api/lessons/{lesson_id}/write", status_code=202)
    def lessons_write(lesson_id: str, body: LessonWrite) -> dict:
        """Claude writes this lesson again (one request). The lesson it replaces is gone."""
        data = lesson_or_404(lesson_id)
        lesson_free(lesson_id)
        topic = " ".join((body.topic or data.get("topic") or "").split())
        if not topic:
            raise HTTPException(400, "say what the lesson is about")
        if topic != data.get("topic"):
            data["topic"] = topic[:lessons.TOPIC_MAX]
            lessons._save(lesson_id, data)
        job = lesson_write_job(lesson_id, topic, body.must, body.render)
        return {**lesson_detail(lesson_id), "job_id": job.id}

    @app.post("/api/lessons/{lesson_id}/render", status_code=202)
    def lessons_render(lesson_id: str, body: LessonRender) -> dict:
        lesson_or_404(lesson_id)
        lesson_free(lesson_id)
        if lessons.script(lesson_id) is None:
            raise HTTPException(400, "this lesson has no script yet")
        job = runner.submit("lesson_render", None, {"lesson": lesson_id},
                            lambda job: lesson_produce(lesson_id, again=body.again, voice=body.voice))
        return {**lesson_detail(lesson_id), "job_id": job.id}

    @app.delete("/api/lessons/{lesson_id}")
    def lessons_delete(lesson_id: str) -> dict:
        lesson_or_404(lesson_id)
        lesson_free(lesson_id)
        lessons.delete(lesson_id)
        return {"deleted": lesson_id}

    @app.get("/api/jobs")
    def list_jobs(run_id: str | None = None) -> list[dict]:
        return [job_out(j) for j in runner.list() if run_id is None or j.run_id == run_id]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, since: int = 0) -> dict:
        job = runner.get(job_id)
        if job is None:
            raise HTTPException(404, f"job '{job_id}' not found")
        with runner._lock:
            return job.to_dict(logs=True, since=max(0, since))

    @app.get("/api/jobs/{job_id}/stream")
    async def stream_job(job_id: str, request: Request):
        job = runner.get(job_id)
        if job is None:
            raise HTTPException(404, f"job '{job_id}' not found")
        try:
            start = int(request.headers.get("last-event-id", "-1")) + 1
        except ValueError:
            start = 0

        async def events():
            nonlocal start
            seen_version = -1
            while True:
                with runner._lock:
                    offset = job.dropped
                    lines = job.log[max(0, start - offset):]
                    first = max(start, offset)
                    status, version = job.to_dict(logs=False), job.version
                for i, line in enumerate(lines):
                    yield {"event": "log", "id": str(first + i), "data": line}
                start = first + len(lines)
                if version != seen_version:
                    seen_version = version
                    yield {"event": "status", "data": json.dumps(status)}
                if status["status"] in ("done", "failed"):
                    return
                if await request.is_disconnected():
                    return
                await asyncio.sleep(0.25)

        return EventSourceResponse(events(), ping=15)

    # ------------------------------------------------------------- files --
    @app.get("/files/{path:path}")
    def files(path: str):
        root = runs_dir().resolve()
        target = (root / path).resolve()
        try:
            rel = target.relative_to(root)
        except ValueError:
            raise HTTPException(404, "not found")
        if (not rel.parts or any(p.startswith(".") for p in rel.parts) or rel.parts == ("jobs.json",)
                or target.suffix.lower() not in SERVED_SUFFIXES or not target.is_file()):
            raise HTTPException(404, "not found")
        return FileResponse(target)

    @app.get("/ui-font/{name}")
    def ui_font(name: str):
        """The interface's own typeface (Inter, bundled under the OFL), so it looks the same on
        every computer. Only these two files."""
        if name not in ("Inter-Regular.otf", "Inter-SemiBold.otf"):
            raise HTTPException(404, "not found")
        return FileResponse(ROOT / "assets" / "fonts" / name, media_type="font/otf",
                            headers={"Cache-Control": "public, max-age=604800"})

    if UI_DIR.is_dir():
        app.mount("/", FreshStaticFiles(directory=UI_DIR, html=True), name="ui")
    return app


# ----------------------------------------------------------------- launch ----

class FreshStaticFiles(StaticFiles):
    """The page's own files, always checked with the server before the browser reuses its copy.
    Without this a browser keeps yesterday's app.js for a while after an update, and the page
    looks as if the update never arrived (a new panel is simply not there)."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def keep_console_awake() -> bool:
    """Windows: turn off the console's QuickEdit mode for this window. With it on, one click
    in the window selects text and the console stops taking output until a key is pressed,
    which used to freeze a job at its next log line. Returns True when it was switched off.
    (Text can still be selected from the window's menu: Edit > Mark.)"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-10)                      # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False                                       # no console (a service, a pipe)
        quick_edit, extended = 0x0040, 0x0080
        if not mode.value & quick_edit:
            return False
        return bool(kernel.SetConsoleMode(handle, (mode.value & ~quick_edit) | extended))
    except Exception:
        return False


def serve(load_config: Callable[..., dict], key_sources: dict[str, str], port: int = DEFAULT_PORT,
          open_browser: bool = True) -> int:
    import uvicorn
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((HOST, port))
        except OSError:
            raise StepError(f"port {port} on {HOST} is in use; pass --port with another number") from None
    keep_console_awake()
    app = create_app(load_config, key_sources, port)
    url = f"http://{HOST}:{port}/"
    print(f"[ui] VidGen at {url}  (API docs {url}api/docs). Only this computer can reach it. Ctrl+C to stop.")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=HOST, port=port, log_level="warning")
    return 0
