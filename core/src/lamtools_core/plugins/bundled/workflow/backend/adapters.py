"""Stable invocation contracts for Workflow integrations.

The Workflow runner used to know the concrete shape of both the Core LLM
client and the sub-agent runner.  That made embedding the runner in another
host needlessly difficult: a test double, a remote adapter, and the in-process
Core implementations all had to look exactly alike.  This module keeps the
boundary deliberately small and provides compatibility adapters for the two
legacy interfaces.

Adapters only dispatch calls.  They do not import arbitrary Python from a
workflow document; plugin code is installed by the host and is registered
explicitly through the execution registry.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, Protocol, runtime_checkable

from .data_packet import (
    WorkflowDataPacket,
    adapt_legacy_value,
    is_data_packet,
)


@runtime_checkable
class ModelInvoker(Protocol):
    """Protocol used by an AI/LLM Workflow node.

    ``request`` is the host's provider-neutral request object (normally
    :class:`lamtools_core.llm.LLMRequest`).  ``context`` is keyword-only so an
    adapter can add host correlation and authority without changing the
    request type.
    """

    async def invoke(self, request: Any, *, context: Any = None, **kwargs: Any) -> Any: ...


@runtime_checkable
class AgentInvoker(Protocol):
    """Protocol used by an Agent Workflow node."""

    async def invoke(
        self,
        task: str,
        *,
        agent: str = "",
        model: str = "",
        mode: str = "",
        attachments: Sequence[Any] | None = None,
        allowed_tools: Sequence[str] | None = None,
        context: Any = None,
        parent_call_id: str = "",
        parent_run_id: str = "",
        parent_turn_id: str = "",
        execution_context: Any = None,
        **extra: Any,
    ) -> Any: ...


@runtime_checkable
class NodeExecutor(Protocol):
    """Protocol implemented by a trusted plugin node executor."""

    async def execute(
        self,
        node: Any,
        inputs: Mapping[str, Any],
        *,
        context: Any = None,
    ) -> Any: ...


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _selected_kwargs(call: Any, kwargs: dict[str, Any]) -> dict[str, Any] | None:
    """Select named arguments without masking exceptions from the callee.

    Legacy Core implementations use ``execution_context`` while small host
    adapters generally use ``context``.  Signature selection lets both work,
    and importantly avoids the old pattern of catching ``TypeError`` and then
    invoking a function twice (which can duplicate side effects).
    """

    try:
        signature = inspect.signature(call)
    except (TypeError, ValueError):
        return None
    parameters = signature.parameters
    if any(
        p.kind == inspect.Parameter.POSITIONAL_ONLY
        and p.default is inspect.Parameter.empty
        for p in parameters.values()
    ):
        return None
    if any(
        p.kind in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }
        and p.default is inspect.Parameter.empty
        and name not in kwargs
        for name, p in parameters.items()
    ):
        return None
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return kwargs
    return {name: value for name, value in kwargs.items() if name in parameters}


async def _call(call: Any, kwargs: dict[str, Any], positional: tuple[Any, ...] = ()) -> Any:
    selected = _selected_kwargs(call, kwargs)
    if selected is not None:
        # A variadic callable has no named slot for the documented positional
        # contract.  Preserve those arguments instead of silently dropping
        # them merely because ``inspect.signature`` succeeded.
        if positional:
            try:
                signature = inspect.signature(call)
            except (TypeError, ValueError):
                result = call(*positional)
            else:
                has_varargs = any(
                    parameter.kind == inspect.Parameter.VAR_POSITIONAL
                    for parameter in signature.parameters.values()
                )
                named_positional = {
                    parameter.name
                    for parameter in signature.parameters.values()
                    if parameter.kind
                    in {
                        inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    }
                }
                if has_varargs and not named_positional:
                    result = call(*positional, **selected)
                else:
                    result = call(**selected)
        else:
            result = call(**selected)
    else:
        # Keep positional-only and opaque callables working without the old
        # ``try keyword call / catch TypeError / call again`` pattern.  That
        # pattern can duplicate a side effect when the callee itself raises a
        # TypeError.  When a signature is available, pass keyword arguments
        # that are not already occupied by the supplied positional values.
        try:
            signature = inspect.signature(call)
        except (TypeError, ValueError):
            result = call(*positional)
        else:
            positional_parameters = [
                parameter
                for parameter in signature.parameters.values()
                if parameter.kind
                in {
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    }
            ]
            # The legacy adapter supplies a canonical positional tuple
            # ``(node, inputs, context)`` (and analogous tuples for model and
            # agent calls).  A target may make only the first two arguments
            # positional and expose context as keyword-only.  Slice the tuple
            # to the target's actual positional slots before adding the
            # remaining named values; passing the full tuple would duplicate
            # a keyword-only context argument.
            call_positional = positional[: len(positional_parameters)]
            occupied = {
                parameter.name
                for parameter in positional_parameters[: len(call_positional)]
            }
            remaining = {
                name: value
                for name, value in kwargs.items()
                if name not in occupied
                and any(
                    parameter.name == name
                    and parameter.kind
                    in {
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        inspect.Parameter.KEYWORD_ONLY,
                    }
                    for parameter in signature.parameters.values()
                )
            }
            if any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            ):
                remaining = {
                    name: value for name, value in kwargs.items() if name not in occupied
                }
            result = call(*call_positional, **remaining)
    return await _maybe_await(result)


def _request_with_context(request: Any, context: Any) -> Any:
    """Attach context metadata to a dataclass-like request when possible."""

    if context is None or not hasattr(request, "metadata"):
        return request
    metadata = getattr(request, "metadata", None)
    metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
    metadata.setdefault(
        "workflow_execution",
        context.metadata() if callable(getattr(context, "metadata", None)) else context,
    )
    # LLMRequest is a frozen-looking value object in some hosts and mutable in
    # others.  ``replace`` preserves the original object when it is a
    # dataclass; the fallback mutates only a private copy of the metadata.
    try:
        return replace(request, metadata=metadata)
    except (TypeError, ValueError):
        try:
            request.metadata = metadata
        except (AttributeError, TypeError):
            pass
        return request


class LegacyModelInvokerAdapter:
    """Adapt ``LLMClient.complete(request)`` to :class:`ModelInvoker`.

    A modern object exposing ``invoke`` is accepted as well, which makes this
    adapter useful at the runner boundary even when a host has no legacy
    client at all.
    """

    def __init__(self, target: Any) -> None:
        self.target = target

    async def invoke(self, request: Any, *, context: Any = None, **extra: Any) -> Any:
        request = _request_with_context(request, context)
        call = getattr(self.target, "invoke", None)
        if call is None:
            call = getattr(self.target, "complete", None)
        if call is None and callable(self.target):
            call = self.target
        if call is None:
            raise TypeError("model invoker must expose invoke(), complete(), or be callable")
        return await _call(
            call,
            {"request": request, "context": context, "execution_context": context, **extra},
            (request,),
        )


class LegacyAgentInvokerAdapter:
    """Adapt ``SubAgentRunner.run(**kwargs)`` to :class:`AgentInvoker`."""

    def __init__(self, target: Any) -> None:
        self.target = target

    async def invoke(
        self,
        task: str,
        *,
        agent: str = "",
        model: str = "",
        mode: str = "",
        attachments: Sequence[Any] | None = None,
        allowed_tools: Sequence[str] | None = None,
        context: Any = None,
        parent_call_id: str = "",
        parent_run_id: str = "",
        parent_turn_id: str = "",
        execution_context: Any = None,
        **extra: Any,
    ) -> Any:
        call = getattr(self.target, "invoke", None)
        if call is None:
            call = getattr(self.target, "run", None)
        if call is None and callable(self.target):
            call = self.target
        if call is None:
            raise TypeError("agent invoker must expose invoke(), run(), or be callable")
        kwargs = {
            "task": task,
            "agent": agent,
            "model": model,
            "mode": mode,
            "attachments": (
                [attachments]
                if isinstance(attachments, (str, bytes, bytearray))
                else list(attachments or [])
            ),
            "allowed_tools": list(allowed_tools) if allowed_tools is not None else None,
            "context": context if context is not None else execution_context,
            "execution_context": execution_context if execution_context is not None else context,
            "parent_call_id": parent_call_id,
            "parent_run_id": parent_run_id,
            "parent_turn_id": parent_turn_id,
            **extra,
        }
        return await _call(call, kwargs, (task,))


class LegacyNodeExecutorAdapter:
    """Adapt a trusted executor's ``execute``/``run``/callable surface."""

    def __init__(self, target: Any) -> None:
        self.target = target

    async def execute(
        self,
        node: Any,
        inputs: Mapping[str, Any],
        *,
        context: Any = None,
        packet: WorkflowDataPacket | None = None,
        data_packet: WorkflowDataPacket | None = None,
    ) -> Any:
        call = getattr(self.target, "execute", None)
        if call is None:
            call = getattr(self.target, "run", None)
        if call is None and callable(self.target):
            call = self.target
        if call is None:
            raise TypeError("node executor must expose execute(), run(), or be callable")
        kwargs = {
            "node": node,
            "inputs": inputs,
            "bound_inputs": inputs,
            # Packet support is opt-in at the executor signature.  The
            # adapter still sends the historical ``inputs`` mapping unchanged.
            "packet": packet if packet is not None else data_packet,
            "data_packet": data_packet if data_packet is not None else packet,
            "context": context,
            "execution_context": context,
        }
        return await _call(call, kwargs, (node, inputs, context))


