"""Regression tests for the config / model-resolution / error-visibility fixes.

Covers four linked defects:

* a non-ASCII api key failing every request and being retried as "flaky";
* a session silently switching model after an unrelated provider was added
  (there is no global default model anymore);
* provider/model/settings files being rewritten on disk and reloaded with no
  notice;
* provider rejections (403) carrying no local identity (which provider/address/
  model failed).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from lamtools_core.app.default_agent import CoreAgentSpec, _inherit_turn_model
from lamtools_core.app.operation_catalog import OperationRequest
from lamtools_core.config import model_selection as ms
from lamtools_core.config.change_notice import (
    drain_config_change_notices,
    reset_config_change_notices,
)
from lamtools_core.config.operations import build_config_operation_catalog
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState


@pytest.fixture(autouse=True)
def _clean_notices():
    ms.reset_model_notices()
    reset_config_change_notices()
    yield
    ms.reset_model_notices()
    reset_config_change_notices()


def _write_provider(root: Path, provider_id: str, *, name: str, base_url: str = "https://example.com/v1", api_key: str = "sk-test") -> None:
    directory = root / "providers"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{provider_id}.jsonc").write_text(
        "{\n"
        f'  "id": "{provider_id}",\n  "name": "{name}",\n  "api_type": "openai",\n'
        f'  "base_url": "{base_url}",\n  "api_key": "{api_key}"\n'
        "}\n",
        encoding="utf-8",
    )


def _write_model(
    root: Path,
    record_id: str,
    *,
    provider_id: str,
    provider_name: str,
    display_name: str = "",
    is_default: bool = False,
) -> None:
    directory = root / "models"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{record_id}.jsonc").write_text(
        "{\n"
        f'  "id": "{record_id}",\n  "model_id": "{record_id}",\n'
        f'  "display_name": "{display_name or record_id}",\n'
        f'  "provider": "{provider_name}",\n  "provider_id": "{provider_id}",\n'
        f'  "is_default": {"true" if is_default else "false"}\n'
        "}\n",
        encoding="utf-8",
    )


def _routed_provider() -> SimpleNamespace:
    """A stand-in for the config-routing LLM client (only the flag matters)."""
    return SimpleNamespace(uses_config_routing=True)


def _turn_request(thread_id: str = "thread-1") -> OperationRequest:
    return OperationRequest(name="turn.start", payload={"thread_id": thread_id, "message": "hi"})


async def _session_store_with_model(thread_id: str, model_id: str) -> InMemoryRuntimeStateStore:
    store = InMemoryRuntimeStateStore()
    await store.save(RuntimeState(session_id=thread_id, metadata={"model_id": model_id}))
    return store


# ── 条 9: non-ASCII api key ────────────────────────────────────────────────


class TestApiKeyValidation:
    def test_validate_rejects_non_ascii_and_keeps_existing_semantics(self):
        from lamtools_core.config.provider_store import (
            MASKED_API_KEY,
            ApiKeyValidationError,
            validate_api_key_text,
        )

        assert validate_api_key_text("  sk-abc  ") == "sk-abc"
        assert validate_api_key_text("") == ""
        assert validate_api_key_text(MASKED_API_KEY) == MASKED_API_KEY
        with pytest.raises(ApiKeyValidationError) as excinfo:
            validate_api_key_text("sk-abc密钥")
        message = str(excinfo.value)
        assert "非 ASCII" in message
        assert "请重新粘贴" in message

    @pytest.mark.asyncio
    async def test_provider_create_rejects_non_ascii_key_without_writing(self, isolated_config_root: Path):
        catalog = build_config_operation_catalog()
        result = await catalog.execute(
            "config.provider.create",
            {
                "name": "带中文的供应商",
                "base_url": "https://example.com/v1",
                "api_key": "sk-abc密钥",
            },
        )
        assert result.status == "error"
        assert "非 ASCII" in result.payload["error"]
        assert not list((isolated_config_root / "providers").glob("*.jsonc"))

    @pytest.mark.asyncio
    async def test_provider_update_rejects_non_ascii_key_and_keeps_old_key(self, isolated_config_root: Path):
        catalog = build_config_operation_catalog()
        created = await catalog.execute(
            "config.provider.create",
            {"name": "P", "base_url": "https://example.com/v1", "api_key": "sk-old"},
        )
        assert created.status == "ok"
        provider_id = created.payload["provider"]["id"]

        rejected = await catalog.execute(
            "config.provider.update",
            {"provider_id": provider_id, "api_key": "sk-old中文"},
        )
        assert rejected.status == "error"
        assert "非 ASCII" in rejected.payload["error"]

        from lamtools_core.config.provider_store import ProviderStore

        assert ProviderStore().get_sync(provider_id).api_key == "sk-old"

    @pytest.mark.asyncio
    async def test_masked_and_empty_update_still_keep_the_key(self, isolated_config_root: Path):
        catalog = build_config_operation_catalog()
        created = await catalog.execute(
            "config.provider.create",
            {"name": "P", "base_url": "https://example.com/v1", "api_key": "sk-old"},
        )
        provider_id = created.payload["provider"]["id"]
        from lamtools_core.config.provider_store import MASKED_API_KEY, ProviderStore

        for value in (MASKED_API_KEY, "", "   "):
            result = await catalog.execute(
                "config.provider.update",
                {"provider_id": provider_id, "api_key": value},
            )
            assert result.status == "ok"
            assert ProviderStore().get_sync(provider_id).api_key == "sk-old"

    @pytest.mark.asyncio
    async def test_import_env_rejects_non_ascii_key(self, isolated_config_root: Path, monkeypatch):
        monkeypatch.setenv("LAMTOOLS_LLM_API_KEY", "sk-abc密钥")
        monkeypatch.setenv("LAMTOOLS_LLM_MODEL_ID", "some-model")
        catalog = build_config_operation_catalog()
        result = await catalog.execute("config.import_env", {})
        assert result.status == "error"
        assert "非 ASCII" in result.payload["error"]


class TestNonAsciiKeyIsNotRetried:
    def test_classify_unicode_errors_as_fatal(self):
        from lamtools_core.llm.retry import classify_model_error

        assert classify_model_error(UnicodeEncodeError("ascii", "x", 7, 14, "ordinal not in range(128)")) == "fatal"
        assert classify_model_error(UnicodeDecodeError("ascii", b"x", 0, 1, "ordinal not in range(128)")) == "fatal"
        assert classify_model_error(
            RuntimeError("'ascii' codec can't encode characters in position 7-14")
        ) == "fatal"
        assert classify_model_error(
            RuntimeError("non-ascii api key rejected")
        ) == "fatal"
        # A generic transient error must still be retryable.
        assert classify_model_error(RuntimeError("connection reset by peer")) == "retryable"

    def test_retry_loop_attempts_once_for_encoding_failures(self):
        from lamtools_core.llm.retry import run_with_model_retry

        calls = {"n": 0}

        async def operation():
            calls["n"] += 1
            raise UnicodeEncodeError("ascii", "x", 7, 14, "ordinal not in range(128)")

        async def sleep(_delay: float) -> None:
            raise AssertionError("an unbuildable request must not be retried")

        with pytest.raises(UnicodeEncodeError):
            asyncio.run(
                run_with_model_retry(operation, max_attempts=10, sleep=sleep)
            )
        assert calls["n"] == 1


class TestProviderErrorIdentity:
    def test_status_error_names_provider_address_and_model(self):
        from lamtools_core.cli import _http_provider_error

        error = _http_provider_error(
            403,
            '{"error":{"message":"Authentication failed"}}',
            {},
            provider_name="讯飞 MaaS",
            base_url="https://example.com/v1",
            model="glm-5.2",
            auth_scheme="Bearer",
        )
        message = str(error)
        assert "403" in message
        assert "provider=讯飞 MaaS" in message
        assert "base_url=https://example.com/v1" in message
        assert "model=glm-5.2" in message
        assert "auth=Bearer" in message
        assert "认证方式" in message
        assert getattr(error, "status_code", None) == 403

    def test_headers_reject_non_ascii_key_with_identity(self):
        from lamtools_core.cli import LLMConfig, CoreHttpLLMClient
        from lamtools_core.config.provider_store import ApiKeyValidationError

        client = CoreHttpLLMClient(
            config=LLMConfig(
                provider_name="P",
                provider_api_type="openai",
                base_url="https://example.com/v1",
                api_key="sk-abc密钥",
                model_record_id="m",
                model_id="m",
                display_name="M",
            ),
            adapter_profile={},
            thinking_enabled=False,
            thinking_budget=0,
            max_tokens=100,
            temperature=0.2,
        )
        with pytest.raises(ApiKeyValidationError) as excinfo:
            client._headers()
        message = str(excinfo.value)
        assert "provider=P" in message
        assert "model=m" in message

    def test_auth_scheme_reflects_protocol(self):
        from lamtools_core.cli import LLMConfig, CoreHttpLLMClient

        def _client(api_type: str, profile: dict) -> CoreHttpLLMClient:
            return CoreHttpLLMClient(
                config=LLMConfig(
                    provider_name="P",
                    provider_api_type=api_type,
                    base_url="https://example.com/v1",
                    api_key="sk-test",
                    model_record_id="m",
                    model_id="m",
                    display_name="M",
                ),
                adapter_profile=profile,
                thinking_enabled=False,
                thinking_budget=0,
                max_tokens=100,
                temperature=0.2,
            )

        assert _client("openai", {})._auth_scheme() == "Bearer"
        assert _client("anthropic", {})._auth_scheme() == "x-api-key"
        # Gemini is reached through the adapter profile's ``auth`` declaration
        # (``provider_api_type`` alone only distinguishes anthropic vs openai).
        assert _client("gemini", {"auth": "x-goog-api-key"})._auth_scheme() == "x-goog-api-key"
        # An explicit profile override wins over the protocol default.
        assert _client("openai", {"auth": "x-api-key"})._auth_scheme() == "x-api-key"


# ── 条 10: never change the model in use without the user asking ───────────


class TestNoGlobalDefaultModel:
    def test_provider_store_default_is_no_longer_runtime_resolution(self, isolated_config_root: Path):
        """``is_default`` may exist for compatibility but must not resolve models."""
        _write_provider(isolated_config_root, "p1", name="P1")
        _write_provider(isolated_config_root, "p2", name="P2")
        _write_model(isolated_config_root, "model-a", provider_id="p1", provider_name="P1", is_default=False)
        _write_model(isolated_config_root, "model-b", provider_id="p2", provider_name="P2", is_default=True)

        from lamtools_core.cli import load_llm_config

        with pytest.raises(ValueError):
            load_llm_config(model_ref="")
        # An explicit reference still works, whichever model is flagged default.
        assert load_llm_config(model_ref="model-a").model_record_id == "model-a"

    @pytest.mark.asyncio
    async def test_preset_provider_create_does_not_switch_the_session_model(self, isolated_config_root: Path):
        """The reported incident: adding a provider via a preset switched the
        model of an in-progress session with no prompt at all."""
        _write_provider(isolated_config_root, "p-a", name="Provider A")
        _write_model(isolated_config_root, "model-a", provider_id="p-a", provider_name="Provider A")
        ms.remember_scene_model(ms.SCENE_CHAT, "model-a")
        runtime_state_store = await _session_store_with_model("thread-1", "model-a")

        catalog = build_config_operation_catalog()
        created = await catalog.execute(
            "config.provider.create",
            {
                "name": "Provider B",
                "base_url": "https://b.example.com/v1",
                "api_key": "sk-b",
                "models": [
                    {"model_id": "model-b1", "display_name": "B1", "is_default": False},
                    {"model_id": "model-b2", "display_name": "B2", "is_default": True},
                ],
            },
        )
        assert created.status == "ok"

        # No global default was written, and no model's flag was cleared.
        from lamtools_core.config.model_store import ModelStore

        store = ModelStore()
        assert store.get_sync("model-a").is_default is False
        assert all(not model.is_default for model in store.list_sync())
        # No provider file/model file became the "global default".
        assert store.default_model_id_sync() == ""

        # The next turn of the running session still runs model-a.
        spec, error = await _inherit_turn_model(
            CoreAgentSpec(default_model=""),
            request=_turn_request(),
            runtime_state_store=runtime_state_store,
            model_provider=_routed_provider(),
        )
        assert error is None
        assert spec.default_model == "model-a"

    @pytest.mark.asyncio
    async def test_preset_seed_only_fills_empty_scenes(self, isolated_config_root: Path):
        """First-run seeding is allowed; it must never overwrite an existing model."""
        _write_provider(isolated_config_root, "p-a", name="Provider A")
        _write_provider(isolated_config_root, "p-b", name="Provider B")
        _write_model(isolated_config_root, "model-a", provider_id="p-a", provider_name="Provider A")
        _write_model(isolated_config_root, "model-b", provider_id="p-b", provider_name="Provider B")
        ms.remember_scene_model(ms.SCENE_CHAT, "model-a")

        catalog = build_config_operation_catalog()
        await catalog.execute(
            "config.provider.create",
            {
                "name": "Provider C",
                "base_url": "https://c.example.com/v1",
                "api_key": "sk-c",
                "models": [{"model_id": "model-c", "display_name": "C", "is_default": True}],
            },
        )

        # The chat scene keeps its model; the previously empty scenes got seeded
        # from the same first-run choice, so they are usable without borrowing
        # anything the user already chose.
        seeded = ms.scene_recent_models(ms.SCENE_STUDY)[0]
        assert seeded.endswith("model-c")
        assert ms.scene_recent_models(ms.SCENE_CHAT)[0] == "model-a"
        assert seeded != "model-a"
        assert ms.scene_recent_models(ms.SCENE_BACKGROUND)[0] == seeded

    @pytest.mark.asyncio
    async def test_no_inheritable_model_is_an_explicit_error(self, isolated_config_root: Path):
        spec, error = await _inherit_turn_model(
            CoreAgentSpec(default_model=""),
            request=_turn_request(),
            runtime_state_store=InMemoryRuntimeStateStore(),
            model_provider=_routed_provider(),
        )
        assert error is not None
        assert "请先添加供应商/模型" in error
        # Nothing was silently picked.
        assert spec.default_model == ""

    @pytest.mark.asyncio
    async def test_explicit_model_wins_and_is_remembered(self, isolated_config_root: Path):
        _write_provider(isolated_config_root, "p-a", name="Provider A")
        _write_model(isolated_config_root, "model-a", provider_id="p-a", provider_name="Provider A")

        request = _turn_request()
        request.payload["model_id"] = "model-a"
        spec, error = await _inherit_turn_model(
            CoreAgentSpec(default_model="model-stale"),
            request=request,
            runtime_state_store=InMemoryRuntimeStateStore(),
            model_provider=_routed_provider(),
        )
        assert error is None
        assert spec.default_model == "model-a"
        assert ms.scene_recent_models(ms.SCENE_CHAT)[0] == "model-a"

    @pytest.mark.asyncio
    async def test_explicit_unknown_model_is_an_explicit_error(self):
        request = _turn_request()
        request.payload["model_id"] = "no-such-model"
        spec, error = await _inherit_turn_model(
            CoreAgentSpec(default_model=""),
            request=request,
            runtime_state_store=InMemoryRuntimeStateStore(),
            model_provider=_routed_provider(),
        )
        assert error is not None
        assert "模型不存在" in error

    def test_scenes_do_not_share_models(self, isolated_config_root: Path):
        _write_provider(isolated_config_root, "p-a", name="Provider A")
        _write_provider(isolated_config_root, "p-b", name="Provider B")
        _write_model(isolated_config_root, "cheap-pet-model", provider_id="p-b", provider_name="Provider B")
        _write_model(isolated_config_root, "main-model", provider_id="p-a", provider_name="Provider A")

        ms.remember_scene_model(ms.SCENE_DESKTOP_PET, "cheap-pet-model")
        ms.remember_scene_model(ms.SCENE_CHAT, "main-model")

        assert ms.resolve_scene_model(ms.SCENE_CHAT).model_id == "main-model"
        assert ms.resolve_scene_model(ms.SCENE_DESKTOP_PET).model_id == "cheap-pet-model"
        # A scene with nothing remembered still refuses rather than borrowing.
        with pytest.raises(ms.ModelResolutionError):
            ms.resolve_scene_model(ms.SCENE_STUDY)

    def test_recent_model_records_are_bounded_and_deduped(self, isolated_config_root: Path):
        for index in range(ms.MAX_SCENE_RECENT + 4):
            ms.remember_scene_model(ms.SCENE_CHAT, f"m{index}")
        ms.remember_scene_model(ms.SCENE_CHAT, "m5")
        recent = ms.scene_recent_models(ms.SCENE_CHAT)
        assert recent[0] == "m5"
        assert len(recent) == ms.MAX_SCENE_RECENT
        assert recent.count("m5") == 1

    def test_deleted_inherited_model_falls_back_within_scene_and_notifies(self, isolated_config_root: Path):
        _write_provider(isolated_config_root, "p-a", name="Provider A")
        _write_model(isolated_config_root, "model-a", provider_id="p-a", provider_name="Provider A")
        _write_model(isolated_config_root, "model-b", provider_id="p-a", provider_name="Provider A")

        ms.remember_scene_model(ms.SCENE_CHAT, "model-b")
        ms.remember_scene_model(ms.SCENE_CHAT, "model-a")  # most recent first

        (isolated_config_root / "models" / "model-a.jsonc").unlink()

        resolution = ms.resolve_scene_model(ms.SCENE_CHAT)
        assert resolution.model_id == "model-b"
        assert resolution.replaced_from == "model-a"
        assert "model-a" in resolution.notice and "model-b" in resolution.notice

    def test_all_models_gone_reports_a_clear_error(self, isolated_config_root: Path):
        _write_provider(isolated_config_root, "p-a", name="Provider A")
        _write_model(isolated_config_root, "model-a", provider_id="p-a", provider_name="Provider A")
        ms.remember_scene_model(ms.SCENE_CHAT, "model-a")
        (isolated_config_root / "models" / "model-a.jsonc").unlink()

        with pytest.raises(ms.ModelResolutionError) as excinfo:
            ms.resolve_scene_model(ms.SCENE_CHAT)
        assert "没有可用模型" in str(excinfo.value)

    def test_model_with_broken_provider_is_not_usable(self, isolated_config_root: Path):
        _write_model(isolated_config_root, "orphan", provider_id="gone", provider_name="Gone")
        ms.remember_scene_model(ms.SCENE_CHAT, "orphan")
        with pytest.raises(ms.ModelResolutionError):
            ms.resolve_scene_model(ms.SCENE_CHAT)

    def test_plugin_scene_mapping_never_defaults_to_chat(self):
        study = SimpleNamespace(name="study", raw={})
        pet = SimpleNamespace(name="emotion-ball-pet", raw={})
        other = SimpleNamespace(name="some-plugin", raw={})
        declared = SimpleNamespace(name="some-plugin", raw={"model_scene": "study"})

        assert ms.scene_for_plugin(study) == ms.SCENE_STUDY
        assert ms.scene_for_plugin(pet) == ms.SCENE_DESKTOP_PET
        assert ms.scene_for_plugin(other) == ms.SCENE_BACKGROUND
        assert ms.scene_for_plugin(declared) == ms.SCENE_STUDY

    @pytest.mark.asyncio
    async def test_plugin_scene_view_keeps_late_bound_catalog_and_own_model(self, isolated_config_root: Path):
        """A plugin gets its own scene's model even though the operation catalog
        is attached to the originating context *after* the backend is created."""
        from lamtools_core.app.operation_catalog import OperationCatalog
        from lamtools_core.plugins.context import PluginContext

        _write_provider(isolated_config_root, "p-a", name="Provider A")
        _write_provider(isolated_config_root, "p-b", name="Provider B")
        _write_model(isolated_config_root, "main-model", provider_id="p-a", provider_name="Provider A")
        _write_model(isolated_config_root, "pet-model", provider_id="p-b", provider_name="Provider B")
        ms.remember_scene_model(ms.SCENE_CHAT, "main-model")
        ms.remember_scene_model(ms.SCENE_DESKTOP_PET, "pet-model")

        context = PluginContext(work_root=isolated_config_root)
        view = context.for_scene(ms.SCENE_DESKTOP_PET)
        assert view.model_id == "pet-model"
        assert view.model_id != ms.scene_recent_models(ms.SCENE_CHAT)[0]

        catalog = OperationCatalog()

        async def _op(request):
            from lamtools_core.app.operation_catalog import OperationResult

            return OperationResult(name=request.name, payload={"ok": True})

        catalog.register("demo.op", _op)
        # Attached after the view was derived, exactly like the real host flow.
        context.operation_catalog = catalog

        result = await view.operation_executor()("demo.op", {}, None)
        assert result.payload == {"ok": True}

    def test_plugin_scene_view_without_a_model_defers_to_an_explicit_error(self, isolated_config_root: Path):
        from lamtools_core.plugins.context import PluginContext

        view = PluginContext(work_root=isolated_config_root).for_scene(ms.SCENE_STUDY)
        assert view.model_id == ""
        assert view.parent is not None

    def test_group_membership_uses_concrete_models(self, isolated_config_root: Path):
        """A group is a list of concrete models: what is selected from it is
        exactly the record id sent to the runtime (no group-level rotation
        exists in Core today)."""
        from lamtools_core.config.model_group_store import ModelGroupStore

        _write_provider(isolated_config_root, "p-a", name="Provider A")
        _write_model(isolated_config_root, "model-a", provider_id="p-a", provider_name="Provider A")
        _write_model(isolated_config_root, "model-b", provider_id="p-a", provider_name="Provider A")

        store = ModelGroupStore()
        created = store.create("Team", model_ids=["model-a", "model-b"])
        group_id = created["group_id"]
        snapshot = store.snapshot(available_model_ids=["model-a", "model-b"])
        group = next(item for item in snapshot["groups"] if item["id"] == group_id)
        assert group["model_ids"] == ["model-a", "model-b"]

        # Whichever member the UI selects is the record id the runtime resolves.
        from lamtools_core.cli import load_llm_config

        assert load_llm_config(model_ref="model-a").model_record_id == "model-a"
        assert load_llm_config(model_ref="model-b").model_record_id == "model-b"


# ── 条 11: external config edits must be announced ─────────────────────────


class TestExternalConfigChangeNotices:
    def test_external_provider_edit_produces_notice(self, isolated_config_root: Path):
        from lamtools_core.config.provider_store import ProviderStore

        _write_provider(isolated_config_root, "p1", name="P1", base_url="https://a.example.com/v1")
        ProviderStore().list_sync()  # establishes the baseline
        assert drain_config_change_notices() == []

        _write_provider(isolated_config_root, "p1", name="P1", base_url="https://b.example.com/v1")
        store = ProviderStore()
        assert store.get_sync("p1").base_url == "https://b.example.com/v1"

        notices = drain_config_change_notices()
        assert len(notices) == 1
        assert notices[0]["kind"] == "provider"
        assert notices[0]["name"] == "p1"
        assert notices[0]["change"] == "modified"
        assert "p1" in notices[0]["message"]
        # Drained exactly once.
        assert drain_config_change_notices() == []

    def test_externally_added_and_removed_files_are_reported(self, isolated_config_root: Path):
        from lamtools_core.config.model_store import ModelStore

        _write_provider(isolated_config_root, "p1", name="P1")
        _write_model(isolated_config_root, "model-a", provider_id="p1", provider_name="P1")
        ModelStore().list_sync()

        _write_model(isolated_config_root, "model-b", provider_id="p1", provider_name="P1")
        ModelStore().list_sync()
        added = drain_config_change_notices()
        assert [notice["change"] for notice in added] == ["added"]

        (isolated_config_root / "models" / "model-b.jsonc").unlink()
        ModelStore().list_sync()
        removed = drain_config_change_notices()
        assert [notice["change"] for notice in removed] == ["removed"]
        assert removed[0]["name"] == "model-b"

    def test_external_settings_edit_produces_notice(self, isolated_config_root: Path):
        from lamtools_core.config.settings_store import get_setting

        get_setting("core.dreaming")
        isolated_config_root.mkdir(parents=True, exist_ok=True)
        settings_path = isolated_config_root / "settings.jsonc"
        settings_path.write_text(
            '{\n  "core": {\n    "dreaming": {"enabled": true}\n  }\n}\n',
            encoding="utf-8",
        )
        assert get_setting("core.dreaming") == {"enabled": True}
        notices = drain_config_change_notices()
        assert [notice["kind"] for notice in notices] == ["settings"]

    @pytest.mark.asyncio
    async def test_our_own_writes_are_not_reported(self, isolated_config_root: Path):
        from lamtools_core.config.provider_store import ProviderStore

        ProviderStore().list_sync()  # baseline
        catalog = build_config_operation_catalog()
        created = await catalog.execute(
            "config.provider.create",
            {"name": "Mine", "base_url": "https://mine.example.com/v1", "api_key": "sk-mine"},
        )
        assert created.status == "ok"
        ProviderStore().list_sync()
        assert drain_config_change_notices() == []

    @pytest.mark.asyncio
    async def test_notices_drain_rpc_returns_and_clears(self, isolated_config_root: Path):
        from lamtools_core.config.provider_store import ProviderStore

        _write_provider(isolated_config_root, "p1", name="P1")
        ProviderStore().list_sync()
        _write_provider(isolated_config_root, "p1", name="P1", api_key="sk-changed")
        ProviderStore().list_sync()

        catalog = build_config_operation_catalog()
        drained = await catalog.execute("config.notices.drain", {})
        assert drained.status == "ok"
        assert len(drained.payload["notices"]) == 1

        again = await catalog.execute("config.notices.drain", {})
        assert again.payload["notices"] == []

    def test_notice_carries_no_config_contents(self, isolated_config_root: Path):
        from lamtools_core.config.provider_store import ProviderStore

        _write_provider(isolated_config_root, "p1", name="P1", api_key="sk-secret-value")
        ProviderStore().list_sync()
        _write_provider(isolated_config_root, "p1", name="P1", api_key="sk-other-secret")
        ProviderStore().list_sync()

        notices = drain_config_change_notices()
        rendered = str(notices)
        assert "sk-secret-value" not in rendered
        assert "sk-other-secret" not in rendered
