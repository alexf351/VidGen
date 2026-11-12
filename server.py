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
import run_status
import app_assets
import ready_scripts
import caption_styles
import code_engine
import progress
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
        cast = run_cast(run_dir)
        if cast:
            return load_config(format_name=run_format(run_dir), providers=providers, cast=cast)
        return load_config(format_name=run_format(run_dir), providers=providers)

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
                        "aspect": f["aspect"], "clip_seconds": f["clip_seconds"], "cast": f["cast"],
                        "beats": f["beats"], "examples": f["examples"],
                        "references": f.get("references", []),
                        "locked_cast": [c["id"] for c in f["overlay"].get("locked_characters", [])],
                        "characters": [{"id": c["id"], "role": c.get("role", ""),
                                        "description": c.get("description", ""),
                                        "image": format_char_url(f["name"], c),
                                        "redraw": format_char_redraw(c)}
                                       for c in f["overlay"].get("locked_characters", [])],
                        "engines": ["ai", "claude_code"] if f.get("code_render") else ["ai"],
                        "code_styles": (f.get("code_render") or {}).get("styles", []),
                        "ready_scripts": ready_scripts.listing(f),
                        "cover": media_url(f["name"], "cover", f["cover"]),
                        "example_video": media_url(f["name"], "example", f["example_video"]),
                        "limits": {"story_shots": r["story_shots"], "vo_words": r["vo_words"],
                                   "montage": r["montage"]["count"] if r["montage"] else None,
                                   "cards": r["cards"]["count"] if r["cards"] else None,
                                   "flashes": r["flashes"]["count"] if r.get("flashes") else None,
                                   "max_animated_shots": f["overlay"].get("max_animated_shots"),
                                   "animate_all": animate_all_for(f),
                                   "narrator": r["narrator"], "cta_caption": r["cta_caption"] if r.get("closing_shot", True) else "",
                                   "closing_shot": bool(r.get("closing_shot", True)),
                                   "talking": r["talking"]["max"] if r.get("talking") else None,
                                   "app_screens": int(r["app_screens"]["max"]),
                                   "song": bool(r.get("song")), "letter": bool(r.get("letter"))}})
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
                      "resolution": cfg[cfg["providers"]["video"]]["video_resolution"]},
            "prices": prices(cfg),
            "clip_sound": bool(cfg["clip_sound"]["enabled"]),
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
                                              captions=captions, screens=body.screens, ready=body.ready)
        except StepError as e:
            raise HTTPException(400, str(e)) from e
        premise = run_status.run_meta(run_dir)["premise"] or premise
        if body.clip_sound is not None and body.engine != "claude_code":
            import clip_sound
            clip_sound.set_for_run(run_dir, body.clip_sound)
            if body.clip_sound:
                preface.append("  clip sound: on (clips are made with their own sound; lines are taken from them)")
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
        if out.get("engine") != "claude_code":
            # The track and levels of this video, and the shot the music comes up on (music.py).
            m = music_out(run_dir, cfg)
            montage = next((s.get("n") for s in (out.get("script") or {}).get("shots", [])
                            if isinstance(s, dict) and s.get("montage")), None)
            out["music"] = {**m["music"], "loud_shot": montage}
            # The sound can be mixed again on its own once a picture has been assembled.
            out["can_remix"] = (run_dir / "build" / "main_video.mp4").is_file()
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
        assemble step runs again (no API calls, so it costs nothing)."""
        run_dir = run_dir_of(run_id)
        image_pipeline_only(run_dir, "caption styles")
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
        image_pipeline_only(run_dir, "caption styles")
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
        image_pipeline_only(run_dir, "caption styles")
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
