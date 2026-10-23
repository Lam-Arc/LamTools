"""Canonical thread snapshot reducer.

The snapshot is the recoverable display state derived from Core ``RunItemEvent``
facts. Product members can project domain labels around it, but the reducer is
member-neutral and idempotent.
"""

# 用户要求原文（本次决策池修复，按发送顺序）：
#
# 0. “卡片点完之后，没有立马消失，我又再点了一次。有没有出错我不确定，自己查去”
# 1. “。继续查，直接查日志。为什么这次又在一次提问中出现了两张卡片？，一张带
#    选项 另一张不带选项，问的是同一个问题，你把设计考虑清楚了之后再做修改，
#    不要留下 bug 好不好”
# 2. “以后开发者模式，你把前端的 console 一块儿给留存下来。方便你随时查”
# 3. “。把边界情况考虑清楚，然后告诉我，这个东西不应该是前端显示池子内拥有的
#    东西，，前端显示的更新时间应当是池子内信息发生变动的时候，当一个卡片或请求
#    被回答完毕之后，这个东西被丢出池子，然后池子顺位补上下一个。这个为什么会出现
#    广播两次这件事儿呢？”
# 4. “想清楚再动手，池子的持久化做了吗”
# 5. “你接下来的所有任务，就是根据我的自然语言去写代码，不要增加额外的逻辑。
#    不要新增我没有说过的东西，你应该替我思考所有的，枚举清楚所有的边界情况来
#    攻击我的逻辑漏洞。你可以随时向我提出质疑，但是绝对不能用我没有说过的话去干”
# 6. “你应该在做每一次工具调用之前，先用一句话说清楚你要干什么”
# 7. “我给你发的所有消息的原文记进注释里了吗”
#
# 这些要求落到本模块的规则：一次出现只有一个作者；回答即终态并从池子移除；
# 重复或迟到的事件不能改写终态、不能擦掉选项；池子的事实源是数据库行。

from __future__ import annotations

import bisect
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from lamtools_core.event import RunItemEvent
from lamtools_core.turn.model import TERMINAL_TURN_STATUSES

TERMINAL_STATUSES = TERMINAL_TURN_STATUSES

# Fields a live approval card must keep when a duplicate/ending event restates
# it with an empty value. `options: []` from a waiting/replay record used to
# overwrite the real choices and leave the card with free input only.
_SERVER_REQUEST_KINDS = frozenset(
    {"approval_request", "approval_response", "interaction_update"}
)
_APPROVAL_REQUEST_FACTS = frozenset(
    {
        "request_id",
        "tool_call_id",
        "tool_name",
        "kind",
        "message",
        "options",
        "context",
        "metadata",
        "sub_agent",
    }
)


def empty_thread_snapshot(thread_id: str) -> dict[str, Any]:
    return {
        "thread_id": thread_id,
        "snapshot_seq": 0,
        "seen_event_ids": [],
        "turns": {},
        "items": {},
        "item_order": [],
        "requests": {},
        "artifacts": {},
        "deleted_agents": {},
        "status": "idle",
    }


def apply_run_item_event(state: dict[str, Any] | None, event: RunItemEvent) -> dict[str, Any]:
    next_state = deepcopy(state) if state else empty_thread_snapshot(event.thread_id)
    return apply_run_item_event_in_place(next_state, event)


