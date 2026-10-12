"""Continue a turn that a host-memory interruption stopped.

Exit criteria for the product requirement「内存中断之后，内存恢复要可以续跑」:

* the interruption is recorded with the reason and the threshold
  (``runtime/memory_guard.py`` owns that text),
* the resume is armed durably, so closing the app while waiting does not lose
  it,
* once available memory is back above the threshold the same session gets a new
  turn that picks up where it stopped, visibly stating why it continued.

The loop also runs the terminal-state reconcile (``reconcile_terminal_turns``):
the two belong together because a memory interruption is exactly the failure
that can leave a session looking alive when it is not.

Nothing here guesses. It only resumes a thread whose own recorded state says
"memory exhaustion" and whose armed resume is still pending, never a turn that
merely went quiet — a legitimate 25-minute video generation looks identical to
a dead one from the outside.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from lamtools_core.runtime.memory_guard import (
    MEMORY_RESUME_KEY,
    available_memory_gb,
    clear_pending_memory_resume,
    mark_memory_resume_handled,
    memory_resume_attempts,
    memory_resume_budget_exhausted,
    memory_resume_enabled,
    memory_resume_resumes_spent,
    memory_resume_started_message,
    pending_memory_resume,
    resume_ready,
    resume_threshold_gb,
)

from .live_operations import (
    _save_runtime_state_with_retry,
    handle_turn_start_operation,
    reconcile_terminal_turns,
)

_logger = logging.getLogger(__name__)

#: Metadata key carrying the armed resume; also what the store finds threads by.
MEMORY_RESUME_METADATA_KEY = MEMORY_RESUME_KEY

DEFAULT_POLL_SECONDS = 15.0


def memory_resume_continuation_prompt(
    *,
    original_message: str,
    resumes_spent: int,
) -> str:
    """The message the continued turn starts from.

    Unlike the question-answer continuation this one must not look like fresh
    user input: it states plainly that the previous turn died of memory and that
    finished work must not be redone.
    """
    lines = [
        memory_resume_started_message(),
        "请从中断处继续完成同一个任务，已经完成的部分不要重做；若刚才的产物已经落盘，"
        "先确认结果再往下走。",
    ]
    if resumes_spent > 0:
        lines.append(f"这是第 {resumes_spent + 1} 次继续（此前已因内存不足中断 {resumes_spent} 次）。")
    original = (original_message or "").strip()
    if original:
        lines.append("")
        lines.append(f"原始任务：{original}")
    return "\n".join(lines)


class MemoryResumeSupervisor:
    """One loop: reconcile orphaned turns, then continue what memory stopped."""

    def __init__(self, *, context: Any, poll_seconds: float = DEFAULT_POLL_SECONDS) -> None:
        self._context = context
        self._poll_seconds = max(1.0, float(poll_seconds))
        self._task: asyncio.Task[Any] | None = None
        self._wake = asyncio.Event()
        self._stopping = False

    async def start(self) -> None:
        if self._task is not None:
            return
        # One tick before the loop: a process that restarts while a resume was
        # still armed must pick it back up instead of waiting for the tick.
        # Nothing is armed here — arming happens once, where the interruption is
        # recorded, and the token is single-use. An earlier design also "adopted"
        # any session that had *ever* been interrupted by memory, which armed
        # again on every start and would have continued the same session
        # forever.
        await self._safe_tick()
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="memory-resume-supervisor")

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except BaseException:
                _logger.exception("[memory-resume] stop failed")

    def wake(self) -> None:
        """Ask for an immediate tick (a turn just ended)."""
        self._wake.set()

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll_seconds)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            if self._stopping:
                return
            await self._safe_tick()

    async def _safe_tick(self) -> None:
        try:
            await self.tick()
        except asyncio.CancelledError:
            raise
        except BaseException:
            # A watchdog that can crash the app is worse than no watchdog.
            _logger.exception("[memory-resume] tick failed")

    async def tick(self) -> int:
        """One pass: repair orphaned turns, then resume what memory can afford."""
        try:
            await reconcile_terminal_turns(context=self._context)
        except BaseException:
            _logger.exception("[memory-resume] reconcile failed")
        return await self._resume_ready_threads()

    async def _resume_ready_threads(self) -> int:
        context = self._context
        if not memory_resume_enabled():
            return 0
        store = context.runtime_state_store
        finder = getattr(store, "find_threads_with_metadata_key", None)
        if store is None or not callable(finder):
            return 0
        try:
            thread_ids = await finder(MEMORY_RESUME_METADATA_KEY)
        except BaseException:
            _logger.exception("[memory-resume] could not list armed threads")
            return 0
        if not thread_ids:
            return 0
        if not resume_ready():
            _logger.info(
                "[memory-resume] %d thread(s) waiting for memory (available %s GB < %s GB)",
                len(thread_ids),
                available_memory_gb(),
                resume_threshold_gb(),
            )
            return 0
        resumed = 0
        for thread_id in thread_ids:
            try:
                resumed += 1 if await self._resume_thread(thread_id) else 0
            except asyncio.CancelledError:
                raise
            except BaseException:
                _logger.exception("[memory-resume] resume failed thread_id=%s", thread_id)
        return resumed

    async def _resume_thread(self, thread_id: str) -> bool:
        context = self._context
        store = context.runtime_state_store
        state = await store.get(thread_id)
        if state is None:
            return False
        pending = pending_memory_resume(state)
        if not pending:
            return False
        if memory_resume_budget_exhausted(state):
            # The interruption text already told the user this was the last
            # chance, so just disarm: nothing will resume, and leaving the
            # marker behind would make every later sweep retry forever.
            await _save_runtime_state_with_retry(
                store,
                thread_id,
                mutate=lambda current: _give_up(current, str(pending.get("turn_id") or "")),
            )
            _logger.warning(
                "[memory-resume] giving up after %d interruption(s) thread_id=%s",
                memory_resume_attempts(state), thread_id,
            )
            return False
        registry = context.runtime_task_registry
        if registry is not None and registry.is_running(thread_id):
            # The user is already running something in this session; their turn
            # wins and the marker goes away in the kernel when that turn starts.
            return False

        # Disarm before starting: a start that is refused (the thread is busy
        # after all) must not leave a marker that resumes a turn later on. The
        # interruption is only marked as handled once a continuation really
        # started, so a refusal can re-arm it for the next tick.
        await _save_runtime_state_with_retry(
            store, thread_id, mutate=clear_pending_memory_resume
        )
        prompt = memory_resume_continuation_prompt(
            original_message=str(pending.get("original_message") or ""),
            resumes_spent=memory_resume_resumes_spent(state),
        )
        refused = await self._start_continuation(thread_id=thread_id, prompt=prompt)
        if refused:
            # Re-arm so the next tick tries again (memory is fine, so the usual
            # cause is the thread still being busy).
            await _save_runtime_state_with_retry(
                store,
                thread_id,
                mutate=lambda current: _rearm(current, pending),
            )
            _logger.warning(
                "[memory-resume] could not continue thread_id=%s: %s", thread_id, refused,
            )
            return False
        await _save_runtime_state_with_retry(
            store,
            thread_id,
            mutate=lambda current: mark_memory_resume_handled(
                current, str(pending.get("turn_id") or "")
            ),
        )
        _logger.warning(
            "[memory-resume] continuing thread_id=%s after memory recovered (available %s GB)",
            thread_id, available_memory_gb(),
        )
        return True


    async def _start_continuation(self, *, thread_id: str, prompt: str) -> str:
        """Start the continuation turn; returns a refusal reason ("" on success)."""
        outcome = await handle_turn_start_operation(
            request_id=None,
            params={
                "thread_id": thread_id,
                "input": [{"type": "text", "text": prompt}],
                "client_message_id": f"{thread_id}:memory-resume:{uuid.uuid4().hex[:12]}",
            },
            context=self._context,
        )
        response = getattr(outcome, "response", None)
        if isinstance(response, dict) and response.get("error"):
            failure = response.get("error")
            detail = failure.get("message") if isinstance(failure, dict) else failure
            return str(detail or "start refused")
        return ""


def _rearm(state: Any, pending: dict[str, Any]) -> None:
    """Put the armed resume back after a start that was refused."""
    metadata = getattr(state, "metadata", None)
    if isinstance(metadata, dict) and not isinstance(metadata.get(MEMORY_RESUME_METADATA_KEY), dict):
        metadata[MEMORY_RESUME_METADATA_KEY] = dict(pending)


def _give_up(state: Any, turn_id: str) -> None:
    """Disarm for good: the budget is spent, so this interruption is history."""
    clear_pending_memory_resume(state)
    mark_memory_resume_handled(state, turn_id)


__all__ = [
    "DEFAULT_POLL_SECONDS",
    "MEMORY_RESUME_METADATA_KEY",
    "MemoryResumeSupervisor",
    "memory_resume_continuation_prompt",
]
