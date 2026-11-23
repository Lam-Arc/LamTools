"""压测自证：同 item 每秒 283 帧、持续 N 秒（默认压缩，可拉满 60 秒）。

user:“22｜把「可丢的工具进度帧」从可靠控制通道迁到可丢通道”+(写一个可复现的脚本/
测试，模拟「同 item 每秒 283 帧、持续 60 秒」，断言可靠通道队列不增长、无 1013、
WAL 不堆积，并给出改动前后的对比数字。)

怎么读这份压测：

* 生产者按真实节拍投喂：283 帧/秒（实测故障现场就是同一 item 1 秒 283 帧）。
* 消费者按单连接 WebSocket 的合理吞吐计时（默认 150 帧/秒；长会话里一整页快照
  几十 MB，单帧序列化 + 客户端解析动辄数毫秒，这是保守取值）。
* “改动前”不是另写一套代码，而是把判定函数临时换回旧规则（所有非 delta 的
  runItem 都走可靠通道）。旧 `_enqueue_run_item` 对非 delta 帧本来就是
  「flush + 立即 _send」，所以旧判定 + 现有投递路径 == 改动前的路由行为。

WAL 的可测等价指标：路由层对瞬时进度帧一次数据库都不碰（``sync_journal`` 调用数
为 0），订阅者队列不溢出、不断连——故障链里 WAL 停止回收是这条链的末端后果
（1013 重连风暴 → 每个重连都 resume → 读池被占死 → checkpoint 停摆）。所以这里断言
的是「链的前两环不再发生」，以及数据库零访问。

跑法::

    cd core
    PYTHONPATH="<repo>/core/src" python -m pytest tests/test_core_live_lossy_channel_stress.py -q --allow-dirty

    # 打印 60 秒版对比数字（约 60 秒 × 2 场景）
    LAMTOOLS_LOSSY_STRESS_SECONDS=60 PYTHONPATH="<repo>/core/src" \\
        python tests/test_core_live_lossy_channel_stress.py
"""
from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lamtools_core.app import live_router
from lamtools_core.app.event_store import CORE_RUN_ITEM_METHOD
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_router import CoreLiveConnection

THREAD_ID = "thread-1"
ITEM_ID = "thread-1:turn-1:call_00_9wn19d0l:tool"
FPS = 283
# 单连接 WS 吞吐（帧/秒）。故障现场同时还在推几十 MB 的快照页。
CONSUMER_CAPACITY_PER_SECOND = 150.0
CONTROL_LIMIT = 64
OUTBOUND_LIMIT = 256

SECONDS = float(os.environ.get("LAMTOOLS_LOSSY_STRESS_SECONDS", "3"))


class DummyWebSocket:
    def __init__(self) -> None:
        self.close_calls: list[tuple[int, str]] = []

    async def accept(self) -> None:
        return None

    async def send_json(self, message) -> None:  # pragma: no cover - sender is simulated
        return None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.close_calls.append((code, reason))


def _legacy_classify(message, *, already_delivered: bool = False) -> str:
    """改动前的分流规则：所有非 delta 的 runItem 都算可靠。"""
    if not isinstance(message, dict):
        return "reliable"
    if "id" in message:
        return "reliable"
    if message.get("method") != CORE_RUN_ITEM_METHOD:
        return "reliable"
    params = message.get("params")
    if not isinstance(params, dict):
        return "reliable"
    value = params.get("payload") if isinstance(params.get("payload"), dict) else params
    inner = value.get("payload") if isinstance(value.get("payload"), dict) else {}
    if isinstance(inner.get("delta"), str):
        return "lossy"
    return "reliable"


class CountingJournal:
    """瞬时帧不该查库；任何一次调用都说明路由层又去打数据库了。"""

    def __init__(self) -> None:
        self.calls = 0

    async def get_change_header(self, *_args, **_kwargs):
        self.calls += 1
        return None

    async def get_change(self, *_args, **_kwargs):
        self.calls += 1
        return None


def _progress_event(index: int) -> dict:
    """同一 item 的第 index 帧进度：参数一直在长，所以内容去重救不了它。"""
    return {
        "event_id": f"evt-{index}",
        "thread_id": THREAD_ID,
        "seq": 0,
        "method": CORE_RUN_ITEM_METHOD,
        "turn_id": "thread-1:turn-1",
        "payload": {
            "kind": "tool_call",
            "item_id": ITEM_ID,
            "thread_id": THREAD_ID,
            "event_id": f"evt-{index}",
            "status": "running",
            "payload": {
                "type": "dynamicToolCall",
                "tool_name": "write_file",
                "arguments": {"path": "a.txt", "content": "x" * (index % 2048 + 1)},
            },
        },
    }


def _terminal_event() -> dict:
    return {
        "event_id": "evt-terminal",
        "thread_id": THREAD_ID,
        "seq": 0,
        "method": CORE_RUN_ITEM_METHOD,
        "turn_id": "thread-1:turn-1",
        "payload": {
            "kind": "tool_result",
            "item_id": ITEM_ID,
            "thread_id": THREAD_ID,
            "event_id": "evt-terminal",
            "status": "completed",
            "payload": {"type": "dynamicToolCall", "tool_name": "write_file",
                        "tool_result": "ok", "status": "completed"},
        },
    }


