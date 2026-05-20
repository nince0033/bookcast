# bookcast 本地网页 UI

CLI 流水线的图形外壳。比敲命令舒服，引擎是同一套。

## 启动

在仓库根目录跑：

```bash
cd /path/to/bookcast
streamlit run web/app.py
```

浏览器会自动打开 `http://localhost:8501`。

首次使用前请先：

```bash
pip install -r requirements.txt
cp config.env.example config.env
# 编辑 config.env，填入你的 MiniMax + Apimart key
```

## 界面构成

- **左侧栏**：环境状态检查 + 历史项目列表（点击可回看）
- **🎬 新建视频**：粘贴结构化讲稿 markdown → 选声音 / 画风 / 画幅 → 点开始生成。日志实时滚动，完成后视频内嵌播放。
- **📽️ 查看项目**：回看任何历史生成，浏览镜头列表，下载 mp4。

## 输出位置

每次"开始生成"会创建一个 `projects/<时间戳>_<标题>/` 目录，里面是完整的流水线产物（script.json、audio/、images/、slices/、final.mp4）。整个 `projects/` 目录已加入 `.gitignore`，不会被提交。

要清理老项目，点侧栏里的 🗑️ 删除按钮。

## 本地 UI 的边界

这是单用户本地应用——没有登录，没有远程访问，没有多用户队列。
- 想给朋友用：在能联网的机器上跑，让他们访问 `http://<你的IP>:8501`
- 想公网发布：要加用户认证、计费、任务队列、滥用防护——见项目 roadmap，不是几天能搞定的

## 不替代 CLI

网页 UI 做的事情，本质上都是在调 `scripts/` 下的脚本。CLI 流程仍然完整可用，`run_all.py` 就是。如果某个操作 UI 暂时没暴露（比如单独重生成某一张图），随时可以打开终端：

```bash
python scripts/img_apimart.py --shot 7 --force --project projects/20260512_my_essay
```
