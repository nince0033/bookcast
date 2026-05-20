"""
Stage 2: Parse a structured talk markdown into script.json.

Expected input format (produced by book-deep-reader SKILL.md):

    ---
    title: <video title>
    aspect_ratio: 16:9
    voice_id: <minimax voice id>
    voice_speed: 1.0
    voice_emotion: calm
    style_anchor: <english phrase>
    bgm: sfx/bgm.mp3
    ---

    <narration paragraph 1>

    > 画面：<english image prompt 1>

    <narration paragraph 2>

    > 画面：<english image prompt 2>

    ...

Each natural paragraph is a shot; the "> 画面：..." line that follows it
is that shot's image_prompt. Blank lines separate paragraphs.

Usage:
    python scripts/parse_shots.py talk.md
    python scripts/parse_shots.py talk.md --out script.json
    python scripts/parse_shots.py talk.md --aspect 9:16 --voice xxx  # override frontmatter

No API key required. No network calls.
"""
import os, sys, re, json, argparse
from pathlib import Path


def _resolve_project():
    args = sys.argv
    if "--project" in args:
        return Path(args[args.index("--project") + 1]).resolve()
    return Path(__file__).resolve().parent.parent


PROJECT = _resolve_project()


IMAGE_PREFIXES = ("> 画面：", "> 画面:", "> [image]", "> image:", "> 画面 ", ">画面：")


def parse_frontmatter(text):
    """Return (frontmatter_dict, body_text). Supports YAML-style --- delimited block."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    fm_text, body = m.group(1), m.group(2)
    fm = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        # Strip surrounding quotes
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        # Coerce numbers
        if re.match(r"^-?\d+\.\d+$", v):
            v = float(v)
        elif re.match(r"^-?\d+$", v):
            v = int(v)
        fm[k] = v
    return fm, body


def parse_shots_from_body(body):
    """Walk paragraphs. A paragraph is a non-image block; the FIRST image line
    after it becomes that shot's image_prompt."""
    # Normalize line endings
    body = body.replace("\r\n", "\n").strip()
    # Split into blocks separated by blank lines
    blocks = re.split(r"\n\s*\n", body)
    shots = []
    pending_narration = None
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        # Check if this block starts with an image-prompt marker
        first_line = block.splitlines()[0].lstrip()
        is_image = any(first_line.startswith(p) for p in IMAGE_PREFIXES)
        if is_image:
            if pending_narration is None:
                # Image without preceding narration - skip with warning
                print(f"WARNING: image block has no preceding narration: {block[:60]}...")
                continue
            # Strip the prefix from the image text
            img_text = block
            for p in IMAGE_PREFIXES:
                if img_text.lstrip().startswith(p):
                    idx = img_text.find(p)
                    img_text = img_text[idx + len(p):].strip()
                    break
            # If image block spans multiple lines, join them
            img_lines = []
            for ln in img_text.splitlines():
                ln = ln.lstrip("> ").rstrip()
                img_lines.append(ln)
            img_prompt = " ".join(l for l in img_lines if l).strip()
            shots.append({
                "narration": pending_narration,
                "image_prompt": img_prompt,
            })
            pending_narration = None
        else:
            # If we already had pending narration without an image, flush as shot with empty image
            if pending_narration is not None:
                shots.append({
                    "narration": pending_narration,
                    "image_prompt": "",
                })
            # Treat any leading "#" headers as plain narration (strip the #)
            cleaned = "\n".join(
                re.sub(r"^#+\s*", "", ln) for ln in block.splitlines()
            ).strip()
            # Collapse internal newlines to spaces for cleaner TTS reading
            cleaned = re.sub(r"\s+", " ", cleaned)
            pending_narration = cleaned

    if pending_narration is not None:
        shots.append({"narration": pending_narration, "image_prompt": ""})

    return shots


def estimate_duration(text, chars_per_sec=4.5):
    # Strip pause markers, count chars
    stripped = re.sub(r"<#[\d.]+#>", "", text)
    return round(len(stripped) / chars_per_sec, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("talk", help="Path to structured talk script (.md)")
    ap.add_argument("--out", default=None, help="Output script.json path (default: <project>/script.json)")
    ap.add_argument("--aspect", default=None, choices=["16:9", "9:16", "1:1", None])
    ap.add_argument("--voice", default=None, help="MiniMax voice_id override")
    ap.add_argument("--speed", type=float, default=None)
    ap.add_argument("--emotion", default=None)
    ap.add_argument("--style", default=None, help="style_anchor override")
    ap.add_argument("--title", default=None)
    ap.add_argument("--bgm", default=None)
    ap.add_argument("--image-model", default=None, help="Image generator model (default: gpt-image-2)")
    ap.add_argument("--project", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    talk_path = Path(args.talk).resolve()
    if not talk_path.exists():
        print(f"ERROR: {talk_path} not found")
        sys.exit(1)

    text = talk_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    shots_raw = parse_shots_from_body(body)

    if not shots_raw:
        print(f"ERROR: no shots parsed from {talk_path}")
        print("       The file must have non-image paragraphs followed by '> 画面：...' lines.")
        sys.exit(1)

    # Build final script.json (frontmatter values take effect unless --flag overrides)
    def resolve(field, cli_val, default):
        if cli_val is not None:
            return cli_val
        if field in fm:
            return fm[field]
        return default

    script = {
        "title":        resolve("title", args.title, talk_path.stem),
        "aspect_ratio": resolve("aspect_ratio", args.aspect, "16:9"),
        "voice_id":     resolve("voice_id", args.voice, "audiobook_male_1"),
        "voice_speed":  resolve("voice_speed", args.speed, 1.0),
        "voice_emotion": resolve("voice_emotion", args.emotion, ""),
        "image_model":  resolve("image_model", args.image_model, "gpt-image-2"),
        "bgm":          resolve("bgm", args.bgm, "sfx/bgm.mp3"),
        "style_anchor": resolve("style_anchor", args.style, "cinematic, high quality, detailed"),
        "shots": [],
    }

    for i, s in enumerate(shots_raw, start=1):
        script["shots"].append({
            "id": i,
            "narration": s["narration"],
            "image_prompt": s["image_prompt"] or "atmospheric scene matching the mood of the narration",
            "duration_hint_seconds": estimate_duration(s["narration"]),
        })

    out_path = Path(args.out) if args.out else (PROJECT / "script.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

    total_chars = sum(len(s["narration"]) for s in script["shots"])
    total_dur = sum(s["duration_hint_seconds"] for s in script["shots"])
    no_image = sum(1 for s in shots_raw if not s["image_prompt"])

    print(f"[parse] Wrote {out_path}")
    print(f"  Shots: {len(script['shots'])}")
    print(f"  Total narration: {total_chars} chars (~{total_dur/60:.1f} min spoken)")
    if no_image:
        print(f"  WARNING: {no_image} shot(s) had no image prompt (using fallback)")


if __name__ == "__main__":
    main()
