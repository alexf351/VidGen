"""Wide app screens shown on a laptop the hero is watching.

Iro is a web app as well as a phone app, and some of what a video can show is wide: a showreel,
a recording of the web app. A wide picture would be a thin strip on a phone, so an app-screen
shot whose picture is wider than it is tall (app_assets.is_wide) goes on a laptop instead.

It works like the hand-held phone (phone_hand.py). The images step draws ONE picture per
format: the hero seen from behind at a desk, in front of an open laptop whose screen is plain
chroma-key green. The assemble step finds the green rectangle and puts the real picture or
recording there; the back of his head stays in front of it.

    characters_cache/desk@<format>-<hash>.png    the desk picture, reused by every run
    runs/<id>/app/desk.png                       this run's copy

Formats without `app_screen_hand`, and a desk picture with no clean green screen, get a plain
laptop drawn by VidGen on the previous shot, blurred (steps/assemble.py compose_laptop_mockup).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import phone_hand
from common import ROOT

GREEN = phone_hand.GREEN


def enabled(config: dict) -> bool:
    return phone_hand.enabled(config)


def run_path(run_dir: Path) -> Path:
    return Path(run_dir) / "app" / "desk.png"


def wanted(script: dict | None) -> bool:
    """True when the script shows at least one wide app screen."""
    import app_assets
    return any(app_assets.is_wide(str(s.get("app_screen") or "")) for s in (script or {}).get("shots", [])
               if isinstance(s, dict) and s.get("app_screen"))


def prompt(config: dict, script: dict | None = None) -> str:
    style = str(config.get("style") or "").strip()
    who = phone_hand._holder(config, script)
    return (
        f"{style}, over-the-shoulder shot from directly behind a person sitting at a desk, watching an "
        f"open laptop. The person is {who}; only the back of the head and the shoulders are in the "
        "picture, low in the frame and slightly out of focus, and the face is not seen. "
        "The laptop stands on the desk in the upper middle of the frame, facing the camera straight on, "
        "level, not tilted and not seen from the side; its screen is as wide as most of the frame and the head "
        "does not cover it. "
        f"The laptop's screen is ONE flat rectangle of solid pure bright green (chroma key green, {GREEN}): "
        "no reflection, no glare, no gradient, no icons, no text, nothing on it. "
        "Thin dark bezel, a dark keyboard below it. Dark, softly blurred room, the screen's light on the "
        "desk and the shoulders. No text anywhere."
    )


def cache_path(config: dict, script: dict | None = None) -> Path:
    key = hashlib.sha1(prompt(config, script).encode()).hexdigest()[:12]
    fmt = config.get("format") or {}
    name = re.sub(r"[^a-z0-9_-]", "", str(fmt.get("extends") or fmt.get("name") or "format").lower())
    return ROOT / config["characters_cache_dir"] / f"desk@{name}-{key}.png"


def usable(path: Path) -> bool:
    return phone_hand.usable(path, wide=True)


def screen_bottom(template: Path, w: int, h: int) -> int | None:
    return phone_hand.screen_bottom(template, w, h, wide=True)


def compose(template: Path, picture: Path, out: Path, w: int, h: int) -> Path | None:
    """The picture on the laptop in the desk picture, at w x h. None when the desk picture has
    no clean green screen (the caller then draws the plain laptop)."""
    return phone_hand.compose(template, picture, out, w, h, wide=True)
