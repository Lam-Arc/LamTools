"""引导的 run id 两种写法必须对得上。

2026-10-09 的丢引导故障：`turn/steer`（以及队列引导）按对外的
`<thread>:turn:<run>` 把引导存进登记表，而内核按运行输入里的短 `<run>` 去取，
两侧写法不同、按原文比较永远对不上——引导被接受、事件也落库，模型却一句都收不到，
一轮里跑了好几个 step 都没生效。
"""

from __future__ import annotations

import asyncio

from lamtools_core.runtime import RuntimeTaskRegistry, normalize_run_id


async def _register_idle_run(
    registry: RuntimeTaskRegistry,
    thread_id: str,
    run_id: str,
) -> asyncio.Task[None]:
    async def _idle() -> None:
        await asyncio.sleep(60)

    task = asyncio.create_task(_idle())
    assert registry.register(thread_id, task, run_id=run_id) is True
    return task


async def _stop(task: asyncio.Task[None]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def test_normalize_run_id_folds_the_turn_prefix():
    assert normalize_run_id("thread-1", "thread-1:turn:run-abc") == "run-abc"
    assert normalize_run_id("thread-1", "run-abc") == "run-abc"
    # 别的会话的前缀不该被剥掉
    assert normalize_run_id("thread-1", "thread-2:turn:run-abc") == "thread-2:turn:run-abc"
    assert normalize_run_id("thread-1", "") == ""


async def test_guidance_survives_both_run_id_spellings():
    registry = RuntimeTaskRegistry()
    thread_id = "thread-1"
    canonical = f"{thread_id}:turn:run-abc"
    task = await _register_idle_run(registry, thread_id, canonical)
    try:
        # 存：对外写法（turn/steer 用的）；取：内核运行输入里的短写法
        assert registry.accept_guidance(
            thread_id, "改成蓝色", run_id=canonical, guidance_id="g-1"
        ) == "accepted"
        assert registry.consume_guidance(thread_id, run_id="run-abc") == ["改成蓝色"]

        # 反过来也要成立
        assert registry.accept_guidance(
            thread_id, "再快一点", run_id="run-abc", guidance_id="g-2"
        ) == "accepted"
        assert registry.consume_guidance(thread_id, run_id=canonical) == ["再快一点"]

        # 别的 round 不能被顺手取走
        assert registry.consume_guidance(thread_id, run_id="other-run") == []
        assert registry.accept_guidance(
            thread_id, "给别人的", run_id="other-run", guidance_id="g-3"
        ) == "not_active"
    finally:
        await _stop(task)


async def test_close_guidance_if_empty_accepts_both_spellings():
    registry = RuntimeTaskRegistry()
    thread_id = "thread-1"
    canonical = f"{thread_id}:turn:run-xyz"
    task = await _register_idle_run(registry, thread_id, canonical)
    try:
        assert registry.accept_guidance(
            thread_id, "换个做法", run_id=canonical, guidance_id="g-1"
        ) == "accepted"
        # 收尾阶段（finalize）用短写法也要能取到，否则最后一步的引导同样会丢
        assert registry.close_guidance_if_empty(thread_id, run_id="run-xyz") == ["换个做法"]
    finally:
        await _stop(task)
