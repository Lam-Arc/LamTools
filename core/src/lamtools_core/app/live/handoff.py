"""Cancellation-safe ownership of the short acceptance-to-runtime handoff."""
from __future__ import annotations

from functools import wraps

from lamtools_core.async_tasks import finish_on_cancel

from .background import _logger


def complete_turn_handoff(operation):
    # user:“该修修，相关插件也要修”+(桌面或插件请求断开后，已接收消息仍须完成启动交接；异常必须收尾)。
    @wraps(operation)
    async def complete(*args, **kwargs):
        context = kwargs["context"]
        params = kwargs.get("params") or {}
        thread_id = str(kwargs.get("thread_id") or params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()
        registry = context.host.runtime_task_registry
        previous = registry.active_run_id(thread_id)

        async def handoff():
            try:
                return await operation(*args, **kwargs)
            except BaseException as exc:
                claimed = registry.active_run_id(thread_id)
                if claimed and claimed != previous and registry.task(thread_id, run_id=claimed) is None:
                    from .runtime_tasks import _fail_runtime_start

                    turn_id = registry.active_turn_id(thread_id) or claimed
                    try:
                        await _fail_runtime_start(
                            context=context, thread_id=thread_id, turn_id=turn_id,
                            message=str(exc) or "turn handoff interrupted",
                        )
                    except BaseException:
                        # _fail_runtime_start keeps the repair intent if the DB
                        # is unavailable and releases the claim in its finally.
                        _logger.exception("[live] failed to settle handoff thread_id=%s", thread_id)
                raise

        # The caller retains its actor until this short setup settles. Only the
        # runtime is detached; disconnect must not release the actor mid-setup.
        return await finish_on_cancel(handoff(), name=f"turn-handoff:{thread_id}")

    return complete
