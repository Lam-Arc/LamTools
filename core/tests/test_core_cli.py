from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from lamtools_core import cli as core_cli
from lamtools_core.cli import CoreCliRunOptions, build_parser, load_llm_config, main, run_core_cli_task
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall, LLMUsage
from lamtools_core.llm.shallow_thinking import SHALLOW_THINKING_PROMPT


class ScriptedCoreCliLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core CLI proof should use streaming when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield LLMStreamEvent(kind="thinking_delta", content="Need to create the document first.")
            yield LLMStreamEvent(
                kind="tool_call_delta",
                metadata={
                    "tool_calls_delta": [
                        {
                            "index": 0,
                            "id": "call_write",
                            "function": {
                                "name": "write_file",
                                "arguments": '{"path":"core-proof.md"}',
                            },
                        }
                    ]
                },
            )
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call_write",
                        name="write_file",
                        arguments={
                            "path": "core-proof.md",
                            "content": "\n".join(f"Line {i}" for i in range(1, 12)),
                        },
                    )
                ],
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
                metadata={"finish_reason": "stop"},
            )
            return

        yield LLMStreamEvent(kind="thinking_delta", content="The tool result is present; answer now.")
        yield LLMStreamEvent(kind="content_delta", content="Saved core-proof.md with 11 lines.")
        yield LLMStreamEvent(
            kind="done",
            usage=LLMUsage(prompt_tokens=12, completion_tokens=6),
            metadata={"finish_reason": "stop"},
        )


class ScriptedCoreCliReadLLM:
    def __init__(self, *, path: str) -> None:
        self.path = path
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core CLI proof should use streaming when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield LLMStreamEvent(kind="thinking_delta", content="Need to read the resource.")
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[LLMToolCall(id="call-read", name="read_file", arguments={"path": self.path})],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content="Read the plugin resource.")
        yield LLMStreamEvent(kind="done")


class ScriptedCoreCliAnswerOnlyLLM:
    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core CLI should use streaming when available")

    async def stream(self, request: LLMRequest):
        yield LLMStreamEvent(kind="thinking_delta", content="Answer directly.")
        yield LLMStreamEvent(kind="content_delta", content="Core can answer a simple question.")
        yield LLMStreamEvent(kind="done", usage=LLMUsage(prompt_tokens=5, completion_tokens=7))


class FailingCoreCliLLM:
    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError("model unavailable")

    async def stream(self, request: LLMRequest):
        raise RuntimeError("model unavailable")
        yield


class ScriptedCoreCliSubAgentLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core CLI should use streaming when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield LLMStreamEvent(kind="done", tool_calls=[
                LLMToolCall(
                    id="call-cli-sub",
                    name="sub_agent",
                    arguments={"task": "write delegated.txt", "agent": "writer"},
                )
            ])
            return
        if len(self.requests) == 2:
            yield LLMStreamEvent(kind="done", tool_calls=[
                LLMToolCall(
                    id="call-cli-child-write",
                    name="write_file",
                    arguments={"path": "delegated.txt", "content": "delegated content"},
                )
            ])
            return
        if len(self.requests) == 3:
            yield LLMStreamEvent(kind="content_delta", content="Child saved delegated.txt.")
            yield LLMStreamEvent(kind="done")
            return
        yield LLMStreamEvent(kind="content_delta", content="Main received the delegated result.")
        yield LLMStreamEvent(kind="done")


class CapturingCoreCliLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core CLI should use streaming when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        yield LLMStreamEvent(kind="thinking_delta", content="Native thinking.")
        yield LLMStreamEvent(kind="content_delta", content="Core shallow run completed.")
        yield LLMStreamEvent(kind="done")


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


def test_core_cli_parser_exposes_agent_run_options(tmp_path: Path) -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "run",
            "write a document",
            "--model-id",
            "xopkimik26",
            "--work-root",
            str(tmp_path),
            "--core-db",
            str(tmp_path / "core.db"),
            "--thread-id",
            "thread-cli",
            "--shallow-thinking",
            "--raw",
        ]
    )

    assert args.command == "run"
    assert args.message == ["write a document"]
    assert args.model_id == "xopkimik26"
    assert args.work_root == str(tmp_path)
    assert args.core_db == str(tmp_path / "core.db")
    assert args.thread_id == "thread-cli"
    assert args.shallow_thinking is True
    assert args.raw is True


