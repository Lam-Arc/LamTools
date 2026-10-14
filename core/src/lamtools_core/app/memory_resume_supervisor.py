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
from pathlib import Path
from typing import Any

from lamtools_core.runtime.member_wake import (
    clear_member_wake_autostart,
    mark_member_wake_autostart,
    member_wake_exhausted,
    member_wake_exhausted_message,
    member_wake_streak,
    note_member_wake,
)
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

#: Member completions that land within this window are delivered by ONE wake
#: turn, so four members finishing at once add one turn, not four (which would
#: mean four model calls, four snapshot writes, four revisions). It is the only
#: added latency: the continuation starts at most this long after the last
#: completion, and in the common case the member result is what the user is
#: waiting for, so one second is an acceptable coalescing window.
MEMBER_WAKE_COALESCE_SECONDS = 1.0

#: While a member result is pending and a turn is still running, re-check this
#: often so the continuation starts as soon as the turn releases. Only scheduled
#: when such a result is actually waiting, so it is not a standing poll.
MEMBER_WAKE_RECHECK_SECONDS = 0.5


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
    """One loop: reconcile orphaned turns, continue what memory stopped, and
    wake a session whose members finished with nobody watching."""

    def __init__(
        self,
        *,
        context: Any,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        sub_agent_data_dir: str | Path | None = None,
    ) -> None:
        self._context = context
        self._poll_seconds = max(1.0, float(poll_seconds))
        # The same directory the sub-agent supervisors live in; when it is not
        # given (focused tests, hosts without members) the member-wake pass is
        # simply inert.
        self._sub_agent_data_dir = Path(sub_agent_data_dir) if sub_agent_data_dir else None
        self._task: asyncio.Task[Any] | None = None
        self._wake = asyncio.Event()
        self._stopping = False
        # Debounce handle for coalescing member completions into one wake turn.
        self._coalesce_handle: asyncio.TimerHandle | None = None

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
        from lamtools_core.sub_agent_supervisor import set_member_event_notifier

        # A member completion wakes the loop at once instead of waiting for the
        # next tick; the notify is debounced so completions that land close
        # together become ONE turn.
        set_member_event_notifier(self.notify_member_event)

    def notify_member_event(self) -> None:
        """Debounced wake hint from a member completion (event-driven)."""
        if self._stopping or self._context is None:
            return
        if self._coalesce_handle is not None:
            return  # a wake is already pending; it will pick this event up too
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._wake.set()
            return
        self._coalesce_handle = loop.call_later(MEMBER_WAKE_COALESCE_SECONDS, self._fire_coalesced)

    def _fire_coalesced(self) -> None:
        self._coalesce_handle = None
        self._wake.set()

    def _schedule_wake_recheck(self) -> None:
        """Re-check soon while a member result waits on a still-running turn.

        Bounded and targeted: only scheduled when a pending member result could
        not be delivered because a turn is active, so the continuation starts
        within a fraction of a second of that turn releasing, without polling
        forever.
        """
        if self._stopping:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.call_later(MEMBER_WAKE_RECHECK_SECONDS, self._wake.set)

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
        from lamtools_core.sub_agent_supervisor import set_member_event_notifier

        set_member_event_notifier(None)
        if self._coalesce_handle is not None:
            self._coalesce_handle.cancel()
            self._coalesce_handle = None

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
        """One pass: repair orphaned turns, resume what memory can afford, then
        wake a session whose finished members were never delivered."""
        if self._sub_agent_data_dir is not None:
            from .sub_agent_recovery import reconcile_sub_agent_state
            try:
                await reconcile_sub_agent_state(context=self._context, data_dir=self._sub_agent_data_dir)
            except Exception:
                _logger.exception("[member-reconcile] pass failed")
        try:
            await reconcile_terminal_turns(context=self._context)
        except BaseException:
            _logger.exception("[memory-resume] reconcile failed")
        resumed = await self._resume_ready_threads()
        try:
            resumed += await self._wake_member_threads()
        except asyncio.CancelledError:
            raise
        except BaseException:
            _logger.exception("[member-wake] pass failed")
        return resumed

    async def _wake_member_threads(self) -> int:
        """Start a turn for every idle session holding an undelivered finish.

        Unlike the memory resume this does not need the session to be open in
        the interface: the events are durable rows and the started turn is
        persisted, so a later open renders it. Returns how many sessions woke.
        """
        data_dir = self._sub_agent_data_dir
        if data_dir is None:
            return 0
        from lamtools_core.sub_agent_supervisor import (
            list_threads_with_pending_member_wakes,
        )

        database = data_dir / "sub_agents.sqlite3"
        thread_ids = list_threads_with_pending_member_wakes(database)
        if not thread_ids:
            return 0
        woken = 0
        for thread_id in thread_ids:
            try:
                woken += 1 if await self._wake_member_thread(thread_id) else 0
            except asyncio.CancelledError:
                raise
            except BaseException:
                _logger.exception("[member-wake] wake failed thread_id=%s", thread_id)
        return woken

    async def _wake_member_thread(self, thread_id: str) -> bool:
        context = self._context
        data_dir = self._sub_agent_data_dir
        if data_dir is None:
            return False
        # Guard 1/2: a live turn (the user's or a kernel's) owns this thread and
        # drains its own member events; never race it with an automatic wake.
        registry = context.runtime_task_registry
        if registry is not None and registry.is_running(thread_id):
            # A live turn owns this thread; the result waits for it to release,
            # and we re-check soon so the continuation is not delayed by a full
            # poll interval.
            self._schedule_wake_recheck()
            return False
        store = context.runtime_state_store
        if store is None or not thread_id:
            return False
        state = await store.get(thread_id)
        if state is None:
            return False
        # Guard 1: an explicit user stop wins. A cancelled turn is the durable
        # record of "the user stopped this on purpose"; the wake must not undo it.
        if (str(getattr(state, "status", "") or "") == "cancelled"
                and state.metadata.get("cancellation_reason") != "unexpected_shutdown"):
            _logger.info(
                "[member-wake] safely skipping user-cancelled thread_id=%s; "
                "member events remain unclaimed for a later user-owned turn",
                thread_id,
            )
            return False
        # Guard 1b: a paused session is waiting for the user, not for us. Its
        # member events stay queued and are delivered by the resumed turn, so an
        # automatic wake can never undo the pause the user just asked for.
        if str(getattr(state, "status", "") or "") == "paused":
            _logger.info(
                "[member-wake] session is paused thread_id=%s; "
                "member events queue for the resumed turn",
                thread_id,
            )
            return False
        # Guard 4: bounded consecutive automatic wakes.
        if member_wake_exhausted(state):
            _logger.warning(
                "[member-wake] budget spent after %d consecutive wakes thread_id=%s: %s",
                member_wake_streak(state),
                thread_id,
                member_wake_exhausted_message(),
            )
            return False

        from lamtools_core.sub_agent_supervisor import (
            member_event_is_reportable,
            member_event_triggers_wake,
            member_wake_prompt,
            peek_member_events,
        )

        database = data_dir / "sub_agents.sqlite3"
        pending = peek_member_events(database, thread_id)
        # Guard 3: only a finished or failed member is wake-worthy. A member
        # paused on a question/approval is a human boundary and must never be
        # treated as a completion (and nothing here answers it).
        if not any(member_event_triggers_wake(item.get("payload") or {}) for item in pending):
            return False
        # Claim only facts this input actually reports. Recovery/shutdown
        # interruptions are included when a completion/failure already makes
        # this turn appropriate; paused and user-closed members remain pending.
        reportable = [
            item for item in pending
            if member_event_is_reportable(item.get("payload") or {})
        ]
        # Guard 2: a queued user message owns the next turn; do not race it.
        if await self._has_queued_user_item(thread_id):
            _logger.info("[member-wake] queued user message wins thread_id=%s", thread_id)
            return False

        # Tell the kernel this turn is ours BEFORE it starts, so its streak reset
        # does not wipe the counter we are enforcing (see runtime/member_wake.py).
        await _save_runtime_state_with_retry(store, thread_id, mutate=mark_member_wake_autostart)
        refused = await self._start_continuation(
            thread_id=thread_id,
            prompt=member_wake_prompt(reportable),
            kind="member-wake",
            origin="member_wake",
        )
        if refused:
            # Nothing was claimed: the row stays pending and the next tick retries.
            await _save_runtime_state_with_retry(
                store, thread_id, mutate=clear_member_wake_autostart
            )
            _logger.warning(
                "[member-wake] could not continue thread_id=%s: %s", thread_id, refused
            )
            return False
        # Guard 5: claim only after the turn started. Both paths filter on
        # `delivered_at IS NULL`, so the kernel cannot deliver these twice.
        from lamtools_core.sub_agent_supervisor import mark_member_events_delivered

        mark_member_events_delivered(database, [str(item.get("id") or "") for item in reportable])
        await _save_runtime_state_with_retry(store, thread_id, mutate=note_member_wake)
        latest = await store.get(thread_id)
        _logger.warning(
            "[member-wake] woke thread_id=%s for %d member event(s) (consecutive=%d)",
            thread_id,
            len(reportable),
            member_wake_streak(latest) if latest is not None else 0,
        )
        return True

    async def _has_queued_user_item(self, thread_id: str) -> bool:
        persistence = getattr(self._context, "persistence", None)
        session_factory = getattr(self._context, "session_factory", None)
        if persistence is None or session_factory is None:
            return False
        try:
            async with session_factory() as db:
                snapshot = await persistence.load_metadata(db, thread_id)
        except BaseException:
            _logger.exception("[member-wake] queue read failed thread_id=%s", thread_id)
            return False
        queue = snapshot.get("queue") if isinstance(snapshot, dict) else None
        if not isinstance(queue, list):
            return False
        return any(
            isinstance(item, dict)
            and str(item.get("status") or "") == "queued"
            and str(item.get("mode") or "next_turn") == "next_turn"
            for item in queue
        )

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
        refused = await self._start_continuation(
            thread_id=thread_id, prompt=prompt, kind="memory-resume", origin="memory_resume"
        )
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


    async def _start_continuation(
        self, *, thread_id: str, prompt: str, kind: str = "memory-resume", origin: str | None = None
    ) -> str:
        """Start the continuation turn; returns a refusal reason ("" on success)."""
        outcome = await handle_turn_start_operation(
            request_id=None,
            params={
                "thread_id": thread_id,
                "input": [{"type": "text", "text": prompt}],
                "client_message_id": f"{thread_id}:{kind}:{uuid.uuid4().hex[:12]}",
                **({"origin": origin} if origin else {}),
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
