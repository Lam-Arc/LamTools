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


def test_global_subscriber_receives_projection_events() -> None:
    async def run() -> None:
        hub = CoreAppEventHub(queue_size=1)
        subscription = hub.subscribe_all()

        await hub.publish_global({"method": "pet/overviewChanged"})

        assert await subscription.get() == {"method": "pet/overviewChanged"}
        hub.unsubscribe_all(subscription)

    asyncio.run(run())


def test_global_subscriber_receives_raw_events_for_projection_services() -> None:
    async def run() -> None:
        hub = CoreAppEventHub(queue_size=2)
        subscription = hub.subscribe_all()

        await hub.publish({"thread_id": "thread-1", "method": "turn/accepted"})

        assert await subscription.get() == {"thread_id": "thread-1", "method": "turn/accepted"}
        hub.unsubscribe_all(subscription)

    asyncio.run(run())
