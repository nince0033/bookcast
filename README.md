# bookcast

> **A book → 30-minute narrated video, fully automated.**
> 一本书,自动生成一段 30 分钟讲书视频。

`bookcast` turns a book (or any long-form essay) into a finished narrated video — script, voice, visuals, subtitles, everything — in about half an hour of unattended wall-clock time and a few dollars of API spend.

It is the toolchain behind a Chinese YouTube channel that publishes 30-minute deep-reads of classic books. Now open-sourced.

---

## What it does

```
┌──────────┐   ┌─────────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│ Your book│──▶│Structured   │──▶│Shot list │──▶│Audio +   │──▶│ final.mp4│
│ or essay │   │talk script  │   │script    │   │images    │   │          │
│          │   │(.md)        │   │.json     │   │          │   │          │
└──────────┘   └─────────────┘   └──────────┘   └──────────┘   └──────────┘
   you write    book-deep-       parse_shots    TTS+image      assemble
   (or paste)   reader skill     (pure Python)  APIs           (ffmpeg)
```

Seven stages. Each writes its output to disk so you can re-run any stage without redoing the others.

---

## Features

- **Book → finished video.** Glue five tools into one command.
- **Voice cloning supported.** Use any MiniMax cloned voice for a consistent channel persona.
- **No-API shotification.** The talk script is already structured into shot blocks by the upstream skill; a pure-Python parser slices it. No Claude/OpenAI call needed at runtime.
- **Style anchored.** One sentence (`style_anchor`) controls the visual look of all 80+ images — water-ink, flat illustration, whatever.
- **Pause markers honored.** Insert `<#0.8#>` anywhere in narration for MiniMax to give the line breathing room.
- **Idempotent.** Re-running a stage only re-does work whose inputs changed (hashes image prompts, tracks done shots).
- **Ken Burns on stills.** A subtle pan/zoom per shot keeps the visual alive in a 20-minute video.
- **Burned subtitles.** SRT generated from measured audio durations, then burned in at assembly time.

---

## What you need

