"""Regression tests for the loopback origin allow-list and SPA containment.

Audit 03 S1: the Core HTTP/WS surface was zero-auth with CORS "*" +
credentials and a SPA fallback route that joined client-controlled path
segments without a containment check — any web page could drive the local
agent and read arbitrary local files.
"""

from __future__ import annotations

import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lamtools_core.app import CoreAppSnapshotProjector, OperationCatalog
from lamtools_core.app.event_store import SqlAlchemyAppEventStore
from lamtools_core.app.factory import add_spa_fallback, create_app
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_operations import CoreLiveContext
from lamtools_core.app.live_router import create_core_live_router
from lamtools_core.app.security import is_allowed_origin
from lamtools_core.app.snapshot_store import SqlAlchemyThreadSnapshotStore


class _Base(DeclarativeBase):
    pass


class _AppEventRow(_Base):
    __tablename__ = "test_security_app_events"
    __table_args__ = (
        UniqueConstraint("thread_id", "seq", name="uq_test_security_app_events_thread_seq"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parent_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    client_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(String, nullable=False, default="{}")


class _ThreadSnapshotRow(_Base):
    __tablename__ = "test_security_thread_snapshots"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_json: Mapped[str] = mapped_column(String, nullable=False, default="{}")


class _SnapshotItemRow(_Base):
    __tablename__ = "test_security_snapshot_items"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[str] = mapped_column(String, nullable=False, default="{}")


def _make_spa_app(tmp_path: pathlib.Path) -> TestClient:
    (tmp_path / "index.html").write_text("<html>index</html>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("SECRET", encoding="utf-8")
    app = create_app(frontend_dir=str(tmp_path))
    add_spa_fallback(app, tmp_path)
    return TestClient(app)


# --- origin allow-list ------------------------------------------------------

def test_is_allowed_origin_units() -> None:
    assert is_allowed_origin(None) is True
    assert is_allowed_origin("") is True
    assert is_allowed_origin("http://localhost:5172") is True
    assert is_allowed_origin("http://127.0.0.1:5173") is True
    assert is_allowed_origin("tauri://localhost") is True
    assert is_allowed_origin("http://tauri.localhost") is True
    assert is_allowed_origin("TAURI://LOCALHOST/") is True  # case/trailing slash
    assert is_allowed_origin("http://evil.example") is False
    assert is_allowed_origin("http://localhost:9999") is False


def test_http_origin_check(tmp_path: pathlib.Path) -> None:
    client = _make_spa_app(tmp_path)
    # Non-browser clients (no Origin header) stay trusted.
    assert client.get("/api/health").status_code == 200
    # Allowed dev/Tauri origins pass.
    assert client.get("/api/health", headers={"Origin": "http://localhost:5173"}).status_code == 200
    # Anything else is rejected on every path, not just /api.
    assert client.get("/api/health", headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.get("/", headers={"Origin": "http://evil.example"}).status_code == 403


def test_websocket_origin_rejected(tmp_path: pathlib.Path) -> None:
    """WS handshakes with a foreign Origin must be rejected (1008) before accept.

    WebSocket is not subject to CORS, so this check is the only thing keeping
    a malicious page from opening a raw socket to the loopback backend.
    """

    async def make_context() -> CoreLiveContext:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'origin.db'}", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(_Base.metadata.create_all)
        return CoreLiveContext(
            session_factory=async_sessionmaker(engine, expire_on_commit=False),
            event_store=SqlAlchemyAppEventStore(_AppEventRow, protocol_version="core.app_server.v1"),
            snapshot_store=SqlAlchemyThreadSnapshotStore(
                _ThreadSnapshotRow,
                item_model=_SnapshotItemRow,
                projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
            ),
            operations=OperationCatalog(),
            hub=CoreAppEventHub(),
        )

    app = FastAPI()
    app.include_router(create_core_live_router(make_context), prefix="/api/core")
    client = TestClient(app)

    with pytest.raises(Exception):  # starlette WebSocketDisconnect on close 1008
        with client.websocket_connect(
            "/api/core/app-server", headers={"Origin": "http://evil.example"}
        ):
            pass  # pragma: no cover
    # Non-browser WS client (no Origin) is accepted and can initialize.
    with client.websocket_connect("/api/core/app-server") as websocket:
        websocket.send_json({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "test"}}})
        initialized = websocket.receive_json()
        assert initialized["result"]["protocolVersion"] == "core.app_server.v1"


# --- SPA fallback containment ----------------------------------------------

def test_spa_fallback_serves_internal_files(tmp_path: pathlib.Path) -> None:
    client = _make_spa_app(tmp_path)
    response = client.get("/secret.txt")
    assert response.status_code == 200
    assert response.text == "SECRET"


def test_spa_fallback_blocks_traversal(tmp_path: pathlib.Path) -> None:
    client = _make_spa_app(tmp_path)
    # A sibling file outside the frontend root (readable only if the old
    # ``resolved / filename`` join was still in place).
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("OUTSIDE-SECRET", encoding="utf-8")
    try:
        for path in ("/%2e%2e/%2e%2e/" + outside.name, "/..%2f" + outside.name):
            response = client.get(path)
            assert response.status_code == 200
            assert "OUTSIDE-SECRET" not in response.text
            assert "index" in response.text
    finally:
        outside.unlink(missing_ok=True)


def test_spa_fallback_falls_back_to_index(tmp_path: pathlib.Path) -> None:
    client = _make_spa_app(tmp_path)
    response = client.get("/some/client/route")
    assert response.status_code == 200
    assert "index" in response.text
