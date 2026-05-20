"""
bookcast — Streamlit 本地网页 UI。

启动:
    cd <bookcast-root>
    streamlit run web/app.py

两阶段流程：
  阶段 1：输入书名/原文/文件 + 选风格/声音/画风 → 点"生成讲稿"
  阶段 2：编辑/确认讲稿 → 点"开始生成视频"
  阶段 3：流水线跑 TTS + 图 + 拼装
"""
import os
import re
import sys
import json
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

import streamlit as st

# --- 路径 ---
ROOT       = Path(__file__).resolve().parent.parent
SCRIPTS    = ROOT / "scripts"
PROJECTS   = ROOT / "projects"
CONFIG_ENV = ROOT / "config.env"
PROJECTS.mkdir(exist_ok=True)


# --- 预设 ---
VOICE_PRESETS = {
    "自定义（手动填 voice_id）":           "",
    "MiniMax · 有声书男声（默认）":        "audiobook_male_1",
    "MiniMax · 沉稳男声 qingse":           "male-qn-qingse",
    "MiniMax · 少女音":                    "female-shaonv",
    "你的克隆音色：Gentle Senior":         "ttv-voice-2026042116132426-GLaeCaYk",
}

EMOTION_PRESETS = {
    "默认（不指定，最自然语速）": "",
    "平静 (calm) — 偏慢":         "calm",
    "高兴 (happy)":               "happy",
    "悲伤 (sad)":                 "sad",
    "愤怒 (angry)":               "angry",
    "恐惧 (fearful)":             "fearful",
    "惊讶 (surprised)":           "surprised",
    "厌恶 (disgusted)":           "disgusted",
}

HOST_STYLE_PRESETS = {
    "默认（平衡）":                "默认",
    "罗胖式（强逻辑+知识包袱）":   "罗胖式",
    "樊登式（温暖+生活化）":       "樊登式",
    "刘擎式（思想纵深）":          "刘擎式",
}

STYLE_PRESETS = {
    "自定义（自己写）": "",
    "工笔重彩（蒋采苹风）": (
        "Gongbi heavy color painting, {scene}, Jiaying style, extremely fine ink "
        "linework, delicate transparent wash, soft beige aged paper texture "
        "background, muted ivory and ink black palette, minimalist composition, "
        "strictly no text, no Chinese characters, no calligraphy, no red seals "
        "or stamps, museum quality, 4K detail --ar 16:9"
    ),
    "中国水墨": (
        "Traditional Chinese ink wash painting, monochrome with subtle warm "
        "tones, elegant brushstrokes, misty atmospheric perspective, classical "
        "literati aesthetic, aged paper texture, no text"
    ),
    "吉卜力插画": (
        "Studio Ghibli-style soft pastel illustration, warm cozy lighting, "
        "hand-drawn texture, gentle whimsical mood, Hayao Miyazaki color palette"
    ),
    "扁平编辑插画": (
        "Flat editorial illustration, muted earth-tone palette, geometric "
        "composition, minimalist forms, subtle paper grain texture, no text"
    ),
}


# --- 工具函数 ---
def check_env():
    """返回 (ok, 致命错误列表, 可选警告列表)。"""
    fatals, warns = [], []
    if not CONFIG_ENV.exists():
        fatals.append(
            f"找不到 `config.env`（应在 {CONFIG_ENV}）。"
            "请把 `config.env.example` 复制为 `config.env` 并填入你的 key。"
        )
        return False, fatals, warns
    text = CONFIG_ENV.read_text(encoding="utf-8")
    needed = ["MINIMAX_API_KEY", "APIMART_API_KEY"]
    for k in needed:
        if f"{k}=" not in text or f"{k}=PASTE" in text or f"{k}=sk-xxxxxx" in text or f"{k}=eyJxxxxxx" in text:
            fatals.append(f"`{k}` 看起来还没填")

    # Detect generate_talk backends (auto-write mode is OPTIONAL)
    has_api = bool(_parse_env_value(text, "ANTHROPIC_API_KEY"))
    has_cli = bool(shutil.which("claude"))
    if has_api:
        warns.append("✅ 自动写讲稿：Anthropic API")
    elif has_cli:
        warns.append("✅ 自动写讲稿：Claude Code CLI")
    else:
        warns.append("ℹ️ 自动写讲稿不可用（只能用手写粘贴模式）")

    if shutil.which("ffmpeg") is None:
        fatals.append("`ffmpeg` 不在 PATH 里。请从 https://ffmpeg.org/download.html 下载安装")
    return len(fatals) == 0, fatals, warns