def apply_run_item_event_in_place(state: dict[str, Any], event: RunItemEvent) -> dict[str, Any]:
    seen = set(state.get("seen_event_ids") or [])
    if event.event_id in seen:
        return state

    state["thread_id"] = event.thread_id
    state["snapshot_seq"] = max(
        int(state.get("snapshot_seq") or 0),
        int(event.seq or 0),
    )
    if event.seq == 0:
        state["snapshot_seq"] = int(state.get("snapshot_seq") or 0) + 1

    state.setdefault("seen_event_ids", []).append(event.event_id)
    if len(state["seen_event_ids"]) > 2000:
        state["seen_event_ids"] = state["seen_event_ids"][-2000:]

    if event.kind == "status":
        status = event.payload.get("status") or event.status
        existing_turn = (state.get("turns") or {}).get(event.turn_id) if event.turn_id else None
        existing_status = str(existing_turn.get("status") or "") if isinstance(existing_turn, dict) else ""
        turn = _upsert_turn(state, event)
        _apply_turn_metrics(turn, event, replace=False)
        if existing_status in TERMINAL_STATUSES and status != existing_status:
            if turn is not None and event.usage and not _is_context_metrics_event(event):
                turn["usage"] = {**dict(turn.get("usage") or {}), **event.usage}
            _recompute_thread_status(state)
            return state
        if status:
            state["status"] = status
        if turn is not None and status:
            turn["status"] = status
        if turn is not None and event.usage and not _is_context_metrics_event(event):
            turn["usage"] = {**dict(turn.get("usage") or {}), **event.usage}
        duration_ms = event.payload.get("duration_ms")
        if (
            turn is not None
            and isinstance(duration_ms, (int, float))
            and not isinstance(duration_ms, bool)
        ):
            turn["duration_ms"] = max(0, round(duration_ms))
        if status in {"failed", "cancelled", "error"} and (
            event.payload.get("message") or event.payload.get("raw_end_reason")
        ):
            item = _upsert_item(state, event)
            if turn is not None and item["item_id"] not in turn.setdefault("items", []):
                turn["items"].append(item["item_id"])
            state["last_error"] = dict(event.payload)
        if turn is not None and status in TERMINAL_STATUSES:
            _close_turn_items(state, turn, status)
            reconcile_terminal_requests(state)
        return state

    if event.kind == "interaction_update":
        _apply_interaction_update(state, event)
        _recompute_thread_status(state)
        return state

    if event.kind == "approval_response":
        _apply_approval_response(state, event)
        nested_child = bool(event.parent_item_id) or isinstance(
            (event.payload or {}).get("sub_agent"), dict
        )
        # The answer closes the visible row in the transcript as well as the
        # request. The live client already flipped this item to completed; the
        # stored snapshot used to keep it `waiting` until the tool result
        # arrived, so after a reload (or for a client that trusts the snapshot)
        # the answered card looked pending again for the whole continuation.
        item = _upsert_item(state, event)
        # Only an existing turn may be resumed by an answer. A response naming a
        # turn this thread never created must not invent one: the invented turn
        # stayed `running` forever (nothing owns it to close it) and pinned the
        # whole session to "running" after everything had finished (2026-10-14).
        turn = (state.get("turns") or {}).get(event.turn_id) if event.turn_id else None
        if isinstance(turn, dict):
            if event.item_id and event.item_id not in turn.setdefault("items", []):
                turn["items"].append(event.item_id)
            turn["last_kind"] = event.kind
            turn["last_seq"] = event.seq or state.get("snapshot_seq", 0)
            if event.run_id:
                turn["run_id"] = event.run_id
            if not nested_child and str(turn.get("status") or "") not in {"failed", "cancelled", "skipped", "paused"}:
                # Resolving a server request resumes the existing turn; it does
                # not complete that turn. A later lifecycle/status item owns
                # terminality. A *paused* turn is excluded: its run has already
                # ended, so reviving it left the session reading running with
                # nothing running, until the user terminated it by hand
                # (2026-10-14). A delegated member's answer belongs to the
                # member, never to the parent turn that happens to own the
                # timeline anchor.
                turn["status"] = "running"
        _recompute_thread_status(state)
        return state

    if event.kind == "usage":
        # `runtime.metrics` items carry session-cumulative context state and
        # flag `replace: true` — they are NOT per-call usage deltas. Keep them
        # in their own field so the UI can show context pressure without
        # poisoning provider-reported token usage.
        turn = _upsert_turn(state, event)
        if turn is None:
            return state
        if event.payload.get("replace") is True:
            if turn is not None and event.usage:
                if event.parent_item_id:
                    turn.setdefault("child_context_metrics", {})[event.parent_item_id] = dict(event.usage)
                else:
                    turn["context_metrics"] = dict(event.usage)
            return state
        if event.usage:
            calls = turn.setdefault("usage_calls", [])
            call = {"id": event.item_id or event.event_id, "seq": event.seq or state["snapshot_seq"],
                    "parent_item_id": event.parent_item_id, "usage": dict(event.usage)}
            existing = next((i for i, row in enumerate(calls) if row["id"] == call["id"]), None)
            if existing is None:
                calls.append(call)
            else:
                call["seq"] = calls[existing].get("seq", call["seq"])
                calls[existing] = call
            turn["usage"] = {}
            for row in calls:
                if not row.get("parent_item_id"):
                    turn["usage"] = _merge_dict_values(turn["usage"], row["usage"])
        return state

    if event.kind == "artifact" or event.artifacts:
        _apply_artifact(state, event)

    event_payload = event.payload if isinstance(event.payload, dict) else {}
    if event_payload.get("type") == "subAgentStatus":
        sub_agent = event_payload.get("sub_agent")
        if isinstance(sub_agent, dict) and str(sub_agent.get("status") or "") == "deleted":
            deleted = state.setdefault("deleted_agents", {})
            for key in (
                sub_agent.get("name"),
                sub_agent.get("agent"),
                sub_agent.get("session_id"),
                sub_agent.get("sub_session_id"),
            ):
                value = str(key or "").strip()
                if value:
                    deleted[value] = True

    existing_turn = (state.get("turns") or {}).get(event.turn_id) if event.turn_id else None
    terminal_turn_status = (
        str(existing_turn.get("status") or "")
        if isinstance(existing_turn, dict)
        and str(existing_turn.get("status") or "") in TERMINAL_STATUSES
        else ""
    )
    # A sub-agent's timeline outlives the parent turn that started it: the parent
    # can end (the watchdog wakes it later) while the member keeps working. Such
    # items carry a parent_item_id and belong to the member, so the ended turn
    # must neither force them terminal nor re-open itself for them.
    nested_child = bool(event.parent_item_id) or isinstance(
        (event.payload or {}).get("sub_agent"), dict
    )
    # Ending is terminal for a request. A late duplicate approval_request (a
    # replayed event, or the parked run's waiting record) must never reopen a
    # card the user already answered: that produced a second, option-less card
    # asking the same question after the first one had been resolved.
    #
    # 用户要求（原文）：“卡片点完之后，没有立马消失”
    # 用户要求（原文）：“当一个卡片或请求被回答完毕之后，这个东西被丢出池子”
    if event.kind == "approval_request":
        request_id = str(
            event.payload.get("request_id") or event.item_id or event.event_id
        )
        existing_request = (state.get("requests") or {}).get(request_id)
        if isinstance(existing_request, dict) and str(
            existing_request.get("status") or ""
        ) in {"resolved", "cancelled", "expired"}:
            return state
    item = _upsert_item(state, event)
    if terminal_turn_status and not nested_child:
        item["status"] = terminal_turn_status
        turn = _upsert_turn(state, event)
        if event.item_id and turn is not None and event.item_id not in turn.setdefault("items", []):
            turn["items"].append(event.item_id)
        _recompute_thread_status(state)
        return state
    if event.kind == "approval_request":
        item["status"] = "waiting"
        if not nested_child:
            state["status"] = "waiting"
        request_id = str(event.payload.get("request_id") or event.item_id or event.event_id)
        requests = state.setdefault("requests", {})
        existing_record = requests.get(request_id)
        request_record = (
            dict(existing_record) if isinstance(existing_record, dict) else {}
        )
        for key, value in event.payload.items():
            if (
                key in _APPROVAL_REQUEST_FACTS
                and not value
                and request_record.get(key)
            ):
                continue
            request_record[key] = value
        request_record.update(
            {
                "request_id": request_id,
                "status": "open",
                "item_id": item["item_id"],
                "turn_id": event.turn_id,
            }
        )
        requests[request_id] = request_record
        # Compatibility alias: older clients and persisted tests address the
        # request by the provider tool-call id. The composite id is the routing
        # key; the alias is the same record and never a second request.
        tool_call_id = str(event.payload.get("tool_call_id") or "")
        if tool_call_id and tool_call_id != request_id:
            requests[tool_call_id] = request_record
    elif event.kind == "error":
        item["status"] = "failed"
        state["last_error"] = event.payload or {"message": item.get("content", "")}
        if _is_terminal_error_event(event):
            state["status"] = "failed"
    elif event.status == "waiting":
        item["status"] = "waiting"
        state["status"] = "waiting"
    elif event.status in TERMINAL_STATUSES:
        item["status"] = event.status
    else:
        item["status"] = event.status
        # A paused turn stays paused: an item the pause itself wrote (the
        # interrupted tool result that closes the cut step) is ordinary work
        # arriving late, not the turn running again.
        if event.turn_id and not nested_child and str(state.get("status") or "") != "paused":
            state["status"] = "running"

    turn = _upsert_turn(state, event)
    if event.item_id and turn is not None and event.item_id not in turn.setdefault("items", []):
        turn["items"].append(event.item_id)
    if turn is None:
        _recompute_thread_status(state)
        return state
    if event.kind == "approval_request":
        if not nested_child:
            turn["status"] = "waiting"
            state["status"] = "waiting"
    elif _is_turn_terminal_event(event):
        turn["status"] = event.status
        reconcile_terminal_requests(state)
        _recompute_thread_status(state)
    elif event.status == "waiting":
        turn["status"] = "waiting"
        state["status"] = "waiting"
    elif (
        event.turn_id
        and str(turn.get("status") or "") not in TERMINAL_STATUSES
        and str(turn.get("status") or "") != "paused"
    ):
        # Same rule for the turn itself: only a resume or a status event may
        # take a paused turn back to running.
        turn["status"] = "running"
        _recompute_thread_status(state)
    return state


