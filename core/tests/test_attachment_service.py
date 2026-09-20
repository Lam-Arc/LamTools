from pathlib import Path

import pytest

import pytest

from lamtools_core.attachment import (
    AttachmentRecord,
    AttachmentService,
    AttachmentSession,
    build_attachment_runtime_input,
    build_capability_aware_attachment_input,
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


# --- Capability-aware attachment splitting ----------------------------------


def _image_record(tmp_path: Path, att_id: str = "img-1") -> AttachmentRecord:
    png = tmp_path / f"{att_id}.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    return AttachmentRecord(
        id=att_id, session_id="s", filename=f"{att_id}.png", mime_type="image/png",
        size=png.stat().st_size, storage_path=str(png), preview_type="image",
    )


def _text_record(tmp_path: Path, att_id: str = "txt-1") -> AttachmentRecord:
    txt = tmp_path / f"{att_id}.txt"
    txt.write_text("hello world", encoding="utf-8")
    return AttachmentRecord(
        id=att_id, session_id="s", filename=f"{att_id}.txt", mime_type="text/plain",
        size=txt.stat().st_size, storage_path=str(txt), preview_type="text",
    )


def _video_record(att_id: str = "vid-1") -> AttachmentRecord:
    return AttachmentRecord(
        id=att_id, session_id="s", filename=f"{att_id}.mp4", mime_type="video/mp4",
        size=1024, storage_path=f"/tmp/{att_id}.mp4", preview_type="video",
    )


def _pdf_record(tmp_path: Path, att_id: str = "pdf-1") -> AttachmentRecord:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    path = tmp_path / f"{att_id}.pdf"
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 72 720 Td (Uploaded PDF evidence) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    with path.open("wb") as output:
        writer.write(output)
    return AttachmentRecord(
        id=att_id,
        session_id="s",
        filename=path.name,
        mime_type="application/pdf",
        size=path.stat().st_size,
        storage_path=str(path),
        preview_type="pdf",
    )


def test_capability_split_multimodal_receives_image_text_defers_video(tmp_path):
    img = _image_record(tmp_path, "img-1")
    txt = _text_record(tmp_path, "txt-1")
    vid = _video_record("vid-1")
    records = [img, txt, vid]
    current = ["img-1", "txt-1", "vid-1"]

    index_text, blocks, deferred = build_capability_aware_attachment_input(records, current, "multimodal")

    # Image → content block; text → inlined in index; video → deferred (no inline block).
    assert any(b.get("type") == "image_url" for b in blocks)
    assert "hello world" in index_text
    assert "vid-1" in deferred
    assert "需委派" in index_text and "vid-1" in index_text


def test_capability_split_text_model_defers_image_and_video(tmp_path):
    img = _image_record(tmp_path, "img-1")
    vid = _video_record("vid-1")
    records = [img, vid]
    current = ["img-1", "vid-1"]

    index_text, blocks, deferred = build_capability_aware_attachment_input(records, current, "text")

    # Text model cannot process images or videos — all deferred, no content blocks.
    assert blocks == []
    assert "img-1" in deferred
    assert "vid-1" in deferred
    assert "需委派" in index_text
    assert "img-1" in index_text


def test_capability_split_text_model_still_inlines_text(tmp_path):
    txt = _text_record(tmp_path, "txt-1")
    records = [txt]
    current = ["txt-1"]

    index_text, _blocks, deferred = build_capability_aware_attachment_input(records, current, "text")

    # Text attachments are always inlined regardless of model capability.
    assert "hello world" in index_text
    assert deferred == []


def test_capability_split_parses_pdf_as_untrusted_text_without_deferring(tmp_path):
    pdf = _pdf_record(tmp_path)

    index_text, blocks, deferred = build_capability_aware_attachment_input(
        [pdf], [pdf.id], "text"
    )

    assert blocks == []
    assert deferred == []
    assert "PDF 已解析" in index_text
    assert "[UNTRUSTED DOCUMENT CONTENT]" in index_text
    assert "Uploaded PDF evidence" in index_text
    assert "需委派" not in index_text


def test_capability_split_empty_when_no_current_attachments(tmp_path):
    img = _image_record(tmp_path, "img-1")
    records = [img]
    current: list[str] = []  # historical only

    index_text, blocks, deferred = build_capability_aware_attachment_input(records, current, "multimodal")

    # Historical attachments are never sent as content blocks.
    assert blocks == []
    assert deferred == []




@pytest.mark.asyncio
async def test_repository_rejects_path_traversal_session_id(tmp_path):
    """Audit 11 S2: session_id becomes a directory name; separators/``..``
    must be rejected instead of writing outside the storage root."""
    from lamtools_core.attachment.store import _CoreAttachmentRepository

    repo = _CoreAttachmentRepository(None, tmp_path / "data")
    for bad in ("../escape", "a/b", "a\b", "..", "", "x" * 257):
        with pytest.raises(LookupError):
            await repo.session(bad)
    ok = await repo.session("session-abc_1.2")
    assert ok.storage_root == tmp_path / "data" / "attachments" / "session-abc_1.2"
    study = await repo.session("study:node:vector")
    repeated = await repo.session("study:node:vector")
    assert study.id == "study:node:vector"
    assert study.storage_root == repeated.storage_root
    assert study.storage_root.parent == tmp_path / "data" / "attachments"
    assert study.storage_root.name.startswith("session-")
    assert ":" not in study.storage_root.name


@pytest.mark.asyncio
async def test_upload_rejects_oversized_content(tmp_path):
    """Audit 03/11 S2: uploads are size-bounded."""
    from lamtools_core.attachment.service import MAX_ATTACHMENT_BYTES

    repository = MemoryAttachmentRepository(tmp_path)
    service = AttachmentService(repository)
    with pytest.raises(ValueError):
        await service.create("session-ok", "big.bin", b"x" * (MAX_ATTACHMENT_BYTES + 1))


@pytest.mark.asyncio
async def test_open_refuses_executable_types(tmp_path, monkeypatch):
    """Audit 03 S2: the /open endpoint must not launch scripts/executables."""
    repository = MemoryAttachmentRepository(tmp_path)
    service = AttachmentService(repository)
    monkeypatch.setattr("lamtools_core.attachment.service.open_with_default_app", lambda path: None)
    for name in ("evil.bat", "evil.ps1", "evil.EXE", "evil.lnk", "evil.sh"):
        record = await service.create("session-ok", name, b"payload")
        with pytest.raises(ValueError):
            await service.open(record["id"])
    record = await service.create("session-ok", "notes.txt", b"hello")
    result = await service.open(record["id"])
    assert result["status"] == "opened"
