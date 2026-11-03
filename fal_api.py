"""Thin wrapper around the fal-client SDK: key check, calls, uploads, downloads."""

from __future__ import annotations

import os
import time
from pathlib import Path

import requests

from common import StepError

_upload_cache: dict[tuple[str, float], str] = {}


def require_key() -> None:
    if not os.environ.get("FAL_KEY"):
        raise StepError("FAL_KEY is not set; put it in .env (see .env.example)")


def _fal():
    # Imported lazily so the key check above runs first and `--help` never needs the SDK.
    import fal_client
    return fal_client


def call(model: str, arguments: dict, label: str) -> dict:
    """Run a fal model through the queue and block for the result."""
    fal_client = _fal()
    started = time.monotonic()

    def on_update(status):
        if isinstance(status, fal_client.InProgress) and status.logs:
            for entry in status.logs[-1:]:
                msg = entry.get("message") if isinstance(entry, dict) else str(entry)
                if msg:
                    print(f"    {label}: {msg}")

    try:
        result = fal_client.subscribe(model, arguments=arguments, with_logs=True,
                                      on_queue_update=on_update)
    except fal_client.FalClientHTTPError as e:
        raise StepError(f"{label}: fal returned HTTP {e.status_code} from {model}: {e.message}") from e
    except fal_client.FalClientTimeoutError as e:
        raise StepError(f"{label}: fal request to {model} timed out: {e}") from e
    except fal_client.FalClientError as e:
        raise StepError(f"{label}: fal error from {model}: {e}") from e
    print(f"    {label}: done in {time.monotonic() - started:.0f}s")
    return result


def upload(path: Path) -> str:
    """Upload a local file to fal storage and return its URL (cached per file mtime)."""
    path = Path(path)
    key = (str(path.resolve()), path.stat().st_mtime)
    if key not in _upload_cache:
        fal_client = _fal()
        try:
            _upload_cache[key] = fal_client.upload_file(path)
        except fal_client.FalClientError as e:
            raise StepError(f"upload of {path} failed: {e}") from e
    return _upload_cache[key]


def download(url: str, dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
    except requests.RequestException as e:
        tmp.unlink(missing_ok=True)
        raise StepError(f"download of {url} failed: {e}") from e
    tmp.replace(dest)
    return dest


def first_image_url(result: dict, label: str) -> str:
    images = result.get("images") if isinstance(result, dict) else None
    if not images or not images[0].get("url"):
        raise StepError(f"{label}: fal result had no image: {result!r}")
    return images[0]["url"]


def video_url(result: dict, label: str) -> str:
    video = result.get("video") if isinstance(result, dict) else None
    if not video or not video.get("url"):
        raise StepError(f"{label}: fal result had no video: {result!r}")
    return video["url"]
