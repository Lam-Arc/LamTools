from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lamtools_core.app.http_agent_app import (
    CoreConfigRoutingLLMClient,
    create_core_agent_http_app,
)
from lamtools_core.app import CoreAgentSpec
from lamtools_core.cli import CoreHttpLLMClient, list_core_cli_sessions
from lamtools_core.llm import LLMRequest, LLMStreamEvent
from lamtools_core.app.base_agent import CoreBaseAgentKit
from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.member import MemberManifest
from lamtools_core.runtime.arrange import ArrangeManager
from lamtools_core.runtime.observer import prepare_observer


def _write_jsonc_config(config_root: Path) -> None:
    """Write provider-1 + model-record jsonc (replaces the old config.db fixture)."""
    provider_dir = config_root / "providers"
    provider_dir.mkdir(parents=True, exist_ok=True)
    (provider_dir / "provider-1.jsonc").write_text(
        '{\n'
        '  "id": "provider-1",\n'
        '  "name": "Provider",\n'
        '  "api_type": "openai",\n'
        '  "base_url": "https://example.test/v1",\n'
        '  "api_key": "secret"\n'
        '}\n',
        encoding="utf-8",
    )
    model_dir = config_root / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model-record.jsonc").write_text(
        '{\n'
        '  "model_id": "model-record",\n'
        '  "display_name": "Model Name",\n'
        '  "provider": "Provider",\n'
        '  "provider_id": "provider-1",\n'
        '  "context_window": 128000,\n'
        '  "max_output_tokens": 4096,\n'
        '  "temperature": 0.2,\n'
        '  "thinking": {"supported": true, "budget": 10000}\n'
        '}\n',
        encoding="utf-8",
    )


def _write_two_model_jsonc_config(config_root: Path) -> None:
    _write_jsonc_config(config_root)
    model_dir = config_root / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "second-record.jsonc").write_text(
        '{\n'
        '  "model_id": "second-record",\n'
        '  "display_name": "Second Model",\n'
        '  "provider": "Provider",\n'
        '  "provider_id": "provider-1",\n'
        '  "context_window": 128000,\n'
        '  "max_output_tokens": 8192,\n'
        '  "temperature": 0.3,\n'
        '  "thinking": {"supported": true, "budget": 7000}\n'
        '}\n',
        encoding="utf-8",
    )


def test_core_agent_http_app_exposes_live_app_server(tmp_path: Path, isolated_config_root: Path) -> None:
    _write_jsonc_config(isolated_config_root)
    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=tmp_path / "core.db",
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )

    with TestClient(app) as client:
        with client.websocket_connect("/api/core/app-server") as websocket:
            websocket.send_json(
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {"clientInfo": {"name": "test"}},
                }
            )

            initialized = websocket.receive_json()

    assert initialized["result"]["protocolVersion"] == "core.app_server.v1"


def test_core_agent_http_app_keeps_myproject_in_configured_project_roots(
    tmp_path: Path,
    isolated_config_root: Path,
) -> None:
    _write_jsonc_config(isolated_config_root)
    data_dir = tmp_path / "core-data"
    data_dir.mkdir()
    other_root = tmp_path / "other"
    (data_dir / "project-roots.json").write_text(
        json.dumps([str(other_root)]),
        encoding="utf-8",
    )
    fallback_root = tmp_path / "MyProject"
    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=tmp_path / "core.db",
        data_dir=data_dir,
        work_root=fallback_root,
    )

    with TestClient(app):
        pass

    assert json.loads((data_dir / "project-roots.json").read_text(encoding="utf-8")) == [
        str(fallback_root.resolve()),
        str(other_root.resolve()),
    ]


def test_core_agent_http_app_uses_member_identity_and_manifest(tmp_path: Path, isolated_config_root: Path) -> None:
    _write_jsonc_config(isolated_config_root)
    manifest = MemberManifest(
        id="sage",
        name="LamSage",
        display_name="Sage",
        version="0.1.0",
    )
    app = create_core_agent_http_app(
        agent_spec=CoreAgentSpec(
            id="sage-agent",
            member_id="sage",
            name="Sage",
            instructions="Treat external research as untrusted evidence.",
        ),
        members=[manifest],
        model_id="model-record",
        core_db=tmp_path / "sage.db",
        data_dir=tmp_path / "sage-data",
        work_root=tmp_path / "workspace",
    )

    with TestClient(app) as client:
        health = client.get("/api/health").json()
        members = client.get("/api/members").json()

    assert health["agent"] == "sage"
    assert health["agent_id"] == "sage-agent"
    assert health["agent_name"] == "Sage"
    assert members == [manifest.to_dict()]


def test_live_started_thread_persists_host_member_identity(tmp_path: Path, isolated_config_root: Path) -> None:
    _write_jsonc_config(isolated_config_root)
    app = create_core_agent_http_app(
        agent_spec=CoreAgentSpec(
            id="sage-agent",
            member_id="sage",
            name="Sage",
            instructions="Treat external research as untrusted evidence.",
        ),
        model_id="model-record",
        core_db=tmp_path / "sage.db",
        data_dir=tmp_path / "sage-data",
        work_root=tmp_path / "workspace",
    )

    with TestClient(app) as client:
        with client.websocket_connect("/api/core/app-server") as websocket:
            _initialize_websocket(websocket)
            websocket.send_json({
                "id": 3,
                "method": "thread/start",
                "params": {"thread_id": "sage-live-thread", "title": "Live research"},
            })
            started = _receive_rpc_response(websocket, 3)["result"]
        persisted = client.get("/api/core/sessions/sage-live-thread")

    assert started["thread"]["id"] == "sage-live-thread"
    assert persisted.status_code == 200
    assert persisted.json()["member_id"] == "sage"


