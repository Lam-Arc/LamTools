"""会话历史索引（P2）：core.db 只读 → 消息级分块 → rag.db 增量入库。

数据流（设计文档 §8.2）：
- 触发：Stop hook（hooks/on_stop.py 读 stdin payload）→ index_session()
- 增量：documents.doc_id = "session:{thread_id}"，mtime 字段存已索引水位
  （core_history_entries.seq 最大值）——重跑只补新消息，幂等。
- 分块：每条消息一个 chunk（role/turn_index/message_id/ts/tool_names），
  turn_index = 该用户消息在会话内的序号（用户消息 + 其后的助手消息同 turn）。
- message_id = "{thread_id}:{seq}"（core_history_entries.seq），UI 跳转锚点
  与提交答案的会话引用都用它。

core.db 定位（与 cli._resolve_core_db 同序）：
  1. LAMTOOLS_CORE_DB 环境变量（Tauri/后端设置时 hook 子进程继承同一份）
  2. 默认 {repo_root}/data/core.db（cli._repo_root 语义）
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path

from .db import connect, encode_vector, l2_normalize
from .embedder import Embedder
from .schema import init_db

_logger = logging.getLogger(__name__)

SOURCE = "session_history"


def core_db_path() -> Path:
    env = os.environ.get("LAMTOOLS_CORE_DB")
    if env:
        return Path(env)
    # 与 cli._resolve_core_db 同序（Tauri dev 后端无 env、无 --core-db 时
    # 默认 {repo}/data/core.db，cwd=core/ 语义一致）：插件布局
    # {repo}/plugins/lamtools-rag/rag_engine/ → parents[3] = {repo}
    repo = Path(__file__).resolve().parents[3]
    return repo / "data" / "core.db"


def _message_text(message: dict) -> str:
    """从 ChatMessage dict 提取可索引文本（str 或 parts 列表）。"""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            kind = part.get("type") or part.get("kind") or ""
            text = part.get("model_text") or part.get("text") or ""
            if kind in ("text", "model_text", "thinking") and text:
                texts.append(str(text))
        return "\n".join(texts)
    return ""


def _load_history(core_db: Path, thread_id: str, after_seq: int) -> list[dict]:
    """从 core_history_entries 读增量消息（seq 升序），空表回退历史 blob。"""
    try:
        conn = sqlite3.connect(f"file:{core_db}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return []
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT seq, message_json, created_at FROM core_history_entries "
            "WHERE thread_id = ? AND seq > ? ORDER BY seq ASC",
            (thread_id, after_seq),
        ).fetchall()
        messages: list[dict] = []
        for row in rows:
            try:
                message = json.loads(row["message_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(message, dict):
                continue
            message.setdefault("_seq", int(row["seq"]))
            message.setdefault("_created_at", row["created_at"])
            messages.append(message)
        return messages
    finally:
        conn.close()


def _chunk_message(
    message: dict,
    *,
    thread_id: str,
    seq: int,
    turn_index: int,
    created_at: str | None,
) -> dict:
    text = _message_text(message)
    role = str(message.get("role") or "unknown")
    tool_names: list[str] = []
    content = message.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "tool_use" and part.get("name"):
                tool_names.append(str(part["name"]))
    # 顶层 tool_calls 形态（OpenAI 格式消息）同样识别
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") or {}
        name = str(fn.get("name") or "").strip()
        if name:
            tool_names.append(name)
    ts = None
    if created_at:
        try:
            ts = time.mktime(time.strptime(str(created_at)[:19], "%Y-%m-%d %H:%M:%S"))
        except (ValueError, TypeError):
            ts = None
    return {
        "message_id": f"{thread_id}:{seq}",
        "role": role,
        "turn_index": turn_index,
        "ts": ts,
        "tool_names": ",".join(sorted(set(tool_names))) or None,
        "text": text.strip(),
    }


def index_session(
    *,
    thread_id: str,
    work_root: Path | str,
    session_title: str = "",
    core_db: Path | None = None,
    embedder: Embedder | None = None,
) -> dict:
    """增量索引一个会话的全部消息到 rag.db（幂等，水位推进）。

    返回 {"indexed": n, "chunks": n, "watermark": seq}；core.db 不存在或
    无新消息时返回零值——索引失败绝不抛出（Stop hook 不得影响会话）。
    embedder：传入共享实例复用（脚本全量循环）；缺省共享 local
    （会话块也走向量——2 字词/语义查询依赖它）。
    """
    work_root = Path(work_root)
    db_path = work_root / ".lamtools" / "rag-index" / "rag.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    core_db_path_resolved = core_db or core_db_path()
    doc_id = f"session:{thread_id}"

    conn = connect(db_path)
    try:
        init_db(conn)
        row = conn.execute(
            "SELECT mtime FROM documents WHERE doc_id = ? AND source = ?",
            (doc_id, SOURCE),
        ).fetchone()
        watermark = int(row[0]) if row else 0

        messages = _load_history(core_db_path_resolved, thread_id, watermark)
        if not messages:
            return {"indexed": 0, "chunks": 0, "watermark": watermark}

        embedder = embedder or _shared_instance(
            os.environ.get("LAMTOOLS_RAG_EMBEDDING") or "local"
        )
        conn.execute("BEGIN")
        # 标题保留策略：显式 session_title 优先；无则保留旧标题；
        # 都没有才用默认占位（增量索引不覆盖真实标题）
        old_row = conn.execute(
            "SELECT title FROM documents WHERE doc_id = ? AND source = ?",
            (doc_id, SOURCE),
        ).fetchone()
        old_title = str(old_row[0]) if old_row else ""
        title = session_title or old_title or f"会话 {thread_id[:8]}"
        # 会话级 doc 行：mtime 存水位 seq（后续按需可加 title 字段）
        conn.execute(
            "INSERT INTO documents(doc_id, source, path, title, sha256, mtime, "
            "document_format, pages, status, indexed_at, version) "
            "VALUES(?, ?, ?, ?, ?, ?, 'session_history', ?, 'indexed', ?, 1) "
            "ON CONFLICT(doc_id) DO UPDATE SET title=excluded.title, "
            "mtime=excluded.mtime, status='indexed', indexed_at=excluded.indexed_at, "
            "version=documents.version+1",
            (doc_id, SOURCE, thread_id, title, "",
             messages[-1].get("_seq", watermark), len(messages), time.time()),
        )
        chunks = 0
        turn_index = 0
        last_seq = watermark
        turn_tools: list[str] = []
        for message in messages:
            seq = int(message.get("_seq", last_seq))
            last_seq = seq
            role = str(message.get("role") or "")
            if role == "user":
                turn_index += 1
                turn_tools = []  # 新轮：清空工具名收集
            elif role == "tool":
                # §8.1：tool 角色消息不入库（工具结果可能巨大且非语义代表）
                continue
            block = _chunk_message(
                message,
                thread_id=thread_id,
                seq=seq,
                turn_index=turn_index,
                created_at=message.get("_created_at"),
            )
            if role == "assistant" and block["tool_names"]:
                # §8.1：带 tool_use 的中间消息不索引正文，工具名收集到同轮元数据
                turn_tools = list(
                    dict.fromkeys([*turn_tools, *block["tool_names"].split(",")])
                )
                continue
            if not block["text"]:
                continue
            texts = [block["text"]]
            embs: list[list[float]] | None = None
            if embedder.available():
                embs = embedder.embed(texts)
            cur = conn.execute(
                "INSERT INTO chunks(doc_id, source, chunk_index, turn_index, message_id, "
                "role, context, tool_names, ts, tokens, emb_source) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    doc_id, SOURCE, chunks, block["turn_index"], block["message_id"],
                    block["role"], block["text"],
                    ",".join(turn_tools) or None,
                    block["ts"],
                    _estimate_tokens(block["text"]),
                    "local" if embs else "none",
                ),
            )
            cid = cur.lastrowid
            conn.execute(
                "INSERT INTO chunks_fts(chunk_id, doc_id, source, page, role, context, heading) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (cid, doc_id, SOURCE, None, block["role"], block["text"], ""),
            )
            if embs:
                conn.execute(
                    "INSERT INTO chunks_vec(chunk_id, embedding) VALUES(?, ?)",
                    (cid, encode_vector(l2_normalize(embs[0]))),
                )
            chunks += 1
        conn.commit()
        return {"indexed": len(messages), "chunks": chunks, "watermark": last_seq}
    except sqlite3.Error:
        _logger.warning("[rag:session] index failed for %s", thread_id, exc_info=True)
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        return {"indexed": 0, "chunks": 0, "watermark": watermark}
    finally:
        conn.close()


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, round(len(text) / 2.5))
