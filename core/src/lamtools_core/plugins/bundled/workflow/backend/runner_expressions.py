"""Safe workflow expressions, conditions and secret-safe evaluation context."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import ast
import math
from typing import Any
from .expressions import Expression, ExpressionContext, ExpressionError, evaluate as evaluate_expression
from .models import WorkflowDef, WorkflowNode
from .runner_context import WorkflowExecutionContext


_CONDITION_BUILTINS = {
    "len": len, "str": str, "int": int, "float": float, "bool": bool,
    "any": any, "all": all, "min": min, "max": max, "sum": sum,
    "abs": abs, "round": round, "isinstance": isinstance, "True": True,
    "False": False, "None": None,
}


_EXPRESSION_NO_ITEM = object()


_EXPRESSION_SECRET_FIELDS = {
    "password",
    "passwd",
    "secret",
    "secrets",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "client_secret",
    "authorization",
    "cookie",
    "credential_secret",
}


_EXPRESSION_CREDENTIAL_FIELDS = {
    "id",
    "name",
    "label",
    "display_name",
    "provider",
    "provider_id",
    "type",
    "kind",
    "ref",
    "reference",
    "credential_ref",
    "credential_id",
    "masked",
    "redacted",
    "status",
}


def _is_structured_expression(value: Any) -> bool:
    return type(value) is dict or type(value) is Expression


def _expression_secret_field(name: str) -> bool:
    lowered = name.casefold()
    return lowered in _EXPRESSION_SECRET_FIELDS or lowered.endswith(("_password", "_secret", "_token", "_api_key"))


def _expression_safe_value(value: Any, *, credential_metadata: bool = False) -> Any:
    """Copy only plain JSON data, removing secret-bearing fields.

    Runtime node configs and upstream values are host-owned objects, so the
    safe expression context is built as a fresh tree.  Unsupported values
    (including ``LazyInput``) become ``None`` and are never exposed through a
    Python object attribute or protocol method.
    """
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        return value if math.isfinite(value) else None
    if type(value) is list:
        return [_expression_safe_value(item) for item in value]
    if type(value) is not dict:
        return None
    copied: dict[str, Any] = {}
    for key, item in value.items():
        if type(key) is not str or not key or key.startswith("__") or key.endswith("__"):
            continue
        lowered = key.casefold()
        if _expression_secret_field(key):
            continue
        if lowered in {"credential", "credentials"}:
            if type(item) is not dict:
                continue
            metadata: dict[str, Any] = {}
            for metadata_key, metadata_value in item.items():
                if (
                    type(metadata_key) is str
                    and metadata_key.casefold() in _EXPRESSION_CREDENTIAL_FIELDS
                ):
                    metadata[metadata_key] = _expression_safe_value(metadata_value, credential_metadata=True)
            copied[key] = metadata
            continue
        if credential_metadata and lowered not in _EXPRESSION_CREDENTIAL_FIELDS:
            continue
        copied[key] = _expression_safe_value(item, credential_metadata=credential_metadata)
    return copied


def _expression_item(bound_inputs: dict[str, Any], item: Any = _EXPRESSION_NO_ITEM) -> Any:
    if item is not _EXPRESSION_NO_ITEM:
        return item
    if "item" in bound_inputs:
        return bound_inputs["item"]
    if "value" in bound_inputs:
        return bound_inputs["value"]
    if len(bound_inputs) == 1:
        return next(iter(bound_inputs.values()))
    return bound_inputs


def _evaluate_workflow_expression(
    expression: dict[str, Any] | Expression,
    *,
    node: WorkflowNode | None,
    bound_inputs: dict[str, Any],
    execution_context: WorkflowExecutionContext | None = None,
    item: Any = _EXPRESSION_NO_ITEM,
) -> Any:
    """Evaluate an AST with the documented runtime roots.

    ``input`` is the current node/source bound-input map, ``item`` is the
    current singular value (or raw transform value), ``node`` is non-secret
    node metadata, and ``env`` is a redacted execution environment.
    """
    from .runner_context import WorkflowExpressionError
    raw_environment = execution_context.environment if execution_context is not None else {}
    context_node = (
        {
            "id": node.id,
            "kind": node.kind,
            "type_id": node.type_id or node.kind,
            "title": node.title,
        }
        if node is not None
        else None
    )
    context = ExpressionContext(
        input=_expression_safe_value(bound_inputs),
        item=_expression_safe_value(_expression_item(bound_inputs, item)),
        node=_expression_safe_value(context_node),
        env=_expression_safe_value(raw_environment),
    )
    try:
        return evaluate_expression(expression, context)
    except ExpressionError as exc:
        # The JSON payload becomes the node-state error and can be parsed by
        # API/CLI consumers without scraping a human-formatted message.
        raise WorkflowExpressionError(exc) from exc


def _source_node(source_id: str, workflow: WorkflowDef) -> WorkflowNode | None:
    return workflow.node(source_id)


def _eval_condition(
    expr: Any,
    bound_inputs: dict[str, Any],
    *,
    node: WorkflowNode | None = None,
    execution_context: WorkflowExecutionContext | None = None,
    item: Any = _EXPRESSION_NO_ITEM,
) -> bool:
    """Evaluate an AST safely or retain the explicit Python legacy fallback.

    ``bound_inputs`` (port name → value) are injected as local variables so
    expressions like ``len(text) > 100`` or ``quality >= 0.8 and source in
    ['A','B']`` work naturally. A restricted set of builtins (``len``, ``str``,
    ``int``, ``float``, ``bool``, ``any``, ``all``, ``min``, ``max``, ``sum``,
    ``abs``, ``round``, ``isinstance``) is available. Empty/missing condition →
    always True (execute). Evaluation errors → False (skip).

    Trust boundary: conditions are written by the workflow author, who can
    already run arbitrary shell/Python nodes, so ``eval`` here is not a
    security boundary (audit 07 S4). As defensive hardening, any attribute
    access on a name starting with ``_`` is rejected, which blocks the classic
    ``x.__class__.__mro__...`` sandbox-escape chain while allowing benign
    method calls like ``text.strip()``.
    """
    if _is_structured_expression(expr):
        return bool(
            _evaluate_workflow_expression(
                expr,
                node=node,
                bound_inputs=bound_inputs,
                execution_context=execution_context,
                item=item,
            )
        )
    if not expr or not str(expr).strip():
        return True
    source = str(expr).strip()
    try:
        tree = ast.parse(source, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                return False
        return bool(eval(source, {"__builtins__": _CONDITION_BUILTINS}, dict(bound_inputs)))  # noqa: S307 — trusted user-authored workflow condition
    except Exception:
        return False
