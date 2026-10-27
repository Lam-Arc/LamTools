"""Packet conversion, JSON boundaries and public execution evidence."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import json
import math
from collections.abc import Mapping
from typing import Any
from .adapters import adapt_data_packet
from .data_packet import WorkflowDataPacket, is_data_packet, packet_to_legacy
from .executors import WorkflowExpansionError
from .models import WorkflowDef, WorkflowInputParam, WorkflowNode, WorkflowNodeState
from .runner_context import WorkflowExecutionContext


def _mark_cancelled(
    node_states: dict[str, WorkflowNodeState],
    workflow: WorkflowDef,
    order: list[str],
    from_index: int,
) -> None:
    for node_id in order[from_index:]:
        state = node_states.get(node_id)
        if state is not None and state.status == "idle":
            state.status = "cancelled"


def _as_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _summarize(value: Any) -> str:
    from .runner_context import LazyInput
    if isinstance(value, LazyInput):
        return repr(value)
    if isinstance(value, str):
        return value if len(value) <= 500 else value[:500] + "…"
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= 500 else text[:500] + "…"


def _serialize_prompt_value(value: Any) -> str:
    """Serialize an executable AI-node input without applying UI preview limits."""
    from .runner_context import LazyInput
    if isinstance(value, LazyInput):
        return repr(value)
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


def _safe_tool_calls(value: Any) -> list[dict[str, Any]]:
    raw_calls = _field(value, "tool_calls", [])
    if not isinstance(raw_calls, (list, tuple)):
        return []
    calls: list[dict[str, Any]] = []
    for raw in raw_calls:
        name = str(_field(raw, "name", "") or "").strip()
        status = str(_field(raw, "status", "") or "").strip()
        if name or status:
            calls.append({**({"name": name} if name else {}), **({"status": status} if status else {})})
    return calls


def _model_audit_metadata(response: Any, *, model_id: str, rounds: int) -> dict[str, Any]:
    metadata: dict[str, Any] = {"kind": "model", "model_id": model_id, "rounds": rounds}
    finish_reason = str(_field(response, "finish_reason", "") or "").strip()
    if finish_reason:
        metadata["finish_reason"] = finish_reason
    calls = _safe_tool_calls(response)
    if calls:
        metadata["tool_calls"] = calls
    usage = _field(response, "usage")
    if isinstance(usage, Mapping):
        safe_usage = {
            str(key): nested for key, nested in usage.items()
            if isinstance(nested, (int, float)) and not isinstance(nested, bool)
        }
        if safe_usage:
            metadata["usage"] = safe_usage
    return metadata


def _agent_audit_metadata(
    result: Any, *, node: WorkflowNode, configured_model: Any
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "kind": "agent",
        "agent": str(node.config.get("agent") or ""),
        "model_id": str(_field(result, "model_id", configured_model) or configured_model or ""),
    }
    for key in (
        "session_id", "run_id", "decision", "tool_call_count", "model_rounds",
        "ended_with_final_response",
    ):
        value = _field(result, key)
        if value not in (None, ""):
            metadata[key] = value
    breakdown = _field(result, "tool_call_breakdown")
    if isinstance(breakdown, Mapping):
        metadata["tool_calls"] = [
            {"name": str(name), "count": int(count)}
            for name, count in breakdown.items()
            if str(name).strip() and isinstance(count, int) and not isinstance(count, bool)
        ]
    elif _safe_tool_calls(result):
        metadata["tool_calls"] = _safe_tool_calls(result)
    return metadata


async def _materialize_inputs(values: dict[str, Any]) -> dict[str, Any]:
    """Resolve lazy values at a built-in service boundary."""
    from .runner_context import LazyInput
    result: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, LazyInput):
            result[key] = await value.aresolve()
        else:
            result[key] = value
    return result


def _contains_lazy_input(value: Any) -> bool:
    from .runner_context import LazyInput
    if isinstance(value, LazyInput):
        return True
    if isinstance(value, dict):
        return any(_contains_lazy_input(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_lazy_input(item) for item in value)
    return False


def _is_executor_surface(value: Any) -> bool:
    """Return whether a value can be adapted as a trusted node executor."""

    return (
        callable(value)
        or callable(getattr(value, "execute", None))
        or callable(getattr(value, "run", None))
    )


def _inherited_allowed_tools(
    context: WorkflowExecutionContext | None,
) -> set[str] | None:
    if context is None:
        return None
    candidates: list[Any] = [
        context.permissions.get("allowed_tools"),
        context.capabilities.get("allowed_tools"),
        context.capabilities.get("tools"),
    ]
    for candidate in candidates:
        if isinstance(candidate, (list, tuple, set, frozenset)):
            result = {str(item).strip() for item in candidate if str(item).strip()}
            return result
    return None


def _execution_model_id(context: WorkflowExecutionContext | None) -> str:
    """Resolve the run-level model inherited by model and agent nodes."""
    if context is None:
        return ""
    for source in (context.event_metadata, context.runtime_snapshot, context.snapshot):
        if isinstance(source, dict):
            model_id = str(source.get("model_id") or source.get("modelId") or "").strip()
            if model_id:
                return model_id
    return ""


def _executor_result_to_legacy(
    value: Any,
    *,
    node: WorkflowNode | None = None,
) -> Any:
    """Accept an explicit packet result while retaining the old result shape."""

    if isinstance(value, WorkflowDataPacket) or is_data_packet(value):
        legacy = packet_to_legacy(value)
        output_ports = node.output_ports() if node is not None else []
        if len(output_ports) == 1:
            return {output_ports[0].name: legacy}
        if isinstance(legacy, Mapping) and output_ports:
            names = {port.name for port in output_ports}
            if set(legacy).issubset(names):
                return dict(legacy)
        # A scalar/object/array legacy result maps to the conventional output
        # port; existing mapping results are otherwise left untouched.
        return {"output": legacy}
    return value


def _packet_view_for_inputs(value: Mapping[str, Any]) -> WorkflowDataPacket:
    """Preserve an already-canonical single input packet's item metadata."""

    if len(value) == 1:
        candidate = next(iter(value.values()))
        if isinstance(candidate, WorkflowDataPacket) or is_data_packet(candidate):
            return WorkflowDataPacket.coerce(candidate)
    candidate = value.get("packet") if isinstance(value, Mapping) else None
    if isinstance(candidate, WorkflowDataPacket) or is_data_packet(candidate):
        return WorkflowDataPacket.coerce(candidate)
    return adapt_data_packet(value)