def test_live_turn_on_new_thread_persists_host_member_identity(tmp_path: Path, monkeypatch, isolated_config_root: Path) -> None:
    _write_jsonc_config(isolated_config_root)

    async def stream(self, request):
        del self, request
        yield LLMStreamEvent(kind="content_delta", content="done")
        yield LLMStreamEvent(kind="done")

    monkeypatch.setattr(CoreConfigRoutingLLMClient, "stream", stream)
    app = create_core_agent_http_app(
        agent_spec=CoreAgentSpec(id="sage-agent", member_id="sage", name="Sage"),
        model_id="model-record",
        core_db=tmp_path / "sage.db",
        data_dir=tmp_path / "sage-data",
        work_root=tmp_path / "workspace",
    )

    with TestClient(app) as client:
        with client.websocket_connect("/api/core/app-server") as websocket:
            _initialize_websocket(websocket)
            websocket.send_json({
                "id": 3,
                "method": "turn/start",
                "params": {
                    "thread_id": "sage-direct-turn",
                    "client_message_id": "sage-direct-message",
                    "input": [{"type": "text", "text": "research"}],
                },
            })
            started = _receive_rpc_response(websocket, 3)["result"]
            # Wait for the background turn to finish before closing the
            # connection so the async turn task is not cancelled mid-flight.
            import time as _time

            for _ in range(100):
                websocket.send_json({"id": 31, "method": "thread/read", "params": {"thread_id": "sage-direct-turn"}})
                thread_snapshot = _receive_rpc_response(websocket, 31)["result"]["snapshot"]
                if thread_snapshot.get("status") in {"completed", "idle", "failed", "cancelled"}:
                    break
                _time.sleep(0.05)
        persisted = client.get("/api/core/sessions/sage-direct-turn")

    assert started["runtime_start"]["thread_id"] == "sage-direct-turn"
    assert persisted.status_code == 200
    assert persisted.json()["member_id"] == "sage"


@pytest.mark.skip(
    reason="TestClient tears down its asyncio loop before the background ArrangeWorker completes; "
    "arrange lifecycle is covered by direct ArrangeManager tests."
)
def test_core_agent_http_app_exposes_durable_goal_and_arrange_operations(tmp_path: Path, isolated_config_root: Path) -> None:
    _write_jsonc_config(isolated_config_root)
    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=tmp_path / "core.db",
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )

    with TestClient(app) as client:
        with client.websocket_connect("/api/core/app-server") as websocket:
            websocket.send_json({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "test"}}})
            websocket.receive_json()
            websocket.send_json({"id": 2, "method": "initialized", "params": {}})
            websocket.receive_json()
            websocket.send_json({
                "id": 3,
                "method": "goal.create",
                "params": {"thread_id": "thread-1", "objective": "Keep evidence current"},
            })
            goal = websocket.receive_json()["result"]["goal"]
            websocket.send_json({
                "id": 4,
                "method": "arrange.create",
                "params": {
                    "thread_id": "thread-1",
                    "work_root": "test-proj",
                    "kind": "focus",
                    "operation": "goal.list",
                    "payload": {"thread_id": "thread-1"},
                    "trigger": {"type": "event", "key": "evidence.changed"},
                    "max_runs": 1,
                },
            })
            job = websocket.receive_json()["result"]["job"]
            assert job["status"] == "waiting"
            websocket.send_json({"id": 5, "method": "arrange.signal", "params": {"key": "evidence.changed"}})
            assert websocket.receive_json()["result"]["signalled"] == 1

            status = ""
            for request_id in range(6, 30):
                websocket.send_json({"id": request_id, "method": "arrange.get", "params": {"job_id": job["id"]}})
                status = websocket.receive_json()["result"]["job"]["status"]
                if status == "completed":
                    break
                time.sleep(0.02)

    assert status == "completed"


def test_core_agent_http_restart_reclaims_running_arrange_occurrence(tmp_path: Path, isolated_config_root: Path) -> None:
    core_db = tmp_path / "core.db"
    _write_jsonc_config(isolated_config_root)

    async def seed_abandoned_job() -> tuple[str, str]:
        db = await open_core_app_db(core_db)
        try:
            # Seed the job from a minute ago so the lease claimed by the dead
            # "stopped-process" worker has already expired — the new app must
            # only reclaim jobs whose lease expired (audit 07: fencing), not
            # steal live work.
            seed_now = datetime.now(timezone.utc) - timedelta(minutes=1)
            job = await ArrangeManager(db.arrange_store).create(
                thread_id="thread-restart",
                work_root="test-proj",
                kind="routine",
                operation="goal.list",
                payload={"thread_id": "thread-restart"},
                trigger={"type": "once", "run_at": seed_now.isoformat()},
                now=seed_now,
            )
            claimed = await db.arrange_store.claim_due(
                now=seed_now,
                worker_id="stopped-process",
                lease_seconds=30,
                limit=1,
            )
            return job.id, claimed[0].occurrence_id
        finally:
            await db.close()

    job_id, occurrence_id = asyncio.run(seed_abandoned_job())
    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=core_db,
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )

    with TestClient(app) as client:
        with client.websocket_connect("/api/core/app-server") as websocket:
            websocket.send_json({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "test"}}})
            websocket.receive_json()
            websocket.send_json({"id": 2, "method": "initialized", "params": {}})
            websocket.receive_json()
            recovered = None
            for request_id in range(3, 30):
                websocket.send_json({"id": request_id, "method": "arrange.get", "params": {"job_id": job_id}})
                recovered = websocket.receive_json()["result"]["job"]
                if recovered["status"] == "completed":
                    break
                time.sleep(0.02)

    assert recovered is not None
    assert recovered["status"] == "completed"
    assert recovered["occurrence_id"] == occurrence_id


