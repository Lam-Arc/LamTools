"""「以默认应用打开」后窗口置前：轮询节奏、Alt 解前台锁、超时兜底。

user:“‘以默认应用打开’后窗口不再最上层，还要单独翻任务栏”
+(验收：① 窗口一出现就置前，不多等到超时；② 置前失败会先敲 Alt 解前台锁再试；
③ 3 秒内搞不定要闪任务栏而不是静默；④ 只在这一次主动置前，之后不再抢焦点)。
"""

from __future__ import annotations

import pytest

from lamtools_core.attachment import window_foreground as wf


class FakeClock:
    """可推进的假时钟：``sleep`` 只推进时间，不真的等。"""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps = 0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.now += seconds


def test_plan_defaults_keep_the_wait_short():
    plan = wf.ForegroundPlan()
    assert 0 < plan.timeout <= 3.0
    assert 0 < plan.interval < plan.nudge_after < plan.timeout


@pytest.mark.parametrize(
    ("elapsed", "nudges", "expected"),
    [
        (0.0, 0, False),
        (0.49, 0, False),
        (0.5, 0, True),
        (0.5, 1, False),
        (1.0, 1, True),
        (1.0, 2, False),
        (5.0, 2, False),
    ],
)
def test_should_nudge_is_rate_limited(elapsed: float, nudges: int, expected: bool):
    assert wf.should_nudge(elapsed, nudges, wf.ForegroundPlan()) is expected


def test_should_give_up_only_after_the_timeout():
    plan = wf.ForegroundPlan()
    assert wf.should_give_up(plan.timeout - 0.01, plan) is False
    assert wf.should_give_up(plan.timeout, plan) is True


def test_window_is_raised_as_soon_as_it_appears():
    clock = FakeClock()
    seen: list[int] = []

    calls = {"count": 0}

    def find_window() -> int | None:
        calls["count"] += 1
        return 1234 if calls["count"] >= 3 else None

    result = wf.await_foreground(
        find_window=find_window,
        raise_window=lambda hwnd: seen.append(hwnd) is None or True,
        clock=clock.clock,
        sleep=clock.sleep,
        plan=wf.ForegroundPlan(),
    )
    assert result.outcome == "foreground"
    assert result.raised is True
    assert result.window == 1234
    assert seen == [1234]
    # 第三次轮询就成功，不该拖到超时。
    assert result.elapsed < wf.ForegroundPlan().timeout


def test_stubborn_window_gets_an_alt_nudge_before_retrying():
    clock = FakeClock()
    nudges: list[int] = []
    attempts: list[int] = []

    def raise_window(hwnd: int) -> bool:
        attempts.append(hwnd)
        # 敲过 Alt 之后才允许成功（模拟前台锁被解除）。
        return bool(nudges)

    result = wf.await_foreground(
        find_window=lambda: 42,
        raise_window=raise_window,
        nudge=lambda: nudges.append(len(nudges)),
        clock=clock.clock,
        sleep=clock.sleep,
        plan=wf.ForegroundPlan(),
    )
    assert result.outcome == "foreground"
    assert result.nudges == 1
    assert len(attempts) >= 1
    assert result.elapsed <= wf.ForegroundPlan().timeout


def test_timeout_flashes_the_taskbar_instead_of_staying_silent():
    clock = FakeClock()
    flashed: list[int | None] = []
    result = wf.await_foreground(
        find_window=lambda: 7,
        raise_window=lambda _hwnd: False,
        nudge=lambda: None,
        flash=flashed.append,
        clock=clock.clock,
        sleep=clock.sleep,
        plan=wf.ForegroundPlan(timeout=1.0, interval=0.1, nudge_after=0.3, max_nudges=1),
    )
    assert result.outcome == "flashed"
    assert result.raised is False
    assert flashed == [7]
    assert result.elapsed >= 1.0 - 1e-9
    assert result.message


def test_missing_window_still_flashes_and_does_not_loop_forever():
    clock = FakeClock()
    flashed: list[int | None] = []
    result = wf.await_foreground(
        find_window=lambda: None,
        raise_window=lambda _hwnd: pytest.fail("没有窗口时不该尝试置前"),
        flash=flashed.append,
        clock=clock.clock,
        sleep=clock.sleep,
        plan=wf.ForegroundPlan(timeout=0.5, interval=0.05, nudge_after=0.2, max_nudges=1),
    )
    assert result.outcome == "flashed"
    assert flashed == [None]
    assert result.window is None
    assert result.elapsed >= 0.5 - 1e-9


def test_without_flash_it_reports_giving_up():
    clock = FakeClock()
    result = wf.await_foreground(
        find_window=lambda: 9,
        raise_window=lambda _hwnd: False,
        clock=clock.clock,
        sleep=clock.sleep,
        plan=wf.ForegroundPlan(timeout=0.2, interval=0.05, nudge_after=0.1, max_nudges=1),
    )
    assert result.outcome == "gave-up"
    assert result.raised is False


def test_result_serialises_for_the_http_response():
    payload = wf.ForegroundResult(outcome="foreground", window=5, elapsed=0.123456, pid=88).to_dict()
    assert payload["raised"] is True
    assert payload["elapsed"] == 0.123
    assert payload["pid"] == 88
