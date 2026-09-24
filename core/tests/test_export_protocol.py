from __future__ import annotations

import asyncio
from datetime import datetime
from io import BytesIO
import json
from zipfile import ZipFile

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lamtools_core.app.core_db import (
    CoreCheckpoint,
    CoreCheckpointAttachmentRef,
    CoreCheckpointBlob,
    CoreCheckpointBlobRef,
    CoreCheckpointV2,
    CoreCheckpointV2Materialized,
    CoreCheckpointV2SessionHistory,
    CoreCheckpointV2SessionMessages,
    CoreAttachment,
    CoreDbBase,
    CoreHandoffContext,
    CoreHistoryEntry,
    CoreRuntimeSession,
    CoreThreadSnapshot,
    CoreWorkspaceManifest,
)
from lamtools_core.app.core_session_store import delete_session_records
from lamtools_core.export import ConversationExportService, build_handoff_context
from lamtools_core.export.serializers import full_to_zip, transcript_to_jsonl, transcript_to_markdown, transcript_to_text
from lamtools_core.http import create_core_router
from lamtools_core.llm import ChatMessage, LLMRequest, LLMToolCall


def _factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'export.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with engine.begin() as connection:
            await connection.run_sync(CoreDbBase.metadata.create_all)

    asyncio.run(setup())
    return engine, factory


def test_transcript_uses_history_facts_and_excludes_internal_messages(tmp_path):
    engine, factory = _factory(tmp_path)

    async def seed():
        async with factory() as db:
            db.add_all([
                CoreHistoryEntry(thread_id="t", seq=1, message_json={"role": "system", "content": "internal"}, created_at=datetime(2026, 1, 1)),
                CoreHistoryEntry(thread_id="t", seq=2, message_json={"role": "user", "content": "hello"}, created_at=datetime(2026, 1, 2)),
                CoreHistoryEntry(thread_id="t", seq=3, message_json={"role": "assistant", "content": "world"}, created_at=datetime(2026, 1, 3)),
                CoreHistoryEntry(thread_id="t", seq=4, message_json={"role": "tool", "content": "secret"}, created_at=datetime(2026, 1, 4)),
                CoreHistoryEntry(thread_id="t", seq=5, message_json={"role": "assistant", "content": "world"}, created_at=datetime(2026, 1, 5)),
            ])
            await db.commit()

    asyncio.run(seed())
    exported = asyncio.run(ConversationExportService(factory).transcript("t"))
    assert [entry.role for entry in exported.entries] == ["user", "assistant"]
    assert [entry.text for entry in exported.entries] == ["hello", "world"]
    assert "secret" not in transcript_to_text(exported)
    assert "## user" in transcript_to_markdown(exported)
    asyncio.run(engine.dispose())


def test_transcript_falls_back_to_legacy_runtime_blob(tmp_path):
    engine, factory = _factory(tmp_path)

    async def seed():
        async with factory() as db:
            db.add(CoreRuntimeSession(thread_id="t", history_json=[{"role": "user", "content": [{"type": "text", "text": "image question"}]}]))
            await db.commit()

    asyncio.run(seed())
    exported = asyncio.run(ConversationExportService(factory).transcript("t"))
    assert exported.entries[0].text == "image question"
    asyncio.run(engine.dispose())


def test_handoff_is_fixed_provider_neutral_message_only_payload():
    payload = build_handoff_context(LLMRequest(
        model="gpt-secret",
        temperature=0.7,
        max_tokens=123,
        tools=[{"type": "function", "function": {"name": "shell"}}],
        metadata={"provider": "secret-provider", "request_id": "req-1"},
        messages=[
            ChatMessage(role="system", content="Instructions\n当前项目: C:/private 当前会话: sid 当前模型: gpt-secret"),
            ChatMessage(role="user", content="continue"),
            ChatMessage(
                role="assistant",
                content="数据库检查完成。",
                tool_calls=[LLMToolCall(id="call_123", name="shell", arguments={"command": "select 1"})],
                metadata={"trace_id": "trace-1"},
            ),
            ChatMessage(role="tool", content="92 sessions found", tool_call_id="call_123"),
        ],
    ))

    assert set(payload) == {"schema", "context"}
    assert payload["schema"] == "lamtools.handoff.v1"
    assert payload["context"] == [
        {"role": "system", "content": "Instructions"},
        {"role": "user", "content": "continue"},
        {"role": "assistant", "content": "数据库检查完成。"},
        {"role": "tool", "content": "92 sessions found"},
    ]


def test_handoff_removes_english_runtime_prompt_metadata():
    payload = build_handoff_context([
        ChatMessage(
            role="system",
            content=(
                "Instructions\n"
                "Current project: C:/private, current session: sid, current model: gpt-secret\n"
                "[Command Shell]\nCurrent platform: Windows.\nCurrent shell: Git Bash (bash.exe).\n"
                "Known successful evidence call IDs are opaque references.\n"
                "Current model capability: text only (set model to \"secret-model\")."
            ),
        ),
    ])

    assert payload["context"] == [
        {"role": "system", "content": "Instructions\nCurrent model capability: text only."},
    ]


