"""LamTools Core HTTP routes — generic FastAPI router for the core skeleton."""

from __future__ import annotations

import json
import inspect
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..app.operation_catalog import OperationCatalog
from ..app.project_store import ActiveProjectSessionsError, CoreProjectStore
from ..provider import ProviderConfig, ProviderRegistry
from ..run_event import (
    InMemoryRuntimeEventStore,
    RuntimeEventRecord,
    RuntimeEventStore,
)
from ..session import (
    InMemorySessionStore,
    MessageRecord,
    SessionRecord,
    SessionStore,
)
from ..usage import (
    InMemoryUsageLedger,
    UsageLedger,
    UsageRecord,
)


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class SessionCreateRequest(BaseModel):
    id: str = Field(min_length=1)
    member_id: str
    title: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionUpdateRequest(BaseModel):
    title: str | None = None
    status: str | None = None
    metadata: dict[str, Any] | None = None


class ProjectCreateRequest(BaseModel):
    work_root: str = Field(min_length=1)
    name: str | None = None


class ProjectUpdateRequest(BaseModel):
    name: str = Field(min_length=1)


class ProjectSessionCreateRequest(BaseModel):
    title: str = "New Session"


class AgentsMdUpdateRequest(BaseModel):
    content: str


class MessageCreateRequest(BaseModel):
    id: str = Field(min_length=1)
    role: str
    content: str
    parts: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TurnStartRequest(BaseModel):
    message: str = Field(min_length=1)
    approval_policy: str = "require"
    model_id: str = ""
    work_root: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventCreateRequest(BaseModel):
    id: str = ""
    name: str
    category: str
    payload: dict[str, Any] = Field(default_factory=dict)
    run_id: str = ""