def test_core_agent_http_startup_restores_persisted_observer(tmp_path: Path, isolated_config_root: Path) -> None:
    core_db = tmp_path / "core.db"
    data_dir = tmp_path / "core-data"
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    _write_jsonc_config(isolated_config_root)
    script = work_root / "observer.py"
    script.write_text(
        "import json, time\n"
        "print(json.dumps({"
        "'protocol':'lamtools.signal.v1',"
        "'event_id':'offline-video-1',"
        "'event_type':'content.published',"
        "'occurred_at':'2026-07-16T14:00:00Z',"
        "'data':{'title':'published while Core was off'}"
        "}), flush=True)\n"
        "time.sleep(10)\n",
        encoding="utf-8",
    )

    async def seed() -> str:
        db = await open_core_app_db(core_db)
        try:
            job = await ArrangeManager(db.arrange_store).create(
                thread_id="thread-observer-restart",
                work_root="test-proj",
                kind="focus",
                operation="goal.list",
                payload={"thread_id": "thread-observer-restart"},
                trigger={"type": "event", "event_type": "content.published"},
                observer=prepare_observer({"entry": "observer.py"}, work_root=work_root),
                max_runs=1,
            )
            return job.id
        finally:
            await db.close()

    job_id = asyncio.run(seed())
    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=core_db,
        data_dir=data_dir,
        work_root=work_root,
    )

    with TestClient(app) as client:
        with client.websocket_connect("/api/core/app-server") as websocket:
            websocket.send_json({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "test"}}})
            websocket.receive_json()
            websocket.send_json({"id": 2, "method": "initialized", "params": {}})
            websocket.receive_json()
            status = ""
            for request_id in range(3, 80):
                websocket.send_json({
                    "id": request_id,
                    "method": "arrange.get",
                    "params": {"job_id": job_id},
                })
                job = websocket.receive_json()["result"]["job"]
                status = job["status"]
                if status == "completed":
                    break
                time.sleep(0.02)

    assert status == "completed"


def test_core_agent_http_app_owns_attachment_storage(tmp_path: Path, isolated_config_root: Path) -> None:
    _write_jsonc_config(isolated_config_root)
    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=tmp_path / "core.db",
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )
    with TestClient(app) as client:
        uploaded = client.post(
            "/api/core/sessions/thread-attachment/attachments",
            files={"file": ("notes.md", b"line one\nline two", "text/markdown")},
        )
        assert uploaded.status_code == 200
        attachment = uploaded.json()
        preview = client.get(f"/api/core/attachments/{attachment['id']}/preview")
        listed = client.get("/api/core/sessions/thread-attachment/attachments")

    assert preview.json()["text"] == "line one\nline two"
    assert [item["id"] for item in listed.json()["attachments"]] == [attachment["id"]]
    assert (tmp_path / "core-data" / "attachments" / "thread-attachment" / "notes.md").is_file()


def test_core_agent_http_accepts_multiple_attachments_in_one_turn(
    tmp_path: Path,
    monkeypatch,
    isolated_config_root: Path,
) -> None:
    _write_jsonc_config(isolated_config_root)

    async def stream(self, request):
        del self, request
        yield LLMStreamEvent(kind="content_delta", content="已收到附件")
        yield LLMStreamEvent(kind="done")

    monkeypatch.setattr(CoreHttpLLMClient, "stream", stream)
    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=tmp_path / "core.db",
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )

    with TestClient(app) as client:
        uploaded = [
            client.post(
                "/api/core/sessions/pet-session/attachments",
                files={"file": ("report.txt", b"report body", "text/plain")},
            ),
            client.post(
                "/api/core/sessions/pet-session/attachments",
                files={"file": ("data.csv", b"name,value\nA,1\n", "text/csv")},
            ),
        ]
        assert all(response.status_code == 200 for response in uploaded)
        attachments = [response.json() for response in uploaded]
        input_items = [
            {"type": "text", "text": "请比较这两个文件"},
            {
                "type": "attachment",
                "attachment_id": attachments[0]["id"],
                "filename": attachments[0]["filename"],
                "mime_type": attachments[0]["mime_type"],
                "preview_type": attachments[0]["preview_type"],
                "size": attachments[0]["size"],
            },
            {
                "type": "attachment",
                "attachment_id": attachments[1]["id"],
                "filename": attachments[1]["filename"],
                "mime_type": attachments[1]["mime_type"],
                "preview_type": attachments[1]["preview_type"],
                "size": attachments[1]["size"],
            },
        ]

        with client.websocket_connect("/api/core/app-server") as websocket:
            _initialize_websocket(websocket)
            websocket.send_json(
                {
                    "id": 3,
                    "method": "turn/start",
                    "params": {
                        "thread_id": "pet-session",
                        "client_message_id": "pet-attachments",
                        "input": input_items,
                    },
                }
            )
            started = _receive_rpc_response(websocket, 3)["result"]
            user_item_id = started["runtime_start"]["user_message_id"]
            assert started["snapshot"]["items"][user_item_id]["content"] == input_items

            final_snapshot = started["snapshot"]
            for request_id in range(4, 40):
                websocket.send_json(
                    {
                        "id": request_id,
                        "method": "thread/read",
                        "params": {"thread_id": "pet-session"},
                    }
                )
                final_snapshot = _receive_rpc_response(websocket, request_id)["result"]["snapshot"]
                if final_snapshot.get("status") in {"completed", "idle", "failed", "cancelled"}:
                    break
                time.sleep(0.02)

    assert final_snapshot["items"][user_item_id]["content"] == input_items


