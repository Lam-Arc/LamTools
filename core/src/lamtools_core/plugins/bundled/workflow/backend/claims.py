"""SQLite-backed cross-process claims for durable workflow execution.

Claims are internal coordination records.  They never enter workflow payloads
or event data.  SQLite ``BEGIN IMMEDIATE`` plus a monotonically increasing
fencing token provides one active owner per durable namespace/run boundary.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


ClaimKind = Literal["run", "signal"]


@dataclass(frozen=True)
class WorkflowClaimLease:
    namespace: str
    kind: ClaimKind
    thread_id: str
    run_id: str
    owner_id: str
    fencing_token: int
    lease_expires_at: float


@dataclass(frozen=True)
class ClaimAcquireResult:
    state: Literal["acquired", "busy", "completed", "mismatch"]
    lease: WorkflowClaimLease | None = None
    retry_at: float = 0.0
    result: dict[str, Any] | None = None


class WorkflowClaimStore:
    """Transactional lease/CAS store scoped to one workflow SQLite file."""

    def __init__(
        self,
        path: str | Path,
        *,
        namespace: str,
        lease_seconds: float = 15.0,
        max_completed_claims: int = 1024,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.namespace = str(namespace)
        self.lease_seconds = max(1.0, float(lease_seconds))
        self.max_completed_claims = max(16, int(max_completed_claims))
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if not self._initialized:
                await asyncio.to_thread(self._initialize_sync)
                self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize_sync(self) -> None:
        last_error: sqlite3.OperationalError | None = None
        for _ in range(100):
            try:
                with self._connect() as connection:
                    connection.execute("PRAGMA journal_mode=WAL")
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS workflow_claims (
                            namespace TEXT NOT NULL,
                            claim_kind TEXT NOT NULL,
                            thread_id TEXT NOT NULL,
                            run_id TEXT NOT NULL,
                            owner_id TEXT NOT NULL,
                            fencing_token INTEGER NOT NULL,
                            lease_expires_at REAL NOT NULL,
                            status TEXT NOT NULL,
                            result_json TEXT,
                            request_fingerprint TEXT,
                            updated_at REAL NOT NULL,
                            PRIMARY KEY (namespace, claim_kind, thread_id, run_id)
                        )
                        """
                    )
                    columns = {
                        str(row[1])
                        for row in connection.execute("PRAGMA table_info(workflow_claims)")
                    }
                    if "request_fingerprint" not in columns:
                        connection.execute(
                            "ALTER TABLE workflow_claims ADD COLUMN request_fingerprint TEXT"
                        )
                    connection.execute(
                        "CREATE INDEX IF NOT EXISTS ix_workflow_claims_cleanup "
                        "ON workflow_claims(namespace, claim_kind, status, updated_at)"
                    )
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                last_error = exc
                time.sleep(0.05)
        if last_error is not None:
            raise last_error

    async def acquire(
        self,
        kind: ClaimKind,
        thread_id: str,
        run_id: str,
        *,
        owner_id: str | None = None,
        request_fingerprint: str | None = None,
    ) -> ClaimAcquireResult:
        await self.initialize()
        return await asyncio.to_thread(
            self._acquire_sync,
            kind,
            str(thread_id),
            str(run_id),
            owner_id or uuid.uuid4().hex,
            str(request_fingerprint or ""),
        )

    def _acquire_sync(
        self,
        kind: ClaimKind,
        thread_id: str,
        run_id: str,
        owner_id: str,
        request_fingerprint: str,
    ) -> ClaimAcquireResult:
        now = time.time()
        expires = now + self.lease_seconds
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT owner_id, fencing_token, lease_expires_at, status, result_json, "
                "request_fingerprint "
                "FROM workflow_claims WHERE namespace=? AND claim_kind=? AND thread_id=? AND run_id=?",
                (self.namespace, kind, thread_id, run_id),
            ).fetchone()
            if row is None:
                fence = 1
                connection.execute(
                    "INSERT INTO workflow_claims "
                    "(namespace, claim_kind, thread_id, run_id, owner_id, fencing_token, "
                    "lease_expires_at, status, result_json, request_fingerprint, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', NULL, ?, ?)",
                    (
                        self.namespace, kind, thread_id, run_id, owner_id, fence, expires,
                        request_fingerprint, now,
                    ),
                )
                connection.commit()
                return ClaimAcquireResult(
                    "acquired",
                    lease=WorkflowClaimLease(
                        self.namespace, kind, thread_id, run_id, owner_id, fence, expires
                    ),
                )
            current_owner, fence, current_expiry, status, result_json, stored_fingerprint = row
            if status == "completed":
                connection.commit()
                if not request_fingerprint or stored_fingerprint != request_fingerprint:
                    return ClaimAcquireResult("mismatch")
                try:
                    result = json.loads(result_json) if result_json else None
                except (TypeError, ValueError):
                    result = None
                return ClaimAcquireResult("completed", result=result if isinstance(result, dict) else None)
            if float(current_expiry) <= now:
                next_fence = int(fence) + 1
                connection.execute(
                    "UPDATE workflow_claims SET owner_id=?, fencing_token=?, lease_expires_at=?, "
                    "status='active', result_json=NULL, request_fingerprint=?, updated_at=? "
                    "WHERE namespace=? AND claim_kind=? AND thread_id=? AND run_id=?",
                    (
                        owner_id, next_fence, expires, request_fingerprint, now,
                        self.namespace, kind, thread_id, run_id,
                    ),
                )
                connection.commit()
                return ClaimAcquireResult(
                    "acquired",
                    lease=WorkflowClaimLease(
                        self.namespace, kind, thread_id, run_id, owner_id, next_fence, expires
                    ),
                )
            connection.commit()
            return ClaimAcquireResult("busy", retry_at=float(current_expiry))
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def renew(self, lease: WorkflowClaimLease) -> WorkflowClaimLease | None:
        await self.initialize()
        return await asyncio.to_thread(self._renew_sync, lease)

    def _renew_sync(self, lease: WorkflowClaimLease) -> WorkflowClaimLease | None:
        now = time.time()
        expires = now + self.lease_seconds
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE workflow_claims SET lease_expires_at=?, updated_at=? "
                "WHERE namespace=? AND claim_kind=? AND thread_id=? AND run_id=? "
                "AND owner_id=? AND fencing_token=? AND status='active'",
                (
                    expires, now, lease.namespace, lease.kind, lease.thread_id, lease.run_id,
                    lease.owner_id, lease.fencing_token,
                ),
            )
            connection.commit()
            if cursor.rowcount != 1:
                return None
        return WorkflowClaimLease(
            lease.namespace, lease.kind, lease.thread_id, lease.run_id,
            lease.owner_id, lease.fencing_token, expires,
        )

    async def complete(self, lease: WorkflowClaimLease, result: dict[str, Any]) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._complete_sync, lease, result)

    def _complete_sync(self, lease: WorkflowClaimLease, result: dict[str, Any]) -> bool:
        now = time.time()
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE workflow_claims SET status='completed', result_json=?, lease_expires_at=0, updated_at=? "
                "WHERE namespace=? AND claim_kind=? AND thread_id=? AND run_id=? "
                "AND owner_id=? AND fencing_token=? AND status='active'",
                (
                    encoded, now, lease.namespace, lease.kind, lease.thread_id, lease.run_id,
                    lease.owner_id, lease.fencing_token,
                ),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    "DELETE FROM workflow_claims WHERE rowid IN ("
                    "SELECT rowid FROM workflow_claims WHERE namespace=? AND claim_kind=? "
                    "AND status='completed' ORDER BY updated_at DESC LIMIT -1 OFFSET ?)",
                    (lease.namespace, lease.kind, self.max_completed_claims),
                )
            connection.commit()
            return cursor.rowcount == 1

    async def release(self, lease: WorkflowClaimLease) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._release_sync, lease)

    def _release_sync(self, lease: WorkflowClaimLease) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM workflow_claims WHERE namespace=? AND claim_kind=? AND thread_id=? AND run_id=? "
                "AND owner_id=? AND fencing_token=? AND status='active'",
                (
                    lease.namespace, lease.kind, lease.thread_id, lease.run_id,
                    lease.owner_id, lease.fencing_token,
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    async def count(self) -> int:
        await self.initialize()
        return await asyncio.to_thread(self._count_sync)

    def _count_sync(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM workflow_claims WHERE namespace=?", (self.namespace,)
            ).fetchone()
        return int(row[0] if row else 0)


def claim_store_for_runtime(event_store: Any, snapshot_store: Any) -> WorkflowClaimStore | None:
    candidate = getattr(event_store, "directory", None) or getattr(snapshot_store, "directory", None)
    if candidate is None:
        return None
    base = Path(candidate).expanduser().resolve()
    # Event/snapshot directories are siblings under the workflow state root.
    workflow_root = base.parent if base.name in {"events", "snapshots"} else base
    namespace = str(workflow_root).casefold()
    return WorkflowClaimStore(workflow_root / "claims.sqlite3", namespace=namespace)


__all__ = [
    "ClaimAcquireResult",
    "WorkflowClaimLease",
    "WorkflowClaimStore",
    "claim_store_for_runtime",
]
