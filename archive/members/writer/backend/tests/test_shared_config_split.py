from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.app_setting import AppSetting
from app.models.llm_config import LLMModel, LLMProvider
from app.models.session import WriterSession
from app.app_server.operations import handle_config_provider_create_operation
from app.routers.core_http import list_providers as list_core_providers
from app.routers.config import (
    SettingUpdate,
    get_runtime_capabilities,
    put_app_setting,
)
from app.services.app_settings import (
    get_app_setting_value,
    move_writer_settings_from_shared_to_writer,
    update_app_setting_value,
)
from app.services.config_read import list_model_configs, list_provider_configs
from app.services.config_write import create_model_config, create_provider_config
from app.services.llm_config_service import resolve_llm_config, set_route_model
from app.services.runtime_capabilities import runtime_controls
from app.shared_config_database import migrate_legacy_shared_config
from app.config import Settings
import app.services.writer_service as writer_service_module
from lamtools_core.config.shared_database import AppSetting as SharedAppSetting
from lamtools_core.config.shared_database import init_shared_config_schema
from lamtools_core.kernel import KernelResult


async def _table_names(db) -> set[str]:
    result = await db.execute(text("select name from sqlite_master where type='table'"))
    return {str(row[0]) for row in result.fetchall()}


@pytest.mark.asyncio
async def test_provider_and_model_config_use_shared_db_not_writer_db(tmp_path):
    writer_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer.db'}", future=True)
    shared_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'shared.db'}", future=True)
    writer_session = async_sessionmaker(writer_engine, expire_on_commit=False)
    shared_session = async_sessionmaker(shared_engine, expire_on_commit=False)
    try:
        async with writer_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await init_shared_config_schema(shared_engine)

        async with shared_session() as shared_db:
            provider = await create_provider_config(
                shared_db,
                {
                    "name": "Shared Provider",
                    "api_type": "openai",
                    "base_url": "https://shared.example/v1",
                    "api_key": "sk-shared-secret",
                },
            )
            model = await create_model_config(
                shared_db,
                {
                    "provider_id": provider["id"],
                    "model_id": "shared-model",
                    "display_name": "Shared Model",
                },
            )
            await set_route_model(shared_db, "writer", model["id"])
            await shared_db.commit()

        async with shared_session() as shared_db:
            providers = await list_provider_configs(shared_db)
            models = await list_model_configs(shared_db)
            resolved = await resolve_llm_config(shared_db, "writer")
        async with writer_session() as writer_db:
            writer_tables = await _table_names(writer_db)

        assert [row["id"] for row in providers] == [provider["id"]]
        assert [row["id"] for row in models] == [model["id"]]
        assert resolved is not None
        assert resolved.model.model_id == "shared-model"
        assert "llm_providers" not in writer_tables
        assert "llm_models" not in writer_tables
    finally:
        await writer_engine.dispose()
        await shared_engine.dispose()


@pytest.mark.asyncio
async def test_legacy_provider_config_migrates_to_shared_db_not_writer_runtime(tmp_path):
    legacy_dir = tmp_path / "legacy" / "LamWriter"
    legacy_dir.mkdir(parents=True)
    legacy_db = legacy_dir / "lamwriter.db"
    with sqlite3.connect(legacy_db) as conn:
        conn.executescript(
            """
            create table llm_providers (
                id text primary key,
                name text,
                api_type text,
                base_url text,
                api_key text,
                is_default integer,
                extra text,
                created_at text,
                updated_at text
            );
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
                is_default integer,
                extra text,
                created_at text,
                updated_at text
            );
            create table app_settings (namespace text primary key, value text, updated_at text);
            insert into llm_providers values (
                'legacy-provider', 'Legacy Provider', 'openai', 'https://legacy.example/v1',
                'sk-legacy', 0, null, '2026-01-01', '2026-01-01'
            );
            insert into llm_models values (
                'legacy-model-row', 'legacy-provider', 'legacy-model', 'Legacy Model',
                128000, 4096, 1, 10000, 0.7, 0, null, '2026-01-01', '2026-01-01'
            );
            insert into app_settings values (
                'lamwriter.modelRouting',
                '{"routes":{"writer":{"mode":"model","model_id":"legacy-model-row"}}}',
                '2026-01-01'
            );
            insert into app_settings values ('core.runtimeControls', '{"tools":{}}', '2026-01-01');
            insert into app_settings values ('writer.runtimeControls', '{"tools":{"write_file":true}}', '2026-01-01');
            """
        )

    shared_db_path = tmp_path / "shared.db"
    shared_engine = create_async_engine(f"sqlite+aiosqlite:///{shared_db_path}", future=True)
    shared_session = async_sessionmaker(shared_engine, expire_on_commit=False)
    try:
        await init_shared_config_schema(shared_engine)

        migrated = migrate_legacy_shared_config(shared_db_path, legacy_db)
        skipped = migrate_legacy_shared_config(shared_db_path, legacy_db)

        async with shared_session() as shared_db:
            provider = await shared_db.get(LLMProvider, "legacy-provider")
            model = await shared_db.get(LLMModel, "legacy-model-row")
            routing = await shared_db.get(SharedAppSetting, "lamwriter.modelRouting")
            core_controls = await shared_db.get(SharedAppSetting, "core.runtimeControls")
            writer_controls = await shared_db.get(SharedAppSetting, "writer.runtimeControls")

        assert migrated is True
        assert skipped is False
        assert provider is not None
        assert provider.api_key == "sk-legacy"
        assert model is not None
        assert model.model_id == "legacy-model"
        assert routing is not None
        assert core_controls is not None
        assert writer_controls is None
    finally:
        await shared_engine.dispose()


