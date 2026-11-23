"""Iro explains, on disk: one folder per lesson, and Claude writing a lesson from a topic.

    <output folder>/_lessons/<lesson id>/
        lesson.json            the script (explainer.py draws it)
        voice.mp3 .json        Iro's voice and when each word is said
        final.mp4              the video
        cover.jpg              a still for the cover
        caption.txt            the text for the post

    create(script, name)              a lesson from a script (yours, or a starter's)
    write(topic, config, must)        Claude writes a lesson about a topic            (one request)
    produce(lesson_id, config)        voice (ElevenLabs, if there is a key), sound, video
    starters()                        the lessons that ship, ready to draw

Drawing costs nothing. A lesson's narration is about 550 characters of ElevenLabs.
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

import explainer
from common import ROOT, StepError, read_json, runs_dir, slugify, write_json

STARTER_FILE = ROOT / "assets" / "lesson_starters.json"
DEFAULT_TAG = "SEARCH IRO AI"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,80}$")
TOPIC_MAX = 300
RENDER_VERSION = 1


def root() -> Path:
    return runs_dir() / "_lessons"


def lesson_dir(lesson_id: str, must_exist: bool = True) -> Path:
    if not isinstance(lesson_id, str) or not ID_RE.match(lesson_id):
        raise StepError(f"{lesson_id!r} is not a lesson")
    path = root() / lesson_id
    if must_exist and not (path / "meta.json").is_file():
        raise StepError(f"there is no lesson called {lesson_id}")
    return path


def load(lesson_id: str) -> dict:
    return read_json(lesson_dir(lesson_id) / "meta.json")


def _save(lesson_id: str, data: dict) -> None:
    path = lesson_dir(lesson_id, must_exist=False)
    path.mkdir(parents=True, exist_ok=True)
    tmp = path / "meta.json.tmp"
    write_json(tmp, data)
    tmp.replace(path / "meta.json")


def _tag(end_tag) -> str:
    return "" if end_tag is None else " ".join(str(end_tag).upper().split())[:28]


def _write_script(lesson_id: str, script: dict) -> None:
    folder = lesson_dir(lesson_id)
    tmp = folder / "lesson.json.tmp"
    write_json(tmp, script)
    tmp.replace(folder / "lesson.json")
    (folder / "caption.txt").write_text((script.get("caption") or "") + "\n", encoding="utf-8")


def new(name: str, topic: str = "", end_tag: str | None = DEFAULT_TAG, voice_id: str = "") -> dict:
    """A lesson with no script yet (one is put in with set_script, or written by Claude)."""
    topic = " ".join(str(topic or "").split())[:TOPIC_MAX]
    name = " ".join(str(name or "").split())[:60] or (topic[:40] or "Lesson")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    lesson_id = f"{stamp}-{slugify(name, 28) or 'lesson'}"
    k = 2
    while (root() / lesson_id).exists():
        lesson_id = f"{stamp}-{slugify(name, 24) or 'lesson'}-{k}"
        k += 1
    data = {"id": lesson_id, "name": name, "topic": topic, "end_tag": _tag(end_tag), "voice_id": str(voice_id or "").strip(),
            "created_at": datetime.now().isoformat(timespec="seconds"), "scripted": False}
    _save(lesson_id, data)
    return data


def set_script(lesson_id: str, script: dict) -> dict:
    """Put a script in, or replace the one that is there. It is checked first."""
    data = load(lesson_id)
    lesson = explainer.clean_lesson(script)
    problems = explainer.check_lesson(lesson)
    if problems:
        raise StepError("this lesson cannot be drawn: " + "; ".join(problems[:5]))
    if not lesson["title"]:
        lesson["title"] = data.get("name") or "Lesson"
    _write_script(lesson_id, lesson)
    data["scripted"] = True
    data.pop("writing", None)
    data.pop("error", None)
    _save(lesson_id, data)
    return lesson


def create(script: dict, name: str = "", topic: str = "", end_tag: str | None = DEFAULT_TAG, voice_id: str = "") -> dict:
    """A lesson from a script. Nothing is drawn yet."""
    lesson = explainer.clean_lesson(script)
    problems = explainer.check_lesson(lesson)
    if problems:
        raise StepError("this lesson cannot be drawn: " + "; ".join(problems[:5]))
    data = new(name or lesson["title"], topic, end_tag, voice_id)
    set_script(data["id"], lesson)
    return load(data["id"])


def update(lesson_id: str, changes: dict) -> dict:
    data = load(lesson_id)
    if "name" in changes and str(changes["name"] or "").strip():
        data["name"] = " ".join(str(changes["name"]).split())[:60]
    if "end_tag" in changes:
        data["end_tag"] = _tag(changes["end_tag"])
    if "voice_id" in changes:
        data["voice_id"] = str(changes["voice_id"] or "").strip()
    _save(lesson_id, data)
    return data


def set_note(lesson_id: str, writing: bool = False, error: str | None = None) -> dict:
    data = load(lesson_id)
    if writing:
        data["writing"] = True
    else:
        data.pop("writing", None)
    if error:
        data["error"] = str(error)[:400]
    else:
        data.pop("error", None)
    _save(lesson_id, data)
    return data


def delete(lesson_id: str) -> None:
    shutil.rmtree(lesson_dir(lesson_id))


def script(lesson_id: str) -> dict | None:
    path = lesson_dir(lesson_id) / "lesson.json"
    return read_json(path) if path.is_file() else None


def _key(lesson: dict, end_tag: str, voiced: bool) -> str:
    return hashlib.sha1(json.dumps([RENDER_VERSION, explainer.clean_lesson(lesson), end_tag, voiced], sort_keys=True).encode()).hexdigest()[:16]


def _made(lesson_id: str) -> dict:
    path = lesson_dir(lesson_id) / "made.json"
    try:
        return read_json(path) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def state(lesson_id: str, data: dict | None = None) -> dict:
    """A lesson, its script and what is made of it."""
    data = data or load(lesson_id)
    folder = lesson_dir(lesson_id)
    lesson = script(lesson_id)
    made = _made(lesson_id)
    video = folder / "final.mp4"
    current = bool(lesson) and video.is_file() and made.get("key") == _key(lesson, data.get("end_tag", ""), bool(made.get("voiced")))
    words = sum(len(s["say"].split()) for s in explainer.segments(explainer.clean_lesson(lesson))) if lesson else 0
    return {"id": lesson_id, "name": data.get("name") or lesson_id, "topic": data.get("topic", ""), "created_at": data.get("created_at"),
            "end_tag": data.get("end_tag", ""), "voice_id": data.get("voice_id", ""), "lesson": lesson,
            "made": current, "stale": bool(lesson) and video.is_file() and not current,
            "voiced": bool(made.get("voiced")) if video.is_file() else False, "seconds": made.get("seconds") if video.is_file() else None,
            "words": words, "writing": bool(data.get("writing")), "error": data.get("error"), "folder": str(folder)}


def all_lessons() -> list[dict]:
    """Every lesson, newest first."""
    out = []
    if root().is_dir():
        for d in sorted(root().iterdir(), reverse=True):
            if d.is_dir() and (d / "meta.json").is_file() and ID_RE.match(d.name):
                try:
                    out.append(state(d.name))
                except (StepError, OSError, ValueError, KeyError):
                    continue
    return out


def starters() -> list[dict]:
    """The lessons that ship with VidGen, each ready to draw."""
    if not STARTER_FILE.is_file():
        return []
    out = []
    for s in (read_json(STARTER_FILE) or {}).get("lessons") or []:
        if isinstance(s, dict) and s.get("id") and isinstance(s.get("lesson"), dict):
            out.append({"id": str(s["id"]), "name": str(s.get("name") or s["id"]), "topic": str(s.get("topic") or ""), "lesson": s["lesson"]})
    return out


# -------------------------------------------------------------- making the video ----

def voice_id_for(data: dict, config: dict) -> str:
    return data.get("voice_id") or (config.get("voices") or {}).get("narrator", "") or config.get("voice_id", "")


def produce(lesson_id: str, config: dict, voice: bool = True, again: bool = False, workers: int = 4, log=print) -> dict:
    """Make a lesson's video: Iro's voice (if there is an ElevenLabs key), the sounds, the drawing.
    A narration already read for the same words and voice is not paid for twice."""
    import story_sound
    data = load(lesson_id)
    lesson = script(lesson_id)
    if not lesson:
        raise StepError("this lesson has no script yet")
    folder = lesson_dir(lesson_id)
    tag = data.get("end_tag", "")
    spoken = explainer.lines(lesson)
    text = " ".join(s["say"] for s in spoken["shots"])
    vid = voice_id_for(data, config)
    voice_file, voice_json = folder / "voice.mp3", folder / "voice.json"
    voice_data = raw_data = None
    if bool(voice) and bool(os.environ.get("ELEVENLABS_API_KEY")) and bool(vid):
        sig = hashlib.sha1(f"{vid}|{text}".encode()).hexdigest()[:16]
        saved = {}
        if voice_json.is_file() and voice_file.is_file():
            try:
                saved = read_json(voice_json)
            except (OSError, ValueError):
                saved = {}
        if saved.get("sig") == sig:
            raw_data = saved
            log("[lesson] the narration is already read; using it")
        else:
            log(f"[lesson] Iro reads {len(text.split())} words ({len(text)} characters) with voice {vid}...")
            audio, raw_data = story_sound.narrate(spoken, config, vid)
            voice_file.write_bytes(audio)
            raw_data["sig"] = sig
            write_json(voice_json, raw_data)
        _, tight_words, tight_duration = story_sound.tighten_plan(raw_data.get("words") or [], float(raw_data.get("duration") or 0))
        voice_data = {**raw_data, "words": tight_words, "duration": tight_duration}
    elif voice:
        log("[lesson] no ElevenLabs key, so this video has no voice (the words on screen keep an even pace)")
    timing = explainer.plan(lesson, voice_data)
    voiced = bool(voice_data) and timing["voiced"]
    if voice_data and not voiced:
        log("[lesson] the narration's words did not line up with the script; the words on screen keep an even pace")
    key = _key(lesson, tag, voiced)
    video = folder / "final.mp4"
    if not again and video.is_file() and _made(lesson_id).get("key") == key:
        log("[lesson] the video is already made")
        return {"made": False, "seconds": _made(lesson_id).get("seconds"), "voiced": voiced}
    started = time.time()
    track = None
    if voice_data:
        cut = story_sound.tighten(voice_file, raw_data, folder / "voice_tight.wav")
        track = folder / "voice_tight.wav"
        if cut["saved"] > 0.05:
            log(f"[lesson] {cut['saved']:.1f} seconds of silence cut from the narration")
    sound = story_sound.mix(folder / "sound.wav", timing["total"], track, explainer.cues(lesson, timing), drone=False)
    log(f"[lesson] drawing {timing['total']:.0f} seconds of video (no model is called; this is free)...")
    last = [0]

    def on_frame(i: int, total: int) -> None:
        pct = int(i * 10 / total)
        if pct > last[0]:
            last[0] = pct
            log(f"  {pct * 10}%")
    explainer.render(lesson, video, timing, audio=sound, end_tag=tag, workers=workers, on_frame=on_frame)
    hook_end = timing["shots"][0]["end"]
    explainer.frame(lesson, max(0.0, hook_end - 0.5), timing, tag, bubble=False).save(folder / "cover.jpg", quality=90)
    write_json(folder / "made.json", {"key": key, "voiced": voiced, "seconds": timing["total"], "at": datetime.now().isoformat(timespec="seconds")})
    log(f"[lesson] made in {time.time() - started:.0f}s: {video}")
    return {"made": True, "seconds": timing["total"], "voiced": voiced}


# ------------------------------------------------------------ Claude writes it ----

WRITER = """You write short lessons for vertical videos. A small robot penguin called Iro stands at the bottom
of the screen and says every word. Above him a title and one card per point build as he talks. The
lesson teaches one useful thing about working with AI, to someone who uses it a little and wants to
be good at it. It runs 40 to 55 seconds.

