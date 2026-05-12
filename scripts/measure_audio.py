"""
Stage 3b: Measure actual mp3 durations via ffprobe and write them
back to script.json so downstream stages know real timing.

Usage:
    python scripts/measure_audio.py
    python scripts/measure_audio.py --project <dir>

Requires `ffprobe` on PATH (comes with ffmpeg).
"""
import os, sys, json, subprocess
from pathlib import Path


def _resolve_project():
    args = sys.argv
    if "--project" in args:
        return Path(args[args.index("--project") + 1]).resolve()
    return Path(__file__).resolve().parent.parent


PROJECT = _resolve_project()
SCRIPT  = PROJECT / "script.json"
AUDIO   = PROJECT / "audio"


def ffprobe_duration(path):
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    info = json.loads(r.stdout)
    for stream in info.get("streams", []):
        if "duration" in stream:
            return float(stream["duration"])
    return None


def main():
    script  = json.loads(SCRIPT.read_text(encoding="utf-8"))
    total   = 0.0
    missing = 0

    for shot in script["shots"]:
        mp3 = AUDIO / f"shot_{shot['id']:03d}.mp3"
        if not mp3.exists():
            print(f"  - shot_{shot['id']:03d}.mp3 missing, skipping")
            missing += 1
            continue
        dur = ffprobe_duration(mp3)
        if dur is None:
            print(f"  ? shot_{shot['id']:03d}: could not measure duration")
            continue
        shot["actual_duration_seconds"] = round(dur, 2)
        total += dur
        print(f"  shot_{shot['id']:03d}: {dur:.1f}s")

    SCRIPT.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    mins = total / 60
    print(f"\n[measure] Wrote durations | Total {mins:.1f} min | Missing {missing}")


if __name__ == "__main__":
    main()
