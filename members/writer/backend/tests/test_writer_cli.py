from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from writer_cli.app_server_client import AppServerClient
from lamtools_core.app.live_client import CoreAppServerClient
from lamtools_core.app.cli_live import OutputChunk
from writer_cli.__main__ import (
    CLI_DISPLAY_TAGS,
    TAG_TO_DISPLAY_GROUP,
    CliRunFormatter,
    _create_visible_session,
    _format_event,
    _event_request_id,
    _is_done_event,
    _stream_chat,
    _is_waiting_event,
    build_parser,
    cmd_delete,
    cmd_compact,
    cmd_run,
    cmd_watch,
    cmd_open_change_file,
    cmd_list,
    cmd_messages,
    cmd_pick_directory,
    cmd_rename,
    cmd_result,
    cmd_show,
    cmd_status,
)


def test_display_tags_map_to_ui_destinations():
    assert TAG_TO_DISPLAY_GROUP["reply"] == "writer_reply"
    assert TAG_TO_DISPLAY_GROUP["decision"] == "decision_card"
    assert TAG_TO_DISPLAY_GROUP["agent"] == "sub_line"
    assert TAG_TO_DISPLAY_GROUP["file"] == "processed_flow"
    assert TAG_TO_DISPLAY_GROUP["git"] == "git_panel"
    assert TAG_TO_DISPLAY_GROUP["failed"] == "error_card"
    assert TAG_TO_DISPLAY_GROUP["done"] == "status_bar"
    assert TAG_TO_DISPLAY_GROUP["debug"] == "debug_log"
    assert set(TAG_TO_DISPLAY_GROUP) == CLI_DISPLAY_TAGS


def test_parser_accepts_forced_interactive_decisions():
    parser = build_parser()
    args = parser.parse_args(["resume", "sess-1", "hello", "--interactive-decisions"])

    assert args.interactive_decisions is True
    assert args.no_interactive_decisions is False


def test_writer_cli_app_server_client_reuses_core_live_client():
    assert issubclass(AppServerClient, CoreAppServerClient)


def test_parser_accepts_run_command_with_project_alias():
    parser = build_parser()
    args = parser.parse_args(["run", "do", "work", "--project", "E:\\LamTools\\members\\writer"])

    assert args.command == "run"
    assert args.message == ["do", "work"]
    assert args.work_root == "E:\\LamTools\\members\\writer"


def test_parser_accepts_project_create_with_work_root():
    parser = build_parser()
    args = parser.parse_args(["project", "create", "--work-root", "E:\\Work\\DemoProject"])

    assert args.command == "project"
    assert args.project_command == "create"
    assert args.work_root == "E:\\Work\\DemoProject"


def test_parser_accepts_project_pick_directory():
    parser = build_parser()
    args = parser.parse_args(["project", "pick-directory"])

    assert args.command == "project"
    assert args.project_command == "pick-directory"


def test_parser_accepts_project_list():
    parser = build_parser()
    args = parser.parse_args(["project", "list"])

    assert args.command == "project"
    assert args.project_command == "list"


def test_parser_accepts_plugin_and_hook_commands():
    parser = build_parser()

    plugin = parser.parse_args(["plugin", "enable", "repo-policy"])
    hook = parser.parse_args(["hook", "trust", "hook-1"])

    assert plugin.command == "plugin"
    assert plugin.plugin_command == "enable"
    assert plugin.name == "repo-policy"
    assert hook.command == "hook"
    assert hook.hook_command == "trust"
    assert hook.hook_id == "hook-1"


def test_parser_accepts_shallow_thinking_for_run_and_resume():
    parser = build_parser()

    run = parser.parse_args(["run", "do", "work", "--shallow-thinking"])
    resume = parser.parse_args(["resume", "sess-1", "继续", "--shallow-thinking"])

    assert run.shallow_thinking is True
    assert resume.shallow_thinking is True


@pytest.mark.parametrize("command", ["chat", "quick", "agent", "tool"])
def test_parser_rejects_removed_side_channel_commands(command):
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([command, "anything"])