@pytest.mark.asyncio
async def test_writer_runtime_resolves_llm_from_shared_config_not_writer_db(tmp_path, monkeypatch):
    writer_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-runtime.db'}", future=True)
    shared_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'shared-runtime.db'}", future=True)
    writer_session = async_sessionmaker(writer_engine, expire_on_commit=False)
    shared_session = async_sessionmaker(shared_engine, expire_on_commit=False)
    captured: dict[str, str] = {}

    def fake_build_llm_client(resolved, **kwargs):
        captured["model"] = resolved.model.model_id
        captured["provider_id"] = resolved.provider.id
        return SimpleNamespace(model_id=resolved.model.model_id)

    async def fake_run_core_kernel(**kwargs):
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="shared-config-runtime-run",
            decision="done",
            message="ok",
            metadata={"core_events": [], "steps_count": 0},
        )

    monkeypatch.setattr(writer_service_module, "build_llm_client", fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", fake_run_core_kernel)
    try:
        async with writer_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await init_shared_config_schema(shared_engine)

        async with shared_session() as shared_db:
            provider = await create_provider_config(
                shared_db,
                {
                    "name": "Runtime Shared Provider",
                    "api_type": "openai",
                    "base_url": "https://runtime.example/v1",
                    "api_key": "sk-runtime-shared-secret",
                },
            )
            model = await create_model_config(
                shared_db,
                {
                    "provider_id": provider["id"],
                    "model_id": "runtime-shared-model",
                    "display_name": "Runtime Shared Model",
                },
            )
            await set_route_model(shared_db, "writer", model["id"])
            await shared_db.commit()

        service = writer_service_module.writer_orchestrate(
            Settings(
                data_dir=str(tmp_path / "data"),
                database_url=f"sqlite+aiosqlite:///{tmp_path / 'writer-runtime.db'}",
            ),
            config_session_factory=shared_session,
        )

        async with writer_session() as writer_db:
            writer_db.add(
                WriterSession(
                    id="shared-runtime-session",
                    title="Shared Runtime",
                    work_root=str(tmp_path / "workspace"),
                )
            )
            await writer_db.commit()
            assert "llm_providers" not in await _table_names(writer_db)

            await service["run_turn"](writer_db, "shared-runtime-session", "hello")

        assert captured == {
            "model": "runtime-shared-model",
            "provider_id": provider["id"],
        }
    finally:
        await writer_engine.dispose()
        await shared_engine.dispose()


@pytest.mark.asyncio
async def test_core_http_provider_adapter_reads_shared_config_not_writer_db(tmp_path):
    writer_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-core-http.db'}", future=True)
    shared_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'shared-core-http.db'}", future=True)
    writer_session = async_sessionmaker(writer_engine, expire_on_commit=False)
    shared_session = async_sessionmaker(shared_engine, expire_on_commit=False)
    try:
        async with writer_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await init_shared_config_schema(shared_engine)

        async with shared_session() as shared_db:
            provider = await create_provider_config(
                shared_db,
                {
                    "name": "Shared Core Provider",
                    "api_type": "openai",
                    "base_url": "https://core.example/v1",
                    "api_key": "sk-shared-core-secret",
                },
            )
            model = await create_model_config(
                shared_db,
                {
                    "provider_id": provider["id"],
                    "model_id": "shared-core-model",
                    "display_name": "Shared Core Model",
                },
            )
            await set_route_model(shared_db, "writer", model["id"])
            await shared_db.commit()

        async with writer_session() as writer_db, shared_session() as shared_db:
            providers = await list_core_providers(
                limit=50,
                offset=0,
                config_db=shared_db,
            )
            writer_tables = await _table_names(writer_db)

        assert "llm_providers" not in writer_tables
        assert providers == [
            {
                "id": provider["id"],
                "kind": "openai",
                "name": "Shared Core Provider",
                "base_url": "https://core.example/v1",
                "api_key_ref": f"provider:{provider['id']}:api_key",
                "default_model": "shared-core-model",
                "models": ["shared-core-model"],
                "metadata": {},
                "enabled": True,
            }
        ]
    finally:
        await writer_engine.dispose()
        await shared_engine.dispose()


