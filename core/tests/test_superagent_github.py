"""GitHub 发布：先查后建、幂等、授权边界。

user:“将推送分支和创建 PR 变成可控、可追踪、可重试的确定性操作”“根据仓库、源分支、
目标分支查询已有 PR，避免重复创建”“网络超时后能够核对实际结果并安全重试”“未获得明确
授权时不推送、不创建 PR”
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from lamtools_core.superagent import (
    EffectOutbox,
    GithubCliAdapter,
    GithubError,
    InMemorySuperagentStore,
    PolicyConfig,
    PolicyGate,
    PublishTarget,
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


# ---------------------------------------------------------------------------
# 适配器本身：只读查询与真实写入分开
# ---------------------------------------------------------------------------


class _Recorder:
    def __init__(self, responses: dict[tuple[str, ...], tuple[int, str, str]]) -> None:
        self.responses = responses
        self.calls: list[list[str]] = []

    async def __call__(self, args: list[str], cwd: str, timeout: float):
        self.calls.append(list(args))
        return self.responses.get(tuple(args), (1, "", "unexpected command"))


@pytest.mark.asyncio
async def test_lookup_push_treats_matching_remote_sha_as_done(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    runner = _Recorder(
        {
            ("git", "rev-parse", "HEAD"): (0, head + "\n", ""),
            ("git", "ls-remote", "--heads", "origin", "ticket/t1"): (
                0,
                f"{head}\trefs/heads/ticket/t1\n",
                "",
            ),
        }
    )
    adapter = GithubCliAdapter(runner=runner)
    ref = await adapter.lookup_push(
        PublishTarget(repo_root=str(repo), branch="ticket/t1")
    )
    assert ref == "origin/ticket/t1"


@pytest.mark.asyncio
async def test_lookup_push_pushes_when_remote_is_behind(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    runner = _Recorder(
        {
            ("git", "rev-parse", "HEAD"): (0, "aaaa\n", ""),
            ("git", "ls-remote", "--heads", "origin", "ticket/t1"): (
                0,
                "bbbb\trefs/heads/ticket/t1\n",
                "",
            ),
        }
    )
    adapter = GithubCliAdapter(runner=runner)
    ref = await adapter.lookup_push(
        PublishTarget(repo_root=str(repo), branch="ticket/t1")
    )
    assert ref is None, "远端停在旧提交时必须继续推送"


@pytest.mark.asyncio
async def test_lookup_pr_finds_an_existing_pr(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    runner = _Recorder(
        {
            (
                "gh",
                "pr",
                "list",
                "--head",
                "ticket/t1",
                "--base",
                "main",
                "--state",
                "all",
                "--limit",
                "5",
                "--json",
                "url,state,number",
            ): (0, '[{"url":"https://example.test/pr/1","state":"OPEN","number":1}]', ""),
        }
    )
    adapter = GithubCliAdapter(runner=runner)
    ref = await adapter.lookup_pr(
        PublishTarget(repo_root=str(repo), branch="ticket/t1", base_branch="main")
    )
    assert ref == "https://example.test/pr/1"


@pytest.mark.asyncio
async def test_perform_pr_recovers_when_create_fails_but_pr_exists(tmp_path: Path) -> None:
    """超时或并发之后重试：创建报错，但远端已经有同一个 PR，就用它。"""
    repo = _make_repo(tmp_path / "repo")
    create_args = (
        "gh",
        "pr",
        "create",
        "--head",
        "ticket/t1",
        "--base",
        "main",
        "--title",
        "标题",
        "--body",
        "正文",
    )
    list_args = (
        "gh",
        "pr",
        "list",
        "--head",
        "ticket/t1",
        "--base",
        "main",
        "--state",
        "all",
        "--limit",
        "5",
        "--json",
        "url,state,number",
    )
    runner = _Recorder(
        {
            create_args: (1, "", "a pull request for branch already exists"),
            list_args: (0, '[{"url":"https://example.test/pr/9","state":"OPEN","number":9}]', ""),
        }
    )
    adapter = GithubCliAdapter(runner=runner)
    url = await adapter.perform_pr(
        PublishTarget(
            repo_root=str(repo), branch="ticket/t1", base_branch="main", title="标题", body="正文"
        )
    )
    assert url == "https://example.test/pr/9"


@pytest.mark.asyncio
async def test_adapter_refuses_an_empty_branch(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    adapter = GithubCliAdapter(runner=_Recorder({}))
    with pytest.raises(GithubError):
        await adapter.perform_push(PublishTarget(repo_root=str(repo), branch=""))


# ---------------------------------------------------------------------------
# 服务层：授权边界、幂等、回写
# ---------------------------------------------------------------------------


class _FakeGithub:
    """记录调用次数的假适配器，行为与真实适配器一致：先查后建。"""

    def __init__(self) -> None:
        self.pushes: list[str] = []
        self.created: list[str] = []
        self.existing: dict[str, str] = {}
        self.fail_first_create = False

    async def lookup(self, effect):
        key = f"{effect.kind}:{effect.idempotency_key}"
        return self.existing.get(key)

    async def perform(self, effect):
        key = f"{effect.kind}:{effect.idempotency_key}"
        if effect.kind == "push":
            self.pushes.append(effect.idempotency_key)
            return f"origin/{effect.payload.get('branch')}"
        if self.fail_first_create:
            self.fail_first_create = False
            # 远端其实建成功了，客户端只看到异常。
            self.existing[key] = "https://example.test/pr/42"
            raise TimeoutError("response timed out")
        self.created.append(effect.idempotency_key)
        self.existing[key] = "https://example.test/pr/42"
        return "https://example.test/pr/42"

    async def pr_status(self, url: str, *, repo_root: str):
        return {"url": url, "state": "OPEN", "number": 42}


def _service(repo: Path, data: Path, github: _FakeGithub, store) -> SuperagentService:
    return SuperagentService(
        store=store,
        policy=PolicyGate(PolicyConfig(version="policy.test")),
        worktree_manager=WorktreeManager(data / "wt", allowed_repo_roots=(str(repo),)),
        outbox=EffectOutbox(store),
        github=github,
    )


async def _ticket_with_branch(service: SuperagentService, repo: Path, *, push: bool, pr: bool):
    async def scheduler(ticket):
        await service.begin_execution(ticket.ticket_id)
        return "job-1"

    service.scheduler = scheduler
    result = await service.submit_goal(
        "做一件要发布的事", repo_root=str(repo), can_push=push, can_create_pr=pr
    )
    assert result.status == "accepted"
    return result.ticket_id


@pytest.mark.asyncio
async def test_publish_without_authorization_touches_nothing(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    github = _FakeGithub()
    store = InMemorySuperagentStore()
    service = _service(repo, tmp_path / "data", github, store)
    ticket_id = await _ticket_with_branch(service, repo, push=False, pr=False)

    outcome = await service.publish(ticket_id)

    assert outcome["push"]["status"] == "skipped"
    assert outcome["pr"]["status"] == "skipped"
    assert github.pushes == [] and github.created == []


@pytest.mark.asyncio
async def test_publish_pushes_and_opens_one_pr(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    github = _FakeGithub()
    store = InMemorySuperagentStore()
    service = _service(repo, tmp_path / "data", github, store)
    ticket_id = await _ticket_with_branch(service, repo, push=True, pr=True)

    outcome = await service.publish(ticket_id, title="标题")

    assert outcome["push"]["status"] == "done"
    assert outcome["pr"]["status"] == "done"
    assert outcome["pr"]["remote_ref"] == "https://example.test/pr/42"
    assert outcome["pr_state"] == "OPEN"
    ticket = await service.get_ticket(ticket_id)
    assert ticket is not None
    assert ticket.result["pr_url"] == "https://example.test/pr/42"
    assert ticket.result["pr_state"] == "OPEN"


@pytest.mark.asyncio
async def test_publish_twice_does_not_open_a_second_pr(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    github = _FakeGithub()
    store = InMemorySuperagentStore()
    service = _service(repo, tmp_path / "data", github, store)
    ticket_id = await _ticket_with_branch(service, repo, push=True, pr=True)

    first = await service.publish(ticket_id)
    second = await service.publish(ticket_id)

    assert first["pr"]["remote_ref"] == second["pr"]["remote_ref"]
    assert len(github.created) == 1, "重复发布不该建第二个 PR"
    assert len(github.pushes) == 1


@pytest.mark.asyncio
async def test_publish_recovers_from_a_timeout_without_duplicating(tmp_path: Path) -> None:
    """第一次创建超时但远端已成功：重试必须先查后建，不能再建一个。"""
    repo = _make_repo(tmp_path / "repo")
    github = _FakeGithub()
    github.fail_first_create = True
    store = InMemorySuperagentStore()
    service = _service(repo, tmp_path / "data", github, store)
    ticket_id = await _ticket_with_branch(service, repo, push=True, pr=True)

    outcome = await service.publish(ticket_id)

    assert outcome["pr"]["status"] == "done"
    assert outcome["pr"]["remote_ref"] == "https://example.test/pr/42"
    assert github.created == [], "超时之后应当先查远端，而不是再建一个 PR"


@pytest.mark.asyncio
async def test_publish_requires_a_branch(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    github = _FakeGithub()
    store = InMemorySuperagentStore()
    service = SuperagentService(
        store=store,
        policy=PolicyGate(PolicyConfig()),
        outbox=EffectOutbox(store),
        github=github,
    )

    async def scheduler(ticket):
        return "job"

    service.scheduler = scheduler
    result = await service.submit_goal("没有工作树的目标", repo_root=str(repo), can_push=True)
    with pytest.raises(ValueError):
        await service.publish(result.ticket_id)