WHAT MAKES A LESSON WORK
- The hook names a problem the viewer has, in the first sentence, in words they would use. No
  greeting, no "in this video". The hook's title is the two to five words they must not scroll past.
- Three points (two to four is allowed). Each one moves: the problem, the fix, how to do it now.
  A point is one or two short sentences Iro says, a title of two to four words, and one card.
- Show, do not describe. If the lesson is about a better prompt, a card shows the weak prompt and
  the strong one. If it is three things to remember, a card lists the three.
- The close pays the hook off in one line{close_rule}
- Plain words a fourteen year old would say. Short sentences. "You", not "users".
- Only say what is true. No statistics, percentages or study results unless they are given to you
  in the topic. Do not name or mock any AI product or company.

THE LESSON IS JSON
{{"title": "a few words, for the list of lessons",
  "caption": "the text under the post: one lower case line, then a short question. no hashtags, no emoji, no app or product names",
  "hook": {{"say": "what Iro says first, one or two sentences",
           "kicker": "A FEW SMALL WORDS ABOVE THE TITLE (optional, at most 30 letters)",
           "title": "TWO TO FIVE WORDS IN GIANT LETTERS", "stamp": "ONE OR TWO WORDS STAMPED ON IT (optional, at most 12 letters)"}},
  "points": [
    {{"label": "two or three words: the problem, the fix, try it",
      "title": "TWO TO FOUR WORDS", "accent": "the one or two words of the title to highlight, exactly as in the title",
      "note": "two to four words that stay on screen as a note after the point",
      "say": "what Iro says for this point, at most {say_max} words",
      "card": {{ ... one of the cards below ... }}}}
  ],
  "close": {{"say": "the last line", "title": "THREE TO SIX WORDS"}}}}

