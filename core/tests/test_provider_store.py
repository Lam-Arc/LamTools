"""Tests for the jsonc ProviderStore (providers/*.jsonc)."""
from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.config.provider_store import (
    MASKED_API_KEY,
    ProviderConfig,
    ProviderStore,
    mask_api_key,
    slugify,
)


def _write_provider(config_root: Path, provider_id: str, *, name: str = "", api_key: str = "", base_url: str = "", is_default: bool = False, extra: str | None = None) -> None:
    name = name or provider_id
    content = (
        "{\n"
        f'  "id": "{provider_id}",\n'
        f'  "name": "{name}",\n'
        f'  "api_type": "openai",\n'
        f'  "base_url": "{base_url}",\n'
        f'  "api_key": "{api_key}",\n'
        f'  "is_default": {str(is_default).lower()}'
    )
    if extra:
        content += ",\n" + extra
    content += "\n}\n"
    path = config_root / "providers" / f"{provider_id}.jsonc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_slugify_keeps_ascii_cjk_and_collapses_rest() -> None:
    assert slugify("OpenCode Zen") == "OpenCode-Zen"
    assert slugify("讯飞 MaaS") == "讯飞-MaaS"
    assert slugify("a/b:c") == "a-b-c"
    assert slugify("   ") == "provider"


def test_mask_api_key() -> None:
    assert mask_api_key("sk-secret") == MASKED_API_KEY
    assert mask_api_key("") == ""


def test_provider_store_lists_and_gets_by_id_and_name(isolated_config_root: Path) -> None:
    _write_provider(
        isolated_config_root, "opencode-zen", name="OpenCode Zen",
        api_key="sk-zen", base_url="https://opencode.ai/zen/v1",
        extra='  "adapter_profile_id": "openai-chat"',
    )
    store = ProviderStore()
    providers = store.list_sync()
    assert len(providers) == 1

    provider = providers[0]
    assert provider.id == "opencode-zen"
    assert provider.name == "OpenCode Zen"
    assert provider.api_key == "sk-zen"
    assert provider.adapter_profile_id == "openai-chat"

    assert store.get_sync("opencode-zen").name == "OpenCode Zen"
    assert store.get_sync("OpenCode Zen").id == "opencode-zen"
    assert store.get_sync("missing") is None


def test_provider_store_default_and_single_fallback(isolated_config_root: Path) -> None:
    _write_provider(isolated_config_root, "a", name="Provider A", api_key="k1")
    assert ProviderStore().default_sync().id == "a"  # single provider fallback

    _write_provider(isolated_config_root, "b", name="Provider B", api_key="k2", is_default=True)
    assert ProviderStore().default_sync().id == "b"  # explicit default wins

    _write_provider(isolated_config_root, "c", name="Provider C", api_key="k3")
    assert ProviderStore().default_sync().id == "b"


def test_provider_store_write_round_trip_and_scope(isolated_config_root: Path, tmp_path: Path) -> None:
    store = ProviderStore()
    provider = ProviderConfig(
        id="custom",
        name="Custom",
        api_type="anthropic",
        base_url="https://custom.test/v1",
        api_key="sk-custom",
    )
    path = store.write(provider, scope="global", work_root=None)
    assert path == isolated_config_root / "providers" / "custom.jsonc"
    assert path.is_file()

    written = store.get_sync("custom")
    assert written.api_type == "anthropic"
    assert written.base_url == "https://custom.test/v1"
    assert written.api_key == "sk-custom"

    project_path = store.write(provider, scope="project", work_root=tmp_path / "project")
    assert project_path == tmp_path / "project" / ".lam" / "config" / "providers" / "custom.jsonc"
    assert project_path.is_file()

    # Project scope overrides global on read.
    project_provider = store.get_sync("custom", work_root=tmp_path / "project")
    assert project_provider.source_path == str(project_path)


def test_provider_store_serialization_keeps_masked_key_out_of_listing(isolated_config_root: Path) -> None:
    _write_provider(isolated_config_root, "p1", name="P1", api_key="super-secret-key")
    providers = ProviderStore().list_sync()
    assert providers[0].masked().api_key == MASKED_API_KEY
    assert providers[0].api_key == "super-secret-key"


def test_unified_config_dir_overrides_legacy_providers(isolated_config_root: Path, monkeypatch) -> None:
    """Regression: the unified config dir is where new writes land, so it must
    override the legacy {lam_home}/config/providers fallback.
    """
    import os

    legacy_providers = Path(os.environ["LAMTOOLS_HOME"]) / "config" / "providers"
    legacy_providers.mkdir(parents=True, exist_ok=True)
    (legacy_providers / "stale.jsonc").write_text(
        '{\n'
        '  "id": "stale",\n'
        '  "name": "Stale Provider",\n'
        '  "api_type": "openai",\n'
        '  "base_url": "https://stale.test/v1",\n'
        '  "api_key": "stale-key"\n'
        '}\n',
        encoding="utf-8",
    )
    _write_provider(
        isolated_config_root, "stale", name="Fresh Provider",
        api_key="fresh-key", base_url="https://fresh.test/v1",
    )

    provider = ProviderStore().get_sync("stale")
    assert provider is not None
    assert provider.name == "Fresh Provider"
    assert provider.api_key == "fresh-key"
    assert provider.base_url == "https://fresh.test/v1"
