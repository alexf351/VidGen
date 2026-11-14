"""The Claude Code engine: Claude Code writes the story and codes every scene, the video renders
on this computer. No image or video model is called; the coding runs on your Claude login.

A format offers it with a code_render block (skill + styles) in its format.yaml. A run made with
this engine keeps everything in runs/<id>/code/ (a copy of the skill's template) and has four
steps instead of the image pipeline's five:

    story    Claude Code writes story.json: one line per beat, a style for each (copywriter.md)
    scenes   Claude Code rewrites each style file for this story and checks stills as it goes
    voice    VidGen reads the lines with ElevenLabs and times the beats to the voice (optional)
    render   VidGen runs `node render.cjs video`, burns word-by-word captions timed to the
             voice onto out/video.mp4 (the template draws none), and saves final.mp4. When
             nothing the picture is drawn from has changed since the last render, only the
             captions are made again (seconds, not minutes).

Claude Code is started headless (`claude -p`) in the run's code folder. Its environment has no
API keys: ANTHROPIC_API_KEY and friends are removed so it uses your subscription login, and the
fal / Sume / ElevenLabs keys stay with VidGen. It may read and edit files in the code folder,
read the skill and the format, and run exactly one command: `node render.cjs stills ...`.
Anything else it tries is denied (permission mode dontAsk), never prompted.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from common import KEY_ENV, ROOT, TOOLS, StepError, read_json, read_premise, write_json

CODE_STEPS = ["story", "scenes", "voice", "render"]
ENGINES = ("ai", "claude_code")
TEMPLATE_FILES = ("index.html", "main.js", "render.cjs", "package.json", "story.json")
TEMPLATE_DIRS = ("lib", "styles")
NODE_CACHE = ROOT / "cache" / "code_engine"

# Environment variables that would make Claude Code bill an API key or a cloud account instead
# of the subscription you are logged in with, or that would stop it starting at all.
AUTH_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
            "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
            "ANTHROPIC_PROFILE", "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID",
            "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")

LIMIT_HINTS = ("hit your session limit", "hit your weekly limit", "hit your opus limit",
               "hit your sonnet limit", "usage limit")
LOGIN_HINTS = ("not logged in", "please run /login", "authentication required")


# ------------------------------------------------------------------ settings ----

def settings(config: dict) -> dict:
    ce = dict(config.get("code_engine") or {})
    ce.setdefault("claude_path", "")
    ce.setdefault("node_path", "")
    ce.setdefault("model", "")                  # empty: Claude Code's own default for your plan
    ce.setdefault("story_max_turns", 20)
    ce.setdefault("scenes_max_turns", 120)
    ce.setdefault("timeout_minutes", 60)        # one Claude Code session
    ce.setdefault("render_timeout_minutes", 90)
    ce.setdefault("voice", True)
    return ce


def offered(config: dict) -> dict | None:
    """The format's code_render block, if this format can use the Claude Code engine."""
    return (config.get("format") or {}).get("code_render")


def workspace(run_dir: Path) -> Path:
    return run_dir / "code"


def _status_path(run_dir: Path) -> Path:
    return workspace(run_dir) / "vidgen_status.json"


def read_status(run_dir: Path) -> dict:
    p = _status_path(run_dir)
    if not p.is_file():
        return {}
    try:
        data = read_json(p)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _mark(run_dir: Path, step: str, value=True, clear: tuple[str, ...] = ()) -> None:
    data = read_status(run_dir)
    for k in clear:
        data.pop(k, None)
    if value is None:
        data.pop(step, None)
    else:
        data[step] = {"at": datetime.now().isoformat(timespec="seconds"), "value": value}
    write_json(_status_path(run_dir), data)


def step_states(run_dir: Path) -> dict:
    st = read_status(run_dir)
    final = (run_dir / "final.mp4").is_file()

    def one(name: str) -> dict:
        done = name in st or (name == "render" and final)
        note = st.get(name, {}).get("value") if isinstance(st.get(name), dict) else None
        return {"status": "done" if done else "pending", "done": int(done), "total": 1,
                "note": note if isinstance(note, str) else None}
    return {name: one(name) for name in CODE_STEPS}


# --------------------------------------------------------------------- tools ----

def _which(configured: str, *names: str) -> str | None:
    if configured:
        p = Path(configured).expanduser()
        return str(p) if p.is_file() else shutil.which(configured)
    for n in names:
        found = shutil.which(n)
        if found:
            return found
    return None


def claude_path(config: dict) -> str | None:
    return _which(settings(config)["claude_path"], "claude")


def node_path(config: dict) -> str | None:
    return _which(settings(config)["node_path"], "node")


def npm_path(config: dict) -> str | None:
    node = node_path(config)
    if node:
        for n in ("npm.cmd", "npm"):
            p = Path(node).with_name(n)
            if p.is_file():
                return str(p)
    return shutil.which("npm")


