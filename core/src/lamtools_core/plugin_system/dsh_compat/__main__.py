"""Offline analysis is the default; --output explicitly creates a port folder.

user:“分步做”+(CLI 把分析、生成目录和对照表生成分开，返回待移植状态供 agent 接续)。
"""

import argparse
import json
import sys
from . import analyze, export_port, render_matrix


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="DSH → Sunday 静态迁移准备")
    parser.add_argument("source", nargs="?", help="一个本地 DSH 插件包目录")
    parser.add_argument("--output", help="生成新迁移目录；拒绝覆盖现有目录")
    parser.add_argument("--matrix", action="store_true", help="输出固定上游的完整宿主对照表")
    options = parser.parse_args(argv)
    if options.matrix:
        if options.source or options.output:
            parser.error("--matrix cannot be combined with source or --output")
        print(render_matrix(), end="")
        return 0
    if not options.source:
        parser.error("source is required")
    try:
        result = export_port(options.source, options.output) if options.output else analyze(options.source)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result["status"] == "needs-port" else 0
    except (ValueError, OSError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
