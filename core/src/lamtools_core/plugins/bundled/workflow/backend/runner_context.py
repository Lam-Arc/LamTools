"""Workflow execution context, lazy inputs and domain errors."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any
from .executors import WorkflowExecutorError
from .expressions import ExpressionError
from .models import _json_copy


@dataclass(frozen=True)
class WorkflowExecutionContext:
    """Host correlation and authority carried across every workflow boundary.

    The context is the one propagation object shared by AI/Agent nodes,
    nested workflows, and workflow-as-tool calls.  New fields are optional so
    existing direct Runner callers keep their historical construction shape.
    """

    parent_session_id: str = ""
    parent_run_id: str = ""
    parent_turn_id: str = ""
    parent_call_id: str = ""
    cwd: str = ""
    cancellation: Any = None
    # Queue shutdowns use a separate, dynamically-set token so an interrupted
    # run can be persisted and resumed.  A bool is also accepted for direct
    # callers; normal cancellation keeps the historical cancelled contract.
    pause_on_cancel: Any = False
    permissions: dict[str, Any] = field(default_factory=dict)
    event_metadata: dict[str, Any] = field(default_factory=dict)
    attachments: list[Any] = field(default_factory=list)
    runtime_snapshot: Any = None
    environment: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    # Resolved credential material is an execution-only child-context value.
    # It is deliberately excluded from repr/compare and from ``metadata``;
    # ``child()`` constructs a fresh context and therefore clears it.
    runtime_credentials: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    trace_id: str = ""
    # ``lineage`` contains parent call identifiers in order.  ``workflow_stack``
    # is separate because it is used for cycle detection, not presentation.
    lineage: tuple[str, ...] = ()
    workflow_stack: tuple[str, ...] = ()
    depth: int = 0
    max_depth: int = 16
    # Set only by the runner's own child/enter helpers.  A serialized context
    # intentionally omits this marker, so a caller cannot smuggle a stack
    # containing the workflow being invoked past the root cycle guard.
    _workflow_stack_internal: bool = field(default=False, repr=False, compare=False)
    # ``snapshot`` is the short spelling used by a few host adapters.  Keep
    # ``runtime_snapshot`` as the canonical wire key for Core compatibility.
    snapshot: Any = None

    def __post_init__(self) -> None:
        # Older callers put trace information exclusively in
        # ``event_metadata``.  Surface it on the explicit field too so all
        # adapters observe one canonical value while preserving object
        # identity for legacy integration tests.
        if not self.trace_id and isinstance(self.event_metadata, dict):
            trace = self.event_metadata.get("trace_id") or self.event_metadata.get("traceId")
            if trace:
                object.__setattr__(self, "trace_id", str(trace))
        if self.runtime_snapshot is None and self.snapshot is not None:
            object.__setattr__(self, "runtime_snapshot", self.snapshot)
        elif self.snapshot is None and self.runtime_snapshot is not None:
            object.__setattr__(self, "snapshot", self.runtime_snapshot)

    def child(
        self,
        *,
        session_id: str,
        run_id: str,
        call_id: str = "",
        workflow_id: str = "",
    ) -> "WorkflowExecutionContext":
        """Create a nested context while inheriting authority and cancel.

        Child permissions/capabilities are copies, never a fresh unrestricted
        mapping.  ``workflow_id`` is appended only for cycle detection; a
        repeated workflow therefore fails before it can execute a node.
        """
        parent_call = call_id or self.parent_call_id
        lineage = tuple(self.lineage)
        if self.parent_call_id:
            lineage = (*lineage, self.parent_call_id)
        if call_id and (not lineage or lineage[-1] != call_id):
            lineage = (*lineage, call_id)
        stack = tuple(self.workflow_stack)
        if workflow_id:
            stack = (*stack, str(workflow_id))
        return WorkflowExecutionContext(
            parent_session_id=session_id,
            parent_run_id=run_id,
            parent_turn_id=self.parent_turn_id,
            parent_call_id=parent_call,
            cwd=self.cwd,
            cancellation=self.cancellation,
            pause_on_cancel=self.pause_on_cancel,
            permissions=dict(self.permissions),
            event_metadata=dict(self.event_metadata),
            attachments=list(self.attachments),
            runtime_snapshot=_json_copy(self.runtime_snapshot),
            environment=_json_copy(self.environment),
            capabilities=_json_copy(self.capabilities),
            trace_id=self.trace_id,
            lineage=lineage,
            workflow_stack=stack,
            depth=max(0, int(self.depth)) + 1,
            max_depth=max(0, int(self.max_depth)),
            snapshot=_json_copy(self.snapshot),
            _workflow_stack_internal=True,
        )

    def enter_workflow(self, workflow_id: str) -> "WorkflowExecutionContext":
        """Mark a workflow active, rejecting recursive/cyclic invocation."""
        identity = str(workflow_id or "").strip()
        if not identity:
            return self
        if identity in self.workflow_stack:
            raise WorkflowRecursionError(
                f"workflow invocation cycle detected: {' -> '.join((*self.workflow_stack, identity))}"
            )
        # ``depth`` is the number of nested workflow boundaries below the
        # root.  A max depth of zero therefore still permits the root run and
        # rejects its first child; the boundary is exceeded only at ``>``.
        if self.depth > max(0, int(self.max_depth)):
            raise WorkflowNestingError(
                f"workflow nesting depth limit exceeded ({self.max_depth})"
            )
        return replace(
            self,
            workflow_stack=(*self.workflow_stack, identity),
            runtime_credentials={},
            _workflow_stack_internal=True,
        )

    def metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "parent_session_id": self.parent_session_id,
            "parent_run_id": self.parent_run_id,
            "parent_turn_id": self.parent_turn_id,
            "parent_call_id": self.parent_call_id,
            "cwd": self.cwd,
            "pause_on_cancel": _json_copy(self.pause_on_cancel)
            if isinstance(self.pause_on_cancel, (bool, int, float, str, type(None)))
            else False,
            "permissions": _json_copy(self.permissions),
            "runtime_permissions": _json_copy(self.permissions),
            **_json_copy(self.event_metadata),
        }
        if self.attachments:
            metadata["attachments"] = _json_copy(self.attachments)
        if self.runtime_snapshot is not None:
            metadata["runtime_snapshot"] = _json_copy(self.runtime_snapshot)
            if self.snapshot is None:
                metadata["snapshot"] = _json_copy(self.runtime_snapshot)
        elif self.snapshot is not None:
            metadata["snapshot"] = _json_copy(self.snapshot)
        if self.environment:
            metadata["environment"] = _json_copy(self.environment)
        if self.capabilities:
            metadata["capabilities"] = _json_copy(self.capabilities)
        if self.trace_id:
            metadata["trace_id"] = self.trace_id
        if self.lineage:
            metadata["lineage"] = list(self.lineage)
        if self.workflow_stack:
            metadata["workflow_stack"] = list(self.workflow_stack)
        metadata["depth"] = int(self.depth)
        metadata["max_depth"] = int(self.max_depth)
        return metadata


class WorkflowValidationError(ValueError):
    """Raised when a workflow graph cannot be executed safely."""


class WorkflowExpressionError(WorkflowExecutorError):
    """A safe expression failure preserved as machine-readable node error."""

    def __init__(self, error: ExpressionError) -> None:
        self.expression_error = error
        super().__init__(error.to_json())


class WorkflowPermissionError(PermissionError):
    """Raised when a command/script node is not allowed by the host gate."""


class WorkflowCapabilityError(PermissionError):
    """Raised when a node declaration is not authorized by its host context."""


class WorkflowRecursionError(WorkflowValidationError):
    """Raised when a nested workflow calls itself through the active chain."""


class WorkflowNestingError(WorkflowValidationError):
    """Raised when the configured nested workflow depth is exceeded."""


class LazyInput:
    """A lazily-resolved workflow input supplied to trusted node executors.

    Lazy inputs are declared on a port (``lazy: true``) or through a node's
    ``config.lazy_inputs`` data.  The resolver is created by the runner from
    the value table; it is never loaded from the workflow document.  Built-in
    executors materialize this object before invoking their host service,
    while a trusted plugin executor may defer or omit the value as needed.
    """

    __slots__ = ("name", "_resolver", "_resolved", "_value")

    def __init__(self, name: str, resolver: Callable[[], Any]) -> None:
        self.name = str(name or "")
        self._resolver = resolver
        self._resolved = False
        self._value: Any = None

    def resolve(self) -> Any:
        if not self._resolved:
            self._value = self._resolver()
            self._resolved = True
        return self._value

    async def aresolve(self) -> Any:
        value = self.resolve()
        if inspect.isawaitable(value):
            try:
                value = await value
            except BaseException:
                # A failed deferred read must remain retryable.  In
                # particular, cancellation should not permanently cache the
                # coroutine object that was interrupted.
                self._resolved = False
                self._value = None
                raise
            self._value = value
        return value

    def __await__(self):
        """Allow trusted executors to use ``await inputs["port"]`` directly."""

        return self.aresolve().__await__()

    @property
    def value(self) -> Any:
        return self.resolve()

    @property
    def resolved(self) -> bool:
        return self._resolved

    def __repr__(self) -> str:
        return f"LazyInput({self.name!r}, resolved={self._resolved})"


LazyValue = LazyInput


class WorkflowConflictError(RuntimeError):
    """Raised when a compare-and-swap revision no longer matches."""