def reduce_run_item_events(thread_id: str, events: list[RunItemEvent]) -> dict[str, Any]:
    state = empty_thread_snapshot(thread_id)
    for event in sorted(events, key=lambda item: (item.seq or 0, item.created_at_ms, item.event_id)):
        apply_run_item_event_in_place(state, event)
    return state


@runtime_checkable
class SnapshotStore(Protocol):
    def get(self, thread_id: str) -> dict[str, Any] | None: ...
    def save(self, snapshot: dict[str, Any]) -> None: ...


@dataclass
class InMemorySnapshotStore:
    _snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get(self, thread_id: str) -> dict[str, Any] | None:
        snapshot = self._snapshots.get(thread_id)
        return deepcopy(snapshot) if snapshot is not None else None

    def save(self, snapshot: dict[str, Any]) -> None:
        thread_id = str(snapshot.get("thread_id") or "")
        if not thread_id:
            raise ValueError("snapshot.thread_id is required")
        self._snapshots[thread_id] = deepcopy(snapshot)

    def apply(self, event: RunItemEvent) -> dict[str, Any]:
        snapshot = apply_run_item_event(self.get(event.thread_id), event)
        self.save(snapshot)
        return snapshot

    def clear(self) -> None:
        self._snapshots.clear()


def _upsert_turn(state: dict[str, Any], event: RunItemEvent) -> dict[str, Any] | None:
    if not event.turn_id:
        return None
    turn = state.setdefault("turns", {}).setdefault(
        event.turn_id,
        {"turn_id": event.turn_id, "status": "running", "items": []},
    )
    turn["last_kind"] = event.kind
    turn["last_seq"] = event.seq or state.get("snapshot_seq", 0)
    if event.run_id:
        turn["run_id"] = event.run_id
    return turn


