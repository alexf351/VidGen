"""How long a video runs: Short, Standard or Long, chosen per video.

Every format is written for one length (its `duration_target`, e.g. "about 15-25 seconds"), and
its rules count for that length: how many shots, how many spoken words, how many may move. That
length is the format's own band, and it is the default. A video can ask for a longer band; its
counts are then scaled up and the script writer is told where the extra time goes (more story,
never padding). Shorter than the format was written for is not offered: the formats are already
at their shortest (a montage, a time card and a call to action do not fit in half the shots).

    BANDS                        the three lengths and their seconds
    native(fmt)                  the band the format was written for
    options(fmt)                 the bands a video of this format may pick, its own first
    run_choice(run_dir)          the band a video asked for, or None (its format's own)
    set_for_run(run_dir, value)  save it (None = the format's own)
    apply(config, run_dir|band)  the config a job on this video uses: counts scaled, a note added

A format can narrow its choice in format.yaml: `lengths: [short, standard]`."""

from __future__ import annotations

import math
import re
from pathlib import Path

from common import StepError, read_json, write_json

BANDS = {                       # name: (title, seconds low, seconds high)
    "short": ("Short", 15, 30),
    "standard": ("Standard", 40, 60),
    "long": ("Long", 75, 100),
}
ORDER = list(BANDS)
WORDS_PER_SECOND_MAX = 2.7


def check(value) -> str:
    v = str(value or "").strip().lower()
    if v not in BANDS:
        raise StepError(f"length must be one of {', '.join(ORDER)}, got {value!r}")
    return v


def _seconds(fmt: dict) -> tuple[float, float] | None:
    """(low, high) from a duration_target like "about 40-45 seconds", or None."""
    m = re.search(r"(\d+)\s*(?:-|–|to)\s*(\d+)\s*s", str(fmt.get("duration_target") or ""))
    if not m:
        return None
    lo, hi = float(m.group(1)), float(m.group(2))
    return (lo, hi) if lo <= hi else (hi, lo)


def _mid(lo: float, hi: float) -> float:
    return (lo + hi) / 2


def native(fmt: dict) -> str:
    """The band nearest the length the format was written for (short when it does not say)."""
    s = _seconds(fmt)
    if not s:
        return "short"
    m = _mid(*s)
    return min(ORDER, key=lambda b: abs(_mid(*BANDS[b][1:]) - m))


def options(fmt: dict) -> list[str]:
    """The bands this format offers: its own, then the longer ones (or what format.yaml lists)."""
    own = native(fmt)
    allowed = [b for b in ORDER[ORDER.index(own):]]
    listed = fmt.get("lengths")
    if listed:
        allowed = [b for b in allowed if b in listed] or [own]
    return allowed


def describe(fmt: dict) -> list[dict]:
    """The choice as the create screen shows it: id, title, seconds, shots, default."""
    own = native(fmt)
    out = []
    for b in options(fmt):
        r = scaled_rules(fmt, b)
        lo, hi = r["seconds"]
        out.append({"id": b, "title": BANDS[b][0], "seconds": f"{lo:.0f}-{hi:.0f} s",
                    "shots": r.get("story_shots"), "words": r.get("vo_words"), "default": b == own})
    return out


def factor(fmt: dict, band: str) -> float:
    """How much longer than the format's own length this band is (1 for its own)."""
    if band == native(fmt):
        return 1.0
    s = _seconds(fmt) or BANDS["short"][1:]
    return _mid(*BANDS[band][1:]) / _mid(*s)


def _scale_pair(pair, f: float) -> list[int]:
    lo, hi = max(1, round(pair[0] * f)), max(1, round(pair[1] * f))
    return [lo, max(lo, hi)]