def test_core_http_sessions_survive_app_restart(tmp_path: Path, isolated_config_root: Path) -> None:
    core_db = tmp_path / "core.db"
    _write_jsonc_config(isolated_config_root)

    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=core_db,
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/core/sessions",
            json={
                "id": "persisted-thread",
                "member_id": "core",
                "title": "Initial title",
                "status": "idle",
                "metadata": {"source": "demo"},
            },
        )
        assert created.status_code == 201
        updated = client.patch(
            "/api/core/sessions/persisted-thread",
            json={"title": "Renamed thread", "metadata": {"source": "restart-test"}},
        )
        assert updated.status_code == 200

    restarted_app = create_core_agent_http_app(
        model_id="model-record",
        core_db=core_db,
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )
    with TestClient(restarted_app) as client:
        response = client.get("/api/core/sessions")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "persisted-thread",
            "member_id": "core",
            "title": "Renamed thread",
            "status": "idle",
            "metadata": {
                "source": "restart-test",
                "work_root": str((tmp_path / "workspace").resolve()),
                "runtime_preferences": {
                    "base_tier": "full_edit",
                    "base_allow_access_outside_workdir": False,
                    "permission_preset": "ask",
                },
            },
            "created_at": created.json()["created_at"],
            "updated_at": updated.json()["updated_at"],
        }
    ]
    assert asyncio.run(list_core_cli_sessions(core_db=core_db)) == [
        {
            "thread_id": "persisted-thread",
            "status": "idle",
            "snapshot_seq": 0,
            "updated_at": updated.json()["updated_at"],
        }
    ]


def test_core_http_session_delete_removes_persisted_thread(tmp_path: Path, isolated_config_root: Path) -> None:
    core_db = tmp_path / "core.db"
    _write_jsonc_config(isolated_config_root)

    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=core_db,
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )
    with TestClient(app) as client:
        assert client.post(
            "/api/core/sessions",
            json={
                "id": "deleted-thread",
                "member_id": "core",
                "title": "Delete me",
                "status": "idle",
            },
        ).status_code == 201
        deleted = client.delete("/api/core/sessions/deleted-thread")
        missing = client.delete("/api/core/sessions/deleted-thread")

    assert deleted.status_code == 204
    assert missing.status_code == 404

    restarted_app = create_core_agent_http_app(
        model_id="model-record",
        core_db=core_db,
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )
    with TestClient(restarted_app) as client:
        assert client.get("/api/core/sessions").json() == []
        assert client.get("/api/core/sessions/deleted-thread").status_code == 404
    assert asyncio.run(list_core_cli_sessions(core_db=core_db)) == []


def test_project_http_round_trip_survives_restart_and_uses_agents_md(tmp_path: Path, isolated_config_root: Path) -> None:
    core_db = tmp_path / "core.db"
    root = tmp_path / "workspace"
    docs_root = root / "docs"
    _write_jsonc_config(isolated_config_root)

    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=core_db,
        data_dir=tmp_path / "core-data",
        work_root=root,
    )
    with TestClient(app) as client:
        unnamed = client.post(
            "/api/core/projects",
            json={"name": "   ", "work_root": str(root / "invalid-name")},
        )
        assert unnamed.status_code == 201
        assert unnamed.json()["project"]["name"] == "invalid-name"
        created = client.post("/api/core/projects", json={"name": "Docs", "work_root": str(docs_root)})
        assert created.status_code == 201
        result = created.json()
        project_id = result["project"]["id"]
        assert result["session"]["metadata"] == {
            "work_root": str(docs_root.resolve()),
            "runtime_preferences": {
                "base_tier": "full_edit",
                "base_allow_access_outside_workdir": False,
                "permission_preset": "ask",
            },
        }

        content = "# Project instructions\n\nUse UTF-8.\n"
        assert client.put(f"/api/core/projects/{project_id}/agents-md", json={"content": content}).json() == {
            "content": content,
            "exists": True,
        }
        assert client.get(f"/api/core/projects/{project_id}/agents-md").json() == {
            "content": content,
            "exists": True,
        }
        assert client.get(f"/api/core/projects/{project_id}/sessions").json()["sessions"] == [result["session"]]
        created_session = client.post(
            f"/api/core/projects/{project_id}/sessions",
            json={"title": "Follow-up"},
        )
        assert created_session.status_code == 201
        assert created_session.json()["metadata"] == {
            "work_root": str(docs_root.resolve()),
            "runtime_preferences": {
                "base_tier": "full_edit",
                "base_allow_access_outside_workdir": False,
                "permission_preset": "ask",
            },
        }
        assert client.post(
            "/api/core/sessions",
            json={
                "id": "invalid-project-session",
                "member_id": "core",
                "title": "Invalid",
                "status": "idle",
                "metadata": {"work_root": "E:\\forged"},
            },
        ).status_code == 422

    restarted_app = create_core_agent_http_app(
        model_id="model-record",
        core_db=core_db,
        data_dir=tmp_path / "core-data",
        work_root=root,
    )
    with TestClient(restarted_app) as client:
        assert client.get(f"/api/core/projects/{project_id}").json()["name"] == "Docs"


