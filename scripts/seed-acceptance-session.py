#!/usr/bin/env python3
"""铺「验收 · 交互与显示」会话的内容（10 条助手气泡，逐条点）。

背景
----
``POST /api/core/sessions/{id}/items`` 是新增的写入侧：它把助手展示内容投影成
真实 turn 用的同一套 runItem 事件（``core.items`` + ``item_order``），再经 live
通道广播，所以界面立即出现气泡，重开会话也还在。本脚本只是这个端点的调用方：
不写数据库、不触发模型、不碰 messages 表。

用法
----
    py -3.14 scripts/seed-acceptance-session.py              # 真正铺内容
    py -3.14 scripts/seed-acceptance-session.py --dry-run    # 只打印请求体，不联网
    py -3.14 scripts/seed-acceptance-session.py --self-check  # 离线自证：请求体合规

前置条件：新包已安装、应用已重启（旧后端没有这条路由，会返回 405）。

user:“内容：按 方案/验收-交互与显示.md 的 10 项，逐条发一条 kind:'text' +
role:'assistant' 的 item（每项单独一条，便于逐条点）”+(十项各一条气泡；富文本/
公式/文件引用/地址这些用 text part 装 Markdown，图表用 chart part，流程图用
mermaid part，可交互控件用 interactive-html part，写作稿用 writing part——都按
端点真实支持的形状，别自造字段。)

user:“幂等：脚本用固定 client_item_id（如 acceptance-<项序号>），重跑不会重复插
入”+(请求级 key 固定住 turn_id，条目级 key 固定住 item_id，两者都由服务端按
sha1 派生，所以重跑落到同一行，端点回执 duplicated=true。)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 会话标题：用户库里已有一个同名空会话，按标题查，查不到就新建。
SESSION_TITLE = "验收 · 交互与显示"

#: 默认后端日志（运行中实例把监听端口写在最后一条启动行里）。
# user:“就把以后的 constant 装到 c 盘” -> “sunday/ 现在就迁吧”+(Constant 常驻实例已迁移至 C:\sunday\constant)
DEFAULT_BACKEND_LOG = Path(r"C:\sunday\constant\.lam\backend.log")

#: 请求级幂等键：固定它，十次写入归到同一个 import turn。
SUITE_KEY = "acceptance-suite-v1"

#: 条目级幂等键前缀，拼上项序号（1..10）。
ITEM_KEY_PREFIX = "acceptance-"

API_PREFIX = "/api/core"

#: 端点允许的展示类 kind（与 lamtools_core.app.session_items.DISPLAY_ITEM_KINDS 一致）。
DISPLAY_ITEM_KINDS = frozenset(
    {"text", "markdown", "message", "chart", "mermaid", "interactive-html", "writing", "artifact"}
)

#: endpoints 支持的 part 类型（服务端 _render_part 的分支）。
PART_KINDS = frozenset(
    {"text", "markdown", "chart", "mermaid", "interactive-html", "interactive_html", "html", "writing", "artifact"}
)

MAX_PART_CHARS = 200_000
MAX_TOTAL_CHARS = 1_000_000

PORT_PATTERN = re.compile(r"Starting Sunday backend on 127\.0\.0\.1:(\d+)")


class SeedError(RuntimeError):
    """本脚本自己的可读错误（不打印密钥、不打印 token）。"""


# ---------------------------------------------------------------------------
# 端口发现
# ---------------------------------------------------------------------------


def discover_port(log_path: Path, *, chunk: int = 512 * 1024) -> int:
    """读日志里最后一条 ``Starting Sunday backend on 127.0.0.1:<port>``。"""
    if not log_path.exists():
        raise SeedError(
            f"找不到后端日志：{log_path}\n"
            "→ 日志路径不对时用 --log 指定，或直接用 --port 指定端口。"
        )
    size = log_path.stat().st_size
    with log_path.open("rb") as handle:
        handle.seek(max(0, size - chunk))
        tail = handle.read().decode("utf-8", "replace")
    matches = PORT_PATTERN.findall(tail)
    if not matches:
        # 尾块里没有（实例跑了很久）：整文件流式扫一遍，只留最后一次匹配，不占内存。
        last: str | None = None
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                found = PORT_PATTERN.search(line)
                if found:
                    last = found.group(1)
        if last:
            return int(last)
        raise SeedError(
            f"日志里没有监听端口记录：{log_path}\n"
            "→ 应用可能没启动过；先启动 Sunday，或用 --port 指定端口。"
        )
    return int(matches[-1])


# ---------------------------------------------------------------------------
# HTTP（只用标准库：不打印任何 token/密钥）
# ---------------------------------------------------------------------------


class ApiError(RuntimeError):
    def __init__(self, *, status: int, payload: Any, path: str) -> None:
        super().__init__(f"HTTP {status} {path}: {payload}")
        self.status = int(status)
        self.payload = payload
        self.path = path

    @property
    def detail(self) -> Any:
        if isinstance(self.payload, dict) and "detail" in self.payload:
            return self.payload["detail"]
        return self.payload


def request_json(base_url: str, method: str, path: str, payload: Any = None, *, timeout: float = 20.0) -> Any:
    url = base_url.rstrip("/") + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed: Any = json.loads(raw)
        except ValueError:
            parsed = raw[:400]
        raise ApiError(status=exc.code, payload=parsed, path=path) from exc
    except urllib.error.URLError as exc:
        raise ApiError(
            status=0,
            payload=f"连不上 {url}（{exc.reason}）",
            path=path,
        ) from exc


def explain_failure(error: ApiError) -> str:
    """把状态码翻成人话 + 下一步（这是脚本对使用者唯一有价值的错误提示）。"""
    detail = error.detail
    if isinstance(detail, dict):
        code = str(detail.get("code") or "")
        message = str(detail.get("message") or "")
    else:
        code, message = "", str(detail)

    if error.status == 405:
        return (
            "405 = 后端没有这条路由，也就是这个实例跑的还是旧后端。\n"
            "  下一步：装新包 → 完全退出 Sunday（含托盘）→ 重新启动 → 再跑本脚本。"
        )
    if error.status == 404:
        if "Session not found" in message or "Session not found" in str(error.payload):
            return "404 = 那个会话 id 不存在（可能已被删除）。下一步：去掉 --session-id，让脚本按标题重查/新建。"
        return "404 = 路径不对（前后端版本不一致）或项目不存在。下一步：确认已在应用里建好 LamTools 项目。"
    if error.status == 409:
        return (
            "409 = 会话正在跑一个回合，写入助手条目会和它的过程时间线冲突。\n"
            "  下一步：等这一轮结束（或点停止）后重跑；这只是稍后重试，不是失败。"
        )
    if error.status == 422:
        return (
            f"422 = 请求体不符合端点契约（{code or 'INVALID_ITEM'}）：{message or '见上方 detail'}\n"
            "  下一步：脚本与后端版本不匹配，先 --self-check 看本地规则，再核对后端 kind/part 支持列表。"
        )
    if error.status == 503:
        return (
            "503 = 这个后端进程没接上 item 写入通道（缺少宿主注入的持久化/广播）。\n"
            "  下一步：确认跑的是桌面端启动的后端（Sunday.exe 拉起），而不是单独跑的脚本进程。"
        )
    if error.status == 0:
        return f"连不上后端：{error.payload}\n  下一步：确认 Sunday 正在运行；端口用 --port 明确指定。"
    return f"HTTP {error.status}：{message or error.payload}"


# ---------------------------------------------------------------------------
# 会话：按标题查，查不到就建
# ---------------------------------------------------------------------------


def list_sessions(base_url: str) -> list[dict[str, Any]]:
    payload = request_json(base_url, "GET", f"{API_PREFIX}/sessions")
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("sessions"), list):
        return [item for item in payload["sessions"] if isinstance(item, dict)]
    return []


def find_session_by_title(base_url: str, title: str) -> dict[str, Any] | None:
    for session in list_sessions(base_url):
        if str(session.get("title") or "").strip() == title.strip():
            return session
    return None


def _project_root_of(project: dict[str, Any]) -> str:
    for key in ("work_root", "root", "path", "workRoot"):
        value = project.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def pick_project(base_url: str, repo_root: Path) -> dict[str, Any]:
    payload = request_json(base_url, "GET", f"{API_PREFIX}/projects")
    projects = payload.get("projects") if isinstance(payload, dict) else payload
    if not isinstance(projects, list) or not projects:
        raise SeedError(
            "应用里还没有任何项目。下一步：先在 Sunday 里新建一个项目（工作目录指向 E:\\LamTools），再跑本脚本。"
        )
    target = os.path.normcase(str(repo_root))
    for project in projects:
        if not isinstance(project, dict):
            continue
        root = _project_root_of(project)
        if root and os.path.normcase(os.path.abspath(root)) == target:
            return project
    for project in projects:
        if isinstance(project, dict) and str(project.get("name") or "").strip().lower() == repo_root.name.lower():
            return project
    names = ", ".join(str(p.get("name") or p.get("id")) for p in projects if isinstance(p, dict))
    raise SeedError(
        f"没找到工作目录为 {repo_root} 的项目（现有：{names}）。\n"
        "→ 用 --project-id 指定，或先在应用里建好这个项目。"
    )


def create_session(base_url: str, repo_root: Path, title: str, project_id: str = "") -> dict[str, Any]:
    if project_id:
        payload = request_json(
            base_url,
            "POST",
            f"{API_PREFIX}/projects/{project_id}/sessions",
            {"title": title},
        )
    else:
        project = pick_project(base_url, repo_root)
        payload = request_json(
            base_url,
            "POST",
            f"{API_PREFIX}/projects/{project['id']}/sessions",
            {"title": title},
        )
    if not isinstance(payload, dict) or not payload.get("id"):
        raise SeedError(f"建会话失败，接口回执看不懂：{payload}")
    return payload


def resolve_session(
    base_url: str,
    repo_root: Path,
    title: str,
    *,
    session_id: str = "",
    project_id: str = "",
) -> tuple[dict[str, Any], bool]:
    """返回 (会话, 是否新建)。"""
    if session_id:
        payload = request_json(base_url, "GET", f"{API_PREFIX}/sessions/{session_id}")
        if not isinstance(payload, dict) or not payload.get("id"):
            raise SeedError(f"会话 {session_id} 读不回来：{payload}")
        return payload, False
    existing = find_session_by_title(base_url, title)
    if existing is not None:
        return existing, False
    print(f"[会话] 没找到标题为「{title}」的会话，新建一个 …")
    return create_session(base_url, repo_root, title, project_id=project_id), True


# ---------------------------------------------------------------------------
# 内容：10 项，每项一条 item
# ---------------------------------------------------------------------------


def _posix(path: Path) -> str:
    """文件引用统一用正斜杠绝对路径（界面按它做文件识别，不认反斜杠）。"""
    return str(path).replace("\\", "/")


def _text_part(markdown: str) -> dict[str, Any]:
    return {"type": "text", "text": markdown}


RICH_TEXT = """## 1 富文本

