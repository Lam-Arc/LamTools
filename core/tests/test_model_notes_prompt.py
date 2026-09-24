from __future__ import annotations

import json
from pathlib import Path

import lamtools_core.cli as cli_module
from lamtools_core.app.http_agent_app import CoreConfigRoutingLLMClient
from lamtools_core.cli import CoreHttpLLMClient, LLMConfig, load_llm_config
from lamtools_core.config.model_store import ModelStore
from lamtools_core.llm import ChatMessage, LLMRequest


def _config(*, model_id: str = "model-a", notes: str = "") -> LLMConfig:
    return LLMConfig(
        provider_name="Provider",
        provider_api_type="openai",
        base_url="https://example.test/v1",
        api_key="secret",
        model_record_id=model_id,
        model_id=model_id,
        display_name=model_id,
        notes=notes,
    )


def _client(*, model_id: str = "model-a", notes: str = "") -> CoreHttpLLMClient:
    return CoreHttpLLMClient(
        config=_config(model_id=model_id, notes=notes),
        adapter_profile={"id": "test", "protocol": "openai-chat-completions"},
        thinking_enabled=False,
        thinking_budget=0,
        reasoning_level="off",
        max_tokens=128,
        temperature=0.2,
    )


def _write_routing_config(config_root: Path) -> None:
    providers = config_root / "providers"
    providers.mkdir(parents=True)
    (providers / "provider.jsonc").write_text(
        json.dumps(
            {
                "id": "provider",
                "name": "Provider",
                "api_type": "openai",
                "base_url": "https://example.test/v1",
                "api_key": "secret",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    models = config_root / "models"
    models.mkdir(parents=True)
    for model_id, notes in (
        ("model-a", "只使用模型 A 的约束"),
        ("model-b", "只使用模型 B 的约束"),
    ):
        (models / f"{model_id}.jsonc").write_text(
            json.dumps(
                {
                    "model_id": model_id,
                    "display_name": model_id,
                    "provider_id": "provider",
                    "notes": notes,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def test_load_llm_config_carries_model_notes(
    isolated_config_root: Path,
    monkeypatch,
) -> None:
    _write_routing_config(isolated_config_root)
    monkeypatch.setattr(cli_module, "_default_model_store", ModelStore())
    monkeypatch.setattr(cli_module, "_model_store_work_root", None)

    assert load_llm_config(model_ref="model-a").notes == "只使用模型 A 的约束"


def test_http_client_injects_notes_without_mutating_or_duplicating_request() -> None:
    original_system = ChatMessage(
        role="system",
        content="base instructions",
        metadata={"cache": "stable"},
    )
    original = LLMRequest(
        model="model-a",
        messages=[original_system, ChatMessage(role="user", content="hello")],
        metadata={"trace_id": "trace-1"},
    )
    client = _client(notes="  第一行\n第二行  ")

    prepared = client._request_with_defaults(original)
    prepared_again = client._request_with_defaults(prepared)

    assert original.messages[0] is original_system
    assert original_system.content == "base instructions"
    assert prepared.messages[0] is not original_system
    assert prepared.messages[0].metadata == {"cache": "stable"}
    assert prepared.messages[0].content == "base instructions\nCurrent model notes: 第一行\n第二行"
    assert str(prepared_again.messages[0].content).count("Current model notes: ") == 1
    assert prepared.metadata == {"trace_id": "trace-1"}
    assert "notes" not in prepared.metadata

    payload = client._assemble_request(prepared, stream=False)["payload"]
    assert "notes" not in payload
    assert payload["messages"][0]["content"].endswith("Current model notes: 第一行\n第二行")


def test_http_client_omits_empty_notes_without_adding_system_message_or_blank_line() -> None:
    messages = [ChatMessage(role="user", content="hello")]
    prepared = _client(notes=" \n ")._request_with_defaults(LLMRequest(messages=messages))

    assert prepared.messages is messages
    assert [(message.role, message.content) for message in prepared.messages] == [("user", "hello")]


def test_http_client_inserts_notes_as_first_system_message_when_missing() -> None:
    original_user = ChatMessage(role="user", content="hello")

    prepared = _client(notes="direct request note")._request_with_defaults(
        LLMRequest(messages=[original_user])
    )

    assert [(message.role, message.content) for message in prepared.messages] == [
        ("system", "Current model notes: direct request note"),
        ("user", "hello"),
    ]
    assert prepared.messages[1] is original_user


def test_routing_client_uses_notes_for_each_actual_model_without_parent_leakage(
    isolated_config_root: Path,
    monkeypatch,
) -> None:
    _write_routing_config(isolated_config_root)
    monkeypatch.setattr(cli_module, "_default_model_store", ModelStore())
    monkeypatch.setattr(cli_module, "_model_store_work_root", None)
    routing = CoreConfigRoutingLLMClient(
        default_model_ref="model-a",
        thinking_enabled=False,
        thinking_budget=0,
        reasoning_level="off",
        max_tokens=128,
    )

    inherited_request = LLMRequest(
        messages=[ChatMessage(role="system", content="child base")],
    )
    inherited_config, inherited_client = routing._client_for_request(inherited_request)
    inherited = inherited_client._request_with_defaults(
        LLMRequest(messages=inherited_request.messages, model=inherited_config.model_id)
    )

    override_request = LLMRequest(
        model="model-b",
        messages=[ChatMessage(role="system", content="child base")],
    )
    override_config, override_client = routing._client_for_request(override_request)
    overridden = override_client._request_with_defaults(
        LLMRequest(messages=override_request.messages, model=override_config.model_id)
    )

    assert inherited.model == "model-a"
    assert "Current model notes: 只使用模型 A 的约束" in str(inherited.messages[0].content)
    assert "模型 B" not in str(inherited.messages[0].content)
    assert overridden.model == "model-b"
    assert "Current model notes: 只使用模型 B 的约束" in str(overridden.messages[0].content)
    assert "模型 A" not in str(overridden.messages[0].content)