def test_core_cli_parser_exposes_session_query_commands(tmp_path: Path) -> None:
    parser = build_parser()

    list_args = parser.parse_args(["session", "list", "--core-db", str(tmp_path / "core.db"), "--raw"])
    ls_args = parser.parse_args(["session", "ls", "--core-db", str(tmp_path / "core.db"), "--raw"])
    show_args = parser.parse_args(
        ["session", "show", "thread-cli", "--core-db", str(tmp_path / "core.db"), "--raw"]
    )

    assert list_args.command == "session"
    assert list_args.session_command == "list"
    assert list_args.core_db == str(tmp_path / "core.db")
    assert list_args.raw is True
    assert ls_args.command == "session"
    assert ls_args.session_command == "list"
    assert ls_args.core_db == str(tmp_path / "core.db")
    assert ls_args.raw is True
    assert show_args.command == "session"
    assert show_args.session_command == "show"
    assert show_args.thread_id == "thread-cli"
    assert show_args.core_db == str(tmp_path / "core.db")
    assert show_args.raw is True


def test_core_project_cli_creates_workspace_and_round_trips_agents(monkeypatch, tmp_path: Path, capsys) -> None:
    core_db = tmp_path / "core.db"
    workspace = tmp_path / "workspace"
    rules = tmp_path / "rules.md"
    rules.write_text("# Core rules\n", encoding="utf-8")
    monkeypatch.setenv("LAMTOOLS_CORE_DB", str(core_db))

    assert main(["project", "create", str(workspace), "--name", "Docs"]) == 0
    created = json.loads(capsys.readouterr().out)
    project_id = created["project"]["id"]
    assert created["project"]["name"] == "Docs"
    assert created["project"]["work_root"] == str(workspace.resolve())
    assert created["session"]["metadata"] == {
        "project_id": project_id,
        "work_root": str(workspace.resolve()),
    }

    assert main(["project", "agents", "set", project_id, str(rules)]) == 0
    assert json.loads(capsys.readouterr().out)["agents_md"] == {"content": "# Core rules\n", "exists": True}
    assert main(["project", "agents", "get", project_id]) == 0
    assert json.loads(capsys.readouterr().out)["agents_md"] == {"content": "# Core rules\n", "exists": True}


def test_core_project_cli_lists_shows_renames_and_deletes(monkeypatch, tmp_path: Path, capsys) -> None:
    core_db = tmp_path / "core.db"
    monkeypatch.setenv("LAMTOOLS_CORE_DB", str(core_db))

    assert main(["project", "create", str(tmp_path / "workspace"), "--name", "Docs"]) == 0
    project_id = json.loads(capsys.readouterr().out)["project"]["id"]

    assert main(["project", "list"]) == 0
    assert [project["id"] for project in json.loads(capsys.readouterr().out)["projects"]] == [project_id]
    assert main(["project", "show", project_id]) == 0
    assert json.loads(capsys.readouterr().out)["project"]["name"] == "Docs"
    assert main(["project", "rename", project_id, "Renamed"]) == 0
    assert json.loads(capsys.readouterr().out)["project"]["name"] == "Renamed"
    assert main(["project", "delete", project_id]) == 0
    assert json.loads(capsys.readouterr().out) == {"deleted": True, "project_id": project_id}


