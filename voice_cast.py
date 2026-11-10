"""Voice casting: give every speaker in a run an ElevenLabs voice that fits them.

A speaker with a voice in config (`voices:` in config.local.yaml, or a library character's own
voice) keeps it. Everyone else, typically the people a format invents for one video, is cast
from the voices in your ElevenLabs account: same gender, close in age, and a different voice for
each person in the video. Gender and age are read from the character's description ("a 31 year
old woman with ...").

    runs/<id>/voices.json     {"voices": {"maya": {"voice_id": "...", "name": "...", "source": "auto"}}}

"source" is "auto" (cast here) or "manual" (you picked it on the run page). An entry here wins
over config for that run, so you can also swap the narrator for one video.

Reading the voice list is a free ElevenLabs call (GET /v1/voices). It is cached for an hour in
cache/elevenlabs_voices.json. If the list cannot be read, nobody is cast and speakers without a
voice use the default `voice_id`, as before.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

import requests

from common import ROOT, StepError, read_json, write_json

API_BASE = "https://api.elevenlabs.io"
CACHE_FILE = ROOT / "cache" / "elevenlabs_voices.json"
CACHE_SECONDS = 3600
VOICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
_memory: dict = {"at": 0.0, "voices": None}


# ------------------------------------------------------------- the catalog ----

def _norm(value) -> str:
    return re.sub(r"[\s-]+", "_", str(value or "").strip().lower())


def _clean(v: dict) -> dict | None:
    if not isinstance(v, dict) or not VOICE_ID_RE.match(str(v.get("voice_id") or "")):
        return None
    labels = v.get("labels") if isinstance(v.get("labels"), dict) else {}
    return {"voice_id": v["voice_id"], "name": str(v.get("name") or v["voice_id"]),
            "category": str(v.get("category") or ""),
            "gender": _norm(labels.get("gender")), "age": _norm(labels.get("age")),
            "accent": str(labels.get("accent") or ""), "description": str(labels.get("description") or ""),
            "use_case": str(labels.get("use_case") or ""),
            "preview_url": str(v.get("preview_url") or "")}


def fetch_voices() -> list[dict]:
    """Every voice in the ElevenLabs account (yours and the stock ones). One free API call."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise StepError("ELEVENLABS_API_KEY is not set, so the voice list cannot be read")
    try:
        r = requests.get(f"{API_BASE}/v1/voices", headers={"xi-api-key": key}, timeout=30)
    except requests.RequestException as e:
        raise StepError(f"could not reach ElevenLabs for the voice list: {e}") from e
    if r.status_code != 200:
        raise StepError(f"ElevenLabs returned HTTP {r.status_code} for the voice list: {r.text[:200]}")
    try:
        raw = r.json().get("voices") or []
    except (ValueError, AttributeError):
        raise StepError("ElevenLabs returned an unreadable voice list") from None
    voices = [c for c in (_clean(v) for v in raw) if c]
    voices.sort(key=lambda v: v["name"].lower())
    return voices


def list_voices(refresh: bool = False) -> list[dict]:
    """The voice list, from memory or cache/elevenlabs_voices.json when fresh, else fetched."""
    now = time.time()
    if not refresh and _memory["voices"] is not None and now - _memory["at"] < CACHE_SECONDS:
        return _memory["voices"]
    if not refresh and CACHE_FILE.is_file() and now - CACHE_FILE.stat().st_mtime < CACHE_SECONDS:
        try:
            voices = [v for v in read_json(CACHE_FILE).get("voices", []) if isinstance(v, dict)]
            _memory.update(at=CACHE_FILE.stat().st_mtime, voices=voices)
            return voices
        except (OSError, ValueError, AttributeError):
            pass
    voices = fetch_voices()
    _memory.update(at=now, voices=voices)
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        write_json(CACHE_FILE, {"voices": voices})
    except OSError:
        pass
    return voices


# ----------------------------------------------------------- who is speaking ----

_FEMALE = r"\b(woman|women|girl|female|lady|mother|mom|grandmother|grandma|wife|daughter|sister|aunt|queen|actress|she|her)\b"
_MALE = r"\b(man|men|guy|boy|male|gentleman|father|dad|grandfather|grandpa|husband|son|brother|uncle|king|dude|he|his)\b"


def traits(description: str) -> dict:
    """{"gender": "male"|"female"|"", "age": "young"|"middle_aged"|"old"|""} from a description
    like "a 31 year old woman with curly hair"."""
    text = str(description or "").lower()
    f, m = re.search(_FEMALE, text), re.search(_MALE, text)
    gender = ""
    if f and (not m or f.start() < m.start()):
        gender = "female"
    elif m:
        gender = "male"
    age = ""
    years = re.search(r"\b(\d{1,3})[\s-]*(?:year|yr)s?[\s-]*old\b", text) or re.search(r"\bin (?:his|her|their) (\d{2})s\b", text)
    if years:
        n = int(years.group(1))
        age = "young" if n < 35 else "middle_aged" if n < 56 else "old"
    elif re.search(r"\b(elderly|old man|old woman|grandmother|grandfather|grandma|grandpa|senior)\b", text):
        age = "old"
    elif re.search(r"\b(young|teen|twenties|student)\b", text):
        age = "young"
    elif re.search(r"\b(middle[\s-]aged|forties|fifties)\b", text):
        age = "middle_aged"
    return {"gender": gender, "age": age}


def speakers(script: dict) -> list[str]:
    """Character ids (and "narrator") that say at least one line, in order of first line."""
    out: list[str] = []
    if isinstance(script.get("song"), dict):
        return out                                 # a song is sung by the music model
    for s in script.get("shots", []):
        if not isinstance(s, dict) or not str(s.get("vo_line") or "").strip():
            continue
        who = s.get("speaker") or "narrator"
        if who not in out:
            out.append(who)
    return out


