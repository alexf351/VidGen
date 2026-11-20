"""Choice stories as a series: every episode ends on a choice, the comments vote, and the next
episode starts from what they chose.

    <output folder>/_stories/<series id>/
        series.json            its name, the premise, whether Iro is in the story, the end words
        ep01/episode.json      the script of episode 1 (stickstory.py draws it)
        ep01/voice.mp3 .json   the narrator and when each word is said
        ep01/final.mp4         the video
        ep01/cover.jpg         a still for the cover
        ep01/caption.txt       the text for the post

    create(name, premise)                 a new series, no episode yet
    write_first(series, config)           Claude writes episode 1 from the premise   (one request)
    write_next(series, "a" | "b", config) Claude writes the next one from the story so far and the vote
    add_episode(series_id, script)        put a script in (yours, a starter, or one Claude wrote)
    produce(series_id, n, config)         narrator (ElevenLabs, if there is a key), sound, video

Drawing costs nothing. An episode's narration is about 500 characters of ElevenLabs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

import stickstory
from common import ROOT, StepError, read_json, runs_dir, slugify, write_json

STARTER_FILE = ROOT / "assets" / "story_starters.json"
DEFAULT_TAG = "SEARCH IRO AI"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,80}$")
MAX_EPISODES = 60
PREMISE_MAX = 600
RENDER_VERSION = 1                 # bump when the drawing changes enough that old videos should be made again


def root() -> Path:
    return runs_dir() / "_stories"


def series_dir(series_id: str, must_exist: bool = True) -> Path:
    if not isinstance(series_id, str) or not ID_RE.match(series_id):
        raise StepError(f"{series_id!r} is not a story series")
    path = root() / series_id
    if must_exist and not (path / "series.json").is_file():
        raise StepError(f"there is no story series called {series_id}")
    return path


def episode_dir(series_id: str, n: int) -> Path:
    return series_dir(series_id) / f"ep{int(n):02d}"


def load(series_id: str) -> dict:
    data = read_json(series_dir(series_id) / "series.json")
    data.setdefault("episodes", 0)
    return data


def _save(series_id: str, data: dict) -> None:
    path = series_dir(series_id, must_exist=False)
    path.mkdir(parents=True, exist_ok=True)
    tmp = path / "series.json.tmp"
    write_json(tmp, data)
    tmp.replace(path / "series.json")


def _tag(end_tag) -> str:
    return "" if end_tag is None else " ".join(str(end_tag).upper().split())[:28]


def create(name: str, premise: str = "", iro: bool = True, end_tag: str | None = DEFAULT_TAG, voice_id: str = "") -> dict:
    """A new series with no episode yet."""
    premise = " ".join(str(premise or "").split())[:PREMISE_MAX]
    name = " ".join(str(name or "").split())[:60] or (premise[:40] or "Story")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    series_id = f"{stamp}-{slugify(name, 28) or 'story'}"
    k = 2
    while (root() / series_id).exists():
        series_id = f"{stamp}-{slugify(name, 24) or 'story'}-{k}"
        k += 1
    data = {"id": series_id, "name": name, "premise": premise, "iro": bool(iro), "end_tag": _tag(end_tag),
            "voice_id": str(voice_id or "").strip(), "created_at": datetime.now().isoformat(timespec="seconds"), "episodes": 0}
    _save(series_id, data)
    return data


def update(series_id: str, changes: dict) -> dict:
    """Change a series' name, end words, narrator or whether Iro is in it."""
    data = load(series_id)
    if "name" in changes and str(changes["name"] or "").strip():
        data["name"] = " ".join(str(changes["name"]).split())[:60]
    if "end_tag" in changes:
        data["end_tag"] = _tag(changes["end_tag"])
    if "voice_id" in changes:
        data["voice_id"] = str(changes["voice_id"] or "").strip()
    if "iro" in changes:
        data["iro"] = bool(changes["iro"])
    _save(series_id, data)
    return data


def set_note(series_id: str, writing: dict | None = None, error: str | None = None) -> dict:
    """Mark a series as waiting for an episode to be written, done waiting, or failed with a reason."""
    data = load(series_id)
    if writing:
        data["writing"] = dict(writing)
    else:
        data.pop("writing", None)
    if error:
        data["error"] = str(error)[:400]
    else:
        data.pop("error", None)
    _save(series_id, data)
    return data


def delete(series_id: str) -> None:
    shutil.rmtree(series_dir(series_id))


# -------------------------------------------------------------------- episodes ----