def test_core_project_cli_defaults_blank_create_name_and_rejects_blank_rename(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("LAMTOOLS_CORE_DB", str(tmp_path / "core.db"))

    assert main(["project", "create", str(tmp_path / "workspace"), "--name", "   "]) == 0
    project_id = json.loads(capsys.readouterr().out)["project"]["id"]
    assert main(["project", "rename", project_id, "   "]) == 1
    assert "Project name is required" in capsys.readouterr().err


def test_core_cli_parser_exposes_live_control_commands(tmp_path: Path) -> None:
    parser = build_parser()

    serve = parser.parse_args([
        "serve", "--host", "0.0.0.0", "--port", "7123", "--model-id", "core-model",
        "--config-db", str(tmp_path / "config.db"), "--core-db", str(tmp_path / "core.db"),
        "--data-dir", str(tmp_path / "data"), "--work-root", str(tmp_path), "--thinking", "disabled",
        "--thinking-budget", "512", "--max-tokens", "1024", "--temperature", "0.4", "--raw",
    ])
    start = parser.parse_args([
        "start", "thread-1", "start work", "--base-url", "http://core.test", "--ws-path", "/live",
        "--token", "secret", "--work-root", str(tmp_path), "--model-id", "core-model", "--thinking", "disabled",
        "--thinking-budget", "512", "--shallow", "--approval-policy", "auto_approve",
        "--client-message-id", "message-1", "--raw",
    ])
    inherited_start = parser.parse_args(["start", "thread-2", "use shared defaults"])
    cancel = parser.parse_args(["cancel", "thread-1", "--turn-id", "turn-1", "--raw"])
    steer = parser.parse_args(["steer", "thread-1", "turn-1", "change course", "--raw"])
    queue_create = parser.parse_args(["queue", "create", "thread-1", "next task", "--raw"])
    queue_update = parser.parse_args(["queue", "update", "thread-1", "queue-1", "updated", "--raw"])
    queue_delete = parser.parse_args(["queue", "delete", "thread-1", "queue-1", "--raw"])
    queue_guide = parser.parse_args(["queue", "guide", "thread-1", "turn-1", "queue-1", "guide", "--raw"])
    approval = parser.parse_args(["approval", "respond", "thread-1", "approve", "yes", "--raw"])
    command_execute = parser.parse_args(["command", "execute", "thread-1", "compact", "--raw"])
    attachment_upload = parser.parse_args(["attachment", "upload", "thread-1", str(tmp_path / "note.txt"), "--raw"])

    assert (serve.command, serve.host, serve.port, serve.thinking, serve.raw) == ("serve", "0.0.0.0", 7123, "disabled", True)
    assert (start.command, start.thread_id, start.message, start.thinking, start.shallow, start.approval_policy, start.raw) == (
        "start", "thread-1", ["start work"], "disabled", True, "auto_approve", True,
    )
    assert inherited_start.approval_policy is None
    assert (cancel.command, cancel.turn_id, cancel.raw) == ("cancel", "turn-1", True)
    assert (steer.command, steer.turn_id, steer.message, steer.raw) == ("steer", "turn-1", ["change course"], True)
    assert (queue_create.queue_command, queue_update.queue_command, queue_delete.queue_command, queue_guide.queue_command) == (
        "create", "update", "delete", "guide",
    )
    assert queue_create.raw and queue_update.raw and queue_delete.raw and queue_guide.raw
    assert (approval.command, approval.approval_command, approval.thread_id, approval.action, approval.response, approval.raw) == (
        "approval", "respond", "thread-1", "approve", ["yes"], True,
    )
    assert (command_execute.command, command_execute.command_action, command_execute.name) == (
        "command", "execute", "compact",
    )
    assert (attachment_upload.command, attachment_upload.attachment_action, attachment_upload.thread_id) == (
        "attachment", "upload", "thread-1",
    )


@pytest.mark.asyncio
async def test_core_cli_live_commands_call_core_app_server_operations(monkeypatch, capsys, tmp_path: Path) -> None:
    calls: list[tuple[str, dict]] = []

    class FakeClient:
        def __init__(self, base_url: str, *, path: str, token: str) -> None:
            calls.append(("client", {"base_url": base_url, "path": path, "token": token}))

        async def connect(self) -> None:
            calls.append(("connect", {}))

        async def close(self) -> None:
            calls.append(("close", {}))

        async def start_turn(self, **params):
            calls.append(("turn.start", params))
            return {"events": []}

        async def cancel_turn(self, **params):
            calls.append(("turn.cancel", params))
            return {"events": []}

        async def steer_turn(self, **params):
            calls.append(("turn.steer", params))
            return {"events": []}

        async def create_queue_input(self, **params):
            calls.append(("queue.create", params))
            return {"events": []}

        async def update_queue_input(self, **params):
            calls.append(("queue.update", params))
            return {"events": []}

        async def delete_queue_input(self, **params):
            calls.append(("queue.delete", params))
            return {"events": []}

        async def guide_queue_input(self, **params):
            calls.append(("queue.guide", params))
            return {"applied": True, "reason": ""}

        async def request(self, method: str, params: dict):
            calls.append((method, params))
            return {"thread_id": params["thread_id"]}

    monkeypatch.setattr(core_cli, "CoreAppServerClient", FakeClient)
    parser = build_parser()
    for argv in [
        ["start", "thread-1", "start", "--work-root", str(tmp_path), "--model-id", "model-1", "--thinking", "disabled", "--thinking-budget", "512", "--shallow", "--approval-policy", "auto_approve", "--client-message-id", "message-1", "--raw"],
        ["cancel", "thread-1", "--turn-id", "turn-1", "--raw"],
        ["steer", "thread-1", "turn-1", "steer", "--raw"],
        ["queue", "create", "thread-1", "queued", "--raw"],
        ["queue", "update", "thread-1", "queue-1", "updated", "--raw"],
        ["queue", "delete", "thread-1", "queue-1", "--raw"],
        ["queue", "guide", "thread-1", "turn-1", "queue-1", "guide", "--raw"],
        ["approval", "respond", "thread-1", "approve", "yes", "--raw"],
        ["command", "execute", "thread-1", "help", "--raw"],
    ]:
        args = parser.parse_args(argv)
        assert await args.func(args) == 0

    assert ("turn.start", {
        "thread_id": "thread-1", "input_items": [{"type": "text", "text": "start"}], "work_root": str(tmp_path),
        "model_id": "model-1", "thinking_enabled": False, "thinking_budget": 512,
        "shallow_thinking_enabled": True, "approval_policy": "auto_approve", "client_message_id": "message-1",
    }) in calls
    assert ("turn.cancel", {"thread_id": "thread-1", "turn_id": "turn-1"}) in calls
    assert ("turn.steer", {"thread_id": "thread-1", "turn_id": "turn-1", "input_items": [{"type": "text", "text": "steer"}]}) in calls
    assert ("queue.create", {"thread_id": "thread-1", "input_items": [{"type": "text", "text": "queued"}]}) in calls
    assert ("queue.update", {"thread_id": "thread-1", "queue_item_id": "queue-1", "text": "updated"}) in calls
    assert ("queue.delete", {"thread_id": "thread-1", "queue_item_id": "queue-1"}) in calls
    assert ("queue.guide", {"thread_id": "thread-1", "turn_id": "turn-1", "queue_item_id": "queue-1", "text": "guide"}) in calls
    assert ("approval.respond", {"thread_id": "thread-1", "action": "approve", "response": "yes"}) in calls
    assert '"thread_id": "thread-1"' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_core_cli_serve_builds_core_http_app_and_runs_uvicorn(monkeypatch, capsys, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def create_app(**kwargs):
        seen["app_options"] = kwargs
        return "core-app"

    class Config:
        def __init__(self, app, **kwargs):
            seen["app"] = app
            seen["run_options"] = kwargs

    class Server:
        def __init__(self, config):
            seen["server_config"] = config

        async def serve(self):
            seen["served"] = True

    monkeypatch.setattr("lamtools_core.app.http_agent_app.create_core_agent_http_app", create_app)
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(Config=Config, Server=Server))
    args = build_parser().parse_args([
        "serve", "--host", "127.0.0.2", "--port", "7123", "--model-id", "model-1",
        "--config-db", str(tmp_path / "config.db"), "--core-db", str(tmp_path / "core.db"),
        "--data-dir", str(tmp_path / "data"), "--work-root", str(tmp_path), "--thinking", "disabled",
        "--thinking-budget", "512", "--max-tokens", "1024", "--temperature", "0.4", "--raw",
    ])

    assert await args.func(args) == 0
    assert seen["app"] == "core-app"
    assert seen["run_options"] == {"host": "127.0.0.2", "port": 7123}
    assert seen["served"] is True
    assert seen["app_options"] == {
        "model_id": "model-1", "config_db": str(tmp_path / "config.db"), "core_db": str(tmp_path / "core.db"),
        "data_dir": str(tmp_path / "data"), "work_root": str(tmp_path), "thinking_enabled": False,
        "thinking_budget": 512, "max_tokens": 1024, "temperature": 0.4,
    }
    assert '"url": "http://127.0.0.2:7123"' in capsys.readouterr().out


def test_core_cli_returns_nonzero_for_live_command_errors(monkeypatch, capsys) -> None:
    async def fail(_args):
        raise RuntimeError("live connection failed")

    parser = SimpleNamespace(parse_args=lambda _argv: SimpleNamespace(func=fail))
    monkeypatch.setattr(core_cli, "build_parser", lambda: parser)

    assert core_cli.main(["cancel", "thread-1"]) == 1
    assert "error: live connection failed" in capsys.readouterr().err


def test_core_cli_wrapper_does_not_default_to_member_database() -> None:
    root = Path(__file__).resolve().parents[2]
    wrapper = root / "scripts" / "core.cmd"

    content = wrapper.read_text(encoding="utf-8").lower()

    assert "members\\writer\\data\\lamwriter.db" not in content
    assert "members/writer/data/lamwriter.db" not in content
    assert "if not defined lamtools_core_db" in content
    assert "if not defined lamtools_core_db" in (root / "core.cmd").read_text(encoding="utf-8").lower()


def test_core_cli_wrapper_does_not_repeat_failed_tasks_with_another_python() -> None:
    root = Path(__file__).resolve().parents[2]
    content = (root / "scripts" / "core.cmd").read_text(encoding="utf-8").lower()

    assert content.count("-m lamtools_core.cli %*") == 1
    assert "if %errorlevel% equ 0 exit /b 0" not in content


def test_load_llm_config_can_read_shared_config_when_sqlite_is_locked(tmp_path: Path) -> None:
    db_path = tmp_path / "config.db"
    _write_config_db(db_path)
    lock = sqlite3.connect(db_path)
    try:
        lock.execute("begin exclusive")

        config = load_llm_config(db_path, model_ref="model-record")

        assert config.model_record_id == "model-record"
        assert config.model_id == "model-name"
        assert config.thinking_supported is True
    finally:
        lock.rollback()
        lock.close()


def test_load_llm_config_reads_core_model_routing_from_shared_config(tmp_path: Path) -> None:
    db_path = tmp_path / "config.db"
    _write_config_db(db_path)
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            create table app_settings (
                namespace text primary key,
                value text,
                updated_at text
            )
            """
        )
        con.execute(
            """
            insert into app_settings (namespace,value,updated_at)
            values ('lamtools.modelRouting', '{"routes":{"core":{"mode":"model","model_id":"model-record"}}}', '2026-01-01')
            """
        )
        con.commit()

    config = load_llm_config(db_path)

    assert config.model_record_id == "model-record"
    assert config.model_id == "model-name"


def test_load_llm_config_ignores_member_model_routing_from_shared_config(tmp_path: Path) -> None:
    db_path = tmp_path / "config.db"
    _write_config_db(db_path)
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            insert into llm_models (
                id,provider_id,model_id,display_name,context_window,max_output_tokens,
                thinking_supported,thinking_budget,temperature,extra,created_at
            )
            values (
                'legacy-route-record','provider-1','legacy-route-model','Legacy Route Model',128000,4096,
                1,10000,0.2,'{}','2026-01-02'
            )
            """
        )
        con.execute(
            """
            create table app_settings (
                namespace text primary key,
                value text,
                updated_at text
            )
            """
        )
        con.execute(
            """
            insert into app_settings (namespace,value,updated_at)
            values ('lamwriter.modelRouting', '{"routes":{"writer":{"mode":"model","model_id":"legacy-route-record"}}}', '2026-01-01')
            """
        )
        con.commit()

    config = load_llm_config(db_path)

    assert config.model_record_id == "model-record"
    assert config.model_id == "model-name"


