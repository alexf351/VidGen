"""Sume API client (https://sume.com/docs): uploads, job submit + polling, retries, downloads.

Every generation on Sume is an async job: POST to a router returns 202 with a status_url to
poll and a result_url that lists the artifacts once the job is terminal. Model inputs must be
HTTPS URLs, so local files are uploaded first through /v1/files/generate-upload-url."""

from __future__ import annotations

import os
import random
import threading
import time
import uuid
from pathlib import Path

import requests

from common import StepError

IMAGE_ENDPOINT = "/v1/image-router/generate"
VIDEO_ENDPOINT = "/v1/video-router/generate"
UPLOAD_ENDPOINT = "/v1/files/generate-upload-url"

# Codes Sume documents as safe to retry. queue_full is the workspace concurrency cap:
# the request is refused (not queued, not charged) and may be resent with the same key.
RETRYABLE_CODES = {
    "queue_full", "rate_limited", "provider_rate_limited", "provider_capacity_exceeded",
    "internal_error", "database_busy", "deploy_draining", "overloaded", "replica_not_ready",
    "api_key_auth_unavailable", "asset_storage_unavailable", "job_not_completed",
}
OVER_LIMIT_CODES = {"queue_full", "rate_limited", "provider_rate_limited"}

_session = requests.Session()
_upload_cache: dict[tuple[str, float], str] = {}
_upload_lock = threading.Lock()
_file_locks: dict[str, threading.Lock] = {}


# ------------------------------------------------------------- transport ----

def _send(method: str, url: str, **kwargs) -> requests.Response:
    """The one place an HTTP request leaves this module (tests replace it)."""
    kwargs.setdefault("timeout", 60)
    return _session.request(method, url, **kwargs)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def require_key() -> str:
    key = os.environ.get("SUME_API_KEY")
    if not key:
        raise StepError("SUME_API_KEY is not set; put it in .env (see .env.example)")
    return key


def _auth() -> dict:
    return {"Authorization": f"Bearer {require_key()}"}


def _base(cfg: dict) -> str:
    return str(cfg["base_url"]).rstrip("/")


def _error_of(resp: requests.Response) -> tuple[str, str, bool | None, float | None, dict]:
    """(code, message, retryable, retry_after_seconds, details) from Sume's error envelope."""
    try:
        err = resp.json().get("error") or {}
    except ValueError:
        err = {}
    retry_after = None
    header = resp.headers.get("retry-after")
    if header:
        try:
            retry_after = float(header)
        except ValueError:
            retry_after = None
    if retry_after is None and isinstance(err.get("retry_after_seconds"), (int, float)):
        retry_after = float(err["retry_after_seconds"])
    message = err.get("message") or resp.text[:300]
    details = err.get("details") if isinstance(err.get("details"), dict) else \
        ({"details": err["details"]} if err.get("details") else {})
    for key in ("param", "field", "errors", "issues", "request_id"):   # whatever says what was wrong
        if err.get(key) and key not in details:
            details[key] = err[key]
    return str(err.get("code") or f"http_{resp.status_code}"), message, err.get("retryable"), \
        retry_after, details


def _backoff(attempt: int, cfg: dict) -> float:
    base = float(cfg["retry_base_seconds"])
    return min(60.0, base * (2 ** attempt)) * (0.75 + random.random() / 2)


def _call(method: str, url: str, label: str, cfg: dict, *, json: dict | None = None,
          headers: dict | None = None, expect: tuple[int, ...] = (200,)) -> dict:
    """One logical request. Retries network errors and retryable refusals (over limit, busy)
    for up to retry_window_seconds, honouring retry-after. Returns the `data` envelope."""
    deadline = time.monotonic() + float(cfg["retry_window_seconds"])
    attempt = 0
    announced = False
    while True:
        try:
            resp = _send(method, url, json=json, headers={**_auth(), **(headers or {})})
        except requests.RequestException as e:
            if time.monotonic() >= deadline:
                raise StepError(f"{label}: could not reach Sume: {e}") from e
            _sleep(_backoff(attempt, cfg))
            attempt += 1
            continue

        if resp.status_code in expect:
            try:
                body = resp.json()
            except ValueError:
                raise StepError(f"{label}: Sume returned non-JSON: {resp.text[:200]}") from None
            return body.get("data", body)

        code, message, retryable, retry_after, details = _error_of(resp)
        if code == "insufficient_funds":
            need, have = details.get("required_usd"), details.get("available_usd")
            raise StepError(f"{label}: Sume balance too low (needs ${need}, has ${have}); "
                            f"top up at sume.com/dashboard/billing and rerun")
        if retryable is None:
            retryable = code in RETRYABLE_CODES or resp.status_code in (429, 500, 503)
        if retryable and time.monotonic() < deadline:
            wait = retry_after if retry_after is not None else _backoff(attempt, cfg)
            if code in OVER_LIMIT_CODES and not announced:
                print(f"    {label}: Sume is at your concurrency limit ({code}); "
                      f"waiting for a slot and retrying")
                announced = True
            _sleep(max(0.5, wait))
            attempt += 1
            continue
        more = ""
        if details:
            import json as _json
            more = " " + _json.dumps(details, ensure_ascii=False, default=str)[:400]
        raise StepError(f"{label}: Sume returned HTTP {resp.status_code} {code}: {message}{more}")


