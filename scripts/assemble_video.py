"""
Stage 6: Assemble final mp4 from slices + audio + subtitles + BGM (ffmpeg).

Each shot becomes a clip whose length matches its mp3, gets a Ken Burns
pan/zoom, and clips are concatenated. If audio/full_narration.mp3 exists,
a single-audio overlay mode is used instead. BGM is optional.

Usage:
    python scripts/assemble_video.py
    python scripts/assemble_video.py --bgm-volume 0.12 --no-subtitles
    python scripts/assemble_video.py --project <dir>
"""
import os, sys, json, subprocess, shutil, datetime
from pathlib import Path


def _resolve_project():
    args = sys.argv
    if "--project" in args:
        return Path(args[args.index("--project") + 1]).resolve()
    return Path(__file__).resolve().parent.parent


PROJECT  = _resolve_project()
SCRIPT   = PROJECT / "script.json"
AUDIO    = PROJECT / "audio"
SLICES   = PROJECT / "slices"
SFX      = PROJECT / "sfx"
SUB_FILE = PROJECT / "subtitles.srt"
OUT_FILE = PROJECT / "final.mp4"
STATE    = PROJECT / ".pipeline_state.json"
TMPDIR   = PROJECT / "_tmp_assemble"


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {}


def save_state(s):
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args():
    args = sys.argv[1:]
    opts = {"transition_duration": 0.5, "bgm_volume": 0.12, "subtitles": True}
    if "--transition-duration" in args:
        opts["transition_duration"] = float(args[args.index("--transition-duration") + 1])
    if "--bgm-volume" in args:
        opts["bgm_volume"] = float(args[args.index("--bgm-volume") + 1])
    if "--no-subtitles" in args:
        opts["subtitles"] = False
    return opts


def _fmt_time(s):
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:06.3f}".replace(".", ",")


def generate_srt(shots):
    lines = []
    t = 0.0
    for i, shot in enumerate(shots):
        dur = shot.get("actual_duration_seconds", shot.get("duration_hint_seconds", 30))
        start = _fmt_time(t)
        end   = _fmt_time(t + dur)
        # Strip pause markers like <#0.8#> from displayed subtitle text
        import re
        text = re.sub(r"<#[\d.]+#>", "", shot["narration"])
        lines.append(f"{i+1}")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
        t += dur
    SUB_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Generated subtitles.srt ({len(shots)} entries)")


def kenburns_vf(sid, dur, fps=30):
    """Fully static image, no motion. Pure scale-to-fit + framerate.

    Rationale: even pure-pan with fixed integer crop shows perceptible stepping
    when per-frame pixel advance is < 1px (long shots or slow pans). Removing
    all internal motion makes jitter mathematically impossible — every frame
    is byte-identical to the previous one within a shot. Variety between shots
    comes from xfade crossfades, which the eye reads as a single smooth blend
    operation rather than per-frame pixel motion.
    """
    return (
        f"scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
        f"fps={fps}"
    )


