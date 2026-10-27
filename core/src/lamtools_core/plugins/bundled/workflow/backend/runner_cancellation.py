"""Cancellation-aware awaiting and host-call argument adaptation."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any
from .runner_context import WorkflowExecutionContext


async def _call_with_supported_kwargs(call: Callable[..., Any], kwargs: dict[str, Any]) -> Any:
    """Invoke old and new agent adapters without hiding exceptions from the call."""
    try:
        signature = inspect.signature(call)
    except (TypeError, ValueError):
        selected = kwargs
    else:
        accepts_extra = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
        selected = kwargs if accepts_extra else {key: value for key, value in kwargs.items() if key in signature.parameters}
    result = call(**selected)
    return await result if inspect.isawaitable(result) else result


def _cancellation_requested(token: Any) -> bool:
    if token is None:
        return False
    if isinstance(token, bool):
        return token
    is_set = getattr(token, "is_set", None)
    if callable(is_set):
        try:
            return bool(is_set())
        except Exception:  # noqa: BLE001 — optional host token
            return False
    if callable(token):
        try:
            return bool(token())
        except Exception:  # noqa: BLE001 — optional host token
            return False
    return False


async def _await_with_context_cancel(
    awaitable: Awaitable[dict[str, Any]],
    context: WorkflowExecutionContext | None,
) -> dict[str, Any]:
    timeout_seconds: float | None = None
    if context is not None and isinstance(context.environment, dict):
        raw_timeout = context.environment.get("__workflow_timeout_seconds")
        try:
            timeout_seconds = float(raw_timeout) if raw_timeout not in (None, "") else None
        except (TypeError, ValueError):
            timeout_seconds = None
    if timeout_seconds is not None and timeout_seconds > 0:
        awaitable = asyncio.wait_for(awaitable, timeout=timeout_seconds)
    token = context.cancellation if context is not None else None
    if token is None:
        return await awaitable
    if _cancellation_requested(token):
        if inspect.iscoroutine(awaitable):
            awaitable.close()
        raise asyncio.CancelledError()
    is_set = getattr(token, "is_set", None)
    if callable(is_set) and is_set():
        if inspect.iscoroutine(awaitable):
            awaitable.close()
        raise asyncio.CancelledError()
    wait = getattr(token, "wait", None)
    if not callable(wait):
        return await awaitable
    cancellation_wait = wait()
    if not inspect.isawaitable(cancellation_wait):
        return await awaitable
    node_task = asyncio.ensure_future(awaitable)
    cancel_task = asyncio.ensure_future(cancellation_wait)
    done, _ = await asyncio.wait({node_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
    if cancel_task in done and not node_task.done():
        node_task.cancel()
        await asyncio.gather(node_task, return_exceptions=True)
        raise asyncio.CancelledError()
    cancel_task.cancel()
    await asyncio.gather(cancel_task, return_exceptions=True)
    return await node_task


def _pause_requested(context: WorkflowExecutionContext | None) -> bool:
    """Read a static or dynamically-set pause-on-cancel token."""
    if context is None:
        return False
    token = context.pause_on_cancel
    if isinstance(token, bool):
        return token
    is_set = getattr(token, "is_set", None)
    if callable(is_set):
        try:
            return bool(is_set())
        except Exception:  # noqa: BLE001 - optional host token
            return False
    if callable(token):
        try:
            return bool(token())
        except Exception:  # noqa: BLE001 - optional host token
            return False
    return bool(token)
