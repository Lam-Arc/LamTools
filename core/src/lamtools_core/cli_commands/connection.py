"""Live command connection lifecycle and shared argument validation."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
import json
import os
from typing import Any
from lamtools_core.app.live_client import CoreAppServerClient


def _add_live_connection_args(parser: argparse.ArgumentParser) -> None:
    """The app-server connection trio a live command needs.

    Older groups spell these three out one by one; new groups call this so the
    defaults stay in step.
    """

    parser.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    parser.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    parser.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))


def _add_live_connection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    parser.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    parser.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))


async def _invoke_live(args: argparse.Namespace, operation: Any) -> dict[str, Any]:
    client = CoreAppServerClient(args.base_url, path=args.ws_path, token=args.token)
    try:
        await client.connect()
        return await operation(client)
    finally:
        await client.close()


def _print_live_result(args: argparse.Namespace, result: dict[str, Any], message: str) -> None:
    if args.raw:
        print(json.dumps(result, ensure_ascii=False), flush=True)
    else:
        print(message, flush=True)


def _positive_timeout_or_none(value: str) -> float | None:
    timeout = float(value)
    return timeout if timeout > 0 else None


def _office_positive_float(value: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be a positive number") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return number


def _office_positive_int(value: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number