def claude_env() -> dict:
    """The environment for Claude Code: VidGen's minus every API key and auth override."""
    drop = set(AUTH_ENV) | set(KEY_ENV.values())
    env = {k: v for k, v in os.environ.items() if k.upper() not in drop}
    return env


def tool_env(config: dict) -> dict:
    """The environment for node/npm: keys removed too, ffmpeg's folder on PATH for render.cjs."""
    env = claude_env()
    ff = TOOLS.get("ffmpeg") or "ffmpeg"
    extra = []
    if os.path.isabs(ff):
        extra.append(str(Path(ff).parent))
    node = node_path(config)
    if node:
        extra.append(str(Path(node).parent))
    if extra:
        env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


def auth_status(config: dict) -> dict:
    """`claude auth status` with the engine's environment (no model request, no usage)."""
    exe = claude_path(config)
    if not exe:
        return {"installed": False}
    out = {"installed": True, "path": exe}
    try:
        v = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30,
                           encoding="utf-8", errors="replace", env=claude_env())
        out["version"] = (v.stdout or v.stderr).strip().splitlines()[0] if (v.stdout or v.stderr).strip() else ""
        a = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=30,
                           encoding="utf-8", errors="replace", env=claude_env())
    except (OSError, subprocess.SubprocessError) as e:
        out["error"] = str(e)
        return out
    out["logged_in"] = a.returncode == 0
    try:
        data = json.loads(a.stdout)
        out["auth_method"] = data.get("authMethod") or ""
    except (ValueError, AttributeError):
        out["auth_method"] = ""
        out["detail"] = (a.stdout or a.stderr).strip()[:200]
    return out


def doctor_rows(config: dict) -> list[tuple[bool | None, str, str]]:
    """Checks for the Claude Code engine. None = skipped (the engine is optional)."""
    rows: list[tuple[bool | None, str, str]] = []
    need = " (only needed for the Claude Code engine)"
    node = node_path(config)
    if node:
        try:
            ver = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            ver = "version unknown"
        rows.append((True, "node", f"{node} ({ver})"))
    else:
        rows.append((None, "node", "not found" + need + ". Install Node.js 20+ (Windows: winget install OpenJS.NodeJS.LTS)"))
    npm = npm_path(config)
    rows.append((True, "npm", npm) if npm else (None, "npm", "not found" + need))
    st = auth_status(config)
    if not st["installed"]:
        rows.append((None, "claude (Claude Code)", "not found" + need + ". Install it, then run: claude auth login"))
    elif st.get("error"):
        rows.append((False, "claude (Claude Code)", f"{st['path']}: {st['error']}"))
    else:
        rows.append((True, "claude (Claude Code)", f"{st['path']} ({st.get('version') or 'version unknown'})"))
        method = st.get("auth_method") or ""
        if not st.get("logged_in"):
            rows.append((False, "Claude Code login", "not logged in. Run: claude auth login"))
        elif method in ("api_key", "api_key_helper", "third_party"):
            rows.append((False, "Claude Code login", f"it would bill {method.replace('_', ' ')}, not your "
                         f"subscription. Check apiKeyHelper or a cloud setting in ~/.claude/settings.json"))
        else:
            rows.append((True, "Claude Code login", f"logged in ({method or 'subscription'}); VidGen removes "
                         f"ANTHROPIC_API_KEY so the engine uses this login"))
    return rows


# ------------------------------------------------------------------ workspace ----

def _run_streamed(cmd: list[str], cwd: Path, env: dict, label: str, timeout_s: float,
                  on_line=None, stdin_text: str | None = None) -> int:
    """Run a command, printing its output line by line into the job log. Kills it on timeout."""
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE if stdin_text is not None
                                else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", bufsize=1)
    except OSError as e:
        raise StepError(f"{label}: could not start {cmd[0]}: {e}") from e
    timed_out = threading.Event()

    def kill():
        timed_out.set()
        proc.kill()
    timer = threading.Timer(timeout_s, kill)
    timer.daemon = True
    timer.start()
    try:
        if stdin_text is not None:
            try:
                proc.stdin.write(stdin_text)
                proc.stdin.close()
            except OSError:
                pass
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            if on_line:
                on_line(line)
            elif line.strip():
                print(f"  {line}")
        proc.wait()
    finally:
        timer.cancel()
    if timed_out.is_set():
        raise StepError(f"{label}: stopped after {timeout_s / 60:.0f} minutes")
    return proc.returncode


