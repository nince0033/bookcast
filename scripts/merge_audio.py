"""
Stage 5b: Concatenate all shot mp3s into audio/full_narration.mp3 via ffmpeg.

Usage:
    python scripts/merge_audio.py
    python scripts/merge_audio.py --project <dir>
"""
import os, sys, subprocess
from pathlib import Path


def _resolve_project():
    args = sys.argv
    if "--project" in args:
        return Path(args[args.index("--project") + 1]).resolve()
    return Path(__file__).resolve().parent.parent


PROJECT = _resolve_project()
AUDIO   = PROJECT / "audio"


def main():
    lines = []
    for i in range(1, 500):
        p = AUDIO / f"shot_{i:03d}.mp3"
        if not p.exists():
            break
        lines.append(f"file '{p.absolute().as_posix()}'")

    if not lines:
        print("ERROR: no shot mp3 files found in audio/")
        sys.exit(1)

    concat_file = PROJECT / "_audio_concat.txt"
    concat_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Listed {len(lines)} audio files")

    out = AUDIO / "full_narration.mp3"
    r = subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(out),
    ])
    if r.returncode == 0:
        mb = out.stat().st_size / 1024 / 1024
        print(f"[merge] OK full_narration.mp3 ({mb:.1f} MB)")
    else:
        sys.exit(r.returncode)


if __name__ == "__main__":
    main()
