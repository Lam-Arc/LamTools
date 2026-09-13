"""Workflow flow-control policy contracts and the local SQLite coordinator.

The policy objects in this module are deliberately independent from the
workflow runner.  A runner can consume the canonical dictionary (or the
typed :class:`FlowControlPolicy`) without having to know about document
aliases, and a later integration can use :class:`FlowControlStore` as the
cross-process coordination boundary.

Only local SQLite state is used.  Each operation opens a short-lived
connection and commits one ``BEGIN IMMEDIATE`` transaction; this is important
for two desktop/worker processes sharing a workflow directory.  A blocked
acquisition returns a decision with ``retry_at`` instead of spinning or
sleeping inside the store.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import sqlite3
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


class FlowControlError(ValueError):
    """Base error for malformed flow-control contracts."""


FlowControlPolicyError = FlowControlError


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _positive_number(value: Any, path: str) -> float:
    if not _is_number(value) or not math.isfinite(float(value)) or float(value) <= 0:
        raise FlowControlError(f"{path} must be a finite positive number")
    return float(value)


def _positive_integer(value: Any, path: str) -> int:
    # Accept an integral float from JSON producers, but do not accept numeric
    # strings or booleans.  This keeps canonicalisation strict while avoiding
    # a surprising rejection of ``2.0`` emitted by some editors.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FlowControlError(f"{path} must be a positive integer")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise FlowControlError(f"{path} must be a positive integer")
    result = int(value)
    if result < 1:
        raise FlowControlError(f"{path} must be a positive integer")
    return result


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FlowControlError(f"{path} must be an integer")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise FlowControlError(f"{path} must be an integer")
    return int(value)


def _safe_key(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FlowControlError(f"{path} must be a non-empty string")
    result = value.strip()
    if len(result) > 512 or any(ord(char) < 32 for char in result):
        raise FlowControlError(f"{path} must be a bounded printable string")
    return result


def _object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FlowControlError(f"{path} must be an object")
    return value


def _single_alias(
    value: Mapping[str, Any],
    canonical: str,
    aliases: tuple[str, ...],
    path: str,
) -> tuple[bool, Any]:
    present = [name for name in (canonical, *aliases) if name in value]
    if len(present) > 1:
        # Multiple spellings are only safe when they carry exactly the same
        # JSON value.  Rejecting conflicting aliases makes a stale editor
        # field visible instead of silently choosing one.
        first = value[present[0]]
        if any(value[name] != first for name in present[1:]):
            raise FlowControlError(f"{path} contains conflicting aliases: {', '.join(present)}")
    return (bool(present), value[present[0]] if present else None)


@dataclass(frozen=True, slots=True)
class ConcurrencyPolicy:
    """A named concurrency bucket and its maximum active leases."""

    key: str
    max: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _safe_key(self.key, "concurrency.key"))
        object.__setattr__(self, "max", _positive_integer(self.max, "concurrency.max"))

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "max": self.max}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConcurrencyPolicy":
        raw = _object(value, "concurrency")
        if set(raw) != {"key", "max"}:
            raise FlowControlError("concurrency requires exactly key and max")
        return cls(raw["key"], raw["max"])


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """Sliding-window admission limit."""

    count: int
    window_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "count", _positive_integer(self.count, "rate_limit.count"))
        object.__setattr__(
            self,
            "window_seconds",
            _positive_number(self.window_seconds, "rate_limit.window_seconds"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"count": self.count, "window_seconds": self.window_seconds}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RateLimitPolicy":
        raw = _object(value, "rate_limit")
        if set(raw) != {"count", "window_seconds"}:
            raise FlowControlError("rate_limit requires exactly count and window_seconds")
        return cls(raw["count"], raw["window_seconds"])


@dataclass(frozen=True, slots=True)
class ThrottlePolicy:
    """Minimum time between accepted acquisitions in a bucket."""

    min_interval_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "min_interval_seconds",
            _positive_number(self.min_interval_seconds, "throttle.min_interval_seconds"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"min_interval_seconds": self.min_interval_seconds}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ThrottlePolicy":
        raw = _object(value, "throttle")
        if set(raw) != {"min_interval_seconds"}:
            raise FlowControlError("throttle requires exactly min_interval_seconds")
        return cls(raw["min_interval_seconds"])


DebounceMode = Literal["leading", "trailing"]


@dataclass(frozen=True, slots=True)
class DebouncePolicy:
    """A reservation that suppresses duplicate submissions for a quiet window."""

    window_seconds: float
    mode: DebounceMode = "trailing"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "window_seconds",
            _positive_number(self.window_seconds, "debounce.window_seconds"),
        )
        mode = str(self.mode).strip().lower()
        if mode in {"first", "head"}:
            mode = "leading"
        elif mode in {"last", "tail"}:
            mode = "trailing"
        if mode not in {"leading", "trailing"}:
            raise FlowControlError("debounce.mode must be 'leading' or 'trailing'")
        object.__setattr__(self, "mode", mode)

    def to_dict(self) -> dict[str, Any]:
        return {"window_seconds": self.window_seconds, "mode": self.mode}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DebouncePolicy":
        raw = _object(value, "debounce")
        if set(raw) != {"window_seconds", "mode"}:
            raise FlowControlError("debounce requires exactly window_seconds and mode")
        return cls(raw["window_seconds"], raw["mode"])


@dataclass(frozen=True, slots=True)
class FlowControlPolicy:
    """Canonical workflow-level flow-control policy.

    Every member is optional so an empty policy remains a valid projection of
    old workflow documents.  ``priority`` is intentionally signed: queues
    may use negative values for low-priority work while the default remains
    zero.
    """

    concurrency: ConcurrencyPolicy | None = None
    rate_limit: RateLimitPolicy | None = None
    throttle: ThrottlePolicy | None = None
    debounce: DebouncePolicy | None = None
    priority: int = 0
    _priority_present: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.concurrency, Mapping):
            object.__setattr__(self, "concurrency", ConcurrencyPolicy.from_dict(self.concurrency))
        if isinstance(self.rate_limit, Mapping):
            object.__setattr__(self, "rate_limit", RateLimitPolicy.from_dict(self.rate_limit))
        if isinstance(self.throttle, Mapping):
            object.__setattr__(self, "throttle", ThrottlePolicy.from_dict(self.throttle))
        if isinstance(self.debounce, Mapping):
            object.__setattr__(self, "debounce", DebouncePolicy.from_dict(self.debounce))
        for name in ("concurrency", "rate_limit", "throttle", "debounce"):
            candidate = getattr(self, name)
            if candidate is not None and not isinstance(
                candidate,
                {
                    "concurrency": ConcurrencyPolicy,
                    "rate_limit": RateLimitPolicy,
                    "throttle": ThrottlePolicy,
                    "debounce": DebouncePolicy,
                }[name],
            ):
                raise FlowControlError(f"{name} must be a policy object")
        object.__setattr__(self, "priority", _integer(self.priority, "priority"))
        object.__setattr__(self, "_priority_present", bool(self._priority_present))

    @property
    def enabled(self) -> bool:
        return any((self.concurrency, self.rate_limit, self.throttle, self.debounce))

    @classmethod
    def empty(cls) -> "FlowControlPolicy":
        return cls()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | "FlowControlPolicy" | None) -> "FlowControlPolicy":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        raw = _object(value, "flow_control")
        canonical: dict[str, Any] = {}
        aliases = {
            "flow_control": "__wrapper__",
            "flowControl": "__wrapper__",
            "rateLimit": "rate_limit",
            "rate-limit": "rate_limit",
            "rateLimitPolicy": "rate_limit",
            "minInterval": "throttle",
            "minIntervalSeconds": "throttle",
            "debouncePolicy": "debounce",
        }
        wrappers = [raw[key] for key in ("flow_control", "flowControl") if key in raw]
        if wrappers:
            if len(wrappers) > 1 and wrappers[0] != wrappers[1]:
                raise FlowControlError("flow_control contains conflicting wrapper aliases")
            wrapped = _object(wrappers[0], "flow_control")
            outer = {key: item for key, item in raw.items() if key not in {"flow_control", "flowControl"}}
            if outer:
                raise FlowControlError("flow_control wrapper cannot be combined with sibling fields")
            return cls.from_dict(wrapped)
        for key in raw:
            clean = aliases.get(str(key), str(key))
            if clean in canonical and canonical[clean] != raw[key]:
                raise FlowControlError(f"flow_control contains conflicting aliases for {clean}")
            canonical[clean] = raw[key]
        allowed = {"concurrency", "rate_limit", "throttle", "debounce", "priority"}
        unknown = sorted(set(canonical) - allowed)
        if unknown:
            raise FlowControlError(f"flow_control has unsupported field(s): {', '.join(unknown)}")

        concurrency = None
        if "concurrency" in canonical:
            if canonical["concurrency"] is None:
                raise FlowControlError("concurrency must be an object")
            item = _object(canonical["concurrency"], "concurrency")
            present_key, key = _single_alias(item, "key", (), "concurrency")
            present_max, maximum = _single_alias(item, "max", ("max_concurrency",), "concurrency")
            if not present_key or not present_max:
                raise FlowControlError("concurrency requires key and max")
            nested_allowed = {"key", "max", "max_concurrency"}
            unknown_nested = sorted(set(item) - nested_allowed)
            if unknown_nested:
                raise FlowControlError(
                    f"concurrency has unsupported field(s): {', '.join(map(str, unknown_nested))}"
                )
            concurrency = ConcurrencyPolicy(key, _positive_integer(maximum, "concurrency.max"))

        rate_limit = None
        if "rate_limit" in canonical:
            if canonical["rate_limit"] is None:
                raise FlowControlError("rate_limit must be an object")
            item = _object(canonical["rate_limit"], "rate_limit")
            present_count, count = _single_alias(item, "count", (), "rate_limit")
            present_window, window = _single_alias(
                item, "window_seconds", ("windowSeconds",), "rate_limit"
            )
            if not present_count or not present_window:
                raise FlowControlError("rate_limit requires count and window_seconds")
            nested_allowed = {"count", "window_seconds", "windowSeconds"}
            unknown_nested = sorted(set(item) - nested_allowed)
            if unknown_nested:
                raise FlowControlError(
                    f"rate_limit has unsupported field(s): {', '.join(map(str, unknown_nested))}"
                )
            rate_limit = RateLimitPolicy(count, window)

        throttle = None
        if "throttle" in canonical:
            if canonical["throttle"] is None:
                raise FlowControlError("throttle must be an object")
            item = _object(canonical["throttle"], "throttle")
            present_interval, interval = _single_alias(
                item,
                "min_interval_seconds",
                ("minIntervalSeconds", "interval_seconds"),
                "throttle",
            )
            if not present_interval:
                raise FlowControlError("throttle requires min_interval_seconds")
            nested_allowed = {"min_interval_seconds", "minIntervalSeconds", "interval_seconds"}
            unknown_nested = sorted(set(item) - nested_allowed)
            if unknown_nested:
                raise FlowControlError(
                    f"throttle has unsupported field(s): {', '.join(map(str, unknown_nested))}"
                )
            throttle = ThrottlePolicy(interval)

        debounce = None
        if "debounce" in canonical:
            if canonical["debounce"] is None:
                raise FlowControlError("debounce must be an object")
            item = _object(canonical["debounce"], "debounce")
            present_window, window = _single_alias(
                item, "window_seconds", ("windowSeconds",), "debounce"
            )
            mode_present, mode = _single_alias(item, "mode", (), "debounce")
            if not present_window:
                raise FlowControlError("debounce requires window_seconds")
            if not mode_present:
                raise FlowControlError("debounce requires window_seconds and mode")
            nested_allowed = {"window_seconds", "windowSeconds", "mode"}
            unknown_nested = sorted(set(item) - nested_allowed)
            if unknown_nested:
                raise FlowControlError(
                    f"debounce has unsupported field(s): {', '.join(map(str, unknown_nested))}"
                )
            debounce = DebouncePolicy(window, mode)

        priority_present = "priority" in canonical
        priority = _integer(canonical["priority"], "priority") if priority_present else 0
        return cls(concurrency, rate_limit, throttle, debounce, priority, priority_present)

    def to_dict(self, *, include_default_priority: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.concurrency is not None:
            result["concurrency"] = self.concurrency.to_dict()
        if self.rate_limit is not None:
            result["rate_limit"] = self.rate_limit.to_dict()
        if self.throttle is not None:
            result["throttle"] = self.throttle.to_dict()
        if self.debounce is not None:
            result["debounce"] = self.debounce.to_dict()
        if include_default_priority or self._priority_present or self.priority != 0:
            result["priority"] = self.priority
        return result

    as_dict = to_dict


def canonicalize_flow_control(value: Mapping[str, Any] | FlowControlPolicy | None) -> dict[str, Any]:
    """Return the strict snake_case wire form of a flow-control policy."""

    return FlowControlPolicy.from_dict(value).to_dict()


canonicalize_flow_control_policy = canonicalize_flow_control
normalize_flow_control = canonicalize_flow_control
normalize_flow_control_policy = canonicalize_flow_control
canonicalize_policy = canonicalize_flow_control
normalize_policy = canonicalize_flow_control
parse_flow_control = FlowControlPolicy.from_dict


def flow_control_from_document(value: Mapping[str, Any] | None) -> FlowControlPolicy:
    """Extract the first-class policy from a document or its ``policies`` map."""

    if not isinstance(value, Mapping):
        return FlowControlPolicy.empty()
    policies = value.get("policies", value)
    if not isinstance(policies, Mapping):
        raise FlowControlError("policies must be an object")
    # A document can retain unrelated legacy/extension policy fields.  Feed
    # only the first-class keys to the strict contract parser.
    selected: dict[str, Any] = {}
    aliases = {
        "flow_control": "flow_control",
        "flowControl": "flow_control",
        "rateLimit": "rate_limit",
        "rate-limit": "rate_limit",
        "rateLimitPolicy": "rate_limit",
        "minInterval": "throttle",
        "minIntervalSeconds": "throttle",
        "debouncePolicy": "debounce",
    }
    allowed = {"concurrency", "rate_limit", "throttle", "debounce", "priority", "flow_control"}
    for key, item in policies.items():
        canonical = aliases.get(str(key), str(key))
        if canonical in allowed:
            selected[canonical] = item
    if "flow_control" in selected:
        if len(selected) != 1:
            raise FlowControlError("flow_control wrapper cannot be combined with sibling fields")
        return FlowControlPolicy.from_dict(selected["flow_control"])
    return FlowControlPolicy.from_dict(selected)


def stable_scope_key(scope: Any, *, key: str = "") -> str:
    """Build a deterministic, non-secret scope key for coordination.

    Mapping key order and JSON representation are canonicalised, then hashed
    so a path, session id, or structured scope cannot accidentally leak into a
    SQLite coordination filename or log.  Passing an already canonical
    string is supported and remains stable across processes/interpreters.
    """

    if isinstance(scope, str):
        scope_value: Any = scope.strip()
    else:
        scope_value = scope
    try:
        encoded = json.dumps(scope_value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        encoded = repr(scope_value)
    prefix = str(key or "").strip()
    material = f"{prefix}\x1f{encoded}" if prefix else encoded
    digest = hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()
    return f"scope_{digest}"


make_scope_key = stable_scope_key
canonical_scope_key = stable_scope_key
flow_control_scope_key = stable_scope_key


@dataclass(frozen=True, slots=True)
class FlowControlLease:
    namespace: str
    scope_key: str
    lease_id: str
    owner_id: str
    fencing_token: int
    acquired_at: float
    lease_expires_at: float

    @property
    def expires_at(self) -> float:
        return self.lease_expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "scope_key": self.scope_key,
            "lease_id": self.lease_id,
            "owner_id": self.owner_id,
            "fencing_token": self.fencing_token,
            "acquired_at": self.acquired_at,
            "lease_expires_at": self.lease_expires_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FlowControlLease":
        return cls(
            namespace=str(value.get("namespace") or "workflow"),
            scope_key=str(value.get("scope_key") or ""),
            lease_id=str(value.get("lease_id") or value.get("id") or ""),
            owner_id=str(value.get("owner_id") or ""),
            fencing_token=int(value.get("fencing_token") or value.get("token") or 0),
            acquired_at=float(value.get("acquired_at") or 0),
            lease_expires_at=float(value.get("lease_expires_at", value.get("expires_at", 0)) or 0),
        )

    @property
    def token(self) -> int:
        return self.fencing_token


@dataclass(frozen=True, slots=True)
class FlowControlDecision:
    """Result of ``acquire``/``check``.

    ``bool(decision)`` is true only for an acquired lease.  This keeps the
    result convenient for small integrations while retaining a reason and
    retry timestamp for non-busy-loop callers.
    """

    state: Literal["acquired", "blocked"]
    lease: FlowControlLease | None = None
    reason: str = ""
    retry_at: float | None = None
    reserved: bool = False

    @property
    def acquired(self) -> bool:
        # ``check`` intentionally does not allocate a lease, but an admitted
        # check is still an allowed decision.  ``acquire`` callers can inspect
        # ``lease`` when they need the release token.
        return self.state == "acquired"

    @property
    def allowed(self) -> bool:
        return self.acquired

    @property
    def busy(self) -> bool:
        return not self.acquired

    @property
    def status(self) -> str:
        return self.state

    @property
    def retry_after(self) -> float | None:
        if self.retry_at is None:
            return None
        return max(0.0, self.retry_at - time.time())

    @property
    def retry_in(self) -> float | None:
        return self.retry_after

    @property
    def lease_id(self) -> str:
        return self.lease.lease_id if self.lease is not None else ""

    @property
    def owner_id(self) -> str:
        return self.lease.owner_id if self.lease is not None else ""

    @property
    def fencing_token(self) -> int:
        return self.lease.fencing_token if self.lease is not None else 0

    def __bool__(self) -> bool:
        return self.acquired


FlowControlResult = FlowControlDecision
FlowControlAcquireResult = FlowControlDecision

# Explicit workflow-prefixed aliases make the public seam discoverable next
# to the existing WorkflowClaim* names while keeping the compact spellings
# useful for integrations.
WorkflowConcurrencyPolicy = ConcurrencyPolicy
WorkflowRateLimitPolicy = RateLimitPolicy
WorkflowThrottlePolicy = ThrottlePolicy
WorkflowDebouncePolicy = DebouncePolicy
WorkflowFlowControlPolicy = FlowControlPolicy


class FlowControlStore:
    """SQLite/local-first coordinator for workflow flow-control decisions."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        store_path: str | Path | None = None,
        db_path: str | Path | None = None,
        root: str | Path | None = None,
        data_dir: str | Path | None = None,
        namespace: str = "workflow",
        lease_seconds: float = 30.0,
        lease_ttl_seconds: float | None = None,
        retention_seconds: float = 86400.0,
        owner_id: str | None = None,
    ) -> None:
        path = path or store_path or db_path
        if path is None:
            if root is not None:
                path = Path(root).expanduser().resolve() / ".lam" / "workflow" / "flow_control.sqlite3"
            elif data_dir is not None:
                path = Path(data_dir).expanduser().resolve() / "workflow" / "flow_control.sqlite3"
            else:
                path = Path(".lam/workflow/flow_control.sqlite3").resolve()
        candidate = Path(path).expanduser().resolve()
        if candidate.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
            candidate = candidate / "flow_control.sqlite3"
        self.path = candidate
        self.namespace = _safe_key(namespace, "namespace")
        self.lease_seconds = _positive_number(
            lease_seconds if lease_ttl_seconds is None else lease_ttl_seconds,
            "lease_seconds",
        )
        self.retention_seconds = _positive_number(retention_seconds, "retention_seconds")
        self.owner_id = str(owner_id or f"pid-{os.getpid()}-{uuid.uuid4().hex}")
        self._initialized = False
        self._init_lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        # WAL is safe for local desktop readers and lets checks proceed while
        # another process commits a short transaction.
        try:
            connection.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as exc:
            # Two fresh store instances may initialise the same SQLite file
            # concurrently.  One wins the journal-mode transition; the other
            # can continue with the bounded busy timeout and observe WAL on
            # its next connection.
            if "locked" not in str(exc).lower():
                raise
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize_sync(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS flow_control_meta (
                    namespace TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS flow_control_leases (
                    namespace TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    lease_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    acquired_at REAL NOT NULL,
                    lease_expires_at REAL NOT NULL,
                    concurrency_key TEXT,
                    concurrency_max INTEGER,
                    PRIMARY KEY(namespace, lease_id)
                )
                """
            )
            # Fencing survives expiry cleanup.  Without this tiny side table,
            # reusing a lease id after expiry could reset its token to one and
            # allow a stale owner to release the replacement lease.
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS flow_control_lease_fences (
                    namespace TEXT NOT NULL,
                    lease_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    PRIMARY KEY(namespace, lease_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS flow_control_rate_events (
                    namespace TEXT NOT NULL,
                    rate_key TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    occurred_at REAL NOT NULL,
                    PRIMARY KEY(namespace, rate_key, event_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS flow_control_throttles (
                    namespace TEXT NOT NULL,
                    throttle_key TEXT NOT NULL,
                    last_at REAL NOT NULL,
                    PRIMARY KEY(namespace, throttle_key)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS flow_control_debounce (
                    namespace TEXT NOT NULL,
                    debounce_key TEXT NOT NULL,
                    reservation_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    reserved_at REAL NOT NULL,
                    lease_expires_at REAL NOT NULL,
                    PRIMARY KEY(namespace, debounce_key)
                )
                """
            )
            # A pre-release coordinator used the same table names with a
            # smaller column set.  Add optional columns in place so opening a
            # desktop's existing database is an idempotent migration rather
            # than a destructive replacement.  The defaults are deliberately
            # conservative and preserve old rows as expired/unscoped data.
            self._ensure_column(connection, "flow_control_leases", "namespace", "TEXT NOT NULL DEFAULT 'workflow'")
            self._ensure_column(connection, "flow_control_leases", "scope_key", "TEXT NOT NULL DEFAULT 'scope_legacy'")
            self._ensure_column(connection, "flow_control_leases", "lease_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "flow_control_leases", "owner_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "flow_control_leases", "fencing_token", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(connection, "flow_control_leases", "acquired_at", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(connection, "flow_control_leases", "lease_expires_at", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(connection, "flow_control_leases", "concurrency_key", "TEXT")
            self._ensure_column(connection, "flow_control_leases", "concurrency_max", "INTEGER")
            self._ensure_column(connection, "flow_control_rate_events", "namespace", "TEXT NOT NULL DEFAULT 'workflow'")
            self._ensure_column(connection, "flow_control_rate_events", "rate_key", "TEXT NOT NULL DEFAULT 'scope_legacy'")
            self._ensure_column(connection, "flow_control_rate_events", "event_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "flow_control_rate_events", "occurred_at", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(connection, "flow_control_throttles", "namespace", "TEXT NOT NULL DEFAULT 'workflow'")
            self._ensure_column(connection, "flow_control_throttles", "throttle_key", "TEXT NOT NULL DEFAULT 'scope_legacy'")
            self._ensure_column(connection, "flow_control_throttles", "last_at", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(connection, "flow_control_debounce", "namespace", "TEXT NOT NULL DEFAULT 'workflow'")
            self._ensure_column(connection, "flow_control_debounce", "debounce_key", "TEXT NOT NULL DEFAULT 'scope_legacy'")
            self._ensure_column(connection, "flow_control_debounce", "reservation_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "flow_control_debounce", "mode", "TEXT NOT NULL DEFAULT 'leading'")
            self._ensure_column(connection, "flow_control_debounce", "reserved_at", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(connection, "flow_control_debounce", "lease_expires_at", "REAL NOT NULL DEFAULT 0")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_flow_control_concurrency "
                "ON flow_control_leases(namespace, concurrency_key, lease_expires_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_flow_control_rate_window "
                "ON flow_control_rate_events(namespace, rate_key, occurred_at)"
            )
            connection.execute(
                "INSERT INTO flow_control_meta(namespace, schema_version) VALUES (?, ?) "
                "ON CONFLICT(namespace) DO UPDATE SET schema_version=excluded.schema_version",
                (self.namespace, self.SCHEMA_VERSION),
            )

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
        columns = {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if not self._initialized:
                await asyncio.to_thread(self._initialize_sync)
                self._initialized = True

    @staticmethod
    def _policy(value: FlowControlPolicy | Mapping[str, Any] | None) -> FlowControlPolicy:
        return FlowControlPolicy.from_dict(value)

    @staticmethod
    def _scope(scope: Any = None, scope_key: str | None = None) -> str:
        if scope_key is not None:
            return _safe_key(scope_key, "scope_key")
        if scope is None:
            return stable_scope_key("global")
        if isinstance(scope, str) and scope.strip():
            return stable_scope_key(scope.strip())
        return stable_scope_key(scope)

    @staticmethod
    def _bucket(scope_key: str, policy_key: str) -> str:
        return stable_scope_key(scope_key, key=policy_key)

    @staticmethod
    def _lease_from_row(row: sqlite3.Row) -> FlowControlLease:
        return FlowControlLease(
            namespace=str(row["namespace"]),
            scope_key=str(row["scope_key"]),
            lease_id=str(row["lease_id"]),
            owner_id=str(row["owner_id"]),
            fencing_token=int(row["fencing_token"]),
            acquired_at=float(row["acquired_at"]),
            lease_expires_at=float(row["lease_expires_at"]),
        )

    @staticmethod
    def _blocked(reason: str, retry_at: float | None = None, *, reserved: bool = False) -> FlowControlDecision:
        return FlowControlDecision("blocked", reason=reason, retry_at=retry_at, reserved=reserved)

    def _cleanup(self, connection: sqlite3.Connection, now: float) -> None:
        connection.execute(
            "DELETE FROM flow_control_leases WHERE namespace=? AND lease_expires_at<=?",
            (self.namespace, now),
        )
        connection.execute(
            "DELETE FROM flow_control_debounce WHERE namespace=? AND lease_expires_at<=?",
            (self.namespace, now),
        )
        cutoff = now - self.retention_seconds
        connection.execute(
            "DELETE FROM flow_control_rate_events WHERE namespace=? AND occurred_at<?",
            (self.namespace, cutoff),
        )

    def _evaluate(
        self,
        connection: sqlite3.Connection,
        policy: FlowControlPolicy,
        scope_key: str,
        now: float,
        *,
        lease_id: str,
        mutate_debounce: bool = False,
    ) -> FlowControlDecision | None:
        """Return a blocking decision, or ``None`` when all checks pass."""

        if policy.concurrency is not None:
            bucket = self._bucket(scope_key, policy.concurrency.key)
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM flow_control_leases "
                "WHERE namespace=? AND concurrency_key=? AND lease_expires_at>? AND lease_id<>?",
                (self.namespace, bucket, now, lease_id),
            ).fetchone()
            if int(row["count"] if row else 0) >= policy.concurrency.max:
                retry_row = connection.execute(
                    "SELECT MIN(lease_expires_at) AS retry_at FROM flow_control_leases "
                    "WHERE namespace=? AND concurrency_key=? AND lease_expires_at>? AND lease_id<>?",
                    (self.namespace, bucket, now, lease_id),
                ).fetchone()
                return self._blocked("concurrency", float(retry_row["retry_at"]) if retry_row and retry_row["retry_at"] is not None else None)

        if policy.rate_limit is not None:
            bucket = self._bucket(scope_key, "rate_limit")
            cutoff = now - policy.rate_limit.window_seconds
            connection.execute(
                "DELETE FROM flow_control_rate_events WHERE namespace=? AND rate_key=? AND occurred_at<=?",
                (self.namespace, bucket, cutoff),
            )
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM flow_control_rate_events WHERE namespace=? AND rate_key=? AND occurred_at>?",
                (self.namespace, bucket, cutoff),
            ).fetchone()
            if int(row["count"] if row else 0) >= policy.rate_limit.count:
                first = connection.execute(
                    "SELECT MIN(occurred_at) AS first_at FROM flow_control_rate_events WHERE namespace=? AND rate_key=? AND occurred_at>?",
                    (self.namespace, bucket, cutoff),
                ).fetchone()
                retry = float(first["first_at"]) + policy.rate_limit.window_seconds if first and first["first_at"] is not None else None
                return self._blocked("rate_limit", retry)

        if policy.throttle is not None:
            bucket = self._bucket(scope_key, "throttle")
            row = connection.execute(
                "SELECT last_at FROM flow_control_throttles WHERE namespace=? AND throttle_key=?",
                (self.namespace, bucket),
            ).fetchone()
            if row is not None:
                retry = float(row["last_at"]) + policy.throttle.min_interval_seconds
                if retry > now:
                    return self._blocked("throttle", retry)

        if policy.debounce is not None:
            bucket = self._bucket(scope_key, "debounce")
            row = connection.execute(
                "SELECT reservation_id, mode, lease_expires_at FROM flow_control_debounce WHERE namespace=? AND debounce_key=?",
                (self.namespace, bucket),
            ).fetchone()
            if row is not None and str(row["reservation_id"]) != lease_id:
                retry = float(row["lease_expires_at"])
                if policy.debounce.mode == "trailing" and mutate_debounce:
                    # A trailing debounce extends the quiet window to the
                    # latest reservation.  The caller is still blocked and
                    # can schedule itself for the returned retry timestamp.
                    connection.execute(
                        "UPDATE flow_control_debounce SET reservation_id=?, mode=?, reserved_at=?, lease_expires_at=? "
                        "WHERE namespace=? AND debounce_key=?",
                        (lease_id, policy.debounce.mode, now, now + policy.debounce.window_seconds, self.namespace, bucket),
                    )
                    retry = now + policy.debounce.window_seconds
                    return self._blocked("debounce", retry, reserved=True)
                return self._blocked("debounce", retry, reserved=True)
        return None

    def _acquire_sync(
        self,
        policy: FlowControlPolicy,
        scope_key: str,
        lease_id: str,
        owner_id: str,
        now: float,
    ) -> FlowControlDecision:
        expires = now + self.lease_seconds
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._cleanup(connection, now)
            existing = connection.execute(
                "SELECT * FROM flow_control_leases WHERE namespace=? AND lease_id=?",
                (self.namespace, lease_id),
            ).fetchone()
            if existing is not None and float(existing["lease_expires_at"]) > now:
                if str(existing["owner_id"]) == owner_id and str(existing["scope_key"]) == scope_key:
                    connection.commit()
                    return FlowControlDecision("acquired", lease=self._lease_from_row(existing))
                connection.commit()
                return self._blocked("lease_conflict", float(existing["lease_expires_at"]))

            blocked = self._evaluate(
                connection,
                policy,
                scope_key,
                now,
                lease_id=lease_id,
                mutate_debounce=True,
            )
            if blocked is not None:
                connection.commit()
                return blocked

            fence_row = connection.execute(
                "SELECT fencing_token FROM flow_control_lease_fences WHERE namespace=? AND lease_id=?",
                (self.namespace, lease_id),
            ).fetchone()
            fence = int(fence_row["fencing_token"]) + 1 if fence_row is not None else 1
            connection.execute(
                "INSERT INTO flow_control_lease_fences(namespace, lease_id, fencing_token) VALUES (?, ?, ?) "
                "ON CONFLICT(namespace, lease_id) DO UPDATE SET fencing_token=excluded.fencing_token",
                (self.namespace, lease_id, fence),
            )
            concurrency_key = (
                self._bucket(scope_key, policy.concurrency.key) if policy.concurrency is not None else None
            )
            connection.execute(
                "INSERT INTO flow_control_leases(namespace, scope_key, lease_id, owner_id, fencing_token, acquired_at, lease_expires_at, concurrency_key, concurrency_max) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.namespace,
                    scope_key,
                    lease_id,
                    owner_id,
                    fence,
                    now,
                    expires,
                    concurrency_key,
                    policy.concurrency.max if policy.concurrency is not None else None,
                ),
            )
            if policy.rate_limit is not None:
                bucket = self._bucket(scope_key, "rate_limit")
                event_id = f"{lease_id}:{fence}"
                connection.execute(
                    "INSERT OR IGNORE INTO flow_control_rate_events(namespace, rate_key, event_id, occurred_at) VALUES (?, ?, ?, ?)",
                    (self.namespace, bucket, event_id, now),
                )
            if policy.throttle is not None:
                bucket = self._bucket(scope_key, "throttle")
                connection.execute(
                    "INSERT INTO flow_control_throttles(namespace, throttle_key, last_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(namespace, throttle_key) DO UPDATE SET last_at=excluded.last_at",
                    (self.namespace, bucket, now),
                )
            if policy.debounce is not None:
                bucket = self._bucket(scope_key, "debounce")
                connection.execute(
                    "INSERT INTO flow_control_debounce(namespace, debounce_key, reservation_id, mode, reserved_at, lease_expires_at) VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(namespace, debounce_key) DO UPDATE SET reservation_id=excluded.reservation_id, mode=excluded.mode, reserved_at=excluded.reserved_at, lease_expires_at=excluded.lease_expires_at",
                    (self.namespace, bucket, lease_id, policy.debounce.mode, now, now + policy.debounce.window_seconds),
                )
            connection.commit()
            lease = FlowControlLease(self.namespace, scope_key, lease_id, owner_id, fence, now, expires)
            return FlowControlDecision("acquired", lease=lease)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def acquire(
        self,
        policy: FlowControlPolicy | Mapping[str, Any] | None = None,
        scope_key: str | None = None,
        lease_id: str | None = None,
        *,
        scope: Any = None,
        key: str | None = None,
        flow_control: FlowControlPolicy | Mapping[str, Any] | None = None,
        strategy: FlowControlPolicy | Mapping[str, Any] | None = None,
        owner_id: str | None = None,
        owner: str | None = None,
        now: float | None = None,
    ) -> FlowControlDecision:
        """Atomically acquire a lease or return a retryable blocked decision."""

        await self.initialize()
        if policy is None:
            policy = flow_control if flow_control is not None else strategy
        elif flow_control is not None or strategy is not None:
            raise FlowControlError("acquire accepts only one policy argument")
        parsed = self._policy(policy)
        stable_scope = self._scope(scope, scope_key if scope_key is not None else key)
        return await asyncio.to_thread(
            self._acquire_sync,
            parsed,
            stable_scope,
            str(lease_id or uuid.uuid4().hex),
            str(owner_id or owner or self.owner_id),
            float(time.time() if now is None else now),
        )

    try_acquire = acquire

    def _check_sync(
        self,
        policy: FlowControlPolicy,
        scope_key: str,
        lease_id: str,
        now: float,
    ) -> FlowControlDecision:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._cleanup(connection, now)
            existing = connection.execute(
                "SELECT * FROM flow_control_leases WHERE namespace=? AND lease_id=? AND lease_expires_at>?",
                (self.namespace, lease_id, now),
            ).fetchone()
            if existing is not None and str(existing["scope_key"]) == scope_key:
                connection.commit()
                return FlowControlDecision("acquired", lease=self._lease_from_row(existing))
            blocked = self._evaluate(connection, policy, scope_key, now, lease_id=lease_id)
            connection.commit()
            # ``FlowControlDecision.__bool__`` intentionally reflects
            # admission, so using ``blocked or allowed`` here would discard a
            # legitimate blocked decision.  Test identity explicitly.
            return blocked if blocked is not None else FlowControlDecision("acquired")
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def check(
        self,
        policy: FlowControlPolicy | Mapping[str, Any] | None = None,
        scope_key: str | None = None,
        lease_id: str = "",
        *,
        scope: Any = None,
        key: str | None = None,
        flow_control: FlowControlPolicy | Mapping[str, Any] | None = None,
        strategy: FlowControlPolicy | Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> FlowControlDecision:
        """Check admission without reserving a lease or consuming a rate hit."""

        await self.initialize()
        if policy is None:
            policy = flow_control if flow_control is not None else strategy
        elif flow_control is not None or strategy is not None:
            raise FlowControlError("check accepts only one policy argument")
        parsed = self._policy(policy)
        stable_scope = self._scope(scope, scope_key if scope_key is not None else key)
        return await asyncio.to_thread(
            self._check_sync,
            parsed,
            stable_scope,
            str(lease_id or "__check__"),
            float(time.time() if now is None else now),
        )

    def _coerce_lease(self, lease: FlowControlLease | FlowControlDecision | Mapping[str, Any] | str, *, scope_key: str = "", owner_id: str = "", fencing_token: int = 0) -> tuple[str, str, str, int]:
        if isinstance(lease, FlowControlDecision):
            lease = lease.lease if lease.lease is not None else ""
        if isinstance(lease, FlowControlLease):
            return lease.scope_key, lease.lease_id, lease.owner_id, lease.fencing_token
        if isinstance(lease, Mapping):
            return (
                str(lease.get("scope_key") or scope_key),
                str(lease.get("lease_id") or lease.get("id") or ""),
                str(lease.get("owner_id") or owner_id or self.owner_id),
                int(lease.get("fencing_token") or fencing_token or 0),
            )
        return scope_key, str(lease), owner_id or self.owner_id, int(fencing_token or 0)

    def _release_sync(self, lease: FlowControlLease | Mapping[str, Any] | str, scope_key: str, owner_id: str, fencing_token: int, now: float) -> bool:
        resolved_scope, lease_id, resolved_owner, fence = self._coerce_lease(
            lease, scope_key=scope_key, owner_id=owner_id, fencing_token=fencing_token
        )
        if not lease_id:
            return False
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM flow_control_leases WHERE namespace=? AND scope_key=? AND lease_id=? AND owner_id=? "
                "AND fencing_token=? AND lease_expires_at>?",
                (self.namespace, resolved_scope, lease_id, resolved_owner, fence, now),
            )
            connection.commit()
            return cursor.rowcount == 1
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def release(
        self,
        lease: FlowControlLease | FlowControlDecision | Mapping[str, Any] | str,
        *,
        scope_key: str = "",
        owner_id: str = "",
        fencing_token: int = 0,
        now: float | None = None,
    ) -> bool:
        """Release only the matching live lease; stale owners cannot release a replacement."""

        await self.initialize()
        return await asyncio.to_thread(
            self._release_sync,
            lease,
            scope_key,
            owner_id,
            fencing_token,
            float(time.time() if now is None else now),
        )

    def _renew_sync(self, lease: FlowControlLease | Mapping[str, Any], now: float) -> FlowControlLease | None:
        resolved_scope, lease_id, owner_id, fence = self._coerce_lease(lease)
        expires = now + self.lease_seconds
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM flow_control_leases WHERE namespace=? AND scope_key=? AND lease_id=? AND owner_id=? AND fencing_token=? AND lease_expires_at>?",
                (self.namespace, resolved_scope, lease_id, owner_id, fence, now),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                "UPDATE flow_control_leases SET lease_expires_at=? WHERE namespace=? AND scope_key=? AND lease_id=? AND owner_id=? AND fencing_token=?",
                (expires, self.namespace, resolved_scope, lease_id, owner_id, fence),
            )
            connection.commit()
            return FlowControlLease(self.namespace, resolved_scope, lease_id, owner_id, fence, float(row["acquired_at"]), expires)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def renew(self, lease: FlowControlLease | Mapping[str, Any], *, now: float | None = None) -> FlowControlLease | None:
        await self.initialize()
        return await asyncio.to_thread(self._renew_sync, lease, float(time.time() if now is None else now))

    def _cleanup_sync(self, now: float) -> int:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            before = int(connection.execute("SELECT COUNT(*) FROM flow_control_leases WHERE namespace=?", (self.namespace,)).fetchone()[0])
            self._cleanup(connection, now)
            after = int(connection.execute("SELECT COUNT(*) FROM flow_control_leases WHERE namespace=?", (self.namespace,)).fetchone()[0])
            connection.commit()
            return max(0, before - after)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def cleanup(self, *, now: float | None = None) -> int:
        await self.initialize()
        return await asyncio.to_thread(self._cleanup_sync, float(time.time() if now is None else now))

    cleanup_expired = cleanup

    async def count(self, *, scope: Any = None, scope_key: str | None = None) -> int:
        await self.initialize()
        resolved = self._scope(scope, scope_key)
        return await asyncio.to_thread(self._count_sync, resolved)

    active_count = count

    def _count_sync(self, scope_key: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM flow_control_leases WHERE namespace=? AND scope_key=? AND lease_expires_at>?",
                (self.namespace, scope_key, time.time()),
            ).fetchone()
        return int(row[0] if row else 0)


# Resolve the forward alias after the class body exists.
WorkflowFlowControlStore = FlowControlStore


__all__ = [
    "ConcurrencyPolicy",
    "DebounceMode",
    "DebouncePolicy",
    "FlowControlAcquireResult",
    "FlowControlDecision",
    "FlowControlError",
    "FlowControlLease",
    "FlowControlPolicy",
    "FlowControlPolicyError",
    "FlowControlResult",
    "FlowControlStore",
    "WorkflowConcurrencyPolicy",
    "WorkflowRateLimitPolicy",
    "WorkflowThrottlePolicy",
    "WorkflowDebouncePolicy",
    "WorkflowFlowControlPolicy",
    "WorkflowFlowControlStore",
    "RateLimitPolicy",
    "ThrottlePolicy",
    "canonical_scope_key",
    "canonicalize_flow_control",
    "canonicalize_flow_control_policy",
    "canonicalize_policy",
    "flow_control_from_document",
    "flow_control_scope_key",
    "make_scope_key",
    "normalize_flow_control",
    "normalize_flow_control_policy",
    "normalize_policy",
    "parse_flow_control",
    "stable_scope_key",
]
