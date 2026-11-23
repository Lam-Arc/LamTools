"""同一 item 的同一事件在一条连接上只能下发一次。

user:“查清 constant 安装版为什么退出 + 修掉事件风暴”+(同一 item 的同一事件
只下发一次：实测安装版（E:\\setuptest\\constant）在一次会话里，模型流式生成
工具参数时每个 chunk 都会重投影一次同一个非 delta 的 ``tool_call`` runItem，
这类事件不走 20ms 合并窗口，路由层原样逐帧直发——同一 item 在 1 秒内下发 283
帧，19 分钟写满一个 16MB 的 backend.log 分片，并在崩溃前把数据库 WAL 顶到
168MB。)
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from lamtools_core.app.event_store import CORE_RUN_ITEM_METHOD
from lamtools_core.app.live_router import CoreLiveConnection

THREAD_ID = "thread-1"
ITEM_ID = "thread-1:sub:worker:abc123:def456:call_00_9wn19d0l:tool"


class DummyWebSocket:
    def __init__(self) -> None:
        self.close_calls: list[tuple[int, str]] = []

    async def accept(self) -> None:
        return None

    async def send_json(self, message) -> None:
        return None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.close_calls.append((code, reason))


def _tool_call_envelope(*, event_id: str, arguments: dict) -> dict:
    """一个非 delta 的 tool_call runItem envelope（与 hub 投递的形状一致）。"""
    return {
        "event_id": event_id,
        "protocol_version": "core.app_server.v1",
        "thread_id": THREAD_ID,
        "method": CORE_RUN_ITEM_METHOD,
        "payload": {
            "kind": "tool_call",
            "item_id": ITEM_ID,
            "thread_id": THREAD_ID,
            "status": "running",
            "payload": {
                "type": "dynamicToolCall",
                "tool_name": "write_file",
                "arguments": arguments,
                "summary": "准备调用 write_file",
            },
        },
        "turn_id": f"{THREAD_ID}:turn:1",
        "item_id": ITEM_ID,
    }


def _drain(connection: CoreLiveConnection) -> list[dict]:
    frames: list[dict] = []
    while True:
        try:
            frames.append(connection.control_outbound.get_nowait())
        except asyncio.QueueEmpty:
            break
    # 可丢通道必须走 _take_outbound：出队时要同时退役「同 item 已排队」索引，
    # 否则测试自己会留下过期索引，让后续帧被并进一个已经取走的帧里。
    while True:
        try:
            frames.append(connection._take_outbound())
        except asyncio.QueueEmpty:
            break
    return frames


def test_same_item_event_is_sent_only_once() -> None:
    async def run() -> None:
        connection = CoreLiveConnection(DummyWebSocket(), context=SimpleNamespace())
        # 200 个 chunk 重投影出内容完全相同的 tool_call 事件（只有 event_id 不同）。
        for index in range(200):
            await connection._enqueue_run_item(
                _tool_call_envelope(event_id=f"evt-{index}", arguments={"path": "a.txt", "content": "x"})
            )
        # user:“22｜把「可丢的工具进度帧」从可靠控制通道迁到可丢通道”+(进行中的进度帧
        # 现在进 20ms 合并窗口、走可丢通道；合并发生在缓冲层，所以要先把窗口冲出来
        # 才能看到这次下发。语义不变：同 item 同内容只发一次。)
        await connection._flush_run_item_buffer()
        frames = _drain(connection)
        assert len(frames) == 1, f"same item+same payload must be sent once, got {len(frames)}"
        assert frames[0]["params"]["item_id"] == ITEM_ID
        assert connection.control_outbound.qsize() == 0

    asyncio.run(run())


def test_changed_item_state_is_still_sent() -> None:
    """进度帧改了状态照样会送到，只是窗口内只保留最新那一个状态。

    user:“22｜把「可丢的工具进度帧」从可靠控制通道迁到可丢通道”+(进行中的工具进度帧
    是「可丢」的：客户端要的收敛结果是同一 item 的最新状态，不是每一帧都到。旧断言
    「每帧必达」保护的其实是「状态变化不会被永久吞掉」，所以这里改成断言最新状态一定
    送达、中间帧被合并计数，而不是否定掉的旧结论。)
    """

    async def run() -> None:
        connection = CoreLiveConnection(DummyWebSocket(), context=SimpleNamespace())
        await connection._enqueue_run_item(
            _tool_call_envelope(event_id="evt-a", arguments={"path": "a.txt"})
        )
        # 参数变了：最新状态必须送达。
        await connection._enqueue_run_item(
            _tool_call_envelope(event_id="evt-b", arguments={"path": "b.txt"})
        )
        await connection._flush_run_item_buffer()
        frames = _drain(connection)
        assert len(frames) == 1
        assert frames[0]["params"]["payload"]["payload"]["arguments"] == {"path": "b.txt"}
        assert connection._lossy_merged_count == 1

        # 窗口之外的下一次状态变化必须重新下发（不是被指纹永久吞掉）。
        await connection._enqueue_run_item(
            _tool_call_envelope(event_id="evt-c", arguments={"path": "a.txt"})
        )
        await connection._flush_run_item_buffer()
        frames = _drain(connection)
        assert len(frames) == 1
        assert frames[0]["params"]["payload"]["payload"]["arguments"] == {"path": "a.txt"}

    asyncio.run(run())


def _tool_result_envelope(*, event_id: str, status: str = "completed") -> dict:
    envelope = _tool_call_envelope(event_id=event_id, arguments={})
    envelope["payload"]["kind"] = "tool_result"
    envelope["payload"]["status"] = status
    envelope["payload"]["payload"] = {
        "type": "dynamicToolCall",
        "tool_name": "write_file",
        "tool_result": "ok",
        "status": status,
    }
    return envelope


def test_terminal_frames_are_never_deduplicated() -> None:
    """完成/失败这类终态帧不参与去重：吞掉一个就等于客户端永远等不到工具结束。"""

    async def run() -> None:
        connection = CoreLiveConnection(DummyWebSocket(), context=SimpleNamespace())
        await connection._enqueue_run_item(_tool_result_envelope(event_id="evt-1"))
        await connection._enqueue_run_item(_tool_result_envelope(event_id="evt-2"))
        frames = _drain(connection)
        assert len(frames) == 2

    asyncio.run(run())


def test_terminal_transition_always_reaches_the_client() -> None:
    """进行中的重复帧被去重后，同一 item 的终态帧必须照常下发。"""

    async def run() -> None:
        connection = CoreLiveConnection(DummyWebSocket(), context=SimpleNamespace())
        for index in range(50):
            await connection._enqueue_run_item(
                _tool_call_envelope(event_id=f"evt-{index}", arguments={"path": "a.txt"})
            )
        await connection._enqueue_run_item(_tool_result_envelope(event_id="evt-done"))
        frames = _drain(connection)
        assert [frame["params"]["payload"]["kind"] for frame in frames] == ["tool_call", "tool_result"]

    asyncio.run(run())
