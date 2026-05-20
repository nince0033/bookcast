"""
Stage 1: Generate a structured talk markdown from raw input.

Two backends, auto-detected (priority: API > CLI):
  - ANTHROPIC_API_KEY set     -> Anthropic SDK (works for anyone with a key)
  - else `claude` CLI on PATH -> Claude Code subprocess (uses your CC quota)
  - else                      -> hard error

Usage:
    python scripts/generate_talk.py "<book name or short pasted text>" [opts]
    python scripts/generate_talk.py --file path/to/book.txt           [opts]

    --style 罗胖式 | 樊登式 | 刘擎式 | 默认
    --title "video title"
    --aspect 16:9 | 9:16 | 1:1
    --voice <minimax voice id>
    --speed 1.0
    --emotion calm | happy | sad | ...
    --style-anchor "<english style anchor with optional {scene}>"
    --bgm sfx/bgm.mp3
    --model claude-sonnet-4-6
    --backend auto | api | cli
    --out <path>         (default: <project>/talk.md)
    --project <dir>      (default: bookcast root)
"""
import os
import re
import sys
import shutil
import argparse
import subprocess
from pathlib import Path


# --- project resolution & env loading -------------------------------
def _resolve_project():
    args = sys.argv
    if "--project" in args:
        return Path(args[args.index("--project") + 1]).resolve()
    return Path(__file__).resolve().parent.parent


PROJECT = _resolve_project()
ROOT    = Path(__file__).resolve().parent.parent
_env_file = PROJECT / "config.env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
# --------------------------------------------------------------------


# --- lean system prompt (replaces sending the full SKILL.md) --------
SYSTEM_PROMPT = """You are writing a structured talk script for the bookcast video pipeline. The output goes directly into a parser, then TTS + image generation + video assembly. There is no human in the loop between you and the parser, so the format MUST be exact.

# OUTPUT FORMAT (strict)

Start with YAML frontmatter, then alternate paragraphs of Chinese narration with image-prompt lines. Like this:

```
---
title: <video title in Chinese>
aspect_ratio: "16:9"
voice_id: <voice id passed in>
voice_speed: 1.0
voice_emotion: calm
style_anchor: <english style description passed in>
bgm: sfx/bgm.mp3
---

<paragraph 1 of Chinese narration, 60-180 chars>

> 画面：<English image prompt for paragraph 1>

<paragraph 2>

> 画面：<English image prompt for paragraph 2>

(continue to the end)
```

# NARRATION RULES

1. Each paragraph = one shot = **60-180 Chinese characters** (roughly 2-3 sentences). Keep this length consistent — long shots feel slow, short shots feel choppy.
2. Conversational tone, NOT academic. Like talking to a friend.
3. Use pause markers inside narration: `<#0.6#>` for em-dash pauses, `<#0.8#>` for dramatic breaks.
4. Open with a HOOK in the very first paragraph: a question, a punch-in-the-gut observation, "如果你最近正在经历…" structure.
5. Arc: hook → context → core insight → examples / stories → call to action / closing image.
6. Use "我" sparingly but meaningfully — one or two "我自己…" or "我有个朋友…" stories make it feel human; too many feels fake.
7. Do NOT include section headers like `## 一、钩子段` — those will break the parser.
8. Do NOT include `---` separators between shots — only the one frontmatter `---` block at the top.

# IMAGE PROMPT RULES

1. English only. Image models work better with English.
2. Begin every prompt with a concrete subject (figure, scene, object).
3. Capture mood / metaphor, not literal narration. Abstract concepts -> concrete imagery.
4. Self-contained. NEVER reference other shots ("the same character as before" will fail).
5. NEVER mention text or characters being shown — image models render garbled fake text. Avoid book covers, signs, calligraphy in subjects unless you want them to come out as nonsense.
6. Keep the prompts 30-80 English words.
7. Do NOT repeat the style_anchor — that gets prepended automatically.

# HOST STYLE

The user message specifies one of:
- **罗胖式** — tight logic, knowledge nuggets, "you think X, but really Y" reversals, business/modern analogies. Short sharp sentences.
- **樊登式** — warm, life-grounded, personal stories, "我有个学员…", emotional resonance, focus on application to daily life.
- **刘擎式** — philosophical depth, "我们从两个角度看…", comfortable with ambiguity, brings in cross-cultural / cross-historical context.
- **默认** — balanced default, slightly informational with some warmth.

Match the chosen style throughout. Don't drift.

# TARGET LENGTH

- For 20-25 min finished video: 50-80 shots, ~5000-7000 Chinese characters total narration.
- For 30-35 min finished video: 80-120 shots, ~7000-10000 chars.

# WHAT TO OUTPUT

Just the .md content. Start with `---` on line 1. No code fences. No preamble. No commentary at the end. Pure parseable markdown.
"""


