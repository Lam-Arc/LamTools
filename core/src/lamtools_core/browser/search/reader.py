"""正文读取：把网页压成「标题层级 + 段落」，按需分段。

user:“读取指定页面的正文和结构化内容，支持局部读取和分段”+
(先按结构找正文容器——article/main/正文 class，用文字量与链接密度挑一个；
再按标题层级切块，按 maxChars 分段，用 offset 续读)。

user:“原始页面噪声不直接进入 Agent 上下文”+(导航、页脚、侧栏、表单、脚本先按结构剔掉，
不靠关键词；一段话只出现一次，不会因为嵌套 li>p 而重复)。
"""

from __future__ import annotations

from . import dom, text as text_tools

# 一次取回正文的容器选择器（最多 8 个：宿主对一次请求的选择器数量有上限）。
FETCH_SELECTORS = (
    "article",
    "main",
    "[role=main]",
    "#js_content",
    ".rich_media_content",
    ".markdown-body",
    "#content",
    "body",
)

# 正文容器候选（按优先级）。最后一定兜底到 body，保证「读得到东西」。
ARTICLE_SELECTORS = (
    "article",
    "main",
    "[role=main]",
    "#js_content",
    ".rich_media_content",
    ".markdown-body",
    ".article-content",
    ".post-content",
    ".entry-content",
    "#article",
    "#content",
    "body",
)

# 读正文时整体跳过的结构（导航/页脚/表单/装饰）。
NOISE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "button",
    "[role=navigation]",
    "[aria-hidden=true]",
)

HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
PARAGRAPH_TAGS = frozenset({"p", "li", "pre", "blockquote", "td", "dd", "figcaption"})

MAX_BLOCK_CHARS = 2000


def _noise(node: dom.Node) -> bool:
    current: dom.Node | None = node
    while current is not None and current.tag != "#document":
        if current.tag in {"script", "style", "noscript", "template", "nav", "header", "footer", "aside", "form", "button", "svg"}:
            return True
        if current.get("aria-hidden") == "true":
            return True
        current = current.parent
    return False


def _link_density(container: dom.Node) -> float:
    total = len(container.text)
    if total <= 0:
        return 1.0
    link_chars = sum(len(anchor.text) for anchor in container.select("a"))
    return min(1.0, link_chars / total)


def _pick_container(root: dom.Node, selector: str) -> dom.Node | None:
    candidates = root.select(selector) or ([root] if selector == "body" else [])
    best: dom.Node | None = None
    best_score = -1.0
    for node in candidates:
        length = len(node.text)
        if length < 80:
            continue
        score = length * (1.0 - _link_density(node))
        if int(node.tag == "article") or int(node.get("role") == "main") or int(node.get("id") in {"js_content", "content", "article"}):
            score *= 1.15
        if score > best_score:
            best = node
            best_score = score
    return best


def _blocks(container: dom.Node) -> list[dict]:
    found: list[dict] = []
    previous = ""
    for node in container.iter_descendants():
        if _noise(node):
            continue
        level = HEADING_LEVELS.get(node.tag)
        if level is None:
            if node.tag not in PARAGRAPH_TAGS:
                continue
            # 只取最内层段：<li><p>…</p></li> 里 p 才是那一段话。
            if node.first("p, li, blockquote"):
                continue
        value = text_tools.normalize(node.text)
        if len(value) < 2:
            continue
        value = text_tools.clip(value, MAX_BLOCK_CHARS)
        if value == previous:
            continue
        previous = value
        found.append({"level": level or 0, "text": value})
    return found


def read(nodes: list[dict], *, max_chars: int = 6000, offset: int = 0) -> dict:
    """把页面片段读成正文块（纯函数，便于用固定 HTML 做回归）。"""
    best_blocks: list[dict] = []
    best_length = 0
    used_selector = ""
    for selector in ARTICLE_SELECTORS:
        for item in nodes:
            root = dom.parse(str(item.get("html") or ""))
            container = _pick_container(root, selector) or (root if selector == "body" else None)
            if container is None:
                continue
            blocks = _blocks(container)
            length = sum(len(block["text"]) for block in blocks)
            if length > best_length:
                best_blocks = blocks
                best_length = length
                used_selector = str(item.get("selector") or selector)
        if best_length >= max_chars * 2:
            break

    offset = max(0, int(offset or 0))
    window = best_blocks[offset:]
    kept: list[dict] = []
    used = 0
    truncated = False
    for index, block in enumerate(window):
        cost = len(block["text"]) + 1
        if kept and used + cost > max_chars:
            truncated = True
            break
        if not kept and cost > max_chars * 2:
            block = {"level": block["level"], "text": text_tools.clip(block["text"], max_chars)}
            cost = len(block["text"]) + 1
            truncated = True
        kept.append(block)
        used += cost
        if used >= max_chars:
            truncated = index + 1 < len(window)
            break

    return {
        "blocks": kept,
        "container": used_selector,
        "chars": used,
        "totalBlocks": len(best_blocks),
        "offset": offset,
        "nextOffset": offset + len(kept) if truncated else 0,
        "truncated": truncated,
        "headings": [block["text"] for block in best_blocks if block["level"]][:20],
    }
