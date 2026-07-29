"""File-backed workflow definitions.

Mirrors the :class:`~lamtools_core.skills.SkillRegistry` discovery pattern:
workflow definitions are JSON files discovered under a small set of roots
that are scanned lazily and cached by mtime signature. Roots:

* Project: ``{work_root}/.lam/workflows/*.json``
* Global personal: ``~/.lam/workflows/*.json``
* Explicit roots passed at construction (e.g. app-shipped defaults).

The ``exposed`` flag lives inside each definition file (single source of
truth), so exposing a workflow is just toggling a JSON field and re-saving.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from lamtools_core.runtime.workflow import WorkflowDef


class WorkflowStore:
    """Discovers, reads, and writes workflow definition JSON files."""

    def __init__(self, *, explicit_roots: Iterable[str | Path] = ()) -> None:
        self._explicit_roots = tuple(Path(item).resolve() for item in explicit_roots)
        self._cached_signature: tuple[tuple[str, int, int], ...] | None = None
        self._cached_defs: list[WorkflowDef] | None = None

    # -- discovery --------------------------------------------------------

    def _candidate_files(self, work_root: str | None) -> list[Path]:
        roots: list[Path] = []
        home = Path.home()
        home_lam = home / ".lam"
        if home_lam.is_dir():
            roots.append(home_lam)
        roots.extend(self._explicit_roots)

        seen: set[Path] = set()
        results: list[Path] = []

        def _add(path: Path) -> None:
            resolved = path.resolve()
            if resolved not in seen and resolved.is_file():
                seen.add(resolved)
                results.append(resolved)

        # Global: {root}/workflows/*.json (one level deep)
        for root in roots:
            if root.is_dir():
                for p in root.glob("workflows/*.json"):
                    _add(p)
        # Project: {work_root}/.lam/workflows/**/*.json (recursive)
        if work_root:
            lam_dir = Path(work_root).resolve() / ".lam"
            if lam_dir.is_dir():
                for p in lam_dir.rglob("workflows/*.json"):
                    _add(p)
        return results

    def _signature(self, work_root: str | None) -> tuple[tuple[str, int, int], ...]:
        entries: list[tuple[str, int, int]] = []
        for path in self._candidate_files(work_root):
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
        sig = self._signature(work_root)
        if self._cached_signature == sig and self._cached_defs is not None:
            return self._cached_defs
        defs: list[WorkflowDef] = []
        for path in self._candidate_files(work_root):
            definition = self._read_sync(path)
            if definition is not None:
                defs.append(definition)
        defs.sort(key=lambda item: item.name)
        self._cached_signature = sig
        self._cached_defs = defs
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
        home_lam = (Path.home() / ".lam").resolve()
        explicit = {p.resolve() for p in self._explicit_roots}
        seen_names: set[str] = set()
        # Collect candidates from global + every project work_root.
        candidates: list[Path] = []
        for p in self._candidate_files(None):
            candidates.append(p)
        for wr in work_roots:
            if not wr:
                continue
            for p in self._candidate_files(wr):
                if p not in candidates:
                    candidates.append(p)
        for path in candidates:
            definition = self._read_sync(path)
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
            if definition.name in seen_names:
                continue
            seen_names.add(definition.name)
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
        for definition in await self.list(work_root=work_root):
            if definition.name == target:
                return definition
        return None

    def get_sync(self, name: str, *, work_root: str | None = None) -> WorkflowDef | None:
        target = name.strip()
        if not target:
            return None
        for definition in self.list_sync(work_root=work_root):
            if definition.name == target:
                return definition
        return None

    async def save(self, definition: WorkflowDef) -> WorkflowDef:
        if not definition.name:
            raise ValueError("workflow name is required")
        self._cached_signature = None
        self._cached_defs = None
        work_root = definition.work_root
        target_dir = self._writable_dir(work_root)
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = _safe_filename(definition.name) + ".json"
        target = target_dir / filename
        definition.updated_at = _now()
        payload = definition.to_dict()
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        await asyncio.to_thread(_write_text, target, text)
        return definition

    async def delete(self, name: str, *, work_root: str | None = None) -> bool:
        target = name.strip()
        if not target:
            return False
        removed = False
        for path in list(self._candidate_files(work_root)):
            definition = await self._read(path)
            if definition is not None and definition.name == target:
                try:
                    await asyncio.to_thread(path.unlink)
                    removed = True
                except OSError:
                    pass
        if removed:
            self._cached_signature = None
            self._cached_defs = None
        return removed

    # -- internals --------------------------------------------------------

    def _writable_dir(self, work_root: str | None) -> Path:
        # Project-scoped writes go to {work_root}/.lam/workflows/.
        if work_root:
            return Path(work_root).resolve() / ".lam" / "workflows"
        # Otherwise the global personal dir.
        return Path.home() / ".lam" / "workflows"

    async def _read(self, path: Path) -> WorkflowDef | None:
        return self._read_sync(path)

    def _read_sync(self, path: Path) -> WorkflowDef | None:
        try:
            text = _read_text(path)
        except OSError:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        return WorkflowDef.from_dict(data)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _safe_filename(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in {"-", "_"} else "_" for c in name).strip("_")
    return safe or "workflow"


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


__all__ = ["WorkflowStore"]