def test_handoff_keeps_tool_result_knowledge_and_generic_attachment_data():
    payload = build_handoff_context([
        {
            "role": "tool",
            "tool_call_id": "call_123",
            "content": {
                "result": "92 sessions",
                "call_id": "call_123",
                "event_seq": 17,
            },
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "请继续检查附件"},
                {"type": "file", "filename": "design.pdf", "mime_type": "application/pdf", "path": "C:/private/design.pdf", "reference": "design.pdf"},
            ],
        },
    ])

    serialized = str(payload)
    assert "92 sessions" in serialized
    assert "call_123" not in serialized
    assert "event_seq" not in serialized
    assert "C:/private" not in serialized
    assert payload["context"][1]["content"][1] == {
        "type": "attachment",
        "name": "design.pdf",
        "media_type": "application/pdf",
        "reference": "design.pdf",
    }


def test_transcript_jsonl_is_one_object_per_line(tmp_path):
    engine, factory = _factory(tmp_path)

    async def seed():
        async with factory() as db:
            db.add(CoreHistoryEntry(thread_id="t", seq=1, message_json={"role": "user", "content": "hello"}))
            db.add(CoreHistoryEntry(thread_id="t", seq=2, message_json={"role": "assistant", "content": "world"}))
            await db.commit()

    asyncio.run(seed())
    exported = asyncio.run(ConversationExportService(factory).transcript("t"))
    lines = transcript_to_jsonl(exported).splitlines()
    assert len(lines) == 2
    assert all(line.startswith("{") and line.endswith("}") for line in lines)
    asyncio.run(engine.dispose())


def test_full_archive_includes_portable_attachment_files_and_handoff(tmp_path):
    engine, factory = _factory(tmp_path)
    source = tmp_path / "private-storage" / "notes.txt"
    source.parent.mkdir()
    source.write_bytes(b"archive attachment")

    async def seed():
        async with factory() as db:
            db.add(CoreRuntimeSession(thread_id="t"))
            db.add(CoreAttachment(
                id="attachment-1",
                session_id="t",
                filename="notes.txt",
                mime_type="text/plain",
                size=source.stat().st_size,
                storage_path=str(source),
                preview_type="text",
                metadata_json={"source": "test"},
            ))
            db.add(CoreHandoffContext(
                thread_id="t",
                context_json=build_handoff_context([
                    ChatMessage(role="user", content="continue from archive"),
                ]),
            ))
            await db.commit()

    asyncio.run(seed())
    exported = asyncio.run(ConversationExportService(factory).full("t"))
    archive = ZipFile(BytesIO(full_to_zip(exported)))
    names = set(archive.namelist())
    attachment_member = "attachments/attachment-1/notes.txt"

    assert attachment_member in names
    assert archive.read(attachment_member) == b"archive attachment"
    assert str(tmp_path) not in archive.read("attachments.jsonl").decode("utf-8")
    attachment = json.loads(archive.read("attachments.jsonl").decode("utf-8").splitlines()[0])
    assert attachment["storage_path"] == attachment_member
    assert attachment["file_present"] is True
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["files"] == [{"path": attachment_member, "size": len(b"archive attachment")}]
    assert json.loads(archive.read("handoff.json"))["schema"] == "lamtools.handoff.v1"
    archive.close()
    asyncio.run(engine.dispose())