def load_episode(series_id: str, n: int) -> dict:
    path = episode_dir(series_id, n) / "episode.json"
    if not path.is_file():
        raise StepError(f"this series has no episode {n}")
    return read_json(path)


def _write_episode(series_id: str, n: int, ep: dict) -> None:
    folder = episode_dir(series_id, n)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / "episode.json.tmp"
    write_json(tmp, ep)
    tmp.replace(folder / "episode.json")
    (folder / "caption.txt").write_text((ep.get("caption") or "") + "\n", encoding="utf-8")


def add_episode(series_id: str, script: dict, voted: str | None = None) -> dict:
    """Put a script in as the series' next episode. `voted` is the choice that won the last one."""
    data = load(series_id)
    if data["episodes"] >= MAX_EPISODES:
        raise StepError(f"a series holds at most {MAX_EPISODES} episodes")
    ep = stickstory.clean_episode(script)
    n = data["episodes"] + 1
    ep["part"] = n
    if n > 1 and voted:
        ep["voted"] = " ".join(str(voted).upper().split())
    else:
        ep.pop("voted", None)
    if not data.get("iro", True):
        for s in ep["shots"]:
            s["iro"] = False
    problems = stickstory.check_episode(ep)
    if problems:
        raise StepError("this episode cannot be drawn: " + "; ".join(problems[:4]))
    if not ep["title"]:
        ep["title"] = f"Part {n}"
    _write_episode(series_id, n, ep)
    data["episodes"] = n
    _save(series_id, data)
    return ep


def save_episode(series_id: str, n: int, script: dict) -> dict:
    """Replace an episode's script (an edit). Its part number and the vote it opens with stay."""
    old = load_episode(series_id, n)
    ep = stickstory.clean_episode(script)
    ep["part"] = int(n)
    if old.get("voted") and int(n) > 1:
        ep["voted"] = old["voted"]
    else:
        ep.pop("voted", None)
    problems = stickstory.check_episode(ep)
    if problems:
        raise StepError("; ".join(problems[:6]))
    if not ep["title"]:
        ep["title"] = old.get("title") or f"Part {n}"
    _write_episode(series_id, n, ep)
    return ep


def delete_last_episode(series_id: str) -> dict:
    """Take the newest episode out (to write it again, or after a vote went the other way)."""
    data = load(series_id)
    if data["episodes"] < 1:
        raise StepError("this series has no episode to remove")
    shutil.rmtree(episode_dir(series_id, data["episodes"]), ignore_errors=True)
    data["episodes"] -= 1
    _save(series_id, data)
    return data


def _key(ep: dict, end_tag: str, voiced: bool) -> str:
    """Changes whenever the video an episode makes would change."""
    return hashlib.sha1(json.dumps([RENDER_VERSION, stickstory.clean_episode(ep), end_tag, voiced], sort_keys=True).encode()).hexdigest()[:16]


def _made(series_id: str, n: int) -> dict:
    path = episode_dir(series_id, n) / "made.json"
    try:
        return read_json(path) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def episode_state(series_id: str, n: int, data: dict | None = None) -> dict:
    """An episode's script and what is made of it."""
    data = data or load(series_id)
    ep = load_episode(series_id, n)
    folder = episode_dir(series_id, n)
    made = _made(series_id, n)
    video = folder / "final.mp4"
    current = video.is_file() and made.get("key") == _key(ep, data.get("end_tag", ""), bool(made.get("voiced")))
    words = sum(len(s["say"].split()) for s in ep["shots"])
    return {"n": int(n), "episode": ep, "made": bool(current), "stale": video.is_file() and not current,
            "voiced": bool(made.get("voiced")) if video.is_file() else False, "seconds": made.get("seconds"),
            "words": words, "folder": str(folder)}


def summary(data: dict) -> dict:
    sid = data["id"]
    made = 0
    last = None
    for n in range(1, data["episodes"] + 1):
        try:
            st = episode_state(sid, n, data)
        except StepError:
            continue
        made += st["made"]
        last = st
    return {"id": sid, "name": data.get("name") or sid, "premise": data.get("premise", ""), "created_at": data.get("created_at"),
            "episodes": data["episodes"], "made": made, "iro": bool(data.get("iro", True)), "end_tag": data.get("end_tag", ""),
            "voice_id": data.get("voice_id", ""), "writing": bool(data.get("writing")), "error": data.get("error"),
            "next_choice": None if last is None else {"a": last["episode"]["a"], "b": last["episode"]["b"], "question": last["episode"]["question"]}}