def test_parser_accepts_resume_command():
    parser = build_parser()
    args = parser.parse_args(["resume", "sess-1", "继续修复", "--heartbeat-interval", "10"])

    assert args.command == "resume"
    assert args.session_id == "sess-1"
    assert args.message == ["继续修复"]
    assert args.heartbeat_interval == 10


def test_parser_accepts_sub_agent_list_show_and_send_commands():
    parser = build_parser()

    listed = parser.parse_args(["sub-agent", "list", "session-1"])
    shown = parser.parse_args(["sub-agent", "show", "session-1", "child-1"])
    sent = parser.parse_args([
        "sub-agent", "send", "session-1", "child-1", "继续检查", "--model-id", "model-2",
        "--thinking", "--thinking-budget", "2048", "--shallow-thinking",
    ])

    assert listed.sub_agent_command == "list"
    assert shown.sub_session_id == "child-1"
    assert sent.message == ["继续检查"]
    assert sent.model_id == "model-2"
    assert sent.thinking is True
    assert sent.thinking_budget == 2048
    assert sent.shallow_thinking is True


def test_parser_accepts_watch_command():
    parser = build_parser()
    args = parser.parse_args(["watch", "sess-1", "--verbose"])

    assert args.command == "watch"
    assert args.session_id == "sess-1"
    assert args.verbose is True


def test_parser_accepts_raw_machine_approval_decision():
    args = build_parser().parse_args(["watch", "sess-1", "--raw", "--approval-decision", "approve_once"])

    assert args.raw is True
    assert args.approval_decision == "approve_once"


@pytest.mark.asyncio
async def test_raw_run_does_not_print_a_session_label(monkeypatch, capsys):
    async def create_session(*_args, **_kwargs):
        return {"id": "session-1"}

    async def stream(*_args, **_kwargs):
        return 0

    monkeypatch.setattr("writer_cli.__main__._create_visible_session", create_session)
    monkeypatch.setattr("writer_cli.__main__._stream_chat", stream)

    result = await cmd_run(SimpleNamespace(raw=True, message=["hello"], title="", work_root="", mode="EXECUTE"))

    assert result == 0
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_raw_watch_stdout_is_jsonl_without_a_watch_label(monkeypatch, capsys):
    async def watch(**kwargs):
        kwargs["output"](OutputChunk('{"event":"app_server_event"}'))
        return SimpleNamespace(exit_code=0)

    monkeypatch.setattr("writer_cli.__main__.watch_live_events", watch)
    args = SimpleNamespace(
        raw=True,
        session_id="session-1",
        verbose=False,
        heartbeat_interval=30,
        approval_decision=None,
        interactive_decisions=False,
        base_url="http://writer.test",
    )

    assert await cmd_watch(args) == 0
    assert [json.loads(line) for line in capsys.readouterr().out.splitlines() if line] == [{"event": "app_server_event"}]


@pytest.mark.asyncio
async def test_stream_chat_reuses_one_client_message_id_when_connect_callback_retries(monkeypatch):
    client_message_ids: list[str | None] = []

    class FakeClient:
        async def start_turn(self, **kwargs):
            client_message_ids.append(kwargs.get("client_message_id"))

    async def retry_connect_callback(**kwargs):
        client = FakeClient()
        await kwargs["on_connected"](client)
        await kwargs["on_connected"](client)
        return SimpleNamespace(exit_code=0)

    monkeypatch.setattr("writer_cli.__main__.watch_live_events", retry_connect_callback)
    args = SimpleNamespace(
        raw=False,
        interactive_decisions=False,
        no_interactive_decisions=True,
        verbose=False,
        heartbeat_interval=30,
        work_root="",
        mode="EXECUTE",
        model_id=None,
        shallow_thinking=False,
        approval_decision=None,
        base_url="http://writer.test",
    )

    assert await _stream_chat(args, "session-1", "hello") == 0
    assert len(client_message_ids) == 2
    assert client_message_ids[0] == client_message_ids[1]
    assert client_message_ids[0]


