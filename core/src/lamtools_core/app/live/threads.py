"""Threads responsibilities."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from ..event_store import AppEventInput
from ..live_protocol import INVALID_REQUEST, int_param as _int_param, rpc_error, rpc_result
from ..thread_history import (
    _character_page_snapshot,
    _history_byte_budget,
    _history_char_limit,
    _history_cursor,
    _history_turn_limit,
    _page_item_byte_budget,
)
from ..thread_outline import build_thread_outline, normalize_thread_outline_char_limit
from .context import CoreLiveContext, CoreLiveOperationOutcome


async def handle_thread_resume_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    from .terminal_state import _reconcile_cancelled_runtime_state
    thread_id = str(params.get("thread_id") or params.get("threadId") or "")
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    after_seq = _int_param(params.get("last_seen_seq") or params.get("lastSeenSeq"), default=0)
    host = getattr(context, "host", None)
    session_store = getattr(host, "session_store", None)
    if session_store is not None and await session_store.get(thread_id) is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread not found")
        )
    include_snapshot = params.get("include_snapshot") is not False
    full_journal = params.get("full_journal") is True
    page_limit = max(1, min(_int_param(params.get("limit"), default=500), 500))
    before_item_id, before_seq = _history_cursor(params)
    async with context.session_factory() as db:
        # The snapshot is the durable authority for everything up to its
        # snapshot_seq.  Journal paging therefore starts after that seq unless
        # the client opts out of the snapshot or explicitly asks for the raw
        # journal (replay-style clients that rebuild state from events).
        # Re-delivering events the snapshot already covers made every session
        # switch fetch and serialize up to 500 stale events (~8.5MB on long
        # threads) that snapshot-hydrating clients immediately discard.
        snapshot = await _load_thread_page(
            context=context,
            db=db,
            thread_id=thread_id,
            params=params,
            page_bytes=_history_byte_budget(params),
        )
        journal_after_seq = after_seq
        if include_snapshot and not full_journal:
            projected_seq = _int_param(
                snapshot.get("snapshot_seq") if isinstance(snapshot, dict) else None,
                default=0,
            )
            journal_after_seq = max(after_seq, projected_seq)
        events = await context.persistence.list_after(
            db, thread_id=thread_id, after_seq=journal_after_seq, limit=page_limit
        )
    await _reconcile_cancelled_runtime_state(context=context, thread_id=thread_id, snapshot=snapshot)
    last_event_seq = max((event.seq for event in events), default=journal_after_seq)
    snapshot_seq = _int_param(snapshot.get("snapshot_seq") if isinstance(snapshot, dict) else None, default=last_event_seq)
    if include_snapshot and not full_journal:
        # Projection writes share the event's transaction, so the journal tail
        # past the snapshot is normally empty.  A full page is the only honest
        # "more may exist" signal that does not depend on that invariant.
        has_more = bool(events) and len(events) >= page_limit
    else:
        has_more = bool(events) and last_event_seq < snapshot_seq
    result: dict[str, Any] = {
        "thread": {"id": thread_id},
        "events": [event.to_dict() for event in events],
        "has_more": has_more,
        "next_after_seq": last_event_seq,
    }
    if include_snapshot:
        result["snapshot"] = _character_page_snapshot(
            snapshot,
            before_item_id=before_item_id,
            before_seq=before_seq,
            char_limit=_history_char_limit(params),
            turn_limit=_history_turn_limit(params),
            byte_limit=_history_byte_budget(params),
        )
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, result)
    )


async def handle_sync_start_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: "CoreLiveContext",
) -> "CoreLiveOperationOutcome":
    """Return one atomic Local-First snapshot or a bounded journal delta."""
    journal = getattr(getattr(context, "host", None), "sync_journal", None)
    if journal is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="sync journal is unavailable")
        )
    raw_cursor = params.get("cursor")
    cursor: int | None
    if raw_cursor is None or raw_cursor == "":
        cursor = None
    else:
        try:
            cursor = int(raw_cursor)
        except (TypeError, ValueError):
            return CoreLiveOperationOutcome(
                response=rpc_error(request_id, code=INVALID_REQUEST, message="cursor must be an integer or null")
            )
        if cursor < 0:
            return CoreLiveOperationOutcome(
                response=rpc_error(request_id, code=INVALID_REQUEST, message="cursor must be non-negative")
            )
    result = await journal.sync(cursor=cursor, limit=int(params.get("limit") or 500))
    # Cursor expiry is a protocol result, rather than a transport failure. It
    # lets the mobile client atomically replace its local database with the
    # next snapshot and keeps the long-lived tunnel alive.
    return CoreLiveOperationOutcome(response=rpc_result(request_id, result))


async def handle_thread_read_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    from .terminal_state import _reconcile_cancelled_runtime_state
    thread_id = str(params.get("thread_id") or params.get("threadId") or "")
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    session_store = getattr(getattr(context, "host", None), "session_store", None)
    if session_store is not None and await session_store.get(thread_id) is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread not found")
        )
    before_item_id, before_seq = _history_cursor(params)
    async with context.session_factory() as db:
        snapshot = await _load_thread_page(
            context=context,
            db=db,
            thread_id=thread_id,
            params=params,
            page_bytes=_history_byte_budget(params),
        )
        events = []
        member_payload = await context.host.member_hooks.augment_thread_read(
            db=db,
            thread_id=thread_id,
            result={"snapshot": snapshot, "events": events},
        )
    await _reconcile_cancelled_runtime_state(context=context, thread_id=thread_id, snapshot=snapshot)
    return CoreLiveOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "thread": {"id": thread_id},
                "events": [event.to_dict() for event in events],
                "snapshot": _character_page_snapshot(
                    snapshot,
                    before_item_id=before_item_id,
                    before_seq=before_seq,
                    char_limit=_history_char_limit(params),
                    turn_limit=_history_turn_limit(params),
                    byte_limit=_history_byte_budget(params),
                ),
                **member_payload,
            },
        )
    )


async def handle_thread_history_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Return one older complete-turn page for an already opened thread."""
    thread_id = str(params.get("thread_id") or params.get("threadId") or "").strip()
    before_item_id = str(params.get("before_item_id") or params.get("beforeItemId") or "").strip()
    before_seq = _int_param(params.get("before_seq") or params.get("beforeSeq"), default=0)
    if not thread_id or (not before_item_id and before_seq <= 0):
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="thread_id and a history cursor are required",
            )
        )
    session_store = getattr(getattr(context, "host", None), "session_store", None)
    if session_store is not None and await session_store.get(thread_id) is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread not found")
        )
    async with context.session_factory() as db:
        snapshot = await _load_thread_page(
            context=context,
            db=db,
            thread_id=thread_id,
            params=params,
            page_bytes=_history_byte_budget(params),
        )
    return CoreLiveOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "thread": {"id": thread_id},
                "snapshot_page": _character_page_snapshot(
                    snapshot,
                    before_item_id=before_item_id or None,
                    before_seq=before_seq,
                    char_limit=_history_char_limit(params),
                    turn_limit=_history_turn_limit(params),
                    byte_limit=_history_byte_budget(params),
                ),
            },
        )
    )


