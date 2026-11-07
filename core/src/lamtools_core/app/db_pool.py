"""Connection-pool instrumentation for the Core database.

The Core app builds one SQLAlchemy engine for ``core.db``. Every live request,
turn projection, checkpoint, sub-agent bookkeeping and background maintenance
task shares that engine's connection pool, so the pool is the single place where
a stalled reader turns into a global outage.

The incident this module was written for surfaced as::

    QueuePool limit of size 4 overflow 4 reached, connection timed out,
    timeout 30.00

which is only the *last* symptom: by the time a request waits 30s at checkout,
eight other operations have been holding connections for seconds to minutes and
nothing in the log says who they are. The pool therefore gets three things it
did not have:

* a checkout **wait** histogram (how long callers queue for a connection),
* a live **holder** registry (who checked a connection out and for how long),
* a **saturation watchdog** that logs one warning per episode with the holder
  count, the longest hold and the stacks of the oldest holders, so the next
  occurrence is diagnosable from one log line instead of a stack trace from an
  innocent caller.

user:“排查并修复 SQLAlchemy 数据库连接池耗尽问题”+(池满时不能在无关请求上抛 30 秒超时了事：要记录谁占着连接、占多久、排队多久)。
"""

from __future__ import annotations

import asyncio
import logging
import os
import traceback
from collections import deque
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Deque

from sqlalchemy.pool import AsyncAdaptedQueuePool

_logger = logging.getLogger("lamtools_core.db.pool")

# One warning per episode is enough: a saturation that lasts a minute must not
# turn into sixty log lines that bury the first (useful) one.
SATURATION_WARNING_SECONDS = 3.0
# A single checked-out connection held this long is already anomalous. SQLite
# statements on core.db are single-digit milliseconds; seconds means the caller
# is doing non-database work while it still owns a connection.
LONG_HOLD_WARNING_SECONDS = 5.0
# A caller waiting this long for a connection means the pool is the bottleneck,
# even if it never reaches the timeout.
SLOW_CHECKOUT_WARNING_SECONDS = 2.0
SAMPLE_INTERVAL_SECONDS = 1.0

_WAIT_SAMPLES = 4096


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        _logger.warning("[db:pool] ignoring non-numeric %s=%r", name, raw)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        _logger.warning("[db:pool] ignoring non-numeric %s=%r", name, raw)
        return default


# Sized for *read* concurrency, not for writes (writes are already serialized by
# SQLiteWriteCoordinator and use one connection at a time). SQLite in WAL mode
# serves independent readers concurrently; the old 4+4 bound was reached by a
# single UI poll cycle during the 2026-10-30 incident (checked-out peaked at 5
# with six `sub_agent.list` pollers and two transcript reads, no writes at all).
# The ceiling stays finite and env-tunable: this is a read-concurrency budget,
# not a way to hide a leak.
DEFAULT_POOL_SIZE = _env_int("LAMTOOLS_DB_POOL_SIZE", 8)
DEFAULT_MAX_OVERFLOW = _env_int("LAMTOOLS_DB_POOL_OVERFLOW", 8)
# Fail fast instead of queueing for 30s. A stuck operation must surface as one
# retryable error; a 30s wait turns every poller into another backlog entry and
# the queue never drains (measured: one request waited 313s during the incident).
DEFAULT_POOL_TIMEOUT = _env_float("LAMTOOLS_DB_POOL_TIMEOUT", 8.0)