def concat_with_ffmpeg(shots, script, opts):
    TMPDIR.mkdir(exist_ok=True)
    ar = script.get("aspect_ratio", "16:9")
    suffix = ar.replace(":", "x")
    bgm_name = script.get("bgm", "bgm.mp3").split("/")[-1]
    bgm_path = SFX / bgm_name
    has_bgm  = bgm_path.exists()

    full_mp3 = AUDIO / "full_narration.mp3"
    single_audio_mode = full_mp3.exists()

    segments, missing = [], []
    for shot in shots:
        img = SLICES / f"shot_{shot['id']:03d}_{suffix}.png"
        if not img.exists():
            img = SLICES / f"shot_{shot['id']:03d}_16x9.png"
        dur = shot.get("actual_duration_seconds", shot.get("duration_hint_seconds", 30))
        if single_audio_mode:
            if not img.exists():
                missing.append(shot["id"])
                continue
            segments.append((img, None, dur, shot["id"]))
        else:
            mp3 = AUDIO / f"shot_{shot['id']:03d}.mp3"
            if not img.exists() or not mp3.exists():
                missing.append(shot["id"])
                continue
            segments.append((img, mp3, dur, shot["id"]))

    if missing:
        print(f"  WARNING: missing files for shots {missing}, skipping")
    if not segments:
        print("ERROR: no segments to assemble")
        return False

    # Pre-compute xfade transition time so we can pre-pad non-last clips.
    # Each clip i (except the last) is extended by T seconds of cloned tail.
    # The xfade then consumes those T seconds, so audio-timing of every shot
    # aligns precisely with its content first frame.
    T = float(opts.get("transition_duration", 0.5))

    clip_files = []
    if single_audio_mode:
        print(f"  Mode: single-audio (full_narration.mp3) + image timeline")
        last_idx = len(segments) - 1
        for idx, (img, _, dur, sid) in enumerate(segments):
            extended_dur = dur + T if idx < last_idx else dur
            clip = TMPDIR / f"clip_{sid:03d}.mp4"
            # Build vf: Ken Burns runs over the AUDIO portion (dur seconds), then
            # tpad clones the last frame for T seconds (only on non-last clips).
            vf = kenburns_vf(sid, dur)
            if idx < last_idx:
                vf = f"{vf},tpad=stop_mode=clone:stop_duration={T}"
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", str(img),
                "-t", str(extended_dur),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                "-vf", vf,
                str(clip),
            ]
            r = subprocess.run(cmd, capture_output=True)
            if r.returncode != 0:
                print(f"  FAIL clip {sid}: {r.stderr.decode(errors='replace')[-150:]}")
            else:
                clip_files.append(clip)
                print(f"  OK clip_{sid:03d}.mp4  ({extended_dur:.1f}s)")
    else:
        print(f"  Mode: per-shot audio")
        for img, mp3, dur, sid in segments:
            clip = TMPDIR / f"clip_{sid:03d}.mp4"
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", str(img),
                "-i", str(mp3),
                "-c:v", "libx264", "-c:a", "aac", "-b:a", "128k",
                "-pix_fmt", "yuv420p", "-shortest",
                "-vf", kenburns_vf(sid, dur),
                str(clip),
            ]
            r = subprocess.run(cmd, capture_output=True)
            if r.returncode != 0:
                print(f"  FAIL clip {sid}: {r.stderr.decode(errors='replace')[-150:]}")
            else:
                clip_files.append(clip)
                print(f"  OK clip_{sid:03d}.mp4")

    # Merge clips with crossfade transitions (xfade chain).
    # Each non-last clip was already padded by +T at render time, so the xfade
    # eats the padding, not real content. Net total = sum(audio_durations).
    N = len(clip_files)
    merged = TMPDIR / "merged.mp4"

    if N == 1:
        shutil.copy(clip_files[0], merged)
    else:
        audio_durations = [seg[2] for seg in segments[:N]]
        # Extended per-clip durations: d_i + T for all but the last, last is d_i
        extended_durations = [d + T for d in audio_durations[:-1]] + [audio_durations[-1]]

        # Build chained xfade filter graph. Offset uses extended durations so
        # that shot i's content first frame appears at output time sum_{j<i} d_j,
        # i.e. exactly when shot i's audio starts.
        parts = []
        prev_label = "0:v"
        running_sum = 0.0
        for i in range(1, N):
            running_sum += extended_durations[i - 1]
            offset = running_sum - i * T
            label = f"v{i}" if i < N - 1 else "vout"
            parts.append(
                f"[{prev_label}][{i}:v]xfade=transition=fade:duration={T}:offset={offset:.3f}[{label}]"
            )
            prev_label = label
        filter_complex = ";".join(parts)

        inputs = []
        for c in clip_files:
            inputs.extend(["-i", str(c)])

        cmd = ["ffmpeg", "-y"] + inputs + [
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-crf", "20", "-preset", "medium", "-r", "30",
            str(merged),
        ]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0:
            print(f"ERROR xfade merge: {r.stderr.decode(errors='replace')[-400:]}")
            return False
        print(f"  OK xfade chain ({N} clips, {T}s transitions)")

    if single_audio_mode:
        with_narration = TMPDIR / "with_narration.mp4"
        r = subprocess.run([
            "ffmpeg", "-y",
            "-i", str(merged), "-i", str(full_mp3),
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-shortest", str(with_narration),
        ], capture_output=True)
        if r.returncode == 0:
            merged = with_narration
            print("  OK narration overlaid")
        else:
            print(f"  FAIL narration overlay: {r.stderr.decode(errors='replace')[-200:]}")
            return False

    if has_bgm:
        final_tmp = TMPDIR / "with_bgm.mp4"
        vol = opts["bgm_volume"]
        r = subprocess.run([
            "ffmpeg", "-y",
            "-i", str(merged),
            "-stream_loop", "-1", "-i", str(bgm_path),
            "-filter_complex",
            f"[1:a]volume={vol}[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(final_tmp),
        ], capture_output=True)
        if r.returncode == 0:
            merged = final_tmp
        else:
            print(f"  BGM mix failed (continuing without): {r.stderr.decode(errors='replace')[-200:]}")

    if opts["subtitles"] and SUB_FILE.exists():
        final_sub = TMPDIR / "with_subs.mp4"
        sub_escaped = str(SUB_FILE.absolute()).replace("\\", "/").replace(":", "\\:")
        r = subprocess.run([
            "ffmpeg", "-y",
            "-i", str(merged),
            "-vf", f"subtitles='{sub_escaped}':force_style='FontName=Source Han Sans SC,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,MarginV=40'",
            "-c:a", "copy", "-c:v", "libx264", "-crf", "18", "-preset", "slow",
            str(final_sub),
        ], capture_output=True)
        if r.returncode == 0:
            merged = final_sub
        else:
            print(f"  Subtitle burn failed (continuing without): {r.stderr.decode(errors='replace')[-200:]}")

    shutil.copy(merged, OUT_FILE)
    size_mb = OUT_FILE.stat().st_size / 1024 / 1024
    print(f"\nOK final.mp4 ({size_mb:.1f} MB) -> {OUT_FILE}")
    return True


def main():
    opts   = parse_args()
    script = json.loads(SCRIPT.read_text(encoding="utf-8"))
    shots  = script["shots"]

    generate_srt(shots)

    total_dur = sum(
        s.get("actual_duration_seconds", s.get("duration_hint_seconds", 30))
        for s in shots
    )
    print(f"[assemble] {len(shots)} shots | est. {total_dur/60:.1f} min")
    print(f"  BGM volume: {opts['bgm_volume']} | Transition: {opts['transition_duration']}s")

    ok = concat_with_ffmpeg(shots, script, opts)
    if ok:
        state = load_state()
        state["stage_completed"] = 6
        state["timestamp"] = datetime.datetime.now().isoformat()
        save_state(state)
        print("[assemble] Complete")
    else:
        print("[assemble] Failed - see errors above")


if __name__ == "__main__":
    main()
