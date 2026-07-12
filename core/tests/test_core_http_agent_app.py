from __future__ import annotations

import asyncio
import sqlite3
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lamtools_core.app.http_agent_app import (
    CoreConfigRoutingLLMClient,
    create_core_agent_http_app,
)
from lamtools_core.cli import CoreHttpLLMClient, list_core_cli_sessions
from lamtools_core.llm import LLMRequest, LLMStreamEvent
from lamtools_core.app.base_agent import CoreBaseAgentKit
from lamtools_core.runtime import default_runtime_task_registry


def _write_config_db(path: Path) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute(
            """
            create table llm_providers (
                id text primary key,
                name text,
                api_type text,
                base_url text,
                api_key text,
                extra text,
                created_at text
            )
            """
        )
        con.execute(
            """
            create table llm_models (
                id text primary key,
                provider_id text,
                model_id text,
                display_name text,
                context_window integer,
                max_output_tokens integer,
                thinking_supported integer,
                thinking_budget integer,
                temperature real,
                extra text,
                created_at text
            )
            """
        )
        con.execute(
            """
            insert into llm_providers (id,name,api_type,base_url,api_key,extra,created_at)
            values ('provider-1','Provider','openai','https://example.test/v1','secret','{}','2026-01-01')
            """
        )
        con.execute(
            """
            insert into llm_models (
                id,provider_id,model_id,display_name,context_window,max_output_tokens,
                thinking_supported,thinking_budget,temperature,extra,created_at
            )
            values (
                'model-record','provider-1','model-name','Model Name',128000,4096,
                1,10000,0.2,'{}','2026-01-01'
            )
            """
        )
        con.commit()
    finally:
        con.close()


def _write_two_model_config_db(path: Path) -> None:
    _write_config_db(path)
    con = sqlite3.connect(path)
    try:
        con.execute(
            """
            insert into llm_models (
                id,provider_id,model_id,display_name,context_window,max_output_tokens,
                thinking_supported,thinking_budget,temperature,extra,created_at
            )
            values (
                'second-record','provider-1','second-provider-model','Second Model',128000,8192,
                1,7000,0.3,'{}','2026-01-02'
            )
            """
        )
        con.commit()
    finally:
        con.close()