class InstrumentedAsyncQueuePool(AsyncAdaptedQueuePool):
    """``AsyncAdaptedQueuePool`` that records how long a checkout had to wait.

    ``_do_get`` is the synchronous QueuePool acquisition; for async engines it
    runs inside the greenlet and blocks on the pool's asyncio-adapted queue, so
    the wall-clock delta is exactly the caller's queue time.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.wait_samples: Deque[float] = deque(maxlen=_WAIT_SAMPLES)
        # Set by PoolTelemetry so a timed-out checkout explains itself instead of
        # surfacing as a bare 30s TimeoutError in an unrelated request.
        self.timeout_hook: Any = None

    def _do_get(self):  # type: ignore[override]
        started = perf_counter()
        try:
            return super()._do_get()
        except BaseException as exc:
            from sqlalchemy.exc import TimeoutError as SATimeoutError

            if isinstance(exc, SATimeoutError) and callable(self.timeout_hook):
                try:
                    self.timeout_hook()
                except Exception:  # noqa: BLE001 - diagnostics must not mask the error
                    pass
            raise
        finally:
            self.wait_samples.append(perf_counter() - started)

    def wait_stats(self) -> dict[str, float]:
        samples = list(self.wait_samples)
        if not samples:
            return {"count": 0, "p50": 0.0, "max": 0.0, "last": 0.0}
        ordered = sorted(samples)
        return {
            "count": len(ordered),
            "p50": ordered[len(ordered) // 2],
            "max": ordered[-1],
            "last": samples[-1],
        }

    def clear_wait_samples(self) -> None:
        self.wait_samples.clear()


@dataclass
class PoolSnapshot:
    """Point-in-time view of the pool plus the operations holding it."""

    size: int
    max_overflow: int
    capacity: int
    checked_out: int
    held_seconds: list[float] = field(default_factory=list)
    waits: dict[str, float] = field(default_factory=dict)
    saturation_episodes: int = 0
    checkout_timeouts: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "max_overflow": self.max_overflow,
            "capacity": self.capacity,
            "checked_out": self.checked_out,
            "longest_hold_seconds": round(max(self.held_seconds), 3) if self.held_seconds else 0.0,
            "checkout_wait_p50_seconds": round(self.waits.get("p50", 0.0), 4),
            "checkout_wait_max_seconds": round(self.waits.get("max", 0.0), 4),
            "saturation_episodes": self.saturation_episodes,
            "checkout_timeouts": self.checkout_timeouts,
        }


class PoolTelemetry:
    """Track who holds a pooled connection and warn when the pool saturates.

    ``capture_stacks`` keeps the Python stack of every checkout. It is off by
    default because it costs on every database operation; enable it with
    ``LAMTOOLS_DB_POOL_TRACE=1`` when reproducing a leak in a dev build.
    """

    def __init__(
        self,
        engine: Any,
        *,
        sample_interval: float = SAMPLE_INTERVAL_SECONDS,
        saturation_seconds: float = SATURATION_WARNING_SECONDS,
        long_hold_seconds: float = LONG_HOLD_WARNING_SECONDS,
        slow_checkout_seconds: float = SLOW_CHECKOUT_WARNING_SECONDS,
        checkout_timeout: float = DEFAULT_POOL_TIMEOUT,
        capture_stacks: bool | None = None,
    ) -> None:
        self.engine = engine
        self.sample_interval = max(0.05, float(sample_interval))
        self.saturation_seconds = max(0.0, float(saturation_seconds))
        self.long_hold_seconds = max(0.0, float(long_hold_seconds))
        self.slow_checkout_seconds = max(0.0, float(slow_checkout_seconds))
        self.checkout_timeout = float(checkout_timeout)
        self.capture_stacks = (
            os.environ.get("LAMTOOLS_DB_POOL_TRACE") == "1"
            if capture_stacks is None
            else bool(capture_stacks)
        )
        # id(dbapi_connection) -> (checked_out_at, stack or "")
        self._held: dict[int, tuple[float, str]] = {}
        # Connection ids already warned about for a long hold.
        self._reported_holds: set[int] = set()
        self.saturation_episodes = 0
        self.checkout_timeouts = 0
        self._saturated_since: float | None = None
        self._saturated_reported = False
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self._attach()

    # ---------------------------------------------------------------- events
    def _attach(self) -> None:
        from sqlalchemy import event

        sync_engine = self.engine.sync_engine
        pool = self.engine.pool
        if hasattr(pool, "timeout_hook"):
            pool.timeout_hook = self.note_timeout

        @event.listens_for(sync_engine, "checkout")
        def _on_checkout(dbapi_connection, _record, _proxy) -> None:
            self._held[id(dbapi_connection)] = (
                perf_counter(),
                "".join(traceback.format_stack(limit=24)) if self.capture_stacks else "",
            )

        @event.listens_for(sync_engine, "checkin")
        def _on_checkin(dbapi_connection, _record) -> None:
            key = id(dbapi_connection)
            self._held.pop(key, None)
            self._reported_holds.discard(key)

        # A connection invalidated while checked out never fires "checkin".
        # Without this the holder registry would keep a dead entry forever and
        # every later warning would name a connection that no longer exists.
        @event.listens_for(sync_engine, "close")
        def _on_close(dbapi_connection, _record) -> None:
            key = id(dbapi_connection)
            self._held.pop(key, None)
            self._reported_holds.discard(key)

    # ----------------------------------------------------------- public API
    @property
    def capacity(self) -> int:
        pool = self.engine.pool
        return int(pool.size()) + int(getattr(pool, "_max_overflow", 0))

    def snapshot(self) -> PoolSnapshot:
        pool = self.engine.pool
        size = int(pool.size())
        max_overflow = int(getattr(pool, "_max_overflow", 0))
        now = perf_counter()
        held = [now - born for born, _ in self._held.values()]
        waits = pool.wait_stats() if hasattr(pool, "wait_stats") else {}
        return PoolSnapshot(
            size=size,
            max_overflow=max_overflow,
            capacity=size + max_overflow,
            checked_out=len(self._held),
            held_seconds=held,
            waits=dict(waits),
            saturation_episodes=self.saturation_episodes,
            checkout_timeouts=self.checkout_timeouts,
        )

    def note_timeout(self) -> None:
        """Record one checkout that timed out (called by the engine wrapper)."""
        self.checkout_timeouts += 1
        snapshot = self.snapshot()
        _logger.error(
            "[db:pool] checkout timed out after %.1fs | checked_out=%d/%d longest_hold=%.2fs | %s",
            self.checkout_timeout,
            snapshot.checked_out,
            snapshot.capacity,
            max(snapshot.held_seconds, default=0.0),
            self._describe_holders(limit=3),
        )

    def _describe_holders(self, *, limit: int = 3) -> str:
        if not self._held:
            return "holders=none"
        now = perf_counter()
        ordered = sorted(self._held.items(), key=lambda item: item[1][0])
        parts: list[str] = []
        for key, (born, stack) in ordered[:limit]:
            frames = [
                line.strip()
                for line in stack.splitlines()
                if line.strip().startswith("File ") and "lamtools_core" in line
            ][-3:]
            suffix = f" via {' <- '.join(frames)}" if frames else ""
            parts.append(f"conn={key} held={now - born:.2f}s{suffix}")
        return "holders: " + " | ".join(parts)

    def start(self) -> "PoolTelemetry":
        """Start the sampling watchdog on the current event loop."""
        if self._task is None and not self._closed:
            self._task = asyncio.create_task(self._sample_loop(), name="db-pool-watchdog")
        return self

    async def stop(self) -> None:
        self._closed = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # -------------------------------------------------------------- internal
    async def _sample_loop(self) -> None:
        while True:
            await asyncio.sleep(self.sample_interval)
            try:
                self._check()
            except Exception:  # noqa: BLE001 - diagnostics must never kill the host
                _logger.warning("[db:pool] pool sampling failed", exc_info=True)

    def _check(self) -> None:
        now = perf_counter()
        snapshot = self.snapshot()
        saturated = snapshot.capacity > 0 and snapshot.checked_out >= snapshot.capacity
        if saturated:
            # The saturation line below already names the holders; emitting one
            # warning per connection here would bury it under 16 look-alikes.
            self._reported_holds.update(self._held.keys())
        else:
            for key, (born, _stack) in list(self._held.items()):
                held = now - born
                if held >= self.long_hold_seconds and key not in self._reported_holds:
                    self._reported_holds.add(key)
                    _logger.warning(
                        "[db:pool] connection %s held %.2fs (checked_out=%d/%d)",
                        key,
                        held,
                        snapshot.checked_out,
                        snapshot.capacity,
                    )
        waits = snapshot.waits
        if waits and waits.get("max", 0.0) >= self.slow_checkout_seconds:
            _logger.warning(
                "[db:pool] checkout queue slow: max=%.2fs p50=%.0fms checked_out=%d/%d",
                waits["max"],
                waits["p50"] * 1000.0,
                snapshot.checked_out,
                snapshot.capacity,
            )
            pool = self.engine.pool
            if hasattr(pool, "clear_wait_samples"):
                pool.clear_wait_samples()
        if saturated:
            if self._saturated_since is None:
                self._saturated_since = now
            elif (
                not self._saturated_reported
                and now - self._saturated_since >= self.saturation_seconds
            ):
                self._saturated_reported = True
                self.saturation_episodes += 1
                _logger.error(
                    "[db:pool] pool saturated for %.1fs: %d/%d connections checked out | %s",
                    now - self._saturated_since,
                    snapshot.checked_out,
                    snapshot.capacity,
                    self._describe_holders(limit=4),
                )
        else:
            if self._saturated_reported:
                _logger.info(
                    "[db:pool] pool recovered after %.1fs (episodes=%d)",
                    now - (self._saturated_since or now),
                    self.saturation_episodes,
                )
            self._saturated_since = None
            self._saturated_reported = False


def attach_pool_telemetry(engine: Any, **kwargs: Any) -> PoolTelemetry:
    """Create telemetry for ``engine``. The caller owns start/stop."""
    return PoolTelemetry(engine, **kwargs)


__all__ = [
    "DEFAULT_MAX_OVERFLOW",
    "DEFAULT_POOL_SIZE",
    "DEFAULT_POOL_TIMEOUT",
    "InstrumentedAsyncQueuePool",
    "PoolSnapshot",
    "PoolTelemetry",
    "attach_pool_telemetry",
]
