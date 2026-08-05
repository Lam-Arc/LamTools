from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

from app.core.writer.core_kernel_adapter import _run_subprocess


@pytest.mark.asyncio
async def test_run_subprocess_cancellation_terminates_child(tmp_path: Path):
    marker = tmp_path / "finished.txt"
    script = (
        "import pathlib, time; "
        "time.sleep(5); "
        f"pathlib.Path({str(marker)!r}).write_text('done', encoding='utf-8')"
    )
    task = asyncio.create_task(
        _run_subprocess([sys.executable, "-c", script], cwd=tmp_path, timeout=30)
    )

    await asyncio.sleep(0.3)
    started_at = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert time.monotonic() - started_at < 3
    await asyncio.sleep(1)
    assert not marker.exists()
