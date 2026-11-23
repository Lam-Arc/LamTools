"""工具进度帧走可丢通道，终态/结果帧走可靠通道。

user:“22｜把「可丢的工具进度帧」从可靠控制通道迁到可丢通道”+(进行中的工具进度帧
（无 delta、非终态）必须迁到可丢通道、允许合并/丢弃；tool_result/status/usage/
approval_*/错误这类结果与决策帧必须继续走 64 格可靠控制通道；判定收成一个纯函数
并单测；被合并/丢弃的帧数按 10 秒节流打日志，超阈值时还要给界面一条可见告警。)

背景（已取证）：模型流式生成工具参数时，每个 chunk 都把同一个 tool_call 状态重投影
一遍。这类帧无 delta、不并入 20ms 合并窗口，`_is_control_outbound()` 又对**所有**
非 delta 的 runItem 返回 True，于是全部挤进 64 格可靠控制通道 → 通道打满 → 1013
重连风暴 → 订阅者队列溢出 → WAL 停止回收（12 万页 / 168MB）→ 后端冻结 67 秒。
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from lamtools_core.app import live_router
from lamtools_core.app.event_store import CORE_RUN_ITEM_METHOD
from lamtools_core.app.live_router import (
    DROP,
    LOSSY,
    RELIABLE,
    CoreLiveConnection,
    classify_run_item_delivery,
)

THREAD_ID = "thread-1"
ITEM_ID = "thread-1:turn-1:call_00_9wn19d0l:tool"


class DummyWebSocket:
    def __init__(self) -> None:
        self.close_calls: list[tuple[int, str]] = []

    async def accept(self) -> None:
        return None

    async def send_json(self, message) -> None:
        return None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.close_calls.append((code, reason))


def _frame(
    *,
    kind: str = "tool_call",
    item_id: str | None = ITEM_ID,
    status: str = "running",
    inner: dict | None = None,
    event_id: str = "evt-1",
) -> dict:
    """A wire-shaped runItem notification (what ``_send`` receives)."""
    value = {
        "kind": kind,
        "thread_id": THREAD_ID,
        "event_id": event_id,
        "status": status,
        "payload": dict(inner or {}),
    }
    if item_id is not None:
        value["item_id"] = item_id
    return {"method": CORE_RUN_ITEM_METHOD, "params": {"thread_id": THREAD_ID, "payload": value}}


def _hub_event(
    *,
    kind: str = "tool_call",
    item_id: str = ITEM_ID,
    status: str = "running",
    inner: dict | None = None,
    event_id: str = "evt-1",
) -> dict:
    """A hub-delivered runItem envelope (what ``_enqueue_run_item`` receives)."""
    return {
        "event_id": event_id,
        "thread_id": THREAD_ID,
        "seq": 0,
        "method": CORE_RUN_ITEM_METHOD,
        "payload": {
            "kind": kind,
            "item_id": item_id,
            "thread_id": THREAD_ID,
            "event_id": event_id,
            "status": status,
            "payload": dict(inner or {}),
        },
        "turn_id": "thread-1:turn-1",
    }


def _drain(connection: CoreLiveConnection) -> list[dict]:
    frames: list[dict] = []
    for queue in (connection.control_outbound, connection.outbound):
        while True:
            try:
                frames.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break
    return frames


def _queued(connection: CoreLiveConnection) -> list[dict]:
    frames: list[dict] = []
    while True:
        try:
            frames.append(connection.outbound.get_nowait())
        except asyncio.QueueEmpty:
            return frames


# ---------------------------------------------------------------------------
# 纯函数判定
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "frame", "expected"),
    [
        ("流式文本 delta", _frame(kind="message", inner={"delta": "chunk"}), LOSSY),
        ("进行中的工具帧", _frame(kind="tool_call", inner={"type": "dynamicToolCall", "arguments": {"a": 1}}), LOSSY),
        ("进行中的思考帧", _frame(kind="thinking", inner={"type": "reasoning", "content": "想"}), LOSSY),
        ("模型阶段帧", _frame(kind="model_phase", inner={"phase": "building"}), LOSSY),
        ("工具终态", _frame(kind="tool_call", status="completed"), RELIABLE),
        ("工具结果", _frame(kind="tool_result", status="completed", inner={"tool_result": "ok"}), RELIABLE),
        ("回合状态", _frame(kind="status", inner={"status": "running"}), RELIABLE),
        ("用量", _frame(kind="usage", inner={"tokens": 3}), RELIABLE),
        ("审批请求", _frame(kind="approval_request", inner={"request_id": "r1"}), RELIABLE),
        ("审批应答", _frame(kind="approval_response", inner={"request_id": "r1"}), RELIABLE),
        ("交互更新", _frame(kind="interaction_update", inner={"state": "appearing"}), RELIABLE),
        ("错误帧", _frame(kind="error", inner={"error": "boom"}), RELIABLE),
        ("未知类型", _frame(kind="mystery_fact", inner={"x": 1}), RELIABLE),
        ("产物帧", _frame(kind="artifact", inner={"artifact_id": "a"}), RELIABLE),
        ("终态且带 delta", _frame(kind="message", status="completed", inner={"delta": "x"}), RELIABLE),
        ("RPC 应答", {"id": "42", "result": {"ok": True}}, RELIABLE),
        ("一般通知", {"method": "thread/snapshot", "params": {"thread_id": THREAD_ID}}, RELIABLE),
        ("无 item 的进度帧", _frame(kind="tool_call", item_id=None), DROP),
        ("无 params", {"method": CORE_RUN_ITEM_METHOD}, RELIABLE),
    ],
)
def test_classify_run_item_delivery(label: str, frame: dict, expected: str) -> None:
    assert classify_run_item_delivery(frame) == expected, label


def test_already_delivered_progress_is_droppable_but_delta_text_is_not() -> None:
    """重复的进度帧可以整帧丢掉；delta 是增量文本，重复内容也必须送达。

    两帧同样的 ``"ha"`` 是合法的增量拼接结果（"haha"），按内容去重会吞字。
    """
    progress = _frame(kind="tool_call", inner={"arguments": {"a": 1}})
    assert classify_run_item_delivery(progress, already_delivered=True) == DROP
    delta = _frame(kind="message", inner={"delta": "ha"})
    assert classify_run_item_delivery(delta, already_delivered=True) == LOSSY


# ---------------------------------------------------------------------------
# 分流：进度帧不进可靠通道
# ---------------------------------------------------------------------------


def test_progress_frames_never_touch_the_reliable_lane() -> None:
    async def run() -> None:
        connection = CoreLiveConnection(DummyWebSocket(), context=SimpleNamespace())
        for index in range(283):
            await connection._enqueue_run_item(
                _hub_event(
                    kind="tool_call",
                    event_id=f"evt-{index}",
                    inner={"type": "dynamicToolCall", "tool_name": "write_file",
                           "arguments": {"path": "a.txt", "content": "x" * (index + 1)}},
                )
            )
        await connection._flush_run_item_buffer()
        assert connection.control_outbound.qsize() == 0
        frames = _queued(connection)
        assert len(frames) <= 3, f"283 progress frames must collapse, got {len(frames)}"
        assert connection._lossy_merged_count >= 279

    asyncio.run(run())


def test_terminal_and_result_frames_stay_on_the_reliable_lane() -> None:
    async def run() -> None:
        connection = CoreLiveConnection(DummyWebSocket(), context=SimpleNamespace())
        await connection._enqueue_run_item(_hub_event(kind="tool_call", inner={"arguments": {"a": 1}}))
        await connection._enqueue_run_item(
            _hub_event(kind="tool_result", status="completed", inner={"tool_result": "ok"})
        )
        await connection._enqueue_run_item(_hub_event(kind="status", inner={"status": "running"}))
        kinds = [frame["params"]["payload"]["kind"] for frame in _drain(connection)]
        assert kinds[-2:] == ["tool_result", "status"]
        # 只有结果/状态两帧进了可靠通道，进度帧一帧都没有。
        assert kinds.count("tool_call") <= 1
        assert connection._lossy_dropped_count == 0

    asyncio.run(run())


def test_pending_progress_frame_is_replaced_instead_of_accreting() -> None:
    """同 item 的进度帧在可丢通道里只占一个槽，后来的状态覆盖先前的。"""

    async def run() -> None:
        connection = CoreLiveConnection(DummyWebSocket(), context=SimpleNamespace(), outbound_limit=1)
        await connection._send(_frame(event_id="e1", inner={"type": "dynamicToolCall",
                                                            "tool_name": "write_file",
                                                            "arguments": {"path": "a.txt"}}))
        await connection._send(_frame(event_id="e2", inner={"type": "dynamicToolCall",
                                                            "tool_name": "write_file",
                                                            "arguments": {"path": "a.txt", "content": "hello"}}))
        assert connection.outbound.qsize() == 1
        assert connection._outbound_dropped_count == 0
        merged = await connection._next_outbound()
        value = merged["params"]["payload"]
        # 最新状态胜出（进度帧携带全量状态，不是增量文本），并保留先前的字段。
        assert value["payload"]["arguments"]["content"] == "hello"
        assert value["payload"]["tool_name"] == "write_file"
        assert value["event_id"] == "e1"
        assert value["_coalesced_event_ids"] == ["e1", "e2"]

    asyncio.run(run())


def test_delta_frames_still_concatenate_and_are_never_suppressed() -> None:
    async def run() -> None:
        connection = CoreLiveConnection(DummyWebSocket(), context=SimpleNamespace())
        await connection._send(_frame(kind="message", event_id="e1", inner={"delta": "ha"}))
        await connection._send(_frame(kind="message", event_id="e2", inner={"delta": "ha"}))
        merged = await connection._next_outbound()
        assert merged["params"]["payload"]["payload"]["delta"] == "haha"

    asyncio.run(run())


def test_stale_progress_frame_is_dropped_when_the_terminal_frame_lands() -> None:
    """终态帧在可靠通道优先发送；排队中的旧进度帧必须被淘汰。

    否则客户端会先收到 completed，再收到一条过期的 running，把工具行重新点亮。
    """

    async def run() -> None:
        connection = CoreLiveConnection(DummyWebSocket(), context=SimpleNamespace())
        await connection._send(_frame(kind="tool_call", event_id="e1", inner={"arguments": {"a": 1}}))
        assert connection.outbound.qsize() == 1
        await connection._send(_frame(kind="tool_call", status="completed", event_id="e2",
                                      inner={"arguments": {"a": 1}, "status": "completed"}))
        terminal = await connection._next_outbound()
        assert terminal["params"]["payload"]["status"] == "completed"
        # 过期进度帧仍在队列里占着位，但出队时被跳过（不会再发给客户端）。
        with pytest.raises(asyncio.QueueEmpty):
            connection._take_outbound()
        assert connection._lossy_dropped_count == 1

    asyncio.run(run())


# ---------------------------------------------------------------------------
# 可观测
# ---------------------------------------------------------------------------


def test_merged_and_dropped_counts_are_logged_on_a_ten_second_throttle(caplog) -> None:
    def stats_lines() -> int:
        return sum(1 for record in caplog.records if "lossy lane" in record.getMessage())

    async def run() -> None:
        connection = CoreLiveConnection(DummyWebSocket(), context=SimpleNamespace())
        for index in range(5):
            await connection._send(_frame(event_id=f"e{index}", inner={"arguments": {"n": index}}))
        # 第一条合并就触发一次日志，之后在同一条节流窗口内不再重复打印。
        connection._log_lossy_lane_stats()
        assert connection._lossy_merged_count == 4
        assert stats_lines() == 1
        # 窗口过去后（这里直接把时间戳清空）再打一条累计值。
        connection._lossy_stats_last_log_at = None
        connection._log_lossy_lane_stats()
        assert stats_lines() == 2

    with caplog.at_level(logging.INFO, logger="lamtools_core.app.live_router"):
        asyncio.run(run())
    text = caplog.text
    assert "merged=4" in text
    assert "dropped=0" in text
    assert "control_depth=0" in text


def test_400_duplicate_progress_frames_do_not_report_pressure() -> None:
    # user:“事件通道压力过高：可靠通道 0/64；已丢弃 400 帧可丢进度；正在自动恢复，无需操作”+(正常去重只计入日志)
    async def run() -> None:
        connection = CoreLiveConnection(DummyWebSocket(), context=SimpleNamespace())
        for index in range(401):
            await connection.send(_frame(event_id=f"e{index}", inner={"arguments": {"n": 1}}))
        await asyncio.gather(*connection.request_tasks)

        assert connection._lossy_dropped_count == 400
        assert connection.outbound.qsize() == 1
        assert connection.control_outbound.empty()

    asyncio.run(run())


def test_reliable_queue_pressure_still_reports_once() -> None:
    async def run() -> None:
        connection = CoreLiveConnection(DummyWebSocket(), context=SimpleNamespace())
        for index in range(33):
            await connection.send({"id": str(index), "result": {}})
        await asyncio.gather(*connection.request_tasks)

        frames = _drain(connection)
        assert [frame["id"] for frame in frames if "id" in frame] == [str(i) for i in range(33)]
        reports = [frame for frame in frames if frame.get("method") == "core/backpressure"]
        assert len(reports) == 1
        report = reports[0]
        assert report["method"] == "core/backpressure"
        params = report["params"]
        assert params["reason"] == "control_queue_pressure"
        assert params["control_queue_depth"] == 32
        assert params["control_queue_limit"] == 64
        assert "wal_pending_pages" not in params

    asyncio.run(run())


def test_outbound_overflow_sends_the_existing_gap_signal() -> None:
    async def run() -> None:
        connection = CoreLiveConnection(DummyWebSocket(), context=SimpleNamespace(), outbound_limit=1)
        connection.thread_id = THREAD_ID
        await connection.send(_frame(kind="message", inner={"delta": "a"}))
        await connection.send(_frame(kind="message", item_id="another-item", inner={"delta": "b"}))
        await asyncio.gather(*connection.request_tasks)

        assert connection.control_outbound.get_nowait() == {
            "method": "thread/gap",
            "params": {"thread_id": THREAD_ID, "reason": "outbound_dropped", "dropped": 1},
        }
        assert connection.control_outbound.empty()

    asyncio.run(run())


def test_pressure_report_does_not_block_when_the_reliable_lane_is_full() -> None:
    """告警本身绝不能把已经打满的可靠通道再堵死。"""

    async def run() -> None:
        connection = CoreLiveConnection(
            DummyWebSocket(), context=SimpleNamespace(), control_outbound_limit=8
        )
        for index in range(8):
            connection.control_outbound.put_nowait({"id": str(index), "result": {}})
        connection._maybe_report_backpressure(now=live_router.time.monotonic())
        for _ in range(20):
            await asyncio.sleep(0)
        assert connection.control_outbound.qsize() == 8
        assert connection.websocket.close_calls == []

    asyncio.run(run())
