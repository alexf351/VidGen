"""In-process job runner for the local server: one job at a time on a background thread, the
rest queued. Each job's print output (and that of any worker threads the pipeline starts
while it runs) is captured into the job's log. History is kept in <output dir>/jobs.json.
"""

from __future__ import annotations

import json
import os
import queue
import secrets
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

import progress
from common import StepError

STATUSES = ("queued", "running", "done", "failed")
MAX_LOG_LINES = 5000            # per job, the oldest are dropped past this
MAX_HISTORY = 500               # jobs kept in jobs.json
# Threads the pipeline starts while a job runs (parallel.TaskRunner uses a ThreadPoolExecutor).
_POOL_PREFIX = "ThreadPoolExecutor-"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Job:
    def __init__(self, action: str, run_id: str | None, params: dict):
        self.id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
        self.action = action
        self.run_id = run_id
        self.params = params
        self.status = "queued"
        self.created_at = _now()
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.error: str | None = None
        self.log: list[str] = []
        self.dropped = 0                       # lines dropped from the front of the log
        self.version = 0                       # bumps on every status change
        self._partial: dict[int, str] = {}     # unfinished line per thread
        self.fn: Callable[[Job], None] | None = None

    def write(self, text: str) -> None:
        """Add text to the log. print() sends a line and its newline as two writes, so each
        thread's unfinished line is kept apart; two threads printing at once (the image and
        video steps do) can then never run their lines together."""
        who = threading.get_ident()
        text = (self._partial.get(who, "") + text).replace("\r\n", "\n").replace("\r", "\n")
        *lines, rest = text.split("\n")
        if rest:
            self._partial[who] = rest
        else:
            self._partial.pop(who, None)
        self.log.extend(lines)
        if len(self.log) > MAX_LOG_LINES:
            extra = len(self.log) - MAX_LOG_LINES
            del self.log[:extra]
            self.dropped += extra

    def flush_partial(self) -> None:
        self.log.extend(text for text in self._partial.values() if text)
        self._partial = {}

    def to_dict(self, logs: bool = True, since: int = 0) -> dict:
        d = {"id": self.id, "action": self.action, "run_id": self.run_id, "params": self.params,
             "status": self.status, "created_at": self.created_at, "started_at": self.started_at,
             "finished_at": self.finished_at, "error": self.error,
             "log_lines": self.dropped + len(self.log)}
        if logs:
            start = max(0, since - self.dropped)
            d["log"] = self.log[start:]
            d["log_offset"] = self.dropped + start
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        j = cls.__new__(cls)
        j.id, j.action, j.run_id = d["id"], d["action"], d.get("run_id")
        j.params = d.get("params") or {}
        j.status = d.get("status", "failed")
        j.created_at, j.started_at = d.get("created_at"), d.get("started_at")
        j.finished_at, j.error = d.get("finished_at"), d.get("error")
        j.log = list(d.get("log") or [])
        j.dropped = int(d.get("log_offset") or 0)
        j.version, j._partial, j.fn = 0, {}, None
        return j


class _StreamRouter:
    """Replaces sys.stdout / sys.stderr once. While a job runs, writes from the job thread and
    from pipeline worker-pool threads go to the job's log as well as the console; everything
    else (the web server's own logging) goes to the console only."""

    def __init__(self, original, runner: "JobRunner"):
        self._original = original
        self._runner = runner

    def write(self, text):
        job = self._runner._capturing()
        if job is not None:
            with self._runner._lock:
                job.write(text)
        return self._original.write(text)

    def flush(self):
        return self._original.flush()

    def __getattr__(self, name):
        return getattr(self._original, name)