def test_parser_accepts_status_command():
    parser = build_parser()
    args = parser.parse_args(["status", "sess-1"])

    assert args.command == "status"
    assert args.session_id == "sess-1"


def test_parser_accepts_compact_command():
    parser = build_parser()
    args = parser.parse_args(["compact", "sess-1", "--verbose"])

    assert args.command == "compact"
    assert args.session_id == "sess-1"
    assert args.verbose is True


def test_parser_accepts_open_change_file_command():
    parser = build_parser()
    args = parser.parse_args(["open-change-file", "sess-1", "src/main.py"])

    assert args.command == "open-change-file"
    assert args.session_id == "sess-1"
    assert args.path == "src/main.py"


def test_parser_accepts_session_metadata_commands():
    parser = build_parser()

    show = parser.parse_args(["show", "sess-1"])
    rename = parser.parse_args(["rename", "sess-1", "New", "Title"])
    delete = parser.parse_args(["delete", "sess-1"])

    assert show.command == "show"
    assert show.session_id == "sess-1"
    assert rename.command == "rename"
    assert rename.session_id == "sess-1"
    assert rename.title == ["New", "Title"]
    assert delete.command == "delete"
    assert delete.session_id == "sess-1"


@pytest.mark.asyncio
async def test_cli_session_creation_uses_app_server_operation(monkeypatch):
    calls = []

    class FakeAppServerClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        async def __aenter__(self):
            calls.append(("enter",))
            return self

        async def __aexit__(self, *args):
            calls.append(("exit",))

        async def connect(self):
            calls.append(("connect",))

        async def create_session(self, *, title, work_root, mode):
            calls.append(("session.create", title, work_root, mode))
            return {"id": "session-1", "title": title, "work_root": work_root, "mode": mode}

    async def fail_http(*args, **kwargs):
        raise AssertionError("CLI session creation should use app-server operation")

    monkeypatch.setattr("writer_cli.__main__.AppServerClient", FakeAppServerClient)
    monkeypatch.setattr("writer_cli.__main__._request_json", fail_http)
    args = SimpleNamespace(base_url="http://writer.test")

    created = await _create_visible_session(
        args,
        title="Visible",
        work_root="E:\\work\\visible",
        mode="EXECUTE",
    )

    assert created["id"] == "session-1"
    assert calls == [
        ("init", "http://writer.test"),
        ("enter",),
        ("connect",),
        ("session.create", "Visible", "E:\\work\\visible", "EXECUTE"),
        ("exit",),
    ]


@pytest.mark.asyncio
async def test_cli_session_creation_without_work_root_still_uses_operation(monkeypatch):
    calls = []

    class FakeAppServerClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            calls.append(("exit",))

        async def connect(self):
            calls.append(("connect",))

        async def create_session(self, *, title, work_root, mode):
            calls.append(("session.create", title, work_root, mode))
            return {"id": "session-1", "title": title, "work_root": work_root, "mode": mode}

    monkeypatch.setattr("writer_cli.__main__.AppServerClient", FakeAppServerClient)
    args = SimpleNamespace(base_url="http://writer.test")

    created = await _create_visible_session(
        args,
        title="Plain",
        work_root="",
        mode="EXECUTE",
    )

    assert created["id"] == "session-1"
    assert calls == [
        ("init", "http://writer.test"),
        ("connect",),
        ("session.create", "Plain", "", "EXECUTE"),
        ("exit",),
    ]


