"""Super-agent 产品化验收：用户交付目标 → 排期 → 执行 → 结果回到工单。

user:“让用户能够直接交付复杂目标，由 Super-agent 自主规划、拆解、委派、执行、监控、
处理异常、恢复任务、验证成果并完成交付”+(这条链路必须端到端走通：工单不能停在 running，
执行必须真的落在独立工作树里，失败必须带着原因落到 blocked)。
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from lamtools_core.superagent import (
    InMemorySuperagentStore,
    PolicyConfig,
    PolicyGate,
    SuperagentService,
    WorktreeManager,
)


def _make_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=root, check=True, capture_output=True
    )
    return root


def _service(repo: Path, data_dir: Path) -> SuperagentService:
    return SuperagentService(
        store=InMemorySuperagentStore(),
        policy=PolicyGate(PolicyConfig(version="policy.test")),
        worktree_manager=WorktreeManager(data_dir / "wt", allowed_repo_roots=(str(repo),)),
    )


@pytest.mark.asyncio
async def test_user_goal_runs_in_isolated_worktree_and_returns_to_review(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    service = _service(repo, tmp_path / "data")
    seen: dict[str, str] = {}

    async def scheduler(ticket):
        # 这里复刻真实装配：排期前先备好执行现场，再把它交给 Arrange。
        plan = await service.begin_execution(ticket.ticket_id, model_id="test/model-1")
        seen["work_root"] = plan.work_root
        seen["branch"] = plan.branch
        seen["prompt"] = plan.prompt
        return "arrange_job_1"

    service.scheduler = scheduler

    result = await service.submit_goal(
        "给这个仓库加一个 hello 函数并补一条测试", repo_root=str(repo)
    )
    assert result.status == "accepted", result.reason

    ticket = await service.get_ticket(result.ticket_id)
    assert ticket is not None
    assert ticket.stage == "running"
    assert ticket.job_id == "arrange_job_1"
    assert ticket.assignment_id

    # 执行必须落在独立工作树里，不能直接改用户当前检出。
    work_root = Path(seen["work_root"])
    assert work_root.exists() and work_root != repo
    assert seen["branch"].startswith("ticket/")
    assert "独立分支" in seen["prompt"]
    assert "write_checklist" in seen["prompt"]
    assert "sub_agent" in seen["prompt"]
    assert "test/model-1" in seen["prompt"]

    # 执行完成后结果要回到工单。
    updated = await service.record_execution_result(
        result.ticket_id,
        status="completed",
        summary="加了 hello 函数并通过测试",
        report={"files": ["app.py", "test_app.py"]},
    )
    assert updated is not None
    assert updated.stage == "review"
    assert updated.result["summary"] == "加了 hello 函数并通过测试"
    assert updated.result["files"] == ["app.py", "test_app.py"]

    assignments = await service.list_assignments(result.ticket_id)
    assert len(assignments) == 1
    assert assignments[0].status == "completed"
    assert assignments[0].worktree_path == seen["work_root"]


@pytest.mark.asyncio
async def test_failed_execution_blocks_the_ticket_with_a_reason(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    service = _service(repo, tmp_path / "data")

    async def scheduler(ticket):
        await service.begin_execution(ticket.ticket_id)
        return "arrange_job_2"

    service.scheduler = scheduler
    result = await service.submit_goal("做一件会失败的事", repo_root=str(repo))
    assert result.status == "accepted"

    updated = await service.record_execution_result(
        result.ticket_id,
        status="failed",
        error="模型流中断",
        report={"attempts": 1},
    )
    assert updated is not None
    assert updated.stage == "blocked"
    assert "assignment-failed" in updated.decision_reason
    assert updated.result["error"] == "模型流中断"


@pytest.mark.asyncio
async def test_same_active_goal_is_not_queued_twice(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    service = _service(repo, tmp_path / "data")
    scheduled: list[str] = []

    async def scheduler(ticket):
        scheduled.append(ticket.ticket_id)
        return "job"

    service.scheduler = scheduler
    first = await service.submit_goal("同一件事", repo_root=str(repo))
    second = await service.submit_goal("同一件事", repo_root=str(repo))

    assert first.status == "accepted"
    assert second.status == "duplicate"
    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_goal_outside_allowed_repo_is_rejected(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    other = _make_repo(tmp_path / "other")
    service = SuperagentService(
        store=InMemorySuperagentStore(),
        policy=PolicyGate(PolicyConfig(allowed_repos=frozenset({str(repo)}))),
    )
    result = await service.submit_goal("越权目标", repo_root=str(other))
    assert result.status == "rejected"
    assert "repo-not-allowed" in result.reason


@pytest.mark.asyncio
async def test_retry_requeues_a_blocked_ticket(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    service = _service(repo, tmp_path / "data")
    jobs: list[str] = []

    async def scheduler(ticket):
        await service.begin_execution(ticket.ticket_id)
        jobs.append(ticket.ticket_id)
        return f"job-{len(jobs)}"

    service.scheduler = scheduler
    result = await service.submit_goal("需要重试的目标", repo_root=str(repo))
    await service.record_execution_result(result.ticket_id, status="failed", error="临时故障")
    blocked = await service.get_ticket(result.ticket_id)
    assert blocked is not None and blocked.stage == "blocked"

    retried = await service.retry_ticket(result.ticket_id)
    assert retried.stage == "running"
    assert retried.job_id == "job-2"
    assert len(jobs) == 2


@pytest.mark.asyncio
async def test_close_marks_the_ticket_delivered(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    service = _service(repo, tmp_path / "data")

    async def scheduler(ticket):
        await service.begin_execution(ticket.ticket_id)
        return "job"

    service.scheduler = scheduler
    result = await service.submit_goal("做完等验收", repo_root=str(repo))
    await service.record_execution_result(result.ticket_id, status="completed", summary="好了")

    closed = await service.close_ticket(result.ticket_id, accepted=True, note="验收通过")
    assert closed.stage == "closed"
    assert closed.decision_reason == "closed-by-user:验收通过"


@pytest.mark.asyncio
async def test_non_git_directory_runs_in_place(tmp_path: Path) -> None:
    """用户把普通目录交给 Super-agent 时，没有工作树也不能直接失败。"""
    plain = tmp_path / "plain"
    plain.mkdir()
    service = SuperagentService(
        store=InMemorySuperagentStore(),
        policy=PolicyGate(PolicyConfig()),
        worktree_manager=WorktreeManager(tmp_path / "wt"),
    )

    async def scheduler(ticket):
        plan = await service.begin_execution(ticket.ticket_id)
        assert plan.work_root == str(plain)
        assert plan.branch == ""
        return "job"

    service.scheduler = scheduler
    result = await service.submit_goal("整理一下这个目录", repo_root=str(plain))
    assert result.status == "accepted"
    ticket = await service.get_ticket(result.ticket_id)
    assert ticket is not None and ticket.stage == "running"