def test_load_llm_config_uses_first_shared_model_when_core_routing_is_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "config.db"
    _write_config_db(db_path)

    config = load_llm_config(db_path)

    assert config.model_record_id == "model-record"
    assert config.model_id == "model-name"


@pytest.mark.asyncio
async def test_core_cli_run_prints_session_before_starting_non_raw_task(monkeypatch, capsys, tmp_path: Path) -> None:
    observed: dict[str, str] = {}

    async def fake_run(options: CoreCliRunOptions):
        observed["thread_id"] = options.thread_id
        observed["pre_run_output"] = capsys.readouterr().out
        return {
            "ok": True,
            "model": {"display_name": "Fake Model"},
            "result": {
                "session_id": options.thread_id,
                "decision": "done",
                "steps_count": 2,
            },
            "proof": {
                "has_reasoning_block": True,
                "has_text_block": True,
                "tool_names": ["write_file"],
                "response_indexes": [0, 1],
                "document_path": "",
                "document_line_count": 0,
            },
            "artifacts": {"summary_json": str(tmp_path / "summary.json")},
        }

    monkeypatch.setattr(core_cli, "run_core_cli_task", fake_run)

    result = await core_cli.cmd_run(
        SimpleNamespace(
            message=["write", "doc"],
            model_id="fake-model",
            config_db="",
            core_db="",
            thread_id="",
            work_root=str(tmp_path),
            run_dir="",
            adapter_dir=[],
            plugin_root=[],
            no_thinking=False,
            shallow_thinking=False,
            thinking_budget=10000,
            max_tokens=4096,
            temperature=0.2,
            auto_approve=True,
            raw=False,
            verbose=False,
        )
    )

    assert result == 0
    assert observed["thread_id"].startswith("core-cli-")
    assert observed["pre_run_output"] == f"[session] {observed['thread_id']}\n"
    output = capsys.readouterr().out
    assert "[done] decision=done steps=2" in output