### 三级标题：普通文案

一级信息用列表承载，读起来比堆句子快：

- 无序列表第一项：`并行` 与 `串行` 的区别在这里不重要
- 无序列表第二项：缩进应当对齐，而不是错位半格
  - 二级缩进
- 无序列表第三项：行距正常，没有挤在一起

有序步骤：

1. 先在设置里配好 key
2. 再新建项目
3. 最后发第一句话

任务清单：

- [x] 已完成项：应当显示勾选状态且文字带弱化
- [ ] 未完成项：应当保持空框
- [ ] 再一项未完成

表格：

| 能力 | 入口 | 预期 |
| --- | --- | --- |
| 图表 | `chart` 围栏 | 可交互的 echarts 图 |
| 流程图 | `mermaid` 围栏 | 矢量流程图 |
| 外部链接 | 普通 Markdown 链接 | 进内置浏览器 |

引用：

> 引用块应当有左侧竖线与淡背景，且和正文有明显区分。
> 第二行仍然属于同一个引用。

行内代码：`core/ui/src/preview/resolve.ts` 里的 `resolvePreviewDocument` 负责决定预览形态。

代码块（带语言高亮）：

```ts
export function previewKindFor(path: string): 'markdown' | 'text' | 'image' | 'pdf' | 'none' {
  const lower = path.toLowerCase()
  if (lower.endsWith('.md')) return 'markdown'
  if (/\\.(png|jpe?g|webp|gif|avif)$/.test(lower)) return 'image'
  if (lower.endsWith('.pdf')) return 'pdf'
  return lower.includes('.') ? 'text' : 'none'
}
```