THE CARDS
- {{"type": "compare", "bad": "the weak version", "good": "the strong version", "bad_label": "VAGUE", "good_label": "CLEAR"}}
  Both are typed out on screen, so write real prompts a person would type, each under {prompt_max} letters.
- {{"type": "list", "items": ["two to four things", "each under {item_max} letters"]}}
  Each is ticked as Iro says it, so say them in the same order and use a word from each item.
- {{"type": "type", "text": "one prompt typed into a chat box, under {prompt_max} letters", "label": "TRY THIS"}}
- {{"type": "rule", "text": "one sentence, under {rule_max} letters", "stamp": "RULE 1"}}
- {{"type": "steps", "items": ["two to four", "single words", "in order"]}}   (each under 16 letters)
- {{"type": "number", "value": 3, "suffix": "x", "label": "what the number counts"}}
  Only for a number that is part of the lesson itself (three parts, two questions). Never a statistic.

RULES THE PROGRAM CHECKS
- {points_min} to {points_max} points, each with a card. Use at least two different kinds of card.
- Everything Iro says, hook to close, is {words_min} to {words_max} words together.
- Titles: the hook at most 6 words and 40 letters, a point at most {title_words} words and {title_chars} letters.
- "accent" must be words that appear in that point's title.

Reply with the JSON only, no other words."""


def writer_prompt(end_tag: str = DEFAULT_TAG) -> str:
    tag = " ".join(str(end_tag or "").split())
    close_rule = f', then ends with these exact words: "{tag.title().replace(" Ai", " AI")}."' if tag else "."
    return WRITER.format(close_rule=close_rule, say_max=explainer.SAY_MAX_WORDS - 4, prompt_max=explainer.PROMPT_MAX_CHARS,
                         item_max=explainer.ITEM_MAX_CHARS, rule_max=explainer.RULE_MAX_CHARS, points_min=explainer.POINTS_MIN,
                         points_max=4, words_min=explainer.WORDS_MIN + 10, words_max=explainer.WORDS_MAX - 15,
                         title_words=explainer.TITLE_MAX_WORDS, title_chars=explainer.TITLE_MAX_CHARS)


def lesson_problems(raw: dict) -> list[str]:
    """What is wrong with a written lesson beyond what the drawing needs: its length."""
    out = explainer.check_lesson(raw)
    lesson = explainer.clean_lesson(raw)
    words = sum(len(s["say"].split()) for s in explainer.segments(lesson))
    if lesson["points"] and not explainer.WORDS_MIN <= words <= explainer.WORDS_MAX:
        out.append(f"everything Iro says is {words} words together; write {explainer.WORDS_MIN + 10} to {explainer.WORDS_MAX - 15}")
    if not lesson["caption"]:
        out.append("the caption for the post is missing")
    return out


def write(topic: str, config: dict, must: str = "", end_tag: str = DEFAULT_TAG, client=None) -> dict:
    """Claude writes a lesson about a topic (one request, a few cents). A lesson that cannot be
    drawn goes back once with the reasons."""
    import steps.script as S
    topic = " ".join(str(topic or "").split())[:TOPIC_MAX]
    if not topic:
        raise StepError("say what the lesson is about")
    client = client or S.create_client()
    model = config["script"]["model"]
    must = " ".join(str(must or "").split())[:400]
    user = f"The lesson is about: {topic}" + (f"\n\nIt must mention: {must}" if must else "") + "\n\nWrite the lesson."
    messages = [{"role": "user", "content": user}]
    problems: list[str] = []
    for attempt in (1, 2):
        response = S.call_model(client, model, 12000, writer_prompt(end_tag), messages, effort="medium")
        text = S.response_text(response)
        try:
            data = S.parse_json(text)
        except ValueError as e:
            data, problems = None, [f"the reply was not JSON ({e})"]
        else:
            if not isinstance(data, dict):
                problems = ["the reply was not one JSON object"]
            else:
                problems = lesson_problems(data)
                if not problems:
                    return explainer.clean_lesson(data)
        if attempt == 1:
            messages += [{"role": "assistant", "content": text[:6000]},
                         {"role": "user", "content": "That lesson cannot be used:\n- " + "\n- ".join(problems[:10])
                          + "\n\nWrite the whole lesson again with these fixed. JSON only."}]
    raise StepError("the lesson that came back could not be used: " + "; ".join(problems[:3]))
