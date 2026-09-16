"""File-backed workflow definitions.

Each workflow is stored as a **folder** (mirroring the
:class:`~lamtools_core.skills.SkillRegistry` folder-per-skill convention):

* ``{root}/workflows/<name>/workflow.json`` — canonical atomic V2 document.
* ``{root}/workflows/<name>/config.json`` — meta (name, description, exposed,
  tool_name, input_params, output_port, timestamps) + a derived legacy ``map``.
* ``{root}/workflows/<name>/<nodeId>.json`` — one file per node with
  ``inputs[]``/``outputs[]`` arrays + ``config`` + ``position``.

The legacy files are retained for rollback and compatibility but are never a
second source of truth when ``workflow.json`` exists.  For an old folder with
no V2 document, explicit edge objects take precedence and ``map`` is only a
last-resort topology parser.

Legacy single-JSON files (``workflows/<name>.json``) are migrated lazily to
the folder layout on first read.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from lamtools_core.config.root import lam_home
from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowDef,
    WorkflowNode,
    ensure_workflow_id,
    _json_copy,
    _parse_map,
    _ports_to_io,
    _serialize_map,
)
from .document import (
    document_from_workflow_def,
    is_v2_document,
    workflow_def_from_document,
)


# Managers may be created independently for the same project (for example by
# an RPC host and a CLI request).  Keep the compare-and-swap critical section
# keyed by the durable workflow directory rather than by a manager instance so
# concurrent in-process writers cannot both observe the same revision.
_MUTATION_LOCKS: dict[str, asyncio.Lock] = {}


class WorkflowStore:
    """Discovers, reads, and writes workflow definition folders."""

    def __init__(self, *, explicit_roots: Iterable[str | Path] = ()) -> None:
        self._explicit_roots = tuple(Path(item).resolve() for item in explicit_roots)
        # Cache keyed by work_root so concurrent calls with different roots
        # (e.g. global vs project) don't return a stale entry from the other.
        self._cached: dict[str, tuple[Any, list[WorkflowDef]]] = {}

    def mutation_lock(self, work_root: str | Path | None = None) -> asyncio.Lock:
        """Return the shared mutation lock for one workflow scope."""
        key = str(self._writable_dir(str(work_root) if work_root else None).resolve()).casefold()
        lock = _MUTATION_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _MUTATION_LOCKS[key] = lock
        return lock

    # -- discovery --------------------------------------------------------

    def _workflow_entries(self, work_root: str | None) -> list[Path]:
        """Return paths to each workflow: folders (with config.json) or legacy
        single-JSON files (migrated on read)."""
        roots: list[Path] = []
        home_lam = lam_home()
        if home_lam.is_dir():
            roots.append(home_lam)
        roots.extend(self._explicit_roots)

        seen: set[Path] = set()
        results: list[Path] = []

        def _add(path: Path) -> None:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                results.append(resolved)

        for root in roots:
            workflows_dir = root / "workflows"
            if workflows_dir.is_dir():
                self._scan_workflows_dir(workflows_dir, _add)
        if work_root:
            lam_dir = Path(work_root).resolve() / ".lam"
            if lam_dir.is_dir():
                for workflows_dir in [lam_dir / "workflows", *lam_dir.rglob("workflows")]:
                    if workflows_dir.is_dir():
                        self._scan_workflows_dir(workflows_dir, _add)
        return results

    @staticmethod
    def _scan_workflows_dir(workflows_dir: Path, _add: Any) -> None:
        """Scan a workflows/ dir for folder entries and legacy single-JSONs."""
        try:
            children = list(workflows_dir.iterdir())
        except OSError:
            return
        for p in children:
            if p.is_dir() and ((p / "workflow.json").is_file() or (p / "config.json").is_file()):
                _add(p)
            elif p.is_file() and p.suffix == ".json" and p.name != "config.json":
                # Legacy single-JSON (parent has no config.json).
                if not (p.parent / "config.json").is_file() and not (
                    p.parent / p.stem / "workflow.json"
                ).is_file():
                    _add(p)

    def _scoped_workflow_entries(self, work_root: str | None) -> list[Path]:
        """Return workflow entry paths confined to a single scope.

        ``work_root=None`` yields only the global roots (home + explicit);
        a project root yields only that project's ``.lam/workflows`` trees.
        Unlike ``_workflow_entries`` this never mixes scopes, so destructive
        operations (delete) cannot reach a same-named workflow elsewhere.
        """
        seen: set[Path] = set()
        results: list[Path] = []

        def _add(path: Path) -> None:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                results.append(resolved)

        if work_root:
            lam_dir = Path(work_root).resolve() / ".lam"
            if lam_dir.is_dir():
                for workflows_dir in [lam_dir / "workflows", *lam_dir.rglob("workflows")]:
                    if workflows_dir.is_dir():
                        self._scan_workflows_dir(workflows_dir, _add)
            return results

        home_lam = lam_home()
        if home_lam.is_dir():
            workflows_dir = home_lam / "workflows"
            if workflows_dir.is_dir():
                self._scan_workflows_dir(workflows_dir, _add)
        for root in self._explicit_roots:
            workflows_dir = root / "workflows"
            if workflows_dir.is_dir():
                self._scan_workflows_dir(workflows_dir, _add)
        return results

    def _signature(self, work_root: str | None) -> tuple[tuple[str, int, int], ...]:
        """Stat every file inside every workflow folder + legacy files."""
        entries: list[tuple[str, int, int]] = []
        for path in self._workflow_entries(work_root):
            if path.is_dir():
                for f in path.rglob("*.json"):
                    try:
                        stat = f.stat()
                    except OSError:
                        continue
                    entries.append((str(f), stat.st_mtime_ns, stat.st_size))
            else:
                try:
                    stat = path.stat()
                except OSError:
                    continue
                entries.append((str(path), stat.st_mtime_ns, stat.st_size))
        return tuple(entries)

    # -- async API (mirrors ArrangeStore shape) ---------------------------

    async def list(self, *, work_root: str | None = None) -> list[WorkflowDef]:
        return await asyncio.to_thread(self.list_sync, work_root=work_root)

    def list_sync(self, *, work_root: str | None = None) -> list[WorkflowDef]:
        key = work_root or ""
        sig = self._signature(work_root)
        cached = self._cached.get(key)
        if cached is not None and cached[0] == sig:
            return cached[1]
        defs: list[WorkflowDef] = []
        for path in self._workflow_entries(work_root):
            definition = self._read_entry(path)
            if definition is not None:
                defs.append(definition)
        defs.sort(key=lambda item: item.name)
        self._cached[key] = (sig, defs)
        return defs

    def list_exposed_sync(self, *, work_root: str | None = None) -> list[WorkflowDef]:
        return [w for w in self.list_sync(work_root=work_root) if w.exposed]

    def list_grouped_sync(self, *, work_roots: list[str]) -> dict[str, list[WorkflowDef]]:
        """List workflows separated by source.

        Returns ``{"global": [...], "<work_root>": [...]}`` keyed by source.
        Workflows under ``~/.lam`` (and explicit roots) fall under ``"global"``;
        project workflows are bucketed under their ``work_root``.
        """
        grouped: dict[str, list[WorkflowDef]] = {"global": []}
        for wr in work_roots:
            if wr and wr not in grouped:
                grouped[wr] = []
        home_lam = lam_home().resolve()
        explicit = {p.resolve() for p in self._explicit_roots}
        candidates: list[Path] = []
        for p in self._workflow_entries(None):
            candidates.append(p)
        for wr in work_roots:
            if not wr:
                continue
            for p in self._workflow_entries(wr):
                if p not in candidates:
                    candidates.append(p)
        for path in candidates:
            definition = self._read_entry(path)
            if definition is None:
                continue
            key = "global"
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if home_lam in resolved.parents or resolved in explicit:
                key = "global"
            else:
                for wr in work_roots:
                    if not wr:
                        continue
                    try:
                        lam_dir = (Path(wr) / ".lam").resolve()
                    except OSError:
                        continue
                    if lam_dir in resolved.parents:
                        key = wr
                        break
            grouped.setdefault(key, []).append(definition)
        for bucket in grouped.values():
            bucket.sort(key=lambda item: item.name)
        return grouped

    async def list_grouped(self, *, work_roots: list[str]) -> dict[str, list[WorkflowDef]]:
        return await asyncio.to_thread(self.list_grouped_sync, work_roots=work_roots)

    async def get(self, name: str, *, work_root: str | None = None) -> WorkflowDef | None:
        target = name.strip()
        if not target:
            return None
        # Scoped lookup (matching delete): a project-scoped get must not
        # return the same-named global workflow (audit 11).
        candidates: list[WorkflowDef] = []
        for path in self._scoped_workflow_entries(work_root):
            definition = await self._read_entry_async(path)
            if definition is not None:
                candidates.append(definition)
        for definition in candidates:
            if definition.name == target:
                return definition
        slug = _ascii_slug(target)
        slug_matches = [d for d in candidates if _ascii_slug(d.name) == slug]
        return slug_matches[0] if len(slug_matches) == 1 else None

    def get_sync(self, name: str, *, work_root: str | None = None) -> WorkflowDef | None:
        target = name.strip()
        if not target:
            return None
        candidates: list[WorkflowDef] = []
        for path in self._scoped_workflow_entries(work_root):
            definition = self._read_entry(path)
            if definition is not None:
                candidates.append(definition)
        for definition in candidates:
            if definition.name == target:
                return definition
        slug = _ascii_slug(target)
        slug_matches = [d for d in candidates if _ascii_slug(d.name) == slug]
        return slug_matches[0] if len(slug_matches) == 1 else None

    async def get_by_id(self, workflow_id: str, *, work_root: str | None = None) -> WorkflowDef | None:
        return await asyncio.to_thread(self.get_by_id_sync, workflow_id, work_root=work_root)

    def get_by_id_sync(self, workflow_id: str, *, work_root: str | None = None) -> WorkflowDef | None:
        target = str(workflow_id or "").strip()
        if not target:
            return None
        # ID lookup must remain confined to the requested repository scope.
        # ``list(work_root=...)`` intentionally combines global and project
        # entries for discovery, so filtering that mixed result can select a
        # same-ID workflow from the wrong scope.
        for path in self._scoped_workflow_entries(work_root):
            definition = self._read_entry(path)
            if definition is not None and definition.id == target:
                return definition
        return None

    async def save(self, definition: WorkflowDef) -> WorkflowDef:
        if not definition.name:
            raise ValueError("workflow name is required")
        ensure_workflow_id(definition)
        self._cached.clear()
        definition.updated_at = _now()
        workflows_dir = self._writable_dir(definition.work_root)
        target_dir = workflows_dir / self._unique_writable_name(workflows_dir, definition.name)
        await asyncio.to_thread(self._write_folder, target_dir, definition)
        # A rename writes to a new name-derived folder. Remove the previous
        # folder only after the new definition is durable, and only when its
        # stable id matches. This keeps rename atomic from the reader's point
        # of view and never deletes an unrelated same-named workflow.
        for path in self._scoped_workflow_entries(definition.work_root):
            if path.resolve() == target_dir.resolve() or path.parent.resolve() != workflows_dir.resolve():
                continue
            existing = await self._read_entry_async(path)
            if existing is not None and existing.id == definition.id:
                await self._remove_entry(path)
        # Legacy single-JSON sources are retained intentionally.  The V2
        # folder is preferred on subsequent reads.
        return definition

    def _unique_writable_name(self, workflows_dir: Path, name: str) -> str:
        """Resolve a collision-free folder name for ``name``.

        Two names that fold to the same ``_safe_filename`` (e.g. ``lam的小实验``
        and ``lam的小实验！`` both folding to ``lam``) must not silently
        overwrite each other's folder — the second one gets a ``-2`` suffix
        (audit 11). Updates to the *same* workflow reuse its existing folder.
        """
        base = _safe_filename(name)
        candidate = base
        index = 2
        while (workflows_dir / candidate).exists():
            existing = self._read_entry(workflows_dir / candidate)
            if existing is not None and existing.name == name:
                break
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    async def delete(self, name: str, *, work_root: str | None = None) -> bool:
        target = name.strip()
        if not target:
            return False
        # Delete only within the requested scope: a project work_root must
        # never remove a same-named workflow from the global roots (and vice
        # versa) — the mixed-scope traversal of _workflow_entries would
        # silently rmtree the wrong copy (audit 11).
        candidates: list[tuple[Path, Any]] = []
        for path in self._scoped_workflow_entries(work_root):
            definition = await self._read_entry_async(path)
            if definition is not None:
                candidates.append((path, definition))

        # Exact name first — unambiguous by construction.
        for path, definition in candidates:
            if definition.name == target:
                return await self._remove_entry(path)
        # Slug fallback (unixy thread ids like ``wf_lam____``) only when the
        # slug is unique in scope; two names folding to one slug (e.g.
        # ``lam的小实验`` vs ``lam____``) must never let a delete hit the
        # wrong one (audit 11).
        slug = _ascii_slug(target)
        slug_matches = [(path, d) for path, d in candidates if _ascii_slug(d.name) == slug]
        if len(slug_matches) == 1:
            return await self._remove_entry(slug_matches[0][0])
        return False

    async def _remove_entry(self, path: Path) -> bool:
        removed = False
        if path.is_dir():
            await asyncio.to_thread(shutil.rmtree, path, True)
            removed = True
        else:
            try:
                await asyncio.to_thread(path.unlink, True)
                removed = True
            except OSError:
                pass
        if removed:
            self._cached.clear()
        return removed

    # -- internals --------------------------------------------------------

    def _writable_dir(self, work_root: str | None) -> Path:
        # Project-scoped writes go to {work_root}/.lam/workflows/.
        if work_root:
            return Path(work_root).resolve() / ".lam" / "workflows"
        # Otherwise the global personal dir.
        return lam_home() / "workflows"

    async def _read_entry_async(self, path: Path) -> WorkflowDef | None:
        return await asyncio.to_thread(self._read_entry, path)

    def _read_entry(self, path: Path) -> WorkflowDef | None:
        """Read a workflow definition from a folder or legacy single-JSON."""
        try:
            if path.is_dir() and ((path / "workflow.json").is_file() or (path / "config.json").is_file()):
                return self._read_folder(path)
        except OSError:
            return None
        return self._read_legacy_file(path)

    def _read_folder(self, folder: Path) -> WorkflowDef | None:
        # V2 is the canonical source whenever present.  Legacy files remain in
        # place for rollback/interchange but never form a second truth source.
        document_path = folder / "workflow.json"
        if document_path.is_file():
            try:
                raw_document = json.loads(_read_text(document_path))
                if is_v2_document(raw_document):
                    definition = workflow_def_from_document(raw_document)
                    ensure_workflow_id(definition, seed=str(folder.resolve()))
                    return definition
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                # A corrupt canonical document must not silently execute stale
                # legacy files from the same folder.
                return None
        config_path = folder / "config.json"
        try:
            data = json.loads(_read_text(config_path))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        # Edges: prefer the full edges array (preserves condition/transform);
        # fall back to parsing the map text (topology only, for old folders).
        edges_data = data.get("edges")
        if not edges_data:
            map_text = str(data.get("map") or "")
            edges_data = [e.to_dict() for e in _parse_map(map_text)] if map_text else []
        # Read each node file (corrupt files are skipped — isolation).
        node_dicts: list[dict[str, Any]] = []
        for node_path in sorted(folder.glob("*.json")):
            if node_path.name == "config.json":
                continue
            try:
                node_data = json.loads(_read_text(node_path))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(node_data, dict):
                node_dicts.append(node_data)
        merged = {**data, "nodes": node_dicts, "edges": edges_data}
        definition = WorkflowDef.from_dict(merged)
        ensure_workflow_id(definition, seed=str(folder.resolve()))
        definition.document = document_from_workflow_def(definition)
        return definition

    def _read_legacy_file(self, path: Path) -> WorkflowDef | None:
        """Read a legacy single-JSON file and lazily migrate it to a folder."""
        try:
            data = json.loads(_read_text(path))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        definition = WorkflowDef.from_dict(data)
        ensure_workflow_id(definition, seed=str(path.resolve()))
        # Migration is intentionally in-memory and non-destructive.  The next
        # explicit save writes canonical V2 while retaining this source file.
        definition.document = document_from_workflow_def(definition)
        return definition

    def _write_folder(self, folder: Path, definition: WorkflowDef) -> None:
        """Write config.json + one JSON per node into ``folder``."""
        folder.mkdir(parents=True, exist_ok=True)
        document = document_from_workflow_def(definition)
        definition.document = document
        _write_text_atomic(
            folder / "workflow.json",
            json.dumps(document, ensure_ascii=False, indent=2),
        )
        # config.json — meta + full edges array (source of truth, preserves
        # condition/transform) + human-readable map text (derived rendering).
        config: dict[str, Any] = {
            "id": definition.id,
            "name": definition.name,
            "description": definition.description,
            "input_params": [p.to_dict() for p in definition.input_params],
            "output_port": definition.output_port,
            "exposed": definition.exposed,
            "tool_name": definition.tool_name,
            "work_root": definition.work_root,
            "created_at": definition.created_at.isoformat(),
            "updated_at": definition.updated_at.isoformat(),
            "revision": definition.revision,
            "edges": [e.to_dict() for e in definition.edges],
            "map": _serialize_map(definition.edges, definition.nodes),
        }
        _write_text_atomic(folder / "config.json", json.dumps(config, ensure_ascii=False, indent=2))
        # One JSON per node (inputs/outputs arrays).
        written: set[Path] = {folder / "config.json", folder / "workflow.json"}
        for node in definition.nodes:
            node_path = folder / (_safe_filename(node.id) + ".json")
            inputs, outputs = _ports_to_io(node)
            node_data: dict[str, Any] = {
                "id": node.id,
                "kind": node.kind,
                "title": node.title,
                "inputs": inputs,
                "outputs": outputs,
                "config": _json_copy(node.config),
                "position": dict(node.position),
            }
            # Keep the canvas-only relationship in the folder's legacy node
            # representation too.  ``workflow.json`` remains canonical, but
            # old-folder readers may have no V2 document to consult.
            if node.parent_id:
                node_data["parent_id"] = node.parent_id
            _write_text_atomic(node_path, json.dumps(node_data, ensure_ascii=False, indent=2))
            written.add(node_path)
        # Do not delete legacy node files during V2 migration.  Readers use
        # workflow.json exclusively, so retained files cannot become a second
        # source of truth and remain available for rollback/recovery.


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _write_text_atomic(path: Path, text: str) -> None:
    """Write text via a temp file then rename (atomic on most OSes)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _safe_filename(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in {"-", "_"} else "_" for c in name).strip("_")
    return safe or "workflow"


def _ascii_slug(name: str) -> str:
    """ASCII-only slug mirroring the frontend thread-id derivation.

    The frontend builds the agent session id as ``wf_<slug>`` where slug replaces
    every non ``[a-zA-Z0-9_-]`` char with ``_`` (so Chinese/unicode chars collapse).
    The build tools strip the ``wf_`` prefix and look the workflow up by the
    remaining slug. Since stored workflow names keep their original unicode
    (e.g. ``lam的小实验``) while the thread id became ``wf_lam____``, an exact-name
    match misses. This function lets ``get``/``delete`` fall back to a slug
    comparison so both sides meet in the middle.
    """
    import re

    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name or "").strip("_")
    return safe or "workflow"


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


__all__ = ["WorkflowStore"]