**应该看到什么**

- 标题、列表、任务框、表格、引用、行内代码、代码块七种形态都有各自样式，没有退化成纯文本
- 代码块右上角有复制按钮，点了能复制
- 表格有横向分隔线，长内容不串列
"""

MATH_TEXT = """## 2 公式

行内公式：质能关系 $E = mc^2$，以及分式 $\\frac{a}{b}$ 和求和 $\\sum_{i=1}^{n} i^2$。

块级公式：

$$
\\int_{0}^{1} \\frac{x^{2} + 1}{\\sqrt{1 - x^{2}}}\\, dx \\;=\\; \\frac{\\pi}{2}\\left(\\frac{5}{6}\\right)
$$

矩阵与对齐：

$$
\\begin{aligned}
\\nabla \\cdot \\mathbf{E} &= \\frac{\\rho}{\\varepsilon_0} \\\\
\\nabla \\times \\mathbf{B} &= \\mu_0 \\mathbf{J} + \\mu_0 \\varepsilon_0 \\frac{\\partial \\mathbf{E}}{\\partial t}
\\end{aligned}
$$

**应该看到什么**

- 行内公式与文字在同一行，基线对齐，没有撑高行距
- 块级公式居中、独立成段
- 公式字体是数学斜体，而不是等宽代码字体
"""

MERMAID_SOURCE = """flowchart TD
    A[用户点开链接] --> B{是否 http 地址}
    B -- 是 --> C[交给内置浏览器]
    B -- 否 --> D[交给文件预览]
    C --> E[分屏 / 全屏 / 悬浮 三种形态]
    D --> F{类型可预览吗}
    F -- 可以 --> G[Markdown / 图片 / PDF 直接看]
    F -- 不可以 --> H[说明原因并给出可打开方式]
    E --> I[地址栏与页内查找可用]
    G --> I
    H --> I
