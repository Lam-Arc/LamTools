"""Backend log formatting and the shared backend log file.

Two facts drive this module:

* The file log is the only durable trace of a run in an installed build (the
  Tauri shell discards the backend's stdout/stderr), so the packaged entry
  point and the HTTP app factory must attach the *same* handler.
* Millisecond timestamps are load-bearing, not cosmetic.  Step timing is read
  by subtracting adjacent lines — request dispatched, first stream event,
  response received — so second resolution silently hides the thing being
  measured.

Step timings the kernel emits and their meaning:

    step=N dispatching model request ... gap_since_last_result=X
        → X seconds between the previous response arriving and this request
          going out (tool execution, history writeback, state save, UI events)
    step=N ... first stream event ... ttft=X
        → X seconds from dispatch to the first streamed event (provider wait)
    step=N model response received ... elapsed=X
        → X seconds for the whole call
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

BACKEND_LOG_FILENAME = "backend.log"

#: Millisecond precision: step timings are compared across lines.
LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def backend_log_formatter() -> logging.Formatter:
    """Return the shared formatter for the console and file backend logs."""
    return logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)


def attach_backend_file_logger(data_dir: Path | str) -> Path | None:
    """Attach ``<data_dir>/backend.log`` to the root logger.

    Idempotent per path: the packaged entry point and the HTTP app factory both
    call it, and a second call must not duplicate every line.  Returns the log
    path, or ``None`` when it could not be created (a read-only install
    directory must not stop the backend from starting).
    """
    try:
        target = Path(data_dir) / BACKEND_LOG_FILENAME
        target.parent.mkdir(parents=True, exist_ok=True)
        resolved = os.path.normcase(os.path.abspath(str(target)))
    except OSError:
        return None
    root = logging.getLogger()
    for handler in root.handlers:
        existing = getattr(handler, "baseFilename", None)
        if existing and os.path.normcase(os.path.abspath(str(existing))) == resolved:
            return target
    try:
        handler = logging.FileHandler(str(target), encoding="utf-8")
    except OSError:
        return None
    handler.setLevel(logging.INFO)
    handler.setFormatter(backend_log_formatter())
    root.addHandler(handler)
    return target


__all__ = [
    "BACKEND_LOG_FILENAME",
    "LOG_DATEFMT",
    "LOG_FORMAT",
    "attach_backend_file_logger",
    "backend_log_formatter",
]
