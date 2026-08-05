from __future__ import annotations

from pathlib import Path

from lamtools_core.llm.profiles import apply_thinking_payload, load_jsonc
from app.utils.llm_adapter_profiles import (
    load_adapter_profiles,
    resolve_adapter_profile,
)


def test_builtin_xfyun_profile_uses_enable_thinking():
    profile = resolve_adapter_profile(
        api_type="openai",
        base_url="https://maas-coding-api.cn-huabei-1.xf-yun.com/v2",
    )
    payload: dict[str, object] = {}

    apply_thinking_payload(payload, profile=profile, thinking_budget=1000)

    assert profile["id"] == "xfyun-coding-plan"
    assert payload == {"enable_thinking": True}


def test_builtin_openai_profile_uses_thinking_budget_template():
    profile = resolve_adapter_profile(
        api_type="openai",
        base_url="https://api.openai.com/v1",
    )
    payload: dict[str, object] = {}

    apply_thinking_payload(payload, profile=profile, thinking_budget=1234)

    assert profile["id"] == "openai-chat"
    assert payload == {
        "thinking": {
            "type": "enabled",
            "budget_tokens": 1234,
        }
    }


def test_provider_extra_selects_custom_jsonc_profile(monkeypatch, tmp_path):
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    profile_file = profile_dir / "custom-gateway.jsonc"
    profile_file.write_text(
        """
        {
          // comments and trailing commas are allowed
          "id": "custom-gateway",
          "request": {
            "thinking": {
              "when_enabled": {
                "custom_thinking": {
                  "budget": "$thinking_budget"
                }
              }
            },
          },
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("LAMWRITER_LLM_ADAPTER_DIR", str(profile_dir))
    load_adapter_profiles.cache_clear()

    profile = resolve_adapter_profile(
        api_type="openai",
        base_url="https://example.invalid/v1",
        provider_extra={"adapter_profile": "custom-gateway"},
    )
    payload: dict[str, object] = {}
    apply_thinking_payload(payload, profile=profile, thinking_budget=4321)

    assert profile["id"] == "custom-gateway"
    assert payload == {"custom_thinking": {"budget": 4321}}


def test_member_resource_dir_contributes_adapter_profiles(monkeypatch, tmp_path):
    resource_root = tmp_path / "runtime" / "members" / "writer"
    profile_dir = resource_root / "llm_adapters"
    profile_dir.mkdir(parents=True)
    (profile_dir / "resource-gateway.jsonc").write_text(
        '{"id":"resource-gateway","match_base_url":["resource-gateway"],"request":{"unsupported_fields":["tools"]}}',
        encoding="utf-8",
    )
    monkeypatch.delenv("LAMWRITER_LLM_ADAPTER_DIR", raising=False)
    monkeypatch.setenv("LAMWRITER_MEMBER_RESOURCE_DIR", str(resource_root))
    load_adapter_profiles.cache_clear()

    profile = resolve_adapter_profile(
        api_type="openai",
        base_url="https://resource-gateway.example/v1",
    )

    assert profile["id"] == "resource-gateway"
    load_adapter_profiles.cache_clear()


def test_member_resource_adapter_overrides_builtin_profile(monkeypatch, tmp_path):
    resource_root = tmp_path / "runtime" / "members" / "writer"
    profile_dir = resource_root / "llm_adapters"
    profile_dir.mkdir(parents=True)
    (profile_dir / "openai-chat.jsonc").write_text(
        '{"id":"openai-chat","request":{"thinking":{"when_enabled":{"resource_thinking":true}}}}',
        encoding="utf-8",
    )
    monkeypatch.delenv("LAMWRITER_LLM_ADAPTER_DIR", raising=False)
    monkeypatch.setenv("LAMWRITER_MEMBER_RESOURCE_DIR", str(resource_root))
    load_adapter_profiles.cache_clear()

    profile = resolve_adapter_profile(
        api_type="openai",
        base_url="https://api.openai.com/v1",
    )
    payload: dict[str, object] = {}
    apply_thinking_payload(payload, profile=profile, thinking_budget=1000)

    assert profile["id"] == "openai-chat"
    assert payload == {"resource_thinking": True}
    load_adapter_profiles.cache_clear()


def test_core_builtin_profile_loads_without_writer_builtin_dir(monkeypatch):
    monkeypatch.delenv("LAMWRITER_LLM_ADAPTER_DIR", raising=False)
    monkeypatch.delenv("LAMWRITER_MEMBER_RESOURCE_DIR", raising=False)
    monkeypatch.setattr("app.utils.llm_adapter_profiles._writer_builtin_profile_dirs", lambda: [])
    monkeypatch.setattr("app.utils.llm_adapter_profiles._runtime_profile_dirs", lambda: [])
    load_adapter_profiles.cache_clear()

    profile = resolve_adapter_profile(
        api_type="openai",
        base_url="https://maas-coding-api.cn-huabei-1.xf-yun.com/v2",
    )
    payload: dict[str, object] = {}
    apply_thinking_payload(payload, profile=profile, thinking_budget=1000)

    assert profile["id"] == "xfyun-coding-plan"
    assert payload == {"enable_thinking": True}
    load_adapter_profiles.cache_clear()


def test_core_builtin_anthropic_profile_loads_without_writer_builtin_dir(monkeypatch):
    monkeypatch.delenv("LAMWRITER_LLM_ADAPTER_DIR", raising=False)
    monkeypatch.delenv("LAMWRITER_MEMBER_RESOURCE_DIR", raising=False)
    monkeypatch.setattr("app.utils.llm_adapter_profiles._writer_builtin_profile_dirs", lambda: [])
    monkeypatch.setattr("app.utils.llm_adapter_profiles._runtime_profile_dirs", lambda: [])
    load_adapter_profiles.cache_clear()

    profile = resolve_adapter_profile(
        api_type="anthropic",
        base_url="https://api.anthropic.com",
    )
    payload: dict[str, object] = {}
    apply_thinking_payload(payload, profile=profile, thinking_budget=2000)

    assert profile["id"] == "anthropic-messages"
    assert payload == {
        "thinking": {
            "type": "enabled",
            "budget_tokens": 2000,
        }
    }
    load_adapter_profiles.cache_clear()


def test_load_jsonc_preserves_comment_like_text(tmp_path):
    path = Path(tmp_path) / "profile.jsonc"
    path.write_text(
        r'''
        {
          "id": "sample",
          "url": "https://example.com//v1",
          /* block comment */
          "text": "not /* a comment */",
        }
        ''',
        encoding="utf-8",
    )

    assert load_jsonc(path) == {
        "id": "sample",
        "url": "https://example.com//v1",
        "text": "not /* a comment */",
    }