def ensure_node_modules(config: dict, skill: dict) -> Path:
    """npm install the template's dependencies once into cache/code_engine/<skill>/ (shared by
    every run). The first time takes a few minutes: puppeteer downloads its own Chrome."""
    npm = npm_path(config)
    if not npm:
        raise StepError("npm was not found; install Node.js 20+ (Windows: winget install OpenJS.NodeJS.LTS)")
    folder = NODE_CACHE / skill["dir"].name
    folder.mkdir(parents=True, exist_ok=True)
    pkg = (skill["template"] / "package.json").read_text(encoding="utf-8")
    stamp = folder / "package.json"
    ready = (folder / "node_modules" / "three").is_dir() and (folder / "node_modules" / "puppeteer").is_dir()
    if ready and stamp.is_file() and stamp.read_text(encoding="utf-8") == pkg:
        return folder / "node_modules"
    stamp.write_text(pkg, encoding="utf-8")
    print(f"[code] installing the template's packages once into {folder} (three, puppeteer)...")
    print("  the first install downloads a copy of Chrome for rendering; this can take a few minutes")
    rc = _run_streamed([npm, "install", "--no-audit", "--no-fund"], folder, tool_env(config),
                       "npm install", 20 * 60)
    if rc != 0:
        raise StepError(f"npm install failed (exit {rc}); see the log above")
    return folder / "node_modules"


def _link_dir(target: Path, link: Path) -> None:
    """A directory link that needs no admin rights: a junction on Windows, a symlink elsewhere.
    Falls back to a copy."""
    if link.exists() or link.is_symlink():
        return
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            link.symlink_to(target, target_is_directory=True)
    except OSError:
        print("  (could not link node_modules; copying it instead)")
        shutil.copytree(target, link)


def prepare_workspace(run_dir: Path, config: dict) -> Path:
    """runs/<id>/code: the skill's template (without its example voice), node_modules linked."""
    skill = offered(config)
    if not skill:
        raise StepError(f"the {config['format']['name']} format has no code_render block, so it "
                        f"cannot use the Claude Code engine")
    if not skill["template"].is_dir():
        raise StepError(f"skills/{skill['dir'].name}/template is missing")
    ws = workspace(run_dir)
    if not (ws / "render.cjs").is_file():
        ws.mkdir(parents=True, exist_ok=True)
        for name in TEMPLATE_FILES:
            shutil.copy2(skill["template"] / name, ws / name)
        for name in TEMPLATE_DIRS:
            shutil.copytree(skill["template"] / name, ws / name, dirs_exist_ok=True)
        print(f"[code] copied the {skill['dir'].name} template to {ws}")
    _link_dir(ensure_node_modules(config, skill), ws / "node_modules")
    # The instructions Claude Code reads, copied in so it never needs a folder outside this one.
    docs = ws / "skill"
    docs.mkdir(exist_ok=True)
    for md in sorted(skill["dir"].glob("*.md")):
        shutil.copyfile(md, docs / md.name)
    brief = ws / "format"
    brief.mkdir(exist_ok=True)
    shutil.copyfile(config["format"]["dir"] / "script_prompt.md", brief / "script_prompt.md")
    _copy_cast_pictures(ws, config)
    return ws


def _copy_cast_pictures(ws: Path, config: dict) -> None:
    """Pictures of the cast (the format's own and your library's) in code/refs/ for Claude to look at."""
    refs = ws / "refs"
    for c in config.get("locked_characters", []):
        src = None
        if c.get("library"):
            from characters import ref_path
            src = ref_path(c["library"])
        elif c.get("image_path"):
            src = ROOT / c["image_path"]
        if src and src.is_file():
            refs.mkdir(exist_ok=True)
            shutil.copyfile(src, refs / f"{c['id']}{src.suffix.lower()}")


# -------------------------------------------------------------- Claude Code ----

def _short(text: str, n: int = 220) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _tool_summary(name: str, inp: dict) -> str:
    for key in ("command", "file_path", "path", "pattern", "url"):
        if isinstance(inp, dict) and inp.get(key):
            return f"{name} {_short(inp[key], 160)}"
    return name


class StreamPrinter:
    """Turns Claude Code's stream-json events into readable job-log lines."""

    def __init__(self, ws: Path):
        self.ws = ws
        self.result: dict | None = None
        self.session_id: str | None = None
        self.raw_tail: list[str] = []

    def __call__(self, line: str) -> None:
        if not line.strip():
            return
        try:
            ev = json.loads(line)
        except ValueError:
            self.raw_tail = (self.raw_tail + [line])[-20:]
            print(f"  {line}")
            return
        if not isinstance(ev, dict):
            return
        t = ev.get("type")
        self.session_id = ev.get("session_id") or self.session_id
        if t == "system" and ev.get("subtype") == "init":
            print(f"  [claude] session started (model {ev.get('model') or 'default'})")
        elif t == "system" and ev.get("subtype") == "api_retry":
            print(f"  [claude] retrying ({ev.get('error') or 'error'}), attempt {ev.get('attempt')}")
        elif t == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if block.get("type") == "text" and block.get("text", "").strip():
                    for para in block["text"].strip().splitlines():
                        if para.strip():
                            print(f"  [claude] {_short(para, 400)}")
                elif block.get("type") == "tool_use":
                    summary = _tool_summary(block.get("name", "tool"), block.get("input") or {})
                    print(f"  [claude] > {summary.replace(str(self.ws) + os.sep, '')}")
        elif t == "user":
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                    content = block.get("content")
                    if isinstance(content, list):
                        content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                    print(f"  [claude]   ! {_short(content or 'tool error', 300)}")
        elif t == "result":
            self.result = ev
        elif t == "permission_denied" or (t == "system" and ev.get("subtype") == "permission_denied"):
            print(f"  [claude]   denied: {_short(json.dumps(ev.get('tool_input') or ev.get('tool') or ev), 200)}")


