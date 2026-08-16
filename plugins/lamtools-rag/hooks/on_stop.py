"""Stop hook：会话结束 → 会话历史增量索引（P2 实现）。

stdin 读 JSON payload（hook 引擎注入：session_id / project_root /
plugin_root / metadata 等），调用 session_indexer.index_session 把
core.db 的历史消息增量写入 rag.db（source=session_history）。

不产生决策（stdout 留空 = 不干预 loop）；索引失败静默（日志 warning），
绝不让 Stop hook 影响会话结束流程。
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# hook 由引擎以 `py <plugin_root>/hooks/on_stop.py` 拉起，cwd 不定——
# 显式把插件根加入 sys.path 才能 import rag_engine 包。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag_engine.session_indexer import index_session  # noqa: E402

logging.basicConfig(level=logging.WARNING)


def main() -> int:
    payload = sys.stdin.read()
    if not payload:
        return 0
    try:
        data = json.loads(payload)
    except (ValueError, json.JSONDecodeError):
        return 0
    if not isinstance(data, dict):
        return 0
    thread_id = str(data.get("session_id") or "").strip()
    work_root = str(data.get("project_root") or data.get("cwd") or "").strip()
    if not thread_id or not work_root:
        return 0
    metadata = data.get("metadata") or {}
    session_title = str(metadata.get("session_title") or "") if isinstance(metadata, dict) else ""
    index_session(
        thread_id=thread_id,
        work_root=work_root,
        session_title=session_title,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
