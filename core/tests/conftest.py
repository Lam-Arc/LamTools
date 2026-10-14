"""Shared pytest fixtures for LamTools Core."""

from __future__ import annotations

from pathlib import Path
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