def test_full_archive_carries_v2_recovery_material_and_portable_workspace_blobs(tmp_path):
    engine, factory = _factory(tmp_path)
    source = tmp_path / "private-storage" / "before-edit.txt"
    source.parent.mkdir()
    source.write_bytes(b"workspace checkpoint bytes")
    checkpoint_id = "checkpoint-v2"
    blob_hash = "blob-v2"
    manifest_hash = "manifest-v2"

    async def seed():
        async with factory() as db:
            db.add(CoreRuntimeSession(thread_id="t"))
            db.add(CoreThreadSnapshot(
                thread_id="t",
                snapshot_json={"session": {"metadata": {"work_root": str(tmp_path)}}},
            ))
            db.add(CoreCheckpoint(
                id=checkpoint_id,
                root_session_id="t",
                graph_id="t",
                parent_checkpoint_id="",
                edge_kind="checkpoint",
                reason="manual",
                label="",
                session_id="t",
                turn_id="turn-1",
                actor_kind="main",
                work_root=str(tmp_path),
                manifest_hash=manifest_hash,
                conversation_json={},
            ))
            db.add(CoreCheckpointV2(
                id=checkpoint_id,
                root_session_id="t",
                session_id="t",
                parent_checkpoint_id="",
                turn_id="turn-1",
                actor_kind="main",
                reason="manual",
                event_seq=4,
                history_seq=2,
                runtime_state_json={"loop_state": "continue"},
                workspace_manifest_id=manifest_hash,
            ))
            db.add(CoreCheckpointV2Materialized(
                checkpoint_id=checkpoint_id,
                runtime_present=True,
                runtime_json={"runtime_state_json": {"loop_state": "continue"}},
                history_json=[{"role": "user", "content": "restore me"}],
                projection_present=True,
                projection_json={"snapshot_seq": 4, "snapshot_json": {"messages": []}},
                events_present=True,
                events_json=[],
            ))
            db.add(CoreCheckpointV2SessionMessages(
                checkpoint_id=checkpoint_id,
                messages_json=[{"id": "message-1"}],
            ))
            db.add(CoreCheckpointV2SessionHistory(
                checkpoint_id=checkpoint_id,
                history_json=[{"role": "user", "content": "restore me"}],
            ))
            db.add(CoreCheckpointAttachmentRef(
                checkpoint_id=checkpoint_id,
                attachment_id="attachment-ref",
            ))
            db.add(CoreCheckpointBlobRef(
                checkpoint_id=checkpoint_id,
                blob_hash=blob_hash,
            ))
            db.add(CoreWorkspaceManifest(
                hash=manifest_hash,
                entries_json={"before-edit.txt": {"hash": blob_hash, "size": source.stat().st_size}},
            ))
            db.add(CoreCheckpointBlob(
                hash=blob_hash,
                size=source.stat().st_size,
                storage_path=str(source),
            ))
            await db.commit()

    asyncio.run(seed())
    exported = asyncio.run(ConversationExportService(factory).full("t"))
    archive = ZipFile(BytesIO(full_to_zip(exported)))
    names = set(archive.namelist())

    assert "checkpoint-materialized.jsonl" in names
    assert "checkpoint-session-messages.jsonl" in names
    assert "checkpoint-session-history.jsonl" in names
    assert "workspace-manifests.jsonl" in names
    assert "checkpoint-blobs.jsonl" in names
    checkpoint = json.loads(archive.read("checkpoints.jsonl").decode("utf-8").splitlines()[0])
    assert checkpoint["runtime_state_json"] == {"loop_state": "continue"}
    workspace_member = "workspace/blobs/blob-v2"
    assert workspace_member in names
    assert archive.read(workspace_member) == b"workspace checkpoint bytes"
    blob_record = json.loads(archive.read("checkpoint-blobs.jsonl").decode("utf-8").splitlines()[0])
    assert blob_record["storage_path"] == workspace_member
    assert blob_record["file_present"] is True
    assert str(tmp_path) not in archive.read("checkpoint-blobs.jsonl").decode("utf-8")
    assert str(tmp_path) not in archive.read("legacy-checkpoints.jsonl").decode("utf-8")
    archive.close()
    asyncio.run(engine.dispose())


def test_session_delete_removes_captured_handoff_context(tmp_path):
    engine, factory = _factory(tmp_path)

    async def seed_and_delete():
        async with factory() as db:
            db.add(CoreHandoffContext(
                thread_id="t",
                context_json=build_handoff_context([ChatMessage(role="user", content="keep no orphan")]),
            ))
            await db.commit()
        async with factory() as db:
            await delete_session_records(db, ["t"])
            await db.commit()
        async with factory() as db:
            return await db.get(CoreHandoffContext, "t")

    assert asyncio.run(seed_and_delete()) is None
    asyncio.run(engine.dispose())


def test_http_export_routes_and_capabilities_use_the_three_tier_protocol(tmp_path):
    engine, factory = _factory(tmp_path)

    async def seed():
        async with factory() as db:
            db.add(CoreHistoryEntry(thread_id="t", seq=1, message_json={"role": "user", "content": "hello"}))
            db.add(CoreHandoffContext(
                thread_id="t",
                context_json=build_handoff_context([
                    ChatMessage(role="system", content="semantic instructions"),
                    ChatMessage(role="user", content="hello"),
                ]),
            ))
            await db.commit()

    asyncio.run(seed())
    async def handoff_provider(thread_id):
        async with factory() as db:
            row = await db.get(CoreHandoffContext, thread_id)
            return row.context_json if row is not None else None

    app = FastAPI()
    app.include_router(
        create_core_router(export_service=ConversationExportService(
            factory,
            handoff_context_provider=handoff_provider,
        )),
        prefix="/api/core",
    )

    with TestClient(app) as client:
        assert client.get("/api/core/sessions/t/export/capabilities").json() == {
            "transcript": ["markdown", "txt", "jsonl"],
            "handoff": ["json"],
            "full": ["zip"],
        }
        transcript = client.post(
            "/api/core/sessions/t/export",
            json={"mode": "transcript", "format": "jsonl"},
        )
        assert transcript.status_code == 200
        assert json.loads(transcript.text)["text"] == "hello"

        handoff = client.post(
            "/api/core/sessions/t/export",
            json={"mode": "handoff", "format": "json"},
        )
        assert handoff.status_code == 200
        assert handoff.json() == {
            "schema": "lamtools.handoff.v1",
            "context": [
                {"role": "system", "content": "semantic instructions"},
                {"role": "user", "content": "hello"},
            ],
        }

        full = client.post(
            "/api/core/sessions/t/export",
            json={"mode": "full", "format": "zip"},
        )
        assert full.status_code == 200
        assert ZipFile(BytesIO(full.content)).testzip() is None

        assert client.post(
            "/api/core/sessions/t/export",
            json={"mode": "transcript", "format": "json"},
        ).status_code == 422

    asyncio.run(engine.dispose())