# ------------------------------------------------------------------ the run ----

def voices_path(run_dir: Path) -> Path:
    return Path(run_dir) / "voices.json"


def run_voices(run_dir: Path) -> dict[str, dict]:
    p = voices_path(run_dir)
    if not p.is_file():
        return {}
    try:
        data = read_json(p).get("voices") or {}
    except (OSError, ValueError, AttributeError):
        return {}
    return {k: v for k, v in data.items()
            if isinstance(v, dict) and VOICE_ID_RE.match(str(v.get("voice_id") or ""))}


def voice_for(run_dir: Path, speaker: str, config: dict) -> str:
    """This run's voice for a speaker: the run's own choice, else config, else the default."""
    mine = run_voices(run_dir).get(speaker)
    if mine:
        return mine["voice_id"]
    return (config.get("voices") or {}).get(speaker, "") or config["voice_id"]


def source_of(run_dir: Path, speaker: str, config: dict) -> str:
    mine = run_voices(run_dir).get(speaker)
    if mine:
        return "manual" if mine.get("source") == "manual" else "auto"
    return "config" if (config.get("voices") or {}).get(speaker) else "default"


def _rank(seed: str, voice_id: str) -> str:
    return hashlib.sha1(f"{seed}:{voice_id}".encode()).hexdigest()


def pick(want: dict, voices: list[dict], used: set[str], seed: str) -> dict | None:
    """The best voice for these traits: right gender first, then age, then one nobody else in
    the video has. Ties are broken by the run's id, so a run always gets the same answer and
    different runs get different voices."""
    if not voices:
        return None

    def score(v: dict) -> int:
        s = 0
        if want.get("gender"):
            s += 10 if v["gender"] == want["gender"] else (-10 if v["gender"] else -2)
        if want.get("age") and v["age"]:
            s += 3 if v["age"] == want["age"] else -1
        if v["voice_id"] in used:
            s -= 6
        return s
    return max(voices, key=lambda v: (score(v), _rank(seed, v["voice_id"])))


def ensure_cast(run_dir: Path, config: dict, script: dict, log=print) -> dict[str, dict]:
    """Cast every speaker that has no voice yet (not the narrator, not anyone with a config
    voice). Returns the run's voices. Never fails the step: on any problem it says so and the
    uncast speakers keep the default voice."""
    settings = config.get("voice_casting") or {}
    current = run_voices(run_dir)
    if settings.get("enabled", True) is False:
        return current
    configured = {k for k, v in (config.get("voices") or {}).items() if v}
    todo = [who for who in speakers(script)
            if who != "narrator" and who not in configured and who not in current]
    if not todo:
        return current
    try:
        catalog = list_voices()
    except StepError as e:
        log(f"[voices] not casting voices: {e}")
        return current
    exclude = {str(x) for x in (settings.get("exclude") or [])}
    pool = [v for v in catalog if v["voice_id"] not in exclude]
    if not pool:
        log("[voices] your ElevenLabs account lists no voices to cast from")
        return current
    used = {v["voice_id"] for v in current.values()} | {config["voice_id"]} | \
        {v for v in (config.get("voices") or {}).values() if v}
    desc = {c["id"]: c.get("description", "") for c in script.get("characters", []) if isinstance(c, dict)}
    for c in config.get("locked_characters", []):
        desc.setdefault(c["id"], c.get("description", ""))
    log(f"[voices] casting {len(todo)} speaker(s) from {len(pool)} ElevenLabs voices")
    for who in todo:
        want = traits(desc.get(who, ""))
        v = pick(want, pool, used, f"{Path(run_dir).name}:{who}")
        if v is None:
            continue
        used.add(v["voice_id"])
        current[who] = {"voice_id": v["voice_id"], "name": v["name"], "source": "auto"}
        looking = ", ".join(x for x in (want["gender"], want["age"].replace("_", " ")) if x) or "no gender or age in the description"
        got = ", ".join(x for x in (v["gender"], v["age"].replace("_", " "), v["accent"]) if x)
        warn = "  (no voice of that gender in your account)" if want["gender"] and v["gender"] != want["gender"] else ""
        log(f"  {who} ({looking}) -> {v['name']} ({got}){warn}")
    write_json(voices_path(run_dir), {"voices": current})
    return current


def set_voice(run_dir: Path, speaker: str, voice_id: str | None, name: str = "") -> dict[str, dict]:
    """Your pick for one speaker in this run ("manual"); None or "" removes the run's choice."""
    current = run_voices(run_dir)
    if not voice_id:
        current.pop(speaker, None)
    else:
        if not VOICE_ID_RE.match(voice_id):
            raise StepError("that does not look like an ElevenLabs voice id")
        current[speaker] = {"voice_id": voice_id, "name": name, "source": "manual"}
    write_json(voices_path(run_dir), {"voices": current})
    return current


def summary(run_dir: Path, config: dict, script: dict | None) -> list[dict]:
    """For the run page: every speaker, their voice id and where it came from."""
    if not script:
        return []
    mine = run_voices(run_dir)
    desc = {c["id"]: c.get("description", "") for c in script.get("characters", []) if isinstance(c, dict)}
    lines: dict[str, list[int]] = {}
    for s in script.get("shots", []):
        if isinstance(s, dict) and str(s.get("vo_line") or "").strip():
            lines.setdefault(s.get("speaker") or "narrator", []).append(s.get("n"))
    out = []
    for who in speakers(script):
        out.append({"speaker": who, "voice_id": voice_for(run_dir, who, config),
                    "source": source_of(run_dir, who, config), "name": (mine.get(who) or {}).get("name", ""),
                    "shots": lines.get(who, []), **traits(desc.get(who, ""))})
    return out