def _close_turn_items(state: dict[str, Any], turn: dict[str, Any], status: str) -> None:
    items = state.get("items") or {}
    for item_id in turn.get("items") or []:
        item = items.get(item_id)
        if not isinstance(item, dict):
            continue
        # A sub-agent's timeline outlives the parent turn that started it: the
        # parent now ENDS while members still run (the watchdog wakes it later),
        # so the member's in-flight rows must keep their own status. Blanket-
        # completing them here would show a still-working member as finished,
        # and a still-waiting card as answered.
        if _is_sub_agent_child_item(item):
            continue
        if str(item.get("status") or "") not in TERMINAL_STATUSES:
            item["status"] = status


def is_sub_agent_child_item(item: dict[str, Any]) -> bool:
    """Whether an item belongs to a delegated member's timeline.

    Provenance: nested items carry the parent's delegated tool row as
    ``parent_item_id``; interactive requests additionally carry ``sub_agent`` in
    the payload. Either mark means the parent turn's terminal transition must
    leave the row alone.
    """
    if item.get("parent_item_id"):
        return True
    payload = item.get("payload")
    return isinstance(payload, dict) and isinstance(payload.get("sub_agent"), dict)


def _is_sub_agent_interaction_item(item: dict[str, Any]) -> bool:
    """Whether an item is a sub-agent's open interactive request.

    Provenance travels in the payload as ``sub_agent`` (the forwarding sink
    stamps it); an ``approval_request`` carrying it belongs to a delegated
    member, whose request lifecycle the parent turn's terminal transition must
    leave alone.
    """
    payload = item.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("sub_agent"), dict):
        return False
    kind = str(item.get("kind") or item.get("last_kind") or "")
    return kind == "approval_request" and str(item.get("status") or "") not in TERMINAL_STATUSES


