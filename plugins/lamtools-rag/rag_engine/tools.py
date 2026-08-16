"""lamtools-rag 工具 handler（plugin-dev-guide §3 契约）。

- rag_index / rag_search / rag_read：P1 已实现（工作区文档，确定性路径）
- rag_search_sessions：P2（会话历史索引）
- submit_answer：答案闸门，规则层 P1 先行（校验对象 = 最近检索命中缓存；
  P4 改为会话内真实命中集 + 可选 LLM 层）
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from lamtools_core.tool import ToolResult

from . import indexer, retriever
from .citation import check_citations
from .db import connect
from .embedder import Embedder

# P1 过渡：最近检索命中缓存（submit_answer 规则层校验对象；P4 改为会话内命中集）
_HIT_CACHE: list[dict] = []
_HIT_CACHE_MAX = 200


def _ctx(call) -> tuple[Path, Path]:
    meta = call.metadata or {}
    return Path(meta.get("work_root") or "."), Path(meta.get("data_dir") or ".")


def _db_path(work_root: Path, data_dir: Path) -> Path:
    # v2：{work_root}/.lamtools/rag-index/rag.db（P2 接插件配置 indexDir）
    return work_root / ".lamtools" / "rag-index" / "rag.db"


def _plugin_config(data_dir: Path) -> dict:
    cfg = data_dir / "plugins" / "lamtools-rag.jsonc"
    try:
        from lamtools_core.plugins._jsonc import load_jsonc_text  # noqa: PLC0415

        data = load_jsonc_text(cfg)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _auto_roots(data_dir: Path) -> list[str]:
    """自动索引白名单。缺省 = ['.lam/docs']（2026-08-16 决策：
    自动检测并向量化的路径统一放工作区 .lam/docs）。"""
    cfg_roots = list(_plugin_config(data_dir).get("autoRoots") or [])
    return cfg_roots or [".lam/docs"]


def _embedding_source(data_dir: Path) -> str:
    return str(_plugin_config(data_dir).get("embeddingSource") or "local")


def _ok(call, content: str, metadata: dict | None = None) -> ToolResult:
    return ToolResult(
        call_id=call.id, name=call.name, status="ok", content=content, metadata=metadata or {}
    )


def _fail(call, error: str) -> ToolResult:
    return ToolResult(call_id=call.id, name=call.name, status="failed", error=error)


def _fmt_doc_hit(h: dict, idx: int) -> str:
    head = h.get("heading") or ""
    return (
        f"[{idx}] doc_id={h['doc_id']} 页{h.get('page') or '?'}"
        + (f" [{head}]" if head else "")
        + f" (score={h.get('score', 0):.2f})\n{h.get('snippet', '')}"
    )


def _fmt_session_hit(h: dict, idx: int) -> str:
    role = h.get("role") or "?"
    return (
        f"[{idx}] 会话消息 role={role} msg={h.get('message_id')}"
        + f" turn={h.get('turn_index')}"
        + f" (score={h.get('score', 0):.2f})\n{h.get('snippet', '')}"
    )


async def rag_index(call) -> ToolResult:
    work_root, data_dir = _ctx(call)
    args = call.arguments or {}
    paths = [str(p) for p in (args.get("paths") or [])]
    full = bool(args.get("full"))
    roots = _auto_roots(data_dir)
    if not paths and not roots:
        return _fail(
            call,
            "未指定 paths 且配置 autoRoots 为空：请提供工作区相对路径，"
            "或先在插件配置中设置 autoRoots 白名单",
        )
    embedder = Embedder(source=_embedding_source(data_dir))
    if not paths:
        # 缺省 autoRoots 目录不存在时给出明确引导（而非静默空索引）
        missing = [r for r in roots if not (work_root / r).is_dir()]
        if len(missing) == len(roots):
            return _fail(
                call,
                f"自动索引目录不存在：{missing[0]}（工作区相对路径）。"
                "请将待索引文档放入该目录，或在插件配置 autoRoots 指定其他目录",
            )
    stats = await asyncio.to_thread(
        indexer.index_documents,
        work_root,
        _db_path(work_root, data_dir),
        paths=paths,
        auto_roots=roots,
        full=full,
        embedder=embedder,
    )
    n_failed = len(stats["failed"])
    content = (
        f"索引完成：新增 {stats['added']}，更新 {stats['updated']}，跳过 {stats['skipped']}"
        + (f"，失败 {n_failed} 个（详见 metadata）" if n_failed else "")
    )
    metadata = {"stats": stats}
    if n_failed:
        metadata["failed"] = stats["failed"]
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="ok" if not n_failed else "failed",
        content=content,
        error="" if not n_failed else f"{n_failed} 个文件索引失败",
        metadata=metadata,
    )


async def rag_search(call) -> ToolResult:
    global _HIT_CACHE
    work_root, data_dir = _ctx(call)
    args = call.arguments or {}
    query = str(args.get("query") or "").strip()
    if not query:
        return _fail(call, "query 不能为空")
    top = int(args.get("top") or 10)
    scope = str(args.get("scope") or "docs")
    source = {"docs": "workspace_doc", "artifact": "artifact"}.get(scope, "workspace_doc")
    embedder = Embedder(source=_embedding_source(data_dir))
    hits = await asyncio.to_thread(
        retriever.search,
        _db_path(work_root, data_dir),
        query,
        source=source,
        top=top,
        embedder=embedder,
    )
    _HIT_CACHE = hits[-_HIT_CACHE_MAX:]  # 供 submit_answer 规则层校验
    if not hits:
        return _ok(
            call,
            "无命中。可能原因：索引未建立（请 rag_index 建立）或检索词与文档措辞差异过大。",
            {"hits": []},
        )
    lines = [_fmt_doc_hit(h, i + 1) for i, h in enumerate(hits)]
    meta_hits = [
        {k: h.get(k) for k in ("doc_id", "page", "heading", "score", "snippet")}
        for h in hits
    ]
    return _ok(call, "\n".join(lines), {"hits": meta_hits, "query": query, "scope": scope})


async def rag_read(call) -> ToolResult:
    work_root, data_dir = _ctx(call)
    args = call.arguments or {}
    doc_id = str(args.get("doc_id") or "").strip()
    page = args.get("page")
    if not doc_id:
        return _fail(call, "doc_id 不能为空（取 rag_search 命中返回的 doc_id）")
    conn = connect(_db_path(work_root, data_dir))
    try:
        if page:
            row = conn.execute(
                "SELECT context, heading, page FROM chunks WHERE doc_id=? AND page=? "
                "ORDER BY chunk_index",
                (doc_id, int(page)),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT context, heading, page FROM chunks WHERE doc_id=? "
                "ORDER BY chunk_index LIMIT 1",
                (doc_id,),
            ).fetchone()
    finally:
        conn.close()
    if row is None:
        return _fail(call, f"未找到 doc_id={doc_id} 页{page}（确认来自 rag_search 命中）")
    head = row["heading"] or ""
    content = f"# {doc_id} 页{row['page']}" + (f" [{head}]" if head else "") + f"\n\n{row['context']}"
    return _ok(call, content)


async def rag_search_sessions(call) -> ToolResult:
    # P2：core.db 只读索引（消息级/turn_index/水位） + 本工具 + operation rag.sessions.search
    return _fail(
        call,
        "会话历史索引尚未实现（P2 阶段）。当前请使用 rag_search 检索工作区文档；"
        "涉及历史会话的问题可先询问用户或引用当前会话上下文。",
    )


async def submit_answer(call) -> ToolResult:
    args = call.arguments or {}
    answer = str(args.get("answer") or "").strip()
    citations = args.get("citations") or []
    if not answer:
        return _fail(call, "answer 不能为空")
    if not citations:
        return _fail(
            call,
            "答案必须带引用：文档引用 {doc_id, page, text} 或会话引用 {message_id, text}，"
            "且必须来自本次检索命中（不得编造页码/message_id）",
        )
    results = check_citations(answer, citations, _HIT_CACHE)
    bad = [r for r in results if not r["ok"]]
    if bad:
        reasons = "；".join(r["reason"] for r in bad)
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="failed",
            content=f"引用校验未通过（{len(bad)}/{len(results)}）：{reasons}",
            error="引用校验未通过",
        )
    return _ok(
        call,
        f"引用校验通过（{len(results)} 条）。请输出最终答案，并保留引用标注（[p.N] 或 [会话, msg:id]）。",
        {"verified": len(results)},
    )


_HANDLERS = {
    "rag_index": rag_index,
    "rag_search": rag_search,
    "rag_read": rag_read,
    "rag_search_sessions": rag_search_sessions,
    "submit_answer": submit_answer,
}
