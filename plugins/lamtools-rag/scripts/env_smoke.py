"""P0 环境实测（量化门槛，docs/rag-plugin-plan.md §2-A）。

验证项：
1. sqlite-vec @ Python 3.14 可加载 + vec0 CRUD/相似度排序
2. FTS5 trigram 中文检索（≥3 字词命中率 100%，负样本不命中）
3. P1 引擎链路 E2E：分片 → 索引入库 → 混合检索（BM25-only 降级路径）→ 引用校验

用法：py -3.14 scripts/env_smoke.py
退出码：0 = 全部通过（P0 门槛达成）；1 = 存在失败项
"""
from __future__ import annotations

import sqlite3
import struct
import sys
import tempfile
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

_PASS = 0
_FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    _PASS += ok
    _FAIL += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    t0 = time.time()
    print(f"Python {sys.version.split()[0]} | SQLite {sqlite3.sqlite_version}")

    # ---- 1. sqlite-vec 加载 + vec0 ----
    try:
        import sqlite_vec  # noqa: PLC0415

        check("sqlite-vec 可导入", True, f"版本 {getattr(sqlite_vec, '__version__', '?')}")
    except ImportError as exc:
        check("sqlite-vec 可导入", False, f"{exc}")
        return 1
    db = sqlite3.connect(":memory:")
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.execute("CREATE VIRTUAL TABLE v USING vec0(embedding float[4] distance_metric=cosine)")

    def enc(v: list[float]) -> bytes:
        return struct.pack(f"<{len(v)}f", *v)

    for rowid, vec in ((1, [1, 0, 0, 0]), (2, [0, 1, 0, 0]), (3, [0, 0, 1, 0])):
        db.execute("INSERT INTO v(rowid, embedding) VALUES (?, ?)", (rowid, enc(vec)))
    rows = db.execute(
        "SELECT rowid, distance FROM v WHERE embedding MATCH ? AND k = 2",
        (enc([1, 0.1, 0, 0]),),
    ).fetchall()
    check("vec0 查询返回 k 条", len(rows) == 2, f"got {len(rows)}")
    check("vec0 相似度排序（最近邻在前）", len(rows) == 2 and rows[0][0] == 1, str(rows))
    db.execute("DELETE FROM v WHERE rowid = 2")
    n = db.execute("SELECT count(*) FROM v").fetchone()[0]
    check("vec0 DELETE", n == 2, f"remaining={n}")

    # ---- 2. FTS5 trigram 中文 ----
    db.execute("CREATE VIRTUAL TABLE t USING fts5(content, tokenize='trigram')")
    docs = [
        "合同约定违约金按合同总价百分之三十收取。",
        "双方协商不成的，争议解决方式为提交仲裁委员会仲裁。",
        "保密义务自协议生效之日起持续五年。",
        "付款条件为验收合格后三十日内一次性支付。",
        "因不可抗力导致无法履行的，双方互不承担违约责任。",
    ]
    for d in docs:
        db.execute("INSERT INTO t(content) VALUES (?)", (d,))
    terms = ["违约金", "争议解决", "保密义务", "生效之日", "合同总价", "不可抗力", "付款条件", "违约责任", "仲裁委员会", "一次性支付"]
    hit_n = 0
    for term in terms:
        n = db.execute("SELECT count(*) FROM t WHERE t MATCH ?", (term,)).fetchone()[0]
        hit_n += n >= 1
    check(
        "FTS5 trigram 中文命中率（≥3 字，10 词）",
        hit_n == len(terms),
        f"{hit_n}/{len(terms)}",
    )
    neg = db.execute("SELECT count(*) FROM t WHERE t MATCH ?", ("无关词汇",)).fetchone()[0]
    check("FTS5 负样本不命中", neg == 0, f"neg={neg}")

    # ---- 3. P1 引擎链路 E2E（BM25-only 降级路径）----
    from rag_engine import indexer, retriever  # noqa: PLC0415
    from rag_engine.embedder import Embedder  # noqa: PLC0415
    from rag_engine.citation import check_citations  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as td:
        wr = Path(td)
        doc = wr / "销售合同.md"
        doc.write_text(
            "# 销售合同\n\n"
            "## 第三条 违约责任\n\n"
            "乙方逾期交货的，应向甲方支付违约金，金额为合同总价的百分之三十。\n\n"
            "## 第十条 争议解决\n\n"
            "双方协商不成的，提交仲裁委员会仲裁。\n",
            encoding="utf-8",
        )
        dbp = wr / ".lamtools" / "rag-index" / "rag.db"
        embedder = Embedder(source="none")
        stats = indexer.index_documents(wr, dbp, paths=["销售合同.md"], embedder=embedder)
        check("索引入库（1 文件）", stats.get("added") == 1, str(stats))
        hits = retriever.search(dbp, "违约金", source="workspace_doc", top=5, embedder=embedder)
        check(
            "检索命中且片段含命中词",
            len(hits) >= 1 and "违约金" in hits[0]["snippet"],
            str([h["doc_id"][:8] for h in hits]),
        )
        check(
            "heading 锚点随块保留",
            len(hits) >= 1 and "违约责任" in (hits[0].get("heading") or ""),
            hits[0].get("heading", ""),
        )
        # 增量：重复索引跳过
        stats2 = indexer.index_documents(wr, dbp, paths=["销售合同.md"], embedder=embedder)
        check("增量索引跳过未变更文件", stats2.get("skipped") == 1, str(stats2))
        # 引用校验规则层
        ok_list = check_citations(
            "违约金 30%",
            [{"doc_id": hits[0]["doc_id"], "page": hits[0]["page"], "text": "违约金，金额为合同总价的百分之三十"}],
            hits,
        )
        bad_list = check_citations(
            "违约金 30%",
            [{"doc_id": "fake_doc_id", "page": 99, "text": "编造片段"}],
            hits,
        )
        check("引用校验：合法引用通过", all(r["ok"] for r in ok_list))
        check("引用校验：编造引用拦截", not all(r["ok"] for r in bad_list))

    print(f"\nP0 实测结果：PASS={_PASS} FAIL={_FAIL}（耗时 {time.time() - t0:.1f}s）")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