@pytest.mark.asyncio
async def test_cli_list_uses_app_server_session_operation(monkeypatch, capsys):
    calls = []

    class FakeAppServerClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        async def __aenter__(self):
            calls.append(("enter",))
            return self

        async def __aexit__(self, *args):
            calls.append(("exit",))

        async def connect(self):
            calls.append(("connect",))

        async def list_sessions(self, *, limit):
            calls.append(("session.list", limit))
            return [
                {
                    "id": "session-1",
                    "status": "active",
                    "mode": "EXECUTE",
                    "title": "Visible",
                }
            ]

    async def fail_http(*args, **kwargs):
        raise AssertionError("CLI list should use app-server operation")

    monkeypatch.setattr("writer_cli.__main__.AppServerClient", FakeAppServerClient)
    monkeypatch.setattr("writer_cli.__main__._request_json", fail_http)

    result = await cmd_list(SimpleNamespace(base_url="http://writer.test", limit=5))

    assert result == 0
    assert calls == [
        ("init", "http://writer.test"),
        ("enter",),
        ("connect",),
        ("session.list", 5),
        ("exit",),
    ]
    assert "session-1  active" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cli_messages_reads_thread_operation(monkeypatch, capsys):
    calls = []

    class FakeAppServerClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            calls.append(("exit",))

        async def connect(self, *, thread_id=None, last_seen_seq=0):
            calls.append(("connect", thread_id, last_seen_seq))

        async def close(self):
            calls.append(("close",))

        async def events(self):
            await asyncio.Event().wait()
            yield {}

        async def read_thread(self, *, thread_id):
            calls.append(("thread.read", thread_id))
            return {
                "snapshot": {
                    "core": {
                        "item_order": ["user-1", "assistant-1", "user-2"],
                        "items": {
                            "user-1": {"item_id": "user-1", "type": "userMessage", "content": [{"text": "first"}]},
                            "assistant-1": {
                                "item_id": "assistant-1",
                                "type": "agentMessage",
                                "turn_id": "turn-1",
                                "content": "answer",
                            },
                            "user-2": {"item_id": "user-2", "type": "userMessage", "content": [{"text": "latest"}]},
                        },
                    }
                },
            }

    async def fail_http(*args, **kwargs):
        raise AssertionError("CLI messages should use app-server thread.read")

    monkeypatch.setattr("writer_cli.__main__.AppServerClient", FakeAppServerClient)
    monkeypatch.setattr("writer_cli.__main__._request_json", fail_http)

    result = await cmd_messages(SimpleNamespace(base_url="http://writer.test", session_id="session-1", limit=2))

    assert result == 0
    assert calls == [
        ("init", "http://writer.test"),
        ("connect", "session-1", 0),
        ("thread.read", "session-1"),
        ("exit",),
    ]
    output = capsys.readouterr().out
    assert "assistant: answer" in output
    assert "user: latest" in output
    assert "user: first" not in output


