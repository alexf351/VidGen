"""preview.py: render a quick preview of one beat (or all of them) and print its REPORT line.

    python preview.py 3 blockout             beat 3 at the blockout pass, mid-beat
    python preview.py 3 final --t 0.4        beat 3, final pass, 0.4 s into the beat
    python preview.py all material           every beat, one picture each

The picture lands in stills/bNN_<stage>.jpg (with --t: bNN_<stage>_t0.4.jpg): Read it. The
REPORT line has the census (must read zero), the objects outside the frame and any warnings.
Blender, the device and the preview size come from blender.json, which VidGen writes.
"""

import json
import os
import subprocess
import sys

WS = os.path.dirname(os.path.abspath(__file__))
STAGES = ("blockout", "bevel", "material", "final")


def usage(msg):
    print(f"preview.py: {msg}\nusage: python preview.py <beat number | all> <{' | '.join(STAGES)}> [--t SECONDS]")
    sys.exit(2)


def one(cfg, beat, stage, t):
    out = f"stills/b{beat:02d}_{stage}" + (f"_t{t:g}" if t is not None else "") + ".jpg"
    cmd = [cfg["blender"], "--background", "--factory-startup", "--python-exit-code", "1",
           "--python", os.path.join(WS, "beat.py"), "--",
           "--beat", str(beat), "--stage", stage, "--mode", "still", "--out", out,
           "--res", cfg.get("preview_res", "540x960"), "--samples", str(cfg.get("preview_samples", 24)),
           "--fps", str(cfg.get("fps", 24)), "--device", cfg.get("device", "CPU"),
           "--engine", cfg.get("engine", "CYCLES")]
    if t is not None:
        cmd += ["--t", str(t)]
    try:
        p = subprocess.run(cmd, cwd=WS, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=int(cfg.get("preview_timeout_s", 600)))
    except subprocess.TimeoutExpired:
        print(f"beat {beat}: the preview took longer than {cfg.get('preview_timeout_s', 600)} s; make the scene lighter")
        return False
    lines = (p.stdout or "").splitlines() + (p.stderr or "").splitlines()
    report = [ln for ln in lines if ln.startswith("REPORT ")]
    if p.returncode != 0 or not report:
        print(f"beat {beat}: Blender failed (exit {p.returncode}). The end of its output:")
        keep = [ln for ln in lines if ln.strip() and "CUEW" not in ln and "HIPEW" not in ln]
        print("\n".join(keep[-25:]))
        return False
    print(report[-1])
    return True


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        usage("say which beat and which pass")
    t = None
    if "--t" in a:
        i = a.index("--t")
        try:
            t = float(a[i + 1])
        except (IndexError, ValueError):
            usage("--t needs a number of seconds")
        del a[i:i + 2]
    which, stage = a[0], a[1]
    if stage not in STAGES:
        usage(f"the pass must be one of {', '.join(STAGES)}")
    try:
        cfg = json.load(open(os.path.join(WS, "blender.json"), encoding="utf-8"))
    except (OSError, ValueError):
        print("preview.py: blender.json is missing; VidGen writes it when the step starts")
        sys.exit(2)
    beats = len(json.load(open(os.path.join(WS, "story.json"), encoding="utf-8"))["beats"])
    if which == "all":
        todo = list(range(1, beats + 1))
    else:
        try:
            todo = [int(which)]
        except ValueError:
            usage(f"{which!r} is not a beat number")
        if not 1 <= todo[0] <= beats:
            usage(f"the story has beats 1 to {beats}")
    ok = all([one(cfg, b, stage, t) for b in todo])
    sys.exit(0 if ok else 1)


main()