def _parse_env_value(env_text: str, key: str) -> str:
    for line in env_text.splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def estimate_cost(n_shots: int) -> dict:
    return {
        "tts_cost":   round(n_shots * 0.03, 2),
        "image_cost": round(n_shots * 0.5, 2),
        "talk_cost":  round(min(15.0, n_shots * 0.15), 2),
        "total":      round(n_shots * (0.03 + 0.5) + min(15.0, n_shots * 0.15), 2),
    }


def list_past_projects() -> list[dict]:
    out = []
    for p in sorted(PROJECTS.iterdir(), reverse=True):
        if not p.is_dir():
            continue
        meta = {
            "name":       p.name,
            "path":       p,
            "has_video":  (p / "final.mp4").exists(),
            "has_script": (p / "script.json").exists(),
            "ctime":      datetime.fromtimestamp(p.stat().st_ctime),
        }
        if meta["has_script"]:
            try:
                s = json.loads((p / "script.json").read_text(encoding="utf-8"))
                meta["title"]    = s.get("title", p.name)
                meta["n_shots"]  = len(s.get("shots", []))
            except Exception:
                meta["title"]   = p.name
                meta["n_shots"] = "?"
        else:
            meta["title"]   = p.name
            meta["n_shots"] = "?"
        out.append(meta)
    return out


def run_subprocess_stream(cmd: list[str], log_placeholder, log_buffer: list[str]) -> int:
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    for line in iter(proc.stdout.readline, ""):
        if not line:
            break
        log_buffer.append(line.rstrip("\n"))
        log_placeholder.code("\n".join(log_buffer[-200:]), language="text")
    proc.wait()
    return proc.returncode


# --- 页面配置 ---
st.set_page_config(page_title="bookcast 讲书视频生成器", page_icon="🎬", layout="wide")

# 状态初始化
if "phase" not in st.session_state:
    st.session_state["phase"] = "input"  # input | review | running | done
if "talk_md" not in st.session_state:
    st.session_state["talk_md"] = ""
if "project_dir" not in st.session_state:
    st.session_state["project_dir"] = None
if "form_settings" not in st.session_state:
    st.session_state["form_settings"] = {}


# --- 侧栏 ---
with st.sidebar:
    st.title("📚 bookcast")
    st.caption("本地讲书视频生成器")
    st.divider()

    ok, fatals, warns = check_env()
    if ok:
        st.success("✅ 环境就绪")
    else:
        st.error("⚠️ 配置不完整")
        for r in fatals:
            st.caption(f"• {r}")
    for w in warns:
        st.caption(w)

    st.divider()
    st.subheader("历史项目")
    past = list_past_projects()
    if not past:
        st.caption("_还没有任何项目——往右边生成第一个吧_")
    else:
        for meta in past[:20]:
            with st.container(border=True):
                st.markdown(f"**{meta['title']}**")
                st.caption(f"{meta['ctime']:%Y-%m-%d %H:%M} · {meta['n_shots']} 镜")
                cols = st.columns(2)
                if meta["has_video"]:
                    with cols[0]:
                        if st.button("▶️ 查看", key=f"view_{meta['name']}"):
                            st.session_state["view_project"] = str(meta["path"])
                with cols[1]:
                    if st.button("🗑️", key=f"del_{meta['name']}", help="删除"):
                        shutil.rmtree(meta["path"], ignore_errors=True)
                        st.rerun()

    st.divider()
    if st.button("🔄 重新开始（清空当前进度）", use_container_width=True):
        for k in ("phase", "talk_md", "project_dir", "form_settings"):
            st.session_state.pop(k, None)
        st.rerun()