def run_claude(ws: Path, config: dict, prompt: str, allowed: list[str], max_turns: int,
               label: str, resume: str | None = None) -> StreamPrinter:
    exe = claude_path(config)
    if not exe:
        raise StepError("Claude Code (the `claude` command) was not found. Install it and log in "
                        "with `claude auth login`, or set code_engine.claude_path in config.local.yaml")
    ce = settings(config)
    cmd = [exe, "-p", "--output-format", "stream-json", "--verbose",
           "--permission-mode", "dontAsk", "--allowedTools", ",".join(allowed),
           "--max-turns", str(int(max_turns))]
    if ce["model"]:
        cmd += ["--model", str(ce["model"])]
    if resume:
        cmd += ["--resume", resume]
    print(f"[{label}] starting Claude Code in {ws} (your Claude login; up to {max_turns} turns)")
    printer = StreamPrinter(ws)
    t0 = time.time()
    rc = _run_streamed(cmd, ws, claude_env(), f"Claude Code ({label})", float(ce["timeout_minutes"]) * 60,
                       on_line=printer, stdin_text=prompt)
    res = printer.result or {}
    text = str(res.get("result") or "")
    secs = (res.get("duration_ms") or (time.time() - t0) * 1000) / 1000
    turns = res.get("num_turns")
    print(f"[{label}] Claude Code finished in {secs:.0f}s" + (f", {turns} turns" if turns else ""))
    for d in res.get("permission_denials") or []:
        print(f"  denied: {_short(json.dumps(d), 200)}")
    low = (text + " " + " ".join(printer.raw_tail)).lower()
    if rc != 0 or res.get("is_error"):
        if any(h in low for h in LIMIT_HINTS):
            raise StepError(f"Claude Code hit your plan's usage limit: {_short(text or low, 200)}. "
                            f"Try again when it resets.")
        if any(h in low for h in LOGIN_HINTS):
            raise StepError("Claude Code is not logged in. Run `claude auth login` in a terminal, then retry.")
        if res.get("subtype") == "error_max_turns":
            raise StepError(f"Claude Code used all {max_turns} turns before finishing. Run the step "
                            f"again to continue, or raise code_engine.{label}_max_turns")
        detail = _short(text or " ".join(printer.raw_tail[-3:]) or f"exit code {rc}", 400)
        raise StepError(f"Claude Code failed ({label}): {detail}")
    return printer


# ------------------------------------------------------------------- prompts ----

def _brief(run_dir: Path, config: dict) -> str:
    fmt = config["format"]
    skill = offered(config)
    styles = skill["styles"]
    if skill["mix"]:
        style_rule = (f"Switch style on hard cuts, using 3 to 6 of these style files, the ones that "
                      f"suit each beat (see the table in copywriter.md): {', '.join(styles)}. "
                      f"A style may repeat.")
    else:
        style_rule = f"Every beat uses the {styles[0]} style (styles/{styles[0]}.js)."
    cast = []
    for c in config.get("locked_characters", []):
        pic = ""
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            if (workspace(run_dir) / "refs" / f"{c['id']}{ext}").is_file():
                pic = f" Picture: refs/{c['id']}{ext} (look at it)."
        who = f" ({c['role']})" if c.get("role") else ""
        cast.append(f"  - {c.get('name') or c['id']}{who}: {c['description']}.{pic}")
    rules = fmt["rules"]
    lines = [
        f"Premise: {read_premise(run_dir)}",
        f"Format: {fmt['title']}. {fmt['description']}",
        f"Length: {fmt['duration_target'] or '15 to 25 seconds'}. Vertical video for Reels and TikTok "
        f"(story.json \"format\": \"vertical\").",
        f"Styles: {style_rule}",
        "Characters who must appear (keep each one the same simple shape and two or three colors "
        "in every beat):",
        *(cast or ["  - none fixed; invent the subject the story needs"]),
    ]
    if fmt["beats"]:
        lines.append(f"Story shape for this format: {' -> '.join(fmt['beats'])}.")
    if rules.get("cta_caption"):
        lines.append(f"The last beat is the call to action. Its line says: {rules['cta_caption'].capitalize()}.")
    lines.append("Background on what this ad is for and its wording rules: format/script_prompt.md "
                 "(read it for the product, the cast rules and the banned wording; ignore its JSON "
                 "output format, it is for VidGen's other engine).")
    return "\n".join(lines)