@pytest.mark.asyncio
async def test_core_cli_run_uses_core_kernel_tool_loop(tmp_path: Path) -> None:
    llm = ScriptedCoreCliLLM()
    core_db = tmp_path / "core.db"

    summary = await run_core_cli_task(
        CoreCliRunOptions(
            message="写一个文档，超过 10 行，随便写。",
            model_id="fake-model",
            work_root=tmp_path / "workspace",
            run_dir=tmp_path / "run",
            core_db=core_db,
            thread_id="thread-cli-tool-loop",
            thinking_enabled=True,
            approval_policy="auto_approve",
        ),
        llm_client=llm,
    )

    assert summary["ok"] is True
    assert summary["artifacts"]["core_db"] == str(core_db)
    assert summary["result"]["session_id"] == "thread-cli-tool-loop"
    assert summary["result"]["decision"] == "done"
    assert summary["result"]["steps_count"] == 2
    assert summary["proof"]["has_reasoning_block"] is True
    assert summary["proof"]["has_text_block"] is True
    assert summary["proof"]["has_tool_call_block"] is True
    assert summary["proof"]["tool_names"] == ["write_file"]
    assert summary["proof"]["response_indexes"] == [0, 1]
    assert summary["proof"]["document_line_count"] == 11
    assert Path(summary["proof"]["document_path"]).read_text(encoding="utf-8").count("\n") >= 10
    assert len(llm.requests) == 2
    assert {tool["function"]["name"] for tool in llm.requests[0].tools or []} >= {"read_file", "write_file"}
    assert "write_document" not in {tool["function"]["name"] for tool in llm.requests[0].tools or []}
    assert {tool["function"]["name"] for tool in llm.requests[1].tools or []} >= {"read_file", "write_file"}

    with sqlite3.connect(core_db) as con:
        tables = {row[0] for row in con.execute("select name from sqlite_master where type='table'")}
        assert {"core_app_events", "core_thread_snapshots", "core_runtime_sessions"} <= tables
        assert "writer_app_events" not in tables
        assert "writer_thread_snapshots" not in tables
        events = con.execute(
            "select method,payload_json from core_app_events where thread_id=? order by seq",
            ("thread-cli-tool-loop",),
        ).fetchall()
        snapshot_row = con.execute(
            "select snapshot_seq,snapshot_json from core_thread_snapshots where thread_id=?",
            ("thread-cli-tool-loop",),
        ).fetchone()
        project_row = con.execute(
            "select id,name,work_root from core_projects",
        ).fetchone()
        snapshot_count = con.execute("select count(*) from core_thread_snapshots").fetchone()[0]

    assert events
    assert {row[0] for row in events} == {"core/runItem"}
    assert any("write_file" in str(row[1]) for row in events)
    user_events = [json.loads(row[1]) for row in events if '"userMessage"' in str(row[1])]
    assert len(user_events) == 1
    assert user_events[0]["payload"]["content"] == [
        {"type": "text", "text": "写一个文档，超过 10 行，随便写。"}
    ]
    assert snapshot_row is not None
    assert snapshot_count == 1
    assert int(snapshot_row[0]) == len(events)
    assert '"status": "completed"' in str(snapshot_row[1])
    snapshot = json.loads(snapshot_row[1])
    assert snapshot["session"]["title"] == "写一个文档，超过 10 行，随便写。"
    assert snapshot["session"]["metadata"]["work_root"] == str((tmp_path / "workspace").resolve())
    assert snapshot["session"]["metadata"]["project_id"] == project_row[0]
    assert project_row[1] == "workspace"
    assert project_row[2] == str((tmp_path / "workspace").resolve())


