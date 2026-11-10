---
name: video-notes
description: 当用户给出视频链接或本地视频文件并要笔记、教程、拆解、图解、学习报告时使用：yt-dlp 带 cookies 抓元数据与最佳音频并用 ffprobe 校验时长，Whisper 转写，按视频结构拆章提炼问题/陷阱/步骤/结论，每章生成 SVG 图解，界面类视频抽真实帧，最后合成可离线打开的单页 HTML 并整页截图自检、切片。
metadata:
  platforms: desktop
---

# 视频转学习报告

输入：视频链接（B 站 / YouTube）或本地视频文件。输出：一个能离线打开的单页 HTML，配音频、转写、真实截图、切片。

时间戳是这份报告的骨架：正文里的每句结论都要能点回视频那一刻。

## 0 开工前确认

- 来源与是否下载视频本体。只有界面演示类（画布 / 控制台 / 剪辑器 / 文档软件）才需要视频文件抽帧，纯讲解视频只下音频。
- 报告定位：课堂笔记（细，覆盖全流程）还是操作手册（粗，按任务拆）。这只影响拆章粒度，不改流程。
- 输出目录，默认 `<work_root>/<视频标题安全名>/`，标题里的 `/\:*?"<>|` 换成 `_`。

## 交付物结构

```
<out>/
├─ meta/          <id>.info.json、封面.jpg、meta.md
├─ audio/         <id>.mp3
├─ transcript/    *.segments.json、*.srt、*.txt
├─ frames/        <阶段名>-<秒>s.jpg
├─ report.html    最终单页（含内联 CSS、内联 SVG）
└─ shots/         page.png、page.cuts.json、page.qa.json、切片 01.png、02.png...
```

## 1 环境

必需：`ffmpeg`、`ffprobe`、`yt-dlp`，转写要 `faster-whisper`（首选，快且省内存）或 `openai-whisper`，整页截图要 `playwright`。

```bash
command -v ffmpeg ffprobe yt-dlp
python -c "import importlib.util as u; print([m for m in ['faster_whisper','whisper','playwright'] if u.find_spec(m)])"
```

缺工具就装，装完再往下走：

```bash
python -m pip install -U yt-dlp faster-whisper
python -m pip install -U playwright && python -m playwright install chromium
```

Python 3.14 这类过新的解释器常常没有 `ctranslate2` / `torch` 轮子，转写建议单独建 3.12 环境：

```bash
python -m venv .venv-whisper && .venv-whisper/Scripts/pip install faster-whisper
```

装不上 `faster-whisper` 就用 `openai-whisper` 或 whisper.cpp，转写产出的 `*.segments.json` 字段保持一致即可，后面的步骤只认这个格式。

**模型从哪来**：huggingface.co 经常连不上或很慢，用镜像 `HF_ENDPOINT=https://hf-mirror.com`；镜像上 `Systran/faster-whisper-large-v3-turbo` 会 401，换 `deepdml/faster-whisper-large-v3-turbo-ct2`。直接把模型下到本地目录再喂给 `--model` 最省事：

```bash
# 并行分片下载 → .lam/models/faster-whisper-large-v3-turbo（含 model.bin/config.json/tokenizer.json/vocabulary.json）
python scripts/... 或自己 curl -r 分片并发，实测单线程 0.5MB/s、6 路并发 4.9MB/s
python scripts/transcribe.py --audio a.mp3 --lang zh --model "E:/.../.lam/models/faster-whisper-large-v3-turbo"
```

**用 GPU 转写**：faster-whisper 走 CUDA 需要 cuDNN 9 与 cuBLAS。本机没装 CUDA 时，可以直接借 ComfyUI 自带的 torch 库：

```bash
# 在 import faster_whisper 之前把 torch/lib 加进 PATH，就能 device=cuda、compute_type=float16
export PATH="E:/AI/ComfyUI-H3/python_embeded/Lib/site-packages/torch/lib:$PATH"
```

CPU 上 42 分钟音频用 turbo 要跑一小时以上，GPU 上几分钟，能上 GPU 就上。

## 2 抓元数据（阶段门 1）