"""

INTERACTIVE_SOURCE = """<div id="demo">
  <label>半径 <input id="r" type="range" min="10" max="140" value="60"> <span id="rv">60</span></label>
  <p>面积 ≈ <b id="area">11310</b> 平方像素</p>
  <div id="stage"><div id="ball"></div></div>
</div>
<style>
  #demo { font: 13px/1.6 sans-serif; color: var(--foreground, #222); }
  #stage { position: relative; height: 160px; margin-top: 8px; border: 1px dashed var(--border, #bbb); border-radius: 8px; background: var(--background, #fff); }
  #ball { position: absolute; left: 20px; top: 60px; width: 48px; height: 48px; border-radius: 50%; background: linear-gradient(135deg, #7bd3ff, #5b8cff); cursor: grab; touch-action: none; }
</style>
<script>
(function () {
  var r = document.getElementById('r'), rv = document.getElementById('rv'), area = document.getElementById('area');
  var stage = document.getElementById('stage'), ball = document.getElementById('ball');
  function paint() { rv.textContent = r.value; area.textContent = Math.round(Math.PI * r.value * r.value); }
  r.addEventListener('input', paint); paint();
  var dragging = false, dx = 0, dy = 0;
  ball.addEventListener('pointerdown', function (e) {
    dragging = true; ball.style.cursor = 'grabbing';
    var b = ball.getBoundingClientRect(); dx = e.clientX - b.left; dy = e.clientY - b.top;
    ball.setPointerCapture(e.pointerId);
  });
  ball.addEventListener('pointermove', function (e) {
    if (!dragging) return;
    var s = stage.getBoundingClientRect();
    var x = Math.max(0, Math.min(s.width - 48, e.clientX - s.left - dx));
    var y = Math.max(0, Math.min(s.height - 48, e.clientY - s.top - dy));
    ball.style.left = x + 'px'; ball.style.top = y + 'px';
  });
  ball.addEventListener('pointerup', function () { dragging = false; ball.style.cursor = 'grab'; });
})();
</script>
"""

WRITING_SOURCE = """周末把会话里的三个小毛病一起修了：

1. 图表在深色主题下终于看得清了，之前灰字几乎融进背景。
2. 长文档预览不再卡住，翻页像翻纸一样。
3. 文件引用点开就是分屏，不用再来回切窗口。

这次没有新概念，只是把已经有的东西做顺手。更新完直接打开旧会话就能感觉到差别。
"""

BAR_CHART = {
    "type": "bar",
    "title": "每周消息量（示例数据）",
    "unit": "条",
    "categories": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
    "series": [
        {"name": "人发", "data": [42, 58, 61, 47, 73, 28, 19]},
        {"name": "机回", "data": [40, 62, 59, 51, 70, 31, 22]},
    ],
    "smooth": False,
    "area": False,
}

LINE_CHART = {
    "type": "line",
    "title": "平均首字延迟（示例数据）",
    "unit": "秒",
    "categories": ["1月", "2月", "3月", "4月", "5月", "6月"],
    "series": [{"name": "首字延迟", "data": [2.4, 2.1, 1.8, 1.6, 1.3, 1.1]}],
    "smooth": True,
    "area": True,
}

PIE_CHART = {
    "type": "pie",
    "title": "会话类型占比（示例数据）",
    "unit": "%",
    "categories": ["日常对话", "写方案", "改代码", "查资料"],
    "series": [{"name": "占比", "data": [38, 27, 22, 13]}],
    "smooth": False,
    "area": False,
}


def _file_ref_markdown(repo_root: Path) -> str:
    """真实文件引用：存在的才列，缺的在文里说明，不伪造。"""
    required = [
        ("文档（Markdown）", repo_root / "方案" / "内置浏览器-01-总体方案.md"),
        ("代码（TypeScript）", repo_root / "core" / "ui" / "src" / "preview" / "resolve.ts"),
        ("图片（PNG）", repo_root / "core" / "desktop" / "src-tauri" / "tests" / "fixtures" / "ocr-known-text.png"),
        ("PDF", repo_root / "output" / "pdf" / "lamtools-technical-paper-bilingual-v0.2.6.pdf"),
    ]
    lines = ["## 7 真实文件引用", "", "下面都是仓库里真实存在的文件，点名称应当直接打开预览：", ""]
    for label, path in required:
        if path.exists():
            lines.append(f"- {label}：`{_posix(path)}`")
        else:
            lines.append(f"- {label}：缺（`{_posix(path)}` 不在仓库里，本项跳过）")
    lines += [
        "",
        "**应该看到什么**",
        "",
        "- 前四个点开后进入分屏或灯箱预览：Markdown 有排版、代码有等宽字体、图片能放大、PDF 能翻页",
        "- 文字里的路径整条被识别，不会只剩半截（例如只识别到 `E:`）",
    ]
    return "\n".join(lines)


def _unpreviewable_markdown(repo_root: Path) -> str:
    lab = repo_root / "lam_projects" / "attachment-preview-lab"
    docx = lab / "05-示例文档.docx"
    pptx = lab / "07-示例演示.pptx"
    lines = ["## 9 不可预览的类型", "", "这一类不该硬塞进预览区：", ""]
    listed = 0
    for label, path in (("Word 文档", docx), ("演示文稿", pptx)):
        if path.exists():
            lines.append(f"- {label}：`{_posix(path)}`")
            listed += 1
        else:
            lines.append(f"- {label}：缺（`{_posix(path)}` 不在仓库里，本项跳过）")
    if not listed:
        lines += ["", "> 仓库里没有 `.docx` / `.pptx` 样本，本项无真人可点；验收时用任意一个 docx 代替即可。"]
    lines += [
        "",
        "**应该看到什么**",
        "",
        "- 预览区给出明确说明（这类文件不支持直接预览），而不是空白或一直转圈",
        "- 提供「用系统默认应用打开」，点了由 Word / PowerPoint 打开",
        "- 全程不弹出命令行黑窗",
    ]
    return "\n".join(lines)


GUIDE_MARKDOWN = """## 10 操作指引与判定标准