async def _scenario(*, legacy: bool, seconds: float) -> dict:
    hub = CoreAppEventHub(queue_size=256)
    websocket = DummyWebSocket()
    journal = CountingJournal()
    context = SimpleNamespace(host=SimpleNamespace(sync_journal=journal))
    connection = CoreLiveConnection(
        websocket,
        context=context,
        outbound_limit=OUTBOUND_LIMIT,
        control_outbound_limit=CONTROL_LIMIT,
        # 缩短“通道打满 → 1013”的等待，让旧规则下的失败在数秒内暴露；机制不变。
        control_outbound_timeout_seconds=0.2,
    )
    connection.thread_id = THREAD_ID
    connection.subscription = hub.subscribe(THREAD_ID)

    stats: dict[str, float | int | list | bool] = {
        "produced": 0,
        "delivered": 0,
        "control_frames": 0,
        "max_control_depth": 0,
        "max_outbound_depth": 0,
        "closes": [],
        "journal_calls": 0,
        "delivered_control": 0,
        "seconds": seconds,
        "legacy": legacy,
    }

    async def consumer() -> None:
        delay = 1.0 / CONSUMER_CAPACITY_PER_SECOND
        while True:
            try:
                message = await connection._next_outbound()
            except asyncio.CancelledError:
                raise
            stats["delivered"] = int(stats["delivered"]) + 1
            if message.get("method") != CORE_RUN_ITEM_METHOD and "id" not in message:
                stats["delivered_control"] = int(stats["delivered_control"]) + 1
            stats["max_control_depth"] = max(
                int(stats["max_control_depth"]), connection.control_outbound.qsize()
            )
            stats["max_outbound_depth"] = max(
                int(stats["max_outbound_depth"]), connection.outbound.qsize()
            )
            await asyncio.sleep(delay)

    async def run_body() -> None:
        reader = asyncio.create_task(connection._hub_reader())
        consumer_task = asyncio.create_task(consumer())
        executor = _legacy_classify if legacy else live_router.classify_run_item_delivery
        interval = 1.0 / FPS
        produced = 0
        started = time.monotonic()
        try:
            with patch.object(live_router, "classify_run_item_delivery", executor):
                total = int(FPS * seconds)
                while produced < total:
                    if websocket.close_calls or connection._closing:
                        break
                    await hub.publish(_progress_event(produced))
                    produced += 1
                    target = started + produced * interval
                    now = time.monotonic()
                    if now < target:
                        await asyncio.sleep(target - now)
                stats["produced"] = produced
                stats["elapsed"] = time.monotonic() - started
                if not websocket.close_calls and not connection._closing:
                    await hub.publish(_terminal_event())
                    await asyncio.sleep(0.05)
        finally:
            reader.cancel()
            consumer_task.cancel()
            await asyncio.gather(reader, consumer_task, return_exceptions=True)

    await run_body()
    stats["closes"] = list(websocket.close_calls)
    stats["journal_calls"] = journal.calls
    stats["control_frames"] = int(getattr(connection, "_control_frames_enqueued", 0))
    stats["lossy_merged"] = int(getattr(connection, "_lossy_merged_count", 0))
    stats["lossy_dropped"] = int(getattr(connection, "_lossy_dropped_count", 0))
    stats["outbound_dropped"] = int(connection._outbound_dropped_count)
    stats["control_queue_depth"] = connection.control_outbound.qsize()
    return stats


def _format(stats: dict) -> str:
    return (
        f"{'改动前' if stats['legacy'] else '改动后'} "
        f"投喂={stats['produced']} 送达={stats['delivered']} "
        f"可靠通道入队={stats['control_frames']} 可靠最大深度={stats['max_control_depth']} "
        f"可丢最大深度={stats['max_outbound_depth']} "
        f"合并={stats['lossy_merged']} 丢弃={stats['lossy_dropped']} "
        f"断连={stats['closes']} 查库={stats['journal_calls']}"
    )


def test_tool_progress_burst_cannot_fill_the_reliable_lane() -> None:
    """283 帧/秒的进度流：改动前挤爆 64 格可靠通道并断连，改动后队列不增长。"""

    async def run() -> None:
        after = await _scenario(legacy=False, seconds=SECONDS)
        before = await _scenario(legacy=True, seconds=SECONDS)

        print("\n" + _format(before))
        print(_format(after) + "\n")

        # --- 改动后：可靠通道不被进度帧占用 ---
        assert after["closes"] == [], after["closes"]
        assert after["max_control_depth"] <= 1, after["max_control_depth"]
        assert after["control_frames"] <= 2, after["control_frames"]
        assert after["journal_calls"] == 0
        assert after["lossy_merged"] > 0
        # 合并后送达量被压掉一个数量级（20ms 窗口 + 同 item 覆盖）。
        assert after["delivered"] * 5 <= after["produced"], (after["delivered"], after["produced"])

        # --- 改动前：同样的帧数把可靠通道打满并触发 1013 ---
        # 采样发生在消费端出队时，读数可能比 64 格限值差一两帧。
        assert before["max_control_depth"] >= CONTROL_LIMIT - 2, before["max_control_depth"]
        assert any(code == 1013 for code, _reason in before["closes"]), before["closes"]
        assert before["produced"] < after["produced"], (before["produced"], after["produced"])

    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover - 手动复现用
    seconds = float(os.environ.get("LAMTOOLS_LOSSY_STRESS_SECONDS", "60"))
    print(f"# 同 item {FPS} 帧/秒 × {seconds:g} 秒，消费端 {CONSUMER_CAPACITY_PER_SECOND:g} 帧/秒")
    for legacy in (True, False):
        print(_format(asyncio.run(_scenario(legacy=legacy, seconds=seconds))))
