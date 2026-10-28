"""user:“用户消息那个也许可以取消”+(取消近期用户原话附录，保留当前请求与历史召回)。"""

from copy import deepcopy

import pytest

from lamtools_core.context_compaction import ContextCompactionRequest, compact_context
from lamtools_core.context_compaction.formatting import append_recent_user_messages
from lamtools_core.context_compaction.models import CompactionSummary
from lamtools_core.llm import ChatMessage, LLMResponse


class SummaryClient:
    calls = 0
    async def complete(self, request):
        self.calls += 1
        return LLMResponse(content=CompactionSummary(goals="继续当前任务", active_user_instructions="保留 UTF-8 编码约束", confirmed_facts_and_decisions="曾确认使用 UTF-8").render(), finish_reason="stop")
    async def stream(self, request):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_compaction_drops_recent_user_appendix_but_keeps_current_request():
    old = append_recent_user_messages(CompactionSummary(goals="旧任务", active_user_instructions="保留 UTF-8").render(), ["过去的用户原文"])
    history = [ChatMessage(role="system", content="SYSTEM"), ChatMessage(role="system", content=old, metadata={"key": "context_compaction_summary", "recent_user_messages": ["过去的用户原文"]})]
    for i in range(55):
        history += [ChatMessage(role="user", content=f"old-{i}"), ChatMessage(role="assistant", content="大量历史工具说明 " * 80)]
    current = ChatMessage(role="user", content="继续修复，编码必须 UTF-8。", metadata={"history_seq": 120})
    history += [current, ChatMessage(role="assistant", content="正在处理 " * 100)]
    before = deepcopy([m.to_dict() for m in history])
    client = SummaryClient()
    result = await compact_context(ContextCompactionRequest(trigger="manual", messages=history, llm_client=client, retained_steps=0, limit_tokens=3000, input_limit_tokens=1000000, estimate_tokens=lambda ms: sum(len(str(m.content)) for m in ms), estimate_exact_tokens=lambda ms: sum(len(str(m.content)) for m in ms)))
    assert result.status == "compacted", result.display_payload
    assert "## Recent user messages" not in result.summary
    assert "过去的用户原文" not in result.summary
    assert result.recent_user_messages == []
    assert [m.content for m in result.retained_messages if m.role == "user"] == [current.content]
    assert result.retained_messages[0] is current
    assert "UTF-8" in result.summary
    assert before == [m.to_dict() for m in history]
    assert client.calls == 1


@pytest.mark.asyncio
async def test_current_request_over_budget_fails_before_summarizing():
    client = SummaryClient()
    result = await compact_context(ContextCompactionRequest(trigger="auto", messages=[ChatMessage(role="user", content="older"), ChatMessage(role="assistant", content="history" * 100), ChatMessage(role="user", content="NEW" * 1000)], llm_client=client, retained_steps=0, limit_tokens=500, input_limit_tokens=100000, estimate_tokens=lambda ms: sum(len(str(m.content)) for m in ms), estimate_exact_tokens=lambda ms: sum(len(str(m.content)) for m in ms)))
    assert result.status == "failed"
    assert result.display_payload["reason"] == "protected_tail_over_limit"
    assert client.calls == 0