def _assert_json_workflow_data(workflow: WorkflowDef) -> None:
    """Reject callable/non-JSON values in a dynamic expansion contract."""
    try:
        _assert_json_value(workflow.to_dict())
    except (TypeError, ValueError) as exc:
        raise WorkflowExpansionError(
            "workflow expansion must contain JSON-compatible data only"
        ) from exc
    # ``to_dict`` intentionally uses ``default=str`` for durable legacy data;
    # inspect the live model as well so a callable cannot be stringified past
    # this security boundary.
    for node in workflow.nodes:
        try:
            _assert_json_value(node.config)
            _assert_json_value(node.position)
        except (TypeError, ValueError) as exc:
            raise WorkflowExpansionError(
                "workflow expansion node config must contain JSON values only"
            ) from exc
        for port in node.ports:
            try:
                _assert_json_value(port.value)
            except (TypeError, ValueError) as exc:
                raise WorkflowExpansionError(
                    "workflow expansion port values must contain JSON values only"
                ) from exc
    for param in workflow.input_params:
        try:
            _assert_json_value(param.name)
            _assert_json_value(param.type)
            _assert_json_value(param.description)
            _assert_json_value(param.required)
            _assert_json_value(param.default)
        except (TypeError, ValueError) as exc:
            raise WorkflowExpansionError(
                "workflow expansion input defaults must contain JSON values only"
            ) from exc


def _coerce_expansion_input_param(value: Any) -> WorkflowInputParam:
    """Normalize one ephemeral input declaration or raise a clear error."""

    if isinstance(value, WorkflowInputParam):
        return value
    if isinstance(value, dict):
        return WorkflowInputParam.from_dict(value)
    raise WorkflowExpansionError(
        f"workflow expansion input parameter must be an object: {type(value).__name__}"
    )


def _assert_json_value(value: Any) -> None:
    """Strictly validate JSON data without ``default=str`` coercion."""
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            _assert_json_value(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_json_value(item)
        return
    raise TypeError(f"non-JSON value: {type(value).__name__}")


def _cache_facts(node_states: dict[str, WorkflowNodeState]) -> dict[str, dict[str, Any]]:
    return {
        node_id: {
            "status": state.cache_status,
            "key": state.cache_key,
            "hit": state.cache_status == "hit",
        }
        for node_id, state in node_states.items()
        if state.cache_status != "bypass" or state.cache_key
    }
