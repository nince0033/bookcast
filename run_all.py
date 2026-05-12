"""
bookcast - one-shot orchestrator.

Runs the full pipeline:
    (1) parse_shots.py talk.md -> script.json   [if --talk given, else skipped]
    (2) tts_minimaxi   script.json -> audio/*.mp3
    (3) measure_audio  fills in actual_duration_seconds
    (4) img_apimart    script.json -> images/*.png
    (5) slice_image    images -> slices/*.png
    (6) merge_audio    audio/*.mp3 -> audio/full_narration.mp3 (optional)
    (7) assemble_video slices + audio + subtitles -> final.mp4

Usage:
    python run_all.py                          # skip shotify, expect script.json present
    python run_all.py --talk my_talk.md        # full pipeline from talk
    python run_all.py --from 4                 # resume from step 4
    python run_all.py --only 5                 # run only step 5
    python run_all.py --project <dir>          # run on a different project dir
"""
import os, sys, subprocess
from pathlib import Path


def _resolve_project():
    args = sys.argv
    if "--project" in args:
        return Path(args[args.index("--project") + 1]).resolve()
    return Path(__file__).resolve().parent


PROJECT = _resolve_project()
SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"


def load_env():
    env_file = PROJECT / "config.env"
    if not env_file.exists():
        print(f"ERROR: {env_file} not found")
        print("       Copy config.env.example to config.env and fill in API keys.")
        sys.exit(1)
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()


def run(script_name, extra_args, desc):
    print(f"\n{'='*60}\n>> {desc}\n{'='*60}")
    cmd = [sys.executable, str(SCRIPTS_DIR / script_name)] + extra_args + ["--project", str(PROJECT)]
    r = subprocess.run(cmd, cwd=str(PROJECT))
    if r.returncode != 0:
        print(f"\nFAIL: {desc} (exit {r.returncode})")
        print(f"      Fix the error, then resume with: python run_all.py --from <N>")
        sys.exit(r.returncode)
    print(f"OK: {desc}")


def check_prereqs(have_talk):
    errors = []
    if not have_talk and not (PROJECT / "script.json").exists():
        errors.append("No script.json found and --talk not given. "
                      "Either pass --talk <file.md> or place script.json in the project dir.")
    keys_needed = ["MINIMAX_API_KEY", "APIMART_API_KEY"]
    for k in keys_needed:
        if not os.environ.get(k):
            errors.append(f"Missing env var: {k} (set in config.env)")
    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        sys.exit(1)
    print("OK: prerequisites pass")


def main():
    args = sys.argv[1:]

    # Strip --project (already consumed for PROJECT resolution)
    if "--project" in args:
        i = args.index("--project")
        del args[i:i+2]

    talk_path = None
    if "--talk" in args:
        i = args.index("--talk")
        talk_path = str(Path(args[i + 1]).resolve())
        del args[i:i+2]

    start_from = 1
    only_step = None
    if "--from" in args:
        i = args.index("--from")
        start_from = int(args[i + 1])
        del args[i:i+2]
    if "--only" in args:
        i = args.index("--only")
        only_step = int(args[i + 1])
        del args[i:i+2]

    # Everything remaining is forwarded to parse_shots.py (e.g. --voice, --style)
    parser_extra = args

    print(f"\nbookcast pipeline")
    print(f"  Project: {PROJECT}")
    print(f"  Scripts: {SCRIPTS_DIR}")

    load_env()
    if only_step is None and start_from == 1:
        check_prereqs(have_talk=talk_path is not None)

    # Pre-step: parse_shots if talk given
    if talk_path and (start_from == 1 or only_step in (None, 1)):
        run("parse_shots.py", [talk_path] + parser_extra, "parse_shots: talk -> script.json")

    steps = [
        ("tts_minimaxi.py",   [], "TTS narration"),
        ("measure_audio.py",  [], "Measure audio durations"),
        ("img_apimart.py",    [], "Generate images"),
        ("slice_image.py",    [], "Slice images to aspect ratio"),
        ("merge_audio.py",    [], "Merge all mp3s (optional)"),
        ("assemble_video.py", [], "Assemble final.mp4"),
    ]
    n_steps = len(steps)

    if only_step is not None:
        # 1=shotify (handled above), 2..n_steps+1=below
        idx = only_step - 2
        if 0 <= idx < n_steps:
            name, extra, desc = steps[idx]
            run(name, extra, f"[{only_step}] {desc}")
        return

    # start_from: 1=shotify, 2=tts, 3=measure, 4=img, 5=slice, 6=merge, 7=assemble
    start_idx = max(0, start_from - 2)
    for k in range(start_idx, n_steps):
        name, extra, desc = steps[k]
        run(name, extra, f"[{k+2}/{n_steps+1}] {desc}")

    final = PROJECT / "final.mp4"
    if final.exists():
        size_mb = final.stat().st_size / 1024 / 1024
        print(f"\n{'='*60}\nDONE: {final} ({size_mb:.1f} MB)\n{'='*60}")


if __name__ == "__main__":
    main()
