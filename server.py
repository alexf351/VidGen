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

import commands
import run_status
from common import (KEY_ENV, PROVIDERS, ROOT, STEP_ORDER, StepError, available_app_screens,
                    read_json, run_format, runs_dir, write_json)
from format_loader import COVER_EXTS, DEFAULT_FORMAT, format_summaries, load_format
from jobs import JobRunner

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
UI_DIR = ROOT / "ui"
SERVED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mp3", ".wav", ".m4a",
                   ".json", ".ass", ".txt"}
ProviderChoice = Union[str, dict, None]


# ----------------------------------------------------------------- models ----

class NewRun(BaseModel):
    premise: str
    format: str = DEFAULT_FORMAT
    provider: ProviderChoice = None
    dry_run: bool = False


class StepRequest(BaseModel):
    step: str
    only: list[int] | None = None
    provider: ProviderChoice = None


class RerollRequest(BaseModel):
    shot: int = Field(ge=1)
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
        try:
            yield
        finally:
            runner.stop()

    app = FastAPI(title="VidGen", docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json", lifespan=lifespan)
    app.state.runner = runner

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
    def config_for(format_name: str | None = None, providers: dict | None = None) -> dict:
        try:
            return load_config(format_name=format_name, providers=providers)
        except StepError as e:
            raise HTTPException(400, str(e)) from e

    def run_dir_of(run_id: str) -> Path:
        root = runs_dir().resolve()
        path = (root / run_id).resolve()
        if path.parent != root or not run_status.is_run_dir(path):
            raise HTTPException(404, f"run '{run_id}' not found")
        return path

    def config_for_run(run_dir: Path, providers: dict | None = None) -> dict:
        return config_for(run_format(run_dir), providers)

    def job_out(job, logs: bool = False) -> dict:
        return job.to_dict(logs=logs)

    def submit_run_job(action: str, run_dir: Path, params: dict, work: Callable[[dict], None],
                       providers: dict | None) -> dict:
        config_for_run(run_dir, providers)          # fail now (400) if the format is gone
        run_id = run_dir.name

        def fn(job):
            # Load the config when the job starts, so queued jobs see the current settings.
            work(load_config(format_name=run_format(run_dir), providers=providers))

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
                        "locked_cast": [c["id"] for c in f["overlay"].get("locked_characters", [])],
                        "cover": media_url(f["name"], "cover", f["cover"]),
                        "example_video": media_url(f["name"], "example", f["example_video"]),
                        "limits": {"story_shots": r["story_shots"], "vo_words": r["vo_words"],
                                   "montage": r["montage"]["count"] if r["montage"] else None,
                                   "cards": r["cards"]["count"] if r["cards"] else None,
                                   "max_animated_shots": f["overlay"].get("max_animated_shots"),
                                   "narrator": r["narrator"], "cta_caption": r["cta_caption"]}})
        return out

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

    @app.get("/api/config")
    def config_info() -> dict:
        cfg = config_for()
        return {
            "default_format": DEFAULT_FORMAT,
            "providers": {"default": cfg["providers"], "available": list(PROVIDERS)},
            "keys_present": {var: bool(os.environ.get(var)) for var in KEY_ENV.values()},
            "locked_cast": [{"id": c["id"], "role": c.get("role", "")} for c in cfg["locked_characters"]],
            "steps": STEP_ORDER, "steps_with_only": sorted(commands.STEPS_WITH_ONLY),
            "output_dir": str(runs_dir()),
            "script_model": cfg["script"]["model"],
            "video": {"clip_seconds": cfg["fal"]["video_seconds"],
                      "resolution": cfg[cfg["providers"]["video"]]["video_resolution"]},
            "prices": prices(cfg),
        }

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
        if not premise:
            raise HTTPException(400, "premise is empty")
        providers = _providers(body.provider)
        cfg = config_for(body.format, providers)
        preface: list[str] = []
        run_dir = commands.create_new_run(premise, cfg, log=preface.append)
        params = {"premise": premise, "format": cfg["format"]["name"], "provider": providers,
                  "dry_run": body.dry_run}

        def fn(job):
            commands.execute_new(run_dir, load_config(format_name=cfg["format"]["name"], providers=providers),
                                 body.dry_run)

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
            cfg = load_config(format_name=run_format(run_dir))
        except StepError:
            cfg = None
        out = run_status.detail(run_dir, cfg)
        job = runner.latest_for_run(run_id)
        out["job"] = job_out(job) if job else None
        out["active_job"] = job_out(runner.active_for_run(run_id)) if runner.active_for_run(run_id) else None
        return out

    @app.post("/api/runs/{run_id}/step", status_code=202)
    def rerun_step(run_id: str, body: StepRequest) -> dict:
        run_dir = run_dir_of(run_id)
        if body.step not in STEP_ORDER:
            raise HTTPException(400, f"step must be one of {', '.join(STEP_ORDER)}")
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
        script = run_status.load_script(run_dir)
        if script is None:
            raise HTTPException(409, "this run has no script.json yet; run the script step first")
        if body.shot not in {s.get("n") for s in script["shots"] if isinstance(s, dict)}:
            raise HTTPException(404, f"shot {body.shot} is not in script.json")
        providers = _providers(body.provider)
        params = {"shot": body.shot, "provider": providers}
        return submit_run_job("reroll", run_dir, params,
                              lambda cfg: commands.reroll(run_id, body.shot, cfg), providers)

    @app.post("/api/runs/{run_id}/recast", status_code=202)
    def recast(run_id: str) -> dict:
        run_dir = run_dir_of(run_id)
        if run_status.load_script(run_dir) is None:
            raise HTTPException(409, "this run has no script.json yet; run the script step first")
        return submit_run_job("recast", run_dir, {}, lambda cfg: commands.recast(run_id, cfg), None)

    @app.put("/api/runs/{run_id}/script")
    def save_script(run_id: str, script: dict = Body(...)) -> dict:
        import steps.script as S
        run_dir = run_dir_of(run_id)
        active = runner.active_for_run(run_id)
        if active:
            raise HTTPException(409, f"job {active.id} ({active.action}) is {active.status} on this run; "
                                     f"wait for it to finish")
        cfg = config_for_run(run_dir)
        try:
            normalized = S.validate_and_normalize(
                script, cfg["style"], int(cfg["max_animated_shots"]), cfg.get("locked_characters", []),
                available_app_screens(cfg), cfg["format"]["rules"])
        except ValueError as e:
            errors = [line[2:] if line.startswith("- ") else line for line in str(e).splitlines()]
            raise HTTPException(422, {"message": "the script does not pass validation", "errors": errors})
        write_json(run_dir / "script.json", normalized)
        return {"saved": True, "script": normalized}

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

    if UI_DIR.is_dir():
        app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
    return app


# ----------------------------------------------------------------- launch ----

def serve(load_config: Callable[..., dict], key_sources: dict[str, str], port: int = DEFAULT_PORT,
          open_browser: bool = True) -> int:
    import uvicorn
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((HOST, port))
        except OSError:
            raise StepError(f"port {port} on {HOST} is in use; pass --port with another number") from None
    app = create_app(load_config, key_sources, port)
    url = f"http://{HOST}:{port}/"
    print(f"[ui] VidGen at {url}  (API docs {url}api/docs). Only this computer can reach it. Ctrl+C to stop.")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=HOST, port=port, log_level="warning")
    return 0