@pytest.mark.asyncio
async def test_cli_show_uses_app_server_session_get(monkeypatch, capsys):
    calls = []

    class FakeAppServerClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            calls.append(("exit",))

        async def connect(self, *, thread_id=None, last_seen_seq=0):
            calls.append(("connect", thread_id, last_seen_seq))

        async def get_session(self, *, session_id):
            calls.append(("session.get", session_id))
            return {"id": session_id, "title": "Visible"}

    monkeypatch.setattr("writer_cli.__main__.AppServerClient", FakeAppServerClient)

    result = await cmd_show(SimpleNamespace(base_url="http://writer.test", session_id="session-1"))

    assert result == 0
    assert calls == [
        ("init", "http://writer.test"),
        ("connect", "session-1", 0),
        ("session.get", "session-1"),
        ("exit",),
    ]
    assert '"title": "Visible"' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cli_rename_uses_app_server_session_update(monkeypatch, capsys):
    calls = []

    class FakeAppServerClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            calls.append(("exit",))

        async def connect(self, *, thread_id=None, last_seen_seq=0):
            calls.append(("connect", thread_id, last_seen_seq))

        async def update_session(self, *, session_id, title):
            calls.append(("session.update", session_id, title))
            return {"id": session_id, "title": title}

    monkeypatch.setattr("writer_cli.__main__.AppServerClient", FakeAppServerClient)

    result = await cmd_rename(SimpleNamespace(base_url="http://writer.test", session_id="session-1", title=["New", "Title"]))

    assert result == 0
    assert calls == [
        ("init", "http://writer.test"),
        ("connect", "session-1", 0),
        ("session.update", "session-1", "New Title"),
        ("exit",),
    ]
    assert "[session_rename] title: New Title" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cli_delete_uses_app_server_session_delete(monkeypatch, capsys):
    calls = []

    class FakeAppServerClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            calls.append(("exit",))

        async def connect(self, *, thread_id=None, last_seen_seq=0):
            calls.append(("connect", thread_id, last_seen_seq))

        async def delete_session(self, *, session_id):
            calls.append(("session.delete", session_id))

    monkeypatch.setattr("writer_cli.__main__.AppServerClient", FakeAppServerClient)

    result = await cmd_delete(SimpleNamespace(base_url="http://writer.test", session_id="session-1"))

    assert result == 0
    assert calls == [
        ("init", "http://writer.test"),
        ("connect", "session-1", 0),
        ("session.delete", "session-1"),
        ("exit",),
    ]
    assert "[session_delete] session_id: session-1" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cli_compact_executes_app_server_command(monkeypatch, capsys):
    calls = []

    class FakeAppServerClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            calls.append(("exit",))

        async def connect(self, *, thread_id=None, last_seen_seq=0):
            calls.append(("connect", thread_id, last_seen_seq))

        async def close(self):
            calls.append(("close",))

        async def events(self):
            await asyncio.Event().wait()
            yield {}

        async def execute_command(self, *, thread_id, command, work_root=""):
            calls.append(("command.execute", thread_id, command, work_root))
            return {
                "status": "compacted",
                "compacted_messages": 8,
                "retained_messages": 6,
                "before_tokens": 18000,
                "after_tokens": 7200,
                "summary": "[Compacted Context]\n1. Current Goal\n- Continue.",
            }

    monkeypatch.setattr("writer_cli.__main__.AppServerClient", FakeAppServerClient)

    result = await cmd_compact(
        SimpleNamespace(
            base_url="http://writer.test",
            session_id="session-1",
            work_root="E:\\LamTools",
            verbose=False,
        )
    )

    assert result == 0
    assert calls == [
        ("init", "http://writer.test"),
        ("connect", None, 0),
        ("command.execute", "session-1", "compact", "E:\\LamTools"),
        ("close",),
    ]
    output = capsys.readouterr().out
    assert "上下文已压缩 · 18000 → 7200 tokens" in output
    assert "[Compacted Context]" not in output


