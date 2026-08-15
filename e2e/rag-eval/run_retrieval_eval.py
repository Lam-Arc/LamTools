"""检索侧 RAG 评测（无 LLM）：recall@k / precision@k / MRR over golden set。

当前模式：BM25-only 基线（embedder=none）——混合检索消融对比的单腿基准。
对照标准：docs/rag-plugin-plan.md §2-B 文档 recall@10 ≥ 0.80。
P5 将接 RAGAS 全四维（context_recall/precision 本脚本先行；
faithfulness/answer_relevancy 需 LLM 答案，P5 接入）。

用法：py -3.14 e2e/rag-eval/run_retrieval_eval.py [--embed none|local]
报告：e2e/rag-eval/reports/retrieval-<mode>-<ts>.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "lamtools-rag"
sys.path.insert(0, str(PLUGIN_ROOT))

from rag_engine import indexer, retriever  # noqa: PLC0415
from rag_engine.db import connect  # noqa: PLC0415
from rag_engine.embedder import Embedder  # noqa: PLC0415

EVAL_DIR = Path(__file__).resolve().parent
CORPUS = EVAL_DIR / "corpus"
GOLDEN = EVAL_DIR / "golden" / "retrieval_golden.jsonl"
REPORTS = EVAL_DIR / "reports"

K = 10  # 检索窗口（与工具默认 top 一致）


def load_golden() -> list[dict]:
    items: list[dict] = []
    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--embed", choices=["none", "local"], default="none")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as td:
        wr = Path(td) / "ws"
        wr.mkdir()
        dbp = wr / ".lamtools" / "rag-index" / "rag.db"
        docs = sorted(CORPUS.glob("*.md"))
        for f in docs:
            shutil.copy2(f, wr / f.name)
        embedder = Embedder(source=args.embed)
        t0 = time.time()
        stats = indexer.index_documents(
            wr, dbp, paths=[f.name for f in docs], embedder=embedder
        )
        idx_sec = time.time() - t0
        print(
            f"语料索引（{args.embed}）：added={stats['added']} failed={len(stats['failed'])}"
            f" 耗时={idx_sec:.1f}s"
        )

        conn = connect(dbp)
        path2id = {
            r["path"]: r["doc_id"]
            for r in conn.execute(
                "SELECT path, doc_id FROM documents WHERE source='workspace_doc'"
            )
        }
        conn.close()

        results: list[dict] = []
        latencies: list[float] = []
        for item in load_golden():
            q = item["question"]
            golds = [path2id[p] for p in item["gold_docs"] if p in path2id]
            t1 = time.time()
            hits = retriever.search(
                dbp, q, source="workspace_doc", top=K, embedder=embedder
            )
            ms = (time.time() - t1) * 1000
            latencies.append(ms)
            hit_ids = [h["doc_id"] for h in hits]
            rank = next((i + 1 for i, d in enumerate(hit_ids) if d in golds), None)
            rel5 = sum(1 for d in hit_ids[:5] if d in golds)
            results.append(
                {
                    "question": q,
                    "type": item.get("type", "?"),
                    "rank": rank,
                    "r1": 1 if rank == 1 else 0,
                    "r5": 1 if rank and rank <= 5 else 0,
                    "r10": 1 if rank else 0,
                    "p5": round(rel5 / 5, 3),
                    "mrr": round(1.0 / rank, 3) if rank else 0.0,
                    "ms": round(ms, 1),
                    "top_docs": [
                        next((p for p, i in path2id.items() if i == d), "?")
                        for d in hit_ids[:3]
                    ],
                }
            )

        n = len(results)
        agg = {
            k: round(sum(r[k] for r in results) / n, 3)
            for k in ("r1", "r5", "r10", "p5", "mrr")
        }
        agg["p95_ms"] = round(sorted(latencies)[max(0, int(n * 0.95) - 1)], 1)
        passed = agg["r10"] >= 0.80
        print(f"\n=== 检索质量（{args.embed}，n={n}，golden 14 问）===")
        for k, v in agg.items():
            print(f"  {k:<8} = {v}")
        print(f"\n对照 §2-B 标准 recall@10 ≥ 0.80 → {'✅ 达标' if passed else '❌ 未达标'}")

        print("\n逐题明细（rank / 命中前 3 文档）：")
        for r in results:
            flag = "✓" if r["rank"] else "✗"
            print(
                f"  [{flag}] {r['type']:<10} rank={str(r['rank']):<3} "
                f"{r['question']} -> {r['top_docs']}"
            )

        REPORTS.mkdir(exist_ok=True)
        out = REPORTS / (
            f"retrieval-{args.embed}-{time.strftime('%Y%m%d-%H%M%S')}.json"
        )
        out.write_text(
            json.dumps(
                {"mode": f"embed={args.embed}", "aggregate": agg, "results": results},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n报告：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
