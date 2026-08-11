"""Tests for the auto-generated session title feature (session_autotitle)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lamtools_core.app.live_operations import CoreLiveContext, _auto_title_session
from lamtools_core.app.session_autotitle import (
    MAX_TITLE_LEN,
    generate_session_title,
    is_default_title,
)
from lamtools_core.http import create_core_router
from lamtools_core.llm import LLMRequest, LLMResponse
from lamtools_core.session import InMemorySessionStore, SessionRecord


class FakeLLMClient:
    def __init__(self, response: LLMResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.response or LLMResponse(content="")


class FakeHub:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, event: dict) -> None:
        self.events.append(event)


class FakeSessionStore:
    def __init__(self, existing_title: str | None = None, patch_result: object = "patched"):
        self.existing_title = existing_title
        self.patch_result = patch_result
        self.patch_calls: list[dict] = []

    async def get(self, session_id: str):
        return SimpleNamespace(title=self.existing_title)

    async def patch(self, session_id: str, *, title=None, status=None, metadata=None, only_if_title_default=False):
        self.patch_calls.append(
            {
                "session_id": session_id,
                "title": title,
                "status": status,
                "metadata": metadata,
                "only_if_title_default": only_if_title_default,
            }
        )
        return self.patch_result


def _context(*, llm: FakeLLMClient | None = None, store: FakeSessionStore | None = None, hub: FakeHub | None = None) -> CoreLiveContext:
    hub = hub or FakeHub()
    # CoreLiveContext.__post_init__ copies snapshot_store / hub /
    # runtime_task_registry / runtime_state_store off the host, so the fake
    # host must expose all of them (hub included, it wins over the ctor arg).
    host = SimpleNamespace(
        session_factory=None,
        persistence=None,
        event_store=None,
        snapshot_store=None,
        hub=hub,
        runtime_task_registry=SimpleNamespace(),
        runtime_state_store=None,
        llm_client=llm,
        default_model_id="model-x",
        session_store=store,
    )
    return CoreLiveContext(operations=SimpleNamespace(), host=host, hub=hub)


class TestIsDefaultTitle:
    def test_empty_and_none_are_default(self):
        assert is_default_title("", session_id="s1")
        assert is_default_title(None, session_id="s1")

    @pytest.mark.parametrize("title", ["new session", "新会话", "新的研究", "untitled", "core"])
    def test_default_titles(self, title: str):
        assert is_default_title(title, session_id="s1")

    def test_case_and_whitespace_insensitive(self):
        assert is_default_title("  New Session  ", session_id="s1")

    def test_bare_session_id_is_default(self):
        assert is_default_title("s1", session_id="s1")
        assert is_default_title("S1", session_id="s1")

    def test_user_title_is_not_default(self):
        assert not is_default_title("我的研究报告", session_id="s1")
        assert not is_default_title("new", session_id="s1")


class TestGenerateSessionTitle:
    async def _run(self, llm: FakeLLMClient, first_message: str = "你好世界") -> str | None:
        return await generate_session_title(llm, "model-x", first_message)

    def test_cleans_quotes_and_brackets(self):
        llm = FakeLLMClient(response=LLMResponse(content="「你好世界」"))
        assert asyncio.run(self._run(llm)) == "你好世界"

    def test_truncates_to_max_len(self):
        llm = FakeLLMClient(response=LLMResponse(content="长" * (MAX_TITLE_LEN + 10)))
        assert asyncio.run(self._run(llm)) == "长" * MAX_TITLE_LEN

    def test_collapses_internal_newlines(self):
        llm = FakeLLMClient(response=LLMResponse(content="第一行\n第二行"))
        assert asyncio.run(self._run(llm)) == "第一行 第二行"

    def test_empty_message_skips_model(self):
        llm = FakeLLMClient(response=LLMResponse(content="标题"))
        assert asyncio.run(self._run(llm, first_message="  ")) is None
        assert llm.calls == []

    def test_empty_response_is_none(self):
        llm = FakeLLMClient(response=LLMResponse(content=""))
        assert asyncio.run(self._run(llm)) is None

    def test_error_returns_none(self):
        llm = FakeLLMClient(error=RuntimeError("boom"))
        assert asyncio.run(self._run(llm)) is None

    def test_request_shape(self):
        llm = FakeLLMClient(response=LLMResponse(content="标题"))
        asyncio.run(self._run(llm))
        assert len(llm.calls) == 1
        request = llm.calls[0]
        assert request.model == "model-x"
        assert request.temperature == 0
        assert request.max_tokens == 40
        assert request.messages[0].role == "system"
        assert request.messages[1].role == "user"


class TestAutoTitleSession:
    def test_generates_and_broadcasts(self):
        hub = FakeHub()
        llm = FakeLLMClient(response=LLMResponse(content="生成的标题"))
        # Untouched session: title falls back to the bare session id.
        store = FakeSessionStore(existing_title="t1", patch_result=SimpleNamespace(title="生成的标题"))
        asyncio.run(_auto_title_session(context=_context(llm=llm, store=store, hub=hub), thread_id="t1", first_message="你好"))

        assert len(store.patch_calls) == 1
        assert store.patch_calls[0]["title"] == "生成的标题"
        assert store.patch_calls[0]["only_if_title_default"] is True
        assert hub.events == [
            {
                "method": "session/updated",
                "thread_id": "t1",
                "payload": {"session": {"title": "生成的标题"}},
            }
        ]

    def test_skips_llm_when_user_title_exists(self):
        hub = FakeHub()
        llm = FakeLLMClient(response=LLMResponse(content="生成的标题"))
        store = FakeSessionStore(existing_title="用户手动标题")
        asyncio.run(_auto_title_session(context=_context(llm=llm, store=store, hub=hub), thread_id="t1", first_message="你好"))

        assert llm.calls == []
        assert store.patch_calls == []
        assert hub.events == []

    def test_no_broadcast_when_patch_rejected(self):
        """Simulates the race: the user renamed the session while the LLM was
        generating; the conditional patch (only_if_title_default) refuses and
        returns None, so nothing is clobbered and nothing is broadcast."""
        hub = FakeHub()
        llm = FakeLLMClient(response=LLMResponse(content="生成的标题"))
        store = FakeSessionStore(existing_title="t1", patch_result=None)
        asyncio.run(_auto_title_session(context=_context(llm=llm, store=store, hub=hub), thread_id="t1", first_message="你好"))

        assert len(llm.calls) == 1
        assert len(store.patch_calls) == 1
        assert hub.events == []

    def test_no_llm_client_short_circuits(self):
        hub = FakeHub()
        store = FakeSessionStore(existing_title="t1")
        asyncio.run(_auto_title_session(context=_context(llm=None, store=store, hub=hub), thread_id="t1", first_message="你好"))

        assert store.patch_calls == []
        assert hub.events == []


class _PatchRecordingStore:
    """Minimal SessionStore-like object exposing ``patch`` (the CoreDb path)."""

    def __init__(self) -> None:
        self.record: SessionRecord | None = None
        self.patch_calls: list[dict] = []

    def create(self, session: SessionRecord) -> SessionRecord:
        self.record = session
        return session

    def get(self, session_id: str) -> SessionRecord | None:
        return self.record

    def list(self, member_id: str | None = None) -> list[SessionRecord]:
        return [self.record] if self.record is not None else []

    def update(self, session: SessionRecord) -> SessionRecord:
        self.record = session
        return session

    def delete(self, session_id: str) -> bool:
        return False

    def add_message(self, message) -> None:
        return None

    def list_messages(self, session_id: str) -> list:
        return []

    async def patch(self, session_id: str, *, title=None, status=None, metadata=None, only_if_title_default=False):
        self.patch_calls.append({"session_id": session_id, "title": title, "status": status, "metadata": metadata})
        if title is not None and self.record is not None:
            self.record.title = title
        return self.record


class TestRoutesSessionUpdatedBroadcast:
    def _client(self, publish_event, store=None) -> TestClient:
        router = create_core_router(session_store=store or InMemorySessionStore(), publish_event=publish_event)
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_rename_via_update_branch_broadcasts(self):
        events: list[dict] = []

        async def publish(event: dict) -> None:
            events.append(event)

        store = InMemorySessionStore()
        store.create(
            SessionRecord(id="s1", member_id="core", title="旧标题", status="idle")
        )
        client = self._client(publish, store=store)
        response = client.patch("/sessions/s1", json={"title": "新标题"})
        assert response.status_code == 200
        assert response.json()["title"] == "新标题"
        assert events == [
            {"method": "session/updated", "thread_id": "s1", "payload": {"session": {"title": "新标题"}}}
        ]

    def test_rename_via_patch_branch_broadcasts(self):
        events: list[dict] = []

        async def publish(event: dict) -> None:
            events.append(event)

        store = _PatchRecordingStore()
        store.create(SessionRecord(id="s1", member_id="core", title="旧标题", status="idle"))
        client = self._client(publish, store=store)
        response = client.patch("/sessions/s1", json={"title": "新标题"})
        assert response.status_code == 200
        assert len(store.patch_calls) == 1
        assert events == [
            {"method": "session/updated", "thread_id": "s1", "payload": {"session": {"title": "新标题"}}}
        ]

    def test_status_only_change_does_not_broadcast(self):
        events: list[dict] = []

        async def publish(event: dict) -> None:
            events.append(event)

        store = InMemorySessionStore()
        store.create(SessionRecord(id="s1", member_id="core", title="旧标题", status="idle"))
        client = self._client(publish, store=store)
        response = client.patch("/sessions/s1", json={"status": "running"})
        assert response.status_code == 200
        assert events == []

    def test_no_publish_event_configured(self):
        store = InMemorySessionStore()
        store.create(SessionRecord(id="s1", member_id="core", title="旧标题", status="idle"))
        client = self._client(None, store=store)
        response = client.patch("/sessions/s1", json={"title": "新标题"})
        assert response.status_code == 200
        assert response.json()["title"] == "新标题"


class _StubOperations:
    def __init__(self) -> None:
        self.executed: list[dict] = []

    def has(self, name: str) -> bool:
        return True

    async def execute(self, name: str, params: dict, **kwargs):
        self.executed.append(params)
        return SimpleNamespace(status="ok", name=name, payload={"run_id": "r1", "run_items": []})


class TestRestTurnTitleBehavior:
    def test_turn_does_not_set_fallback_title(self):
        """The dead 60-char fallback was removed: a REST turn leaves a default
        title untouched (the LLM autotitle path owns it)."""
        store = InMemorySessionStore()
        store.create(SessionRecord(id="s1", member_id="core", title="new session", status="idle"))
        operations = _StubOperations()
        router = create_core_router(session_store=store, operations=operations)
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            response = client.post("/sessions/s1/turns", json={"message": "请帮我写一份报告"})
            assert response.status_code == 200
            fetched = client.get("/sessions/s1")
        assert fetched.json()["title"] == "new session"
        assert operations.executed[0]["message"] == "请帮我写一份报告"
