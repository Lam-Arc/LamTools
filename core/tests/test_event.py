"""Tests for lamtools_core.event module."""

import pytest

from lamtools_core.event import CollectingEventSink, CoreEvent, EventCategory, EventTag, InMemoryEventLog


class TestCoreEvent:
    def test_construction(self):
        evt = CoreEvent(name="turn_start", category="lifecycle")
        assert evt.name == "turn_start"
        assert evt.category == "lifecycle"
        assert evt.event_id != ""
        assert evt.timestamp_ms > 0

    def test_to_dict(self):
        evt = CoreEvent(
            name="tool_called",
            category="tool",
            payload={"tool": "search"},
            session_id="s1",
            tags=["tool", "debug"],
        )
        d = evt.to_dict()
        assert d["name"] == "tool_called"
        assert d["category"] == "tool"
        assert d["payload"] == {"tool": "search"}
        assert d["session_id"] == "s1"
        assert d["tags"] == ["tool", "debug"]

    def test_to_dict_omits_empty_fields(self):
        evt = CoreEvent(name="reply", category="message")
        d = evt.to_dict()
        assert "session_id" not in d
        assert "correlation_id" not in d
        assert "tags" not in d

    def test_event_id_unique(self):
        e1 = CoreEvent(name="a", category="lifecycle")
        e2 = CoreEvent(name="b", category="lifecycle")
        assert e1.event_id != e2.event_id

    def test_all_categories(self):
        categories: list[EventCategory] = [
            "lifecycle", "progress", "message", "tool",
            "decision", "verification", "artifact", "error",
        ]
        for cat in categories:
            evt = CoreEvent(name="test", category=cat)
            assert evt.category == cat

    def test_all_tags(self):
        tags: list[EventTag] = [
            "reply", "tool", "artifact", "decision",
            "progress", "state", "error", "done", "debug",
        ]
        for tag in tags:
            evt = CoreEvent(name="test", category="lifecycle", tags=[tag])
            assert tag in evt.tags


class TestInMemoryEventLog:
    def test_append_and_replay(self):
        log = InMemoryEventLog()
        e1 = CoreEvent(name="a", category="lifecycle")
        e2 = CoreEvent(name="b", category="tool")
        log.append(e1)
        log.append(e2)
        all_events = log.replay_since()
        assert len(all_events) == 2

    def test_replay_tail(self):
        log = InMemoryEventLog()
        for i in range(5):
            log.append(CoreEvent(name=f"e{i}", category="lifecycle"))
        tail = log.replay_since(tail=2)
        assert len(tail) == 2

    def test_replay_since_id(self):
        log = InMemoryEventLog()
        e1 = CoreEvent(name="first", category="lifecycle")
        e2 = CoreEvent(name="second", category="lifecycle")
        e3 = CoreEvent(name="third", category="lifecycle")
        log.append(e1)
        log.append(e2)
        log.append(e3)
        after = log.replay_since(event_id=e1.event_id)
        assert len(after) == 2
        assert after[0][1].name == "second"

    def test_clear(self):
        log = InMemoryEventLog()
        log.append(CoreEvent(name="x", category="lifecycle"))
        log.clear()
        assert len(log.replay_since()) == 0


class TestCollectingEventSink:
    @pytest.mark.asyncio
    async def test_collects_and_forwards_events(self):
        forwarded = []

        async def live_callback(event: CoreEvent):
            forwarded.append(event)

        sink = CollectingEventSink(live_callback=live_callback)
        event = CoreEvent(name="progress", category="progress")

        await sink.emit(event)

        assert sink.events == [event]
        assert forwarded == [event]

    @pytest.mark.asyncio
    async def test_can_forward_transient_events_without_retaining_them(self):
        forwarded = []
        sink = CollectingEventSink(
            live_callback=forwarded.append,
            should_collect=lambda event: event.metadata.get("delivery") != "transient",
        )
        transient = CoreEvent(
            name="runtime.reply_delta",
            category="message",
            metadata={"delivery": "transient"},
        )

        await sink.emit(transient)

        assert forwarded == [transient]
        assert sink.events == []

    @pytest.mark.asyncio
    async def test_clear(self):
        sink = CollectingEventSink()
        await sink.emit(CoreEvent(name="progress", category="progress"))
        sink.clear()
        assert sink.events == []