def _is_turn_terminal_event(event: RunItemEvent) -> bool:
    if event.status not in TERMINAL_STATUSES:
        return False
    if event.kind == "error":
        return _is_terminal_error_event(event)
    # Item completion is not turn completion. Intermediate assistant text,
    # verification, and tool items may all complete before more work begins.
    # The dedicated turn status event owns successful terminality.
    return False


def _is_terminal_error_event(event: RunItemEvent) -> bool:
    payload_type = str(event.payload.get("type") or "").lower()
    if payload_type in {"runtime", "turn"}:
        return True
    runtime_phase = str((event.metadata or {}).get("runtime_phase") or "")
    if runtime_phase == "runtime.failed":
        return True
    return not event.item_id


def typed_input_parts_text(parts: list[Any]) -> str:
    """Flatten typed input parts (``[{"type": "text", "text": ...}]``) to text.

    Mirrors the client's concatenation, so a message body reads the same on the
    wire and in the durable record.  Only ``text`` members contribute; every
    part stays intact in the payload for readers that need the structure
    (attachments, typed inputs).
    """
    pieces: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            pieces.append(text)
    return "".join(pieces).strip()


def _upsert_item(state: dict[str, Any], event: RunItemEvent) -> dict[str, Any]:
    item_id = event.item_id or f"{event.turn_id or event.thread_id}:{event.kind}:{event.event_id}"
    existing_item = (state.get("items") or {}).get(item_id)
    # A duplicate approval_request is only a restatement while the item is
    # live. Once the card ended (tool_result/completed), it must not demote the
    # row back to waiting or turn it into a serverRequest again.
    if (
        event.kind == "approval_request"
        and isinstance(existing_item, dict)
        and str(existing_item.get("status") or "") in TERMINAL_STATUSES
    ):
        existing_item["last_seq"] = max(
            int(existing_item.get("last_seq") or 0), int(event.seq or 0)
        )
        return existing_item
    item = state.setdefault("items", {}).setdefault(
        item_id,
        {
            "item_id": item_id,
            "turn_id": event.turn_id,
            "parent_item_id": event.parent_item_id,
            "kind": event.kind,
            "content": "",
            "deltas": [],
            "status": event.status,
        },
    )
    if event.kind == "tool_result":
        item["kind"] = "tool_result"
    else:
        item["kind"] = item.get("kind") or event.kind
    item["last_kind"] = event.kind
    item["last_seq"] = event.seq or state.get("snapshot_seq", 0)
    item["status"] = event.status
    if event.payload:
        current_payload = item.setdefault("payload", {})
        for key, value in event.payload.items():
            # Identity/presentation facts are write-once for an open request:
            # a restated event with an empty field (notably `options: []`) must
            # not erase what the original card carried.
            if (
                event.kind in _SERVER_REQUEST_KINDS
                and key in _APPROVAL_REQUEST_FACTS
                and not value
                and current_payload.get(key)
            ):
                continue
            current_payload[key] = value
    if event.artifacts:
        item["artifacts"] = event.artifacts
    if event.usage:
        item["usage"] = _merge_dict_values(item.get("usage"), event.usage)

    delta = event.payload.get("delta")
    content = event.payload.get("content", event.payload.get("text"))
    if isinstance(delta, str):
        if event.payload.get("replace") is True:
            item["deltas"] = [delta]
            item["content"] = delta
        else:
            item.setdefault("deltas", []).append(delta)
            item["content"] = f"{item.get('content', '')}{delta}"
    elif isinstance(content, str):
        item["content"] = content
    elif isinstance(content, list):
        # userMessage items carry typed input parts; the mid-turn guidance
        # bubble is projected that way (`runtime.guidance_received`).  Keeping
        # the flat body in ``content`` as well means the durable record — and
        # every consumer that reads ``content`` instead of the payload — still
        # has the message text.
        text = typed_input_parts_text(content)
        if text:
            item["content"] = text

    item_seq = int(event.seq or 0)
    if item_id not in state.setdefault("item_order", []):
        # Record the first event's seq as the ordering anchor and insert the
        # item at the correct position right away. Deferred part events are
        # projected at the turn boundary (after runtime-projected tool
        # results), so appending would leave the turn's items out of order;
        # inserting by seq keeps item_order equal to production order without
        # any post-hoc reordering.
        item["seq"] = item_seq
        order = state["item_order"]
        # The store projects onto a partial item map (only the touched items
        # are loaded); it injects ``_item_seq_map`` (item_id -> first seq) so
        # the insertion position still reflects every item's anchor.
        seq_map = state.get("_item_seq_map") or {}
        items = state.get("items") or {}
        index = bisect.bisect_right(
            [
                int(
                    seq_map.get(iid)
                    or int((items.get(iid) or {}).get("seq") or 0)
                    or 0
                )
                for iid in order
            ],
            item_seq,
        )
        order.insert(index, item_id)
        if isinstance(seq_map, dict):
            seq_map[item_id] = item_seq
    elif "seq" not in item:
        item["seq"] = item_seq
    return item


