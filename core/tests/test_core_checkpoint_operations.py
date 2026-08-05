from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import lamtools_core.cli as core_cli
from lamtools_core.app import open_core_app_db
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.http_agent_app import create_core_agent_http_app
from lamtools_core.checkpoint import CoreCheckpointCoordinator
from lamtools_core.cli import build_parser
from lamtools_core.runtime import RuntimeState
from lamtools_core.session import SessionRecord


def _write_config_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            create table llm_providers (
                id text primary key, name text, api_type text, base_url text,
                api_key text, extra text, created_at text
            );
            create table llm_models (
                id text primary key, provider_id text, model_id text, display_name text,
                context_window integer, max_output_tokens integer,
                thinking_supported integer, thinking_budget integer,
                temperature real, extra text, created_at text
            );
            insert into llm_providers values (
                'provider-1', 'Provider', 'openai', 'https://example.test/v1',
                'secret', '{}', '2026-01-01'
            );
            insert into llm_models values (
                'model-record', 'provider-1', 'model-name', 'Model Name',
                128000, 4096, 0, 0, 0.2, '{}', '2026-01-01'
            );
            """
        )
        connection.commit()
    finally:
        connection.close()


async def _seed_checkpoint(
    *,
    core_db: Path,
    work_root: Path,
    session_id: str,
    turn_id: str,
    status: str = "idle",
):
    db = await open_core_app_db(core_db)
    sessions = CoreDbSessionStore(lambda: db)
    try:
        if await sessions.get(session_id) is None:
            await sessions.create(SessionRecord(
                id=session_id,
                member_id="core",
                title=session_id,
                status=status,
                metadata={"work_root": str(work_root)},
            ))
        await db.runtime_state_store.save(RuntimeState(
            session_id=session_id,
            run_id=turn_id if status in {"running", "waiting"} else "",
            status=status,
        ))
        coordinator = CoreCheckpointCoordinator(
            work_root=work_root,
            session_factory=db.session_factory,
            write_coordinator=db.persistence.write_coordinator,
        )
        return await coordinator.begin_turn(
            session_id=session_id,
            turn_id=turn_id,
            actor_kind="main",
        )
    finally:
        await db.close()


def _initialize(websocket) -> None:
    websocket.send_json({
        "id": 1,
        "method": "initialize",
        "params": {"clientInfo": {"name": "checkpoint-test"}},
    })
    assert websocket.receive_json()["result"]["protocolVersion"] == "core.app_server.v1"


def _request(websocket, request_id: int, method: str, params: dict) -> dict:
    websocket.send_json({"id": request_id, "method": method, "params": params})
    while True:
        response = websocket.receive_json()
        if response.get("id") == request_id:
            return response


def test_core_app_server_uses_one_operation_contract_for_list_rollback_and_restart_safe_undo(
    tmp_path: Path,
) -> None:
    config_db = tmp_path / "config.db"
    core_db = tmp_path / "core.db"
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    _write_config_db(config_db)
    target = work_root / "state.txt"
    target.write_text("before\n", encoding="utf-8")
    checkpoint = asyncio.run(_seed_checkpoint(
        core_db=core_db,
        work_root=work_root,
        session_id="session-operation",
        turn_id="turn-2",
    ))
    target.write_text("after\n", encoding="utf-8")

    first_app = create_core_agent_http_app(
        model_id="model-record",
        config_db=config_db,
        core_db=core_db,
        data_dir=tmp_path / "core-data",
        work_root=work_root,
    )
    with TestClient(first_app) as client:
        with client.websocket_connect("/api/core/app-server") as websocket:
            _initialize(websocket)
            listed = _request(
                websocket,
                2,
                "session.checkpoints.list",
                {"session_id": "session-operation"},
            )
            assert [item["id"] for item in listed["result"]["checkpoints"]] == [checkpoint.id]

            rolled_back = _request(
                websocket,
                3,
                "session.rollback",
                {"session_id": "session-operation", "checkpoint_id": checkpoint.id},
            )["result"]

    assert rolled_back["status"] == "committed"
    assert set(rolled_back) == {
        "operation_id",
        "checkpoint_id",
        "undo_checkpoint_id",
        "derived_checkpoint_id",
        "scope",
        "status",
        "restored_paths",
    }
    assert target.read_text(encoding="utf-8") == "before\n"

    restarted_app = create_core_agent_http_app(
        model_id="model-record",
        config_db=config_db,
        core_db=core_db,
        data_dir=tmp_path / "core-data-restarted",
        work_root=work_root,
    )
    with TestClient(restarted_app) as client:
        with client.websocket_connect("/api/core/app-server") as websocket:
            _initialize(websocket)
            undone = _request(
                websocket,
                4,
                "session.rollback.undo",
                {
                    "session_id": "session-operation",
                    "operation_id": rolled_back["operation_id"],
                },
            )["result"]

    assert undone["status"] == rolled_back["status"] == "committed"
    assert set(undone) == set(rolled_back)
    assert target.read_text(encoding="utf-8") == "after\n"


def test_core_app_server_rejects_missing_foreign_and_active_turn_checkpoints(tmp_path: Path) -> None:
    config_db = tmp_path / "config.db"
    core_db = tmp_path / "core.db"
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    _write_config_db(config_db)
    idle_checkpoint = asyncio.run(_seed_checkpoint(
        core_db=core_db,
        work_root=work_root,
        session_id="session-idle",
        turn_id="idle-turn",
    ))
    active_checkpoint = asyncio.run(_seed_checkpoint(
        core_db=core_db,
        work_root=work_root,
        session_id="session-active",
        turn_id="active-turn",
        status="running",
    ))
    app = create_core_agent_http_app(
        model_id="model-record",
        config_db=config_db,
        core_db=core_db,
        data_dir=tmp_path / "core-data",
        work_root=work_root,
    )
    with TestClient(app) as client:
        with client.websocket_connect("/api/core/app-server") as websocket:
            _initialize(websocket)
            missing = _request(
                websocket,
                2,
                "session.rollback",
                {"session_id": "session-idle", "checkpoint_id": "missing-checkpoint"},
            )
            foreign = _request(
                websocket,
                3,
                "session.rollback",
                {"session_id": "session-idle", "checkpoint_id": active_checkpoint.id},
            )
            active = _request(
                websocket,
                4,
                "session.rollback",
                {"session_id": "session-active", "checkpoint_id": active_checkpoint.id},
            )

    assert "error" in missing and "checkpoint" in missing["error"]["message"].lower()
    assert "error" in foreign and "session" in foreign["error"]["message"].lower()
    assert "error" in active and "active" in active["error"]["message"].lower()
    assert idle_checkpoint.id != active_checkpoint.id


@pytest.mark.asyncio
async def test_core_cli_checkpoint_commands_are_thin_adapters_over_the_same_operations(
    monkeypatch,
    capsys,
) -> None:
    calls: list[tuple[str, dict]] = []
    operation_result = {
        "operation_id": "operation-1",
        "checkpoint_id": "checkpoint-1",
        "undo_checkpoint_id": "undo-1",
        "status": "committed",
        "restored_paths": ["state.txt"],
    }

    class FakeClient:
        def __init__(self, base_url: str, *, path: str, token: str) -> None:
            del base_url, path, token

        async def connect(self) -> None:
            pass

        async def close(self) -> None:
            pass

        async def request(self, method: str, params: dict):
            calls.append((method, params))
            if method == "session.checkpoints.list":
                return {"checkpoints": [{"id": "checkpoint-1", "status": "ready"}]}
            return dict(operation_result)

    monkeypatch.setattr(core_cli, "CoreAppServerClient", FakeClient)
    parser = build_parser()
    commands = [
        ["session", "checkpoints", "session-1", "--raw"],
        ["session", "rollback", "session-1", "checkpoint-1", "--raw"],
        ["session", "rollback-undo", "session-1", "operation-1", "--raw"],
    ]
    for command in commands:
        args = parser.parse_args(command)
        assert await args.func(args) == 0

    assert calls == [
        ("session.checkpoints.list", {"session_id": "session-1"}),
        (
            "session.rollback",
            {"session_id": "session-1", "checkpoint_id": "checkpoint-1"},
        ),
        (
            "session.rollback.undo",
            {"session_id": "session-1", "operation_id": "operation-1"},
        ),
    ]
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[0]["checkpoints"][0]["id"] == "checkpoint-1"
    assert output[1] == output[2] == operation_result