从上往下逐项点，不用按顺序也没有副作用。

**怎么用**

1. 左侧项目下点开会话「验收 · 交互与显示」，十条气泡都在这里。
2. 每条气泡只看它自己那一项，对照下表打勾。
3. 第 5 项只在助手回复里运行（这是有意的安全边界），所以它必须在这份会话里看。

| # | 项目 | 判定标准 | 结果 |
| --- | --- | --- | --- |
| 1 | 富文本 | 七种形态样式齐全、代码块复制按钮可用 | ☐ |
| 2 | 公式 | 行内不撑行、块级居中、数学字体正确 | ☐ |
| 3 | 图表 | 三张图可交互、图例可点、跟随主题 | ☐ |
| 4 | 流程图 | 多分支形状清晰、连线文字不重叠 | ☐ |
| 5 | 交互控件 | 拖动小球、滑块联动（只在助手回复里跑） | ☐ |
| 6 | 写作稿 | 卡片可编辑可复制、不外发 | ☐ |
| 7 | 文件引用 | 四种可预览、路径整条识别 | ☐ |
| 8 | 真实地址 | 进内置浏览器、三种形态切换、查找可用 | ☐ |
| 9 | 不可预览 | 说明清楚、默认应用可打开、无黑窗 | ☐ |
| 10 | 主题 | 深色/浅色下文字与图表都看得清 | ☐ |

**这条会话怎么来的**