tab_new, tab_view = st.tabs(["🎬 新建视频", "📽️ 查看项目"])


# ===================== 标签：新建视频 =====================
with tab_new:
    if not ok:
        st.warning("先解决侧栏里的配置问题再开始生成视频。")
        st.stop()

    phase = st.session_state["phase"]

    # ----- 阶段 1: 输入 -----
    if phase == "input":
        st.header("第 1 步 · 输入 + 设置")

        # 顶层：两种模式
        mode = st.radio(
            "准备方式",
            ["✍️ 我已经手写好讲稿（粘贴/上传结构化 md，跳过 Claude）",
             "🤖 让 Claude 自动写讲稿（输入书名/原文，Claude 写一稿，再花钱跑后面）"],
            horizontal=False,
            help="选哪种取决于你有没有现成讲稿。'我已经手写好' = 你已经用 Claude Code + skills/book-deep-reader 写好了，复制粘贴过来。'让 Claude 自动写' = 这里调 Claude API/CLI 自动写，但需要 ANTHROPIC_API_KEY 或者 Claude Code CLI 非交互权限。",
        )
        is_paste_mode = mode.startswith("✍️")

        st.divider()

        col_left, col_right = st.columns([3, 2])

        with col_left:
            content = ""

            if is_paste_mode:
                st.subheader("📝 粘贴讲稿")
                st.caption(
                    "把已经写好的**结构化讲稿 md** 粘贴在这里。格式是 YAML frontmatter + 段落 + `> 画面：英文画面提示` 的成对结构。"
                    "怎么写出讲稿？打开 Claude Code，说：`用 skills/book-deep-reader 帮我把《XX》做成樊登式 25 分钟讲书稿,按 bookcast 结构化 md 格式输出`。"
                )
                paste_subsrc = st.radio(
                    "来源",
                    ["粘贴", "上传文件"],
                    horizontal=True,
                    label_visibility="collapsed",
                )
                if paste_subsrc == "粘贴":
                    content = st.text_area(
                        "讲稿 markdown",
                        height=400,
                        placeholder=(
                            "---\n"
                            "title: 我的讲书视频\n"
                            "aspect_ratio: \"16:9\"\n"
                            "voice_id: audiobook_male_1\n"
                            "voice_speed: 1.0\n"
                            "voice_emotion: calm\n"
                            "style_anchor: Traditional Chinese ink wash...\n"
                            "bgm: sfx/bgm.mp3\n"
                            "---\n\n"
                            "第一段讲稿内容...\n\n"
                            "> 画面：A lone figure standing before towering buildings\n\n"
                            "第二段讲稿内容...\n\n"
                            "> 画面：A weathered desk with scattered resumes"
                        ),
                        label_visibility="collapsed",
                    )
                else:
                    uploaded = st.file_uploader("上传 .md 或 .txt", type=["md", "txt"], label_visibility="collapsed")
                    if uploaded:
                        content = uploaded.read().decode("utf-8")
                        with st.expander(f"预览（共 {len(content)} 字）"):
                            st.text(content[:1500] + ("..." if len(content) > 1500 else ""))
            else:
                st.subheader("📖 内容来源")
                src_mode = st.radio(
                    "来源类型",
                    ["📚 书名（让 Claude 用训练知识讲）",
                     "📝 粘贴原文（按你给的文本讲）",
                     "📎 上传文件（.txt / .md）"],
                    label_visibility="collapsed",
                )

                if src_mode.startswith("📚"):
                    content = st.text_input(
                        "书名 / 主题",
                        placeholder="例如：庄子 · 内篇 / 被讨厌的勇气 / 关于 35 岁焦虑的思考",
                    )
                elif src_mode.startswith("📝"):
                    content = st.text_area(
                        "原文内容",
                        height=350,
                        placeholder="把书的某一章节、一篇散文、自己的一段笔记…粘贴在这里。",
                    )
                else:
                    uploaded = st.file_uploader("上传 .txt 或 .md", type=["txt", "md"])
                    if uploaded:
                        content = uploaded.read().decode("utf-8")
                        with st.expander(f"预览（共 {len(content)} 字）"):
                            st.text(content[:1500] + ("..." if len(content) > 1500 else ""))

        with col_right:
            st.subheader("⚙️ 设置")
            if is_paste_mode:
                st.caption("以下设置会**覆盖**你粘贴讲稿里 frontmatter 的对应值。")

            title = st.text_input("视频标题", value="")

            # 这两项只在让 Claude 写时有用
            if is_paste_mode:
                host_style    = None
                target_length = None
            else:
                host_style_label = st.selectbox(
                    "讲述风格（决定讲稿调性）",
                    list(HOST_STYLE_PRESETS.keys()),
                    index=0,
                )
                host_style = HOST_STYLE_PRESETS[host_style_label]

                target_length = st.slider(
                    "目标镜头数（决定视频长度）",
                    min_value=20, max_value=120, value=60, step=10,
                    help="60 镜约对应 25 分钟视频",
                )

            st.markdown("**🎤 配音**")
            voice_label = st.selectbox("声音", list(VOICE_PRESETS.keys()), index=4)
            if voice_label.startswith("自定义"):
                voice_id = st.text_input("Voice ID", placeholder="ttv-voice-... 或 audiobook_male_1")
            else:
                voice_id = VOICE_PRESETS[voice_label]
                st.caption(f"`{voice_id}`")
            speed         = st.slider("语速", 0.5, 1.5, 1.0, 0.05)
            emotion_label = st.selectbox("情绪", list(EMOTION_PRESETS.keys()), index=0)
            emotion       = EMOTION_PRESETS[emotion_label]

            st.markdown("**🎨 画面风格**")
            style_label = st.selectbox("风格预设", list(STYLE_PRESETS.keys()), index=1)
            if style_label.startswith("自定义"):
                style_anchor = st.text_area(
                    "Style anchor（英文）",
                    height=120,
                    placeholder="用英文描述全片视觉风格；用 {scene} 占位每个镜头的具体内容",
                )
            else:
                style_anchor = STYLE_PRESETS[style_label]
                with st.expander("Style anchor（自动填充）"):
                    st.code(style_anchor, language="text")

            aspect = st.selectbox("画幅", ["16:9", "9:16", "1:1"], index=0)
            bgm = st.text_input(
                "背景音乐文件（可选）",
                value="sfx/bgm.mp3",
                help="项目内的相对路径；如果文件不存在，视频就没有背景音乐",
            )

        # 成本预览
        st.divider()
        if is_paste_mode:
            # 从粘贴内容算出 shot 数
            body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL) if content else ""
            blocks = re.split(r"\n\s*\n", body.strip()) if body else []
            n_shots = sum(
                1 for b in blocks
                if b.strip() and not b.lstrip().startswith(">")
            )
            est = estimate_cost(n_shots) if n_shots else {"tts_cost": 0, "image_cost": 0, "total": 0}
            cols = st.columns([2, 2, 2, 3])
            cols[0].metric("检测到镜头数", n_shots if n_shots else "—")
            cols[1].metric("预估视频", f"~{n_shots * 8 / 60:.1f} 分钟" if n_shots else "—")
            cols[2].metric("预估花费", f"¥{est['tts_cost'] + est['image_cost']:.0f}" if n_shots else "—")
            cols[3].caption(f"明细：TTS ~¥{est['tts_cost']:.1f} · 配图 ~¥{est['image_cost']:.1f}（手写讲稿不调 Claude，省掉这笔钱）")
        else:
            est_cost = estimate_cost(target_length)
            cols = st.columns([2, 2, 2, 3])
            cols[0].metric("目标镜头数", target_length)
            cols[1].metric("预估视频", f"~{target_length * 8 / 60:.1f} 分钟")
            cols[2].metric("预估总成本", f"¥{est_cost['total']:.0f}")
            cols[3].caption(
                f"明细：写讲稿 ~¥{est_cost['talk_cost']:.1f}（Claude） · "
                f"TTS ~¥{est_cost['tts_cost']:.1f} · 配图 ~¥{est_cost['image_cost']:.1f}"
            )

        can_generate = bool(content.strip()) and bool(voice_id.strip()) and bool(style_anchor.strip())
        if not can_generate:
            st.info("填好内容、声音和画风之后再继续。")

        btn_label = "➡️ 进入审阅讲稿" if is_paste_mode else "📝 让 Claude 生成讲稿"

        if st.button(
            btn_label,
            type="primary",
            disabled=not can_generate,
            use_container_width=True,
        ):
            # Persist settings
            st.session_state["form_settings"] = {
                "content":      content,
                "title":        title or "讲书视频",
                "host_style":   host_style,
                "target_length": target_length,
                "voice_id":     voice_id,
                "speed":        speed,
                "emotion":      emotion,
                "style_anchor": style_anchor,
                "aspect":       aspect,
                "bgm":          bgm,
            }

            # Create project dir
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = re.sub(r"[^\w一-龥-]+", "_", title)[:40] or "untitled"
            project_dir = PROJECTS / f"{ts}_{safe_title}"
            project_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(CONFIG_ENV, project_dir / "config.env")
            st.session_state["project_dir"] = str(project_dir)

            settings = st.session_state["form_settings"]

            if is_paste_mode:
                # 手动模式: 直接把用户粘的讲稿写到 talk.md, 用右边设置覆盖 frontmatter
                clean_body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL)
                fm_lines = ["---"]
                fm_dict = {
                    "title":         settings["title"],
                    "aspect_ratio":  settings["aspect"],
                    "voice_id":      settings["voice_id"],
                    "voice_speed":   settings["speed"],
                    "voice_emotion": settings["emotion"],
                    "style_anchor":  settings["style_anchor"],
                    "bgm":           settings["bgm"],
                }
                for k, v in fm_dict.items():
                    if isinstance(v, str) and (":" in v or "{" in v or v.startswith(" ")):
                        fm_lines.append(f'{k}: "{v}"')
                    else:
                        fm_lines.append(f"{k}: {v}")
                fm_lines.append("---")
                talk_md = "\n".join(fm_lines) + "\n\n" + clean_body.lstrip()
                talk_path = project_dir / "talk.md"
                talk_path.write_text(talk_md, encoding="utf-8")
                st.session_state["talk_md"] = talk_md
                st.session_state["phase"] = "review"
                st.rerun()
            else:
                # 自动模式: 调 generate_talk.py 让 Claude 写
                src_path = project_dir / "source.txt"
                src_path.write_text(content, encoding="utf-8")

                cmd = [
                    sys.executable, str(SCRIPTS / "generate_talk.py"),
                    "--file", str(src_path),
                    "--style", settings["host_style"],
                    "--title", settings["title"],
                    "--aspect", settings["aspect"],
                    "--voice", settings["voice_id"],
                    "--speed", str(settings["speed"]),
                    "--emotion", settings["emotion"],
                    "--style-anchor", settings["style_anchor"],
                    "--bgm", settings["bgm"],
                    "--target-length", str(settings["target_length"]),
                    "--project", str(project_dir),
                ]

                with st.spinner("Claude 正在写讲稿，通常 30 秒到 2 分钟..."):
                    log_placeholder = st.empty()
                    log_buffer: list[str] = []
                    rc = run_subprocess_stream(cmd, log_placeholder, log_buffer)

                if rc != 0:
                    st.error(f"生成失败（退出码 {rc}）。查看上方日志排查。")
                    st.stop()

                talk_path = project_dir / "talk.md"
                st.session_state["talk_md"] = talk_path.read_text(encoding="utf-8")
                st.session_state["phase"] = "review"
                st.rerun()

    # ----- 阶段 2: review -----
    elif phase == "review":
        settings = st.session_state["form_settings"]
        project_dir = Path(st.session_state["project_dir"])
        was_auto = settings.get("host_style") is not None  # auto = Claude wrote it

        st.header("第 2 步 · 审阅讲稿")
        if was_auto:
            st.caption(
                "Claude 写出来的初稿在下方。**可以直接编辑**——改完点「开始生成视频」就用编辑后的版本跑后面的 TTS 和图。"
                "不满意可以「让 Claude 重写」再调一次（会重新花一次 Claude 调用的钱）。"
            )
        else:
            st.caption(
                "你粘贴的讲稿在下方（frontmatter 已用右边设置覆盖）。**可以继续编辑**——点「开始生成视频」就用这一版跑后面的 TTS 和图。"
            )

        # Stats summary
        body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", st.session_state["talk_md"], count=1, flags=re.DOTALL)
        blocks = re.split(r"\n\s*\n", body.strip())
        n_shots = sum(1 for b in blocks if b.strip() and not b.lstrip().startswith(">"))
        total_chars = sum(len(b.strip()) for b in blocks if b.strip() and not b.lstrip().startswith(">"))
        est_min = total_chars / 4.5 / 60
        est_cost = estimate_cost(n_shots)

        cols = st.columns(4)
        cols[0].metric("镜头数", n_shots)
        cols[1].metric("总字数", total_chars)
        cols[2].metric("预估视频", f"~{est_min:.1f} 分钟")
        cols[3].metric("剩余花费", f"¥{est_cost['tts_cost'] + est_cost['image_cost']:.0f}",
                       help="TTS + 配图的成本，Claude 写讲稿的钱已经花掉了")

        edited = st.text_area(
            "讲稿 markdown",
            value=st.session_state["talk_md"],
            height=500,
            label_visibility="collapsed",
        )

        cols = st.columns([1, 1, 2])
        with cols[0]:
            if st.button("← 返回修改设置", use_container_width=True):
                st.session_state["phase"] = "input"
                st.rerun()
        with cols[1]:
            rewrite_label = "🔄 让 Claude 重写" if was_auto else "🔄 重新粘贴"
            if st.button(rewrite_label, use_container_width=True):
                st.session_state["phase"] = "input"
                st.session_state["talk_md"] = ""
                st.rerun()
        with cols[2]:
            if st.button("🎬 用这版讲稿开始生成视频", type="primary", use_container_width=True):
                # Save edited talk
                (project_dir / "talk.md").write_text(edited, encoding="utf-8")
                st.session_state["talk_md"] = edited
                st.session_state["phase"] = "running"
                st.rerun()

    # ----- 阶段 3: 跑后续流水线 -----
    elif phase == "running":
        st.header("第 3 步 · 生成视频")
        st.caption("正在跑 TTS + 配图 + 拼装。中途可以喝杯水。")

        project_dir = Path(st.session_state["project_dir"])
        talk_path = project_dir / "talk.md"

        stages = [
            ("parse_shots.py",    [str(talk_path)], "解析讲稿为分镜"),
            ("tts_minimaxi.py",   [],               "TTS 旁白配音"),
            ("measure_audio.py",  [],               "测量音频时长"),
            ("img_apimart.py",    [],               "AI 出图（每个 shot 一张）"),
            ("slice_image.py",    [],               "裁切到目标画幅"),
            ("merge_audio.py",    [],               "合并旁白音轨"),
            ("assemble_video.py", [],               "拼装最终视频"),
        ]

        progress = st.progress(0, text="启动中...")
        log_placeholder = st.empty()
        log_buffer: list[str] = []

        for i, (script_name, extra, desc) in enumerate(stages):
            progress.progress(i / len(stages), text=f"[{i+1}/{len(stages)}] {desc}")
            log_buffer.append(f"\n>>> {desc}\n")
            cmd = [sys.executable, str(SCRIPTS / script_name)] + extra + ["--project", str(project_dir)]
            rc = run_subprocess_stream(cmd, log_placeholder, log_buffer)
            if rc != 0:
                st.error(f"阶段失败：{desc}（退出码 {rc}）")
                # run_all.py step numbers: 1=parse_shots, 2=tts, 3=measure,
                # 4=img, 5=slice, 6=merge, 7=assemble. Our stages list matches
                # those 1-indexed, so resume = i+1.
                st.info(
                    f"修复输入后可以从这个阶段断点续跑，命令行：\n"
                    f"`python run_all.py --from {i+1} --project {project_dir}`"
                )
                if st.button("← 返回审阅讲稿"):
                    st.session_state["phase"] = "review"
                    st.rerun()
                st.stop()

        progress.progress(1.0, text="完成！")
        st.balloons()
        st.session_state["phase"] = "done"
        st.rerun()

    # ----- 阶段 4: 完成 -----
    elif phase == "done":
        project_dir = Path(st.session_state["project_dir"])
        final_mp4 = project_dir / "final.mp4"

        st.success(f"🎉 视频生成完毕！项目：`{project_dir.name}`")
        if final_mp4.exists():
            st.metric("文件大小", f"{final_mp4.stat().st_size / 1024 / 1024:.1f} MB")
            st.video(str(final_mp4))
            with open(final_mp4, "rb") as f:
                safe_name = re.sub(r"[^\w一-龥-]+", "_", st.session_state["form_settings"].get("title", "video"))[:40]
                st.download_button(
                    "⬇️ 下载 final.mp4",
                    f,
                    file_name=f"{safe_name}.mp4",
                    mime="video/mp4",
                    use_container_width=True,
                )
        else:
            st.error("没找到 final.mp4，可能生成中断了。")

        st.divider()
        if st.button("➕ 开始下一个", type="primary", use_container_width=True):
            for k in ("phase", "talk_md", "project_dir", "form_settings"):
                st.session_state.pop(k, None)
            st.rerun()


