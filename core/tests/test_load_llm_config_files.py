"""Integration test: load_llm_config resolves models from jsonc model + provider files."""
from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core import cli as cli_module
from lamtools_core.cli import (
    configure_model_store_context,
    list_llm_model_configs,
    LLMConfig,
    load_llm_config,
)


def _write_provider(config_root: Path, provider_id: str, name: str, *, api_key: str, base_url: str, api_type: str = "openai", extra: str | None = None) -> None:
    content = (
        "{\n"
        f'  "id": "{provider_id}",\n'
        f'  "name": "{name}",\n'
        f'  "api_type": "{api_type}",\n'
        f'  "base_url": "{base_url}",\n'
        f'  "api_key": "{api_key}"'
    )
    if extra:
        content += ",\n" + extra
    content += "\n}\n"
    path = config_root / "providers" / f"{provider_id}.jsonc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_model(config_root: Path, model_id: str, *, provider: str, display_name: str, context_window: int, max_output_tokens: int, temperature: float, thinking_supported: bool, thinking_budget: int, is_default: bool = False, capability: str = "", provider_id: str = "") -> None:
    content = (
        "{\n"
        f'  "model_id": "{model_id}",\n'
        f'  "display_name": "{display_name}",\n'
        f'  "provider": "{provider}",\n'
        f'  "provider_id": "{provider_id}",\n'
        f'  "context_window": {context_window},\n'
        f'  "max_output_tokens": {max_output_tokens},\n'
        f'  "temperature": {temperature},\n'
        f'  "thinking": {{"supported": {str(thinking_supported).lower()}, "budget": {thinking_budget}}},'
    )
    if capability:
        content += f'\n  "capability": "{capability}",'
    content += f'\n  "is_default": {str(is_default).lower()}\n'
    content += "}\n"
    path = config_root / "models" / f"{model_id}.jsonc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolated_model_store(monkeypatch):
    """Each test gets a cleared process-level store context."""
    monkeypatch.setattr(cli_module, "_default_model_store", None)
    monkeypatch.setattr(cli_module, "_model_store_work_root", None)
    configure_model_store_context(work_root=None, store=None)
    yield
    configure_model_store_context(work_root=None, store=None)


def _make_config(config_root: Path) -> None:
    """Write a provider + two models mirroring the old DB fixture."""
    _write_provider(
        config_root, "prov-1", "讯飞 MaaS",
        api_key="sk-test", base_url="https://example.com/v2/",
        extra='  "adapter_profile_id": "xfyun-coding-plan"',
    )
    _write_model(
        config_root, "xopglm52", provider="讯飞 MaaS", display_name="GLM-5.2",
        context_window=500000, max_output_tokens=32768, temperature=0.7,
        thinking_supported=True, thinking_budget=10000,
    )
    _write_model(
        config_root, "xopkimik26", provider="讯飞 MaaS", display_name="Kimi-K2.6",
        context_window=256000, max_output_tokens=32768, temperature=0.7,
        thinking_supported=True, thinking_budget=10000, is_default=True,
        capability="multimodal", provider_id="prov-1",
    )


def test_load_llm_config_resolves_text_model_from_jsonc(isolated_config_root: Path):
    _make_config(isolated_config_root)

    config = load_llm_config(model_ref="xopglm52")

    assert isinstance(config, LLMConfig)
    # Model fields come from the jsonc model file.
    assert config.model_id == "xopglm52"
    assert config.display_name == "GLM-5.2"
    assert config.context_window == 500000
    assert config.max_output_tokens == 32768
    assert config.temperature == 0.7
    assert config.thinking_supported is True
    assert config.thinking_budget == 10000
    # Provider connection comes from the jsonc provider file.
    assert config.provider_name == "讯飞 MaaS"
    assert config.api_key == "sk-test"
    assert config.base_url == "https://example.com/v2"
    # Capability resolved via builtin table (GLM is text-only).
    assert config.capability == "text"
    # Provider-level adapter profile is surfaced through provider_extra.
    assert config.provider_extra.get("adapter_profile_id") == "xfyun-coding-plan"


def test_load_llm_config_resolves_multimodal_capability_for_kimi(isolated_config_root: Path):
    _make_config(isolated_config_root)

    config = load_llm_config(model_ref="xopkimik26")

    assert config.model_id == "xopkimik26"
    assert config.capability == "multimodal"