def _apply_approval_response(state: dict[str, Any], event: RunItemEvent) -> None:
    request_id = str(event.payload.get("request_id") or event.item_id or "")
    if not request_id:
        return
    requests = state.setdefault("requests", {})
    request = requests.setdefault(request_id, {"request_id": request_id})
    for key, value in event.payload.items():
        if key in _APPROVAL_REQUEST_FACTS and not value and request.get(key):
            continue
        request[key] = value
    request["status"] = event.payload.get("status") or "resolved"
    # Keep the compatibility alias (provider tool-call id) in step with the
    # composite record. Both keys describe one request, never two.
    for key, candidate in requests.items():
        if key == request_id or not isinstance(candidate, dict):
            continue
        if str(candidate.get("request_id") or "") == request_id:
            for field, value in event.payload.items():
                if field in _APPROVAL_REQUEST_FACTS and not value and candidate.get(field):
                    continue
                candidate[field] = value
            candidate["status"] = request["status"]
    # Ending is terminal for the decision pool: the card never renders again.
    _remove_interaction_from_pools(state, request_id, event.payload)


def _interaction_matches(
    item: dict[str, Any], request_id: str, payload: dict[str, Any]
) -> bool:
    candidates = {
        request_id,
        str(payload.get("interaction_id") or ""),
        str(payload.get("tool_call_id") or ""),
    }
    return bool(
        {
            str(item.get("interaction_id") or ""),
            str(item.get("request_id") or ""),
            str(item.get("tool_call_id") or ""),
        }
        & candidates
    )


def _remove_interaction_from_pools(
    state: dict[str, Any], request_id: str, payload: dict[str, Any]
) -> None:
    for container in (state, state.get("core")):
        if not isinstance(container, dict):
            continue
        pool = container.get("interactions")
        if isinstance(pool, list):
            container["interactions"] = [
                item
                for item in pool
                if not (
                    isinstance(item, dict)
                    and _interaction_matches(item, request_id, payload)
                )
            ]


