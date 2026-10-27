"""QQ credentials are stored through the host's per-plugin secret store."""

from __future__ import annotations

from pathlib import Path

from lamtools_core.plugin_system import PluginContext
from lamtools_core.plugin_system.secrets import PluginSecretStore

from qqbot.runtime import QQBotRuntime


def test_manual_credentials_go_to_the_host_secret_store(tmp_path: Path) -> None:
    store = PluginSecretStore(tmp_path / "secrets")
    context = PluginContext(work_root=tmp_path, data_dir=tmp_path)
    context.set_scoped_service("secrets", store.view("qq-bot"))
    runtime = QQBotRuntime(context)

    runtime._save_credentials("123456", "super-secret")

    assert store.view("qq-bot").get("appSecret") == "super-secret"
    assert runtime._app_secret() == "super-secret"
    assert "super-secret" not in (tmp_path / "config.jsonc").read_text(encoding="utf-8")


def test_legacy_plaintext_config_is_migrated_on_start(tmp_path: Path) -> None:
    (tmp_path / "config.jsonc").write_text(
        '{"appId": "123456", "appSecret": "legacy-secret"}',
        encoding="utf-8",
    )
    store = PluginSecretStore(tmp_path / "secrets")
    context = PluginContext(work_root=tmp_path, data_dir=tmp_path)
    context.set_scoped_service("secrets", store.view("qq-bot"))
    runtime = QQBotRuntime(context)

    # Same migration step start() performs before any gateway work.
    runtime._migrate_secret()

    assert store.view("qq-bot").get("appSecret") == "legacy-secret"
    assert "legacy-secret" not in (tmp_path / "config.jsonc").read_text(encoding="utf-8")
    assert runtime._app_secret() == "legacy-secret"
