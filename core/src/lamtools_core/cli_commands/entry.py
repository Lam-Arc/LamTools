"""Command-line entry, error reporting and exit status."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
import sys


def main(argv: list[str] | None = None) -> int:
    from .parser import build_parser
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(asyncio.run(args.func(args)))
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # network-level failures (httpx.ConnectError etc.)
        # Failures that do not subclass the four above (e.g. httpx transport
        # errors) used to print a raw traceback — fold them into the same
        # one-line error (audit 08 S3).
        print(f"error: {exc}", file=sys.stderr)
        return 1
