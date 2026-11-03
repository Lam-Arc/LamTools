"""Shared pytest fixtures for LamTools Core."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from functools import wraps
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def loopback_test_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model local socket peers explicitly for existing in-process app tests.

    Starlette's synthetic default is the hostname 'testclient', which cannot
    establish socket trust. Tests specifying a remote/unknown peer retain it.
    This changes only the test transport, never the production access policy.
    """
    from starlette.testclient import TestClient

    original = TestClient.__init__

    @wraps(original)
    def initialize(self, *args, **kwargs):
        if len(args) < 10:
            kwargs.setdefault("client", ("127.0.0.1", 50000))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", initialize)


@pytest.fixture
def instant_model_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Avoid wall-clock backoff only in tests explicitly opting into this.

    Keep the real retry classification, attempts, events, and exhaustion.
    Patch the injected sleeper at assembly points, never asyncio.sleep or
    product defaults, so timers and dedicated retry tests remain unchanged.
    """
    from lamtools_core.kernel import loop
    from lamtools_core.app import session_autotitle

    sleeper = AsyncMock()

    def inject_sleep(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            kwargs["sleep"] = sleeper
            return function(*args, **kwargs)
        return wrapped

    for module, names in (
        (loop, ("complete_with_retry", "stream_with_retry")),
        (session_autotitle, ("complete_with_retry",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, inject_sleep(getattr(module, name)))
    return sleeper


@pytest.fixture(autouse=True)
def isolated_config_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every config root at a temp location and return the unified
    config directory (``.lam/core/config``).

    Autouse: LAMTOOLS_CORE_CONFIG_ROOT pins the unified config dir and
    LAMTOOLS_HOME pins the legacy ``{lam_home}/config`` fallback for *every*
    test. Without this, anything writing a global-scope config (model
    migration, sub-agent guide, AGENTS.md, …) would leak into the developer's
    real ``~/.lam`` or repo ``.lam/core`` directories.
    """
    lam = tmp_path / "lam"
    monkeypatch.setenv("LAMTOOLS_CORE_CONFIG_ROOT", str(lam / "core"))
    monkeypatch.setenv("LAMTOOLS_HOME", str(lam))
    return lam / "core" / "config"


# ---------------------------------------------------------------------------
# 本地技能目录夹具
# ---------------------------------------------------------------------------

_AGENT_SKILLS_REL = Path(".agents") / "skills"


def _candidate_skill_roots(root: Path) -> list[Path]:
    """找出所有可能已经有 .agents/skills 的检出目录（主仓库 + 各工作树）。"""
    roots = [root]
    try:
        output = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if output.returncode == 0:
            for line in output.stdout.splitlines():
                if line.startswith("worktree "):
                    roots.append(Path(line[len("worktree "):].strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    return roots


def _ensure_agent_skills(root: Path) -> str:
    """保证 .agents/skills 存在；返回来源说明，用于失败时提示。"""
    target = root / _AGENT_SKILLS_REL
    if (target / "release-lamtools" / "SKILL.md").is_file():
        return "present"
    for candidate in _candidate_skill_roots(root):
        source = candidate / _AGENT_SKILLS_REL
        if source.resolve() == target.resolve():
            continue
        if not (source / "release-lamtools" / "SKILL.md").is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(source, target, dirs_exist_ok=True)
        except OSError:
            continue
        if (target / "release-lamtools" / "SKILL.md").is_file():
            return f"copied from {candidate}"
    return "missing"


@pytest.fixture(scope="session", autouse=True)
def _agent_skills_available() -> None:
    """user:“修复 .agents/skills 在独立工作树中的测试夹具问题，保证测试环境可自动准备，
    不依赖手动复制”+(.agents/ 被 gitignore，工作树里本来没有；这里从任意已有检出复制，
    找不到就明确报错，而不是让收集阶段抛一个看不懂的 FileNotFoundError)。
    """
    root = Path(__file__).resolve().parents[2]
    status = _ensure_agent_skills(root)
    if status == "missing":
        pytest.fail(
            "缺少 .agents/skills/release-lamtools/SKILL.md：请在任意一次检出里准备该目录，"
            "或从主工作区复制到当前检出的 .agents/skills（测试会尝试自动复制）。",
            pytrace=False,
        )