# What a story has to do to hold a scroller. The story step scores three drafts against these
# and keeps the strongest; one draft written straight through came back flat.
STORY_TESTS = "\n".join(f"   - {t}" for t in (
    "The first line stops a scroll on its own: a person, a problem and a moment, specific enough to "
    "picture (\"Marcus froze when his boss said: just ask AI.\"). Never a scene-setter, a question to "
    "the viewer, or the person's name and job.",
    "By the third line the viewer knows what the hero stands to lose, and it is something a "
    "stranger would mind losing (the job, the date, the money, being laughed at).",
    "The app arrives at the turn and gives ONE result you could draw (the report done in two "
    "minutes, the plan on one page, the reply that got the yes), never a feature or a promise.",
    "The twist pays off something from the first three lines (the same boss, the same room, the "
    "same coworker), so the ending changes what the start meant. No twist about how the video "
    "was made, unless the premise asks for exactly that.",
    "Every line is something that happens and can be drawn, and the story still makes sense with "
    "the sound off.",
    "A stranger could retell the whole story after hearing it once.",
))


HEADLESS = (
    "You are running unattended inside VidGen, a video tool. Nobody can answer questions or "
    "approve anything, so never ask: make the call yourself and keep going. The current folder "
    "is a fresh copy of the claude-animation-styles template with its packages installed; do not "
    "run npm and do not copy the template again. The skill's instructions are in skill/ "
    "(SKILL.md, copywriter.md, styles.md). Work only inside this folder. Run commands from the "
    "current folder exactly as written, never chained with && or cd."
)


def story_prompt(run_dir: Path, config: dict) -> str:
    return "\n\n".join([
        HEADLESS,
        "THE BRIEF\n" + _brief(run_dir, config),
        "THIS STEP: WRITE THE STORY ONLY\n"
        "1. Read skill/SKILL.md and skill/copywriter.md (and the part of styles.md for each style you use).\n"
        "2. Draft THREE different stories with copywriter.md, each with its own first line and its own "
        "twist: one line per beat, 3 to 9 words a line, 15 to 25 seconds read aloud. Write them in "
        "story-drafts.md. Then give each draft one point for every test below it passes, write the "
        "scores under it, and keep the draft with the most points:\n" + STORY_TESTS + "\n"
        "   Fix the winner wherever it lost a point, then check it against copywriter.md's "
        "\"Before you show it\" list.\n"
        "3. Write story.json: {\"format\": \"vertical\", \"beats\": [{\"style\": <style file name>, "
        "\"seconds\": <1.2 to 4>, \"line\": <the line>}]}. Seconds are a first guess; the voice "
        "retimes them later.\n"
        "4. Write story.md: the lines, each with its style and one sentence on what the picture "
        "shows (the subject, what it does, the camera).\n"
        "Do NOT edit anything in styles/ or lib/ and do NOT render. Finish with the winning "
        "draft's scores and then its lines, one per line, as your last message.",
    ])


def scenes_prompt(run_dir: Path, config: dict) -> str:
    return "\n\n".join([
        HEADLESS,
        "THE BRIEF\n" + _brief(run_dir, config),
        "THIS STEP: CODE THE SCENES\n"
        "story.json and story.md are final; the user may have edited them, so read them now. Do "
        "not change the lines, the styles or the order of the beats.\n"
        "Follow SKILL.md steps 5 and 6 and \"Changing the subject\": for each style file the story "
        "uses, keep the look and replace the subject with this story's. Read the part of styles.md "
        "for each style first (skill/styles.md). Build the subject once per family (a drawX for the 2D styles in "
        "lib/common.js, a makeX(kit) for the 3D ones in lib/three-claude.js) so it is the same in "
        "every style. A style used for two beats draws a different scene for each (this.index).\n"
        "After each style, check stills with `node render.cjs stills <seconds>` (seconds into the "
        "whole video; pick moments inside that style's beats) and Read every picture it prints. Is "
        "the subject recognizable with the sound off? Does it read as that style? Is anything cut "
        "off? Fix it and check again. Delete nothing outside this folder.\n"
        "Do NOT run voice.py and do NOT render the video: VidGen adds the voice and renders after "
        "you. Finish with one short line per beat saying what it shows.",
    ])


# -------------------------------------------------------------------- story ----

def check_story(data, styles: list[str]) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return ["story.json must be an object"]
    if data.get("format") not in ("vertical", "wide"):
        errors.append('"format" must be "vertical" or "wide"')
    beats = data.get("beats")
    if not isinstance(beats, list) or not (2 <= len(beats) <= 16):
        return errors + ['"beats" must be a list of 2 to 16 beats']
    for i, b in enumerate(beats):
        where = f"beat {i + 1}"
        if not isinstance(b, dict):
            errors.append(f"{where} must be an object")
            continue
        if b.get("style") not in styles:
            errors.append(f"{where}: style must be one of {', '.join(styles)}, got {b.get('style')!r}")
        s = b.get("seconds")
        if not isinstance(s, (int, float)) or isinstance(s, bool) or not (0.5 <= s <= 12):
            errors.append(f"{where}: seconds must be a number from 0.5 to 12, got {s!r}")
        if not isinstance(b.get("line"), str) or not b["line"].strip():
            errors.append(f"{where}: line must be a non-empty sentence")
    return errors


