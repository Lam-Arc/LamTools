from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from lamtools_core.runtime.arrange import ArrangeManager, InMemoryArrangeStore
from lamtools_core.runtime.observer import ObserverSupervisor, prepare_observer


async def _wait_until(predicate, *, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition was not met before timeout")
        await asyncio.sleep(0.02)


def _write_catch_up_observer(path: Path) -> None:
    path.write_text(
        """
import json
import os
from pathlib import Path
import time

root = Path(os.environ["LAMTOOLS_OBSERVER_WORK_ROOT"])
state = Path(os.environ["LAMTOOLS_OBSERVER_STATE_DIR"])
state.mkdir(parents=True, exist_ok=True)
cursor_path = state / "cursor.txt"
feed_path = root / "feed.json"

while True:
    items = json.loads(feed_path.read_text(encoding="utf-8"))
    if cursor_path.exists():
        cursor = cursor_path.read_text(encoding="utf-8").strip()
        ids = [str(item["id"]) for item in items]
        start = ids.index(cursor) + 1 if cursor in ids else 0
        for item in items[start:]:
            print(json.dumps({
                "protocol": "lamtools.signal.v1",
                "event_id": f"content:{item['id']}",
                "event_type": "content.published",
                "occurred_at": item["occurred_at"],
                "subject": "creator:42",
                "data": item,
            }, ensure_ascii=False), flush=True)
        if items:
            cursor_path.write_text(str(items[-1]["id"]), encoding="utf-8")
    elif items:
        cursor_path.write_text(str(items[-1]["id"]), encoding="utf-8")
    time.sleep(0.05)
""".strip()
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_observer_catches_up_events_created_while_core_was_off(tmp_path: Path) -> None:
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    observer_path = work_root / "observer.py"
    feed_path = work_root / "feed.json"
    _write_catch_up_observer(observer_path)
    feed_path.write_text(
        json.dumps([{"id": "old", "occurred_at": "2026-07-17T12:00:00Z"}]),
        encoding="utf-8",
    )

    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="observer-thread",
        work_root=str(work_root),
        kind="focus",
        operation="turn.start",
        payload={"message": "notify me"},
        trigger={"type": "event", "event_type": "content.published"},
        observer=prepare_observer({"entry": "observer.py"}, work_root=work_root),
    )
    data_dir = tmp_path / "core-data"

    first = ObserverSupervisor(store, data_dir=data_dir, poll_interval=0.05)
    await first.start()
    cursor = data_dir / "observers" / job.id / "cursor.txt"
    await _wait_until(cursor.exists)
    assert await manager.list_occurrences(job_id=job.id) == []
    await first.stop()

    feed_path.write_text(
        json.dumps([
            {"id": "old", "occurred_at": "2026-07-17T12:00:00Z"},
            {
                "id": "new",
                "occurred_at": "2026-07-17T14:00:00Z",
                "title": "published while offline",
            },
        ]),
        encoding="utf-8",
    )

    wakes: list[str] = []
    restarted = ObserverSupervisor(
        store,
        data_dir=data_dir,
        wake_runner=lambda: wakes.append("wake"),
        poll_interval=0.05,
    )
    await restarted.start()
    await _wait_until(lambda: bool(wakes))
    occurrences = await manager.list_occurrences(job_id=job.id)
    await restarted.stop()

    assert len(occurrences) == 1
    assert occurrences[0].signal["metadata"]["source_event_id"] == "content:new"
    assert occurrences[0].signal["data"]["title"] == "published while offline"


@pytest.mark.asyncio
async def test_observer_signal_only_targets_its_bound_arrange(tmp_path: Path) -> None:
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    script = work_root / "observer.py"
    script.write_text(
        """
import json
import time
print(json.dumps({
    "protocol": "lamtools.signal.v1",
    "event_id": "evt-bound",
    "event_type": "content.published",
    "occurred_at": "2026-07-17T14:00:00Z"
}), flush=True)
time.sleep(10)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    bound = await manager.create(
        thread_id="bound-thread",
        work_root="test-proj",
        kind="focus",
        operation="turn.start",
        payload={"message": "bound"},
        trigger={"type": "event", "event_type": "content.published"},
        observer=prepare_observer({"entry": "observer.py"}, work_root=work_root),
    )
    other = await manager.create(
        thread_id="other-thread",
        work_root="test-proj",
        kind="focus",
        operation="turn.start",
        payload={"message": "other"},
        trigger={"type": "event", "event_type": "content.published"},
    )

    supervisor = ObserverSupervisor(store, data_dir=tmp_path / "data", poll_interval=0.05)
    await supervisor.start()
    await _wait_until(lambda: supervisor.status(bound.id).get("last_signal_at") is not None)
    await supervisor.stop()

    assert len(await manager.list_occurrences(job_id=bound.id)) == 1
    assert await manager.list_occurrences(job_id=other.id) == []


@pytest.mark.asyncio
async def test_observer_requires_new_approval_after_script_changes(tmp_path: Path) -> None:
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    script = work_root / "observer.py"
    script.write_text("import time\ntime.sleep(10)\n", encoding="utf-8")
    observer = prepare_observer({"entry": "observer.py"}, work_root=work_root)
    script.write_text("print('changed')\n", encoding="utf-8")

    store = InMemoryArrangeStore()
    job = await ArrangeManager(store).create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="focus",
        operation="turn.start",
        payload={"message": "observe"},
        trigger={"type": "event", "event_type": "artifact.changed"},
        observer=observer,
    )
    supervisor = ObserverSupervisor(store, data_dir=tmp_path / "data", poll_interval=0.05)
    await supervisor.start()
    await _wait_until(lambda: supervisor.status(job.id).get("status") == "approval_required")
    status = supervisor.status(job.id)
    await supervisor.stop()

    assert status["status"] == "approval_required"
    assert "changed" in str(status["last_error"]).lower()


@pytest.mark.asyncio
async def test_observer_follows_arrange_pause_resume_and_cancel(tmp_path: Path) -> None:
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    script = work_root / "observer.py"
    script.write_text("import time\nwhile True:\n    time.sleep(1)\n", encoding="utf-8")

    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="focus",
        operation="turn.start",
        payload={"message": "observe"},
        trigger={"type": "event", "event_type": "artifact.changed"},
        observer=prepare_observer({"entry": "observer.py"}, work_root=work_root),
    )
    supervisor = ObserverSupervisor(store, data_dir=tmp_path / "data", poll_interval=0.05)
    await supervisor.start()
    await _wait_until(lambda: supervisor.status(job.id).get("status") == "running")
    first_pid = supervisor.status(job.id)["pid"]

    await manager.update_status(job.id, "paused")
    supervisor.wake()
    await _wait_until(lambda: supervisor.status(job.id).get("status") == "stopped")

    await manager.update_status(job.id, "scheduled")
    supervisor.wake()
    await _wait_until(
        lambda: supervisor.status(job.id).get("status") == "running"
        and supervisor.status(job.id).get("pid") != first_pid
    )

    await manager.update_status(job.id, "cancelled")
    supervisor.wake()
    await _wait_until(lambda: supervisor.status(job.id).get("status") == "stopped")
    await supervisor.stop()

    assert (await manager.get(job.id)).status == "cancelled"  # type: ignore[union-attr]


def test_prepare_observer_requires_explicit_workspace(tmp_path: Path) -> None:
    script = tmp_path / "observer.py"
    script.write_text("pass\n", encoding="utf-8")

    with pytest.raises(ValueError, match="work_root"):
        prepare_observer({"entry": str(script)}, work_root="")
