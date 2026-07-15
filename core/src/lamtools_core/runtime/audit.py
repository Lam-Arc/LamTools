"""Small, secret-free runtime facts needed to reproduce Core executions."""

from __future__ import annotations

import hashlib
import platform
import sys
from pathlib import Path
from typing import Any


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def build_kernel_audit(*, policy: Any, kernel_module_path: str) -> dict[str, Any]:
    """Return effective behavior knobs without copying arbitrary policy metadata."""

    module_path = Path(kernel_module_path).resolve()
    return {
        "schema_version": 1,
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": platform.python_version(),
        "kernel_module_path": str(module_path),
        "kernel_module_sha256": _file_digest(module_path),
        "loop_policy": {
            "model_timeout_seconds": policy.model_timeout_seconds,
            "model_retries": policy.model_retries,
            "tool_timeout_seconds": policy.tool_timeout_seconds,
            "max_identical_tool_results": policy.max_identical_tool_results,
            "identical_tool_result_window": policy.identical_tool_result_window,
            "parallel_tool_calls": policy.parallel_tool_calls,
            "max_concurrent_tools": policy.max_concurrent_tools,
            "context_window_tokens": policy.context_window_tokens,
            "compact_trigger_tokens": policy.compact_trigger_tokens,
            "compact_limit_tokens": policy.compact_limit_tokens,
        },
    }


__all__ = ["build_kernel_audit"]
