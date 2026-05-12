# Architecture

This is a deliberately simple pipeline. No daemons, no queues, no databases. Each stage is a Python script that reads files on disk, writes files on disk, and exits.

## Design principles

1. **Files are the API between stages.** If `images/shot_017.png` exists and is non-empty, stage 4 is done for that shot. If not, it isn't. No "in-progress" states, no database to consult.
2. **Idempotent.** Re-running any stage skips work that's already done. Hashes on image prompts catch when you changed a prompt and need to re-render that one shot.
3. **No LLM at runtime.** The talk script is authored interactively (by Claude via the `book-deep-reader` skill, or by hand) in a structured format. The render pipeline is pure rule-based parsing — no Claude key needed, deterministic, no surprise costs.
4. **Image gen is the expensive stage.** It dominates cost and wall time. The pipeline is structured so you can iterate one shot at a time without paying for the rest.
5. **No video tool lock-in.** All visual output is plain PNG and MP3 until the final ffmpeg step. You can drop into any NLE (Premiere, DaVinci, CapCut) at slice-time and finish there if you want fine control.

## The seven stages

```
┌───┐ ┌───────────────┐ ┌──────────────────┐ ┌───────────────┐
│ 1 │ │ book-deep-    │ │ talk.md          │ │ parse_shots.py│
│   │▶│ reader skill  │▶│ (structured md   │▶│ (pure stdlib, │
│   │ │ (in Claude)   │ │  with frontmatter│ │  no API call) │
│   │ │ INTERACTIVE   │ │  + image prompts)│ │               │
└───┘ └───────────────┘ └──────────────────┘ └───────┬───────┘
                                                     │
                                              script.json
                                                     │
                       ┌─────────────────────────────┼──────────────────────┐
                       ▼                             ▼                      ▼
              ┌───────────────┐            ┌───────────────┐       ┌───────────────┐
              │ 2. tts        │            │ 3. measure    │       │ 4. img_apimart│
              │   MiniMax     │            │   ffprobe     │       │   gpt-image-2 │
              └───────┬───────┘            └───────┬───────┘       └───────┬───────┘
                      │                            │                       │
                  audio/*.mp3              actual_duration_seconds      images/*.png
                      │                       in script.json               │
                      ▼                                                    ▼
              ┌───────────────┐                                   ┌───────────────┐
              │ 5b. merge     │                                   │ 5. slice      │
              │     ffmpeg    │                                   │   PIL/Pillow  │
              └───────┬───────┘                                   └───────┬───────┘
                      │                                                   │
            full_narration.mp3                                       slices/*.png
                      │                                                   │
                      └──────────────────┬────────────────────────────────┘
                                         ▼
                                ┌───────────────────────┐
                                │ 6. assemble_video     │
                                │    ffmpeg + ffmpeg    │
                                │  - Ken Burns per shot │
                                │  - concat all clips   │
                                │  - mix narration      │
                                │  - mix BGM            │
                                │  - burn subtitles     │
                                └──────────┬────────────┘
                                           ▼
                                      final.mp4
```

## Why these tool choices

### Why no LLM at runtime

Shot boundaries and image prompts ARE narrative decisions — where listeners take a breath, when a metaphor lands. LLMs are good at these. Determinism is bad at them.

The trick is: we **do** use Claude for these decisions, but during **authoring**, not rendering. The `book-deep-reader` skill is invoked interactively in Claude Code; Claude writes the talk script with shot boundaries and image prompts already paired. You review and edit. The result is a fully self-describing `.md` file.

At render time, the script is "frozen" — `parse_shots.py` is a 200-line stdlib parser. No keys, no surprise bills, no provider outages. The author paid for the intelligence once, not every render.

### Why MiniMax for TTS

Three reasons:
- Voice cloning: you can train a voice on your own samples and use the resulting `ttv-voice-XXX` ID. Critical for channels that want a consistent host persona.
- Pause markers: `<#0.8#>` syntax is honored. Most other Chinese TTS doesn't expose this.
- Pricing: cheaper than OpenAI's `tts-1-hd` for Chinese.