@pytest.mark.asyncio
async def test_core_cli_persists_user_message_before_model_execution(tmp_path: Path) -> None:
    core_db = tmp_path / "core.db"

    summary = await run_core_cli_task(
        CoreCliRunOptions(
            message="must remain visible after interruption",
            model_id="fake-model",
            work_root=tmp_path / "workspace",
            run_dir=tmp_path / "run",
            core_db=core_db,
            thread_id="thread-cli-interrupted",
            approval_policy="auto_approve",
        ),
        llm_client=FailingCoreCliLLM(),
    )

    assert summary["result"]["decision"] == "failed"

    with sqlite3.connect(core_db) as con:
        payloads = [
            json.loads(row[0])
            for row in con.execute(
                "select payload_json from core_app_events where thread_id=? order by seq",
                ("thread-cli-interrupted",),
            )
        ]

    user_payloads = [payload for payload in payloads if payload["payload"].get("type") == "userMessage"]
    assert [payload["payload"]["content"] for payload in user_payloads] == [
        [{"type": "text", "text": "must remain visible after interruption"}]
    ]


@pytest.mark.asyncio
async def test_core_cli_sub_agent_uses_durable_child_session_and_parent_timeline(tmp_path: Path) -> None:
    core_db = tmp_path / "core.db"
    thread_id = "thread-cli-sub-agent"

    summary = await run_core_cli_task(
        CoreCliRunOptions(
            message="delegate",
            model_id="fake-model",
            work_root=tmp_path / "workspace",
            run_dir=tmp_path / "run",
            core_db=core_db,
            thread_id=thread_id,
            approval_policy="auto_approve",
        ),
        llm_client=ScriptedCoreCliSubAgentLLM(),
    )

    with sqlite3.connect(core_db) as con:
        child = con.execute(
            "select runtime_state_json,history_json from core_runtime_sessions where thread_id=?",
            (f"{thread_id}:sub:writer",),
        ).fetchone()
        write_events = con.execute(
            "select payload_json from core_app_events where thread_id=? and payload_json like '%write_file%'",
            (thread_id,),
        ).fetchall()

    assert summary["result"]["decision"] == "done"
    assert (tmp_path / "workspace" / "delegated.txt").read_text(encoding="utf-8") == "delegated content"
    assert child is not None
    assert json.loads(child[0])["status"] == "completed"
    assert not json.loads(child[1])[-1].get("tool_calls")
    assert write_events


