"""Tests for the dreaming (memory consolidation) pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from lamtools_core.llm import ChatMessage, LLMRequest, LLMResponse
from lamtools_core.mem import MemoryQuery
from lamtools_core.mem.dreaming import (
    DreamCandidate,
    dream_session,
    record_dream_turn,
    should_dream,
    _parse_candidates,
    _format_history_for_dream,
)
from lamtools_core.mem.store import InMemoryMemoryStore
from lamtools_core.runtime import RuntimeState


# ── mock LLM ─────────────────────────────────────────────────────


@dataclass
class MockLLM:
    response_text: str = "[]"

    async def complete(self, request: LLMRequest, **kw) -> LLMResponse:
        return LLMResponse(content=self.response_text, finish_reason="stop")

    async def stream(self, request: LLMRequest, **kw):
        yield {"type": "content_delta", "text": self.response_text}
        yield {"type": "done"}


class FailingLLM:
    async def complete(self, request: LLMRequest, **kw) -> LLMResponse:
        raise RuntimeError("API down")

    async def stream(self, request: LLMRequest, **kw):
        raise RuntimeError("API down")


# ── _parse_candidates ────────────────────────────────────────────


class TestParseCandidates:
    def test_empty(self):
        assert _parse_candidates("") == []

    def test_plain_array(self):
        cands = _parse_candidates('[{"kind":"fact","content":"x","confidence":0.8}]')
        assert len(cands) == 1
        assert cands[0].kind == "fact"
        assert cands[0].confidence == 0.8

    def test_markdown_fenced(self):
        cands = _parse_candidates('```json\n[{"kind":"fact","content":"x","confidence":0.5}]\n```')
        assert len(cands) == 1

    def test_single_object(self):
        cands = _parse_candidates('{"kind":"todo","content":"fix","confidence":0.7}')
        assert len(cands) == 1
        assert cands[0].kind == "todo"

    def test_garbage_returns_empty(self):
        assert _parse_candidates("not json at all") == []

    def test_confidence_clamped(self):
        cands = _parse_candidates('[{"kind":"fact","content":"x","confidence":1.5}]')
        assert cands[0].confidence == 1.0

    def test_missing_content_skipped(self):
        cands = _parse_candidates('[{"kind":"fact","content":"","confidence":0.8}]')
        assert cands == []


# ── _format_history_for_dream ────────────────────────────────────


class TestFormatHistory:
    def test_truncates_tool_results(self):
        history = [ChatMessage(role="tool", content="x" * 500, tool_call_id="t1")]
        text = _format_history_for_dream(history)
        assert "…" in text
        assert len(text) < 500

    def test_includes_compaction_summary(self):
        history = [ChatMessage(role="user", content="hi")]
        text = _format_history_for_dream(history, compaction_summary="prior context")
        assert "[此前会话摘要]" in text
        assert "prior context" in text

    def test_empty_history(self):
        assert _format_history_for_dream([]).strip() == ""

    def test_tool_call_traces_without_content(self):
        from lamtools_core.llm import LLMToolCall

        history = [
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[LLMToolCall(id="c1", name="read_file", arguments={})],
            )
        ]
        text = _format_history_for_dream(history)
        assert "read_file" in text


# ── should_dream / record_dream_turn ─────────────────────────────


class TestShouldDream:
    def test_disabled_policy(self):
        from lamtools_core.kernel.policy import LoopPolicy

        state = RuntimeState(session_id="s", turn_count=10)
        policy = LoopPolicy(dreaming_enabled=False)
        assert not should_dream(state, policy=policy, had_tool_use=True)

    def test_not_enough_turns(self):
        from lamtools_core.kernel.policy import LoopPolicy

        state = RuntimeState(session_id="s", turn_count=1)
        policy = LoopPolicy(dreaming_enabled=True, dream_min_turns=3)
        assert not should_dream(state, policy=policy, had_tool_use=True)

    def test_no_compaction_no_tools(self):
        from lamtools_core.kernel.policy import LoopPolicy

        state = RuntimeState(session_id="s", turn_count=5)
        policy = LoopPolicy(dreaming_enabled=True, dream_min_turns=3)
        assert not should_dream(state, policy=policy, had_compaction=False, had_tool_use=False)

    def test_triggers_with_tools(self):
        from lamtools_core.kernel.policy import LoopPolicy

        state = RuntimeState(session_id="s", turn_count=5)
        policy = LoopPolicy(dreaming_enabled=True, dream_min_turns=3)
        assert should_dream(state, policy=policy, had_tool_use=True)

    def test_triggers_with_compaction(self):
        from lamtools_core.kernel.policy import LoopPolicy

        state = RuntimeState(session_id="s", turn_count=5)
        policy = LoopPolicy(dreaming_enabled=True, dream_min_turns=3)
        assert should_dream(state, policy=policy, had_compaction=True)

    def test_record_dream_turn_resets_cooldown(self):
        from lamtools_core.kernel.policy import LoopPolicy

        state = RuntimeState(session_id="s", turn_count=5)
        policy = LoopPolicy(dreaming_enabled=True, dream_min_turns=3)
        record_dream_turn(state)
        assert state.metadata["last_dream_turn"] == 5
        # Only 1 turn since last dream → should not fire
        state.turn_count = 6
        assert not should_dream(state, policy=policy, had_tool_use=True)
        # 3 turns later → should fire
        state.turn_count = 8
        assert should_dream(state, policy=policy, had_tool_use=True)


# ── dream_session ────────────────────────────────────────────────


class TestDreamSession:
    async def test_full_pipeline_with_mock_llm(self, tmp_path: Path):
        store = InMemoryMemoryStore()
        history = [
            ChatMessage(role="user", content="项目用什么数据库？"),
            ChatMessage(role="assistant", content="用 SQLite，存在 data/core.db"),
            ChatMessage(role="tool", content="ok", tool_call_id="t1"),
        ]
        llm = MockLLM(
            response_text='[{"kind":"fact","content":"项目用 SQLite，数据库在 data/core.db","confidence":0.9},'
            '{"kind":"preference","content":"用户偏好 PowerShell 中文用 UTF-8","confidence":0.85}]'
        )
        result = await dream_session(
            session_id="s1",
            work_root=tmp_path,
            history=history,
            memory_store=store,
            llm_client=llm,
            model="mock",
        )
        assert result.status == "dreamed"
        assert result.extracted == 2
        assert result.added == 2
        assert result.memory_md_updated is True

        # Store has both entries
        assert (await store.search(MemoryQuery(query="SQLite", limit=5))).total == 1
        assert (await store.search(MemoryQuery(query="UTF-8", limit=5))).total == 1

        # MEMORY.md was written
        md = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
        assert "SQLite" in md
        assert "UTF-8" in md

    async def test_dedup_on_second_dream(self, tmp_path: Path):
        store = InMemoryMemoryStore()
        history = [ChatMessage(role="user", content="test")]
        llm = MockLLM(
            response_text='[{"kind":"fact","content":"重复的事实","confidence":0.9}]'
        )
        await dream_session(
            session_id="s1", work_root=tmp_path, history=history,
            memory_store=store, llm_client=llm, model="mock",
        )
        result2 = await dream_session(
            session_id="s1", work_root=tmp_path, history=history,
            memory_store=store, llm_client=llm, model="mock",
        )
        assert result2.added == 0
        assert result2.updated == 1

    async def test_no_llm_with_compaction_summary(self, tmp_path: Path):
        store = InMemoryMemoryStore()
        result = await dream_session(
            session_id="s1",
            work_root=tmp_path,
            history=[ChatMessage(role="user", content="hi")],
            compaction_summary="讨论了数据库架构",
            memory_store=store,
            llm_client=None,
        )
        # Without LLM, the compaction summary becomes a low-confidence candidate
        # that gets filtered by the default min_confidence=0.5.
        assert result.status in ("no_llm", "dreamed")

    async def test_failing_llm_returns_failed(self, tmp_path: Path):
        store = InMemoryMemoryStore()
        result = await dream_session(
            session_id="s1",
            work_root=tmp_path,
            history=[ChatMessage(role="user", content="test")],
            memory_store=store,
            llm_client=FailingLLM(),
            model="mock",
        )
        assert result.status == "failed"
        assert "failed" in result.summary.lower() or result.error

    async def test_empty_history_skipped(self, tmp_path: Path):
        store = InMemoryMemoryStore()
        result = await dream_session(
            session_id="s1", work_root=tmp_path, history=[],
            memory_store=store, llm_client=MockLLM(),
        )
        assert result.status == "skipped"

    async def test_low_confidence_filtered(self, tmp_path: Path):
        store = InMemoryMemoryStore()
        llm = MockLLM(
            response_text='[{"kind":"fact","content":"low confidence fact","confidence":0.3}]'
        )
        result = await dream_session(
            session_id="s1", work_root=tmp_path,
            history=[ChatMessage(role="user", content="x")],
            memory_store=store, llm_client=llm, model="mock",
            min_confidence=0.5,
        )
        assert result.extracted == 0
        assert result.added == 0

    async def test_memory_md_not_written_without_work_root(self, tmp_path: Path):
        store = InMemoryMemoryStore()
        llm = MockLLM(
            response_text='[{"kind":"fact","content":"fact","confidence":0.9}]'
        )
        result = await dream_session(
            session_id="s1", work_root="",  # no work root
            history=[ChatMessage(role="user", content="x")],
            memory_store=store, llm_client=llm, model="mock",
        )
        assert result.memory_md_updated is False
