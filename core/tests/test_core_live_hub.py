from __future__ import annotations

import asyncio

from lamtools_core.app.live_hub import CoreAppEventGap, CoreAppEventHub


def test_slow_subscriber_receives_gap_signal_and_is_removed() -> None:
    async def run() -> None:
        hub = CoreAppEventHub(queue_size=1)
        subscription = hub.subscribe("thread-1")

        await hub.publish({"thread_id": "thread-1", "seq": 1})
        await hub.publish({"thread_id": "thread-1", "seq": 2})

        gap = await subscription.get()
        assert isinstance(gap, CoreAppEventGap)
        assert gap.thread_id == "thread-1"
        assert gap.reason == "subscriber_overflow"
        assert "thread-1" not in hub._subscribers

    asyncio.run(run())
