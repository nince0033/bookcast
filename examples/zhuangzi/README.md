# Example: Zhuangzi — when the world calls you useless

A real, working ~22-minute deep-read of *Zhuangzi*'s concept of **useless as protection**, addressed to people facing layoffs, age discrimination, AI displacement.

## Files

| File | Contents |
|---|---|
| `source.txt` | The raw hand-written 5,800-character talk, NOT in the bookcast structured format. Useful as reference for what the upstream source looked like. |
| `source_structured.md` | A short structured-md sample (first ~5 shots) showing the format that `parse_shots.py` expects. Use this to understand the input contract. |

The full structured-md (80+ shots covering the entire essay) is what the `book-deep-reader` skill would output if invoked on this content. Regenerate it in Claude Code by:

```
用 skills/book-deep-reader 把这段稿子转换成 bookcast 的结构化 md 格式
（粘贴 source.txt 的全部内容）
```

Save Claude's response as `talk_full.md`.

## How to regenerate the video

```bash
cd C:/path/to/bookcast
# Make sure config.env has your MINIMAX_API_KEY and APIMART_API_KEY

# Quick test on the small structured sample (4-5 shots, ~1 min video, ~¥0.5)
python run_all.py --talk examples/zhuangzi/source_structured.md

# Full 22-minute version (requires generating talk_full.md first)
python run_all.py --talk examples/zhuangzi/talk_full.md
```

Expect for the full version:
- ~5 minutes for TTS (80+ mp3s, ~22 minutes of speech)
- ~15 minutes for images (80+ ink-wash paintings via Apimart gpt-image-2)
- ~5 minutes for slicing + assembly
- ~¥17–40 in API spend

Output: `final.mp4`, roughly 22 minutes long, 16:9.

## What this example demonstrates

- **Long-form, not short-form.** A YouTube essay, not a 60-second short.
- **Single visual style across all shots.** Note how `style_anchor` in the frontmatter keeps every image looking like part of the same series.
- **Pause markers in narration.** Look for `<#0.8#>` and `<#0.6#>` — these are honored by MiniMax T2A and give the calm voice room to breathe at dramatic moments.
- **One central question.** Every shot serves the question "are you actually useless, or are you the great tree the carpenter walked past?"

## Modify it

Want a different style? Just change `style_anchor` in the frontmatter:

```yaml
style_anchor: Studio Ghibli-style soft pastel illustration, warm cozy lighting, hand-drawn
```

Want a different voice? Get a MiniMax voice clone and swap `voice_id`:

```yaml
voice_id: ttv-voice-2026042116132426-GLaeCaYk
```

Want a different aspect for shorts? Set `aspect_ratio: "9:16"` and re-run from stage 5:

```bash
python run_all.py --from 5
```

You don't need to redo TTS or image gen — source images crop to either ratio.