def build_user_prompt(content: str, args) -> str:
    return f"""Generate a structured bookcast talk script.

# Source

The user wants a talk script about the following. If it's a book name only, draw on your training knowledge to extract the core ideas. If it's pasted text, treat that as the source content — base your script on it without inventing material the source doesn't support.

---
{content}
---

# Configuration

- Host style: **{args.style}**
- Target length: ~{args.target_length} shots
- Frontmatter values to put in the output (use these exactly):
  - title: {args.title}
  - aspect_ratio: "{args.aspect}"
  - voice_id: {args.voice}
  - voice_speed: {args.speed}
  - voice_emotion: {args.emotion}
  - style_anchor: {args.style_anchor}
  - bgm: {args.bgm}

# Action

Generate the full structured talk markdown now. Output the entire document, starting with `---` on the first line. No commentary. No code fences. Just parseable markdown.
"""


def via_anthropic_api(system_prompt: str, user_prompt: str, model: str) -> str:
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic SDK not installed. Run: pip install anthropic")
        sys.exit(1)
    client = anthropic.Anthropic()
    print(f"[generate_talk] backend=api, model={model}", flush=True)
    resp = client.messages.create(
        model=model,
        max_tokens=16000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    print(f"[generate_talk] tokens: in={resp.usage.input_tokens} out={resp.usage.output_tokens}", flush=True)
    return resp.content[0].text


def via_claude_cli(system_prompt: str, user_prompt: str) -> str:
    """Invoke `claude` CLI in non-interactive mode.

    Combined prompt may be ~10k chars. Python's subprocess passes args directly
    to CreateProcess on Windows (max ~32k chars), no cmd.exe in between, so this
    handles long prompts.
    """
    combined = (
        f"SYSTEM INSTRUCTIONS:\n\n{system_prompt}\n\n"
        f"---\n\nUSER REQUEST:\n\n{user_prompt}"
    )
    print(f"[generate_talk] backend=cli (Claude Code subprocess), prompt {len(combined)} chars", flush=True)
    cmd = ["claude", "-p", combined, "--output-format", "text"]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "")[-500:]
        raise RuntimeError(f"claude CLI failed (exit {proc.returncode}): {msg}")
    return proc.stdout


def clean_output(text: str) -> str:
    """Strip code fences if Claude wrapped output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def pick_backend(requested: str) -> str:
    if requested == "api":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ERROR: backend=api but ANTHROPIC_API_KEY not set")
            sys.exit(1)
        return "api"
    if requested == "cli":
        if not shutil.which("claude"):
            print("ERROR: backend=cli but `claude` not on PATH")
            sys.exit(1)
        return "cli"
    # auto
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api"
    if shutil.which("claude"):
        return "cli"
    print(
        "ERROR: no backend available.\n"
        "  Either set ANTHROPIC_API_KEY in config.env (from https://console.anthropic.com/),\n"
        "  or install Claude Code (https://docs.claude.com/en/docs/claude-code) so `claude` is on PATH."
    )
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("content", nargs="?", help="Book name or pasted source text (overridden by --file)")
    ap.add_argument("--file", help="Read source from a .txt/.md file")
    ap.add_argument("--style", choices=["罗胖式", "樊登式", "刘擎式", "默认"], default="默认")
    ap.add_argument("--title", default="未命名讲书")
    ap.add_argument("--aspect", default="16:9", choices=["16:9", "9:16", "1:1"])
    ap.add_argument("--voice", default="audiobook_male_1")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--emotion", default="calm")
    ap.add_argument("--style-anchor", dest="style_anchor", default="cinematic, high quality, detailed")
    ap.add_argument("--bgm", default="sfx/bgm.mp3")
    ap.add_argument("--target-length", type=int, default=60, help="Approximate number of shots")
    ap.add_argument("--model", default="claude-sonnet-4-6")
    ap.add_argument("--backend", choices=["auto", "api", "cli"], default="auto")
    ap.add_argument("--out", default=None)
    ap.add_argument("--project", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    # Read source content
    if args.file:
        content = Path(args.file).read_text(encoding="utf-8")
    elif args.content:
        content = args.content
    else:
        print("ERROR: pass `content` positional or use --file")
        sys.exit(1)

    if not content.strip():
        print("ERROR: source content is empty")
        sys.exit(1)

    backend = pick_backend(args.backend)
    user_prompt = build_user_prompt(content, args)

    if backend == "api":
        text = via_anthropic_api(SYSTEM_PROMPT, user_prompt, args.model)
    else:
        text = via_claude_cli(SYSTEM_PROMPT, user_prompt)

    text = clean_output(text)

    if not text.startswith("---"):
        # Sometimes Claude adds a stray sentence before the frontmatter. Try to recover.
        idx = text.find("---")
        if idx > 0:
            text = text[idx:]
        else:
            print("WARNING: output does not start with frontmatter. Saving anyway.")

    out_path = Path(args.out) if args.out else (PROJECT / "talk.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")

    # Stats
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.DOTALL)
    blocks = re.split(r"\n\s*\n", body.strip())
    n_shots = sum(1 for b in blocks if b.strip() and not b.lstrip().startswith(">"))
    total_chars = sum(len(b.strip()) for b in blocks if b.strip() and not b.lstrip().startswith(">"))

    print(f"\n[generate_talk] Wrote {out_path}")
    print(f"  Shots: {n_shots}")
    print(f"  Total narration: ~{total_chars} chars")
    print(f"  Estimated video length: ~{total_chars / 4.5 / 60:.1f} min")


if __name__ == "__main__":
    main()
