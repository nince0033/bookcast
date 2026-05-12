# Quickstart — your first video in 30 minutes

This walks you from a fresh clone to a finished `final.mp4`. Two paths:

- **Path A** — you have a structured talk markdown already. ~25 min wall-clock.
- **Path B** — you have only a book or topic idea. Add 10 min for Claude (interactively) to produce the structured talk via the `book-deep-reader` skill.

## Prerequisites

```bash
python --version           # 3.10+
ffmpeg -version            # required
ffprobe -version           # comes with ffmpeg
pip install -r requirements.txt
```

If ffmpeg is missing on Windows: download from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), extract, add `bin/` to `PATH`.

## Step 1 — Get API keys

Only two needed:

| Service | Sign-up | Used for |
|---|---|---|
| MiniMax T2A v2 | https://platform.minimaxi.com/ | Chinese narration TTS |
| Apimart | https://apimart.ai/ | Image generation via gpt-image-2 |

(No Anthropic key needed at runtime — bookcast is fully local once the talk script is written.)

## Step 2 — Configure

```bash
cp config.env.example config.env
```

Edit `config.env` and paste in your two keys. The file is in `.gitignore` so it won't get committed.

## Step 3 — Get a structured talk script

bookcast's parser is **rule-based**, so the input markdown must follow a specific structure: YAML frontmatter, then paragraph + image-prompt pairs.

### Path A: you have one already

Save as `talk.md` in any location. Aim for **~80 paragraphs**, each 2–3 sentences (60–180 Chinese chars). That maps to a 20–25 minute video.

See [examples/zhuangzi/source_structured.md](../examples/zhuangzi/source_structured.md) for the exact format.

### Path B: have Claude write one (interactive)

Open this repo in Claude Code, then:

```
读 skills/book-deep-reader/SKILL.md。然后用樊登式风格把《被讨厌的勇气》做成
20-25 分钟讲书稿,按 bookcast 的结构化 md 格式输出,保存为 talk.md。
```

Claude will follow the skill's 7-step process and produce a file with frontmatter + ~80 shot blocks.

## Step 4 — Run the pipeline

```bash
python run_all.py --talk talk.md
```

What happens:

1. **parse_shots** (~1s) — slices `talk.md` into `script.json`.
2. **TTS** (~5min, ~¥2) — MiniMax generates one mp3 per shot.
3. **Measure audio** (~5s) — ffprobe writes actual durations back.
4. **Image gen** (~15min, ~¥15–40) — Apimart generates one image per shot.
5. **Slice images** (~30s) — crop to 16:9.
6. **Merge audio** (~5s) — concatenate mp3s.
7. **Assemble** (~5min) — ffmpeg builds final mp4 with Ken Burns, subtitles, BGM (if `sfx/bgm.mp3` exists).

Total: **~25 min wall-clock, ~¥17–42 spend**.

## Step 5 — Check the result

```
final.mp4          <- your video
subtitles.srt      <- standalone subtitles if you need them
audio/             <- the mp3s
images/            <- raw AI images
slices/            <- cropped versions
```

## Common adjustments

### "The voice sounds wrong"

```bash
# Edit script.json (or talk.md frontmatter): change voice_id
# Re-do shot 1 only, to A/B test:
python scripts/tts_minimaxi.py --shot 1 --force
# play audio/shot_001.mp3
```

When you're happy:

```bash
python scripts/tts_minimaxi.py --force
```

### "An image is wrong"

```bash
# Edit script.json: rewrite that shot's image_prompt
python scripts/img_apimart.py --shot 12 --force
```

### "I want to make a 9:16 short from the same content"

```bash
# Change script.json: aspect_ratio: "9:16"
# Re-slice + re-assemble. TTS and image gen don't need to rerun.
python run_all.py --from 5
```

## Stuck?

See [troubleshooting.md](troubleshooting.md).