def all_series() -> list[dict]:
    """Every series, newest first."""
    out = []
    if root().is_dir():
        for d in sorted(root().iterdir(), reverse=True):
            if d.is_dir() and (d / "series.json").is_file() and ID_RE.match(d.name):
                try:
                    out.append(summary(load(d.name)))
                except (StepError, OSError, ValueError, KeyError):
                    continue
    return out


def starters() -> list[dict]:
    """The stories that ship with VidGen: a name, a premise, and for some a finished first episode."""
    if not STARTER_FILE.is_file():
        return []
    out = []
    for s in (read_json(STARTER_FILE) or {}).get("stories") or []:
        if isinstance(s, dict) and s.get("id") and s.get("premise"):
            out.append({"id": str(s["id"]), "name": str(s.get("name") or s["id"]), "premise": str(s["premise"]),
                        "episode": s.get("episode") if isinstance(s.get("episode"), dict) else None})
    return out


# -------------------------------------------------------------- making the video ----

def voice_id_for(data: dict, config: dict) -> str:
    return data.get("voice_id") or (config.get("voices") or {}).get("narrator", "") or config.get("voice_id", "")


def produce(series_id: str, n: int, config: dict, voice: bool = True, again: bool = False, workers: int = 4, log=print) -> dict:
    """Make an episode's video: the narrator (if there is an ElevenLabs key), the sound, the
    drawing. A narration already read for the same words and voice is not paid for twice."""
    import story_sound
    data = load(series_id)
    ep = load_episode(series_id, n)
    folder = episode_dir(series_id, n)
    tag = data.get("end_tag", "")
    text = " ".join(s["say"] for s in ep["shots"])
    vid = voice_id_for(data, config)
    voice_file, voice_json = folder / "voice.mp3", folder / "voice.json"
    voice_data = None
    want_voice = bool(voice) and bool(os.environ.get("ELEVENLABS_API_KEY")) and bool(vid)
    if want_voice:
        sig = hashlib.sha1(f"{vid}|{text}".encode()).hexdigest()[:16]
        saved = {}
        if voice_json.is_file() and voice_file.is_file():
            try:
                saved = read_json(voice_json)
            except (OSError, ValueError):
                saved = {}
        if saved.get("sig") == sig:
            voice_data = saved
            log(f"[story] part {n}: the narration is already read; using it")
        else:
            log(f"[story] part {n}: the narrator reads {len(text.split())} words ({len(text)} characters) with voice {vid}...")
            audio, voice_data = story_sound.narrate(ep, config, vid)
            voice_file.write_bytes(audio)
            voice_data["sig"] = sig
            write_json(voice_json, voice_data)
    elif voice:
        log(f"[story] part {n}: no ElevenLabs key, so this video has no narrator (the words on screen keep an even pace)")
    timing = stickstory.plan(ep, voice_data)
    voiced = bool(voice_data) and timing["voiced"]
    if voice_data and not voiced:
        log(f"[story] part {n}: the narration's words did not line up with the script; the words on screen keep an even pace")
    key = _key(ep, tag, voiced)
    video = folder / "final.mp4"
    if not again and video.is_file() and _made(series_id, n).get("key") == key:
        log(f"[story] part {n}: the video is already made")
        return {"n": n, "made": False, "seconds": _made(series_id, n).get("seconds"), "voiced": voiced}
    started = time.time()
    sound = story_sound.mix(folder / "sound.wav", timing["total"], voice_file if voice_data else None, story_sound.cues(ep, timing))
    log(f"[story] part {n}: drawing {timing['total']:.0f} seconds of video (no model is called; this is free)...")
    last = [0]

    def on_frame(i: int, total: int) -> None:
        pct = int(i * 10 / total)
        if pct > last[0]:
            last[0] = pct
            log(f"  {pct * 10}%")
    stickstory.render(ep, video, timing, audio=sound, end_tag=tag, workers=workers, on_frame=on_frame)
    first = timing["shots"][0]
    cover_at = 1.0 if ep.get("voted") else min(timing["total"] - 0.1, first["start"] + (first["end"] - first["start"]) * 0.6)
    stickstory.frame(ep, cover_at, timing, tag).save(folder / "cover.jpg", quality=90)
    write_json(folder / "made.json", {"key": key, "voiced": voiced, "seconds": timing["total"],
                                      "at": datetime.now().isoformat(timespec="seconds")})
    log(f"[story] part {n}: made in {time.time() - started:.0f}s: {video}")
    return {"n": n, "made": True, "seconds": timing["total"], "voiced": voiced}


# ------------------------------------------------------------ Claude writes it ----

