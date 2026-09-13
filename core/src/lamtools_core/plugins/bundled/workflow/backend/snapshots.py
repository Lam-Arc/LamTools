"""Durable workflow run snapshots.

Snapshots are intentionally separate from workflow definitions and queue
records.  They contain the value table and per-node state needed to continue a
paused/interrupted graph after the Python process is restarted; no Core config
database or implicit agent session is involved.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported only for static checkers
    from .runtime import WorkflowRunResult


class WorkflowSnapshotStore:
    """JSON-file snapshot store keyed by ``thread_id`` and ``run_id``."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        path: str | Path | None = None,
        store_path: str | Path | None = None,
        data_dir: str | Path | None = None,
    ) -> None:
        path = path or store_path
        if path is not None:
            candidate = Path(path).expanduser().resolve()
            self.directory = candidate if candidate.suffix.lower() != ".json" else candidate.parent / "snapshots"
            self._single_path = candidate if candidate.suffix.lower() == ".json" else None
        elif root is not None:
            self.directory = Path(root).expanduser().resolve() / ".lam" / "workflow" / "snapshots"
            self._single_path = None
        elif data_dir is not None:
            self.directory = Path(data_dir).expanduser().resolve() / "workflow" / "snapshots"
            self._single_path = None
        else:
            self.directory = Path(".lam/workflow/snapshots").resolve()
            self._single_path = None
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._loaded: set[tuple[str, str]] = set()
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(thread_id: str, run_id: str) -> tuple[str, str]:
        return (str(thread_id or ""), str(run_id or ""))

    def snapshot_path(self, thread_id: str, run_id: str) -> Path:
        key = f"{thread_id}\x00{run_id}".encode("utf-8", errors="replace")
        digest = hashlib.sha256(key).hexdigest()
        return self.directory / f"{digest}.json"

    def _load_sync(self, thread_id: str, run_id: str) -> dict[str, Any] | None:
        key = self._key(thread_id, run_id)
        if key in self._loaded:
            value = self._cache.get(key)
            return _json_copy(value) if value is not None else None
        self._loaded.add(key)
        path = self._single_path if self._single_path is not None else self.snapshot_path(*key)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if not isinstance(value, dict):
            return None
        self._cache[key] = value
        return _json_copy(value)

    def _write_sync(self, thread_id: str, run_id: str, value: Mapping[str, Any]) -> None:
        key = self._key(thread_id, run_id)
        path = self._single_path if self._single_path is not None else self.snapshot_path(*key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".workflow-snapshot-", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, default=str)
                handle.flush()
                os.fsync(handle.fileno())
            Path(name).replace(path)
        finally:
            try:
                Path(name).unlink(missing_ok=True)
            except OSError:
                pass

    async def get(self, thread_id: str, run_id: str) -> "WorkflowRunResult | None":
        async with self._lock:
            raw = await asyncio.to_thread(self._load_sync, thread_id, run_id)
        if raw is None:
            return None
        from .runtime import WorkflowRunResult

        try:
            return WorkflowRunResult.from_dict(raw.get("result", raw))
        except (TypeError, ValueError, KeyError):
            return None

    async def get_dict(self, thread_id: str, run_id: str) -> dict[str, Any] | None:
        async with self._lock:
            value = await asyncio.to_thread(self._load_sync, thread_id, run_id)
        return value

    async def save(
        self,
        thread_id: str,
        run_id: str,
        result: "WorkflowRunResult | Mapping[str, Any]",
        *,
        workflow_id: str = "",
        workflow_name: str = "",
        workflow_revision: int = 0,
        definition_digest: str = "",
        workflow_definition: Mapping[str, Any] | None = None,
        inputs: Mapping[str, Any] | None = None,
    ) -> None:
        if hasattr(result, "to_dict"):
            result_dict = result.to_dict()  # type: ignore[union-attr]
        elif isinstance(result, Mapping):
            result_dict = dict(result)
        else:
            raise TypeError("workflow snapshot result must be a WorkflowRunResult or object")
        value = {
            "version": 2,
            "thread_id": str(thread_id or ""),
            "run_id": str(run_id or ""),
            "workflow_id": str(workflow_id or ""),
            "workflow_name": str(workflow_name or ""),
            "workflow_revision": max(0, int(workflow_revision)),
            "definition_digest": str(definition_digest or ""),
            "workflow_definition": _json_copy(dict(workflow_definition or {})),
            "inputs": _json_copy(dict(inputs or {})),
            "result": _json_copy(result_dict),
        }
        async with self._lock:
            self._cache[self._key(thread_id, run_id)] = value
            self._loaded.add(self._key(thread_id, run_id))
            try:
                await asyncio.to_thread(self._write_sync, thread_id, run_id, value)
            except OSError:
                # Snapshot durability is best effort at the filesystem layer;
                # an unavailable cache path must not fail the workflow itself.
                pass

    async def delete(self, thread_id: str, run_id: str) -> bool:
        key = self._key(thread_id, run_id)
        async with self._lock:
            self._cache.pop(key, None)
            self._loaded.add(key)
            path = self._single_path if self._single_path is not None else self.snapshot_path(*key)
            try:
                await asyncio.to_thread(path.unlink, missing_ok=True)
            except OSError:
                return False
            return True

    async def list(self) -> list[dict[str, Any]]:
        async with self._lock:
            try:
                paths = list(self.directory.glob("*.json"))
            except OSError:
                paths = []
            values: list[dict[str, Any]] = []
            for path in paths:
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    continue
                if isinstance(raw, dict):
                    values.append(raw)
            return values

    async def clear(self, *, confirm: bool = False) -> int:
        if not confirm:
            raise ValueError("clearing workflow snapshots requires confirm=True")
        async with self._lock:
            try:
                paths = list(self.directory.glob("*.json"))
            except OSError:
                paths = []
            count = 0
            for path in paths:
                try:
                    path.unlink()
                    count += 1
                except OSError:
                    pass
            self._cache.clear()
            self._loaded.clear()
            return count


WorkflowRunSnapshotStore = WorkflowSnapshotStore


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return value


__all__ = ["WorkflowRunSnapshotStore", "WorkflowSnapshotStore"]