@pytest.mark.asyncio
async def test_core_cli_reuses_persisted_history_across_independent_runs(tmp_path: Path) -> None:
    core_db = tmp_path / "core.db"
    thread_id = "thread-cli-history"
    first_llm = CapturingCoreCliLLM()
    second_llm = CapturingCoreCliLLM()

    await run_core_cli_task(
        CoreCliRunOptions(
            message="Remember alpha.",
            model_id="fake-model",
            work_root=tmp_path / "workspace",
            run_dir=tmp_path / "run-1",
            core_db=core_db,
            thread_id=thread_id,
        ),
        llm_client=first_llm,
    )
    await run_core_cli_task(
        CoreCliRunOptions(
            message="What should you remember?",
            model_id="fake-model",
            work_root=tmp_path / "workspace",
            run_dir=tmp_path / "run-2",
            core_db=core_db,
            thread_id=thread_id,
        ),
        llm_client=second_llm,
    )

    messages = [message for message in second_llm.requests[0].messages if message.role != "system"]
    assert [(message.role, message.content) for message in messages] == [
        ("user", "Remember alpha."),
        ("assistant", "Core shallow run completed."),
        ("user", "What should you remember?"),
    ]


@pytest.mark.asyncio
async def test_core_cli_run_success_is_not_tied_to_document_proof(tmp_path: Path) -> None:
    summary = await run_core_cli_task(
        CoreCliRunOptions(
            message="用一句话说明 Core 是否可用。",
            model_id="fake-model",
            work_root=tmp_path / "workspace",
            run_dir=tmp_path / "run",
            core_db=tmp_path / "core.db",
            thread_id="thread-cli-answer-only",
            thinking_enabled=True,
        ),
        llm_client=ScriptedCoreCliAnswerOnlyLLM(),
    )

    assert summary["ok"] is True
    assert summary["result"]["decision"] == "done"
    assert summary["proof"]["has_reasoning_block"] is True
    assert summary["proof"]["has_text_block"] is True
    assert summary["proof"]["has_tool_call_block"] is False
    assert summary["proof"]["document_line_count"] == 0


