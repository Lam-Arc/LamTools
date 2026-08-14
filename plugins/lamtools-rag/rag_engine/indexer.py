"""工作区文档索引（P1 确定性路径；P3 接入 format router/VLM）。

复用 core 的 document_normalize 管线（docx/pdf/xlsx → markdown + ## Page N 分页锚点）；
纯文本（md/txt）直读。增量：sha256 指纹 + mtime；中断可重跑（断点续跑）。
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

from .chunker import split_document
from .db import connect, encode_vector, l2_normalize
from .embedder import Embedder

_logger = logging.getLogger(__name__)

TEXT_SUFFIXES = {".md", ".txt", ".markdown"}
DOC_SUFFIXES = TEXT_SUFFIXES | {".pdf", ".docx", ".xlsx"}


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read_text(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _normalize(path: Path, work_root: Path) -> tuple[str, str, list[str]]:
    """返回 (markdown, document_format, warnings)。复用 core 解析管线。"""
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return _read_text(path), suffix.lstrip("."), []
    from lamtools_core.tool.document_normalize import normalize_document  # noqa: PLC0415

    result = normalize_document(path, workspace_root=work_root)
    if result is None:
        raise RuntimeError(f"无法解析文档: {path.name}")
    return result.markdown, result.document_format, list(result.warnings)


def _collect_files(
    work_root: Path, paths: list[str] | None, auto_roots: list[str]
) -> list[Path]:
    """显式 paths 优先；否则遍历 autoRoots 白名单目录。路径越界即拒绝。"""
    root = work_root.resolve()
    targets: list[Path] = []
    if paths:
        for p in paths:
            fp = (work_root / p).resolve()
            if not fp.is_relative_to(root):
                raise ValueError(f"路径越界（仅限工作区内）: {p}")
            if fp.is_dir():
                targets.extend(
                    f for f in fp.rglob("*") if f.is_file() and f.suffix.lower() in DOC_SUFFIXES
                )
            elif fp.is_file():
                targets.append(fp)
    else:
        for sub in auto_roots:
            d = (work_root / sub).resolve()
            if d.is_dir():
                targets.extend(
                    f for f in d.rglob("*") if f.is_file() and f.suffix.lower() in DOC_SUFFIXES
                )
    seen: set[str] = set()
    result: list[Path] = []
    for p in targets:
        rp = str(p.resolve())
        if rp not in seen:
            seen.add(rp)
            result.append(p)
    result.sort(key=lambda p: str(p).lower())
    return result


def _delete_doc(conn, doc_id: str) -> None:
    conn.execute(
        "DELETE FROM chunks_vec WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE doc_id=?)",
        (doc_id,),
    )
    conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM chunks_fts WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,))


def _ingest(
    conn,
    *,
    doc_id: str,
    rel: str,
    sha: str,
    mtime: float,
    doc_format: str,
    markdown: str,
    embedder: Embedder,
) -> int:
    """分块入库（先清旧版再写）。返回块数。"""
    blocks = split_document(markdown)
    texts = [b["context"] for b in blocks]
    embs: list[list[float]] | None = embedder.embed(texts) if texts else None

    conn.execute("BEGIN")
    for i, block in enumerate(blocks):
        cur = conn.execute(
            "INSERT INTO chunks(doc_id, source, chunk_index, page, char_offset, heading, "
            "block_type, context, tokens, emb_source) "
            "VALUES(?, 'workspace_doc', ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                doc_id,
                i,
                block["page"],
                block["char_offset"],
                block["heading"],
                block["block_type"],
                block["context"],
                block["tokens"],
                "local" if embs else "none",
            ),
        )
        cid = cur.lastrowid
        conn.execute(
            "INSERT INTO chunks_fts(chunk_id, doc_id, source, page, context, heading) "
            "VALUES(?, ?, 'workspace_doc', ?, ?, ?)",
            (cid, doc_id, block["page"], block["context"], block["heading"]),
        )
        if embs:
            conn.execute(
                "INSERT INTO chunks_vec(chunk_id, embedding) VALUES(?, ?)",
                (cid, encode_vector(l2_normalize(embs[i]))),
            )
    pages = {b["page"] for b in blocks}
    conn.execute(
        "INSERT INTO documents(doc_id, source, path, title, sha256, mtime, document_format, "
        "pages, status, indexed_at, version) "
        "VALUES(?, 'workspace_doc', ?, ?, ?, ?, ?, ?, 'indexed', ?, 1) "
        "ON CONFLICT(doc_id) DO UPDATE SET mtime=excluded.mtime, "
        "pages=excluded.pages, status='indexed', indexed_at=excluded.indexed_at, "
        "version=documents.version+1",
        (doc_id, rel, Path(rel).name, sha, mtime, doc_format, len(pages), time.time()),
    )
    conn.commit()
    return len(blocks)


def index_documents(
    work_root: Path,
    db_path: Path,
    *,
    paths: list[str] | None = None,
    auto_roots: list[str] | None = None,
    full: bool = False,
    embedder: Embedder | None = None,
) -> dict:
    """索引工作区文档。返回统计 {added, updated, skipped, failed:[{path,error}]}。"""
    embedder = embedder or Embedder(source="local")
    stats: dict = {"added": 0, "updated": 0, "skipped": 0, "failed": []}
    # resolve 先行：Windows 8.3 短路径（ADMINI~1）与完整路径混用时
    # relative_to 会误判越界——统一到完整路径再比较
    work_root = Path(work_root).resolve()
    files = _collect_files(work_root, paths, auto_roots or [])
    if not files:
        return stats
    conn = connect(db_path)
    try:
        for file_path in files:
            rel = str(file_path.relative_to(work_root))
            try:
                content = file_path.read_bytes()
                digest = _sha256(content)
                row = conn.execute(
                    "SELECT doc_id, sha256 FROM documents WHERE source='workspace_doc' AND path=?",
                    (rel,),
                ).fetchone()
                if row and row["sha256"] == digest and not full:
                    stats["skipped"] += 1
                    continue
                if row and row["doc_id"] != digest:
                    _delete_doc(conn, row["doc_id"])  # 内容寻址：旧版本清理
                markdown, doc_format, _warnings = _normalize(file_path, Path(work_root))
                _ingest(
                    conn,
                    doc_id=digest,
                    rel=rel,
                    sha=digest,
                    mtime=file_path.stat().st_mtime,
                    doc_format=doc_format,
                    markdown=markdown,
                    embedder=embedder,
                )
                stats["updated" if row else "added"] += 1
            except Exception as exc:  # noqa: BLE001 — 单文件失败不阻断全量
                stats["failed"].append({"path": rel, "error": f"{type(exc).__name__}: {exc}"})
                _logger.warning("[rag] index failed %s: %s", rel, exc)
    finally:
        conn.close()
    return stats
