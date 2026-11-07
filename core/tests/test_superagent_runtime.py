"""Super-agent 验收：授权、去重、幂等副作用、工作树隔离、工单状态机。

user:“所有未经授权的仓库写操作必须被拒绝；外部 PR、评论等副作用不得因超时重试而重复创建”
+(这些是硬闸门，测试必须直接验证行为，不允许用"模型说它会做"替代)。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess

import pytest

from lamtools_core.superagent import (
    EffectOutbox,
    InMemorySuperagentStore,
    Mandate,
    PolicyConfig,
    PolicyGate,
    SourceActor,
    SourceEvent,
    SuperagentService,
    WorktreeManager,
)

REPO = str(Path("test-repo").resolve())


def _config(**overrides) -> PolicyConfig:
    base = dict(
        allowed_sources=frozenset({"github"}),
        allowed_event_types=frozenset({"issue.opened", "issue.comment"}),
        trusted_actors=frozenset({"alice"}),
        allowed_repos=frozenset({REPO}),
        allow_create_pr=True,
        version="policy.test",
    )
    base.update(overrides)
    return PolicyConfig(**base)


def _event(
    *,
    event_id: str = "evt-1",
    event_type: str = "issue.opened",
    actor: str = "alice",
    trusted: bool = True,
    repo: str = REPO,
    text: str = "修复登录按钮点击无响应",
    payload_extra: dict | None = None,
) -> SourceEvent:
    payload = {"text": text, **(payload_extra or {})}
    return SourceEvent(
        source_id="github",
        event_id=event_id,
        event_type=event_type,
        actor=SourceActor(actor_id=actor, login=actor, trusted=trusted),
        payload=payload,
        repo=repo,
        thread_key=f"issue:{event_id}",
    )


def _service(*, scheduler=None, config: PolicyConfig | None = None, worktree=None):
    store = InMemorySuperagentStore()
    service = SuperagentService(
        store=store,
        policy=PolicyGate(config or _config()),
        scheduler=scheduler,
        worktree_manager=worktree,
    )
    return service, store


# ---------------------------------------------------------------------------
# 1. 未授权一律拒绝
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_untrusted_actor_cannot_create_ticket() -> None:
    service, _ = _service()
    result = await service.handle_event(_event(trusted=False))
    assert result.status == "rejected"
    assert "actor-not-trusted" in result.reason
    assert await service.list_tickets() == []


@pytest.mark.asyncio
async def test_unlisted_repo_is_rejected() -> None:
    service, _ = _service()
    result = await service.handle_event(_event(repo=str(Path("other-repo").resolve())))
    assert result.status == "rejected"
    assert "repo-not-allowed" in result.reason


@pytest.mark.asyncio
async def test_empty_policy_denies_everything() -> None:
    service, _ = _service(config=PolicyConfig())
    result = await service.handle_event(_event())
    assert result.status == "rejected"
    assert result.reason == "no-source-authorized"


@pytest.mark.asyncio
async def test_high_risk_action_in_payload_goes_to_human() -> None:
    """事件正文要求推送/合并只触发人工确认，不自动获得权限。"""
    service, _ = _service()
    result = await service.handle_event(
        _event(payload_extra={"requested_actions": ["merge"]})
    )
    assert result.status == "ask_human"
    ticket = await service.get_ticket(result.ticket_id)
    assert ticket is not None
    assert ticket.stage == "blocked"
    assert ticket.mandate.can_push is False


# ---------------------------------------------------------------------------
# 2. 重复投递与冲突
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_event_delivered_100_times_creates_one_ticket() -> None:
    scheduled: list[str] = []

    async def scheduler(ticket):
        scheduled.append(ticket.ticket_id)
        return "job-1"

    service, _ = _service(scheduler=scheduler)
    # 必须是「同一个事件重复投递」，所以复用同一个对象（含同一个 occurred_at）。
    event = _event()
    results = [await service.handle_event(event) for _ in range(100)]

    tickets = await service.list_tickets()
    assert len(tickets) == 1
    assert results[0].status == "accepted"
    assert all(item.status in {"duplicate", "accepted"} for item in results)
    assert len(set(item.ticket_id for item in results)) == 1
    assert len(scheduled) == 1, "同一事件被排期了多次"


@pytest.mark.asyncio
async def test_same_event_id_with_different_content_is_rejected() -> None:
    service, _ = _service()
    first = await service.handle_event(_event())
    assert first.status == "accepted"
    second = await service.handle_event(_event(text="完全不同的内容"))
    assert second.status == "rejected"
    assert second.reason == "conflicting-event-id"
    assert len(await service.list_tickets()) == 1


# ---------------------------------------------------------------------------
# 3. 副作用幂等：远端已成功但客户端超时，不得重复创建
# ---------------------------------------------------------------------------


class _FlakyAdapter:
    def __init__(self) -> None:
        self.perform_calls = 0
        self.created: dict[str, str] = {}
        self.remote_state: dict[str, str] = {}

    async def lookup(self, effect):
        return self.remote_state.get(effect.idempotency_key)

    async def perform(self, effect):
        self.perform_calls += 1
        # 第一次"成功创建但响应超时"：远端有资源，客户端只看到异常。
        self.remote_state[effect.idempotency_key] = f"pr:{effect.idempotency_key}"
        raise TimeoutError("response timed out")


@pytest.mark.asyncio
async def test_effect_outbox_does_not_create_duplicate_on_timeout() -> None:
    store = InMemorySuperagentStore()
    outbox = EffectOutbox(store)
    adapter = _FlakyAdapter()

    effect = await outbox.ensure(
        ticket_id="tkt-1",
        kind="create_pr",
        idempotency_key="tkt-1:pr:main",
        payload={"title": "fix"},
    )
    delivered = await outbox.deliver(effect, adapter)

    assert delivered.status == "done"
    assert delivered.remote_ref == "pr:tkt-1:pr:main"
    assert adapter.perform_calls == 1, "超时后应当先查远端，而不是再建一个 PR"


@pytest.mark.asyncio
async def test_effect_outbox_same_key_reuses_record() -> None:
    store = InMemorySuperagentStore()
    outbox = EffectOutbox(store)
    first = await outbox.ensure(ticket_id="t", kind="comment", idempotency_key="k1")
    second = await outbox.ensure(ticket_id="t", kind="comment", idempotency_key="k1")
    first_dict = first.to_dict()
    second_dict = second.to_dict()
    first_dict.pop("revision", None)
    second_dict.pop("revision", None)
    assert first_dict == second_dict


# ---------------------------------------------------------------------------
# 4. 工单状态机与 worktree 隔离
# ---------------------------------------------------------------------------


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


@pytest.mark.asyncio
async def test_two_tickets_get_isolated_worktrees(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    manager = WorktreeManager(tmp_path / "wt", allowed_repo_roots=(str(repo),))
    service = SuperagentService(
        store=InMemorySuperagentStore(),
        policy=PolicyGate(
            PolicyConfig(
                allowed_sources=frozenset({"github"}),
                allowed_event_types=frozenset({"issue.opened"}),
                trusted_actors=frozenset({"alice"}),
                allowed_repos=frozenset({str(repo)}),
                version="policy.test",
            )
        ),
        worktree_manager=manager,
    )
    event_a = SourceEvent(
        source_id="github",
        event_id="a",
        event_type="issue.opened",
        actor=SourceActor("alice", "alice", True),
        payload={"text": "修 A"},
        repo=str(repo),
    )
    event_b = SourceEvent(
        source_id="github",
        event_id="b",
        event_type="issue.opened",
        actor=SourceActor("alice", "alice", True),
        payload={"text": "修 B"},
        repo=str(repo),
    )
    assert (await service.handle_event(event_a)).status == "accepted"
    assert (await service.handle_event(event_b)).status == "accepted"

    tickets = await service.list_tickets()
    assert len(tickets) == 2
    first = await service.start_assignment(tickets[0].ticket_id, "exec-1")
    second = await service.start_assignment(tickets[1].ticket_id, "exec-2")

    assert first.worktree_path and second.worktree_path
    assert first.worktree_path != second.worktree_path
    assert first.branch != second.branch
    assert Path(first.worktree_path, "README.md").exists()
    assert Path(second.worktree_path, "README.md").exists()

    finished = await service.finish_assignment(
        first.assignment_id, status="completed", report={"patch": "diff"}
    )
    assert finished.status == "completed"
    ticket = await service.get_ticket(finished.ticket_id)
    assert ticket is not None and ticket.stage == "review"


@pytest.mark.asyncio
async def test_revoked_mandate_blocks_assignment(tmp_path: Path) -> None:
    from dataclasses import replace as dc_replace

    repo = _make_repo(tmp_path / "repo2")
    store = InMemorySuperagentStore()
    service = SuperagentService(
        store=store,
        policy=PolicyGate(
            PolicyConfig(
                allowed_sources=frozenset({"github"}),
                allowed_event_types=frozenset({"issue.opened"}),
                trusted_actors=frozenset({"alice"}),
                allowed_repos=frozenset({str(repo)}),
            )
        ),
    )
    event = SourceEvent(
        source_id="github",
        event_id="c",
        event_type="issue.opened",
        actor=SourceActor("alice", "alice", True),
        payload={"text": "做点事"},
        repo=str(repo),
    )
    result = await service.handle_event(event)
    ticket = await service.get_ticket(result.ticket_id)
    assert ticket is not None
    revoked = Ticket_with(ticket, mandate=dc_replace(ticket.mandate, revoked=True))
    await store.put("ticket", ticket.ticket_id, revoked.to_dict(), expected_revision=ticket.revision)

    with pytest.raises(PermissionError):
        await service.start_assignment(ticket.ticket_id, "exec-3")


def Ticket_with(ticket, **changes):
    from lamtools_core.superagent.models import Ticket

    data = {**ticket.to_dict(), **changes}
    if "mandate" in changes and isinstance(changes["mandate"], Mandate):
        data["mandate"] = changes["mandate"].to_dict()
    return Ticket.from_dict(data)
