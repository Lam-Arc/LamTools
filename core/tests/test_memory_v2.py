"""Focused v2 shared-memory contract checks (Study and Agent paths)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from lamtools_core.llm import ChatMessage, LLMRequest, LLMResponse
from lamtools_core.mem import MemoryQuery, MemoryScope, MemoryService
from lamtools_core.mem.service import MemoryAuthorizationError
from lamtools_core.mem.dreaming import dream_session
from lamtools_core.mem.store import InMemoryMemoryStore, SqlAlchemyMemoryStore
from lamtools_core.app.core_db import open_core_app_db


@dataclass
class _LLM:
    response_text: str

    async def complete(self, request: LLMRequest, **kwargs) -> LLMResponse:
        return LLMResponse(content=self.response_text, finish_reason="stop")


@pytest.fixture(params=["memory", "sqlite"])
async def service(request, tmp_path: Path):
    db = None
    if request.param == "sqlite":
        db = await open_core_app_db(tmp_path / "memory-v2.db")
        store = db.memory_store
    else:
        store = InMemoryMemoryStore()
    try:
        yield MemoryService(store)
    finally:
        if db is not None:
            await db.close()


def _agent_scope() -> MemoryScope:
    return MemoryScope.for_project("user-a", "env-a", "project-a", work_root="C:/repo/a")


def _study_scope() -> MemoryScope:
    return MemoryScope.for_study("user-a", "env-a", "library-a")


async def test_scope_isolation_and_work_root_compatibility(service: MemoryService):
    project = _agent_scope()
    study = _study_scope()
    await service.remember_explicit(project, "只在项目 A 使用", source="user-msg-1", thread_id="thread-1")
    assert (await service.query(project, "项目 A")).total == 1
    assert (await service.query(study, "项目 A")).total == 0


async def test_same_public_id_cannot_cross_scope_mutate_or_read(service: MemoryService):
    scope_a = MemoryScope.for_project("user-a", "env-a", "project-a", work_root="C:/repo/a")
    scope_b = MemoryScope.for_project("user-a", "env-a", "project-b", work_root="C:/repo/b")
    owner = await service.remember_explicit(
        scope_a,
        "only project A",
        memory_id="shared-public-id",
        source="source-a",
    )

    assert await service.read(scope_b, owner.id) is None
    assert (await service.query(scope_b, "only project A")).total == 0
    with pytest.raises(MemoryAuthorizationError):
        await service.correct(scope_b, owner.id, "project B overwrite")
    assert await service.forget(scope_b, owner.id) == 0
    await service.suppress(scope_b, "source-a")
    assert (await service.read(scope_a, owner.id)).content == "only project A"  # type: ignore[union-attr]
    with pytest.raises(MemoryAuthorizationError):
        await service.remember_explicit(
            scope_b,
            "replacement from B",
            memory_id="new-b-id",
            replace_id=owner.id,
        )

    # A payload cannot forge the stored scope marker.  Reusing the public id
    # creates an independent B row, leaving A authoritative and unchanged.
    await service.remember_explicit(
        scope_b,
        "only project B",
        memory_id=owner.id,
        metadata={"__memory_scope__": scope_a.to_dict()},
    )
    assert (await service.read(scope_a, owner.id)).content == "only project A"  # type: ignore[union-attr]
    assert (await service.read(scope_b, owner.id)).content == "only project B"  # type: ignore[union-attr]


async def test_session_id_and_thread_id_are_normalized(service: MemoryService):
    entry = await service.remember_explicit(
        _study_scope(), "偏好用例子讲解", source="user-msg-2", session_id="study:node:1"
    )
    assert entry.metadata["session_id"] == "study:node:1"
    assert entry.metadata["thread_id"] == "study:node:1"


async def test_correction_and_forget_invalidate_cache_and_replay(service: MemoryService):
    scope = _study_scope()
    entry = await service.remember_explicit(scope, "先讲定义", source="user-msg-3")
    assert (await service.query(scope, "先讲定义")).total == 1
    corrected = await service.correct(scope, entry.id, "先讲直觉再讲定义", expected_version=entry.version)
    assert corrected.version == entry.version + 1
    assert (await service.query(scope, "先讲定义")).total == 0
    assert (await service.query(scope, "先讲直觉")).total == 1
    assert await service.forget(scope, corrected.id) == 1
    assert (await service.query(scope, "先讲直觉")).total == 0
    candidate = await service.submit_signal(
        scope, event_id="user-msg-3", content="先讲直觉再讲定义", source="user-msg-3"
    )
    assert candidate.status == "suppressed"


async def test_teaching_hint_is_not_personal_memory(service: MemoryService):
    scope = _study_scope()
    await service.remember_teaching_hint(scope, "先从平均变化率引入导数", source="node:derivative")
    assert (await service.query(scope, "平均变化率")).total == 0
    assert (await service.query(scope, "平均变化率", include_teaching_hints=True)).total == 1


async def test_single_mark_or_exam_mistake_does_not_become_ability(tmp_path: Path):
    store = InMemoryMemoryStore()
    result = await dream_session(
        session_id="study:node:derivative",
        work_root="",
        scope=_study_scope(),
        history=[ChatMessage(role="user", content="这题我做错了")],
        memory_store=store,
        llm_client=_LLM('[{"kind":"ability","content":"用户不会导数","confidence":0.99}]'),
    )
    assert result.added == 0
    assert (await store.search(MemoryQuery(query="用户不会导数"))).total == 0


async def test_project_dreaming_keeps_legacy_export_but_study_does_not(tmp_path: Path):
    store = InMemoryMemoryStore()
    llm = _LLM('[{"kind":"fact","content":"项目事实","confidence":0.9}]')
    project_result = await dream_session(
        session_id="agent-thread",
        work_root=tmp_path,
        scope=MemoryScope.local_legacy(str(tmp_path)),
        history=[ChatMessage(role="user", content="fact")],
        memory_store=store,
        llm_client=llm,
    )
    assert project_result.memory_md_updated is True
    study_root = tmp_path / "study-root"
    study_result = await dream_session(
        session_id="study-thread",
        work_root=study_root,
        scope=_study_scope(),
        history=[ChatMessage(role="user", content="fact")],
        memory_store=store,
        llm_client=llm,
    )
    assert study_result.memory_md_updated is False
    assert not (study_root / "MEMORY.md").exists()
