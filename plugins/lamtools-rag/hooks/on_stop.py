"""Stop hook：会话结束 → 会话历史增量索引（P2 实现）。

当前占位：不产生决策（stdout 留空 = 不干预 loop）。
P2 将从 stdin 的 JSON payload（session/run 上下文）读取 data_dir，
调用 session_indexer 增量入库。
"""
from __future__ import annotations

import sys


def main() -> int:
    # payload = sys.stdin.read()  # P2 解析
    return 0


if __name__ == "__main__":
    sys.exit(main())