OpenAI TTS, ElevenLabs, and 讯飞 are all reasonable fallbacks. The TTS interface is small (one function: `tts_shot(shot, voice_id, speed, emotion) -> mp3 bytes`), so adding a provider is ~40 lines.

### Why Apimart / gpt-image-2

Apimart fronts gpt-image-2 (Bytedance's image model, ranked top-3 on most Chinese leaderboards mid-2026) at a price 4x cheaper than going through OpenAI's gpt-image-1. Quality and Chinese-cultural fluency are noticeably better than Stable Diffusion / SDXL for ink-wash, 国风, calligraphy-adjacent styles.

For non-Chinese / non-traditional styles, DALL-E 3 via OpenAI or SDXL via Replicate are fine substitutes.

### Why ffmpeg over MoviePy

MoviePy is wonderful for prototyping but the dependency chain (numpy, imageio, decorator, proglog…) is fragile on Windows. `ffmpeg` is a single binary; once it's on PATH, nothing else can break it. The pipeline shells out to `ffmpeg` directly for the heavy work.

A MoviePy fallback exists in `assemble_video.py` and gets used if ffmpeg is missing.

## State management

The only state file is `.pipeline_state.json`. It tracks:

```json
{
  "tts_done": [1, 2, 3, ..., 35],
  "img_hashes": {"1": "8a2c3...", "2": "f1e5d...", ...},
  "stage_completed": 6,
  "timestamp": "2026-05-12T10:23:00"
}
```

`img_hashes` is the trick that lets you edit one shot's `image_prompt` and only re-render that one. Re-running `img_apimart.py` computes the hash of each prompt; if it doesn't match the stored hash, that shot gets regenerated.

## Stage cost / time profile (typical 35-shot project)

| Stage | Time | Cost | Bottleneck |
|---|---|---|---|
| 1. parse_shots | <1s | 0 | Local stdlib |
| 2. tts | 4-6 min | ~¥2 | Sequential MiniMax calls + 3s sleep |
| 3. measure | 5s | 0 | Local ffprobe |
| 4. images | 12-25 min | ~¥15-40 | Async polling, ~20s per image |
| 5. slice | 10-30s | 0 | Local Pillow |
| 6. merge | 5s | 0 | Local ffmpeg copy concat |
| 7. assemble | 4-8 min | 0 | ffmpeg encode + subtitle burn |
| **Total** | **~25 min** | **~¥17-42** | |

## Extension points

If you want to fork this, the natural points to add capability:

- **New TTS provider**: write `scripts/tts_xxx.py` mirroring the `tts_shot()` interface in `tts_minimaxi.py`. Update `run_all.py` step 2 to call yours.
- **New image provider**: same pattern with `img_xxx.py`. Watch for the async-task pattern in `img_apimart.py` if your provider supports webhooks instead of polling.
- **Different shot strategy**: write a new `parse_xxx.py` (or `shotify_xxx.py`). The output schema is well-defined — produce the same `script.json` shape and the rest of the pipeline doesn't care.
- **Different visual style per scene**: extend the `shot` schema with per-shot `style_override`, plumb it through to `img_apimart.py`.
- **Multi-language output**: today the pipeline assumes Chinese narration. Adding English/Japanese is mostly a TTS provider change plus updating the `image_prompt` language hint in `shotify.py`'s system prompt.

## What we deliberately do NOT do

- **No video generation models.** Sora et al. produce 5-10 second clips at very high cost. For a 25-minute video you would need 150+ of them. Cheaper and better to use stills + Ken Burns.
- **No real-time preview.** This is a batch tool. If you need to preview before rendering, just run stage 5 and look at slices/.
- **No GUI.** A Gradio interface is on the roadmap, but the CLI matters more — it composes with cron, CI, and your shell history.