@pytest.mark.asyncio
async def test_config_routes_use_shared_settings_and_writer_overlay(tmp_path):
    writer_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-route.db'}", future=True)
    shared_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'shared-route.db'}", future=True)
    writer_session = async_sessionmaker(writer_engine, expire_on_commit=False)
    shared_session = async_sessionmaker(shared_engine, expire_on_commit=False)
    try:
        async with writer_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await init_shared_config_schema(shared_engine)

        async with writer_session() as writer_db, shared_session() as shared_db:
            await put_app_setting(
                "core.runtimeControls",
                SettingUpdate(value={"tools": {"run_command": True}}),
                db=writer_db,
                shared_db=shared_db,
            )
            await put_app_setting(
                "writer.runtimeControls",
                SettingUpdate(value={"tools": {"run_command": False}}),
                db=writer_db,
                shared_db=shared_db,
            )
            capabilities = await get_runtime_capabilities(
                work_root=None,
                db=writer_db,
                shared_db=shared_db,
            )

        async with writer_session() as writer_db, shared_session() as shared_db:
            assert await shared_db.get(AppSetting, "core.runtimeControls") is not None
            assert await writer_db.get(AppSetting, "core.runtimeControls") is None
            assert await writer_db.get(AppSetting, "writer.runtimeControls") is not None
            assert await shared_db.get(AppSetting, "writer.runtimeControls") is None
        run_command = next(tool for tool in capabilities.tools if tool.name == "run_command")
        assert run_command.enabled is False
    finally:
        await writer_engine.dispose()
        await shared_engine.dispose()


@pytest.mark.asyncio
async def test_app_server_provider_config_uses_shared_db_not_writer_db(tmp_path):
    writer_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-app-server.db'}", future=True)
    shared_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'shared-app-server.db'}", future=True)
    writer_session = async_sessionmaker(writer_engine, expire_on_commit=False)
    shared_session = async_sessionmaker(shared_engine, expire_on_commit=False)
    try:
        async with writer_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await init_shared_config_schema(shared_engine)

        outcome = await handle_config_provider_create_operation(
            request_id=1,
            params={
                "name": "Shared Provider",
                "base_url": "https://shared.example/v1",
                "api_key": "sk-shared-secret",
            },
            session_factory=writer_session,
            config_session_factory=shared_session,
        )
        provider_id = outcome.response["result"]["provider"]["id"]

        async with writer_session() as writer_db, shared_session() as shared_db:
            assert "llm_providers" not in await _table_names(writer_db)
            assert await shared_db.get(LLMProvider, provider_id) is not None
    finally:
        await writer_engine.dispose()
        await shared_engine.dispose()


@pytest.mark.asyncio
async def test_app_server_provider_config_requires_shared_config_session(tmp_path):
    writer_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-no-shared.db'}", future=True)
    writer_session = async_sessionmaker(writer_engine, expire_on_commit=False)
    try:
        async with writer_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        outcome = await handle_config_provider_create_operation(
            request_id=1,
            params={
                "name": "Wrong DB Provider",
                "base_url": "https://wrong-db.example/v1",
                "api_key": "sk-wrong-db-secret",
            },
            session_factory=writer_session,
        )

        assert outcome.response["error"]["message"] == "shared config session is required"
        async with writer_session() as writer_db:
            assert "llm_providers" not in await _table_names(writer_db)
    finally:
        await writer_engine.dispose()


