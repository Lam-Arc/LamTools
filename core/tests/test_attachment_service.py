from pathlib import Path

import pytest

from lamtools_core.attachment import (
    AttachmentRecord,
    AttachmentService,
    AttachmentSession,
    build_attachment_runtime_input,
)


class MemoryAttachmentRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.records: dict[str, AttachmentRecord] = {}

    async def session(self, session_id: str):
        return AttachmentSession(id=session_id, storage_root=self.root / session_id)

    async def create(self, record):
        self.records[record.id] = record
        return record

    async def list(self, session_id: str):
        return [record for record in self.records.values() if record.session_id == session_id]

    async def get(self, attachment_id: str):
        return self.records.get(attachment_id)


@pytest.mark.asyncio
async def test_core_attachment_service_owns_upload_preview_and_runtime_input(tmp_path):
    repository = MemoryAttachmentRepository(tmp_path)
    service = AttachmentService(repository)

    uploaded = await service.create("thread-1", "说明.txt", "附件正文".encode(), "text/plain")
    preview = await service.preview(uploaded["id"])
    record = await service.get(uploaded["id"])
    context, blocks = build_attachment_runtime_input([record], [record.id])

    assert Path(record.storage_path).read_text(encoding="utf-8") == "附件正文"
    assert preview["text"] == "附件正文"
    assert "本条消息附件" in context
    assert "附件正文" in context
    assert blocks == []