这十条是用 `POST /api/core/sessions/{id}/items` 直接写进会话的助手展示条目，没有跑模型、没有花 token；每条带固定 `client_item_id`，所以重跑脚本不会重复插入。
"""


def build_acceptance_items(repo_root: Path) -> list[dict[str, Any]]:
    """十项内容，按端点契约构造成 items（每项一条）。"""
    items: list[dict[str, Any]] = [
        {"kind": "text", "role": "assistant", "parts": [_text_part(RICH_TEXT)]},
        {"kind": "text", "role": "assistant", "parts": [_text_part(MATH_TEXT)]},
        {
            "kind": "text",
            "role": "assistant",
            "parts": [
                {"type": "text", "text": "## 3 图表\n\n三张图各自可交互（悬停出提示、点击图例切换系列显隐）。"},
                {"type": "chart", "source": BAR_CHART},
                {"type": "chart", "source": LINE_CHART},
                {"type": "chart", "source": PIE_CHART},
                {
                    "type": "text",
                    "text": (
                        "**应该看到什么**\n\n"
                        "- 三张图分别是柱状、折线（带渐变面积）、饼图，各自有标题\n"
                        "- 鼠标悬停出现数值提示；点击图例能隐藏或显示系列\n"
                        "- 图表配色跟随当前主题，切换深浅色后不会出现看不清的文字\n"
                        "- 图下方没有报错文字（例如「图表数据不是合法 JSON」）"
                    ),
                },
            ],
        },
        {
            "kind": "text",
            "role": "assistant",
            "parts": [
                {
                    "type": "text",
                    "text": (
                        "## 4 流程图\n\n"
                        "**应该看到什么**\n\n"
                        "- 至少 4 个节点、多个分支的流程图，箭头方向正确\n"
                        "- 菱形判定节点与矩形普通节点形状区分明显\n"
                        "- 连线上的文字（是 / 否）落在线上，不重叠\n"
                        "- 放大窗口时图形跟着等比缩放，文字不模糊"
                    ),
                },
                {"type": "mermaid", "source": MERMAID_SOURCE},
            ],
        },
        {
            "kind": "text",
            "role": "assistant",
            "parts": [
                {
                    "type": "text",
                    "text": (
                        "## 5 交互控件\n\n"
                        "这一类只有在**会话的助手回复**里才会真正运行；在文件预览里只显示源码。\n"
                        "下面这个应当在这里就动起来：\n\n"
                        "**应该看到什么**\n\n"
                        "- 拖动小球时它跟着鼠标走，不会拖出虚线框\n"
                        "- 拉动滑块时「半径」数字和面积同时变化\n"
                        "- 控件是嵌在气泡里的，不会把整页撑破或溢出"
                    ),
                },
                {"type": "interactive-html", "source": INTERACTIVE_SOURCE},
            ],
        },
        {
            "kind": "text",
            "role": "assistant",
            "parts": [
                {"type": "text", "text": "## 6 写作稿\n\n**应该看到什么**\n\n- 成稿以卡片形式出现，有标题栏\n- 卡片右上角有「编辑」和「复制」两个按钮\n- 它是本地草稿，点这些按钮不会发送任何东西"},
                {"type": "writing", "source": WRITING_SOURCE, "variant": "social_post", "title": "一发就懂的更新说明"},
            ],
        },
        {
            "kind": "text",
            "role": "assistant",
            "parts": [_text_part(_file_ref_markdown(repo_root))],
        },
        {
            "kind": "text",
            "role": "assistant",
            "parts": [
                _text_part(
                    "## 8 真实地址\n\n"
                    "- 百度：https://www.baidu.com\n"
                    "- 哔哩哔哩：https://www.bilibili.com\n\n"
                    "也可以直接点这两条：[百度](https://www.baidu.com) · [哔哩哔哩](https://www.bilibili.com)\n\n"
                    "**应该看到什么**\n\n"
                    "- 点击链接进入内置浏览器，而不是甩到外部 Chrome\n"
                    "- 内置浏览器能在分屏、全屏、悬浮三种形态之间切换，切换后页面不白屏\n"
                    "- 地址栏可以改地址并回车跳转；页内查找能定位到关键字\n"
                    "- 关掉浏览器后回到原会话，滚动位置没有丢"
                )
            ],
        },
        {
            "kind": "text",
            "role": "assistant",
            "parts": [_text_part(_unpreviewable_markdown(repo_root))],
        },
        {
            "kind": "text",
            "role": "assistant",
            "parts": [_text_part(GUIDE_MARKDOWN)],
        },
    ]
    # user:“脚本用固定 client_item_id（如 acceptance-<项序号>）”+(条目级幂等键在这里
    # 一次性钉死：重跑时服务端派生出同一个 item_id，端点返回 duplicated=true。)
    for index, item in enumerate(items, start=1):
        item["client_item_id"] = f"{ITEM_KEY_PREFIX}{index}"
    return items


def build_request_body(item: dict[str, Any]) -> dict[str, Any]:
    """一条 item → 一次 POST /sessions/{id}/items 的请求体。"""
    return {
        "client_item_id": SUITE_KEY,
        "items": [item],
    }


# ---------------------------------------------------------------------------
# 离线契约自检（不联网、不启动应用）
# ---------------------------------------------------------------------------


def _render_part_locally(part: Any) -> str:
    """本地复刻服务端 _render_part 的渲染量（只为算字符数）。"""
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        raise SeedError("parts 里的每一项必须是对象或字符串")
    kind = str(part.get("type") or part.get("kind") or "text").strip().lower()
    if kind in {"text", "markdown"}:
        return str(part.get("text", ""))
    if kind == "chart":
        source = part.get("source", part.get("text", ""))
        return source if isinstance(source, str) else json.dumps(source, ensure_ascii=False)
    if kind in {"mermaid", "interactive-html", "interactive_html", "html", "writing"}:
        return str(part.get("source", part.get("text", "")))
    raise SeedError(f"不支持的 part 类型: {kind}")


def local_contract_errors(items: list[dict[str, Any]]) -> list[str]:
    """把端点校验规则在本地跑一遍：不懂后端源码也能知道请求体哪里不对。"""
    problems: list[str] = []
    if not items:
        return ["items 不能为空"]
    if len(items) > 50:
        problems.append("items 超过 50 条")
    total = 0
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"items[{index}] 不是对象")
            continue
        if str(item.get("role") or "assistant") != "assistant":
            problems.append(f"items[{index}].role 只允许 assistant")
        kind = str(item.get("kind") or "text")
        if kind not in DISPLAY_ITEM_KINDS:
            problems.append(f"items[{index}].kind={kind} 不受端点支持")
        parts = item.get("parts")
        if not isinstance(parts, list) or not parts:
            problems.append(f"items[{index}].parts 必须是非空数组")
            continue
        rendered: list[str] = []
        for part_index, part in enumerate(parts):
            part_kind = str(part.get("type") if isinstance(part, dict) else "text")
            if isinstance(part, dict) and part_kind not in PART_KINDS:
                problems.append(f"items[{index}].parts[{part_index}].type={part_kind} 不受端点支持")
                continue
            try:
                text = _render_part_locally(part)
            except SeedError as exc:
                problems.append(f"items[{index}].parts[{part_index}]: {exc}")
                continue
            if part_kind == "chart":
                raw = part.get("source") if isinstance(part, dict) else None
                if isinstance(raw, str):
                    try:
                        json.loads(raw)
                    except ValueError:
                        problems.append(f"items[{index}].parts[{part_index}].source 不是合法 JSON")
            if len(text) > MAX_PART_CHARS:
                problems.append(f"items[{index}].parts[{part_index}] 超过 {MAX_PART_CHARS} 字符")
            rendered.append(text)
        markdown = "\n\n".join(piece for piece in rendered if piece.strip())
        total += len(markdown)
        if not markdown.strip() and not item.get("artifacts"):
            problems.append(f"items[{index}] 没有任何可展示内容")
    if total > MAX_TOTAL_CHARS:
        problems.append(f"本次写入总量 {total} 超过 {MAX_TOTAL_CHARS} 字符")
    return problems


def _server_side_check(items: list[dict[str, Any]], repo_root: Path) -> list[str]:
    """用后端自己的 normalize_session_items 校验请求体（离线自证的最硬证据）。"""
    src = repo_root / "core" / "src"
    if not src.is_dir():
        return [f"跳过服务端校验：找不到 {src}"]
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from lamtools_core.app.session_items import (  # noqa: PLC0415 - 只在自检时导入
            build_item_plan,
            normalize_session_items,
        )
    except Exception as exc:  # noqa: BLE001 - 导入失败只是自检降级
        return [f"跳过服务端校验：导入 lamtools_core 失败（{type(exc).__name__}: {exc}）"]

    problems: list[str] = []
    try:
        normalized = normalize_session_items(items)
    except Exception as exc:  # noqa: BLE001
        return [f"服务端 normalize_session_items 拒绝：{exc}"]
    if len(normalized) != len(items):
        problems.append(f"规范化后条目数不一致：{len(normalized)} != {len(items)}")

    # 幂等：同样的 key 跑两次，item_id 必须一模一样（这就是「重跑不重复插入」）。
    first = build_item_plan("thread-x", normalized, client_item_id=SUITE_KEY)
    second = build_item_plan("thread-x", normalized, client_item_id=SUITE_KEY)
    if [i["item_id"] for i in first["items"]] != [i["item_id"] for i in second["items"]]:
        problems.append("同一 client_item_id 两次规划出的 item_id 不一致（幂等失效）")
    if first["turn_id"] != second["turn_id"]:
        problems.append("同一 client_item_id 两次规划出的 turn_id 不一致（幂等失效）")
    ids = [i["item_id"] for i in first["items"]]
    if len(set(ids)) != len(ids):
        problems.append("条目级 client_item_id 有冲突：多条 item 派生出同一个 item_id")
    return problems


def run_self_check(repo_root: Path) -> int:
    items = build_acceptance_items(repo_root)
    print(f"[自检] 构造 {len(items)} 条 item（请求体形状：POST {API_PREFIX}/sessions/{{id}}/items）\n")
    width = max(len(str(i.get("client_item_id"))) for i in items)
    for item in items:
        parts = ", ".join(str(p.get("type")) for p in item["parts"])
        rendered = "\n\n".join(_render_part_locally(p) for p in item["parts"])
        print(f"  {item['client_item_id']:<{width}}  kind={item['kind']:<6} parts=[{parts}]  {len(rendered):>6} 字符")
    print()

    problems = local_contract_errors(items)
    server_problems = _server_side_check(items, repo_root)
    hard_failures = [p for p in problems]
    skipped = [p for p in server_problems if p.startswith("跳过")]
    server_failures = [p for p in server_problems if not p.startswith("跳过")]

    if hard_failures:
        print("[自检] 本地规则不通过：")
        for problem in hard_failures:
            print(f"  - {problem}")
    else:
        print("[自检] 本地规则通过：role/kind/part 类型/字符上限全部合规")
    for note in skipped:
        print(f"[自检] {note}")
    if server_failures:
        print("[自检] 服务端校验不通过：")
        for problem in server_failures:
            print(f"  - {problem}")
    elif not skipped:
        print("[自检] 服务端校验通过：normalize_session_items + build_item_plan 接受全部条目，重跑 id 稳定")

    ok = not hard_failures and not server_failures
    print(f"\n[自检] 结论：{'通过' if ok else '未通过'}")
    return 0 if ok else 1


def run_dry_run(repo_root: Path, title: str, log_path: Path, port: int | None) -> int:
    """不联网：打印将要发的请求，顺带把本地规则跑一遍。"""
    items = build_acceptance_items(repo_root)
    if port is None:
        try:
            port = discover_port(log_path)
            port_line = f"{port}（来自 {log_path}）"
        except SeedError as exc:
            port = 0
            port_line = f"未发现（{exc.args[0].splitlines()[0]}），真跑时请用 --port"
    else:
        port_line = f"{port}（--port）"

    print(f"[dry-run] 目标端口：{port_line}")
    print(f"[dry-run] 会话标题：{title}")
    print(f"[dry-run] 端点：POST http://127.0.0.1:{port or '<port>'}{API_PREFIX}/sessions/<session_id>/items\n")
    for item in items:
        body = build_request_body(item)
        print(f"--- {item['client_item_id']} ---")
        preview = json.loads(json.dumps(body, ensure_ascii=False))
        for part in preview["items"][0]["parts"]:
            for key in ("text", "source"):
                if isinstance(part.get(key), str) and len(part[key]) > 160:
                    part[key] = part[key][:160] + f"…（共 {len(part[key])} 字符）"
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        print()

    problems = local_contract_errors(items)
    if problems:
        print("[dry-run] 本地规则不通过：")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("[dry-run] 本地规则通过；没有发送任何请求。")
    return 0


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def seed(base_url: str, items: list[dict[str, Any]], session_id: str) -> int:
    path = f"{API_PREFIX}/sessions/{session_id}/items"
    created = duplicated = 0
    failures: list[tuple[str, str]] = []

    for item in items:
        body = build_request_body(item)
        label = str(item["client_item_id"])
        try:
            result = request_json(base_url, "POST", path, body)
        except ApiError as exc:
            hint = explain_failure(exc)
            failures.append((label, hint))
            print(f"  [失败] {label}: HTTP {exc.status}\n    {hint}")
            if exc.status in (404, 405, 503):
                # 这三种后面九条也一定失败：立刻停下，别刷屏。
                print("\n[中止] 这是环境/版本问题，不是单条内容问题；修好后重跑（已写入的会被幂等跳过）。")
                break
            continue
        if isinstance(result, dict) and result.get("duplicated"):
            duplicated += 1
            print(f"  [已在] {label} → item_id={result.get('items', [{}])[0].get('item_id', '?')}")
        else:
            created += 1
            print(f"  [写入] {label} → item_id={result.get('items', [{}])[0].get('item_id', '?')}")

    print()
    print(f"[汇总] 新写入 {created} 条，已存在跳过 {duplicated} 条，失败 {len(failures)} 条")
    return 0 if not failures else 1


def _force_utf8_when_piped() -> None:
    """输出被重定向/管道时统一走 UTF-8，避免控制台代码页把中文写成乱码。

    交互式控制台不动（Windows 控制台走 Unicode API，本来就是对的）。
    """
    stream = sys.stdout
    if stream is None or stream.isatty():
        return
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        return


def main(argv: list[str] | None = None) -> int:
    _force_utf8_when_piped()
    parser = argparse.ArgumentParser(
        description="把「验收 · 交互与显示」的 10 项内容写进会话（POST /sessions/{id}/items，不跑模型）。",
    )
    parser.add_argument("--port", type=int, default=None, help="后端端口（默认从 backend.log 读）")
    parser.add_argument("--log", default=str(DEFAULT_BACKEND_LOG), help="后端日志路径")
    parser.add_argument("--title", default=SESSION_TITLE, help="会话标题（默认按标题查，查不到就建）")
    parser.add_argument("--session-id", default="", help="直接指定会话 id，跳过按标题查找")
    parser.add_argument("--project-id", default="", help="新建会话时用的项目 id（默认按工作目录找 LamTools 项目）")
    parser.add_argument("--dry-run", action="store_true", help="只打印请求体，不联网")
    parser.add_argument("--self-check", action="store_true", help="离线自证：请求体是否符合端点契约")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    log_path = Path(args.log)

    if args.self_check:
        return run_self_check(repo_root)
    if args.dry_run:
        return run_dry_run(repo_root, args.title, log_path, args.port)

    port = args.port if args.port is not None else discover_port(log_path)
    base_url = f"http://127.0.0.1:{port}"
    print(f"[后端] {base_url}")

    items = build_acceptance_items(repo_root)
    problems = local_contract_errors(items)
    if problems:
        print("[中止] 脚本自己构造的请求体不合契约（先 --self-check 看详情）：")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    try:
        session, is_new = resolve_session(
            base_url,
            repo_root,
            args.title,
            session_id=args.session_id,
            project_id=args.project_id,
        )
    except SeedError as exc:
        print(f"[中止] {exc}")
        return 1
    except ApiError as exc:
        print(f"[中止] {explain_failure(exc)}")
        return 1

    print(f"[会话] {'新建' if is_new else '复用'}：{session.get('title')}  id={session.get('id')}")
    print(f"[写入] {len(items)} 条 → {API_PREFIX}/sessions/{session['id']}/items\n")
    return seed(base_url, items, str(session["id"]))


if __name__ == "__main__":
    raise SystemExit(main())