def adapt_model_invoker(target: Any) -> ModelInvoker | None:
    if target is None:
        return None
    if isinstance(target, LegacyModelInvokerAdapter):
        return target
    return LegacyModelInvokerAdapter(target)


def adapt_agent_invoker(target: Any) -> AgentInvoker | None:
    if target is None:
        return None
    if isinstance(target, LegacyAgentInvokerAdapter):
        return target
    return LegacyAgentInvokerAdapter(target)


def adapt_node_executor(target: Any) -> NodeExecutor:
    if isinstance(target, LegacyNodeExecutorAdapter):
        return target
    return LegacyNodeExecutorAdapter(target)


class WorkflowDataPacketAdapter:
    """Compatibility bridge for node hosts that still exchange raw values.

    The bridge makes the conversion explicit at the integration boundary.  It
    never guesses that an arbitrary mapping is already a packet; only the
    marked ``lamtools.workflow.data-packet`` envelope is accepted as one.
    """

    @staticmethod
    def to_packet(value: Any) -> WorkflowDataPacket:
        return WorkflowDataPacket.coerce(value)

    @staticmethod
    def from_packet(value: WorkflowDataPacket | Any) -> Any:
        packet = value if isinstance(value, WorkflowDataPacket) else WorkflowDataPacket.coerce(value)
        return packet.to_legacy()

    @staticmethod
    def is_packet(value: Any) -> bool:
        return is_data_packet(value)