def read_story(run_dir: Path) -> dict | None:
    p = workspace(run_dir) / "story.json"
    if not p.is_file() or "story" not in read_status(run_dir):
        return None
    try:
        return read_json(p)
    except (OSError, ValueError):
        return None


def save_story(run_dir: Path, config: dict, story: dict) -> dict:
    """The UI's story editor. Clean it, check it, save it; later steps then need a re-run."""
    styles = offered(config)["styles"]
    beats = [{"style": b.get("style"), "seconds": b.get("seconds"),
              "line": " ".join(str(b.get("line") or "").split())}
             for b in (story.get("beats") or []) if isinstance(b, dict)]
    clean = {"format": story.get("format") or "vertical", "beats": beats}
    errors = check_story(clean, styles)
    if errors:
        raise ValueError("\n".join(f"- {e}" for e in errors))
    write_json(workspace(run_dir) / "story.json", clean)
    _mark(run_dir, "story", "edited", clear=("scenes", "voice"))
    return clean


def run_story(run_dir: Path, config: dict) -> None:
    ws = prepare_workspace(run_dir, config)
    skill = offered(config)
    allowed = ["Read", "Write", "Edit", "Glob", "Grep"]
    printer = run_claude(ws, config, story_prompt(run_dir, config), allowed,
                         settings(config)["story_max_turns"], "story")
    try:
        data = read_json(ws / "story.json")
        errors = check_story(data, skill["styles"])
    except (OSError, ValueError) as e:
        errors = [f"story.json could not be read: {e}"]
    if errors and printer.session_id:
        print("[story] story.json needs fixing:\n  " + "\n  ".join(errors))
        fix = ("story.json failed VidGen's check:\n" + "\n".join(f"- {e}" for e in errors) +
               "\nFix story.json (and story.md to match). Do not touch anything else.")
        run_claude(ws, config, fix, allowed, 8, "story", resume=printer.session_id)
        try:
            data = read_json(ws / "story.json")
            errors = check_story(data, skill["styles"])
        except (OSError, ValueError) as e:
            errors = [f"story.json could not be read: {e}"]
    if errors:
        raise StepError("story.json is still not valid:\n" + "\n".join(f"- {e}" for e in errors))
    _mark(run_dir, "story", "claude", clear=("scenes", "voice"))
    print("\n[story] the story:")
    for i, b in enumerate(data["beats"], 1):
        print(f"  {i:>2}. [{b['style']}] {b['line']}")


# ------------------------------------------------------------------- scenes ----

def run_scenes(run_dir: Path, config: dict) -> None:
    if read_story(run_dir) is None:
        raise StepError("there is no story yet; run the story step first")
    ws = prepare_workspace(run_dir, config)
    allowed = ["Read", "Write", "Edit", "Glob", "Grep", "Bash(node render.cjs stills *)"]
    run_claude(ws, config, scenes_prompt(run_dir, config), allowed,
               settings(config)["scenes_max_turns"], "scenes")
    _mark(run_dir, "scenes", "claude", clear=("voice",))
    stills = sorted((ws / "stills").glob("*.jpg"))
    print(f"[scenes] done; {len(stills)} still(s) in code/stills/")


# -------------------------------------------------------------------- voice ----

def run_voice(run_dir: Path, config: dict) -> None:
    """Read every line in one ElevenLabs call and time the beats to it (the skill's voice.py,
    done with VidGen's ElevenLabs settings)."""
    import base64
    story = read_story(run_dir)
    if story is None:
        raise StepError("there is no story yet; run the story step first")
    ws = workspace(run_dir)
    if not settings(config)["voice"] or not config["format"]["rules"].get("narrator", True):
        _mark(run_dir, "voice", "off")
        print("[voice] this format has no narration; skipping")
        return
    if not os.environ.get("ELEVENLABS_API_KEY"):
        _mark(run_dir, "voice", "no key")
        for f in ("voice.mp3", "voice.json"):
            (ws / f).unlink(missing_ok=True)
        print("[voice] no ELEVENLABS_API_KEY, so the video will have no voice (the beats keep "
              "their seconds)")
        return
    import voice_cast
    from steps.voice import tts_with_timestamps
    lines = [b["line"].strip() for b in story["beats"]]
    text = " ".join(lines)
    voice_id = voice_cast.voice_for(run_dir, "narrator", config)
    print(f"[voice] reading {len(lines)} lines ({len(text)} characters) with voice {voice_id}...")
    data = tts_with_timestamps(text, voice_id, config, "voice")
    (ws / "voice.mp3").write_bytes(base64.b64decode(data["audio_base64"]))
    a = data["alignment"]
    ch, st = a["characters"], a["character_start_times_seconds"]
    end = a["character_end_times_seconds"][-1]
    starts, i = [], 0
    for line in lines:
        starts.append(st[min(i, len(st) - 1)])
        i += len(line) + 1
    for k, b in enumerate(story["beats"]):
        nxt = starts[k + 1] if k + 1 < len(lines) else end + 1.2
        b["seconds"] = round(max(0.6, nxt - starts[k]), 2)
    story["beats"][0]["seconds"] = round(story["beats"][0]["seconds"] + starts[0], 2)
    write_json(ws / "story.json", story)
    words, w0 = [], None
    for k, c in enumerate(list(ch) + [" "]):
        if c.isspace():
            if w0 is not None:
                said = "".join(ch[w0:k]).strip()
                words.append({"w": said.strip(".,!?").lower(), "say": said, "t": round(st[w0], 3)})
            w0 = None
        elif w0 is None:
            w0 = k
    write_json(ws / "voice.json", {"words": words})
    _mark(run_dir, "voice", "voiced")
    print(f"[voice] beats timed to voice.mp3; the video runs {end + 1.2:.1f}s")


