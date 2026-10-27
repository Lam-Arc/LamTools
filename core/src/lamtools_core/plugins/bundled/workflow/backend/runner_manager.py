"""Workflow definition CRUD, document persistence and mutation serialization."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
import inspect
from pathlib import Path
from typing import Any
from .models import WorkflowDef, WorkflowEdge, WorkflowInputParam, WorkflowNode, _utcnow, ensure_workflow_id


_WORKFLOW_MUTATION_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}


class WorkflowManager:
    """Coordinates workflow definitions with a :class:`WorkflowStore`-like store.

    The store protocol mirrors :class:`ArrangeStore`: async ``list`` / ``get`` /
    ``save`` / ``delete``. The file-backed implementation lives in
    :mod:`lamtools_core.plugins.bundled.workflow.backend.store`.
    """

    def __init__(self, store: Any, node_registry: Any = None) -> None:
        self.store = store
        self.node_registry = node_registry

    def _mutation_lock(self, work_root: str | None) -> asyncio.Lock:
        provider = getattr(self.store, "mutation_lock", None)
        if callable(provider):
            return provider(work_root)
        # Store-compatible test/embedding implementations may not expose a
        # lock provider.  Still serialize all managers sharing that store and
        # scope so expected_revision remains a real compare-and-swap.
        try:
            scope = str(Path(work_root).expanduser().resolve()) if work_root else ""
        except (OSError, TypeError, ValueError):
            scope = str(work_root or "")
        key = (id(self.store), scope.casefold())
        lock = _WORKFLOW_MUTATION_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _WORKFLOW_MUTATION_LOCKS[key] = lock
        return lock

    async def create(self, definition: WorkflowDef) -> WorkflowDef:
        from .runner_validation import validate_workflow
        async with self._mutation_lock(definition.work_root):
            ensure_workflow_id(definition)
            definition.revision = max(1, definition.revision)
            validate_workflow(definition, node_registry=self.node_registry)
            return await self.store.save(definition)

    async def get(self, name: str, *, work_root: str | None = None) -> WorkflowDef | None:
        return await self.store.get(name, work_root=work_root)

    async def get_by_id(self, workflow_id: str, *, work_root: str | None = None) -> WorkflowDef | None:
        """Resolve a workflow ID within one repository scope.

        File-backed stores provide an exact scoped lookup.  Keep the
        list-and-filter fallback for store-compatible integrations that have
        not adopted the optional ``get_by_id`` seam yet.
        """
        provider = getattr(self.store, "get_by_id", None)
        if callable(provider):
            result = provider(workflow_id, work_root=work_root)
            if inspect.isawaitable(result):
                return await result
            return result
        definitions = await self.store.list(work_root=work_root)
        target = str(workflow_id or "").strip()
        if not target:
            return None
        return next((item for item in definitions if item.id == target), None)

    async def get_document(self, name: str, *, work_root: str | None = None) -> dict[str, Any] | None:
        from .document import document_from_workflow_def

        definition = await self.get(name, work_root=work_root)
        return document_from_workflow_def(definition) if definition is not None else None

    async def save_document(
        self,
        document: dict[str, Any],
        *,
        work_root: str | None = None,
        expected_revision: int | None = None,
    ) -> WorkflowDef:
        """CAS-save one canonical V2 document through the runtime seam."""
        from .runner_context import WorkflowConflictError
        from .runner_validation import validate_workflow
        from .document import canonicalize_document, workflow_def_from_document

        doc = canonicalize_document(document)
        resource = doc["resource"]
        active_root = str(work_root if work_root is not None else resource["work_root"])
        async with self._mutation_lock(active_root):
            current = await self.store.get(resource["name"], work_root=active_root or None)
            if current is not None:
                if expected_revision is not None and current.revision != expected_revision:
                    raise WorkflowConflictError(
                        f"workflow revision conflict: expected {expected_revision}, current {current.revision}"
                    )
                resource["id"] = current.id
                resource["created_at"] = current.created_at.isoformat()
                resource["revision"] = max(1, current.revision + 1)
            else:
                if expected_revision not in (None, 0):
                    raise WorkflowConflictError(
                        f"workflow revision conflict: expected {expected_revision}, current 0"
                    )
                resource["revision"] = max(1, int(resource.get("revision") or 0))
            resource["work_root"] = active_root
            resource["updated_at"] = _utcnow().isoformat()
            definition = workflow_def_from_document(doc)
            validate_workflow(definition, node_registry=self.node_registry)
            return await self.store.save(definition)

    async def list(self, *, work_root: str | None = None) -> list[WorkflowDef]:
        return await self.store.list(work_root=work_root)

    async def list_grouped(self, *, work_roots: list[str]) -> dict[str, list[WorkflowDef]]:
        """Return workflows bucketed by source: ``"global"`` + per ``work_root``."""
        grouped = getattr(self.store, "list_grouped", None)
        if grouped is None:
            return {"global": await self.store.list(work_root=None)}
        return await grouped(work_roots=work_roots)

    async def update_fields(
        self,
        name: str,
        *,
        work_root: str | None = None,
        description: str | None = None,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
        input_params: list[dict[str, Any]] | None = None,
        output_port: str | None = None,
        exposed: bool | None = None,
        tool_name: str | None = None,
        expected_revision: int | None = None,
    ) -> WorkflowDef:
        from .runner_context import WorkflowConflictError
        from .runner_validation import validate_workflow
        async with self._mutation_lock(work_root):
            current = await self.store.get(name, work_root=work_root)
            if current is None:
                raise LookupError(f"Workflow not found: {name}")
            if expected_revision is not None and current.revision != expected_revision:
                raise WorkflowConflictError(
                    f"workflow revision conflict: expected {expected_revision}, current {current.revision}"
                )
            if description is not None:
                current.description = description
            if nodes is not None:
                current.nodes = [WorkflowNode.from_dict(n) for n in nodes]
            if edges is not None:
                current.edges = [WorkflowEdge.from_dict(e) for e in edges]
            if input_params is not None:
                current.input_params = [WorkflowInputParam.from_dict(p) for p in input_params]
            if output_port is not None:
                current.output_port = output_port
            if exposed is not None:
                current.exposed = exposed
            if tool_name is not None:
                current.tool_name = tool_name
            current.updated_at = _utcnow()
            current.revision = max(1, current.revision + 1)
            validate_workflow(current, node_registry=self.node_registry)
            return await self.store.save(current)

    async def rename(
        self,
        name: str,
        new_name: str,
        *,
        work_root: str | None = None,
    ) -> WorkflowDef:
        """Rename a workflow while preserving its stable resource id."""
        from .runner_validation import validate_workflow
        clean_name = str(new_name or "").strip()
        if not clean_name:
            raise ValueError("new workflow name is required")
        async with self._mutation_lock(work_root):
            current = await self.store.get(name, work_root=work_root)
            if current is None:
                raise LookupError(f"Workflow not found: {name}")
            if clean_name == current.name:
                return current
            collision = await self.store.get(clean_name, work_root=work_root)
            if collision is not None and collision.id != current.id:
                raise ValueError(f"Workflow already exists: {clean_name}")
            current.name = clean_name
            current.updated_at = _utcnow()
            validate_workflow(current, node_registry=self.node_registry)
            return await self.store.save(current)

    async def delete(self, name: str, *, work_root: str | None = None) -> bool:
        async with self._mutation_lock(work_root):
            return await self.store.delete(name, work_root=work_root)

    async def set_exposed(self, name: str, exposed: bool, *, work_root: str | None = None) -> WorkflowDef:
        return await self.update_fields(name, work_root=work_root, exposed=exposed)

    async def list_exposed(self, *, work_root: str | None = None) -> list[WorkflowDef]:
        return [w for w in await self.store.list(work_root=work_root) if w.exposed]
