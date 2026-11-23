"""Assistant display items written straight into a thread.

user:“让「写进会话」真的能看见：补 item 写入端点（或投影兼容层）”+(界面气泡
只从 ``core.items`` 组装，``POST /sessions/{id}/messages`` 只写 messages 表，
于是出现「写得进、看不见」。这个模块提供真正的写入侧：把一条助手展示内容变成
真实 turn 用的同一套 RunItemEvent，交给 AppPersistenceHost 做快照投影
（core.items + item_order），再用 live hub 广播，界面立即出现气泡。)

user:“行为：写 core.items + item_order，并通过现有 live 通道广播 item 事件
（复用真实 turn 用的同一套投影与广播路径，别另造一套）”+(所以这里不碰
messages 表、不建 user turn、不触发模型运行：只追加 runItem 事件。)

user:“严格校验：只允许 role='assistant' 的展示类 kind，拒绝工具调用与执行类；
单项与总量大小上限；id 由服务端生成并稳定”+(校验和 id 生成都在本模块内，路由
只负责搬运。)

user:“幂等：支持 client_item_id，重复提交同 id 不重复插入”+(client_item_id
决定 turn_id / item_id，重复提交先查库，命中就原样回执不重复插入。)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from lamtools_core.event import RunItemEvent

# ---------------------------------------------------------------------------
# Wire contract
# ---------------------------------------------------------------------------

#: 只允许助手展示类。ch̶a̶r̶t̶/mermaid/interactive-html/writing 在真实 turn 里不是
#: 独立条目类型，而是 agentMessage 正文里的围栏代码块（UI 由 MarkdownRenderer
#: 渲染）。这里接受它们作为「part 的语义类型」，落库时展开成同一种 agentMessage，
#: 存储格式与真实 turn 完全一致。
DISPLAY_ITEM_KINDS = frozenset(
    {"text", "markdown", "message", "chart", "mermaid", "interactive-html", "writing", "artifact"}
)

#: 明确拒绝的执行类 kind：它们代表工具调用、审批、状态机或用户输入，写入端点
#: 不接受（否则外部调用者能伪造工具执行记录和审批卡）。
EXECUTION_ITEM_KINDS = frozenset(
    {
        "tool_call",
        "tool_result",
        "commandExecution",
        "dynamicToolCall",
        "fileChange",
        "serverRequest",
        "approval_request",
        "approval_response",
        "interaction_update",
        "status",
        "error",
        "thinking",
        "reasoning",
        "usage",
        "model_phase",
        "userMessage",
        "systemMessage",
        "questionGroup",
        "plan",
        "handoff",
        "verification",
        "subAgents",
    }
)

ALLOWED_ROLES = frozenset({"assistant"})

MAX_ITEMS = 50
MAX_PART_CHARS = 200_000
MAX_ITEM_CHARS = 400_000
MAX_TOTAL_CHARS = 1_000_000

#: item_id 里的标签段：与真实 turn 的 ``<session>:turn:<run>`` 明确区分。
IMPORT_TURN_MARKER = ":turn:import:"
ITEM_ID_MARKER = ":item:"


class SessionItemsError(ValueError):
    """A rejected item write. Carries the HTTP status the route should use."""

    def __init__(self, message: str, *, status_code: int = 422, code: str = "INVALID_ITEM") -> None:
        super().__init__(message)
        self.message = str(message)
        self.status_code = int(status_code)
        self.code = str(code)

    @property
    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


def _digest(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _require_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise SessionItemsError(f"{field} 必须是字符串")
    return value


def _fence(name: str, body: str, *, attrs: str = "") -> str:
    return f"```{name}{attrs}\n{body.rstrip()}\n```"


def _chart_source(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = _require_text(value, field="chart.source")
    try:
        json.loads(text)
    except ValueError as exc:  # noqa: PERF203 - 校验失败必须给出明确原因
        raise SessionItemsError("chart.source 不是合法 JSON，界面无法渲染图表") from exc
    return text


def _writing_attrs(part: dict[str, Any]) -> str:
    attrs: list[str] = []
    variant = part.get("variant")
    if isinstance(variant, str) and variant.strip():
        attrs.append(f'variant="{variant.strip()}"')
    title = part.get("title")
    if isinstance(title, str) and title.strip():
        attrs.append(f'title="{title.strip()}"')
    subject = part.get("subject")
    if isinstance(subject, str) and subject.strip():
        attrs.append(f'subject="{subject.strip()}"')
    return ("{" + " ".join(attrs) + "}") if attrs else ""


def _render_part(part: Any) -> str:
    """One accepted part → the markdown a real turn would have streamed."""
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        raise SessionItemsError("parts 里的每一项必须是对象或字符串")
    kind = str(part.get("type") or part.get("kind") or "text").strip().lower()
    if kind in {"text", "markdown"}:
        return _require_text(part.get("text", ""), field="part.text")
    if kind == "chart":
        return _fence("chart", _chart_source(part.get("source", part.get("text", ""))))
    if kind == "mermaid":
        return _fence("mermaid", _require_text(part.get("source", part.get("text", "")), field="mermaid.source"))
    if kind in {"interactive-html", "interactive_html", "html"}:
        return _fence(
            "interactive-html",
            _require_text(part.get("source", part.get("text", "")), field="interactive-html.source"),
        )
    if kind == "writing":
        return _fence(
            "writing",
            _require_text(part.get("source", part.get("text", "")), field="writing.source"),
            attrs=_writing_attrs(part),
        )
    raise SessionItemsError(f"不支持的 part 类型: {kind}")


def _item_artifacts(item: dict[str, Any], parts: list[Any]) -> list[dict[str, Any]]:
    """Artifact parts keep the real artifact storage shape (item.artifacts)."""
    raw: list[Any] = []
    if isinstance(item.get("artifacts"), list):
        raw.extend(item["artifacts"])
    for part in parts:
        if isinstance(part, dict) and str(part.get("type") or "") == "artifact":
            raw.append(part)
    artifacts: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise SessionItemsError("artifact 必须是对象")
        artifact = dict(entry)
        artifact.pop("type", None)
        artifact.setdefault("artifact_id", f"artifact-{uuid.uuid4().hex[:16]}")
        artifacts.append(artifact)
    return artifacts


def normalize_session_items(items: Any) -> list[dict[str, Any]]:
    """Validate the request items and collapse each one into what gets stored."""
    if not isinstance(items, list) or not items:
        raise SessionItemsError("items 不能为空")
    if len(items) > MAX_ITEMS:
        raise SessionItemsError(f"items 最多 {MAX_ITEMS} 条")

    normalized: list[dict[str, Any]] = []
    total_chars = 0
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise SessionItemsError(f"items[{index}] 必须是对象")
        role = str(raw.get("role") or "assistant").strip()
        if role not in ALLOWED_ROLES:
            raise SessionItemsError(
                f"items[{index}].role 只允许 assistant（用户输入请走 /messages 或 turn.start）"
            )
        kind = str(raw.get("kind") or "text").strip()
        if kind in EXECUTION_ITEM_KINDS:
            raise SessionItemsError(
                f"items[{index}].kind={kind} 是执行/工具类，写入端点不接受"
            )
        if kind not in DISPLAY_ITEM_KINDS:
            raise SessionItemsError(
                f"items[{index}].kind={kind} 不受支持，允许: {sorted(DISPLAY_ITEM_KINDS)}"
            )
        parts = raw.get("parts")
        if parts is None:
            parts = []
        if not isinstance(parts, list):
            raise SessionItemsError(f"items[{index}].parts 必须是数组")
        if not parts and not raw.get("artifacts"):
            raise SessionItemsError(f"items[{index}].parts 不能为空")

        pieces: list[str] = []
        for part_index, part in enumerate(parts):
            rendered = _render_part(part)
            if len(rendered) > MAX_PART_CHARS:
                raise SessionItemsError(
                    f"items[{index}].parts[{part_index}] 超过 {MAX_PART_CHARS} 字符"
                )
            if rendered:
                pieces.append(rendered)
        markdown = "\n\n".join(piece for piece in pieces if piece.strip())
        if len(markdown) > MAX_ITEM_CHARS:
            raise SessionItemsError(f"items[{index}] 超过 {MAX_ITEM_CHARS} 字符")
        total_chars += len(markdown)
        if total_chars > MAX_TOTAL_CHARS:
            raise SessionItemsError(f"本次写入总量超过 {MAX_TOTAL_CHARS} 字符")

        artifacts = _item_artifacts(raw, parts)
        if not markdown and not artifacts:
            raise SessionItemsError(f"items[{index}] 没有任何可展示内容")
        normalized.append(
            {
                "kind": kind,
                "markdown": markdown,
                "artifacts": artifacts,
                "client_item_id": str(raw.get("client_item_id") or "").strip(),
                "index": index,
            }
        )
    return normalized


def build_item_plan(
    thread_id: str,
    items: list[dict[str, Any]],
    *,
    client_item_id: str = "",
    turn_id: str = "",
) -> dict[str, Any]:
    """Resolve the turn id and stable item ids for one write.

    Ids are derived from the caller's keys, so a retried submission addresses the
    same rows instead of appending duplicates. Without keys the ids are random
    (a genuinely new write each call).
    """
    key = client_item_id.strip()
    if turn_id.strip():
        resolved_turn_id = turn_id.strip()
    elif key:
        resolved_turn_id = f"{thread_id}{IMPORT_TURN_MARKER}{_digest(key)}"
    else:
        resolved_turn_id = f"{thread_id}{IMPORT_TURN_MARKER}{uuid.uuid4().hex[:12]}"

    planned: list[dict[str, Any]] = []
    for position, item in enumerate(items):
        item_key = item.get("client_item_id") or ""
        if item_key:
            item_id = f"{resolved_turn_id}{ITEM_ID_MARKER}{_digest(item_key)}"
        elif key:
            # 同一个 client_item_id 重试时，按位置派生，位置与内容都是确定的。
            item_id = f"{resolved_turn_id}{ITEM_ID_MARKER}{_digest(f'{key}:{position}')}"
        else:
            item_id = f"{resolved_turn_id}{ITEM_ID_MARKER}{uuid.uuid4().hex[:12]}"
        planned.append({**item, "item_id": item_id})
    return {"turn_id": resolved_turn_id, "items": planned, "idempotency_key": key}


def build_run_item_events(
    thread_id: str,
    plan: dict[str, Any],
    *,
    source: str = "api.items",
) -> list[RunItemEvent]:
    """Project one write into the canonical event stream.

    A message item plus (optionally) artifact items, then a turn ``status``
    event so the turn this write created reads ``completed`` right away — a turn
    left at ``running`` would pin the whole session as busy and block sending.
    """
    turn_id = plan["turn_id"]
    events: list[RunItemEvent] = []
    for item in plan["items"]:
        item_id = item["item_id"]
        markdown = item["markdown"]
        if markdown:
            events.append(
                RunItemEvent(
                    kind="message",
                    thread_id=thread_id,
                    turn_id=turn_id,
                    item_id=item_id,
                    status="completed",
                    source=source,
                    payload={
                        "type": "agentMessage",
                        "content": markdown,
                        "metadata": {
                            "origin": "api.items",
                            "api_item_kind": item["kind"],
                            **({"client_item_id": plan["idempotency_key"]} if plan["idempotency_key"] else {}),
                        },
                    },
                )
            )
        artifacts = item.get("artifacts") or []
        if artifacts:
            events.append(
                RunItemEvent(
                    kind="artifact",
                    thread_id=thread_id,
                    turn_id=turn_id,
                    item_id=f"{item_id}:artifact" if markdown else item_id,
                    status="completed",
                    source=source,
                    payload={"type": "artifact"},
                    artifacts=artifacts,
                )
            )
    events.append(
        RunItemEvent(
            kind="status",
            thread_id=thread_id,
            turn_id=turn_id,
            status="completed",
            source=source,
            payload={"status": "completed", "type": "runtime"},
        )
    )
    return events


# ---------------------------------------------------------------------------
# Read-side guards (cheap queries, never a whole-thread load)
# ---------------------------------------------------------------------------


async def _existing_item_ids(
    session_factory: Any,
    snapshot_store: Any,
    thread_id: str,
    item_ids: list[str],
) -> set[str]:
    model = getattr(snapshot_store, "item_model", None)
    if session_factory is None or model is None or not item_ids:
        return set()
    from sqlalchemy import select

    async with session_factory() as db:
        result = await db.execute(
            select(model.item_id).where(
                model.thread_id == thread_id,
                model.item_id.in_(item_ids),
            )
        )
        return {str(row[0]) for row in result}


async def _active_turn_ids(
    session_factory: Any,
    snapshot_store: Any,
    thread_id: str,
) -> list[str]:
    """Turns the runtime still owns. Writing next to one would be ambiguous."""
    loader = getattr(snapshot_store, "load_metadata", None)
    if session_factory is None or not callable(loader):
        return []
    async with session_factory() as db:
        meta = await loader(db, thread_id)
    if not isinstance(meta, dict):
        return []
    core = meta.get("core") if isinstance(meta.get("core"), dict) else {}
    turns: dict[str, Any] = {}
    for container in (meta.get("turns"), core.get("turns")):
        if isinstance(container, dict):
            turns.update(container)
    active: list[str] = []
    for turn_id, turn in turns.items():
        if not isinstance(turn, dict):
            continue
        if str(turn.get("status") or "") in {"running", "waiting", "interrupting"}:
            active.append(str(turn.get("turn_id") or turn_id))
    return active


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    """The entry shape both the fresh write and the idempotent retry return."""
    return {
        "item_id": item["item_id"],
        "kind": item["kind"],
        "type": "agentMessage",
        "content_chars": len(item.get("markdown") or ""),
        "artifacts": len(item.get("artifacts") or []),
    }


async def write_session_items(
    *,
    thread_id: str,
    items: Any,
    persistence: Any,
    hub: Any,
    session_factory: Any = None,
    client_item_id: str = "",
    turn_id: str = "",
    source: str = "api.items",
) -> dict[str, Any]:
    """Validate, project and broadcast one assistant item write.

    Nothing here starts a model run, creates a user turn or touches the
    ``messages`` table: the only durable effects are runItem event rows, the
    thread snapshot rows they project onto, and the live notifications.
    """
    normalized = normalize_session_items(items)
    plan = build_item_plan(
        thread_id,
        normalized,
        client_item_id=client_item_id,
        turn_id=turn_id,
    )
    snapshot_store = getattr(persistence, "snapshot_store", None)
    planned_ids = [item["item_id"] for item in plan["items"]]

    existing = await _existing_item_ids(session_factory, snapshot_store, thread_id, planned_ids)
    if existing and existing >= set(planned_ids):
        # user:“幂等：支持 client_item_id，重复提交同 id 不重复插入”+(命中就回执，
        # 不再追加事件；调用方据此知道这次是重试。)
        return {
            "thread_id": thread_id,
            "turn_id": plan["turn_id"],
            "items": [_public_item(item) for item in plan["items"]],
            "duplicated": True,
        }

    if not turn_id:
        active = await _active_turn_ids(session_factory, snapshot_store, thread_id)
        if active:
            raise SessionItemsError(
                "会话有正在运行的回合，写入助手条目会和它的过程时间线冲突；等这一轮结束再写",
                status_code=409,
                code="SESSION_BUSY",
            )

    events = build_run_item_events(thread_id, plan, source=source)
    envelopes = await persistence.append_batch_atomic(run_item_events=events)
    for envelope in envelopes or []:
        publish = getattr(hub, "publish", None)
        if callable(publish):
            await publish(envelope)

    return {
        "thread_id": thread_id,
        "turn_id": plan["turn_id"],
        "items": [_public_item(item) for item in plan["items"]],
        "duplicated": False,
        "events": [envelope.to_dict() for envelope in envelopes or []],
    }


__all__ = [
    "ALLOWED_ROLES",
    "DISPLAY_ITEM_KINDS",
    "EXECUTION_ITEM_KINDS",
    "SessionItemsError",
    "build_item_plan",
    "build_run_item_events",
    "normalize_session_items",
    "write_session_items",
]