@pytest.mark.asyncio
async def test_settings_classification_sends_core_settings_to_shared_and_writer_ui_to_writer(tmp_path):
    writer_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-settings.db'}", future=True)
    shared_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'shared-settings.db'}", future=True)
    writer_session = async_sessionmaker(writer_engine, expire_on_commit=False)
    shared_session = async_sessionmaker(shared_engine, expire_on_commit=False)
    try:
        async with writer_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await init_shared_config_schema(shared_engine)

        async with writer_session() as writer_db, shared_session() as shared_db:
            await update_app_setting_value(
                writer_db,
                "core.runtimeControls",
                {"command_policies": {"dangerous": "ask_user"}},
                shared_db=shared_db,
            )
            await update_app_setting_value(
                writer_db,
                "writer.ui",
                {"density": "compact"},
                shared_db=shared_db,
            )

        async with writer_session() as writer_db, shared_session() as shared_db:
            shared_runtime = await shared_db.get(AppSetting, "core.runtimeControls")
            writer_runtime = await writer_db.get(AppSetting, "core.runtimeControls")
            writer_ui = await writer_db.get(AppSetting, "writer.ui")
            shared_ui = await shared_db.get(AppSetting, "writer.ui")
            runtime_payload = await get_app_setting_value(
                writer_db,
                "core.runtimeControls",
                shared_db=shared_db,
            )

        assert shared_runtime is not None
        assert shared_runtime.value == {"command_policies": {"dangerous": "ask_user"}}
        assert writer_runtime is None
        assert writer_ui is not None
        assert writer_ui.value == {"density": "compact"}
        assert shared_ui is None
        assert runtime_payload["value"]["command_policies"]["dangerous"] == "ask_user"
    finally:
        await writer_engine.dispose()
        await shared_engine.dispose()


@pytest.mark.asyncio
async def test_writer_only_settings_move_from_shared_to_writer_db(tmp_path):
    writer_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-move-settings.db'}", future=True)
    shared_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'shared-move-settings.db'}", future=True)
    writer_session = async_sessionmaker(writer_engine, expire_on_commit=False)
    shared_session = async_sessionmaker(shared_engine, expire_on_commit=False)
    try:
        async with writer_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await init_shared_config_schema(shared_engine)

        async with shared_session() as shared_db:
            shared_db.add_all(
                [
                    SharedAppSetting(namespace="core.runtimeControls", value={"tools": {"run_command": True}}),
                    SharedAppSetting(namespace="lamwriter.runtimeControls", value={"tools": {"write_file": False}}),
                    SharedAppSetting(namespace="writer.ui", value={"density": "compact"}),
                ]
            )
            await shared_db.commit()

        async with writer_session() as writer_db, shared_session() as shared_db:
            moved = await move_writer_settings_from_shared_to_writer(writer_db, shared_db)

        async with writer_session() as writer_db, shared_session() as shared_db:
            writer_legacy = await writer_db.get(AppSetting, "lamwriter.runtimeControls")
            writer_ui = await writer_db.get(AppSetting, "writer.ui")
            shared_core = await shared_db.get(SharedAppSetting, "core.runtimeControls")
            shared_legacy = await shared_db.get(SharedAppSetting, "lamwriter.runtimeControls")
            shared_ui = await shared_db.get(SharedAppSetting, "writer.ui")

        assert set(moved) == {"lamwriter.runtimeControls", "writer.ui"}
        assert writer_legacy is not None
        assert writer_legacy.value == {"tools": {"write_file": False}}
        assert writer_ui is not None
        assert writer_ui.value == {"density": "compact"}
        assert shared_core is not None
        assert shared_legacy is None
        assert shared_ui is None
    finally:
        await writer_engine.dispose()
        await shared_engine.dispose()


@pytest.mark.asyncio
async def test_runtime_controls_merge_core_base_with_writer_overlay(tmp_path):
    writer_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-permissions.db'}", future=True)
    shared_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'shared-permissions.db'}", future=True)
    writer_session = async_sessionmaker(writer_engine, expire_on_commit=False)
    shared_session = async_sessionmaker(shared_engine, expire_on_commit=False)
    try:
        async with writer_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await init_shared_config_schema(shared_engine)

        async with writer_session() as writer_db, shared_session() as shared_db:
            shared_db.add(
                AppSetting(
                    namespace="core.runtimeControls",
                    value={
                        "tools": {"run_command": True, "write_file": True},
                        "command_policies": {"regular": "auto_allow", "dangerous": "ask_user"},
                    },
                )
            )
            writer_db.add(
                AppSetting(
                    namespace="writer.runtimeControls",
                    value={
                        "tools": {"write_file": False, "writer_only_tool": True},
                        "command_policies": {"regular": "ask_user"},
                    },
                )
            )
            await shared_db.commit()
            await writer_db.commit()

        async with writer_session() as writer_db, shared_session() as shared_db:
            controls = await runtime_controls(writer_db, shared_db=shared_db)

        assert controls["tools"]["run_command"] is True
        assert controls["tools"]["write_file"] is False
        assert controls["tools"]["writer_only_tool"] is True
        assert controls["command_policies"] == {"regular": "ask_user", "dangerous": "ask_user"}
    finally:
        await writer_engine.dispose()
        await shared_engine.dispose()
