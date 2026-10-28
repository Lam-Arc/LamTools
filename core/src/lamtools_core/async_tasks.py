"""Own short commit-and-activate operations through caller cancellation."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any, TypeVar

_logger = logging.getLogger(__name__)
T = TypeVar("T")


async def finish_on_cancel(work: Coroutine[Any, Any, T], *, name: str) -> T:
    # user:“该修修，相关插件也要修”+(请求断线和重复取消不能截断已开始的提交与启动交接；保留调用者的取消结果)。
    task = asyncio.create_task(work, name=name)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        if not task.cancelled() and task.exception() is not None:
            _logger.error("Cancelled caller's operation %s failed: %s", name, task.exception())
        raise
