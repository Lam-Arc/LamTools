"""Derive paper-facing retrieval metrics from the frozen v0.2.6 reports.

The release reports retain the first-hit rank and the first three document names.
This script verifies that the current first-hit ranks agree with document-name
deduplication for this stored case, then recomputes the aggregate values and an
inclusive, linearly interpolated p95 over the stored warm query-time values.
It deliberately does not claim complete-set recall for multi-document questions.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "e2e" / "rag-eval" / "golden" / "retrieval_golden.jsonl"
REPORTS = ROOT / "e2e" / "rag-eval" / "reports"
OUTPUT = ROOT / "docs" / "paper" / "evidence" / "retrieval-derived-v0.2.6.json"
SOURCES = {
    "bm25-only": REPORTS / "retrieval-none-20260815-095234.json",
    "local-hybrid": REPORTS / "retrieval-local-20260815-101253.json",
}


def load_golden() -> list[dict]:
    return [
        json.loads(line)
        for line in GOLDEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def inclusive_p95(values: list[float]) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[94]


def derive(mode: str, path: Path, golden: list[dict]) -> dict:
    report = json.loads(path.read_text(encoding="utf-8"))
    derived_ranks: list[int | None] = []
    for item, result in zip(golden, report["results"], strict=True):
        gold_docs = set(item["gold_docs"])
        unique_top_docs = list(dict.fromkeys(result.get("top_docs", [])))
        rank = next(
            (index + 1 for index, doc in enumerate(unique_top_docs) if doc in gold_docs),
            None,
        )
        stored_rank = result.get("rank")
        if stored_rank is not None and stored_rank > len(unique_top_docs):
            raise ValueError(
                f"{mode}: stored rank {stored_rank} exceeds retained top_docs "
                f"for question {result['question']!r}; rerun the harness before deriving."
            )
        if rank != stored_rank:
            raise ValueError(
                f"{mode}: deduplicated rank {rank} disagrees with stored rank "
                f"{stored_rank} for question {result['question']!r}."
            )
        derived_ranks.append(rank)

    n = len(derived_ranks)
    aggregate = {
        f"any_gold_recall@{k}": round(
            sum(rank is not None and rank <= k for rank in derived_ranks) / n, 3
        )
        for k in (1, 5, 10)
    }
    aggregate["mrr_first_any_gold"] = round(
        sum(1 / rank if rank else 0 for rank in derived_ranks) / n, 3
    )
    latencies = [float(item["ms"]) for item in report["results"]]
    aggregate["p95_warm_query_ms"] = round(inclusive_p95(latencies), 2)
    return {
        "mode": mode,
        "source_report": str(path.relative_to(ROOT)).replace("\\", "/"),
        "question_count": n,
        "aggregate": aggregate,
        "ranks": derived_ranks,
        "latencies_ms": latencies,
    }


def main() -> None:
    golden = load_golden()
    derived = {
        mode: derive(mode, path, golden) for mode, path in SOURCES.items()
    }
    result = {
        "software_version": "v0.2.6",
        "software_commit": "dd54b7fdd57f4eb0926f1dd3a94fbf2c2bb0fd8a",
        "metric_definition": "Any-gold document Recall@k after deduplicating returned document IDs; a multi-document question counts as a hit when any gold document appears.",
        "mrr_definition": "Mean reciprocal rank of the first any-gold document; complete-set recall is not measured.",
        "latency_definition": "Warm query-time latency retained in the source reports; p95 uses inclusive linear interpolation over the 14 per-question values.",
        "derived": derived,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT)
    for mode, item in derived.items():
        print(mode, item["aggregate"])


if __name__ == "__main__":
    main()