def test_project_http_delete_rejects_active_session_and_app_server_uses_project_operations(tmp_path: Path, isolated_config_root: Path) -> None:
    _write_jsonc_config(isolated_config_root)
    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=tmp_path / "core.db",
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )
    with TestClient(app) as client:
        with client.websocket_connect("/api/core/app-server") as websocket:
            _initialize_websocket(websocket)
            websocket.send_json(
                {
                    "id": 3,
                    "method": "project.create",
                    "params": {"name": "Docs", "work_root": str(tmp_path / "workspace")},
                }
            )
            created = _receive_rpc_response(websocket, 3)["result"]
            project_id = created["project"]["id"]
            session_id = created["session"]["id"]

            websocket.send_json(
                {
                    "id": 31,
                    "method": "project.create",
                    "params": {"name": "   ", "work_root": str(tmp_path / "workspace" / "invalid")},
                },
            )
            assert _receive_rpc_response(websocket, 31)["result"]["project"]["name"] == "invalid"

            websocket.send_json({"id": 4, "method": "project.get", "params": {"project_id": project_id}})
            assert _receive_rpc_response(websocket, 4)["result"]["project"]["id"] == project_id

            websocket.send_json(
                {"id": 5, "method": "project.update", "params": {"project_id": project_id, "name": "Renamed"}}
            )
            assert _receive_rpc_response(websocket, 5)["result"]["project"]["name"] == "Renamed"

            websocket.send_json(
                {"id": 51, "method": "project.update", "params": {"project_id": project_id, "name": "   "}}
            )
            assert _receive_rpc_response(websocket, 51)["error"]["message"] == "Project name is required"

            websocket.send_json({"id": 6, "method": "project.sessions.list", "params": {"project_id": project_id}})
            assert _receive_rpc_response(websocket, 6)["result"]["sessions"][0]["id"] == session_id

            websocket.send_json({"id": 61, "method": "project.sessions.create", "params": {"project_id": project_id}})
            project_session = _receive_rpc_response(websocket, 61)["result"]["session"]
            assert project_session["metadata"]["work_root"] == str(tmp_path / "workspace")

            websocket.send_json(
                {"id": 7, "method": "project.agents_md.update", "params": {"project_id": project_id, "content": "# Rules\n"}}
            )
            assert _receive_rpc_response(websocket, 7)["result"]["agents_md"] == {"content": "# Rules\n", "exists": True}

            websocket.send_json({"id": 8, "method": "project.agents_md.get", "params": {"project_id": project_id}})
            assert _receive_rpc_response(websocket, 8)["result"]["agents_md"] == {"content": "# Rules\n", "exists": True}
        protected = client.patch(
            f"/api/core/sessions/{session_id}",
            json={"metadata": {"work_root": "E:\\forged", "note": "kept"}},
        )
        assert protected.status_code == 200
        assert protected.json()["metadata"] == {
            "work_root": str((tmp_path / "workspace").resolve()),
            "note": "kept",
            "runtime_preferences": {
                "base_tier": "full_edit",
                "base_allow_access_outside_workdir": False,
                "permission_preset": "ask",
            },
        }
        assert client.patch(f"/api/core/sessions/{session_id}", json={"status": "running"}).status_code == 200
        assert client.delete(f"/api/core/projects/{project_id}").status_code == 409
        assert client.patch(f"/api/core/sessions/{session_id}", json={"status": "idle"}).status_code == 200

        with client.websocket_connect("/api/core/app-server") as websocket:
            _initialize_websocket(websocket)
            websocket.send_json({"id": 9, "method": "project.delete", "params": {"project_id": project_id}})
            assert _receive_rpc_response(websocket, 9)["result"] == {"deleted": True}
        assert client.get(f"/api/core/sessions/{session_id}").status_code == 404


def _receive_rpc_response(websocket, request_id: int) -> dict:
    while True:
        message = websocket.receive_json()
        if message.get("id") == request_id:
            return message


def _initialize_websocket(websocket) -> None:
    websocket.send_json({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "test"}}})
    assert _receive_rpc_response(websocket, 1)["result"]["protocolVersion"] == "core.app_server.v1"
    websocket.send_json({"id": 2, "method": "initialized", "params": {}})
    assert _receive_rpc_response(websocket, 2)["result"] == {"ok": True}