def test_load_llm_config_resolves_default_model_when_ref_empty(isolated_config_root: Path):
    _make_config(isolated_config_root)

    config = load_llm_config(model_ref="")

    # The default model (is_default=true) is xopkimik26.
    assert config.model_id == "xopkimik26"


def test_load_llm_config_raises_for_unknown_model(isolated_config_root: Path):
    _make_config(isolated_config_root)

    with pytest.raises(ValueError):
        load_llm_config(model_ref="no-such-model")


def test_load_llm_config_strips_trailing_slash_from_base_url(isolated_config_root: Path):
    _make_config(isolated_config_root)
    config = load_llm_config(model_ref="xopglm52")
    assert not config.base_url.endswith("/")


def test_list_llm_model_configs_resolves_provider_id_from_provider_store(isolated_config_root: Path):
    """jsonc model files store ``provider`` (a name) and optionally
    ``provider_id``. ``list_llm_model_configs`` must resolve the provider_id /
    api_type through the ProviderStore so the UI can match models to their
    provider.

    Regression test for the "暂无模型" bug where models had an empty
    ``provider_id`` and never matched any provider in the UI.
    """
    _make_config(isolated_config_root)

    models = list_llm_model_configs()
    assert models, "expected jsonc models"

    by_model_id = {m["model_id"]: m for m in models}
    glm = by_model_id["xopglm52"]
    # provider_id resolved from the provider store by name, not blank.
    assert glm["provider_id"] == "prov-1"
    assert glm["provider_name"] == "讯飞 MaaS"
    assert glm["provider_api_type"] == "openai"

    kimi = by_model_id["xopkimik26"]
    assert kimi["provider_id"] == "prov-1"
    assert kimi["capability"] == "multimodal"
    assert kimi["is_default"] is True


def test_list_llm_model_configs_survives_missing_provider(isolated_config_root: Path):
    _write_model(
        isolated_config_root, "orphan", provider="Nonexistent", display_name="Orphan",
        context_window=1000, max_output_tokens=4096, temperature=0.2,
        thinking_supported=False, thinking_budget=10000,
    )
    models = list_llm_model_configs()
    assert len(models) == 1
    assert models[0]["provider_id"] == ""
    assert models[0]["provider_name"] == "Nonexistent"


def test_unified_config_dir_overrides_legacy_models(isolated_config_root: Path, monkeypatch) -> None:
    """Regression: the unified config dir is where new writes land, so it must
    override the legacy {lam_home}/config/models fallback. A stale legacy file
    with the same model_id used to shadow freshly created/edited models,
    making the UI look like model creation had no effect.
    """
    import os

    legacy_models = Path(os.environ["LAMTOOLS_HOME"]) / "config" / "models"
    legacy_models.mkdir(parents=True, exist_ok=True)
    (legacy_models / "shadowed.jsonc").write_text(
        '{\n'
        '  "model_id": "shadowed",\n'
        '  "display_name": "Legacy Version",\n'
        '  "provider": "Old Provider",\n'
        '  "provider_id": "old-uuid",\n'
        '  "context_window": 100000,\n'
        '  "max_output_tokens": 8192,\n'
        '  "temperature": 0.7,\n'
        '  "thinking": {"supported": true, "budget": 10000}\n'
        '}\n',
        encoding="utf-8",
    )
    # Same model_id in the unified config dir (what config.models.upsert writes).
    _write_provider(isolated_config_root, "new-provider", name="New Provider",
                    api_key="sk-new", base_url="https://new.test/v1")
    _write_model(
        isolated_config_root, "shadowed", provider="New Provider", display_name="New Version",
        context_window=200000, max_output_tokens=16384, temperature=0.3,
        thinking_supported=False, thinking_budget=2000,
        capability="multimodal", provider_id="new-provider",
    )

    models = {m["model_id"]: m for m in list_llm_model_configs()}
    assert models["shadowed"]["provider_name"] == "New Provider"
    assert models["shadowed"]["provider_id"] == "new-provider"
    assert models["shadowed"]["display_name"] == "New Version"
    assert models["shadowed"]["capability"] == "multimodal"
    assert load_llm_config(model_ref="shadowed").provider_name == "New Provider"