@pytest.mark.asyncio
async def test_cli_compact_verbose_prints_summary(monkeypatch, capsys):
    class FakeAppServerClient:
        def __init__(self, base_url):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def connect(self, *, thread_id=None, last_seen_seq=0):
            pass

        async def read_thread(self, *, thread_id):
            return {"snapshot": {"snapshot_seq": 0}}

        async def close(self):
            pass

        async def events(self):
            await asyncio.Event().wait()
            yield {}

        async def execute_command(self, *, thread_id, command, work_root=""):
            return {
                "status": "compacted",
                "compacted_messages": 1,
                "summary": "[Compacted Context]\n1. Current Goal\n- Continue.",
            }

    monkeypatch.setattr("writer_cli.__main__.AppServerClient", FakeAppServerClient)

    result = await cmd_compact(
        SimpleNamespace(base_url="http://writer.test", session_id="session-1", work_root="", verbose=True)
    )

    assert result == 0
    assert "[Compacted Context]" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cli_open_change_file_uses_app_server_operation(monkeypatch, capsys):
    calls = []

    class FakeAppServerClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            calls.append(("exit",))

        async def connect(self, *, thread_id=None, last_seen_seq=0):
            calls.append(("connect", thread_id, last_seen_seq))

        async def request(self, method, params=None):
            calls.append((method, params))
            return {"status": "opened", "path": "src/main.py", "opened_with": "default"}

    async def fail_http(*args, **kwargs):
        raise AssertionError("CLI open-change-file should use app-server operation")

    monkeypatch.setattr("writer_cli.__main__.AppServerClient", FakeAppServerClient)
    monkeypatch.setattr("writer_cli.__main__._request_json", fail_http)

    result = await cmd_open_change_file(
        SimpleNamespace(base_url="http://writer.test", session_id="session-1", path="src/main.py")
    )

    assert result == 0
    assert calls == [
        ("init", "http://writer.test"),
        ("connect", "session-1", 0),
        ("session.change_file.open", {"session_id": "session-1", "path": "src/main.py"}),
        ("exit",),
    ]
    assert "[open_change_file] src/main.py via default" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cli_status_reads_thread_operation(monkeypatch, capsys):
    calls = []

    class FakeAppServerClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            calls.append(("exit",))

        async def connect(self, *, thread_id=None, last_seen_seq=0):
            calls.append(("connect", thread_id, last_seen_seq))

        async def read_thread(self, *, thread_id):
            calls.append(("thread.read", thread_id))
            return {
                "session": {
                    "id": thread_id,
                    "status": "completed",
                    "phase": "done",
                    "mode": "EXECUTE",
                    "work_root": "E:\\work",
                },
                "snapshot": {
                    "core": {
                        "item_order": ["user-1", "assistant-1"],
                        "items": {
                            "user-1": {"item_id": "user-1", "type": "userMessage", "content": [{"text": "hello"}]},
                            "assistant-1": {
                                "item_id": "assistant-1",
                                "type": "agentMessage",
                                "turn_id": "turn-1",
                                "content": "done",
                            },
                        },
                    }
                },
            }

    async def fail_http(*args, **kwargs):
        raise AssertionError("CLI status should use app-server thread.read")

    monkeypatch.setattr("writer_cli.__main__.AppServerClient", FakeAppServerClient)
    monkeypatch.setattr("writer_cli.__main__._request_json", fail_http)
    monkeypatch.setattr("writer_cli.__main__._load_local_state_summary", lambda _session_id: {})

    result = await cmd_status(SimpleNamespace(base_url="http://writer.test", session_id="session-1"))

    assert result == 0
    assert calls == [
        ("init", "http://writer.test"),
        ("connect", "session-1", 0),
        ("thread.read", "session-1"),
        ("exit",),
    ]
    output = capsys.readouterr().out
    assert "session session-1" in output
    assert "status  completed  phase=done  mode=EXECUTE" in output
    assert "  assistant: done" in output


@pytest.mark.asyncio
async def test_cli_result_reads_thread_operation(monkeypatch, capsys):
    calls = []

    class FakeAppServerClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            calls.append(("exit",))

        async def connect(self, *, thread_id=None, last_seen_seq=0):
            calls.append(("connect", thread_id, last_seen_seq))

        async def read_thread(self, *, thread_id):
            calls.append(("thread.read", thread_id))
            return {
                "session": {
                    "id": thread_id,
                    "status": "completed",
                    "phase": "done",
                    "work_root": "",
                },
                "snapshot": {
                    "core": {
                        "item_order": ["assistant-1", "assistant-2"],
                        "items": {
                            "assistant-1": {
                                "item_id": "assistant-1",
                                "kind": "message",
                                "turn_id": "turn-1",
                                "payload": {"type": "agentMessage"},
                                "content": "first",
                            },
                            "assistant-2": {
                                "item_id": "assistant-2",
                                "kind": "message",
                                "turn_id": "turn-2",
                                "payload": {"type": "agentMessage"},
                                "content": "final summary",
                            },
                        },
                    }
                },
            }

    async def fail_http(*args, **kwargs):
        raise AssertionError("CLI result should use app-server thread.read")

    monkeypatch.setattr("writer_cli.__main__.AppServerClient", FakeAppServerClient)
    monkeypatch.setattr("writer_cli.__main__._request_json", fail_http)
    monkeypatch.setattr("writer_cli.__main__._load_local_state_summary", lambda _session_id: {})

    result = await cmd_result(SimpleNamespace(base_url="http://writer.test", session_id="session-1"))

    assert result == 0
    assert calls == [
        ("init", "http://writer.test"),
        ("connect", "session-1", 0),
        ("thread.read", "session-1"),
        ("exit",),
    ]
    output = capsys.readouterr().out
    assert "session session-1" in output
    assert "summary" in output
    assert "final summary" in output