def test_core_http_websocket_active_turn_steer_and_second_start_matrix(tmp_path: Path, monkeypatch, isolated_config_root: Path) -> None:
    _write_jsonc_config(isolated_config_root)
    model_started = threading.Event()
    release_model = threading.Event()
    guided_call_seen = threading.Event()
    requests: list[LLMRequest] = []

    async def fake_stream(self, request):
        requests.append(request)
        if len(requests) == 1:
            model_started.set()
            while not release_model.is_set():
                await asyncio.sleep(0.005)
            yield LLMStreamEvent(kind="content_delta", content="first final")
            yield LLMStreamEvent(kind="done")
            return
        guided_call_seen.set()
        yield LLMStreamEvent(kind="content_delta", content="guided final")
        yield LLMStreamEvent(kind="done")

    monkeypatch.setattr(CoreHttpLLMClient, "stream", fake_stream)
    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=tmp_path / "core.db",
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )
    registry = app.state.core_agent_runtime_task_registry
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/api/core/app-server") as websocket:
                _initialize_websocket(websocket)
                websocket.send_json({
                    "id": 3,
                    "method": "turn/start",
                    "params": {
                        "thread_id": "transport-thread",
                        "client_message_id": "transport-start",
                        "input": [{"type": "text", "text": "start"}],
                    },
                })
                started = _receive_rpc_response(websocket, 3)
                turn_id = started["result"]["runtime_start"]["turn_id"]
                assert model_started.wait(timeout=2)

                websocket.send_json({
                    "id": 4,
                    "method": "turn/start",
                    "params": {
                        "thread_id": "transport-thread",
                        "client_message_id": "transport-second",
                        "input": [{"type": "text", "text": "second"}],
                    },
                })
                rejected_start = _receive_rpc_response(websocket, 4)
                assert rejected_start["error"]["data"] == {
                    "code": "SESSION_BUSY",
                    "reason": "active_turn_exists",
                    "active_run_id": turn_id,
                }

                websocket.send_json({
                    "id": 5,
                    "method": "turn/steer",
                    "params": {
                        "thread_id": "transport-thread",
                        "turn_id": turn_id,
                        "client_message_id": "transport-steer",
                        "input": [{"type": "text", "text": "transport guidance"}],
                    },
                })
                steered = _receive_rpc_response(websocket, 5)
                assert steered["result"]["applied"] is True
                release_model.set()
                assert guided_call_seen.wait(timeout=2)
        assert len(requests) == 2
        assert any(message.content == "transport guidance" for message in requests[1].messages)
    finally:
        release_model.set()
        registry.clear()


def test_core_http_websocket_rejects_steer_after_kernel_seal_before_task_done(tmp_path: Path, monkeypatch, isolated_config_root: Path) -> None:
    _write_jsonc_config(isolated_config_root)
    sealed_window = threading.Event()
    release_writeback = threading.Event()
    original_writeback = CoreBaseAgentKit.writeback

    async def fake_stream(self, request):
        yield LLMStreamEvent(kind="content_delta", content="final")
        yield LLMStreamEvent(kind="done")

    async def blocking_writeback(self, state, turn, tool_results, verification, decision):
        if decision == "done":
            sealed_window.set()
            while not release_writeback.is_set():
                await asyncio.sleep(0.005)
        return await original_writeback(self, state, turn, tool_results, verification, decision)

    monkeypatch.setattr(CoreHttpLLMClient, "stream", fake_stream)
    monkeypatch.setattr(CoreBaseAgentKit, "writeback", blocking_writeback)
    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=tmp_path / "core.db",
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )
    registry = app.state.core_agent_runtime_task_registry
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/api/core/app-server") as websocket:
                _initialize_websocket(websocket)
                websocket.send_json({
                    "id": 3,
                    "method": "turn/start",
                    "params": {
                        "thread_id": "sealed-transport-thread",
                        "client_message_id": "sealed-start",
                        "input": [{"type": "text", "text": "finish"}],
                    },
                })
                started = _receive_rpc_response(websocket, 3)
                turn_id = started["result"]["runtime_start"]["turn_id"]
                assert sealed_window.wait(timeout=2)
                runtime_task = registry.task("sealed-transport-thread", run_id=turn_id)
                assert runtime_task is not None
                runtime_done = threading.Event()
                runtime_task.add_done_callback(lambda _task: runtime_done.set())

                websocket.send_json({
                    "id": 4,
                    "method": "turn.steer",
                    "params": {
                        "thread_id": "sealed-transport-thread",
                        "turn_id": turn_id,
                        "client_message_id": "sealed-late-steer",
                        "input": [{"type": "text", "text": "too late"}],
                    },
                })
                rejected = _receive_rpc_response(websocket, 4)
                assert rejected["result"]["applied"] is False
                assert rejected["result"]["reason"] == "run_not_active"
                release_writeback.set()
                assert runtime_done.wait(timeout=2)
    finally:
        release_writeback.set()
        registry.clear()


def test_core_agent_http_app_exposes_shared_model_catalog_without_secrets(tmp_path: Path, isolated_config_root: Path) -> None:
    # isolated_config_root (autouse conftest fixture) isolates from the
    # developer's real ~/.lam/config jsonc files.
    _write_jsonc_config(isolated_config_root)
    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=tmp_path / "core.db",
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )

    with TestClient(app) as client:
        response = client.get("/api/core/config/models")

    assert response.status_code == 200
    body = response.json()
    assert body["models"] == [
        {
            "id": "model-record",
            "provider_id": "provider-1",
            "provider_name": "Provider",
            "provider_api_type": "openai",
            "model_id": "model-record",
            "display_name": "Model Name",
            "context_window": 128000,
            "max_output_tokens": 4096,
            "thinking_supported": True,
            "thinking_budget": 10000,
            "temperature": 0.2,
            "capability": "text",
            "reasoning_off_supported": True,
            "notes": "",
            "is_default": False,
            "adapter_profile_id": "",
        }
    ]
    assert "secret" not in response.text