def scaled_rules(fmt: dict, band: str) -> dict:
    """The counts of `fmt` for a video of this band (only the ones that change)."""
    f = factor(fmt, band)
    rules = fmt.get("rules") or {}
    s = _seconds(fmt) or BANDS["short"][1:]
    out: dict = {"factor": f, "seconds": s if f == 1 else BANDS[band][1:]}
    for key in ("story_shots", "vo_words"):
        if rules.get(key):
            out[key] = list(rules[key]) if f == 1 else _scale_pair(rules[key], f)
    if f != 1 and out.get("vo_words"):            # nobody follows faster than about 2.7 words a second
        cap = round(WORDS_PER_SECOND_MAX * BANDS[band][2])
        out["vo_words"] = [min(out["vo_words"][0], cap), min(out["vo_words"][1], cap)]
    return out


def run_choice(run_dir: Path | None) -> str | None:
    if run_dir is None:
        return None
    try:
        value = read_json(Path(run_dir) / "run.json").get("length")
    except (OSError, ValueError, AttributeError):
        return None
    return value if value in BANDS else None


def set_for_run(run_dir: Path, value: str | None) -> str | None:
    path = Path(run_dir) / "run.json"
    meta = read_json(path)
    if value is None:
        meta.pop("length", None)
    else:
        meta["length"] = check(value)
    write_json(path, meta)
    return run_choice(run_dir)


def note(fmt: dict, band: str) -> str:
    """What the script writer is told about a longer video ("" for the format's own length)."""
    r = scaled_rules(fmt, band)
    if r["factor"] == 1:
        return ""
    lo, hi = r["seconds"]
    counts = []
    if r.get("story_shots"):
        counts.append(f"{r['story_shots'][0]}-{r['story_shots'][1]} shots")
    if r.get("vo_words"):
        counts.append(f"{r['vo_words'][0]}-{r['vo_words'][1]} spoken words")
    return (f"LENGTH: this video runs longer than this format usually does ({fmt.get('duration_target')}): "
            f"about {lo:.0f}-{hi:.0f} seconds" + (f", {' and '.join(counts)}" if counts else "") + ". These "
            "numbers replace every length and shot count given above, and a count of shots for one part of "
            "the story (flashes, a montage) grows with it. Keep every beat of the format, "
            "in the same order. Spend the extra time on the story itself: a first try that fails before the "
            "turn, a setback that raises the stakes, more of the change shown as things happening, a payoff "
            "that lands on someone from the start. Never pad: no shot that repeats an earlier one, no line "
            "that only restates what we see, no longer speeches.")


def apply(config: dict, run_dir: Path | None = None, band: str | None = None) -> dict:
    """`config` for a video of this length: its rules' counts scaled and the note added to the
    format, so the script step, the validator and the cost estimate all see the same numbers.
    The band is the video's own choice (run.json) unless given. Safe to call twice. Changes and
    returns `config`."""
    fmt = config["format"]
    want = band or run_choice(run_dir)
    if not want or config.get("_length") or want not in options(fmt):
        return config
    f = factor(fmt, want)
    config["_length"] = want
    if f == 1:
        return config
    text = note(fmt, want)                        # before the counts change: it states both
    rules = fmt["rules"]
    for key, value in scaled_rules(fmt, want).items():
        if key in ("story_shots", "vo_words"):
            rules[key] = value
    for key in ("flashes", "stats"):
        if rules.get(key) and rules[key].get("count"):
            rules[key]["count"] = _scale_pair(rules[key]["count"], f)
    if rules.get("montage"):                      # a montage grows, but less: it is a burst
        rules["montage"]["count"] = _scale_pair(rules["montage"]["count"], math.sqrt(f))
    if rules.get("talking"):
        rules["talking"]["max"] = math.ceil(rules["talking"]["max"] * f)
    if rules.get("app_screens") and rules["app_screens"].get("max"):
        rules["app_screens"]["max"] = math.ceil(rules["app_screens"]["max"] * f)
    if config.get("max_animated_shots"):
        config["max_animated_shots"] = math.ceil(int(config["max_animated_shots"]) * f)
    lo, hi = BANDS[want][1:]
    fmt["length_note"] = text
    fmt["duration_target"] = f"about {lo}-{hi} seconds"
    return config