def test_parser_accepts_result_command():
    parser = build_parser()
    args = parser.parse_args(["result", "sess-1"])

    assert args.command == "result"
    assert args.session_id == "sess-1"


def test_cli_plugin_list_uses_app_server(monkeypatch, capsys):
    calls = []

    class FakeClient:
        def __init__(self, base_url):
            self.base_url = base_url

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def connect(self, thread_id=None):
            return None

        async def request(self, method, params=None):
            calls.append((method, params or {}))
            return {"plugins": [{"name": "repo-policy", "enabled": True}]}

    monkeypatch.setattr("writer_cli.__main__.AppServerClient", FakeClient)
    from writer_cli.__main__ import main

    assert main(["plugin", "list"]) == 0
    assert calls == [("plugin.list", {})]
    assert "repo-policy" in capsys.readouterr().out


def test_cli_hook_trust_uses_app_server(monkeypatch, capsys):
    calls = []

    class FakeClient:
        def __init__(self, base_url):
            self.base_url = base_url

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def connect(self, thread_id=None):
            return None

        async def request(self, method, params=None):
            calls.append((method, params or {}))
            return {"hook_id": "hook-1", "trusted": True}

    monkeypatch.setattr("writer_cli.__main__.AppServerClient", FakeClient)
    from writer_cli.__main__ import main

    assert main(["hook", "trust", "hook-1"]) == 0
    assert calls == [("hook.trust", {"hook_id": "hook-1"})]
    assert "trusted" in capsys.readouterr().out


def test_ping_event_is_hidden():
    event = {"event": "ping", "data": {}}

    assert _format_event(event) is None


def test_unknown_event_is_hidden():
    event = {"event": "writer_custom", "data": {"value": 3}}

    assert _format_event(event) is None


def core_run_item(kind, payload, **extra):
    return {
        "event": "app_server_event",
        "data": {
            "method": "core/runItem",
            "payload": {
                "kind": kind,
                "thread_id": "thread-1",
                "event_id": f"event-{kind}",
                "turn_id": "turn-1",
                "item_id": f"item-{kind}",
                "payload": payload,
                **extra,
            },
        },
    }


def test_app_server_core_run_item_message_formats_reply():
    event = core_run_item("message", {"type": "agentMessage", "delta": "done"})

    assert _format_event(event) == "done"


def test_app_server_core_run_item_compaction_formats_status_not_summary():
    event = core_run_item(
        "message",
        {
            "type": "compaction",
            "label": "上下文已压缩",
            "content": "[Compacted Context]\n1. Current Goal\n- Continue.",
            "before_tokens": 18000,
            "after_tokens": 7200,
            "compacted_messages": 8,
        },
        status="completed",
    )

    assert _format_event(event) == "上下文已压缩 · 18000 → 7200 tokens"


def test_app_server_core_run_item_compaction_formats_skipped_business_status():
    event = core_run_item(
        "message",
        {
            "type": "compaction",
            "label": "暂无可压缩上下文",
            "compaction_status": "skipped",
            "message": "Not enough history to compact",
        },
        status="completed",
    )

    assert _format_event(event) == "无需压缩 · 原上下文已保留"


def test_cli_run_formatter_formats_compaction_as_process_line():
    formatter = CliRunFormatter()
    lines = formatter.format(
        core_run_item(
            "message",
            {
                "type": "compaction",
                "label": "上下文已压缩",
                "content": "[Compacted Context]\n1. Current Goal\n- Continue.",
                "before_tokens": 18000,
                "after_tokens": 7200,
                "compacted_messages": 8,
            },
            status="completed",
        )
    )

    assert lines == ["[00:00] done 上下文已压缩 · 18000 → 7200 tokens"]


def test_app_server_turn_lifecycle_event_is_hidden():
    event = {
        "event": "app_server_event",
        "data": {
            "method": "turn/started",
            "payload": {"type": "turn", "status": "running"},
        },
    }

    assert _format_event(event) is None