def test_core_agent_http_app_exposes_config_catalog_over_live_operations(tmp_path: Path, isolated_config_root: Path) -> None:
    # isolated_config_root (autouse conftest fixture) isolates from the
    # developer's real ~/.lam/config jsonc files.
    _write_jsonc_config(isolated_config_root)
    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=tmp_path / "core.db",
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )

    with TestClient(app) as client:
        with client.websocket_connect("/api/core/app-server") as websocket:
            websocket.send_json(
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {"clientInfo": {"name": "test"}},
                }
            )
            websocket.receive_json()
            websocket.send_json({"id": 2, "method": "initialized", "params": {}})
            websocket.receive_json()

            websocket.send_json({"id": 3, "method": "config.models.list", "params": {}})
            models = websocket.receive_json()
            websocket.send_json({"id": 4, "method": "config.providers.list", "params": {}})
            providers = websocket.receive_json()
            websocket.send_json({
                "id": 5,
                "method": "config.resolved.get",
                "params": {"model_id": "model-record"},
            })
            resolved = websocket.receive_json()

    assert models["id"] == 3
    assert models["result"]["models"][0]["id"] == "model-record"
    assert models["result"]["default_model_id"] == "model-record"
    assert providers["id"] == 4
    assert providers["result"]["providers"] == [
        {
            "id": "provider-1",
            "name": "Provider",
            "api_type": "openai",
            "base_url": "https://example.test/v1",
            "api_key": "********",
            "has_api_key": True,
            "is_default": False,
            "extra": {},
        }
    ]
    assert "secret" not in str(providers)
    assert resolved["id"] == 5
    assert resolved["result"]["resolved"]["model"]["reasoning_off_supported"] is True
    operations = app.state.core_agent_app_state["operations"]
    assert {
        "project.list",
        "project.create",
        "project.get",
        "project.update",
        "project.delete",
        "project.sessions.list",
        "project.agents_md.get",
        "project.agents_md.update",
    } <= set(operations.list())
    assert operations.has("config.provider.create")
    assert operations.has("config.model.update")
    assert operations.has("plugin.list")
    assert operations.has("hook.trust")


@pytest.mark.asyncio
async def test_core_config_routing_llm_client_uses_per_request_model_and_thinking(tmp_path: Path, monkeypatch, isolated_config_root: Path) -> None:
    _write_two_model_jsonc_config(isolated_config_root)
    captured: list[dict[str, object]] = []

    async def fake_stream(self, request):
        captured.append(
            {
                "config_model": self.config.model_id,
                "request_model": request.model,
                "thinking_enabled": self.thinking_enabled,
                "thinking_budget": self.thinking_budget,
            }
        )
        yield LLMStreamEvent(kind="done")

    monkeypatch.setattr(CoreHttpLLMClient, "stream", fake_stream)
    client = CoreConfigRoutingLLMClient(
        default_model_ref="model-record",
        thinking_enabled=True,
        thinking_budget=10000,
        max_tokens=4096,
        temperature=0.2,
    ).with_runtime_options(
        model_id="second-record",
        thinking_enabled=False,
        thinking_budget=1234,
    )

    events = [event async for event in client.stream(LLMRequest(model="second-record"))]

    assert [event.kind for event in events] == ["done"]
    assert captured == [
        {
            "config_model": "second-record",
            "request_model": "second-record",
            "thinking_enabled": False,
            "thinking_budget": 1234,
        }
    ]


@pytest.mark.asyncio
async def test_core_config_routing_llm_client_uses_selected_model_output_limit_by_default(
    tmp_path: Path,
    monkeypatch,
    isolated_config_root: Path,
) -> None:
    _write_two_model_jsonc_config(isolated_config_root)
    captured: list[int] = []

    async def fake_stream(self, request):
        captured.append(self.max_tokens)
        yield LLMStreamEvent(kind="done")

    monkeypatch.setattr(CoreHttpLLMClient, "stream", fake_stream)
    client = CoreConfigRoutingLLMClient(
        default_model_ref="model-record",
        thinking_enabled=True,
        thinking_budget=10000,
        max_tokens=None,
        temperature=0.2,
    )

    events = [event async for event in client.stream(LLMRequest(model="second-record"))]

    assert [event.kind for event in events] == ["done"]
    assert captured == [8192]


