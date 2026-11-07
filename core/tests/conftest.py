"""Shared pytest fixtures for LamTools Core."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from functools import wraps
from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# 源码绑定守卫
# ---------------------------------------------------------------------------
#
# user:“所有测试统一绑定当前工作树源码，执行前自动核验模块路径与提交 SHA，
# 不一致直接失败”+(一次会话只能测本检出 core/src 的代码。加载到别的检出、
# 或让一个与 HEAD 不符的脏工作树冒充同一个提交，都必须在收集阶段终止，
# 而不是给出一份看起来通过、其实测的是别处代码的结果)。
#
# 背景：可编辑安装把主工作区的 core/src 放进了 sys.path，于是从工作树直接跑
# pytest 时，测试文件来自本分支、被测代码来自另一条分支。

_EXPECTED_SRC = (Path(__file__).resolve().parents[1] / "src").resolve()
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_GUARD_KEY = pytest.StashKey[tuple[Path, str, str]]()


def _git_output(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _bound_source_root() -> Path | None:
    import lamtools_core

    location = getattr(lamtools_core, "__file__", None)
    return Path(location).resolve().parent if location else None


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("lamtools")
    group.addoption(
        "--expect-sha",
        action="store",
        default="",
        help="Fail unless HEAD starts with this commit SHA (acceptance runs).",
    )
    group.addoption(
        "--allow-dirty",
        action="store_true",
        default=False,
        help="Allow uncommitted changes under core/src (development runs).",
    )


def pytest_configure(config: pytest.Config) -> None:
    loaded = _bound_source_root()
    if loaded is None or not loaded.is_relative_to(_EXPECTED_SRC):
        pytest.exit(
            "测试源码未绑定本检出：\n"
            f"  期望：{_EXPECTED_SRC}\n"
            f"  实际：{loaded}\n"
            "可编辑安装指向了别的检出（通常是主工作区）。显式绑定源码后重跑：\n"
            f'  PYTHONPATH="{_EXPECTED_SRC}" python -m pytest <paths>',
            returncode=2,
        )
    head = _git_output("rev-parse", "HEAD") or "unknown"
    dirty = _git_output("status", "--porcelain", "--", str(_EXPECTED_SRC)) or ""
    expected = str(config.getoption("--expect-sha") or "").strip()
    if expected and not head.startswith(expected):
        pytest.exit(
            f"提交 SHA 不匹配：期望 {expected}，当前 {head}。",
            returncode=2,
        )
    if dirty and not config.getoption("--allow-dirty"):
        pytest.exit(
            "core/src 有未提交改动，当前 HEAD 不代表被测代码：\n"
            f"{dirty}\n"
            "提交后重跑；开发中确需如此时加 --allow-dirty。",
            returncode=2,
        )
    config.stash[_SOURCE_GUARD_KEY] = (loaded, head, dirty)


def pytest_report_header(config: pytest.Config) -> list[str]:
    stashed = config.stash.get(_SOURCE_GUARD_KEY, None)
    if stashed is None:
        return []
    loaded, head, dirty = stashed
    return [f"lamtools source: {loaded} @ {head[:12]} ({'dirty' if dirty else 'clean'})"]



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