# ------------------------------------------------------------------- render ----

# The files a render draws the picture from. A render newer than all of them, made with the
# same voice choice, is still the picture they would make.
PICTURE_FILES = ("story.json", "voice.mp3", "voice.json", "main.js", "index.html", "render.cjs")
PICTURE_DIRS = ("styles", "lib")


def _picture_changed_at(ws: Path) -> float:
    times = [(ws / f).stat().st_mtime for f in PICTURE_FILES if (ws / f).is_file()]
    for d in PICTURE_DIRS:
        if (ws / d).is_dir():
            times += [p.stat().st_mtime for p in (ws / d).rglob("*") if p.is_file()]
    return max(times, default=0.0)


def render_is_current(ws: Path, audio: bool) -> bool:
    out, note = ws / "out" / "video.mp4", ws / "out" / "render.json"
    if not out.is_file() or not note.is_file():
        return False
    try:
        same_voice = read_json(note).get("audio") == audio
    except (OSError, ValueError, AttributeError):
        return False
    return same_voice and out.stat().st_mtime >= _picture_changed_at(ws)


def run_render(run_dir: Path, config: dict) -> None:
    if read_story(run_dir) is None:
        raise StepError("there is no story yet; run the story step first")
    if "scenes" not in read_status(run_dir):
        print("[render] note: the scenes step has not run, so this renders the template's scenes")
    ws = prepare_workspace(run_dir, config)
    audio = (ws / "voice.mp3").is_file() and read_status(run_dir).get("voice", {}).get("value") == "voiced"
    out = ws / "out" / "video.mp4"
    if render_is_current(ws, audio):
        print("[render] nothing the picture is drawn from has changed since the last render, so it is "
              "kept and only the captions are made again")
    else:
        node = node_path(config)
        if not node:
            raise StepError("node was not found; install Node.js 20+ (Windows: winget install OpenJS.NodeJS.LTS)")
        cmd = [node, "render.cjs", "video"] + (["--audio", "voice.mp3"] if audio else [])
        print(f"[render] {' '.join(cmd[1:])}  (on Windows and Linux the 3D styles render in software; "
              f"a 20 second video can take several minutes)")
        out.unlink(missing_ok=True)
        (ws / "out" / "render.json").unlink(missing_ok=True)
        rc = _run_streamed(cmd, ws, tool_env(config), "render",
                           float(settings(config)["render_timeout_minutes"]) * 60)
        if rc != 0 or not out.is_file():
            raise StepError(f"render.cjs failed (exit {rc}); see the log above")
        write_json(ws / "out" / "render.json", {"audio": audio})
    captioned = add_captions(run_dir, config, out)
    shutil.copyfile(captioned or out, run_dir / "final.mp4")
    print(f"[render] saved {run_dir / 'final.mp4'}")


# ----------------------------------------------------------------- captions ----

CAPTION_HOLD_MAX = 1.6      # seconds a caption stays up when no word follows it (a pause, the end)


def caption_words(run_dir: Path) -> list[dict]:
    """[{"word": the word as written, "start": seconds}] for the whole video. Timed to the voice
    when there is one; without a voice each beat's line is spread over its seconds."""
    story = read_story(run_dir) or {"beats": []}
    lines = [str(b.get("line") or "").strip() for b in story["beats"]]
    ws = workspace(run_dir)
    voiced = read_status(run_dir).get("voice", {}).get("value") == "voiced"
    timed = []
    if voiced and (ws / "voice.json").is_file():
        try:
            timed = [w for w in read_json(ws / "voice.json").get("words") or []
                     if isinstance(w, dict) and isinstance(w.get("t"), (int, float))]
        except (OSError, ValueError, AttributeError):
            timed = []
    if timed:
        # Older voice.json files kept only lower-case words; the story's own words take their
        # place when the two line up one to one.
        written = " ".join(lines).split()
        same = len(written) == len(timed)
        return [{"word": str(w.get("say") or (written[i] if same else w.get("w") or "")), "start": float(w["t"])}
                for i, w in enumerate(timed)]
    words, at = [], 0.0
    for b, line in zip(story["beats"], lines):
        toks, length = line.split(), float(b.get("seconds") or 0)
        for i, t in enumerate(toks):
            words.append({"word": t, "start": round(at + i * length / max(1, len(toks)), 3)})
        at += length
    return words