def _apply_interaction_update(state: dict[str, Any], event: RunItemEvent) -> None:
    """Appearing/processing is a pool upsert; the sequence never changes."""
    payload = dict(event.payload or {})
    interaction_id = str(
        payload.get("interaction_id")
        or payload.get("request_id")
        or event.item_id
        or ""
    )
    if not interaction_id:
        return
    terminal_request_status = {"resolved", "cancelled", "expired"}
    existing_requests = state.get("requests") or {}
    for key in (
        interaction_id,
        str(payload.get("request_id") or ""),
        str(payload.get("interaction_id") or ""),
    ):
        existing_request = existing_requests.get(key) if key else None
        if isinstance(existing_request, dict) and str(
            existing_request.get("status") or ""
        ) in terminal_request_status:
            # Ending is terminal for the pool too: a late appearing/processing
            # update must not resurrect a card that was already answered.
            return
    lifecycle = str(
        payload.get("state") or payload.get("lifecycle") or "appearing"
    )
    status = "processing" if lifecycle == "processing" else "open"
    item = {
        "interaction_id": interaction_id,
        "request_id": str(payload.get("request_id") or interaction_id),
        "kind": str(payload.get("kind") or "approval"),
        "status": status,
        "lifecycle": lifecycle,
        "decision_id": str(payload.get("decision_id") or ""),
        "sequence": int(payload.get("sequence") or 0),
        "tool_call_id": str(payload.get("tool_call_id") or ""),
        "turn_id": str(payload.get("turn_id") or ""),
        "title": str(payload.get("title") or ""),
        "options": list(payload.get("options") or []),
        "scope": str(payload.get("scope") or "main"),
        "agent_name": str(payload.get("agent_name") or ""),
        "agent_session_id": str(payload.get("agent_session_id") or ""),
        "delivered_by": str(payload.get("delivered_by") or "main"),
        "project_id": str(payload.get("project_id") or ""),
    }
    for container in (state, state.get("core")):
        if not isinstance(container, dict):
            continue
        pool = container.get("interactions")
        if not isinstance(pool, list):
            pool = []
            container["interactions"] = pool
        for index, existing in enumerate(pool):
            if isinstance(existing, dict) and _interaction_matches(
                existing, interaction_id, payload
            ):
                merged = {**existing, **item}
                if not item.get("options") and existing.get("options"):
                    merged["options"] = existing["options"]
                pool[index] = merged
                break
        else:
            pool.append(item)

    requests = state.setdefault("requests", {})
    request = requests.setdefault(
        item["request_id"], {"request_id": item["request_id"]}
    )
    # Monotonic: a late appearing update may not reopen a resolved request.
    if str(request.get("status") or "") not in {
        "resolved",
        "cancelled",
        "expired",
    }:
        request.update(payload)
        request["status"] = status


def _apply_artifact(state: dict[str, Any], event: RunItemEvent) -> None:
    artifacts = event.artifacts or ([event.payload] if event.payload else [])
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_id = str(artifact.get("artifact_id") or artifact.get("id") or event.item_id or event.event_id)
        # 登记表是索引不是仓库。事件带 artifacts 时，_upsert_item 已把完整
        # 副本（含 content 正文与 image_data_url）挂在条目上，登记表再存一份
        # 会让每张图、每段正文在快照里出现两次，装载、写回、同步全部陪跑。
        # 仅 payload 兜底（event.artifacts 为空）时保留 content：那时登记表
        # 可能是快照里唯一的正文副本。
        registry_copy = artifact
        metadata = artifact.get("metadata")
        drop_inline_image = isinstance(metadata, dict) and "image_data_url" in metadata
        drop_content = bool(event.artifacts) and "content" in artifact
        if drop_inline_image or drop_content:
            registry_copy = dict(artifact)
            if drop_inline_image:
                registry_copy["metadata"] = {
                    key: value for key, value in metadata.items() if key != "image_data_url"
                }
            if drop_content:
                registry_copy.pop("content", None)
        state.setdefault("artifacts", {})[artifact_id] = registry_copy


def _has_open_request(state: dict[str, Any]) -> bool:
    return any(
        isinstance(request, dict) and request.get("status") == "open"
        for request in (state.get("requests") or {}).values()
    )


def reconcile_terminal_requests(state: dict[str, Any]) -> dict[str, Any]:
    """Close stale server requests whose owning turn can no longer answer them."""
    turns = state.get("turns")
    requests = state.get("requests")
    if not isinstance(turns, dict) or not isinstance(requests, dict):
        return state
    terminal_statuses = {
        str(turn_id): str(turn.get("status") or "")
        for turn_id, turn in turns.items()
        if isinstance(turn, dict) and str(turn.get("status") or "") in TERMINAL_STATUSES
    }
    for request_id, request in list(requests.items()):
        if not isinstance(request, dict) or request.get("status") != "open":
            continue
        # A sub-agent's request is anchored to the parent turn for ordering, but
        # its lifecycle belongs to the sub-agent. The parent turn going terminal
        # must not close a card the child is still waiting on (the child's own
        # approval_response, or its close/interrupt, closes it).
        if isinstance(request.get("sub_agent"), dict):
            continue
        terminal_status = terminal_statuses.get(str(request.get("turn_id") or ""))
        if not terminal_status:
            continue
        requests[request_id] = {
            **request,
            "status": "cancelled" if terminal_status == "cancelled" else "resolved",
            "terminal_turn_status": terminal_status,
        }
    return state


