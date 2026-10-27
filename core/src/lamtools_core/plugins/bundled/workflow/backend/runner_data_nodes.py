"""Content, template, condition, merge and join node execution."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import re
from dataclasses import replace
from typing import Any
from .models import WorkflowNode
from .runner_context import WorkflowExecutionContext


async def _execute_content(
    runner, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str
) -> dict[str, Any]:
    """Content nodes emit each output port's configured constant value."""
    result: dict[str, Any] = {}
    for port in node.output_ports():
        result[port.name] = port.value
    return result


def _execute_passthrough(runner, node: WorkflowNode, bound_inputs: dict[str, Any]) -> dict[str, Any]:
    """Map same-name inputs to outputs, with a predictable single-value fallback."""
    from .runner_graph import SKIP_SENTINEL, _default_output_port
    active = {key: value for key, value in bound_inputs.items() if value != SKIP_SENTINEL}
    fallback = next(iter(active.values()), node.config.get("value"))
    outputs = node.output_ports()
    if not outputs:
        return {_default_output_port(node) or "output": fallback}
    return {port.name: active.get(port.name, fallback) for port in outputs}


def _execute_template(
    runner,
    node: WorkflowNode,
    bound_inputs: dict[str, Any],
    *,
    execution_context: WorkflowExecutionContext | None = None,
) -> dict[str, Any]:
    from .runner_expressions import _evaluate_workflow_expression, _is_structured_expression
    from .runner_graph import SKIP_SENTINEL, _default_output_port
    from .runner_values import _summarize
    raw_template = node.config.get("template", node.config.get("text", node.config.get("content", "")))
    if _is_structured_expression(raw_template):
        rendered_value = _evaluate_workflow_expression(
            raw_template,
            node=node,
            bound_inputs=bound_inputs,
            execution_context=execution_context,
        )
        rendered = rendered_value if isinstance(rendered_value, str) else _summarize(rendered_value)
        return {port.name: rendered for port in node.output_ports()} or {
            _default_output_port(node) or "output": rendered
        }

    template = str(raw_template)

    def replace(match: re.Match[str]) -> str:
        value = bound_inputs.get(match.group(1).strip(), "")
        if value in (None, SKIP_SENTINEL):
            return ""
        return value if isinstance(value, str) else _summarize(value)

    rendered = re.sub(r"\{\{\s*([^{}]+?)\s*\}\}", replace, template)
    return {port.name: rendered for port in node.output_ports()} or {
        _default_output_port(node) or "output": rendered
    }


def _execute_condition(
    runner,
    node: WorkflowNode,
    bound_inputs: dict[str, Any],
    *,
    execution_context: WorkflowExecutionContext | None = None,
) -> dict[str, Any]:
    from .runner_expressions import _eval_condition
    from .runner_graph import SKIP_SENTINEL
    raw_expression = node.config.get("condition") or node.config.get("expression") or "value"
    matched = _eval_condition(
        raw_expression,
        bound_inputs,
        node=node,
        execution_context=execution_context,
    )
    value = bound_inputs.get("value", next(iter(bound_inputs.values()), None))
    result: dict[str, Any] = {}
    for port in node.output_ports():
        lowered = port.name.strip().lower()
        if lowered in {"true", "yes", "then", "matched"}:
            result[port.name] = value if matched else SKIP_SENTINEL
        elif lowered in {"false", "no", "else", "unmatched"}:
            result[port.name] = value if not matched else SKIP_SENTINEL
        elif lowered in {"result", "condition", "matched_bool"}:
            result[port.name] = matched
        else:
            result[port.name] = value if matched else SKIP_SENTINEL
    return result or {"true": value if matched else SKIP_SENTINEL, "false": value if not matched else SKIP_SENTINEL}


def _execute_merge(runner, node: WorkflowNode, bound_inputs: dict[str, Any]) -> dict[str, Any]:
    from .runner_graph import SKIP_SENTINEL, _default_output_port
    active: list[Any] = []
    for value in bound_inputs.values():
        items = value if isinstance(value, list) else [value]
        active.extend(item for item in items if item != SKIP_SENTINEL)
    selected = active[0] if active else SKIP_SENTINEL
    return {port.name: selected for port in node.output_ports()} or {
        _default_output_port(node) or "output": selected
    }


def _execute_join(runner, node: WorkflowNode, bound_inputs: dict[str, Any]) -> dict[str, Any]:
    from .runner_graph import SKIP_SENTINEL, _default_output_port
    joined = {key: value for key, value in bound_inputs.items() if value != SKIP_SENTINEL}
    return {port.name: joined for port in node.output_ports()} or {
        _default_output_port(node) or "output": joined
    }