def caption_events(words: list[dict], max_words: int, total: float) -> list[tuple[float, float, str]]:
    from steps.assemble import chunk_words
    chunks = chunk_words(words, max_words)
    events = []
    for i, ch in enumerate(chunks):
        start = min(float(ch["start"]), total)
        nxt = float(chunks[i + 1]["start"]) if i + 1 < len(chunks) else total
        end = min(nxt, start + CAPTION_HOLD_MAX, total)
        if end > start + 0.04:
            events.append((start, end, ch["text"]))
    return events


def add_captions(run_dir: Path, config: dict, video: Path) -> Path | None:
    """build/captioned.mp4: `video` with the spoken words burned in, in the run's caption style
    (the same captions as the image pipeline). None when there are none to add."""
    import caption_styles
    from media import probe_duration, require_ffmpeg, run_ffmpeg
    from steps import assemble as A
    style = caption_styles.for_run(run_dir, config)
    asm = caption_styles.apply(config["assemble"], style)
    asm = caption_styles.with_words(asm, caption_styles.words_for_run(run_dir, asm))
    asm = caption_styles.with_size(asm, caption_styles.size_for_run(run_dir))
    if asm.get("caption_style") == "off":
        print("[render] captions are off for this video")
        return None
    words = caption_words(run_dir)
    if not words:
        print("[render] no lines to caption")
        return None
    require_ffmpeg()
    build = run_dir / "build"
    build.mkdir(parents=True, exist_ok=True)
    try:
        w, h = A._video_size(video)          # 1920x1080 for a "wide" story
    except Exception:
        w, h = int(asm["width"]), int(asm["height"])
    if h != int(asm["height"]):                  # the caption sizes are for the format's height
        k = h / int(asm["height"])
        asm = {**asm, "caption_size": max(12, round(float(asm["caption_size"]) * k)),
               "caption_outline": max(1, round(float(asm["caption_outline"]) * k))}
    total = probe_duration(video)
    font = A.pick_caption_font(asm, build)
    cy, blur, pop = int(round(h * float(asm["caption_y"]))), int(asm["caption_blur"]), A.caption_pop(asm)
    events = caption_events(words, int(asm["caption_max_words"]), total)
    lines = A.ass_head(asm, font, w, h)
    lines += [f"Dialogue: 0,{A._ass_time(s)},{A._ass_time(e)},Caption,,0,0,0,,"
              f"{{\\an5\\pos({w // 2},{cy})\\blur{blur}{pop}}}{A._ass_escape(t)}" for s, e, t in events]
    (build / "captions.ass").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Paths relative to the build folder only, so no Windows drive letter reaches the filter.
    shutil.copyfile(video, build / "rendered.mp4")
    fonts = f":fontsdir={A.FONTS_SUBDIR}" if (build / A.FONTS_SUBDIR).is_dir() else ""
    look = "" if style == caption_styles.FORMAT else f", {caption_styles.title(style)} style"
    print(f"[render] burning {len(events)} captions{look}...")
    run_ffmpeg(["-i", "rendered.mp4", "-vf", f"ass=captions.ass{fonts},format=yuv420p",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                "-c:a", "copy", "captioned.mp4"], "captions", cwd=build)
    (build / "rendered.mp4").unlink(missing_ok=True)
    return build / "captioned.mp4"


STEP_FUNCS = {"story": run_story, "scenes": run_scenes, "voice": run_voice, "render": run_render}


def run_step(name: str, run_dir: Path, config: dict) -> None:
    if name not in STEP_FUNCS:
        raise StepError(f"the Claude Code engine's steps are {', '.join(CODE_STEPS)}, not '{name}'")
    print(f"\n=== step: {name} ({run_dir.name}, Claude Code engine) ===")
    import progress
    progress.step(name)
    STEP_FUNCS[name](run_dir, config)


def execute(run_dir: Path, config: dict, dry_run: bool = False) -> None:
    if dry_run:
        run_step("story", run_dir, config)
        print("\nstory only: read it, edit it if you like, then run the scenes, voice and render "
              "steps (or: python main.py step <run> scenes)")
        return
    for name in CODE_STEPS:
        run_step(name, run_dir, config)
    print(f"\nrun {run_dir.name} complete")
