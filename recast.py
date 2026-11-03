"""recast: sync a run's script.json with the locked character descriptions in config.yaml."""

from __future__ import annotations

from pathlib import Path

from common import read_script, write_json


def recast_run(run_dir: Path, config: dict) -> dict:
    """Replace stale locked descriptions in script.json and drop the affected reference sheets.

    Returns a summary dict: changed ids, deleted sheet paths, affected shot numbers, and the
    shots where an old description was not found verbatim in the image_prompt."""
    script = read_script(run_dir)
    locked = {c["id"]: c["description"] for c in config.get("locked_characters", [])}

    changed: dict[str, tuple[str, str]] = {}
    for c in script["characters"]:
        new = locked.get(c["id"])
        if new is not None and c["description"] != new:
            changed[c["id"]] = (c["description"], new)
            c["description"] = new

    not_found: list[tuple[int, str]] = []
    for shot in script["shots"]:
        for cid, (old, new) in changed.items():
            if cid not in shot["characters"]:
                continue
            if old in shot["image_prompt"]:
                shot["image_prompt"] = shot["image_prompt"].replace(old, new)
            else:
                not_found.append((shot["n"], cid))

    if changed:
        write_json(run_dir / "script.json", script)

    # Sheets to drop: every changed character, plus Iro (its reference now comes from config).
    stale_ids = set(changed) | {"iro"}
    deleted: list[Path] = []
    for cid in sorted(stale_ids):
        sheet = run_dir / "characters" / f"{cid}.png"
        if sheet.exists():
            sheet.unlink()
            deleted.append(sheet)

    affected = sorted(s["n"] for s in script["shots"]
                      if stale_ids.intersection(s["characters"]))
    return {"changed": changed, "deleted": deleted, "shots": affected, "not_found": not_found}


def run(run_dir: Path, config: dict) -> None:
    summary = recast_run(run_dir, config)

    if summary["changed"]:
        print("[recast] descriptions updated:")
        for cid, (old, new) in summary["changed"].items():
            print(f"  {cid}:\n    - {old}\n    + {new}")
    else:
        print("[recast] every locked description already matches config")

    for n, cid in summary["not_found"]:
        print(f"  warning: shot {n} lists {cid} but its old description was not found verbatim "
              f"in image_prompt; edit that prompt by hand")

    if summary["deleted"]:
        print("[recast] deleted reference sheets:")
        for p in summary["deleted"]:
            print(f"  {p.relative_to(run_dir)}")

    shots = summary["shots"]
    if shots:
        joined = ",".join(str(n) for n in shots)
        print(f"[recast] shots to regenerate ({len(shots)}): {joined}")
        print(f"  python main.py step {run_dir.name} images --only {joined}")
        print(f"  python main.py step {run_dir.name} video --only {joined}   # animated ones only")
    else:
        print("[recast] no shots affected")