# ===================== 标签：查看项目 =====================
with tab_view:
    if "view_project" not in st.session_state:
        st.info("从左侧栏选一个历史项目。")
    else:
        p = Path(st.session_state["view_project"])
        st.header(p.name)

        script_path = p / "script.json"
        if script_path.exists():
            script = json.loads(script_path.read_text(encoding="utf-8"))
            st.markdown(f"**{script.get('title', '(无标题)')}**")
            cols = st.columns(4)
            cols[0].metric("镜头数", len(script["shots"]))
            cols[1].metric("画幅", script.get("aspect_ratio", "?"))
            cols[2].metric("声音", script.get("voice_id", "?")[:24])
            total_dur = sum(
                s.get("actual_duration_seconds", s.get("duration_hint_seconds", 0))
                for s in script["shots"]
            )
            cols[3].metric("总时长", f"{total_dur/60:.1f} 分钟")

        final_mp4 = p / "final.mp4"
        if final_mp4.exists():
            st.video(str(final_mp4))
            with open(final_mp4, "rb") as f:
                st.download_button("⬇️ 下载 final.mp4", f, file_name=f"{p.name}.mp4", mime="video/mp4")
        else:
            st.warning("这个项目还没有 `final.mp4`。")

        if script_path.exists():
            with st.expander(f"镜头列表（共 {len(script['shots'])} 个）"):
                for shot in script["shots"]:
                    cols = st.columns([1, 3, 3])
                    img_path = p / "slices" / f"shot_{shot['id']:03d}_{script.get('aspect_ratio','16:9').replace(':','x')}.png"
                    if not img_path.exists():
                        img_path = p / "images" / f"shot_{shot['id']:03d}.png"
                    if img_path.exists():
                        cols[0].image(str(img_path))
                    dur = shot.get("actual_duration_seconds", shot.get("duration_hint_seconds", "?"))
                    cols[1].caption(f"**Shot {shot['id']}** · {dur}秒")
                    cols[1].text(shot["narration"][:200])
                    cols[2].caption("画面提示词")
                    cols[2].text(shot["image_prompt"][:200])