class JobRunner:
    def __init__(self, history_path: Callable[[], Path]):
        self._history_path = history_path
        self._lock = threading.RLock()
        self._queue: queue.Queue[Job | None] = queue.Queue()
        self.jobs: dict[str, Job] = {}
        self._current: Job | None = None
        self._worker_ident: int | None = None
        self._thread: threading.Thread | None = None
        self._stopped = False
        self._load()

    # ------------------------------------------------------------ history --
    def _load(self) -> None:
        path = self._history_path()
        if not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"[ui] could not read {path} ({e}); starting with no job history", file=sys.stderr)
            return
        changed = False
        for d in raw.get("jobs", []):
            try:
                j = Job.from_dict(d)
            except (KeyError, TypeError):
                continue
            if j.status in ("queued", "running"):
                was = j.status
                j.status = "failed"
                j.finished_at = j.finished_at or _now()
                j.error = ("the VidGen server stopped while this job was running" if was == "running"
                           else "the VidGen server stopped before this job started")
                changed = True
            self.jobs[j.id] = j
        if changed:
            self.save()

    def save(self) -> None:
        with self._lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j.created_at or "")[-MAX_HISTORY:]
            data = {"jobs": [j.to_dict() for j in jobs]}
            path = self._history_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.tmp")
            tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, path)

    # ------------------------------------------------------------ running --
    def start(self) -> None:
        if not isinstance(sys.stdout, _StreamRouter):
            sys.stdout = _StreamRouter(sys.stdout, self)
        if not isinstance(sys.stderr, _StreamRouter):
            sys.stderr = _StreamRouter(sys.stderr, self)
        if self._thread is None:
            self._thread = threading.Thread(target=self._work, name="vidgen-jobs", daemon=True)
            self._thread.start()

    def _capturing(self) -> Job | None:
        job = self._current
        if job is None:
            return None
        t = threading.current_thread()
        if t.ident == self._worker_ident or t.name.startswith(_POOL_PREFIX):
            return job
        return None

    def submit(self, action: str, run_id: str | None, params: dict, fn: Callable[[Job], None],
               preface: list[str] | None = None) -> Job:
        if self._stopped:
            raise StepError("the job runner has stopped")
        job = Job(action, run_id, params)
        job.fn = fn
        for line in preface or []:
            job.log.append(line)
        with self._lock:
            self.jobs[job.id] = job
        self.save()
        self._queue.put(job)
        return job

    def _set_status(self, job: Job, status: str, error: str | None = None) -> None:
        with self._lock:
            if self._stopped:
                return              # shut down: the job was already recorded as failed
            job.status = status
            if status == "running":
                job.started_at = _now()
            if status in ("done", "failed"):
                job.finished_at = _now()
                job.flush_partial()
            if error:
                job.error = error
            job.version += 1
        self.save()

    def _work(self) -> None:
        self._worker_ident = threading.get_ident()
        while True:
            job = self._queue.get()
            if job is None or self._stopped:
                return
            self._current = job
            progress.clear()
            self._set_status(job, "running")
            try:
                job.fn(job)
            except StepError as e:
                print(f"error: {e}", file=sys.stderr)
                self._current = None
                self._set_status(job, "failed", str(e))
            except BaseException as e:   # noqa: BLE001 - a job must never kill the worker
                traceback.print_exc()
                self._current = None
                self._set_status(job, "failed", f"{type(e).__name__}: {e}")
            else:
                self._current = None
                self._set_status(job, "done")
            finally:
                self._current = None
                progress.clear()
                job.fn = None

    def stop(self) -> None:
        """Server shutdown: whatever is running or queued will not finish."""
        with self._lock:
            self._stopped = True
            for j in self.jobs.values():
                if j.status in ("queued", "running"):
                    j.error = ("the VidGen server stopped while this job was running"
                               if j.status == "running" else "the VidGen server stopped before this job started")
                    j.status = "failed"
                    j.finished_at = _now()
                    j.version += 1
        self.save()
        self._queue.put(None)

    # -------------------------------------------------------------- query --
    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self.jobs.values(), key=lambda j: j.created_at or "", reverse=True)

    def active_for_run(self, run_id: str) -> Job | None:
        with self._lock:
            for j in self.jobs.values():
                if j.run_id == run_id and j.status in ("queued", "running"):
                    return j
        return None

    def latest_for_run(self, run_id: str) -> Job | None:
        with self._lock:
            mine = [j for j in self.jobs.values() if j.run_id == run_id]
        return max(mine, key=lambda j: j.created_at or "") if mine else None