@pytest.mark.asyncio
async def test_core_cli_run_can_enable_shallow_thinking_prompt(tmp_path: Path) -> None:
    llm = CapturingCoreCliLLM()

    summary = await run_core_cli_task(
        CoreCliRunOptions(
            message="answer",
            model_id="fake-model",
            work_root=tmp_path / "workspace",
            run_dir=tmp_path / "run",
            core_db=tmp_path / "core.db",
            thread_id="thread-cli-shallow",
            shallow_thinking_enabled=True,
        ),
        llm_client=llm,
    )

    assert summary["ok"] is True
    assert any(message.content == SHALLOW_THINKING_PROMPT for message in llm.requests[0].messages)


@pytest.mark.asyncio
async def test_core_cli_session_queries_read_core_db(tmp_path: Path) -> None:
    llm = ScriptedCoreCliLLM()
    core_db = tmp_path / "core.db"

    await run_core_cli_task(
        CoreCliRunOptions(
            message="写一个文档，超过 10 行，随便写。",
            model_id="fake-model",
            work_root=tmp_path / "workspace",
            run_dir=tmp_path / "run",
            core_db=core_db,
            thread_id="thread-cli-query",
            thinking_enabled=True,
            approval_policy="auto_approve",
        ),
        llm_client=llm,
    )

    sessions = await core_cli.list_core_cli_sessions(core_db=core_db)
    detail = await core_cli.show_core_cli_session("thread-cli-query", core_db=core_db)

    assert sessions[0]["thread_id"] == "thread-cli-query"
    assert sessions[0]["status"] == "completed"
    assert sessions[0]["snapshot_seq"] > 0
    assert detail["thread_id"] == "thread-cli-query"
    assert detail["snapshot"]["status"] == "completed"
    assert any(event["method"] == "core/runItem" for event in detail["events"])
    assert any("write_file" in str(event["payload"]) for event in detail["events"])


@pytest.mark.asyncio
async def test_core_cli_run_loads_plugin_skill_roots(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    sample = plugin_root / "sample"
    skill_dir = sample / "skills"
    skill_dir.mkdir(parents=True)
    (sample / "plugin.json").write_text(
        '{"name":"sample","version":"1.0.0","skills":["./skills"]}',
        encoding="utf-8",
    )
    (skill_dir / "shared.md").write_text("plugin skill resource\n", encoding="utf-8")
    llm = ScriptedCoreCliReadLLM(path="shared.md")

    summary = await run_core_cli_task(
        CoreCliRunOptions(
            message="read plugin skill",
            model_id="fake-model",
            work_root=tmp_path / "workspace",
            run_dir=tmp_path / "run",
            plugin_roots=(plugin_root,),
        ),
        llm_client=llm,
    )

    events = Path(summary["artifacts"]["events_redacted_json"]).read_text(encoding="utf-8")
    assert summary["result"]["decision"] == "done"
    assert "plugin skill resource" in events
