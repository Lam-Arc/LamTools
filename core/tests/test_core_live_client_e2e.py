from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import pytest

uvicorn = pytest.importorskip("uvicorn")  # e2e 需要真实 uvicorn 服务；dev 最小环境缺席时跳过

from lamtools_core.app import CoreAppServerClient
from lamtools_core.app.http_agent_app import CoreConfigRoutingLLMClient, create_core_agent_http_app
from lamtools_core.llm import LLMStreamEvent, LLMToolCall


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


async def _wait_for_waiting(client: CoreAppServerClient, thread_id: str) -> None:
    for _ in range(100):
        snapshot = (await client.read_thread(thread_id=thread_id)).get("snapshot") or {}
        if snapshot.get("core", {}).get("status") == "waiting":
            return
        await asyncio.sleep(0.01)
    raise AssertionError("approval request did not become pending")


async def _wait_for_terminal(client: CoreAppServerClient, thread_id: str, *, timeout: float = 5.0) -> None:
    last_snapshot: dict = {}
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        snapshot = (await client.read_thread(thread_id=thread_id)).get("snapshot") or {}
        last_snapshot = snapshot
        if snapshot.get("core", {}).get("status") in {"completed", "cancelled", "failed"}:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"{thread_id} did not reach a terminal state: {last_snapshot}")


@pytest.mark.asyncio
async def test_core_app_server_client_runs_live_operation_matrix_against_real_websocket_server(tmp_path, monkeypatch, isolated_config_root) -> None:
    _write_jsonc_config(isolated_config_root)
    release_steered_turn = asyncio.Event()
    release_cancelled_turn = asyncio.Event()
    steered_stream_started = asyncio.Event()
    cancelled_stream_started = asyncio.Event()
    async def stream(self, request):
        user_text = "\n".join(str(message.content or "") for message in request.messages if message.role == "user")
        if "fail-model" in user_text:
            raise RuntimeError("provider unavailable")
        if "approval" in user_text:
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-approval",
                        name="write_file",
                        arguments={"path": "approved.md", "content": "approved\n"},
                    )
                ],
            )
            return
        if "hold-steer" in user_text:
            steered_stream_started.set()
            while not release_steered_turn.is_set():
                await asyncio.sleep(0.01)
        elif "hold-cancel" in user_text:
            cancelled_stream_started.set()
            while not release_cancelled_turn.is_set():
                await asyncio.sleep(0.01)
        yield LLMStreamEvent(kind="content_delta", content="done")
        yield LLMStreamEvent(kind="done")

    async def complete(self, request):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(CoreConfigRoutingLLMClient, "stream", stream)
    monkeypatch.setattr(CoreConfigRoutingLLMClient, "complete", complete)
    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=tmp_path / "core.db",
        data_dir=tmp_path / "data",
        work_root=tmp_path / "work",
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    server_task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started
        client = CoreAppServerClient(f"http://127.0.0.1:{port}")
        try:
            await client.connect()
            started = await client.start_turn(
                thread_id="thread-running",
                client_message_id="start-running",
                input_items=[{"type": "text", "text": "hold-steer"}],
            )
            turn_id = started["runtime_start"]["turn_id"]
            await asyncio.wait_for(steered_stream_started.wait(), timeout=5)
            queue_tasks = [
                asyncio.create_task(
                    client.create_queue_input(
                        thread_id="thread-running",
                        client_message_id=f"queue-running-{index}",
                        input_items=[{"type": "text", "text": f"queued-{index}"}],
                    )
                )
                for index in range(8)
            ]
            steer_task = asyncio.create_task(
                client.steer_turn(
                    thread_id="thread-running",
                    turn_id=turn_id,
                    input_items=[{"type": "text", "text": "steer"}],
                )
            )
            *queued_items, steered = await asyncio.wait_for(
                asyncio.gather(*queue_tasks, steer_task),
                timeout=5,
            )
            release_steered_turn.set()
            resumed = await client.request("thread.resume", {"thread_id": "thread-running", "last_seen_seq": 0})
            read = await client.read_thread(thread_id="thread-running")

            assert all(result["queue_item"]["status"] == "queued" for result in queued_items)
            assert steered["applied"] is True
            assert resumed["events"]
            resumed_sequences = [event["seq"] for event in resumed["events"]]
            assert resumed_sequences == list(range(1, len(resumed_sequences) + 1))
            assert read["snapshot"]["thread_id"] == "thread-running"
            await _wait_for_terminal(client, "thread-running")

            cancelling = await client.start_turn(
                thread_id="thread-cancel",
                client_message_id="start-cancel",
                input_items=[{"type": "text", "text": "hold-cancel"}],
            )
            await asyncio.wait_for(cancelled_stream_started.wait(), timeout=5)
            cancelled, next_started = await asyncio.wait_for(
                asyncio.gather(
                    client.cancel_turn(
                        thread_id="thread-cancel",
                        turn_id=cancelling["runtime_start"]["turn_id"],
                    ),
                    client.start_turn(
                        thread_id="thread-next",
                        client_message_id="start-next",
                        input_items=[{"type": "text", "text": "next"}],
                    ),
                ),
                timeout=5,
            )
            assert [event["method"] for event in cancelled["events"]] == ["turn/interrupted", "core/runItem"]
            cancelled_turn_id = cancelling["runtime_start"]["turn_id"]
            assert "snapshot" not in cancelled
            assert cancelled["events"][1]["payload"]["status"] == "interrupting"
            await _wait_for_terminal(client, "thread-cancel")
            cancelled_snapshot = (await client.read_thread(thread_id="thread-cancel"))["snapshot"]
            cancelled_turn = cancelled_snapshot["core"]["turns"][cancelled_turn_id]
            assert cancelled_turn["status"] == "cancelled"
            assert cancelled_turn["usage"]["context_window_tokens"] == 128_000
            assert cancelled_turn["usage"]["estimated_prompt_tokens"] > 0
            assert next_started["runtime_start"]["thread_id"] == "thread-next"

            failed = await client.start_turn(
                thread_id="thread-failed",
                client_message_id="start-failed",
                input_items=[{"type": "text", "text": "fail-model"}],
            )
            await _wait_for_terminal(client, "thread-failed")
            failed_snapshot = (await client.read_thread(thread_id="thread-failed"))["snapshot"]
            failed_turn = failed_snapshot["core"]["turns"][failed["runtime_start"]["turn_id"]]
            assert failed_turn["status"] == "failed"
            assert failed_turn["usage"]["context_window_tokens"] == 128_000
            assert failed_turn["usage"]["estimated_prompt_tokens"] > 0

            await client.start_turn(
                thread_id="thread-approval",
                client_message_id="start-approval",
                input_items=[{"type": "text", "text": "approval"}],
            )
            await _wait_for_waiting(client, "thread-approval")
            approval = await client.request(
                "approval.respond",
                {
                    "thread_id": "thread-approval", "request_id": "call-approval",
                    "action": "deny", "response": "no",
                },
            )
            assert approval["snapshot"]["core"]["requests"]["call-approval"]["status"] == "resolved"
            assert approval["snapshot"]["core"]["status"] == "cancelled"

        finally:
            await asyncio.wait_for(client.close(), timeout=1)
    finally:
        release_steered_turn.set()
        release_cancelled_turn.set()
        server.should_exit = True
        await server_task
