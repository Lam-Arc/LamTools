"""Unit tests for Writer Core app factory adoption.

Verifies:
1. GET /api/health returns 200 with status/app and Writer service status.
2. GET /api/members returns 200 and contains member id "writer"
3. GET /api/core/sessions returns 200 (Writer-specific Core adapter mounted)
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base, get_db
from app.main import app


@pytest.fixture
def client(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'main-core-app.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def setup_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(setup_db())

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        test_client.close()
        asyncio.run(engine.dispose())


def test_health_returns_ok_with_app_key(client):
    """GET /api/health returns 200 with the Writer health payload."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in {"ok", "degraded"}
    assert data["app"] == "LamWriter"
    assert data["writer_service"] in {"ok", "unavailable"}


def test_members_contains_writer(client):
    """GET /api/members returns 200 and contains member id writer."""
    response = client.get("/api/members")
    assert response.status_code == 200
    data = response.json()
    ids = [m["id"] for m in data]
    assert "writer" in ids


def test_core_sessions_endpoint_exists(client):
    """GET /api/core/sessions returns 200 -- Writer Core adapter is mounted."""
    response = client.get("/api/core/sessions")
    assert response.status_code == 200


def test_legacy_runtime_events_endpoint_is_not_mounted(client):
    response = client.get("/api/sessions/missing/runtime-events")
    assert response.status_code == 404
