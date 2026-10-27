"""Bounded history pages and attachment reference views for live threads."""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .live_protocol import int_param as _int_param
from .queue_state import ACTIVE_TURN_STATUSES

# user:“审查后端大文件并拆分”+(按职责独立维护实现，原模块保留导入入口以兼容现有调用。)

# History paging bounds.
#
# Every live paging path (thread.resume / thread.read / thread.history) routes
# through ``_character_page_snapshot``, which now budgets the page by
# *serialized bytes*. Items are selected newest-first and accumulation stops
# once the next item would cross the byte budget, so a page may end inside a
# turn — the before_item_id/before_seq cursor already addresses that, and the
# client already loops thread.history with it.
#
# One item is one tool exchange: a tool_call and its tool_result share an item id
# (see runtime_projection._tool_item_id), so an item-boundary cut can never
# strand a result without its call.
#
# ``char_limit`` and ``turn_limit`` are retained as informational / turn-count
# upper bounds only; ``MAX_THREAD_HISTORY_CHAR_LIMIT`` is still not a size guard.
# The byte budget is deliberately well under the 4 MiB single-message cap most
# clients enforce. A single item that exceeds the budget on its own (an oversized
# body that should not ride with the page) still yields one page of at least that
# item, so paging always makes progress; that separate case is not solved here.
DEFAULT_THREAD_HISTORY_CHAR_LIMIT = 200_000
MAX_THREAD_HISTORY_CHAR_LIMIT = 1_000_000
DEFAULT_THREAD_HISTORY_TURN_LIMIT = 10
MAX_THREAD_HISTORY_TURN_LIMIT = 100
DEFAULT_THREAD_HISTORY_PAGE_BYTES = 2 * 1024 * 1024
MAX_THREAD_HISTORY_PAGE_BYTES = 3 * 1024 * 1024
MIN_THREAD_HISTORY_PAGE_BYTES = 64 * 1024
# Inline artifact bodies (notably ``metadata.image_data_url`` on tool results)
# are the only thing that can push a single item past the page budget. When one
# exceeds this, the page carries a reference instead: the durable snapshot, the
# event row and the database keep the body byte for byte, and only the serialized
# page swaps it for an identifier + mime type + byte size with
# ``availability == "reference"``, resolved on demand through the existing
# artifact path/read. See the "single oversized item" design note.
MAX_INLINE_ARTIFACT_BYTES = 256 * 1024
ARTIFACT_AVAILABILITY_REFERENCE = "reference"


def _history_char_limit(params: dict[str, Any]) -> int:
    """Clamp the requested character budget.

    Informational only on every live path: it is handed to
    ``_character_page_snapshot`` together with a ``turn_limit``, and turn-limit
    mode never splits a turn by characters.  It surfaces as
    ``history_page.char_limit`` and drives selection only in the legacy
    character-only mode that direct callers can reach by passing
    ``turn_limit=None`` (no live RPC does).  See the constants block above.
    """
    raw = params.get("char_limit") or params.get("charLimit")
    return max(1_000, min(_int_param(raw, default=DEFAULT_THREAD_HISTORY_CHAR_LIMIT), MAX_THREAD_HISTORY_CHAR_LIMIT))


def _history_turn_limit(params: dict[str, Any]) -> int:
    """Clamp the requested page size in turns (an upper bound, not the size guard)."""
    raw = params.get("turn_limit") or params.get("turnLimit")
    return max(1, min(_int_param(raw, default=DEFAULT_THREAD_HISTORY_TURN_LIMIT), MAX_THREAD_HISTORY_TURN_LIMIT))


def _history_byte_budget(params: dict[str, Any]) -> int:
    """Clamp the requested page byte budget (the real response-size guard).

    Defaults to ``DEFAULT_THREAD_HISTORY_PAGE_BYTES`` (well under the 4 MiB
    client cap) and is bounded above by ``MAX_THREAD_HISTORY_PAGE_BYTES`` so a
    caller cannot ask for a page that would defeat the guard.
    """
    raw = params.get("page_bytes") or params.get("pageBytes")
    requested = _int_param(raw, default=DEFAULT_THREAD_HISTORY_PAGE_BYTES)
    return max(MIN_THREAD_HISTORY_PAGE_BYTES, min(requested, MAX_THREAD_HISTORY_PAGE_BYTES))