def _latest_active_turn(state: dict[str, Any]) -> dict[str, Any] | None:
    turns = [
        turn for turn in (state.get("turns") or {}).values()
        if isinstance(turn, dict) and turn.get("status") in {"queued", "running", "waiting"}
    ]
    turns.sort(key=lambda item: int(item.get("last_seq") or 0), reverse=True)
    return turns[0] if turns else None


def _is_sub_agent_child_item(item: dict[str, Any]) -> bool:
    """Internal alias kept for the module's own call sites."""
    return is_sub_agent_child_item(item)


def recompute_thread_status(state: dict[str, Any]) -> None:
    # A paused turn owns the session until the user continues or terminates it.
    # It outranks an open request (a member waiting on a question keeps its card
    # answerable, but the session itself is paused, not waiting) and it is not
    # an active execution, so the runtime never reports it as "running" again.
    paused = any(
        isinstance(turn, dict) and str(turn.get("status") or "") == "paused"
        for turn in (state.get("turns") or {}).values()
    )
    if paused:
        state["status"] = "paused"
        return
    if _has_open_request(state):
        state["status"] = "waiting"
        return
    if _latest_active_turn(state) is not None:
        state["status"] = "running"
        return
    turns = [
        turn for turn in (state.get("turns") or {}).values()
        if isinstance(turn, dict)
    ]
    turns.sort(key=lambda item: int(item.get("last_seq") or 0), reverse=True)
    latest_status = str((turns[0] if turns else {}).get("status") or "")
    if latest_status == "completed":
        state["status"] = "completed"
    elif latest_status == "cancelled":
        state["status"] = "cancelled"
    elif latest_status == "failed":
        state["status"] = "failed"
    else:
        state["status"] = "idle"


def _recompute_thread_status(state: dict[str, Any]) -> None:
    """Internal alias kept for the module's own call sites."""
    recompute_thread_status(state)


def _merge_dict_values(current: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    result = dict(current or {})
    for key, value in incoming.items():
        if key == "cache_hit_rate":
            continue
        if isinstance(value, (int, float)) and isinstance(result.get(key), (int, float)):
            result[key] += value
        else:
            result[key] = value
    denominator = float(result.get("cache_reported_input_tokens") or 0)
    if "cached_tokens" in incoming:
        denominator += float(incoming.get("input_tokens") or incoming.get("prompt_tokens") or 0)
    if "cached_tokens" in incoming or "cache_reported_input_tokens" in result:
        result["cache_reported_input_tokens"] = denominator
    if denominator > 0:
        result["cache_hit_rate"] = min(1, float(result.get("cached_tokens") or 0) / denominator)
    else:
        result.pop("cache_hit_rate", None)
    return result


_CONTEXT_METRIC_KEYS = {
    "estimated_prompt_tokens",
    "estimatedPromptTokens",
    "context_tokens",
    "contextTokens",
    "context_window_tokens",
    "contextWindowTokens",
    "context_compaction_trigger_tokens",
    "contextCompactionTriggerTokens",
    "trigger_tokens",
    "triggerTokens",
    "context_compacted",
    "contextCompacted",
    "context_compaction_status",
    "context_tokens_before_compaction",
    "context_tokens_after_compaction",
    "context_messages_before_compaction",
    "context_messages_after_compaction",
    "steps_total",
    "model_id",
}


def _is_context_metrics_event(event: RunItemEvent) -> bool:
    # Provider usage events historically used the payload key
    # ``runtime_metrics`` as a transport envelope too.  That key alone does
    # not make the values context metrics; only terminal status events and
    # explicit replace-style runtime.metrics events do.
    if event.payload.get("replace") is True:
        return True
    if event.kind == "status" and event.payload.get("runtime_metrics") is not None:
        return True
    return bool(
        event.usage
        and any(key in event.usage for key in _CONTEXT_METRIC_KEYS)
    )


def _apply_turn_metrics(
    turn: dict[str, Any] | None,
    event: RunItemEvent,
    *,
    replace: bool,
) -> None:
    if turn is None or not event.usage or not _is_context_metrics_event(event):
        return
    if replace:
        turn["context_metrics"] = dict(event.usage)
    else:
        turn["context_metrics"] = {
            **dict(turn.get("context_metrics") or {}),
            **event.usage,
        }


__all__ = [
    "SnapshotStore",
    "InMemorySnapshotStore",
    "apply_run_item_event",
    "empty_thread_snapshot",
    "reconcile_terminal_requests",
    "reduce_run_item_events",
]
