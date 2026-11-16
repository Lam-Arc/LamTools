"""等成员的显示标注不得把已经结束的回合重新标成 running。

user:“父会话为什么会有等待态这一个意义不明的东西？正常走完成不就唤醒了吗？”
+(设计上父回合产出最终答复就结束，成员结果交给唤醒另开一轮；那条“还在等成员”的标注
只是给人看的，不能参与回合状态推导，否则唤醒守卫会永远以为会话在跑。)
"""
from __future__ import annotations

from lamtools_core.snapshot import apply_run_item_event_in_place
from lamtools_core.event.run_item import RunItemEvent

THREAD = "thread-wait"
TURN = f"{THREAD}:turn:1"


def _terminal(seq: int) -> RunItemEvent:
    return RunItemEvent(
        kind="status",
        thread_id=THREAD,
        turn_id=TURN,
        item_id=f"{TURN}:terminal",
        status="completed",
        seq=seq,
        payload={"status": "completed"},
    )


def _wait_annotation(seq: int, *, waiting: bool) -> RunItemEvent:
    return RunItemEvent(
        kind="status",
        thread_id=THREAD,
        turn_id=TURN,
        item_id=f"{TURN}:sub-agent-wait",
        status="running",
        seq=seq,
        payload={
            "type": "subAgents",
            "status": "running",
            "waiting_on_members": waiting,
            "members": [] if not waiting else [{"name": "worker", "status": "running"}],
        },
    )


def test_a_wait_annotation_never_reopens_a_finished_turn() -> None:
    state = apply_run_item_event_in_place({}, _terminal(1))
    assert state["turns"][TURN]["status"] == "completed"
    assert state["status"] == "completed"

    state = apply_run_item_event_in_place(state, _wait_annotation(2, waiting=True))

    # 标注出现了（界面能看到“只剩成员在跑”），但回合仍是终态。
    assert state["turns"][TURN]["status"] == "completed"
    assert state["status"] == "completed"


def test_a_drained_annotation_keeps_the_turn_finished() -> None:
    state = apply_run_item_event_in_place({}, _terminal(1))
    state = apply_run_item_event_in_place(state, _wait_annotation(2, waiting=True))
    state = apply_run_item_event_in_place(state, _wait_annotation(3, waiting=False))

    assert state["turns"][TURN]["status"] == "completed"
    assert state["status"] == "completed"


def test_an_ordinary_running_status_still_marks_the_turn_running() -> None:
    """只有“等成员”这条标注被排除；普通状态事件照旧驱动回合状态。"""

    state = apply_run_item_event_in_place({}, _terminal(1))
    assert state["turns"][TURN]["status"] == "completed"

    resumed = RunItemEvent(
        kind="status",
        thread_id=THREAD,
        turn_id=f"{THREAD}:turn:2",
        item_id=f"{THREAD}:turn:2:running",
        status="running",
        seq=2,
        payload={"status": "running"},
    )
    state = apply_run_item_event_in_place(state, resumed)

    assert state["turns"][f"{THREAD}:turn:2"]["status"] == "running"
