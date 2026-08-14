"""引用校验规则层（v2 §11；P4 与 submit_answer 接线，P1 先行实现）。

规则（确定性，零成本）：
1. 文档引用：doc_id + page 必须存在于本次检索命中集；原文片段与命中文本归一化后一致；
2. 会话引用：message_id 必须存在于命中集；片段同校验。
P4 将叠加可选 LLM 层（断言与引用支持关系核对）。
"""
from __future__ import annotations

import re


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def check_citations(
    answer: str, citations: list[dict], hits: list[dict]
) -> list[dict]:
    """逐条校验，返回 [{ok, reason}]。hits = 本次（或最近）检索命中集。"""
    hit_docs: dict[str, set] = {}
    hit_msgs: dict[str, str] = {}
    for h in hits or []:
        if h.get("doc_id"):
            hit_docs.setdefault(h["doc_id"], set()).add(h.get("page"))
        if h.get("message_id"):
            hit_msgs[h["message_id"]] = h.get("context", "")

    results: list[dict] = []
    for c in citations or []:
        text = _norm(c.get("text", ""))
        if c.get("doc_id"):
            pages = hit_docs.get(c["doc_id"])
            ok_page = pages is not None and (not c.get("page") or c.get("page") in pages)
            ok_text = True
            if text:
                ctxs = [
                    _norm(h.get("context", ""))
                    for h in hits
                    if h.get("doc_id") == c["doc_id"]
                ]
                ok_text = any(text in ctx for ctx in ctxs)
            ok = bool(ok_page and ok_text)
            results.append(
                {
                    "ok": ok,
                    "reason": (
                        ""
                        if ok
                        else f"文档引用校验失败: doc_id={c['doc_id']} page={c.get('page')}"
                        "（引用目标不在命中集，或原文片段与索引文本不一致）"
                    ),
                }
            )
        elif c.get("message_id"):
            ctx = hit_msgs.get(c["message_id"])
            ok = ctx is not None and (
                not text or _norm(ctx).find(text) >= 0
            )
            results.append(
                {
                    "ok": ok,
                    "reason": (
                        ""
                        if ok
                        else f"会话引用校验失败: message_id={c['message_id']}"
                        "（不在命中集，或原文片段不一致）"
                    ),
                }
            )
        else:
            results.append(
                {"ok": False, "reason": "引用缺少 doc_id/page 或 message_id"}
            )
    return results
