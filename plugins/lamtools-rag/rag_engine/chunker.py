"""heading-aware 分片（v2 §6）：文档 → 页 → 块。

规则：
- 块不跨标题（标题链锚点，合同"第X条"整条一块）；
- 默认 token 预算 400（评测集校准，P5）；
- 超预算段落按句子边界补切；
- 合同/结构化文档场景关闭 overlap（锚点天然分界）。
"""
from __future__ import annotations

import re

DEFAULT_BUDGET_TOKENS = 400
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_PAGE_RE = re.compile(r"^##\s+[Pp]age\s+(\d+)\s*$")


def estimate_tokens(text: str) -> int:
    """中文为主文本的近似：约 2 字符 / token。"""
    return max(1, len(text) // 2)


def _split_long_text(text: str, budget: int) -> list[str]:
    """超预算文本按句子边界贪心切块（不裁词）。"""
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    parts: list[str] = []
    buf = ""
    for sent in sentences:
        if buf and estimate_tokens(buf + sent) > budget:
            parts.append(buf.strip())
            buf = sent
        else:
            buf += sent
    if buf.strip():
        parts.append(buf.strip())
    return parts or ([text.strip()] if text.strip() else [])


def split_document(
    markdown: str,
    *,
    budget: int = DEFAULT_BUDGET_TOKENS,
) -> list[dict]:
    """把 normalized markdown 切成块。

    返回块列表：{page, heading, block_type, context, char_offset, tokens}
    char_offset 为块首个字符在整文中的偏移（char 维度定位）。
    """
    blocks: list[dict] = []
    pending: list[str] = []
    pending_len = 0
    heading_chain: list[str] = []
    page = 1
    offset = 0

    def flush() -> None:
        nonlocal pending, pending_len
        if not pending:
            return
        text = "\n".join(pending).strip()
        if not text:
            pending = []
            pending_len = 0
            return
        tokens = estimate_tokens(text)
        heading = " / ".join(title for _level, title in heading_chain)
        if tokens <= budget:
            blocks.append(
                {
                    "page": page,
                    "heading": heading,
                    "block_type": "heading" if text.startswith("#") else "paragraph",
                    "context": text,
                    "char_offset": offset,
                    "tokens": tokens,
                }
            )
        else:
            for part in _split_long_text(text, budget):
                blocks.append(
                    {
                        "page": page,
                        "heading": heading,
                        "block_type": "paragraph",
                        "context": part,
                        "char_offset": offset,
                        "tokens": estimate_tokens(part),
                    }
                )
        pending = []
        pending_len = 0

    for line in markdown.splitlines():
        line_len = len(line) + 1  # +换行
        page_m = _PAGE_RE.match(line)
        if page_m:
            flush()
            page = int(page_m.group(1))
            offset += line_len
            continue
        head_m = _HEADING_RE.match(line)
        if head_m:
            flush()
            level = len(head_m.group(1))
            title = head_m.group(2).strip()
            # 标题链：更高级标题重置其下层级
            heading_chain = [h for h in heading_chain if h[0] < level]
            heading_chain.append((level, title))
            pending = [line]
            pending_len = line_len
            offset += line_len
            continue
        pending.append(line)
        pending_len += line_len
        if not line.strip():
            flush()  # 空行 = 段落边界
        offset += line_len
    flush()
    return blocks
