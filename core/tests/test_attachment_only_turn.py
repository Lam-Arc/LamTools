from __future__ import annotations

import pytest

from lamtools_core.app.default_agent import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
from lamtools_core.app.live_member import DefaultCoreLiveMemberHooks
from lamtools_core.attachment import AttachmentRecord
from lamtools_core.llm import LLMStreamEvent


class CapturingLLM:
    def __init__(self):
        self.requests = []

    async def complete(self, request):
        raise AssertionError("Expected streaming")

    async def stream(self, request):
        self.requests.append(request)
        yield LLMStreamEvent(kind="content_delta", content="Attachment received.")
        yield LLMStreamEvent(kind="done")


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", "   "])
async def test_attachment_only_turn_reaches_model(tmp_path, monkeypatch, text):
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    path = tmp_path / "note.txt"
    path.write_text("Attachment-only evidence", encoding="utf-8")
    record = AttachmentRecord(
        id="att-1", session_id="thread-1", filename="note.txt", mime_type="text/plain",
        size=path.stat().st_size, storage_path=str(path), preview_type="text",
    )

    class AttachmentStore:
        async def get(self, attachment_id):
            assert attachment_id == record.id
            return record

    # Use the same preparation as the live UI/CLI input path.
    prepared = await DefaultCoreLiveMemberHooks().prepare_turn_input(
        thread_id="thread-1", params={"work_root": str(tmp_path)},
        input_items=[{"type": "text", "text": text}, {"type": "attachment", "attachment_id": record.id}],
    )
    llm = CapturingLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(), paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path),
        model_provider=llm, attachment_service=AttachmentStore(),
    )
    result = await catalog.execute("turn.start", {
        "thread_id": "thread-1", "message": prepared.runtime_text, **prepared.runtime_extras,
    })

    assert result.status == "ok"
    assert result.payload["snapshot"]["status"] == "completed"
    user_message = next(message for message in llm.requests[0].messages if message.role == "user")
    assert isinstance(user_message.content, list)
    assert "Attachment-only evidence" in user_message.content[0]["text"]
    assert "note.txt" in user_message.content[0]["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", "   "])
async def test_empty_turn_without_attachment_still_rejected(tmp_path, text):
    llm = CapturingLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(), paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path),
        model_provider=llm,
    )
    result = await catalog.execute("turn.start", {
        "thread_id": "thread-1", "message": text, "attachment_ids": [],
    })
    assert result.status == "error"
    assert result.payload["error"] == "message is required"
    assert llm.requests == []