class ProviderCreateRequest(BaseModel):
    id: str = Field(min_length=1)
    kind: str
    name: str
    base_url: str = ""
    api_key_ref: str = ""
    default_model: str = ""
    models: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class UsageCreateRequest(BaseModel):
    id: str = Field(min_length=1)
    member_id: str
    session_id: str = ""
    provider_id: str = ""
    usage_type: str = ""
    amount: float = 0.0
    unit: str = ""
    cost: float = 0.0
    currency: str = "USD"
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def create_core_router(
    *,
    session_store: InMemorySessionStore | SessionStore | None = None,
    event_store: InMemoryRuntimeEventStore | RuntimeEventStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    usage_ledger: InMemoryUsageLedger | UsageLedger | None = None,
    operations: OperationCatalog | None = None,
    project_store: CoreProjectStore | Callable[[], CoreProjectStore] | None = None,
) -> APIRouter:
    """Create an APIRouter with all core LamTools routes.

    Each parameter accepts the concrete in-memory implementation,
    a protocol-compatible object, or None (which creates the
    in-memory default).
    """
    # --- Defaults ---
    if session_store is None:
        _session_store: SessionStore = InMemorySessionStore()
    else:
        _session_store = session_store

    if event_store is None:
        _event_store: RuntimeEventStore = InMemoryRuntimeEventStore()
    else:
        _event_store = event_store

    if provider_registry is None:
        _provider_registry = ProviderRegistry()
    else:
        _provider_registry = provider_registry

    if usage_ledger is None:
        _usage_ledger: UsageLedger = InMemoryUsageLedger()
    else:
        _usage_ledger = usage_ledger

    _operations = operations

    def require_project_store() -> CoreProjectStore:
        resolved = project_store() if callable(project_store) else project_store
        if resolved is None:
            raise HTTPException(status_code=503, detail="Project storage is not configured")
        return resolved

    router = APIRouter()

    # ==================================================================
    # Session routes
    # ==================================================================

    @router.get("/sessions")
    async def list_sessions() -> list[dict[str, Any]]:
        return [s.to_dict() for s in await _store_call(_session_store.list)]

    @router.post("/sessions", status_code=201)
    async def create_session(body: SessionCreateRequest) -> dict[str, Any]:
        if _has_project_metadata(body.metadata):
            raise HTTPException(status_code=422, detail="Use the project session endpoint for project-owned sessions")
        record = SessionRecord(
            id=body.id,
            member_id=body.member_id,
            title=body.title,
            status=body.status,
            metadata=body.metadata,
        )
        await _store_call(_session_store.create, record)
        return record.to_dict()

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        record = await _store_call(_session_store.get, session_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return record.to_dict()

    @router.patch("/sessions/{session_id}")
    async def update_session(
        session_id: str,
        body: SessionUpdateRequest,
    ) -> dict[str, Any]:
        existing = await _store_call(_session_store.get, session_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Session not found")
        metadata = _validated_session_metadata(existing.metadata, body.metadata)
        patch_method = getattr(_session_store, "patch", None)
        if patch_method is not None:
            record = await _store_call(
                patch_method,
                session_id,
                title=body.title,
                status=body.status,
                metadata=metadata,
            )
            if record is None:
                raise HTTPException(status_code=404, detail="Session not found")
            return record.to_dict()
        record = existing
        if body.title is not None:
            record.title = body.title
        if body.status is not None:
            record.status = body.status
        if metadata is not None:
            record.metadata = metadata
        await _store_call(_session_store.update, record)
        return record.to_dict()

    @router.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str) -> Response:
        record = await _store_call(_session_store.get, session_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if str(record.status).lower() in {"running", "waiting", "interrupting"}:
            raise HTTPException(status_code=409, detail="Stop the active session before deleting it")
        if not await _store_call(_session_store.delete, session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        return Response(status_code=204)

    @router.get("/sessions/{session_id}/messages")
    async def list_messages(session_id: str) -> list[dict[str, Any]]:
        return [m.to_dict() for m in await _store_call(_session_store.list_messages, session_id)]

    @router.post("/sessions/{session_id}/messages", status_code=201)
    async def create_message(
        session_id: str,
        body: MessageCreateRequest,
    ) -> dict[str, Any]:
        record = MessageRecord(
            id=body.id,
            session_id=session_id,
            role=body.role,
            content=body.content,
            parts=body.parts,
            metadata=body.metadata,
        )
        await _store_call(_session_store.add_message, record)
        return record.to_dict()

    @router.post("/sessions/{session_id}/turns")
    async def start_turn(
        session_id: str,
        body: TurnStartRequest,
    ) -> dict[str, Any]:
        session = await _store_call(_session_store.get, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if _operations is None or not _operations.has("turn.start"):
            raise HTTPException(status_code=503, detail="Core turn operation is not configured")

        user_message = MessageRecord(
            id=f"user-{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            role="user",
            content=body.message,
        )
        await _store_call(_session_store.add_message, user_message)
        await _update_session_status(session, _session_store, "running", title_fallback=body.message)

        try:
            result = await _operations.execute(
                "turn.start",
                {
                    "thread_id": session_id,
                    "session_id": session_id,
                    "message": body.message,
                    "approval_policy": body.approval_policy,
                    **({"model_id": body.model_id} if body.model_id else {}),
                    **({"work_root": body.work_root} if body.work_root else {}),
                    "metadata": body.metadata,
                },
                metadata={"source": "core_http"},
            )
        except Exception as exc:
            await _update_session_status(session, _session_store, "failed")
            failure = MessageRecord(
                id=f"system-{uuid.uuid4().hex[:12]}",
                session_id=session_id,
                role="system",
                content=str(exc),
                parts=[_system_part("Core 执行失败", str(exc), status="error")],
                metadata={"source": "core_http", "error": str(exc)},
            )
            await _store_call(_session_store.add_message, failure)
            raise HTTPException(status_code=500, detail=str(exc))

        payload = dict(result.payload or {})
        run_items = _run_items_from_payload(payload)
        for item in run_items:
            _append_run_item_event(_event_store, session_id=session_id, run_id=str(payload.get("run_id") or ""), item=item)

        part_items = _message_part_items_from_payload(payload, fallback=run_items)
        parts = _message_parts_from_run_items(part_items)
        content = _assistant_content(payload, parts)
        assistant_message = MessageRecord(
            id=f"assistant-{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            role="assistant",
            content=content,
            parts=parts,
            metadata={
                "source": "core_http",
                "operation": result.name,
                "operation_status": result.status,
                "run_id": payload.get("run_id") or "",
                "decision": payload.get("decision") or "",
                "document_path": payload.get("document_path") or "",
            },
        )
        await _store_call(_session_store.add_message, assistant_message)
        await _update_session_status(session, _session_store, "completed" if result.status == "ok" else "failed")

        return {
            "status": result.status,
            "operation": result.name,
            "payload": payload,
            "user_message": user_message.to_dict(),
            "assistant_message": assistant_message.to_dict(),
        }

    # ==================================================================
    # Project routes
    # ==================================================================

    @router.get("/projects")
    async def list_projects() -> dict[str, Any]:
        store = require_project_store()
        return {"projects": [project.to_dict() for project in await store.list()]}

    @router.post("/projects", status_code=201)
    async def create_project(body: ProjectCreateRequest, response: Response) -> dict[str, Any]:
        store = require_project_store()
        try:
            project, session, created = await store.create_with_initial_session(body.work_root, name=body.name)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not created:
            response.status_code = 200
        return {"project": project.to_dict(), "session": session.to_dict()}

    @router.get("/projects/{project_id}")
    async def get_project(project_id: str) -> dict[str, Any]:
        project = await require_project_store().get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project.to_dict()

    @router.patch("/projects/{project_id}")
    async def update_project(project_id: str, body: ProjectUpdateRequest) -> dict[str, Any]:
        try:
            project = await require_project_store().rename(project_id, body.name)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project.to_dict()

    @router.delete("/projects/{project_id}", status_code=204)
    async def delete_project(project_id: str) -> Response:
        try:
            deleted = await require_project_store().delete_with_sessions(project_id)
        except ActiveProjectSessionsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Project not found")
        return Response(status_code=204)

    @router.get("/projects/{project_id}/sessions")
    async def list_project_sessions(project_id: str) -> dict[str, Any]:
        store = require_project_store()
        if await store.get(project_id) is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"sessions": [session.to_dict() for session in await store.list_sessions(project_id)]}

    @router.post("/projects/{project_id}/sessions", status_code=201)
    async def create_project_session(project_id: str, body: ProjectSessionCreateRequest) -> dict[str, Any]:
        try:
            session = await require_project_store().create_session(project_id, title=body.title)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Project not found") from exc
        return session.to_dict()

    @router.get("/projects/{project_id}/agents-md")
    async def get_project_agents_md(project_id: str) -> dict[str, str | bool]:
        try:
            agents_md = await require_project_store().read_agents_md(project_id)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if agents_md is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return agents_md

    @router.put("/projects/{project_id}/agents-md")
    async def update_project_agents_md(
        project_id: str,
        body: AgentsMdUpdateRequest,
    ) -> dict[str, str | bool]:
        try:
            agents_md = await require_project_store().write_agents_md(project_id, body.content)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if agents_md is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return agents_md

    # ==================================================================
    # Project file routes (for Stage pane file tree & preview)
    # ==================================================================

    _IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache"}

    @router.get("/projects/{project_id}/files")
    async def list_project_files(project_id: str, path: str = "") -> dict[str, Any]:
        store = require_project_store()
        project = await store.get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        root = Path(project.work_root)
        target = (root / path).resolve() if path else root
        try:
            target.relative_to(root)
        except ValueError:
            raise HTTPException(status_code=403, detail="Path escapes project root")
        if not target.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")
        entries = []
        try:
            for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if item.is_dir() and item.name in _IGNORED_DIRS:
                    continue
                entries.append({
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else 0,
                    "ext": item.suffix.lower().lstrip(".") if item.is_file() else "",
                })
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied")
        return {"entries": entries, "path": path}

    @router.get("/projects/{project_id}/files/content")
    async def read_project_file_content(project_id: str, path: str) -> dict[str, str]:
        if not path:
            raise HTTPException(status_code=400, detail="path is required")
        store = require_project_store()
        project = await store.get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        root = Path(project.work_root)
        target = (root / path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise HTTPException(status_code=403, detail="Path escapes project root")
        if not target.exists():
            raise HTTPException(status_code=404, detail="File not found")
        if not target.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=422, detail="File is not valid UTF-8 text")
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied")
        return {"content": content, "path": path}

    @router.get("/projects/{project_id}/files/raw")
    async def read_project_file_raw(project_id: str, path: str):
        if not path:
            raise HTTPException(status_code=400, detail="path is required")
        store = require_project_store()
        project = await store.get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        root = Path(project.work_root)
        target = (root / path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise HTTPException(status_code=403, detail="Path escapes project root")
        if not target.exists():
            raise HTTPException(status_code=404, detail="File not found")
        if not target.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")
        return FileResponse(str(target))

    @router.put("/projects/{project_id}/files/content")
    async def write_project_file_content(project_id: str, path: str, body: dict):
        if not path:
            raise HTTPException(status_code=400, detail="path is required")
        content = body.get("content")
        if content is None:
            raise HTTPException(status_code=400, detail="content is required")
        store = require_project_store()
        project = await store.get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        root = Path(project.work_root)
        target = (root / path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise HTTPException(status_code=403, detail="Path escapes project root")
        if not target.exists():
            raise HTTPException(status_code=404, detail="File not found")
        if not target.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")
        try:
            target.write_text(content, encoding="utf-8")
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied")
        return {"content": content, "path": path}

    # ==================================================================
    # Event routes
    # ==================================================================

    @router.get("/sessions/{session_id}/events")
    async def list_events(session_id: str) -> list[dict[str, Any]]:
        return [e.to_dict() for e in _event_store.list(session_id=session_id)]

    @router.post("/sessions/{session_id}/events", status_code=201)
    async def create_event(
        session_id: str,
        body: EventCreateRequest,
    ) -> dict[str, Any]:
        event_id = body.id or uuid.uuid4().hex[:16]
        record = RuntimeEventRecord(
            id=event_id,
            session_id=session_id,
            name=body.name,
            category=body.category,
            payload=body.payload,
            run_id=body.run_id,
            created_at=datetime.now(),
            sequence=0,
        )
        _event_store.append(record)
        return record.to_dict()

    # ==================================================================
    # Provider routes
    # ==================================================================

    @router.get("/providers")
    async def list_providers() -> list[dict[str, Any]]:
        return [p.to_dict() for p in _provider_registry.list()]

    @router.post("/providers", status_code=201)
    async def create_provider(body: ProviderCreateRequest) -> dict[str, Any]:
        config = ProviderConfig(
            id=body.id,
            kind=body.kind,
            name=body.name,
            base_url=body.base_url,
            api_key_ref=body.api_key_ref,
            default_model=body.default_model,
            models=body.models,
            metadata=body.metadata,
            enabled=body.enabled,
        )
        try:
            _provider_registry.register(config)
        except ValueError:
            raise HTTPException(
                status_code=409,
                detail=f"Provider '{body.id}' is already registered",
            )
        return config.to_dict()

    @router.get("/providers/default")
    async def get_default_provider(
        kind: str | None = None,
    ) -> dict[str, Any]:
        try:
            config = _provider_registry.select_default(kind)
        except KeyError:
            detail = "No enabled provider found"
            if kind is not None:
                detail += f" of kind '{kind}'"
            raise HTTPException(status_code=404, detail=detail)
        return config.to_dict()

    # ==================================================================
    # Usage routes
    # ==================================================================

    @router.get("/usage")
    async def list_usage() -> list[dict[str, Any]]:
        return [r.to_dict() for r in _usage_ledger.list()]

    @router.post("/usage", status_code=201)
    async def create_usage(body: UsageCreateRequest) -> dict[str, Any]:
        record = UsageRecord(
            id=body.id,
            member_id=body.member_id,
            session_id=body.session_id,
            provider_id=body.provider_id,
            usage_type=body.usage_type,
            amount=body.amount,
            unit=body.unit,
            cost=body.cost,
            currency=body.currency,
            metadata=body.metadata,
            created_at=datetime.now(),
        )
        _usage_ledger.append(record)
        return record.to_dict()

    @router.get("/usage/total")
    async def get_usage_total(
        member_id: str | None = None,
        currency: str = "USD",
    ) -> dict[str, Any]:
        total = _usage_ledger.total_cost(member_id=member_id, currency=currency)
        return {"total_cost": total, "currency": currency}

    return router


async def _update_session_status(
    session: SessionRecord,
    store: SessionStore,
    status: str,
    *,
    title_fallback: str = "",
) -> None:
    session.status = status
    if title_fallback and (not session.title or session.title.lower() in {"new session", "untitled", "core"}):
        session.title = title_fallback[:60]
    await _store_call(store.update, session)


async def _store_call(method: Any, *args: Any, **kwargs: Any) -> Any:
    result = method(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def _run_items_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = payload.get("run_items")
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def _message_part_items_from_payload(payload: dict[str, Any], *, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    snapshot_items = _run_items_from_snapshot(payload)
    return snapshot_items or fallback


def _run_items_from_snapshot(payload: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        return []
    core_snapshot = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else snapshot
    items = core_snapshot.get("items") if isinstance(core_snapshot, dict) else None
    if not isinstance(items, dict) or not items:
        return []
    raw_order = core_snapshot.get("item_order")
    ordered_ids = [str(item_id) for item_id in raw_order] if isinstance(raw_order, list) else []
    if not ordered_ids:
        ordered_ids = sorted(
            (str(item_id) for item_id in items),
            key=lambda item_id: int((items.get(item_id) or {}).get("last_seq") or 0),
        )
    thread_id = str(core_snapshot.get("thread_id") or payload.get("thread_id") or "")
    run_id = str(payload.get("run_id") or "")
    result: list[dict[str, Any]] = []
    for item_id in ordered_ids:
        item = items.get(item_id)
        if isinstance(item, dict):
            result.append(_run_item_from_snapshot_item(item, thread_id=thread_id, run_id=run_id))
    return result


def _run_item_from_snapshot_item(item: dict[str, Any], *, thread_id: str, run_id: str) -> dict[str, Any]:
    payload, artifacts = _payload_from_snapshot_item(item)
    converted = {
        "kind": str(item.get("kind") or ""),
        "thread_id": thread_id,
        "event_id": str(item.get("event_id") or item.get("item_id") or uuid.uuid4().hex[:16]),
        "turn_id": str(item.get("turn_id") or ""),
        "item_id": str(item.get("item_id") or item.get("event_id") or ""),
        "seq": int(item.get("last_seq") or item.get("seq") or 0),
        "status": str(item.get("status") or ""),
        "payload": payload,
        "run_id": run_id,
    }
    if artifacts:
        converted["artifacts"] = artifacts
    return converted


def _payload_from_snapshot_item(item: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = dict(item.get("payload") if isinstance(item.get("payload"), dict) else {})
    artifacts = [artifact for artifact in item.get("artifacts", []) if isinstance(artifact, dict)]
    raw_content = item.get("content")
    parsed_content = _json_object(raw_content)
    parsed_payload_content = _json_object(payload.get("content"))
    parsed_payload_delta = _json_object(payload.get("delta"))

    if isinstance(parsed_payload_content, dict) and parsed_payload_content.get("part_type"):
        payload.update(_payload_from_runtime_part(parsed_payload_content, payload_type=str(payload.get("type") or "")))
    elif isinstance(parsed_content, dict) and parsed_content.get("part_type"):
        payload.update(_payload_from_runtime_part(parsed_content, payload_type=str(payload.get("type") or "")))

    if str(item.get("kind") or "") == "tool_result" and isinstance(parsed_content, dict):
        tool_name = parsed_content.get("tool_name")
        if isinstance(tool_name, str) and tool_name:
            payload["tool_name"] = tool_name
        result_content = parsed_content.get("content")
        if isinstance(result_content, str):
            payload["tool_result"] = result_content
        error = parsed_content.get("error")
        if isinstance(error, str):
            payload["error"] = error
        parsed_artifacts = parsed_content.get("artifacts")
        if isinstance(parsed_artifacts, list):
            artifacts = [artifact for artifact in parsed_artifacts if isinstance(artifact, dict)]

    if isinstance(parsed_payload_delta, dict) and parsed_payload_delta.get("finish_reason"):
        payload["finish_reason"] = str(parsed_payload_delta.get("finish_reason") or "")
        payload["content"] = str(parsed_payload_delta.get("content") or "")
        payload.pop("delta", None)
        payload.setdefault("summary", payload["finish_reason"])
    return payload, artifacts


def _payload_from_runtime_part(part: dict[str, Any], *, payload_type: str) -> dict[str, Any]:
    mapped = {
        "type": payload_type or "agentMessage",
        "content": str(part.get("content") or ""),
        "label": str(part.get("label") or ""),
    }
    if "final_response" in part:
        mapped["final_response"] = part.get("final_response")
    if "has_tool_calls" in part:
        mapped["has_tool_calls"] = part.get("has_tool_calls")
    return mapped


def _json_object(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str) or not value.strip().startswith("{"):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _append_run_item_event(
    store: RuntimeEventStore,
    *,
    session_id: str,
    run_id: str,
    item: dict[str, Any],
) -> None:
    event_id = str(item.get("event_id") or uuid.uuid4().hex[:16])
    store.append(
        RuntimeEventRecord(
            id=event_id,
            session_id=session_id,
            name="core.run_item",
            category="runtime",
            payload=item,
            run_id=str(item.get("run_id") or run_id),
            created_at=_datetime_from_ms(item.get("created_at_ms")),
            sequence=int(item.get("seq") or 0),
        )
    )


def _message_parts_from_run_items(run_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    completed_tool_item_ids = {
        str(item.get("item_id") or "")
        for item in run_items
        if item.get("kind") == "tool_result" and _part_status(str(item.get("status") or "")) == "completed"
    }
    parts: list[dict[str, Any]] = []
    for index, item in enumerate(run_items, 1):
        part = _message_part_from_run_item(item, index=index, completed_tool_item_ids=completed_tool_item_ids)
        if part is not None:
            parts.append(part)
    return parts


def _message_part_from_run_item(
    item: dict[str, Any],
    *,
    index: int,
    completed_tool_item_ids: set[str],
) -> dict[str, Any] | None:
    kind = str(item.get("kind") or "")
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    part_type = _part_type(kind, payload)
    if part_type is None:
        return None
    item_id = str(item.get("item_id") or item.get("event_id") or f"part-{index}")
    raw_status = str(item.get("status") or "")
    status = _part_status(raw_status)
    if kind == "tool_call" and item_id in completed_tool_item_ids:
        status = "completed"
    if _is_terminal_message_metadata_only(kind, payload):
        return None
    content = _part_content(kind, payload)
    if part_type in {"text", "model_text"} and not content.strip():
        return None
    tool_name = str(payload.get("tool_name") or "")
    part: dict[str, Any] = {
        "id": f"{item_id}:{kind}:{index}",
        "partType": part_type,
        "status": status,
        "content": content,
        "label": _part_label(part_type, payload),
        "detail": str(payload.get("message") or payload.get("summary") or ""),
        "runId": str(item.get("run_id") or ""),
        "metadata": {
            "coreRunItem": item,
            **(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
        },
    }
    if tool_name:
        part["toolName"] = tool_name
    arguments = payload.get("arguments")
    if isinstance(arguments, dict):
        part["toolArgs"] = arguments
    input_preview = payload.get("input_preview") or payload.get("inputPreview")
    if isinstance(input_preview, dict):
        part["inputPreview"] = input_preview
    if kind == "tool_result" or part_type == "tool_result":
        part["toolResult"] = str(payload.get("tool_result") or payload.get("content") or payload.get("delta") or "")
        error = str(payload.get("error") or "")
        if error:
            part["toolError"] = error
    artifacts = item.get("artifacts")
    if isinstance(artifacts, list) and artifacts:
        part["artifacts"] = [artifact for artifact in artifacts if isinstance(artifact, dict)]
    return part


def _is_terminal_message_metadata_only(kind: str, payload: dict[str, Any]) -> bool:
    if kind != "message":
        return False
    if "finish_reason" not in payload and "usage" not in payload:
        return False
    for key in ("content", "delta", "message", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return False
    return True


def _part_type(kind: str, payload: dict[str, Any]) -> str | None:
    payload_type = str(payload.get("type") or "")
    if kind == "thinking" or payload_type in {"reasoning", "thinking"}:
        return "reasoning"
    if kind == "tool_call" or payload_type == "dynamicToolCall":
        return "tool_call"
    if kind == "tool_result":
        return "tool_result"
    if kind == "approval_request" or payload_type == "serverRequest":
        return "decision"
    if kind == "error":
        return "error"
    if kind == "status":
        return "status"
    if kind == "message":
        return "model_text" if payload_type == "agentMessage" else "text"
    return None


def _part_status(status: str) -> str:
    if status in {"completed", "done", "ok", "skipped"}:
        return "completed"
    if status in {"failed", "error", "cancelled"}:
        return "error"
    if status in {"waiting", "queued", "pending"}:
        return "pending"
    return "running"


def _part_content(kind: str, payload: dict[str, Any]) -> str:
    if kind == "tool_result":
        return str(payload.get("tool_result") or payload.get("content") or payload.get("delta") or payload.get("error") or "")
    for key in ("content", "delta", "message", "summary", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _part_label(part_type: str, payload: dict[str, Any]) -> str:
    if part_type == "reasoning":
        return "思考"
    if part_type == "model_text":
        return "正文"
    if part_type in {"tool_call", "tool_result"}:
        return str(payload.get("tool_name") or "tool")
    if part_type == "decision":
        return "确认"
    if part_type == "error":
        return "错误"
    return str(payload.get("label") or part_type)


def _assistant_content(payload: dict[str, Any], parts: list[dict[str, Any]]) -> str:
    message = str(payload.get("message") or "").strip()
    if message:
        return message
    texts = [
        str(part.get("content") or "")
        for part in parts
        if part.get("partType") in {"text", "model_text"} and str(part.get("content") or "").strip()
    ]
    return "\n".join(texts).strip()


def _system_part(label: str, content: str, *, status: str) -> dict[str, Any]:
    return {
        "id": f"system-{uuid.uuid4().hex[:12]}",
        "partType": "error" if status == "error" else "status",
        "status": status,
        "label": label,
        "content": content,
    }


def _datetime_from_ms(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(value) / 1000)
    except (TypeError, ValueError, OSError, OverflowError):
        return datetime.now()


def _has_project_metadata(metadata: dict[str, Any]) -> bool:
    return "work_root" in metadata


def _validated_session_metadata(existing: dict[str, Any], requested: dict[str, Any] | None) -> dict[str, Any] | None:
    if requested is None:
        return None
    work_root = existing.get("work_root")
    if not isinstance(work_root, str) or not work_root:
        if _has_project_metadata(requested):
            raise HTTPException(status_code=422, detail="Use the project session endpoint for project-owned sessions")
        return dict(requested)
    metadata = dict(requested)
    metadata["work_root"] = str(work_root)
    return metadata