```bash
bash scripts/fetch_meta.sh "<视频URL>" "<out>/meta" "chrome"   # cookies 也可以是 cookies.txt 路径，留空则不带 cookies
python scripts/summarize_meta.py "<out>/meta" --out "<out>/meta/meta.md"
```

B 站要保住的字段：

| 字段 | info.json 位置 | 在报告里的位置 |
|---|---|---|
| 标题 | `title` | 页头大标题 |
| UP 主 | `uploader` 或 `owner.name` | 页头副标题、署名 |
| 分 P | `entries[]`（每个 P 有 `title`/`id`/`duration`/`webpage_url`） | 页头分 P 列表、章节锚点 |
| 简介 | `description` | 页头可折叠区 |
| 标签 | `tags[]` | 页头标签、拆章参考 |
| 封面 | `thumbnail`（已存为 meta/*.jpg） | 页头缩略图，相对路径引用 |
| 时长 | `duration` 秒 | 页头、时长校验基准 |

多 P 视频：URL 带 `?p=1` 只抓该 P，要全量就在 URL 里给整个视频页并让 yt-dlp 当播放列表处理。分 P 与章节的关系是「一个大章节一个 P」，不要把一个 P 的连续内容拆到两个 P 里。

**阶段门**：`title` 与 `duration` 为空就是失败。B 站会因风控返回空字段，此时换 cookies（先试浏览器名 `chrome`/`edge`，再试导出的 `cookies.txt`），仍然为空就停止并向用户要 cookies。

**B 站 412 风控**：`HTTP Error 412: Precondition Failed` 是冲着非浏览器客户端来的，带 cookie、换 UA、`--impersonate chrome` 都可能照样 412。两条路：

1. 浏览器 cookie 读不出来时（`Failed to decrypt with DPAPI`、`Could not copy Chrome cookie database`，Chrome/Edge 127 之后的 App-Bound 加密导致），用 `scripts/harvest_cookies.py` 走浏览器本身取 cookie：

```bash
python scripts/harvest_cookies.py --url "<视频URL>" --out out/meta/cookies.txt            # 匿名取 buvid
python scripts/harvest_cookies.py --url "<视频URL>" --out out/meta/cookies.txt --login 120 # 开有头浏览器人工登录，拿 SESSDATA
```

2. 还是 412，就整个绕开 yt-dlp，用 `scripts/bili_via_browser.py` 在真实 Chromium 里拿元数据并下音频，产出的 info.json 与 yt-dlp 对齐：

```bash
python scripts/bili_via_browser.py --url "<视频URL>" --out out                # 元数据 + 封面 + mp3
python scripts/bili_via_browser.py --url "<视频URL>" --out out --want video --max-height 720   # 再下视频给抽帧用
```

注意未登录时 B 站只给 480p，界面文字可能看不清，这种情况要么 `--login` 让用户登录一次，要么在报告里说明截图清晰度受限。

## 3 音频与时长校验（阶段门 2）

```bash
bash scripts/fetch_media.sh audio "<视频URL>" "<out>/audio" "chrome"
python scripts/check_duration.py "<out>/audio/<id>.mp3" "<out>/meta/<id>.info.json"
```

`check_duration.py` 用 ffprobe 读 mp3 真实时长，和 info.json 的 `duration` 比，差异超过 5% 直接报错退出（退出码 2）。

超过 5% 怎么办，按顺序试：

1. 重下音频（`--force-overwrites`，必要时换 cookies 或换线路）。
2. 重下还不行，在报告页头标一条 `异常：音频时长与元数据相差 x%，以 ffprobe 为准`，后续所有时间戳以音频为准。
3. 差异来自分 P 匹配错（多 P 视频常见），用 `--p N` 单独抓对应 P 再比。

## 4 转写（阶段门 3）

```bash
python scripts/transcribe.py --audio "<out>/audio/<id>.mp3" --lang zh --outdir "<out>/transcript"
python scripts/transcribe.py --audio "<out>/audio/<id>.mp3" --lang en --outdir "<out>/transcript"
```

模型选择是硬规则：中文视频用 `turbo`（large-v3-turbo），英文视频用 `small.en`。英文转写出来是英文，再由你逐段翻成中文写进报告，时间戳沿用原文 segment 的时间戳，不要把英文视频交给中文模型硬听。

产出 `*.segments.json`（`{start,end,text}` 列表）、`*.srt`、`*.txt`。脚本自动校验最后一个 segment 的结束时间与音频时长的差：

- 差在 5% 或 10 秒以内：通过。
- 差得更多：说明转写被截断或漏了尾部，重跑；`--check-only` 可以直接复检已有 json，不用重听。

转写完成后，从 segments 里抽出章节边界候选（话题切换、明显的「接下来」「第一点」这类转折句），这些只是线索，最终边界由你看完整文稿后定。

## 5 拆章（阶段门 4）

按视频自己的结构走，不是按固定模板切。一个话题讲完了就收一章，一堂课里通常 4 到 12 章。

每章四件套，用白话短句写，不加修饰：

- 问题：这章要解决什么，一句话。
- 陷阱：新手在这里容易做错的地方，没有就不写，不要编。
- 步骤：可照做的顺序，用编号列表，每步一个动作。
- 结论：这章最终要记住的东西，一到两句。

再给每章配：

- 起止时间戳，以及可点的回跳链接（见第 7 节的链接规则）。
- 关键引用：UP 原话里最有信息量的一两句，用引号标出并带时间戳。
- 视觉锚点：这一章画面上有什么（某个面板、某段代码、某张图表），描述要让读者一眼认出，截图就按它定位。

章节标题要能一眼看出内容，不要「第三章」「内容小结」这类空标题。

## 6 每章按内容画 SVG 图解

图解不是装饰，是这一章信息的另一种说法。先判断这章在讲什么，再选图形：

| 这章在讲 | 画什么 | 必须出现的元素 |
|---|---|---|
| 操作流程、处理路径 | 流程图：步骤框 + 箭头，必要时带判断分支 | 步骤名词、箭头、起点终点 |
| 概念、体系、分层 | 关系图 / 分层图：包含、并列、上下位 | 概念名、层级标签、连接线 |
| 随时间变化、发展史 | 时间线：轴 + 节点 | 时间标记、事件名、变化方向 |
| 方案对比、优劣 | 矩阵：两列或多列 + 逐项对比 | 对比维度、两侧结论、优劣标记 |
| 风险、误区、易错点 | 检查表 / 决策树：条件 + 分支后果 | 判断条件、后果、正确做法 |
| 数据、规模、比例 | 简图：条形 / 占比 / 折线，标注真实数值 | 数值、单位、比较基准 |
| 因果、连锁反应 | 链路图：因 → 中间 → 果 | 每个环节的原因与结果、箭头 |

硬性要求：

- 图形里的关键词、标签、数值都来自这一章的真实内容，写不出具体词说明这章还没读懂。
- 必须有关系表达：箭头、包含、连线、坐标轴至少有一种。
- 禁止装饰性图形（纯圆形、纯图标、无标签的色块）。
- 禁止把同一张 SVG 换个标题重复用；两章内容不同，图就必须不同。
- `viewBox` 固定宽度（建议 0 0 960 H），高度按内容给；文字不少于 11px；颜色不超过 4 种，用页面的 CSS 变量保持一致。
- 图上不写「图解」两个字，页面里的图注负责标明。

可复用的写法见 `references/svg-patterns.md`。

## 7 真实截图（只给界面演示类视频）

画布、控制台、剪辑器、文档、后台这类视频，每章在 SVG 之外再配一张从视频里抽的真实帧；纯口播或纯 PPT 讲述可以不配，别硬凑。

抽帧流程：

```bash
# 长视频先分片并行抽候选帧，文件名就是秒数
bash scripts/frames_candidates.sh "<video.mp4>" "<out>/frames/_cand" 20 800 8 640
# 看完候选，指定秒数精确抽一帧（-ss 定位，-q:v 1 最高质量）
bash scripts/frame_at.sh "<video.mp4>" 754 "<out>/frames/参数面板-754s.jpg" 1280
```

- 候选帧按文件名里的秒数挑，选信息量最大、界面最清晰、没有转场模糊和鼠标遮挡的一帧。
- 只下过音频就先 `bash scripts/fetch_media.sh video "<URL>" "<out>/video" "chrome" 720` 拿视频。
- 文件命名 `<阶段名>-<秒>s.jpg`，阶段名用这章的关键词，一眼能对回章节。
- 抽出来的帧必须自己打开看一遍：黑帧、白帧、贴片广告、弹幕糊屏都要换。

## 8 合成单页 HTML

以 `assets/page-template.html` 为骨架，把 `{{...}}` 占位符换成真内容。要求：

- 单文件：CSS 内联在 `<style>`，SVG 内联在 HTML 里，截图和封面走相对路径（`frames/xxx.jpg`），整个目录拷走仍能离线打开。
- 页头放标题、UP 主、时长、标签、简介（折叠）、封面缩略图、音频播放器。
- 每章排版固定为：**正文 → 图解（SVG）→ 真实截图**。图解讲关系，截图给实证，顺序不要打乱。
- 图注必须一眼区分来源：SVG 的图注前缀写 `图解`，截图的图注前缀写 `视频时间戳 12:34`。
- 回跳链接按来源二选一：
  - 在线视频：`https://www.bilibili.com/video/<BV号>?p=<P>&t=<秒>` 放在时间戳上，`target="_blank"`。
  - 本地文件：`<a href="audio/<id>.mp3#t=<秒>">`，页面里的内联脚本会把点击变成对 `<audio>` 的 seek，离线也能跳。

## 9 截图自检（阶段门 5）

```bash
python scripts/page_shot.py --html "<out>/report.html" --out-dir "<out>/shots" --name page
```

脚本用 headless Chromium 整页截图，同时做机器能查的检查：横向溢出、图片没加载、图片尺寸为 0、SVG 里文字节点少于 2 个或图形元素过少、章节块高度异常、页面里的可疑空白带（相邻内容块间距超过 600px）。报告写在 `page.qa.json`，有问题退出码非 0，`page.cuts.json` 给出章节标题的 y 坐标，留给切片用。

机器查完必须人来查：用 `read_file` 打开 `shots/page.png` 亲眼看整页，逐项确认：

1. 每章的 SVG 都完整显示，没有文字重叠、文字出框、箭头指向空白。
2. 每张截图都正常显示，没有破图、没有裁掉一半。
3. 没有大片空白、没有横向滚动条、没有元素压在一起。
4. 图解和截图的图注前缀能区分来源。

发现问题改 HTML 再跑一遍，直到一遍过。这一步不能省，也不能只看 qa.json。

## 10 切片

```bash
bash scripts/slice.sh "<out>/shots/page.png" "<out>/shots/slices" 2000 100 "<out>/shots/page.cuts.json"
```

`ffmpeg` crop 切片，相邻片保留约 100px 重叠，切点会被吸附到最接近的章节标题上方，避免把标题切成两半。切完抽查首片、末片和中间一片，确认没有断标题、没有断图。

## 交付前清单

- [ ] 元数据齐全：标题、UP、分 P、简介、标签、封面、时长，都在页面上。
- [ ] 音频时长与元数据差异 ≤ 5%，否则标了异常。
- [ ] 转写最后 segment 与音频时长接近，截断的已重跑。
- [ ] 章节按内容组织，每章有问题、陷阱（有则写）、步骤、结论、时间戳、关键引用、视觉锚点。
- [ ] 每章 SVG 来自本章真实内容，有标签和关系，没有重复套壳。
- [ ] 界面演示类视频每章配了真实截图，命名带阶段名和秒数。
- [ ] 页面能离线打开，路径全相对，SVG 全内联。
- [ ] 整页截图自检通过，并且亲眼看过了。
- [ ] 切片保留 100px 重叠，没有切断标题。

## 异常处理速查

| 现象 | 处理 |
|---|---|
| yt-dlp 报风控 / 空标题 | 换 cookies：浏览器名 → 导出 cookies.txt → 让用户重新导出 |
| 音频下载中断 | 加 `--force-overwrites` 重下，再跑 check_duration |
| 转写时长对不上 | `--check-only` 复检，确认截断就换更大模型或分段重跑 |
| 抽帧是黑帧或广告 | 换 ±2 秒重抽，或降低候选帧间隔重挑 |
| 截图里 SVG 文字挤压 | 加宽 viewBox，拆成两行标签，缩小字号上限不要低于 11px |
| 切片切断标题 | 重跑 slice.sh 并传 cuts.json，或临时调大重叠 |
