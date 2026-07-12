"""Core HTTP Writer unit tests -- isolated SQLite test app.

Tests cover:
1. /api/health still returns {"status":"ok","app":"LamWriter"}
2. /api/core/sessions: create, list, get, patch
3. PATCH /api/core/sessions/{id} updates title/status/metadata
4. Writer /api/core message/event routes are not mounted; app-server snapshot is the GUI message source
5. Existing /api/sessions still works in same test app, but legacy message routes are not mounted
6. Provider mapping never exposes raw api_key or any substring
7. /api/core/usage returns [] and /api/core/usage/total returns zero cost

All tests use a real in-memory SQLite database with dependency override.
No mocks.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db, writer_write_coordinator
from app.models.llm_config import LLMProvider, LLMModel
from app.shared_config_database import get_shared_config_db
from app.routers.config import router as config_router
from app.routers.session import router as session_router
from app.routers.core_http import get_writer_write, router as core_http_router
from lamtools_core.app import create_app
from lamtools_core.config.shared_database import init_shared_config_schema
from lamtools_core.member import MemberManifest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures -- isolated test app with real SQLite
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def test_app_and_client():
    """Build a test app with real SQLite DB and both /api and /api/core routers."""
    # Keep TemporaryDirectory alive for the whole fixture lifespan.
    # If we let it close before yield, Windows cannot delete test.db
    # while SQLite still holds the file.
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test.db"
    shared_db_path = Path(tmp_dir) / "shared.db"

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        future=True,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    shared_engine = create_async_engine(
        f"sqlite+aiosqlite:///{shared_db_path}",
        future=True,
    )
    shared_session_factory = async_sessionmaker(shared_engine, expire_on_commit=False)

    # Create tables via a dedicated event loop (then close it)
    init_loop = asyncio.new_event_loop()
    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await init_shared_config_schema(shared_engine)
    init_loop.run_until_complete(_init())
    init_loop.close()

    def _health_payload():
        return {"status": "ok", "app": "LamWriter"}

    manifest = MemberManifest(
        id="writer",
        name="LamWriter",
        version="0.1.0",
        capabilities=["session", "project", "config", "attachment"],
        default_routes={
            "/api": "Writer session, project, config, attachment routers",
            "/api/core": "Core HTTP adapter",
        },
    )

    app = create_app(
        members=[manifest],
        title="LamWriter",
        version="0.1.0",
        on_startup=[],
        on_shutdown=[],
        enable_core_routes=False,
        health_payload=_health_payload,
    )

    # Override get_db to use test SQLite
    async def _override_get_db():
        async with session_factory() as db:
            yield db

    async def _override_get_shared_config_db():
        async with shared_session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_shared_config_db] = _override_get_shared_config_db
    app.dependency_overrides[get_writer_write] = lambda: writer_write_coordinator(session_factory).run

    # Mount Writer routers
    app.include_router(session_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(core_http_router, prefix="/api/core")

    client = TestClient(app)
    yield client

    # Cleanup: dispose engine first, then remove temp dir
    cleanup_loop = asyncio.new_event_loop()
    cleanup_loop.run_until_complete(engine.dispose())
    cleanup_loop.run_until_complete(shared_engine.dispose())
    cleanup_loop.close()
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def client(test_app_and_client):
    return test_app_and_client


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_writer_payload(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data == {"status": "ok", "app": "LamWriter"}


# ---------------------------------------------------------------------------
# Core sessions CRUD
# ---------------------------------------------------------------------------

class TestCoreSessionsCRUD:
    def test_list_sessions_empty(self, client):
        response = client.get("/api/core/sessions")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_session(self, client):
        response = client.post(
            "/api/core/sessions",
            json={"title": "Core Test Session", "work_root": "/tmp/test-work"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["member_id"] == "writer"
        assert data["title"] == "Core Test Session"
        assert data["status"] == "idle"
        assert data["id"]
        # metadata preserves Writer fields
        assert data["metadata"]["work_root"].replace("\\", "/").endswith("/tmp/test-work")
        assert data["metadata"]["phase"] == "idle"
        assert data["metadata"]["mode"] == "EXECUTE"

    def test_generic_session_create_rejects_client_project_id(self, client):
        response = client.post(
            "/api/core/sessions",
            json={"title": "Invalid project session", "project_id": "missing-project"},
        )
        assert response.status_code == 422

    def test_get_session(self, client):
        # Create first
        create_resp = client.post(
            "/api/core/sessions",
            json={"title": "Get Test"},
        )
        sid = create_resp.json()["id"]

        response = client.get(f"/api/core/sessions/{sid}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sid
        assert data["title"] == "Get Test"

    def test_get_session_404(self, client):
        response = client.get("/api/core/sessions/nonexistent-id")
        assert response.status_code == 404

    def test_list_sessions_after_create(self, client):
        client.post("/api/core/sessions", json={"title": "List Test 1"})
        client.post("/api/core/sessions", json={"title": "List Test 2"})
        response = client.get("/api/core/sessions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 2
        titles = [s["title"] for s in data]
        assert "List Test 1" in titles
        assert "List Test 2" in titles


class TestCoreSessionPatch:
    def test_patch_title(self, client):
        create_resp = client.post(
            "/api/core/sessions",
            json={"title": "Before Patch"},
        )
        sid = create_resp.json()["id"]

        response = client.patch(
            f"/api/core/sessions/{sid}",
            json={"title": "After Patch"},
        )
        assert response.status_code == 200
        assert response.json()["title"] == "After Patch"

    def test_patch_status(self, client):
        create_resp = client.post(
            "/api/core/sessions",
            json={"title": "Status Patch"},
        )
        sid = create_resp.json()["id"]

        response = client.patch(
            f"/api/core/sessions/{sid}",
            json={"status": "completed"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

    def test_patch_metadata_merge(self, client):
        create_resp = client.post(
            "/api/core/sessions",
            json={"title": "Metadata Patch"},
        )
        sid = create_resp.json()["id"]

        response = client.patch(
            f"/api/core/sessions/{sid}",
            json={"metadata": {"custom_key": "custom_value"}},
        )
        assert response.status_code == 200
        data = response.json()
        # Merged: original Writer fields + new custom_key
        assert data["metadata"]["custom_key"] == "custom_value"
        # Writer fields still preserved
        assert "phase" in data["metadata"]

    def test_patch_404(self, client):
        response = client.patch(
            "/api/core/sessions/nonexistent-id",
            json={"title": "Nope"},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Removed Writer Core message/event routes
# ---------------------------------------------------------------------------

class TestRemovedCoreMessageEventRoutes:
    def test_core_messages_route_is_not_mounted(self, client):
        create_resp = client.post(
            "/api/core/sessions",
            json={"title": "Removed Message Route Test"},
        )
        sid = create_resp.json()["id"]

        response = client.get(f"/api/core/sessions/{sid}/messages")
        assert response.status_code == 404

    def test_core_message_create_route_is_not_mounted(self, client):
        create_resp = client.post(
            "/api/core/sessions",
            json={"title": "Removed Message Create Route Test"},
        )
        sid = create_resp.json()["id"]

        response = client.post(
            f"/api/core/sessions/{sid}/messages",
            json={"role": "user", "content": "not accepted"},
        )
        assert response.status_code == 404

    def test_core_events_route_is_not_mounted(self, client):
        response = client.get("/api/core/sessions/no-such-id/events")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Existing /api/sessions still works
# ---------------------------------------------------------------------------

class TestExistingSessionRoutes:
    def test_existing_api_sessions_create(self, client):
        response = client.post(
            "/api/sessions",
            json={"title": "Legacy Route Test"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Legacy Route Test"
        assert "id" in data

    def test_existing_api_sessions_list(self, client):
        response = client.get("/api/sessions")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_existing_api_session_messages_route_is_not_mounted(self, client):
        create_resp = client.post(
            "/api/sessions",
            json={"title": "Removed Legacy Message Route Test"},
        )
        sid = create_resp.json()["id"]

        get_response = client.get(f"/api/sessions/{sid}/messages")
        assert get_response.status_code == 404

        post_response = client.post(
            f"/api/sessions/{sid}/messages",
            json={"role": "user", "content": "not accepted"},
        )
        assert post_response.status_code == 404


# ---------------------------------------------------------------------------
# Provider mapping -- no raw api_key exposure
# ---------------------------------------------------------------------------

class TestProviderMapping:
    def test_adapter_profiles_endpoint_exposes_builtin_profiles(self, client):
        response = client.get("/api/config/adapter-profiles")
        assert response.status_code == 200
        profiles = response.json()
        ids = {item["id"] for item in profiles}
        assert "openai-chat" in ids
        assert "xfyun-coding-plan" in ids
        xfyun = next(item for item in profiles if item["id"] == "xfyun-coding-plan")
        assert xfyun["protocol"] == "openai-chat-completions"
        assert any("xf-yun" in pattern for pattern in xfyun["match_base_url"])

    def test_provider_never_exposes_raw_api_key(self, client):
        """Provider list must not contain raw api_key or any substring of it."""
        # Create a provider with a distinctive secret
        secret_key = "sk-test-secret-key-abc123XYZ789-do-not-expose"
        create_resp = client.post(
            "/api/config/providers",
            json={
                "name": "Secret Provider",
                "api_type": "openai",
                "base_url": "https://api.example.com/v1",
                "api_key": secret_key,
                "is_default": True,
            },
        )
        assert create_resp.status_code == 200

        # Check /api/core/providers
        response = client.get("/api/core/providers")
        assert response.status_code == 200
        providers = response.json()
        assert len(providers) >= 1

        for p in providers:
            # api_key_ref must be a safe reference, not a substring of the raw key
            ref = p.get("api_key_ref", "")
            assert secret_key not in ref
            assert "abc123" not in ref
            assert "XYZ789" not in ref
            assert "sk-test" not in ref
            # Must not have a raw "api_key" field at all
            assert "api_key" not in p
            # api_key_ref format: "provider:<id>:api_key" or empty
            if ref:
                assert ref.startswith("provider:")

    def test_default_provider_no_raw_key(self, client):
        """GET /api/core/providers/default must also mask the key."""
        response = client.get("/api/core/providers/default?kind=openai")
        # 404 is acceptable if no default exists; skip if so
        if response.status_code == 404:
            return
        assert response.status_code == 200
        data = response.json()
        ref = data.get("api_key_ref", "")
        # No substring of any plausible secret
        assert "sk-test-secret" not in ref
        # No raw "api_key" field
        assert "api_key" not in data


# ---------------------------------------------------------------------------
# Usage routes -- stable fallback
# ---------------------------------------------------------------------------

class TestUsageRoutes:
    def test_usage_returns_empty(self, client):
        response = client.get("/api/core/usage")
        assert response.status_code == 200
        assert response.json() == []

    def test_usage_total_returns_zero(self, client):
        response = client.get("/api/core/usage/total")
        assert response.status_code == 200
        data = response.json()
        assert data["total_cost"] == 0.0
        assert data["currency"] == "USD"

    def test_usage_total_with_params(self, client):
        response = client.get("/api/core/usage/total?member_id=writer&currency=EUR")
        assert response.status_code == 200
        data = response.json()
        assert data["total_cost"] == 0.0
        assert data["currency"] == "EUR"