WRITER = """You write episodes of a serial story for short vertical videos. The viewer is the hero: it is
told to them in the second person, present tense ("you"). The pictures are stick figures in dark
flat rooms, drawn by a program from the script you write. Every episode ends on a choice between
two things the hero can do, the viewers vote in the comments, and the next episode starts from
the choice that won.

WHAT MAKES AN EPISODE WORK
- The first line is the hook and it lands in two seconds. Episode 1 opens with "Imagine you" and
  something already wrong. Later episodes open with the vote: "You chose to hide." and what it cost.
- Every shot changes something: a sound, a light, a door, someone arriving, a rule of the place.
  No shot only describes a feeling.
- One strange detail a viewer will repeat to a friend ("the voice sounds exactly like your mom").
- It ends at the worst possible moment, on a choice with no safe answer. Both choices must be
  things a person might really do, and each must lead somewhere different.
- Short plain sentences a fourteen year old would say. No gore, no real people, no brand names,
  nothing sexual, no weapons used on people. Dread, not violence.

THE SCRIPT IS JSON
{{"title": "two to four words",
  "shots": [ ... {shots_min} to {shots_max} shots ... ],
  "question": "the last line, the choice as a question",
  "a": "ONE OR TWO WORDS", "b": "ONE OR TWO WORDS",
  "recap": "one or two sentences: what is true now, for whoever writes the next episode",
  "caption": "the text under the post: one lower case line, then a short question. no hashtags, no emoji, no app or product names"}}

A SHOT
{{"say": "what the narrator says over this shot, at most {say_max} words",
  "set": one of the sets, "light": one of the lights,
  "you": {{"pose": a pose, "at": a place, "to": a place (only if you move), "face": "left" or "right" (optional)}},
        or null when you are not in the picture,
  "them": {{"kind": a kind, "pose": a pose, "at": a place, "to": a place, "count": 2 to 6 for a crowd,
           "eyes": "red" | "green" | "white" | "none"}}  (leave out when nobody else is there),
  "iro": true or false, "event": one of the events (at most one a shot), "target": "door" or "window",
  "door": "closed" or "open" (how the door is when the shot starts), "camera": "push" | "still" | "pull" | "shake",
  "banner": "a few words at the top, like 3:07 AM or DAY 2 (optional, at most 18 letters)"}}

SETS
{sets}

LIGHTS
{lights}

POSES
{poses}
  ("lie" in the bedroom is in the bed; "sit" is on the couch or the bed when you are at it; a figure
  with "to" walks there; "run" with "to" runs there)

WHO ELSE ("them".kind)
{kinds}

EVENTS (each has its own sound)
{events}

PLACES ("at" and "to")
far_left, left, center, right, far_right, off_left and off_right (outside the picture, to walk in
or out), door, window, a number from 0 (left edge) to 1 (right edge), and in some sets: {spots}

RULES THE PROGRAM CHECKS
- {shots_min} to {shots_max} shots. All the "say" lines together are {words_min} to {words_max} words: about
  thirty seconds read aloud. One or two short sentences a shot.
- The last shot's "say" is the question, and "question" repeats it. "a" and "b" are the two answers
  as the viewer would type them in a comment: one or two short words in capitals, at most
  {option_max} letters each.
- Use two to four different sets across the episode, and change the light when the mood changes.
- Only use the words listed above for set, light, pose, kind, event, camera and place.
{iro}

Reply with the JSON only, no other words."""

IRO_ON = """- Iro is the hero's small AI companion: a glowing robot penguin that stays at their side. Set
  "iro": true in the shots where the hero is in the picture. Once in the episode, and no more than
  twice, Iro notices something useful and says it ("Iro whispers: the footsteps stopped outside
  the door"). Iro never solves the problem and never says which choice is right."""
IRO_OFF = """- There is no companion in this story: set "iro": false in every shot and never mention Iro."""


def _vocab() -> dict:
    spots = sorted({f"{name} ({', '.join(stickstory.build_set(name)[3].get('spots', {}))})"
                    for name in stickstory.SETS if stickstory.build_set(name)[3].get("spots")})
    return {"sets": "\n".join(f"- {k}: {v}" for k, v in stickstory.SETS.items()),
            "lights": "\n".join(f"- {k}: {v}" for k, v in stickstory.LIGHTS.items()),
            "poses": ", ".join(stickstory.POSES),
            "kinds": "\n".join(f"- {k}: {v}" for k, v in stickstory.KINDS.items()),
            "events": "\n".join(f"- {k}: {v}" for k, v in stickstory.EVENTS.items()),
            "spots": "; ".join(spots)}


