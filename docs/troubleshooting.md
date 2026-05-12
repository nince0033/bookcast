# Troubleshooting

## Setup / environment

### `ERROR: MINIMAX_API_KEY not set` even though I set it

Two common causes:

1. **You set it in PowerShell as `$env:MINIMAX_API_KEY = "..."` but ran the script from Bash/Git Bash.** PowerShell session env vars don't cross shells. Easiest fix: put it in `config.env` — every script reads that file at startup.
2. **You set it in Windows User Environment Variables after starting your terminal.** Restart the terminal. Or just use `config.env`.

### `UnicodeEncodeError: 'gbk' codec can't encode character '✓'`

You're on Windows and a script tried to print a Unicode emoji. The bookcast scripts have been audited to use ASCII-only output. If you see this, you're running an older copy. Re-pull.

If you're writing your own additions, never print `✓ ✗ →`. Use `OK FAIL ->`.

### `ffprobe: command not found`

`ffmpeg` is missing. Windows: get a static build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), unzip, add `bin/` to `PATH`. macOS: `brew install ffmpeg`. Linux: `apt install ffmpeg`.

---

## parse_shots.py

### `ERROR: no shots parsed from talk.md`

Your input doesn't match the expected structured format. Check:

- YAML frontmatter is present (`---` delimited block at the top)
- Each shot has a narration paragraph followed by a `> 画面：...` (or `> [image] ...`) line
- Paragraphs are separated by blank lines
- No stray `## headings` between shots (the parser treats these as narration)

Run `parse_shots.py talk.md` directly to see the warning messages.

### "Some shots got generic image prompts"

That means a narration paragraph had no `> 画面：` line after it. The parser fills in a fallback. Add the image prompt and re-run from stage 1.

### Frontmatter values not being picked up

YAML frontmatter is parsed line-by-line. Each line must be `key: value`, one per line. No nested objects, no inline arrays. If you need quotes, use straight quotes `"..."` not curly quotes.

---

## TTS (MiniMax)

### `HTTP 401: invalid_api_key`

Your `MINIMAX_API_KEY` is wrong, expired, or has insufficient balance. Log into the MiniMax console and verify.

### `base_resp.status_code: 1002` (rate limit)

The script retries automatically. If it keeps hitting limits, increase `time.sleep(3)` in the main loop to `time.sleep(6)` or upgrade your MiniMax tier.

### Output is silent / corrupted mp3

Run with `--shot N --force` on the bad shot. Check that:

- Your `voice_id` is a string that MiniMax actually recognizes
- `emotion` is one of `calm`, `happy`, `sad`, `angry`, `disgusted`, `fearful`, `surprised`

### Pause markers don't pause

Use exactly `<#0.8#>` with the `#` characters. `<0.8>` and `[pause 0.8]` will be read literally. Range: 0.01 to 99.99 seconds.

---

## Image generation (Apimart)

### `Task timed out after 300s`

Apimart's queue is congested. Re-run that shot:

```bash
python scripts/img_apimart.py --shot 7 --force
```

Or increase `timeout=300` in `poll_task()`.

### Image has fake / nonsense Chinese characters

Known limitation of gpt-image-2. Either:

1. Add `"no text, no characters, no calligraphy"` to your `style_anchor` or per-shot `image_prompt`.
2. Accept it and crop/cover the text region in post.

### Style consistency drift across shots

`style_anchor` is too vague. Make it specific:

- Bad: `"watercolor style"`
- Good: `"hand-painted watercolor, muted earth tones, visible paper texture, sketchy ink outlines, Hayao Miyazaki color palette"`

---

## Assembly (ffmpeg)

### Subtitle burn fails: `unknown font 'Source Han Sans SC'`

Either install [Source Han Sans](https://github.com/adobe-fonts/source-han-sans/releases) (free) or edit `assemble_video.py` and change `FontName=Source Han Sans SC` to a font you have, e.g. `FontName=Microsoft YaHei` on Windows.

### Final video is silent

Run `python scripts/measure_audio.py` first and confirm it found mp3s. If `audio/full_narration.mp3` doesn't exist, run `python scripts/merge_audio.py`. If both exist, check assembly log for `narration overlaid` vs `narration overlay failed`.

### Ken Burns motion too jittery / too still

Edit the `0.0006` zoom delta in `kenburns_vf()` in `assemble_video.py`. Higher = faster motion.

### Final video is 8GB

Default CRF is 18 (very high quality). For uploads, change `-crf 18` to `-crf 23` in the subtitle burn step and re-run from stage 7. Cuts file size ~4× with imperceptible quality loss.

---

## Resuming after a failure

```bash
python run_all.py --from 4    # resume from image generation
python run_all.py --only 7    # just re-do assembly
```

Stage numbers: 1=parse_shots, 2=tts, 3=measure, 4=images, 5=slice, 6=merge, 7=assemble.

---

## Still stuck?

Open an issue with:
- The full command you ran
- The last ~30 lines of output
- The contents of `.pipeline_state.json` (if it exists)
- Your OS and Python version