def test_core_http_serves_enabled_desktop_plugin_assets(
    tmp_path: Path,
    isolated_config_root: Path,
) -> None:
    _write_jsonc_config(isolated_config_root)
    data_dir = tmp_path / "core-data"
    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=tmp_path / "core.db",
        data_dir=data_dir,
        work_root=tmp_path / "workspace",
    )

    with TestClient(app) as client:
        listed = client.get("/api/core/desktop-plugins")
        assert listed.status_code == 200
        pet = next(item for item in listed.json()["plugins"] if item["name"] == "emotion-ball-pet")
        assert pet["window"]["collapsedWidth"] == 256
        assert pet["window"]["collapsedHeight"] == 288
        assert pet["window"]["expandedWidth"] == 506
        assert pet["window"]["expandedHeight"] == 680
        assert pet["window"]["cardWidth"] == 506
        assert pet["window"]["cardHeight"] == 360
        assert pet["fileDrop"] is True

        html = client.get(pet["entry_url"])
        script = client.get(
            "/api/core/desktop-plugins/emotion-ball-pet/assets/pet.js"
        )
        escaped = client.get(
            "/api/core/desktop-plugins/emotion-ball-pet/assets/%2E%2E/plugin.json"
        )
        assert html.status_code == 200
        assert "LamTools 桌宠" in html.text
        assert "x-frame-options" not in html.headers
        assert html.headers["cross-origin-resource-policy"] == "cross-origin"
        assert "http://127.0.0.1:*" in html.headers["content-security-policy"]
        assert html.headers["cache-control"] == "no-store"
        assert script.status_code == 200
        assert "当前会话" not in html.text
        assert "向 Core 提问" not in html.text
        assert "turn/start" in script.text
        assert "/api/core/desktop-plugins/emotion-ball-pet/session" in script.text
        assert "fetch('/api/core/sessions/'" in script.text
        assert "/attachments" in script.text
        assert "files-dropped" in script.text
        assert "approval/respond" in script.text
        assert "toolName === 'question'" in script.text
        assert "set_desktop_plugin_view_mode" in script.text
        assert 'id="queuePreviewSecond"' in html.text
        assert 'id="queuePreviewThird"' in html.text
        assert escaped.status_code == 404

        (data_dir / "plugins.jsonc").write_text(
            '{"plugins":{"emotion-ball-pet":{"enabled":false}}}',
            encoding="utf-8",
        )
        disabled = client.get("/api/core/desktop-plugins")
        disabled_asset = client.get(pet["entry_url"])

    assert all(item["name"] != "emotion-ball-pet" for item in disabled.json()["plugins"])
    assert disabled_asset.status_code == 404


def _write_desktop_plugin(root: Path, name: str) -> None:
    plugin_root = root / name
    (plugin_root / "desktop").mkdir(parents=True, exist_ok=True)
    (plugin_root / "plugin.json").write_text(
        '{\n'
        f'  "name": "{name}",\n'
        '  "version": "0.1.0",\n'
        '  "desktop": {\n'
        '    "entry": "./desktop/index.html",\n'
        f'    "title": "{name}",\n'
        '    "window": {}\n'
        '  }\n'
        '}\n',
        encoding="utf-8",
    )
    (plugin_root / "desktop" / "index.html").write_text("<!doctype html>", encoding="utf-8")


def _desktop_session_test_app(tmp_path: Path, isolated_config_root: Path, plugin_roots: tuple[Path, ...] = ()):
    _write_jsonc_config(isolated_config_root)
    return create_core_agent_http_app(
        model_id="model-record",
        core_db=tmp_path / "core.db",
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
        plugin_roots=plugin_roots,
    )


def test_desktop_plugin_session_is_created_once(tmp_path: Path, isolated_config_root: Path) -> None:
    app = _desktop_session_test_app(tmp_path, isolated_config_root)
    with TestClient(app) as client:
        first = client.post("/api/core/desktop-plugins/emotion-ball-pet/session")
        second = client.post("/api/core/desktop-plugins/emotion-ball-pet/session")

    restarted = _desktop_session_test_app(tmp_path, isolated_config_root)
    with TestClient(restarted) as client:
        after_restart = client.post("/api/core/desktop-plugins/emotion-ball-pet/session")

    assert first.status_code == 200
    assert second.status_code == 200
    assert after_restart.status_code == 200
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert after_restart.json()["created"] is False
    assert first.json()["session_id"] == second.json()["session_id"]
    assert first.json()["session_id"] == after_restart.json()["session_id"]


def test_desktop_plugin_session_isolated_between_plugins(tmp_path: Path, isolated_config_root: Path) -> None:
    plugins = tmp_path / "plugins"
    _write_desktop_plugin(plugins, "plugin-a")
    _write_desktop_plugin(plugins, "plugin-b")
    app = _desktop_session_test_app(tmp_path, isolated_config_root, (plugins,))

    with TestClient(app) as client:
        session_a = client.post("/api/core/desktop-plugins/plugin-a/session")
        session_b = client.post("/api/core/desktop-plugins/plugin-b/session")

    assert session_a.status_code == 200
    assert session_b.status_code == 200
    assert session_a.json()["session_id"] != session_b.json()["session_id"]


def test_deleted_desktop_plugin_session_is_recreated(tmp_path: Path, isolated_config_root: Path) -> None:
    app = _desktop_session_test_app(tmp_path, isolated_config_root)
    with TestClient(app) as client:
        first = client.post("/api/core/desktop-plugins/emotion-ball-pet/session").json()
        assert client.delete(f"/api/core/sessions/{first['session_id']}").status_code == 204
        second = client.post("/api/core/desktop-plugins/emotion-ball-pet/session").json()

    assert first["created"] is True
    assert second["created"] is True
    assert first["session_id"] != second["session_id"]


def test_disabled_plugin_cannot_ensure_session(tmp_path: Path, isolated_config_root: Path) -> None:
    app = _desktop_session_test_app(tmp_path, isolated_config_root)
    data_dir = tmp_path / "core-data"
    with TestClient(app) as client:
        (data_dir / "plugins.jsonc").write_text(
            '{"plugins":{"emotion-ball-pet":{"enabled":false}}}',
            encoding="utf-8",
        )
        response = client.post("/api/core/desktop-plugins/emotion-ball-pet/session")

    assert response.status_code == 404
