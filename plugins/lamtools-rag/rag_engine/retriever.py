"""FTS5 + vec0 混合召回 + RRF 融合 + snippet（v2 §5/§8）。

- 词法腿：FTS5 BM25（中文 trigram，≥3 字词）
- 语义腿：vec0 向量（embedder 可用时；缺失自动降级 BM25-only）
- 融合：RRF（只依赖排名，规避分数量纲不可比）
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from .db import connect, encode_vector, l2_normalize
from .embedder import Embedder

_logger = logging.getLogger(__name__)

_RRF_K = 60
_DEFAULT_TOP = 10
_MAX_TOP = 50


def search(
    db_path: Path,
    query: str,
    *,
    source: str = "workspace_doc",
    top: int = _DEFAULT_TOP,
    role: str | None = None,
    embedder: Embedder | None = None,
) -> list[dict]:
    """混合检索。返回命中列表（含 snippet），按 RRF 分数降序。"""
    top = max(1, min(int(top), _MAX_TOP))
    embedder = embedder or Embedder(source="none")
    conn = connect(db_path)
    try:
        fts_hits = _fts(conn, query, source=source, top=top * 3, role=role)
        vec_hits: list[dict] = []
        if embedder.available():
            vec_hits = _vec(conn, query, source=source, top=top * 3, role=role, embedder=embedder)
    finally:
        conn.close()
    merged = _rrf([fts_hits, vec_hits], top=top)
    for hit in merged:
        hit["snippet"] = _snippet(hit.get("context", ""), query)
    return merged


_WORD_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_-]{2,}")

# 中文疑问/虚词停用表（启发式查询切分用；P5 评估 jieba 分词对比）。
# 注意：不/没/未 不入表——否定常构成内容词（不合格/不可抗力/未履行）
_FTS_STOP = frozenset(
    "的是多少什么怎么哪些哪家哪个要吗了在去及与和为之其对向谁几如何"
    "多久几年何时哪里双方发生要求约定规定请问一下有"
)


def _fts_query(query: str) -> str:
    """把自然语言查询转成 FTS5 OR 短语查询。

    关键：FTS5 trigram 下 MATCH 默认把整句当"短语"——查询与文档必须
    连续匹配才会命中，自然语言长句必然全 miss。因此先做启发式切分：
    去停用词 → 保留 ≥3 字的连续片段 → '"片段1" OR "片段2"'。
    限制：2 字概念词（押金/仲裁）trigram 无法匹配——这是词法腿的真实
    边界，由向量腿补齐（消融基线的一部分）。
    """
    cleaned = re.sub(r"[？?。，、：；！!（）()\s]+", " ", query)
    parts: list[str] = []
    for seg in cleaned.split(" "):
        buf = ""
        for ch in seg:
            if ch in _FTS_STOP:
                if len(buf) >= 3:
                    parts.append(buf)
                buf = ""
            else:
                buf += ch
        if len(buf) >= 3:
            parts.append(buf)
    seen: set[str] = set()
    uniq = [p for p in parts if not (p in seen or seen.add(p))]
    if not uniq:
        return f'"{query}"'  # 全被停用词吃掉：回退整句（大概率 miss，诚实返回）
    return " OR ".join(f'"{p}"' for p in uniq)


def _fts_expanded_query(query: str) -> str:
    """窗口展开版：在基础片段上补 3-6 字滑动窗口（两阶段回退用）。

    跨停用词拼接出的超长短语在文档中往往不连续（如"提前解除劳务合同"），
    子窗口（"提前解除"/"劳务合同"/"不合格"）才是可匹配单元。
    """
    base = _fts_query(query)
    m = re.findall(r'"([^"]+)"', base)
    expanded: list[str] = []
    for p in m:
        expanded.append(p)
        if len(p) > 4:
            for w in (3, 4, 5, 6):
                for i in range(0, len(p) - w + 1):
                    expanded.append(p[i : i + w])
    dedup = sorted(set(expanded), key=len, reverse=True)
    return " OR ".join(f'"{p}"' for p in dedup)


def _fts(conn, query: str, *, source: str, top: int, role: str | None) -> list[dict]:
    # 两阶段：基础短语 OR → 无命中时窗口展开重试（降噪与召回兼得）
    fts_query = _fts_query(query)
    rows = _run_fts(conn, fts_query, source=source, top=top, role=role)
    if not rows:
        expanded = _fts_expanded_query(query)
        if expanded != fts_query:
            rows = _run_fts(conn, expanded, source=source, top=top, role=role)
    hits: list[dict] = []
    for row in rows:
        hit = _load_hit(conn, row["chunk_id"], score=-float(row["score"]))
        if hit:
            hits.append(hit)
    return hits


def _run_fts(conn, fts_query: str, *, source: str, top: int, role: str | None) -> list:
    sql = (
        "SELECT chunk_id, bm25(chunks_fts) AS score FROM chunks_fts "
        "WHERE chunks_fts MATCH ? AND source = ?"
    )
    args: list = [fts_query, source]
    if role:
        sql += " AND role = ?"
        args.append(role)
    sql += " ORDER BY score LIMIT ?"
    args.append(top)
    return conn.execute(sql, args).fetchall()


def _vec(
    conn, query: str, *, source: str, top: int, role: str | None, embedder: Embedder
) -> list[dict]:
    embs = embedder.embed([query])
    if not embs:
        return []
    qvec = encode_vector(l2_normalize(embs[0]))
    sql = (
        "SELECT v.chunk_id, v.distance FROM chunks_vec v "
        "JOIN chunks c ON c.chunk_id = v.chunk_id "
        "WHERE v.embedding MATCH ? AND k = ? AND c.source = ?"
    )
    args: list = [qvec, top, source]
    if role:
        sql += " AND c.role = ?"
        args.append(role)
    hits: list[dict] = []
    for row in conn.execute(sql, args).fetchall():
        hit = _load_hit(conn, row["chunk_id"], score=-float(row["distance"]))
        if hit:
            hits.append(hit)
    return hits


def _load_hit(conn, chunk_id: int, *, score: float) -> dict | None:
    row = conn.execute(
        "SELECT chunk_id, doc_id, source, page, heading, context, role, turn_index, "
        "message_id, ts, tokens FROM chunks WHERE chunk_id=?",
        (chunk_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "chunk_id": row["chunk_id"],
        "doc_id": row["doc_id"],
        "source": row["source"],
        "page": row["page"],
        "heading": row["heading"],
        "context": row["context"],
        "role": row["role"],
        "turn_index": row["turn_index"],
        "message_id": row["message_id"],
        "ts": row["ts"],
        "tokens": row["tokens"],
        "score": score,
    }


def _rrf(lists_: list[list[dict]], top: int) -> list[dict]:
    """Reciprocal Rank Fusion：score = Σ 1/(K + rank)。"""
    scores: dict[int, float] = {}
    by_id: dict[int, dict] = {}
    for lst in lists_:
        for rank, hit in enumerate(lst):
            if not hit:
                continue
            by_id[hit["chunk_id"]] = hit
            scores[hit["chunk_id"]] = scores.get(hit["chunk_id"], 0.0) + 1.0 / (
                _RRF_K + rank
            )
    result = []
    for cid, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top]:
        hit = dict(by_id[cid])
        hit["score"] = score
        result.append(hit)
    return result


_WORD_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_-]{2,}")


def _snippet(context: str, query: str, width: int = 120) -> str:
    """围绕首个命中词裁剪片段（±width/2），命中词高亮由调用方处理。"""
    terms = [t for t in _WORD_RE.findall(query) if t]
    terms.sort(key=len, reverse=True)
    pos = -1
    for t in terms:
        idx = context.find(t)
        if idx >= 0:
            pos = idx
            break
    if pos < 0:
        return context[:width] + ("…" if len(context) > width else "")
    start = max(0, pos - width // 2)
    end = min(len(context), pos + width // 2)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(context) else ""
    return prefix + context[start:end] + suffix
