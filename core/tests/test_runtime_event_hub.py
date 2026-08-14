import json

import pytest

from lamtools_core.run_event import RuntimeEventHub


def _payload_from_sse(sse_line: str) -> dict:
    for line in sse_line.splitlines():
        if line.startswith("data:"):
            return json.loads(line.split(":", 1)[1].strip())
    raise AssertionError(f"SSE line has no data payload: {sse_line!r}")


@pytest.mark.asyncio
async def test_runtime_event_hub_replays_after_last_event_id():
    hub = RuntimeEventHub()
    first_id, _delivered = hub.publish_runtime_record(
        name="task_started",
        session_id="s1",
        data={"session_id": "s1"},
    )
    second_id, _delivered = hub.publish_runtime_record(
        name="task_progress",
        session_id="s1",
        data={"session_id": "s1", "message": "working"},
    )

    _queue_id, queue, replay_gap = await hub.subscribe(session_id="s1", last_event_id=first_id)

    assert replay_gap is False
    data = _payload_from_sse(queue.get_nowait())
    assert data["id"] == second_id
    assert data["type"] == "task_progress"
    assert data["data"]["message"] == "working"


def test_runtime_event_hub_outputs_core_runtime_shape():
    hub = RuntimeEventHub()
    event_id, _delivered = hub.publish_runtime_record(
        name="task_progress",
        session_id="s2",
        run_id="run-1",
        data={"session_id": "s2", "type": "task_progress"},
    )

    [record] = hub.list_events(session_id="s2")

    assert record["id"] == event_id
    assert record["session_id"] == "s2"
    assert record["name"] == "task_progress"
    assert record["type"] == "task_progress"
    assert record["category"] == "runtime"
    assert record["run_id"] == "run-1"
    assert "timestamp" in record
    assert "created_at" in record
    assert record["data"] == {"session_id": "s2", "type": "task_progress"}
    assert "payload" not in record
    assert "event_type" not in record
    assert "correlation_id" not in record


@pytest.mark.asyncio
async def test_subscribe_reports_replay_gap_when_last_event_id_trimmed():
    hub = RuntimeEventHub(max_events=3)
    ids = []
    for i in range(5):
        event_id, _ = hub.publish_runtime_record(name="ev", session_id="s3", data={"n": i})
        ids.append(event_id)

    # The first event has been trimmed out of the 3-event window — resuming
    # from it must be flagged as a gap instead of silently replaying nothing.
    _queue_id, queue, replay_gap = await hub.subscribe(session_id="s3", last_event_id=ids[0])
    assert replay_gap is True
    assert queue.empty()


@pytest.mark.asyncio
async def test_stale_queues_are_swept_on_publish():
    hub = RuntimeEventHub()
    queue_id, _queue, _gap = await hub.subscribe(session_id="s4")
    assert hub.queue_count == 1

    # Force the subscription to look stale, then publish — the sweep must
    # drop the zombie queue (audit 11: subscribers that never unsubscribe
    # would otherwise leak forever).
    hub._queue_registry[queue_id] = (
        hub._queue_registry[queue_id][0],
        hub._queue_registry[queue_id][1],
        hub._now() - hub.QUEUE_STALE_SECONDS - 1,
    )
    hub.publish_runtime_record(name="ev", session_id="s4", data={})
    assert hub.queue_count == 0
    assert "s4" not in hub._session_queues


def test_sequence_stays_monotonic_after_trim():
    """After the event window trims old records, new sequences must not
    collide with or fall below kept records' sequences (audit 07)."""
    hub = RuntimeEventHub(max_events=3)
    ids = []
    for i in range(6):
        _id, _ = hub.publish_runtime_record(name="evt", session_id="s-seq", data={"n": i})
        ids.append(_id)

    records = hub._event_store.list()
    sequences = [record.sequence for record in records]
    # Only the last 3 survive the trim.
    assert len(records) == 3
    # Kept records keep their original (high) sequences…
    assert ids[-3:] == [record.id for record in records]
    # …and the next append still goes strictly above them.
    _new_id, _ = hub.publish_runtime_record(name="evt", session_id="s-seq", data={"n": 6})
    assert _new_id == hub._event_store.list()[-1].id
    new_sequence = hub._event_store.list()[-1].sequence
    assert new_sequence > max(sequences)
    assert len({record.sequence for record in hub._event_store.list()}) == len(hub._event_store.list())


@pytest.mark.asyncio
async def test_slow_consumer_drop_is_logged(caplog):
    """Queue-full drops warn once per stuck subscriber (audit 07 S4)."""
    hub = RuntimeEventHub(max_queue_size=1)
    queue_id, queue, _gap = await hub.subscribe(session_id="s-drop")
    # Fill the queue; the second event must be dropped.
    hub.publish_runtime_record(name="evt", session_id="s-drop", data={"n": 1})
    assert queue.qsize() == 1
    hub.publish_runtime_record(name="evt", session_id="s-drop", data={"n": 2})
    hub.publish_runtime_record(name="evt", session_id="s-drop", data={"n": 3})

    warnings = [r for r in caplog.records if r.name == "lamtools_core.run_event.hub" and r.levelno >= 30]
    assert len(warnings) == 1
    assert queue_id in warnings[0].message