def test_core_agent_http_app_exposes_live_app_server(tmp_path: Path) -> None:
    config_db = tmp_path / "lamtools-config.db"
    _write_config_db(config_db)
    app = create_core_agent_http_app(
        model_id="model-record",
        config_db=config_db,
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


def test_core_http_sessions_survive_app_restart(tmp_path: Path) -> None:
    config_db = tmp_path / "lamtools-config.db"
    core_db = tmp_path / "core.db"
    _write_config_db(config_db)

    app = create_core_agent_http_app(
        model_id="model-record",
        config_db=config_db,
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
        config_db=config_db,
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
            "metadata": {"source": "restart-test"},
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


def test_core_http_session_delete_removes_persisted_thread(tmp_path: Path) -> None:
    config_db = tmp_path / "lamtools-config.db"
    core_db = tmp_path / "core.db"
    _write_config_db(config_db)

    app = create_core_agent_http_app(
        model_id="model-record",
        config_db=config_db,
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
        config_db=config_db,
        core_db=core_db,
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )
    with TestClient(restarted_app) as client:
        assert client.get("/api/core/sessions").json() == []
        assert client.get("/api/core/sessions/deleted-thread").status_code == 404
    assert asyncio.run(list_core_cli_sessions(core_db=core_db)) == []


def test_project_http_round_trip_survives_restart_and_uses_agents_md(tmp_path: Path) -> None:
    config_db = tmp_path / "lamtools-config.db"
    core_db = tmp_path / "core.db"
    root = tmp_path / "workspace"
    _write_config_db(config_db)

    app = create_core_agent_http_app(
        model_id="model-record",
        config_db=config_db,
        core_db=core_db,
        data_dir=tmp_path / "core-data",
        work_root=root,
    )
    with TestClient(app) as client:
        created = client.post("/api/core/projects", json={"name": "Docs", "work_root": str(root)})
        assert created.status_code == 201
        result = created.json()
        project_id = result["project"]["id"]
        assert result["session"]["metadata"] == {
            "project_id": project_id,
            "work_root": str(root.resolve()),
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

    restarted_app = create_core_agent_http_app(
        model_id="model-record",
        config_db=config_db,
        core_db=core_db,
        data_dir=tmp_path / "core-data",
        work_root=root,
    )
    with TestClient(restarted_app) as client:
        assert client.get(f"/api/core/projects/{project_id}").json()["name"] == "Docs"


def test_project_http_delete_rejects_active_session_and_app_server_uses_project_operations(tmp_path: Path) -> None:
    config_db = tmp_path / "lamtools-config.db"
    _write_config_db(config_db)
    app = create_core_agent_http_app(
        model_id="model-record",
        config_db=config_db,
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
        assert client.patch(f"/api/core/sessions/{session_id}", json={"status": "running"}).status_code == 200
        assert client.delete(f"/api/core/projects/{project_id}").status_code == 409


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


def test_core_http_websocket_active_turn_steer_and_second_start_matrix(tmp_path: Path, monkeypatch) -> None:
    config_db = tmp_path / "lamtools-config.db"
    _write_config_db(config_db)
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
    registry = default_runtime_task_registry()
    registry.clear()
    app = create_core_agent_http_app(
        model_id="model-record",
        config_db=config_db,
        core_db=tmp_path / "core.db",
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )
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


def test_core_http_websocket_rejects_steer_after_kernel_seal_before_task_done(tmp_path: Path, monkeypatch) -> None:
    config_db = tmp_path / "lamtools-config.db"
    _write_config_db(config_db)
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
    registry = default_runtime_task_registry()
    registry.clear()
    app = create_core_agent_http_app(
        model_id="model-record",
        config_db=config_db,
        core_db=tmp_path / "core.db",
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )
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
                assert registry.task("sealed-transport-thread", run_id=turn_id) is not None

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
    finally:
        release_writeback.set()
        registry.clear()


def test_core_agent_http_app_exposes_shared_model_catalog_without_secrets(tmp_path: Path) -> None:
    config_db = tmp_path / "lamtools-config.db"
    _write_config_db(config_db)
    app = create_core_agent_http_app(
        model_id="model-record",
        config_db=config_db,
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
            "model_id": "model-name",
            "display_name": "Model Name",
            "context_window": 128000,
            "max_output_tokens": 4096,
            "thinking_supported": True,
            "thinking_budget": 10000,
            "temperature": 0.2,
        }
    ]
    assert "secret" not in response.text


def test_core_agent_http_app_exposes_config_catalog_over_live_operations(tmp_path: Path) -> None:
    config_db = tmp_path / "lamtools-config.db"
    _write_config_db(config_db)
    app = create_core_agent_http_app(
        model_id="model-record",
        config_db=config_db,
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

    assert models["id"] == 3
    assert models["result"]["models"][0]["id"] == "model-record"
    assert providers["id"] == 4
    assert providers["result"]["providers"] == [
        {
            "id": "provider-1",
            "name": "Provider",
            "api_type": "openai",
            "base_url": "https://example.test/v1",
        }
    ]
    assert "secret" not in str(providers)
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
async def test_core_config_routing_llm_client_uses_per_request_model_and_thinking(tmp_path: Path, monkeypatch) -> None:
    config_db = tmp_path / "lamtools-config.db"
    _write_two_model_config_db(config_db)
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
        config_db_path=config_db,
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
            "config_model": "second-provider-model",
            "request_model": "second-provider-model",
            "thinking_enabled": False,
            "thinking_budget": 1234,
        }
    ]
