"""Downloading finished images and clips without losing them to a dropped connection.

A provider can finish a clip (which is what costs money) and then drop the connection while the
file is being downloaded. Two things keep that from wasting the clip:

  * fetch() tries the download several times, with a growing pause between tries.
  * Before downloading, the step notes the file's address next to where it will be saved
    (shots/18.mp4.url). If every try fails, the next run of the step downloads from that address
    first, and only generates again if the address no longer works.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import requests

from common import StepError

ATTEMPTS = 5
PAUSES = (2, 5, 10, 20)             # seconds before tries 2, 3, 4, 5
_RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


def fetch(url: str, dest: Path, get: Callable[[str], requests.Response],
          sleep: Callable[[float], None] = time.sleep, attempts: int = ATTEMPTS) -> Path:
    """Download `url` to `dest` (through a .part file). `get(url)` opens a streaming response.
    Dropped connections, timeouts and busy-server replies are tried again; a plain refusal
    (403, 404) is not."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last = ""
    for attempt in range(1, attempts + 1):
        again = True
        try:
            with get(url) as r:
                status = getattr(r, "status_code", 200)
                if status in _RETRY_STATUS:
                    last = f"HTTP {status}"
                else:
                    try:
                        r.raise_for_status()
                    except requests.HTTPError as e:
                        last, again = str(e), False
                    else:
                        with open(tmp, "wb") as f:
                            for chunk in r.iter_content(chunk_size=1 << 16):
                                f.write(chunk)
                        tmp.replace(dest)
                        return dest
        except requests.RequestException as e:
            last = str(e)
        tmp.unlink(missing_ok=True)
        if not again or attempt == attempts:
            break
        pause = PAUSES[min(attempt - 1, len(PAUSES) - 1)]
        print(f"  download did not finish ({last}); trying again in {pause}s "
              f"(try {attempt + 1} of {attempts})")
        sleep(pause)
    raise StepError(f"download of {url} failed: {last}")


def _note(dest: Path) -> Path:
    dest = Path(dest)
    return dest.with_name(dest.name + ".url")


def remember(dest: Path, url: str) -> None:
    """Note where a finished file lives before downloading it."""
    try:
        _note(dest).parent.mkdir(parents=True, exist_ok=True)
        _note(dest).write_text(url.strip() + "\n", encoding="utf-8")
    except OSError:
        pass


def forget(dest: Path) -> None:
    _note(dest).unlink(missing_ok=True)


def save(url: str, dest: Path, download: Callable[[str, Path], Path]) -> Path:
    """Download a freshly generated file, keeping its address until it is safely on disk."""
    remember(dest, url)
    download(url, dest)
    forget(dest)
    return Path(dest)


def resume(dest: Path, download: Callable[[str, Path], Path], label: str) -> bool:
    """If an earlier run generated this file but could not download it, download it now.
    True when the file is in place; False means it has to be generated (again)."""
    note = _note(dest)
    if not note.is_file():
        return False
    try:
        url = note.read_text(encoding="utf-8").strip()
    except OSError:
        url = ""
    if url.startswith("http"):
        try:
            download(url, dest)
        except StepError:
            print(f"  {label}: the file made earlier is no longer available, generating it again")
        else:
            forget(dest)
            print(f"  {label}: downloaded the file that was made earlier (nothing generated again)")
            return True
    forget(dest)
    return False