# --------------------------------------------------------------- uploads ----

def _content_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise StepError(f"unsupported image type (first bytes {data[:8]!r}); expected PNG, JPEG or WebP")


def upload(path: Path, cfg: dict, label: str) -> str:
    """Upload a local file to Sume storage and return its public URL (cached per file mtime)."""
    path = Path(path)
    with _upload_lock:
        file_lock = _file_locks.setdefault(str(path.resolve()), threading.Lock())
    # One upload per file even when parallel shots share a reference sheet.
    with file_lock:
        return _upload_once(path, cfg, label)


def _upload_once(path: Path, cfg: dict, label: str) -> str:
    key = (str(path.resolve()), path.stat().st_mtime)
    with _upload_lock:
        if key in _upload_cache:
            return _upload_cache[key]
    data = path.read_bytes()
    slot = _call("POST", _base(cfg) + UPLOAD_ENDPOINT, label, cfg, expect=(200, 201), json={
        "content_type": _content_type(data), "size_bytes": len(data), "filename": path.name,
    })
    for attempt in range(3):
        try:
            # Exactly the headers Sume signed into the URL, and never the API key.
            put = _send(slot.get("upload_method", "PUT"), slot["upload_url"],
                        data=data, headers=slot.get("upload_headers") or {}, timeout=120)
        except requests.RequestException as e:
            if attempt == 2:
                raise StepError(f"{label}: upload of {path.name} to Sume failed: {e}") from e
            _sleep(_backoff(attempt, cfg))
            continue
        if 200 <= put.status_code < 300:
            break
        if attempt == 2:
            raise StepError(f"{label}: upload of {path.name} to Sume failed: HTTP {put.status_code}")
        _sleep(_backoff(attempt, cfg))
    with _upload_lock:
        _upload_cache[key] = slot["public_url"]
    return slot["public_url"]


# ------------------------------------------------------------------ jobs ----

def submit(endpoint: str, body: dict, label: str, cfg: dict) -> dict:
    """Submit a generation job. One Idempotency-Key per job, reused on every retry, so a
    refusal-then-retry never runs (or charges) the job twice."""
    return _call("POST", _base(cfg) + endpoint, label, cfg, json=body, expect=(200, 201, 202),
                 headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())})


def wait(job: dict, label: str, cfg: dict) -> list[dict]:
    """Poll a submitted job until it is terminal and return its artifacts."""
    status_url = job["status_url"]
    result_url = job["result_url"]
    timeout = float(cfg["job_timeout_seconds"])
    started = time.monotonic()
    state = job
    while not state.get("terminal"):
        if time.monotonic() - started > timeout:
            job_id = (job.get("job") or {}).get("id") or job.get("request_id")
            raise StepError(f"{label}: Sume job {job_id} not finished after {timeout:.0f}s; "
                            f"check it at {status_url}")
        _sleep(max(1.0, float(state.get("next_poll_after_seconds") or 2)))
        state = _call("GET", status_url, label, cfg)
    # A failed or canceled job answers 409 job_failed / job_canceled here, with the reason.
    result = _call("GET", result_url, label, cfg)
    artifacts = (result.get("result") or {}).get("artifacts") or []
    if not artifacts:
        raise StepError(f"{label}: Sume job finished with no artifacts: {str(result)[:300]}")
    print(f"    {label}: Sume job done in {time.monotonic() - started:.0f}s")
    return artifacts


def _artifact_url(artifacts: list[dict], kind: str, label: str) -> str:
    for a in artifacts:
        if a.get("type") == kind and a.get("url"):
            return a["url"]
    for a in artifacts:
        if a.get("url"):
            return a["url"]
    raise StepError(f"{label}: Sume result had no {kind} URL: {artifacts!r}")


def download(url: str, dest: Path) -> Path:
    """Save a finished file. A dropped connection is tried again (see downloads.py)."""
    import downloads
    return downloads.fetch(url, dest, lambda u: _send("GET", u, stream=True, timeout=180), sleep=_sleep)


# --------------------------------------------------------------- models ----

def generate_image(config: dict, prompt: str, aspect_ratio: str, refs: list[Path], label: str) -> str:
    """Nano Banana on Sume: text-to-image, or an edit when reference images are given."""
    cfg = config["sume"]
    body = {"model": cfg["image_model"], "prompt": prompt, "aspect_ratio": aspect_ratio, "num_images": 1}
    if refs:
        body["image_urls"] = [upload(p, cfg, label) for p in refs]
    job = submit(IMAGE_ENDPOINT, body, label, cfg)
    return _artifact_url(wait(job, label, cfg), "image", label)


def generate_video(config: dict, prompt: str, first_frame: Path, label: str) -> str:
    """Seedance 2.0 Fast image-to-video on Sume."""
    cfg = config["sume"]
    body = {
        "model": cfg["video_model"],
        "prompt": prompt,
        "image_url": upload(first_frame, cfg, label),
        "duration": int(cfg["video_seconds"]),
        "resolution": str(cfg["video_resolution"]),
        "aspect_ratio": "9:16",
        "generate_audio": bool(cfg["video_audio"]),
    }
    job = submit(VIDEO_ENDPOINT, body, label, cfg)
    return _artifact_url(wait(job, label, cfg), "video", label)
