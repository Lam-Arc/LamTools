"""The run mode is decided by the session's first message and never changes after.

user:“新建会话之后，在聊天区内选择，输入框上方是一个三选一的胶囊，发送第一条消息时，
定下该会话模式”“新建会话时选择好，就不可变动了”
+(模式只写一次：第一条消息把胶囊选的值写进会话，缺省 work；之后每条消息都用会话里
存的那个模式，客户端再带别的值也不生效；旧名字 consider/execute 归一成 chat/work。)
"""
from __future__ import annotations

import pytest

from lamtools_core.app.live.turn_options import _fix_session_active_mode


class _SessionStore:
    def __init__(self, metadata: dict | None = None, *, fail: bool = False) -> None:
        self.metadata = dict(metadata or {})
        self.patches: list[dict] = []
        self.fail = fail

    async def get(self, _session_id: str):
        raise AssertionError("the mode fix must not re-read the session")

    async def patch(self, _session_id: str, *, metadata=None, **_kwargs):
        if self.fail:
            raise RuntimeError("database is busy")
        self.patches.append(dict(metadata or {}))
        self.metadata = dict(metadata or {})
        return None


class _Host:
    def __init__(self, store: _SessionStore | None) -> None:
        self.session_store = store


class _Context:
    def __init__(self, store: _SessionStore | None) -> None:
        self.host = _Host(store)


@pytest.mark.asyncio
async def test_first_message_writes_the_mode_chosen_in_the_capsule():
    store = _SessionStore()
    params, chosen = await _fix_session_active_mode(
        context=_Context(store),
        thread_id="thread-mode",
        params={"active_mode": "auto"},
        session_metadata={},
    )

    assert chosen == "auto"
    assert params["active_mode"] == "auto"
    assert store.metadata["composer_state"]["active_mode"] == "auto"


@pytest.mark.asyncio
async def test_first_message_defaults_to_work_when_the_client_sends_no_mode():
    store = _SessionStore()
    params, chosen = await _fix_session_active_mode(
        context=_Context(store),
        thread_id="thread-mode",
        params={},
        session_metadata={},
    )

    assert chosen == "work"
    assert params["active_mode"] == "work"
    assert store.metadata["composer_state"]["active_mode"] == "work"


@pytest.mark.asyncio
async def test_a_session_that_already_chose_a_mode_ignores_the_request():
    store = _SessionStore({"composer_state": {"active_mode": "chat"}})
    params, chosen = await _fix_session_active_mode(
        context=_Context(store),
        thread_id="thread-mode",
        params={"active_mode": "auto"},
        session_metadata={"composer_state": {"active_mode": "chat"}},
    )

    assert chosen == "chat"
    assert params["active_mode"] == "chat"
    assert store.patches == []


@pytest.mark.asyncio
async def test_legacy_mode_names_are_normalized_when_the_mode_is_written():
    store = _SessionStore()
    _params, chosen = await _fix_session_active_mode(
        context=_Context(store),
        thread_id="thread-mode",
        params={"active_mode": "consider"},
        session_metadata={},
    )

    assert chosen == "chat"
    assert store.metadata["composer_state"]["active_mode"] == "chat"


@pytest.mark.asyncio
async def test_auxiliary_sessions_keep_the_server_side_mode():
    store = _SessionStore()
    params, chosen = await _fix_session_active_mode(
        context=_Context(store),
        thread_id="thread-aux",
        params={"active_mode": "work"},
        session_metadata={"ui_surface": "auxiliary"},
    )

    assert chosen is None
    assert params["active_mode"] == "work"
    assert store.patches == []


@pytest.mark.asyncio
async def test_a_failed_write_does_not_block_the_message():
    store = _SessionStore(fail=True)
    params, chosen = await _fix_session_active_mode(
        context=_Context(store),
        thread_id="thread-mode",
        params={"active_mode": "work"},
        session_metadata={},
    )

    assert chosen == "work"
    assert params["active_mode"] == "work"
