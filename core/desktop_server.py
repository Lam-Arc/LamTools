from __future__ import annotations

import asyncio
import multiprocessing
import os
import sys

from lamtools_core.cli import cmd_serve


class ServeArgs:
    host = "127.0.0.1"
    port = 5172
    model_id = ""
    config_db = ""
    core_db = ""
    data_dir = ""
    work_root = ""
    thinking = "enabled"
    thinking_budget = 10000
    max_tokens = None
    temperature = 0.2
    raw = False

    def __getattr__(self, name: str):
        return getattr(self, name, None)


def main() -> None:
    if os.name == "nt":
        multiprocessing.freeze_support()

    port = int(os.environ.get("LAMTOOLS_CORE_PORT", "5172"))
    data_dir = os.environ.get("LAMTOOLS_CORE_DATA_DIR", "")
    work_root = os.environ.get("LAMTOOLS_CORE_WORK_ROOT", "")

    args = ServeArgs()
    args.port = port
    if data_dir:
        args.data_dir = data_dir
    if work_root:
        args.work_root = work_root

    sys.argv = ["lamtools-core", "serve", "--port", str(port)]
    if data_dir:
        sys.argv.extend(["--data-dir", data_dir])
    if work_root:
        sys.argv.extend(["--work-root", work_root])

    asyncio.run(cmd_serve(args))


if __name__ == "__main__":
    main()
