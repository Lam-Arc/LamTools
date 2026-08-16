"""手动会话历史索引（P2）：Stop hook 之外的补索引入口。

用法：
  py scripts/session_index.py --work-root <项目根> [--thread-id <会话id>] [--core-db <core.db>]

缺省 --thread-id 时索引 core.db 中全部会话；重复执行幂等（水位增量）。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag_engine.session_indexer import core_db_path, index_session  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Index session history into rag.db (P2)")
    parser.add_argument("--work-root", required=True, help="Project/work root (rag.db lives under its .lamtools/rag-index/)")
    parser.add_argument("--thread-id", default="", help="Session thread id (default: all sessions)")
    parser.add_argument("--core-db", default="", help="core.db path (default: LAMTOOLS_CORE_DB or {repo}/data/core.db)")
    args = parser.parse_args()

    db_path = Path(args.core_db) if args.core_db else core_db_path()
    if not db_path.exists():
        print(f"core.db not found: {db_path}", flush=True)
        return 1
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        print(f"cannot open core.db: {exc}", flush=True)
        return 1
    try:
        if args.thread_id:
            thread_ids = [args.thread_id]
        else:
            rows = conn.execute(
                "SELECT DISTINCT thread_id FROM core_history_entries ORDER BY thread_id"
            ).fetchall()
            thread_ids = [r[0] for r in rows]
    finally:
        conn.close()

    total_indexed = 0
    total_chunks = 0
    for thread_id in thread_ids:
        result = index_session(thread_id=thread_id, work_root=args.work_root)
        total_indexed += result["indexed"]
        total_chunks += result["chunks"]
        print(
            f"{thread_id}: indexed={result['indexed']} chunks={result['chunks']} "
            f"watermark={result['watermark']}",
            flush=True,
        )
    print(f"done: {len(thread_ids)} sessions, {total_indexed} messages, {total_chunks} chunks", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