- **Python 3.10+** with `pip`
- **ffmpeg** + **ffprobe** on `PATH` — [download](https://ffmpeg.org/download.html)
- **Two API keys** (no Anthropic key needed — see "How it works" below):
  - [MiniMax T2A v2](https://platform.minimaxi.com/) — for narration (Chinese-first)
  - [Apimart](https://apimart.ai/) — for image generation (gpt-image-2)

Total budget per ~25-minute video: roughly **¥12–30** depending on shot count and image regenerations.

---

## Quickstart

```bash
git clone https://github.com/nince0033/bookcast.git
cd bookcast
pip install -r requirements.txt

# 1. Set up API keys
cp config.env.example config.env
# edit config.env, paste your MiniMax and Apimart keys

# 2. Get a structured talk.md (see "How it works" below for the format)
#    - Either write it by hand
#    - Or invoke skills/book-deep-reader inside Claude Code

# 3. Run the whole pipeline
python run_all.py --talk talk.md
```

When it finishes, your video is at `final.mp4`.

---

## How it works

### The "structured talk" format

bookcast's runtime parser is **rule-based, not LLM-based**. That means the input markdown must be in a specific format. Every shot is one paragraph of narration followed by an image-prompt line:

```markdown
---
title: 庄子：被时代判定没用的人，怎么活
aspect_ratio: "16:9"
voice_id: ttv-voice-2026042116132426-GLaeCaYk
voice_speed: 1.0
voice_emotion: calm
style_anchor: Traditional Chinese ink wash painting, monochrome with warm tones
bgm: sfx/bgm_guqin.mp3
---

我不绕弯子，直接说。<#0.8#>如果你最近正在经历下面这几件事的任何一件，这期节目可能就是为你准备的。

> 画面：A lone modern figure standing at the foot of towering office buildings, ink wash style

被裁员了，投了几十份简历没有回音。过了35岁，猎头不再找你。

> 画面：A weathered desk strewn with crumpled paper resumes, soft window light
```

Rules:
- YAML frontmatter at the top sets video-wide config
- Each natural paragraph (2–3 sentences) becomes one shot
- The `> 画面：...` line right after each paragraph is that shot's English image prompt
- Blank lines separate shots
- `<#0.8#>` markers inside narration become pauses spoken by TTS

### Why no Claude API at runtime?

Earlier versions of bookcast called Claude to shotify arbitrary input markdown. We dropped that — the upstream `book-deep-reader` skill (which you run interactively in Claude Code) outputs in the structured format directly. So the pipeline:

- During authoring: Claude (the agent) writes content interactively → you can review and edit
- During render: pure Python, no AI calls, no Claude key needed, deterministic, free

Image prompts are written by the skill author (or you), not generated at render time.

### The seven stages

| # | Script | Inputs | Outputs | Time | Cost |
|---|---|---|---|---|---|
| 1 | `parse_shots.py` | `talk.md` | `script.json` | 1s | 0 |
| 2 | `tts_minimaxi.py` | shots | `audio/*.mp3` | ~5 min | ~¥1 |
| 3 | `measure_audio.py` | mp3s | timestamps | 5s | 0 |
| 4 | `img_apimart.py` | shots | `images/*.png` | ~15 min | ~¥10–25 |
| 5 | `slice_image.py` | png | `slices/*.png` | 30s | 0 |
| 6 | `merge_audio.py` | mp3s | `full_narration.mp3` | 5s | 0 |
| 7 | `assemble_video.py` | everything | `final.mp4` | ~5 min | 0 |

---

## Step-by-step (when you want control)

```bash
# Parse - cut talk.md into script.json
python scripts/parse_shots.py talk.md \
    --aspect 16:9 \
    --style "Traditional Chinese ink wash painting" \
    --voice ttv-voice-2026042116132426-GLaeCaYk

# Narration
python scripts/tts_minimaxi.py
python scripts/measure_audio.py

# Visuals
python scripts/img_apimart.py
python scripts/slice_image.py

# Assembly
python scripts/merge_audio.py
python scripts/assemble_video.py
```

Every TTS / image script accepts `--shot <id>` to (re)run a single shot, and `--force` to redo everything. Done work is cached.

---

## The book-deep-reader skill

`skills/book-deep-reader/SKILL.md` is a Claude skill (see [Claude Skills docs](https://docs.claude.com/en/docs/agents-and-tools/skills)) that turns a book into a structured talk script in one of four host styles:

| Style | Vibe |
|---|---|
| 罗胖式 | Strong logic, knowledge nuggets, business analogies |
| 樊登式 | Warm, life-grounded, family stories |
| 刘擎式 | Philosophical depth, comfortable with complexity |
| 默认通用 | Balanced default |

Use it inside Claude Code (or any Claude-skill-aware harness):

```
[in Claude Code]
> 用 skills/book-deep-reader 把《庄子》做成罗胖式 30 分钟讲书稿,保存为 zhuangzi.md
```

The skill outputs a `.md` file in the exact structured format `parse_shots.py` expects. Feed it to `run_all.py --talk zhuangzi.md` and you're done.

---

## Configuration: `script.json` schema

Generated by `parse_shots.py`. You can hand-write it instead of using the talk-md pipeline if you prefer.

```json
{
  "title": "Zhuangzi: when the world calls you useless",
  "aspect_ratio": "16:9",
  "voice_id": "audiobook_male_1",
  "voice_speed": 1.0,
  "voice_emotion": "calm",
  "image_model": "gpt-image-2",
  "bgm": "sfx/bgm.mp3",
  "style_anchor": "Traditional Chinese ink wash painting...",
  "shots": [
    {
      "id": 1,
      "narration": "...",
      "image_prompt": "...",
      "duration_hint_seconds": 30
    }
  ]
}
```

After stage 3 runs, each shot gets `actual_duration_seconds` filled in. Stages 5/7 use that for accurate timing.

---

## Examples

- [`examples/zhuangzi/`](examples/zhuangzi/) — a ~22-minute deep-read of *Zhuangzi*'s concept of *uselessness as protection*. Includes both the raw source text and a small structured-md sample showing the parser format.

---

## Repo layout

```
bookcast/
├── README.md
├── LICENSE                    MIT
├── config.env.example         API key template (MiniMax + Apimart only)
├── requirements.txt           requests, Pillow, moviepy
├── run_all.py                 one-shot orchestrator
├── skills/
│   └── book-deep-reader/
│       └── SKILL.md           talk-script generator (4 host styles)
├── scripts/
│   ├── parse_shots.py         talk.md -> script.json (pure stdlib)
│   ├── tts_minimaxi.py        per-shot mp3 narration
│   ├── measure_audio.py       ffprobe -> actual durations
│   ├── img_apimart.py         per-shot AI image
│   ├── slice_image.py         crop to 16:9 / 9:16 / 1:1
│   ├── merge_audio.py         concat all mp3s
│   └── assemble_video.py      slices + audio + subs -> mp4
├── examples/
│   └── zhuangzi/              real-world demo
└── docs/
    ├── quickstart.md
    ├── architecture.md
    └── troubleshooting.md
```

---

## Costs (approximate)

For a 25-minute video with ~80 shots:

| Stage | Provider | Calls | Cost |
|---|---|---|---|
| Parse shots | local | 1 | 0 |
| TTS | MiniMax speech-02-hd | 80 | ~¥2 |
| Images | Apimart gpt-image-2 | 80 | ~¥15–40 |
| **Total** | | | **~¥17–42** |

Image regenerations dominate cost. Get your `style_anchor` right on shot 1 before batch-running.

---

## Roadmap

- [ ] Local image fallback (Stable Diffusion / ComfyUI) for budget mode
- [ ] OpenAI TTS fallback
- [ ] Direct upload to YouTube / Bilibili / Douyin
- [ ] Web UI (Gradio) for non-developers
- [ ] Subtitle highlight-word style for short-form cuts

---

## Contributing

PRs welcome. Especially valuable:
- More TTS / image providers
- Better Ken Burns choreography
- Non-Chinese language hosts and styles
- Skill variants (e.g. paper-deep-reader, news-deep-reader)

---

## License

MIT — see [LICENSE](LICENSE).

---

## Acknowledgments

- `book-deep-reader` style references: 樊登读书, 刘擎西方现代思想课, 罗振宇《罗辑思维》
- TTS: [MiniMax](https://platform.minimaxi.com/)
- Image gen: [Apimart](https://apimart.ai/) gpt-image-2
- Skill design: [Anthropic Claude Skills](https://docs.claude.com/en/docs/agents-and-tools/skills)