async def handle_thread_outline_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Return a bounded conversation outline without exposing transcript bodies."""

    thread_id = str(params.get("thread_id") or params.get("threadId") or "").strip()
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    # Keep existence and access behavior identical to thread.history/read.  In
    # the production host the session store is the authoritative thread
    # namespace; focused operation tests may construct a host without one.
    session_store = getattr(getattr(context, "host", None), "session_store", None)
    if session_store is not None and await session_store.get(thread_id) is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread not found")
        )
    limit = normalize_thread_outline_char_limit(
        params.get("char_limit") or params.get("charLimit")
    )
    async with context.session_factory() as db:
        # The outline needs each turn's own closing assistant body, which can sit
        # arbitrarily deep inside a turn that ends with child output (measured:
        # 200 items deep on the longest development thread). A bounded read
        # cannot reproduce it, and a wrong or empty excerpt is worse than a slow
        # panel, so this one read stays complete.
        snapshot = await context.persistence.load(db, thread_id)
    outline = build_thread_outline(
        snapshot,
        thread_id=thread_id,
        char_limit=limit,
    )
    return CoreLiveOperationOutcome(response=rpc_result(request_id, outline))


async def _load_thread_page(
    *,
    context: CoreLiveContext,
    db: Any,
    thread_id: str,
    params: dict[str, Any],
    page_bytes: int,
) -> dict[str, Any]:
    """Load one conversation page instead of the whole thread.

    Every transcript read (open, read, history) serves at most one page, so
    materializing every item row first made the first screen of a long thread
    cost as much as reading all of it. Hosts without the bounded read keep the
    full assembly so the operation stays usable everywhere.
    """
    before_item_id, before_seq = _history_cursor(params)
    loader = getattr(context.persistence, "load_page", None)
    if not callable(loader):
        return await context.persistence.load(db, thread_id)
    return await loader(
        db,
        thread_id,
        before_item_id=before_item_id,
        before_seq=before_seq,
        item_byte_budget=_page_item_byte_budget(page_bytes),
    )


async def handle_thread_start_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    from .events import _append_app_event
    from .params import _expected_revision, _thread_id_from_params
    thread_id = _thread_id_from_params(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    try:
        expected_revision = _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))

    async def write(db: AsyncSession):
        await context.persistence.assert_revision(db, thread_id, expected_revision)
        member_payload = await context.host.member_hooks.materialize_thread(
            db=db,
            thread_id=thread_id,
            params=params,
        )
        event = await _append_app_event(
            db,
            context=context,
            event=AppEventInput(
                thread_id=thread_id,
                method="thread/started",
                payload={"type": "thread", "status": "idle", **params, **member_payload},
            ),
        )
        return event, await context.persistence.load(db, thread_id)

    event, snapshot = await context.persistence.write(write)
    await context.hub.publish(event)
    return CoreLiveOperationOutcome(
        response=rpc_result(
            request_id,
            {"thread": {"id": thread_id}, "event": event.to_dict(), "snapshot": snapshot},
        ),
        publish_events=[event],
    )
