"""Content-addressed cache for explicitly pure, deterministic workflow nodes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkflowCacheLookup:
    """Result of a cache lookup with an explicit hit/miss/bypass status."""

    status: str
    key: str = ""
    value: Any = None

    @property
    def hit(self) -> bool:
        return self.status == "hit"

    def to_dict(self) -> dict[str, Any]:
        data = {"status": self.status, "key": self.key, "hit": self.hit}
        if self.hit:
            data["value"] = _json_copy(self.value)
        return data


def canonical_json(value: Any) -> str:
    """Serialize JSON-compatible content into a stable signature string."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def content_signature(
    *,
    workflow_id: str,
    workflow_revision: int,
    node_id: str,
    node_kind: str,
    node_config: Mapping[str, Any] | None,
    bound_inputs: Mapping[str, Any] | None,
) -> str:
    """Build a stable SHA-256 key from all computation-relevant content."""
    payload = {
        "version": 1,
        "workflow_id": workflow_id,
        "workflow_revision": int(workflow_revision or 0),
        "node_id": node_id,
        "node_kind": node_kind,
        "config": dict(node_config or {}),
        "inputs": dict(bound_inputs or {}),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class WorkflowContentCache:
    """Small JSON-backed cache with an in-memory mode for standalone runners.

    ``root`` may be a directory (the cache is written to
    ``<root>/.lam/workflow/cache.json``) or an explicit ``*.json`` path.  No
    cache file is written when ``root`` is omitted, which keeps direct library
    use side-effect free while still allowing plugin runtimes to opt into
    durable entries.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        path: str | Path | None = None,
        store_path: str | Path | None = None,
    ) -> None:
        path = path or store_path
        if path is not None:
            self.path: Path | None = Path(path).expanduser().resolve()
        elif root is None:
            self.path = None
        else:
            candidate = Path(root).expanduser().resolve()
            self.path = candidate if candidate.suffix.lower() == ".json" else candidate / ".lam" / "workflow" / "cache.json"
        self._entries: dict[str, Any] = {}
        self._loaded = False
        self._lock = asyncio.Lock()

    def _load_sync(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self.path is None or not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                entries = raw.get("entries", raw)
                if isinstance(entries, dict):
                    self._entries = {
                        str(key): value.get("value") if isinstance(value, dict) and "value" in value else value
                        for key, value in entries.items()
                    }
        except (OSError, ValueError, TypeError):
            # A corrupt cache is disposable; it must never break a workflow run.
            self._entries = {}

    def _write_sync(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "entries": _json_copy(self._entries)}
        fd, name = tempfile.mkstemp(prefix=".workflow-cache-", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            Path(name).replace(self.path)
        finally:
            try:
                Path(name).unlink(missing_ok=True)
            except OSError:
                pass

    async def lookup(self, key: str) -> WorkflowCacheLookup:
        if not key:
            return WorkflowCacheLookup(status="miss")
        async with self._lock:
            self._load_sync()
            if key not in self._entries:
                return WorkflowCacheLookup(status="miss", key=key)
            return WorkflowCacheLookup(status="hit", key=key, value=_json_copy(self._entries[key]))

    async def get(self, key: str, default: Any = None) -> Any:
        lookup = await self.lookup(key)
        return lookup.value if lookup.hit else default

    async def set(self, key: str, value: Any) -> None:
        if not key:
            return
        # Cache entries must be portable JSON values.  If a node returns a
        # non-JSON object, skip caching rather than inventing a lossy encoding.
        try:
            copied = json.loads(json.dumps(value, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            return
        async with self._lock:
            self._load_sync()
            self._entries[key] = copied
            try:
                self._write_sync()
            except OSError:
                # Cache persistence is best effort; a failed write must not
                # turn a successful node into a failed workflow.
                pass

    async def delete(self, key: str) -> bool:
        async with self._lock:
            self._load_sync()
            if key not in self._entries:
                return False
            del self._entries[key]
            try:
                self._write_sync()
            except OSError:
                pass
            return True

    async def clear(self, *, confirm: bool = False) -> int:
        if not confirm:
            raise ValueError("clearing workflow cache requires confirm=True")
        async with self._lock:
            self._load_sync()
            count = len(self._entries)
            self._entries.clear()
            try:
                self._write_sync()
            except OSError:
                pass
            return count

    async def list(self) -> list[dict[str, Any]]:
        async with self._lock:
            self._load_sync()
            return [{"key": key, "value": _json_copy(value)} for key, value in self._entries.items()]

    # Synchronous helpers make the store convenient in diagnostic tooling and
    # preserve the naming style of WorkflowStore.
    def lookup_sync(self, key: str) -> WorkflowCacheLookup:
        self._load_sync()
        if key not in self._entries:
            return WorkflowCacheLookup(status="miss", key=key)
        return WorkflowCacheLookup(status="hit", key=key, value=_json_copy(self._entries[key]))

    def clear_sync(self, *, confirm: bool = False) -> int:
        if not confirm:
            raise ValueError("clearing workflow cache requires confirm=True")
        self._load_sync()
        count = len(self._entries)
        self._entries.clear()
        try:
            self._write_sync()
        except OSError:
            pass
        return count


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return value


__all__ = [
    "WorkflowCacheLookup",
    "WorkflowContentCache",
    "canonical_json",
    "content_signature",
]