def test_app_server_turn_interrupted_is_not_terminal_without_core_status():
    event = {
        "event": "app_server_event",
        "data": {
            "method": "turn/interrupted",
            "payload": {"type": "turn", "reason": "user_interrupt"},
        },
    }

    assert _format_event(event) is None
    assert _is_done_event(event) is False


def test_app_server_core_run_item_approval_is_waiting_with_request_id():
    event = core_run_item(
        "approval_request",
        {"request_id": "req-1", "message": "Approve?"},
        item_id="req-1",
        status="waiting",
    )

    assert _format_event(event) == "[waiting] Approve?"
    assert _is_waiting_event(event) is True
    assert _event_request_id(event) == "req-1"


def test_app_server_core_run_item_completed_is_done():
    event = core_run_item("status", {"type": "turn"}, status="completed")

    assert _format_event(event) == "[done]"
    assert _is_done_event(event) is True


def test_cli_run_formatter_ignores_legacy_writer_event():
    formatter = CliRunFormatter()
    event = {"event": "writer_thought", "data": {"text": "long internal reasoning"}}

    assert formatter.format(event) == []


def test_cli_run_formatter_ignores_legacy_writer_event_when_verbose():
    formatter = CliRunFormatter(verbose=True)
    lines = formatter.format({"event": "writer_thought", "data": {"text": "long internal reasoning"}})

    assert lines == []


def test_cli_run_formatter_keeps_legacy_writer_error_output():
    formatter = CliRunFormatter()

    assert formatter.format({"event": "writer_error", "data": {"error": "cannot continue"}}) == [
        "[00:00] error cannot continue"
    ]


def test_cli_run_formatter_formats_core_tool_call_event():
    formatter = CliRunFormatter()
    event = core_run_item(
        "tool_call",
        {
            "type": "dynamicToolCall",
            "tool_name": "write_file",
            "arguments": {"path": "draft.md"},
            "message": "writing",
        },
        status="running",
    )
    lines = formatter.format(event)

    assert lines == ["[00:00] file write_file draft.md writing"]


def test_cli_run_formatter_formats_core_reply_delta():
    formatter = CliRunFormatter()
    lines = formatter.format(core_run_item("message", {"type": "agentMessage", "delta": "最终结果"}))

    assert lines == ["[00:00] reply 最终结果"]


def test_cli_run_formatter_formats_core_completed_status():
    formatter = CliRunFormatter()
    lines = formatter.format(core_run_item("status", {"type": "turn"}, status="completed"))

    assert lines == ["[00:00] done"]


def test_cli_run_formatter_formats_core_completed_status_with_usage_count():
    formatter = CliRunFormatter()

    formatter.format(core_run_item("usage", {"type": "turn", "runtime_metrics": {"total_tokens": 12}}))
    lines = formatter.format(core_run_item("status", {"type": "turn"}, status="completed"))

    assert lines == ["[00:00] done 模型调用 1 次"]


@pytest.mark.asyncio
async def test_app_server_client_deduplicates_response_and_socket_events():
    client = AppServerClient("http://writer.test")
    event = {
        "event_id": "event-1",
        "seq": 1,
        "thread_id": "thread-1",
        "method": "item/started",
        "payload": {"type": "userMessage"},
    }

    await client.put_app_server_event(event)
    await client.put_app_server_event(dict(event))

    queued = await asyncio.wait_for(client._events.get(), timeout=1)
    assert queued == {"event": "app_server_event", "data": event}
    assert client._events.empty()


def test_cli_run_formatter_formats_core_failed_status():
    formatter = CliRunFormatter()
    lines = formatter.format(core_run_item("status", {"type": "turn", "raw_end_reason": "llm_error"}, status="failed"))

    assert lines == ["[00:00] failed llm_error"]


def test_cli_run_formatter_formats_core_error():
    formatter = CliRunFormatter()
    lines = formatter.format(core_run_item("error", {"type": "approval", "message": "cannot continue"}, status="failed"))

    assert lines == ["[00:00] error cannot continue"]