def adapt_workflow_data(value: Any) -> WorkflowDataPacket:
    """Named adapter for legacy scalar/object/array node values."""

    return adapt_legacy_value(value)


def adapt_data_packet(value: Any) -> WorkflowDataPacket:
    """Canonical-or-legacy packet adapter used by plugin hosts."""

    return WorkflowDataPacket.coerce(value)


# Friendly aliases used by hosts that call these objects "legacy bridges".
ModelInvokerAdapter = LegacyModelInvokerAdapter
AgentInvokerAdapter = LegacyAgentInvokerAdapter
NodeExecutorAdapter = LegacyNodeExecutorAdapter
LLMModelInvokerAdapter = LegacyModelInvokerAdapter
SubAgentInvokerAdapter = LegacyAgentInvokerAdapter
LLMInvoker = ModelInvoker
SubAgentInvoker = AgentInvoker
LegacyLLMAdapter = LegacyModelInvokerAdapter
LegacySubAgentAdapter = LegacyAgentInvokerAdapter


__all__ = [
    "AgentInvoker",
    "AgentInvokerAdapter",
    "LegacyAgentInvokerAdapter",
    "LegacyModelInvokerAdapter",
    "LegacyNodeExecutorAdapter",
    "LegacyLLMAdapter",
    "LegacySubAgentAdapter",
    "LLMModelInvokerAdapter",
    "LLMInvoker",
    "ModelInvoker",
    "ModelInvokerAdapter",
    "NodeExecutor",
    "NodeExecutorAdapter",
    "SubAgentInvokerAdapter",
    "SubAgentInvoker",
    "adapt_agent_invoker",
    "adapt_model_invoker",
    "adapt_node_executor",
    "WorkflowDataPacketAdapter",
    "adapt_data_packet",
    "adapt_workflow_data",
]