def _history_cursor(params: dict[str, Any]) -> tuple[str | None, int | None]:
    """Optional before cursor shared by thread.read/resume/history.

    ``(None, None)`` means "newest page". Passing it explicitly lets the same
    continuation loop the client already runs against ``thread.history`` also
    walk the snapshot embedded in ``thread.read`` / ``thread.resume``.
    """
    before_item_id = str(params.get("before_item_id") or params.get("beforeItemId") or "").strip() or None
    raw_seq = params.get("before_seq") or params.get("beforeSeq")
    before_seq = None if raw_seq is None or raw_seq == "" else _int_param(raw_seq, default=0)
    return before_item_id, before_seq


def _mime_from_data_url(value: str) -> str:
    """Extract the media type from a ``data:<mime>;base64,...`` URL."""
    if not value.startswith("data:"):
        return ""
    header = value[5:].split(",", 1)[0]
    return header.split(";", 1)[0].strip()


def _decoded_data_url_size(value: str) -> int:
    """Approximate decoded byte size of a base64 data URL."""
    if "," not in value:
        return 0
    payload = value.split(",", 1)[1]
    padding = payload.count("=", max(0, len(payload) - 2))
    return max(0, (len(payload) * 3) // 4 - padding)


def _artifact_has_large_inline_body(artifact: Mapping[str, Any]) -> bool:
    """True when an artifact carries an inline body worth referencing out.

    Only data-URL bodies over ``MAX_INLINE_ARTIFACT_BYTES`` count; a small inline
    body is left alone so ordinary cards stay self-contained.
    """
    def _is_large(value: Any) -> bool:
        return isinstance(value, str) and value.startswith("data:") and len(value) > MAX_INLINE_ARTIFACT_BYTES

    if _is_large(artifact.get("content")):
        return True
    metadata = artifact.get("metadata")
    if isinstance(metadata, Mapping):
        return any(_is_large(value) for value in metadata.values())
    return False


def _artifact_reference(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Replace an oversized inline body with an explicit reference marker.

    The durable artifact is untouched: this returns a new dict holding the
    artifact's identity (``artifact_id``) plus, explicitly, a mime type and a
    byte size, with ``availability == "reference"`` and the bulky data URL
    dropped. The client resolves the body on demand through the existing
    artifact path/read, so nothing needs a new fetch call.
    """
    reference = dict(artifact)
    mime = str(artifact.get("mime_type") or "")
    size = artifact.get("size_bytes")
    inline_bytes = 0
    metadata = artifact.get("metadata")
    if not isinstance(size, int) and isinstance(metadata, Mapping):
        # The artifact's own file size is the most useful display size; fall back
        # to decoding the data URL only when it is absent.
        declared = metadata.get("size_bytes")
        if isinstance(declared, int):
            size = declared

    if isinstance(metadata, Mapping):
        trimmed: dict[str, Any] = {}
        for key, value in metadata.items():
            if isinstance(value, str) and value.startswith("data:"):
                inline_bytes += len(value)
                mime = mime or _mime_from_data_url(value)
                if not isinstance(size, int):
                    size = _decoded_data_url_size(value)
                continue
            trimmed[key] = value
        reference["metadata"] = trimmed

    content = artifact.get("content")
    if isinstance(content, str) and content.startswith("data:") and len(content) > MAX_INLINE_ARTIFACT_BYTES:
        inline_bytes += len(content)
        mime = mime or _mime_from_data_url(content)
        if not isinstance(size, int):
            size = _decoded_data_url_size(content)
        reference.pop("content", None)

    reference["availability"] = ARTIFACT_AVAILABILITY_REFERENCE
    if mime:
        reference["mime_type"] = mime
    if isinstance(size, int):
        reference["size_bytes"] = size
    reference["inline_bytes"] = inline_bytes
    return reference


def _reference_oversized_item_artifacts(item: dict[str, Any]) -> dict[str, Any]:
    """Return the wire view of an item: original, or a copy with bodies referenced.

    The copy is shallow and fresh (a new artifact list) so the shared snapshot
    item — and therefore the durable row — is never mutated.
    """
    artifacts = item.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return item
    replaced: list[Any] | None = None
    for index, artifact in enumerate(artifacts):
        if isinstance(artifact, Mapping) and _artifact_has_large_inline_body(artifact):
            if replaced is None:
                replaced = list(artifacts)
            replaced[index] = _artifact_reference(artifact)
    if replaced is None:
        return item
    view = dict(item)
    view["artifacts"] = replaced
    return view


def _character_page_snapshot(
    snapshot: dict[str, Any],
    *,
    before_item_id: str | None,
    before_seq: int | None,
    char_limit: int,
    turn_limit: int | None = None,
    byte_limit: int = DEFAULT_THREAD_HISTORY_PAGE_BYTES,
) -> dict[str, Any]:
    """Keep snapshot metadata but include only one newest-first, byte-bounded page.

    Items are selected newest-first and accumulation stops once the next item
    would push the page past ``byte_limit`` serialized bytes, so a page may end
    inside a turn (the before_item_id/before_seq cursor the client already loops
    on addresses that). ``turn_limit`` is a turn-count upper bound and
    ``char_limit`` is informational only. A single item larger than
    ``byte_limit`` still yields a page containing at least that one item, so
    paging always makes progress; that oversized-body case is not solved here.
    Artifact bodies are available through artifact operations and never ride with
    conversation pages.

    The page is assembled without cloning the snapshot: every key the page
    replaces is rebuilt into a fresh container, so the input snapshot is never
    mutated, while untouched branches — including the exposed item dicts — are
    shared with the caller. The page is meant to be serialized into a response
    immediately, not stored or mutated by callers. Item sizes are measured lazily
    per item instead of serializing the whole thread up front (tens of MB on long
    sessions); bytes are measured so the budget is a real wire-size bound.
    """
    core = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else {}
    raw_core_items = core.get("items") if isinstance(core.get("items"), dict) else {}
    raw_core_order = (
        core.get("item_order")
        if isinstance(core.get("item_order"), list)
        else list(raw_core_items)
    )
    raw_top_items = snapshot.get("items") if isinstance(snapshot.get("items"), dict) else {}
    raw_top_order = (
        snapshot.get("item_order")
        if isinstance(snapshot.get("item_order"), list)
        else list(raw_top_items)
    )
    turn_id_by_item: dict[str, str] = {}
    for raw_turns in (snapshot.get("turns"), core.get("turns")):
        if not isinstance(raw_turns, dict):
            continue
        for raw_turn_id, raw_turn in raw_turns.items():
            if not isinstance(raw_turn, dict):
                continue
            turn_id = str(raw_turn.get("turn_id") or raw_turn_id)
            for raw_item_id in raw_turn.get("items") or []:
                turn_id_by_item.setdefault(str(raw_item_id), turn_id)

    char_sizes: dict[str, int] = {}
    byte_sizes: dict[str, int] = {}
    wired_top: dict[str, dict[str, Any]] = {}
    wired_core: dict[str, dict[str, Any]] = {}

    def _wire(item_id: str, items: dict[str, Any], cache: dict[str, dict[str, Any]]) -> Any:
        # The wire view is the item with any oversized inline artifact body
        # swapped for a reference. Sizes and the page both use this view, so the
        # budget bounds what is actually sent while the durable item is untouched.
        item = items.get(item_id)
        if not isinstance(item, dict):
            return item
        cached = cache.get(item_id)
        if cached is None:
            cached = _reference_oversized_item_artifacts(item)
            cache[item_id] = cached
        return cached

    def _item_chars(item_id: str) -> int:
        # Mirrors the merged-timeline semantics: an item id present in both the
        # top-level and core maps contributes both serialized sizes.
        cached = char_sizes.get(item_id)
        if cached is None:
            cached = 0
            item = _wire(item_id, raw_top_items, wired_top)
            if isinstance(item, dict):
                cached += len(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
            item = _wire(item_id, raw_core_items, wired_core)
            if isinstance(item, dict):
                cached += len(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
            char_sizes[item_id] = cached
        return cached

    def _item_bytes(item_id: str) -> int:
        # UTF-8 byte length, not characters: the budget must bound what actually
        # goes on the wire (CJK content is 3 bytes per character).
        cached = byte_sizes.get(item_id)
        if cached is None:
            cached = 0
            item = _wire(item_id, raw_top_items, wired_top)
            if isinstance(item, dict):
                cached += len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            item = _wire(item_id, raw_core_items, wired_core)
            if isinstance(item, dict):
                cached += len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            byte_sizes[item_id] = cached
        return cached

    # User messages live in the top-level item map while assistant process
    # items live in ``core``. Paging only the latter made the user side of a
    # large turn unreachable: its id could never become a history cursor.
    # Build one thread-global timeline, matching the UI's seq-based merge.
    ordered_by_id: dict[str, tuple[int, int, int, str, str]] = {}
    for source_rank, (raw_order, raw_items) in enumerate(
        ((raw_top_order, raw_top_items), (raw_core_order, raw_core_items))
    ):
        for index, raw_id in enumerate(raw_order, 1):
            item_id = str(raw_id)
            item = raw_items.get(item_id)
            if not isinstance(item, dict):
                continue
            seq = _int_param(item.get("seq") or item.get("last_seq"), default=index)
            turn_id = str(item.get("turn_id") or turn_id_by_item.get(item_id) or "")
            previous = ordered_by_id.get(item_id)
            if previous is None:
                ordered_by_id[item_id] = (seq, source_rank, index, item_id, turn_id)
            else:
                ordered_by_id[item_id] = (*previous[:4], previous[4] or turn_id)
    full_order = sorted(ordered_by_id.values(), key=lambda entry: entry[:4])
    # How many items the thread actually has. A bounded read materializes only
    # the newest page of conversation rows, so the envelope must come from the
    # metadata's item orders rather than from the loaded items — otherwise a
    # thread with thousands of items would report has_more=false after the first
    # page and the older turns would become unreachable.
    total_items = len(set(raw_top_order) | set(raw_core_order) | set(ordered_by_id))

    before_index = None
    if before_item_id:
        before_index = next(
            (index for index, entry in enumerate(full_order) if entry[3] == before_item_id),
            None,
        )
    if before_index is not None:
        ordered = full_order[:before_index]
    elif before_seq is not None:
        ordered = [entry for entry in full_order if entry[0] < before_seq]
    else:
        ordered = full_order

    selected: list[tuple[int, int, int, str, str]] = []
    if turn_limit is not None:
        # Byte-budgeted selection, newest-first. Accumulation stops before the
        # next item would cross the budget, so a page may end inside a turn; the
        # cursor below is what the client already follows. ``turn_limit`` stays a
        # turn-count upper bound. At least one item is always taken so a page
        # never comes back empty (progress even when one item alone is oversized).
        selected_turns: set[str] = set()
        selected_bytes = 0
        for entry in reversed(ordered):
            turn_key = entry[4] or f"item:{entry[3]}"
            if turn_key not in selected_turns and len(selected_turns) >= turn_limit:
                continue
            item_bytes = _item_bytes(entry[3])
            if selected and selected_bytes + item_bytes > byte_limit:
                break
            selected.append(entry)
            selected_bytes += item_bytes
            selected_turns.add(turn_key)
        selected.reverse()
    else:
        character_count = 0
        for entry in reversed(ordered):
            item_chars = _item_chars(entry[3])
            if selected and character_count + item_chars > char_limit:
                break
            selected.append(entry)
            character_count += item_chars
        selected.reverse()
    selected_ids = {entry[3] for entry in selected}
    earliest_seq = min((entry[0] for entry in selected), default=None)
    # ``selected``/``ordered`` cover only the items this read materialized: a
    # bounded read returns the newest page of rows, so "is there older content"
    # is either an unselected loaded item or the store's probe for rows older
    # than the loaded prefix. ``total_items`` still reports the thread's full
    # item count from the metadata, which is what progress/paging UI reads.
    has_more = len(selected) < len(ordered) or bool(core.get("_page_has_older_items"))

    # If a page begins inside an assistant turn, retain the user inputs that
    # causally precede the visible assistant items. They are lightweight turn
    # anchors, do not affect the contiguous history cursor, and prevent an
    # assistant-only first render for a large single-turn thread.
    selected_turn_max_seq: dict[str, int] = {}
    for seq, _, _, item_id, _turn_id in selected:
        item = raw_core_items.get(item_id)
        turn_id = str(item.get("turn_id") or "") if isinstance(item, dict) else ""
        if turn_id:
            selected_turn_max_seq[turn_id] = max(selected_turn_max_seq.get(turn_id, seq), seq)
    context_user_ids: set[str] = set()
    for index, raw_id in enumerate(raw_top_order, 1):
        item_id = str(raw_id)
        item = raw_top_items.get(item_id)
        if not isinstance(item, dict) or str(item.get("type") or "") != "userMessage":
            continue
        turn_id = str(item.get("turn_id") or "")
        max_seq = selected_turn_max_seq.get(turn_id)
        seq = _int_param(item.get("seq") or item.get("last_seq"), default=index)
        if max_seq is not None and seq <= max_seq:
            context_user_ids.add(item_id)
    visible_ids = selected_ids | context_user_ids
    character_count = sum(_item_chars(entry[3]) for entry in selected) + sum(
        len(json.dumps(raw_top_items[item_id], ensure_ascii=False, separators=(",", ":")))
        for item_id in context_user_ids - selected_ids
    )

    def filtered_turns(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, Any] = {}
        for turn_id, raw_turn in value.items():
            if not isinstance(raw_turn, dict):
                continue
            turn_items = [str(item_id) for item_id in raw_turn.get("items") or []]
            kept = [item_id for item_id in turn_items if item_id in visible_ids]
            if kept or str(raw_turn.get("status") or "") in ACTIVE_TURN_STATUSES:
                result[str(turn_id)] = {**raw_turn, "items": kept}
        return result

    page_core = dict(core)
    # Private store hint for the paging envelope; never part of the wire page.
    page_core.pop("_page_has_older_items", None)
    page_core["items"] = {
        item_id: _wire(item_id, raw_core_items, wired_core)
        for item_id in selected_ids
        if isinstance(raw_core_items.get(item_id), dict)
    }
    page_core["item_order"] = [
        str(item_id) for item_id in raw_core_order if str(item_id) in selected_ids
    ]
    page_core["turns"] = filtered_turns(core.get("turns"))
    page_core["artifacts"] = {}
    page_core["seen_event_ids"] = []
    page = dict(snapshot)
    page["core"] = page_core
    page["items"] = {
        item_id: _wire(item_id, raw_top_items, wired_top)
        for item_id in visible_ids
        if isinstance(raw_top_items.get(item_id), dict)
    }
    page["item_order"] = [
        str(item_id) for item_id in raw_top_order if str(item_id) in visible_ids
    ]
    page["turns"] = filtered_turns(snapshot.get("turns"))
    page["artifacts"] = {}
    page["seen_event_ids"] = []
    # Serialized bytes of the selected items, the quantity the budget bounds. The
    # page also carries a few metadata keys, so this under-reports the exact wire
    # size; the budget leaves ample headroom under the client cap for them.
    page_bytes = sum(_item_bytes(entry[3]) for entry in selected)
    page["history_page"] = {
        "char_limit": char_limit,
        "character_count": character_count,
        "byte_limit": byte_limit,
        "byte_count": page_bytes,
        "turn_limit": turn_limit,
        "turn_count": len({entry[4] or f"item:{entry[3]}" for entry in selected}),
        "item_count": len(visible_ids),
        "total_items": total_items,
        "has_more": has_more,
        "next_before_item_id": selected[0][3] if has_more and selected else None,
        "next_before_seq": earliest_seq if has_more else None,
    }
    return page


def _page_item_byte_budget(page_bytes: int) -> int:
    """Read budget for one conversation page: a small multiple of its wire cap.

    The page itself is capped at ``page_bytes``, so reading a few times that is
    enough to fill it (the extra absorbs items the selector skips) while keeping
    the read bounded no matter how long the thread is.
    """
    return max(2 * 1024 * 1024, min(16 * 1024 * 1024, int(page_bytes) * 3))
