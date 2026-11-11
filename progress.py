"""What the running job is doing right now, for the progress bar in the web UI.

One job runs at a time, so this is a single shared record. commands.py says which steps the job
will run and when each one starts; the steps say how many pieces they have to make and tick as
each one finishes. On the command line nothing reads it, and that is fine.

    progress.start(["script", "images", "video", "voice", "assemble"])
    progress.step("images")
    progress.plan(29, "images")      # 29 pictures to make in this step
    progress.tick()                  # one finished (safe to call from worker threads)
    progress.snapshot()              # {"step": "images", "index": 2, "count": 5, "done": 1,
                                     #  "total": 29, "unit": "images", "percent": 7}
"""

from __future__ import annotations

import threading

# Rough share of a full run's time each step takes; only used to place the bar.
WEIGHTS = {"script": 6, "images": 34, "video": 40, "voice": 6, "assemble": 14,
           "story": 8, "scenes": 62, "render": 24}

_lock = threading.Lock()
_state: dict | None = None


def _blank(steps: list[str]) -> dict:
    return {"steps": list(steps), "step": None, "done": 0, "total": 0, "unit": "", "note": ""}


def clear() -> None:
    global _state
    with _lock:
        _state = None


def start(steps: list[str]) -> None:
    """A job begins; `steps` are the steps it will run, in order."""
    global _state
    with _lock:
        _state = _blank(steps)


def step(name: str) -> None:
    """A step begins. A job that never called start() is a one-step job."""
    global _state
    with _lock:
        if _state is None:
            _state = _blank([name])
        if name not in _state["steps"]:
            _state["steps"].append(name)
        _state.update(step=name, done=0, total=0, unit="", note="")


def plan(total: int, unit: str = "") -> None:
    """How many pieces the current step is about to make (0 = nothing to do)."""
    with _lock:
        if _state is not None:
            _state.update(done=0, total=max(0, int(total)), unit=unit, note="")


def add(n: int = 1) -> None:
    """The current step found more pieces to make."""
    with _lock:
        if _state is not None:
            _state["total"] += max(0, int(n))


def tick(n: int = 1) -> None:
    """Pieces finished."""
    with _lock:
        if _state is not None:
            _state["done"] = min(_state["done"] + max(0, int(n)), max(_state["total"], 0))


def note(text: str = "") -> None:
    """What the step is on right now when it is one long piece of work ("final mix 40%"),
    shown beside the step's name in place of the count. Empty clears it."""
    with _lock:
        if _state is not None:
            _state["note"] = str(text or "")


def snapshot() -> dict | None:
    """Where the job is, or None when nothing has reported yet."""
    with _lock:
        if _state is None or _state["step"] is None:
            return None
        st = dict(_state)
    steps = st["steps"]
    index = steps.index(st["step"])
    weights = [WEIGHTS.get(s, 10) for s in steps]
    inside = st["done"] / st["total"] if st["total"] else 0.0
    percent = (sum(weights[:index]) + weights[index] * inside) / (sum(weights) or 1) * 100
    return {"step": st["step"], "index": index + 1, "count": len(steps),
            "done": st["done"], "total": st["total"], "unit": st["unit"],
            "note": st.get("note", ""),
            "percent": max(0, min(99, int(percent)))}