WORDS_MIN, WORDS_MAX = 60, 105


def writer_prompt(iro: bool) -> str:
    return WRITER.format(shots_min=7, shots_max=11, say_max=18, words_min=WORDS_MIN, words_max=WORDS_MAX,
                         option_max=stickstory.OPTION_MAX_CHARS, iro=IRO_ON if iro else IRO_OFF, **_vocab())


def story_problems(ep: dict) -> list[str]:
    """What is wrong with a written episode beyond what the drawing needs: its length and its ending."""
    out = stickstory.check_episode(ep)
    clean = stickstory.clean_episode(ep)
    words = sum(len(s["say"].split()) for s in clean["shots"])
    if clean["shots"] and not WORDS_MIN - 12 <= words <= WORDS_MAX + 15:
        out.append(f"the narrator's lines are {words} words together; write {WORDS_MIN} to {WORDS_MAX}")
    if clean["shots"] and "?" not in clean["shots"][-1]["say"]:
        out.append("the last shot's line must be the question the episode ends on")
    if not clean["recap"]:
        out.append("the recap is missing")
    return out


def _ask(config: dict, system: str, user: str, client=None) -> dict:
    """One episode from Claude; if it cannot be drawn, it is told why and asked once more."""
    import steps.script as S
    client = client or S.create_client()
    model = config["script"]["model"]
    messages = [{"role": "user", "content": user}]
    problems: list[str] = []
    for attempt in (1, 2):
        response = S.call_model(client, model, 16000, system, messages, effort="medium")
        text = S.response_text(response)
        try:
            data = S.parse_json(text)
        except ValueError as e:
            data, problems = None, [f"the reply was not JSON ({e})"]
        else:
            if not isinstance(data, dict):
                data, problems = None, ["the reply was not one JSON object"]
            else:
                problems = story_problems(data)
                if not problems:
                    return stickstory.clean_episode(data)
        if attempt == 1:
            messages += [{"role": "assistant", "content": text[:6000]},
                         {"role": "user", "content": "That script cannot be used:\n- " + "\n- ".join(problems[:10])
                          + "\n\nWrite the whole episode again with these fixed. JSON only."}]
    raise StepError("the episode that came back could not be used: " + "; ".join(problems[:3]))


def write_first(data: dict, config: dict, client=None) -> dict:
    """Claude writes episode 1 from the series' premise (one request, a few cents)."""
    premise = data.get("premise") or ""
    if not premise.strip():
        raise StepError("this series has no premise to write from")
    user = f"The premise of the series:\n{premise}\n\nWrite episode 1."
    return _ask(config, writer_prompt(bool(data.get("iro", True))), user, client)


def story_so_far(series_id: str) -> str:
    data = load(series_id)
    lines = []
    for n in range(1, data["episodes"] + 1):
        ep = load_episode(series_id, n)
        told = " ".join(s["say"] for s in ep["shots"])
        lines.append(f"EPISODE {n}: {ep.get('title', '')}\n" + (f"(the vote before it: {ep['voted']})\n" if ep.get("voted") else "")
                     + f"Narration: {told}\nWhat is true after it: {ep.get('recap', '')}\nIt ended on: {ep['question']}  ({ep['a']} or {ep['b']})")
    return "\n\n".join(lines)


def write_next(series_id: str, choice: str, config: dict, client=None) -> tuple[dict, str]:
    """Claude writes the next episode from the story so far and the choice that won ("a" or "b").
    Returns (the script, the winning words)."""
    data = load(series_id)
    if data["episodes"] < 1:
        raise StepError("this series has no episode yet; write the first one")
    last = load_episode(series_id, data["episodes"])
    choice = str(choice or "").strip().lower()
    if choice not in ("a", "b"):
        raise StepError("say which choice won: a or b")
    won, lost = (last["a"], last["b"]) if choice == "a" else (last["b"], last["a"])
    n = data["episodes"] + 1
    user = (f"The premise of the series:\n{data.get('premise', '')}\n\nTHE STORY SO FAR\n{story_so_far(series_id)}\n\n"
            f"THE VOTE: most viewers chose {won} (not {lost}).\n\nWrite episode {n}. Its first line says the choice "
            f"in the hero's terms (\"You chose to ...\") and the first two shots show what that choice did. It has to "
            f"matter: {won} must cost something or reveal something that {lost} would not have. Keep every fact from "
            f"the story so far. Then raise the stakes and end on a new choice.")
    return _ask(config, writer_prompt(bool(data.get("iro", True))), user, client), won
