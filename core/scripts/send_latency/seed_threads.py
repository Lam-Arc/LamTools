"""Seed conversations at three sizes through the real persistence layer.

The send-latency harness needs threads that look like the ones the desktop app
actually produces: user turns, assistant text, thinking blocks, tool calls with
long results, usage records and terminal statuses. Replaying the same app events
the kernel writes (``turn/accepted`` + ``item/started`` + ``core/runItem``)
through ``AppPersistenceHost.append_batch`` keeps the item rows, the metadata
row and the event journal in exactly the shape production leaves them.

Usage:
    python core/scripts/send_latency/seed_threads.py --db <core.db> --size 20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

CORE_SRC = Path(__file__).resolve().parents[2] / "src"
if str(CORE_SRC) not in sys.path:
    sys.path.insert(0, str(CORE_SRC))

from lamtools_core.app.core_db import open_core_app_db  # noqa: E402
from lamtools_core.app.event_store import AppEventInput  # noqa: E402
from lamtools_core.app.turn_acceptance import build_turn_acceptance_plan  # noqa: E402
from lamtools_core.event import RunItemEvent  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

# A realistic turn produces 6-8 items. The per-turn mix below keeps the three
# message kinds the report asks for (plain text, long text, tool traffic).
ITEMS_PER_TURN = 7

_LONG_TEXT = (
    "这一段是助手的长回复正文，用来模拟真实会话里动辄几千字的分析段落。"
    "排查问题时它会把读到的结构、可疑点、验证方式和下一步动作完整写出来。"
) * 6

_TOOL_OUTPUT = (
    "[command] ls -la E:/LamTools/core/src/lamtools_core\n"
    "[exit_code: 0]\ndrwxr-xr-x 1 Administrator 197121 0 Nov  2 19:28 app\n"
    "drwxr-xr-x 1 Administrator 197121 0 Nov  2 19:28 event\n"
    "drwxr-xr-x 1 Administrator 197121 0 Nov  2 19:28 turn\n"
) * 24


def _turn_items(thread_id: str, turn_id: str, index: int) -> list[RunItemEvent]:
    """The runtime facts one turn writes, in kernel order."""

    items: list[RunItemEvent] = [
        RunItemEvent(
            kind="thinking",
            thread_id=thread_id,
            event_id=f"{turn_id}:reasoning",
            run_id=turn_id,
            turn_id=turn_id,
            item_id=f"{turn_id}:response-0:reasoning",
            status="completed",
            payload={"type": "reasoning", "content": f"第 {index} 轮的思考内容。" * 12},
        ),
        RunItemEvent(
            kind="message",
            thread_id=thread_id,
            event_id=f"{turn_id}:text",
            run_id=turn_id,
            turn_id=turn_id,
            item_id=f"{turn_id}:response-0:text",
            status="completed",
            payload={
                "type": "agentMessage",
                "content": f"第 {index} 轮答复：{_LONG_TEXT}",
                "final_response": False,
                "has_tool_calls": True,
            },
        ),
        RunItemEvent(
            kind="tool_call",
            thread_id=thread_id,
            event_id=f"{turn_id}:call0",
            run_id=turn_id,
            turn_id=turn_id,
            item_id=f"{thread_id}:{turn_id}:call_00_tool",
            status="running",
            payload={
                "type": "dynamicToolCall",
                "tool_name": "run_command",
                "arguments": {"command": "ls -la E:/LamTools/core"},
                "summary": "run_command",
                "input_preview": {"command": "ls -la E:/LamTools/core"},
            },
        ),
        RunItemEvent(
            kind="tool_result",
            thread_id=thread_id,
            event_id=f"{turn_id}:call0:result",
            run_id=turn_id,
            turn_id=turn_id,
            item_id=f"{thread_id}:{turn_id}:call_00_tool",
            status="completed",
            payload={
                "type": "dynamicToolCall",
                "tool_name": "run_command",
                "arguments": {"command": "ls -la E:/LamTools/core"},
                "summary": "run_command",
                "message": "",
                "delta": _TOOL_OUTPUT,
                "tool_result": _TOOL_OUTPUT,
                "replace": True,
                "metadata": {},
                "status": "completed",
                "error": None,
            },
        ),
        RunItemEvent(
            kind="tool_call",
            thread_id=thread_id,
            event_id=f"{turn_id}:call1",
            run_id=turn_id,
            turn_id=turn_id,
            item_id=f"{thread_id}:{turn_id}:call_01_tool",
            status="running",
            payload={
                "type": "dynamicToolCall",
                "tool_name": "read_file",
                "arguments": {"path": "core/src/lamtools_core/app/snapshot_store.py"},
                "summary": "read_file",
            },
        ),
        RunItemEvent(
            kind="tool_result",
            thread_id=thread_id,
            event_id=f"{turn_id}:call1:result",
            run_id=turn_id,
            turn_id=turn_id,
            item_id=f"{thread_id}:{turn_id}:call_01_tool",
            status="completed",
            payload={
                "type": "dynamicToolCall",
                "tool_name": "read_file",
                "arguments": {"path": "core/src/lamtools_core/app/snapshot_store.py"},
                "summary": "read_file",
                "message": "",
                "delta": _TOOL_OUTPUT[:4000],
                "tool_result": _TOOL_OUTPUT[:4000],
                "replace": True,
                "metadata": {},
                "status": "completed",
                "error": None,
            },
        ),
        RunItemEvent(
            kind="usage",
            thread_id=thread_id,
            event_id=f"{turn_id}:usage",
            run_id=turn_id,
            turn_id=turn_id,
            item_id=f"{turn_id}:usage",
            status="running",
            usage={
                "input_tokens": 12_000 + index,
                "output_tokens": 900,
                "total_tokens": 12_900 + index,
                "cached_input_tokens": 6_000,
            },
            payload={"type": "turn", "runtime_metrics": {"input_tokens": 12_000 + index}},
        ),
    ]
    return items


async def seed(
    db_path: Path,
    thread_id: str,
    turns: int,
    *,
    title: str,
    work_root: str,
) -> dict[str, int]:
    db = await open_core_app_db(db_path)
    project = str(Path(work_root).resolve())

    async def append(app_events, run_items):
        async def write(session):
            return await db.persistence.append_batch(
                session, app_events=app_events, run_item_events=run_items
            )

        return await db.persistence.write(write)

    await append(
        [AppEventInput(
            thread_id=thread_id,
            method="thread/started",
            payload={"status": "idle", "member_id": "default", "title": title},
        )],
        [],
    )

    for index in range(turns):
        turn_id = f"{thread_id}:turn:{index:06d}"
        user_item_id = f"{turn_id}:user"
        input_items = [{
            "type": "text",
            "text": f"第 {index} 条用户消息：帮我看一下这个模块的发送链路。",
        }]
        if index % 11 == 0:
            # Attachment metadata on a realistic minority of user messages.
            input_items.append({
                "type": "attachment",
                "attachment_id": f"att_{index:04d}",
                "name": f"screenshot-{index}.png",
                "mime_type": "image/png",
                "size_bytes": 184_320,
            })
        plan = build_turn_acceptance_plan(
            thread_id=thread_id,
            turn_id=turn_id,
            user_item_id=user_item_id,
            client_message_id=f"seed-{turn_id}",
            input_items=input_items,
            work_root=project,
            turn_payload_extra={
                "runtime_snapshot": {
                    "permission_preset": "ask",
                    "model_id": "stub-chat",
                },
                "duration_ms": 1_500 + index,
            },
            include_turn_status=True,
        )
        items = _turn_items(thread_id, turn_id, index)
        items.append(RunItemEvent(
            kind="status",
            thread_id=thread_id,
            event_id=f"{turn_id}:terminal",
            run_id=turn_id,
            turn_id=turn_id,
            item_id=f"{turn_id}:terminal",
            status="completed",
            payload={"type": "turn", "status": "completed", "duration_ms": 1_500 + index},
        ))
        await append(
            [
                AppEventInput(
                    thread_id=thread_id,
                    method=plan.turn_accepted.method,
                    payload=plan.turn_accepted.payload,
                    turn_id=turn_id,
                    client_message_id=plan.turn_accepted.client_message_id,
                ),
                AppEventInput(
                    thread_id=thread_id,
                    method=plan.user_item.method,
                    payload=plan.user_item.payload,
                    turn_id=turn_id,
                    item_id=user_item_id,
                    client_message_id=plan.user_item.client_message_id,
                ),
            ],
            items,
        )

    # The session record the runtime reads is derived from the snapshot row's
    # session block, so the project root has to live there too: the runtime
    # refuses a turn whose session project is missing or non-canonical.
    async def stamp_project(session):
        row = await session.get(db.snapshot_store.snapshot_model, thread_id)
        state = dict(row.snapshot_json or {})
        block = dict(state.get("session") or {})
        block["member_id"] = block.get("member_id") or "core"
        block["title"] = block.get("title") or title
        block["metadata"] = {
            **dict(block.get("metadata") or {}),
            "work_root": project,
            "execution_directory": project,
        }
        state["session"] = block
        row.snapshot_json = state
        flag_modified(row, "snapshot_json")
        await session.flush()
        return state

    await db.persistence.write(stamp_project)

    # Force the same projection path the app uses, then report what landed.
    async def load(session):
        return await db.snapshot_store.load(session, thread_id)

    state = await db.persistence.write(load)
    item_count = len((state.get("core") or {}).get("item_order") or [])
    async with db.session_factory() as session:
        await session.rollback()
    await db.close()
    return {"turns": turns, "items": item_count}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--turns", type=int, required=True)
    parser.add_argument("--title", default="perf seed")
    parser.add_argument("--work-root", default=str(Path.cwd()))
    args = parser.parse_args()
    result = asyncio.run(seed(
        Path(args.db),
        args.thread_id,
        args.turns,
        title=args.title,
        work_root=args.work_root,
    ))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
