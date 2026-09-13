"""A small, JSON-native expression language for Workflow documents.

The Workflow runtime historically accepted Python snippets in a few fields.
This module is deliberately independent from that compatibility behaviour.  It
defines a versioned JSON AST and a parser for a small expression syntax.  The
evaluator only operates on values made from the JSON primitive types, lists,
and dictionaries.  It never follows object attributes or invokes a value from
the input context.

The canonical AST is made of dictionaries such as::

    {"type": "path", "root": "input", "segments": ["customer", "name"]}
    {"type": "binary", "op": ">", "left": {...}, "right": {...}}

``validate`` accepts either a node or the versioned envelope returned by
``expression_to_dict`` and returns a canonical node.  ``parse`` accepts a
canonical node, a versioned envelope, or the small textual form.  Textual
``{{ ... }}`` interpolation is provided only as an explicit legacy adapter;
it does not alter the old Workflow runtime.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Final, TypeAlias


EXPRESSION_SCHEMA: Final[str] = "lamtools.workflow.expression"
EXPRESSION_VERSION: Final[int] = 1
# Short aliases are useful to callers that expose schema metadata in a
# generic protocol envelope.
SCHEMA: Final[str] = EXPRESSION_SCHEMA
VERSION: Final[int] = EXPRESSION_VERSION
ERROR_SCHEMA: Final[str] = "lamtools.workflow.expression-error"
ERROR_VERSION: Final[int] = 1

JSONScalar: TypeAlias = None | bool | int | float | str
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]

_ROOTS: Final[frozenset[str]] = frozenset({"input", "item", "node", "env"})
_NODE_TYPES: Final[frozenset[str]] = frozenset(
    {"literal", "path", "ref", "array", "list", "object", "map", "unary", "binary", "compare", "logical", "coalesce", "template"}
)
_UNARY_OPS: Final[frozenset[str]] = frozenset({"!", "not", "neg", "+", "-"})
_BINARY_OPS: Final[frozenset[str]] = frozenset(
    {
        "+",
        "-",
        "*",
        "/",
        "%",
        "==",
        "!=",
        "<",
        "<=",
        ">",
        ">=",
        "&&",
        "and",
        "||",
        "or",
        "??",
        "add",
        "sub",
        "mul",
        "div",
        "mod",
        "eq",
        "neq",
        "lt",
        "lte",
        "gt",
        "gte",
        "coalesce",
    }
)
_SENSITIVE_FIELDS: Final[frozenset[str]] = frozenset(
    {
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
)
_CREDENTIAL_CONTAINERS: Final[frozenset[str]] = frozenset({"credential", "credentials"})
_CREDENTIAL_METADATA_FIELDS: Final[frozenset[str]] = frozenset(
    {
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
)
_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class ExpressionLimits:
    """Resource limits applied while parsing, validating, and evaluating.

    The limits are intentionally finite even for trusted workflow authors.
    They prevent a document from turning recursive AST walking, string
    interpolation, or arithmetic into an unbounded operation.
    """

    max_depth: int = 32
    max_nodes: int = 256
    max_string_length: int = 4096
    max_array_length: int = 128
    max_object_keys: int = 128
    max_path_segments: int = 32
    max_number_bits: int = 256
    max_context_nodes: int = 4096
    max_template_parts: int = 128

    def __post_init__(self) -> None:
        values = (
            ("max_depth", self.max_depth),
            ("max_nodes", self.max_nodes),
            ("max_string_length", self.max_string_length),
            ("max_array_length", self.max_array_length),
            ("max_object_keys", self.max_object_keys),
            ("max_path_segments", self.max_path_segments),
            ("max_number_bits", self.max_number_bits),
            ("max_context_nodes", self.max_context_nodes),
            ("max_template_parts", self.max_template_parts),
        )
        for name, value in values:
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")


DEFAULT_LIMITS: Final[ExpressionLimits] = ExpressionLimits()


class ExpressionError(ValueError):
    """Base error with a stable, JSON-serializable representation."""

    stage: str = "expression"

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: tuple[str | int, ...] = (),
        details: dict[str, JSONValue] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.path = tuple(path)
        self.details = dict(details or {})
        super().__init__(message)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "schema": ERROR_SCHEMA,
            "version": ERROR_VERSION,
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
            "path": list(self.path),
            "details": _json_safe_error_value(self.details),
        }

    as_dict = to_dict

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ExpressionParseError(ExpressionError):
    stage = "parse"


class ExpressionValidationError(ExpressionError):
    stage = "validate"


class ExpressionEvaluationError(ExpressionError):
    stage = "evaluate"


@dataclass(frozen=True, slots=True)
class ExpressionContext:
    """The four read-only roots visible to an expression."""

    input: JSONValue = None
    item: JSONValue = None
    node: JSONValue = None
    env: JSONValue = None

    def to_dict(self) -> dict[str, JSONValue]:
        # Do not expose arbitrary attributes or the caller's mutable objects.
        # The evaluator performs the bounded JSON copy before reading values.
        return {"input": self.input, "item": self.item, "node": self.node, "env": self.env}


@dataclass(frozen=True, slots=True)
class Expression:
    """Optional object wrapper for callers that want an explicit envelope."""

    node: dict[str, JSONValue]
    schema: str = EXPRESSION_SCHEMA
    version: int = EXPRESSION_VERSION

    def to_dict(self) -> dict[str, JSONValue]:
        return {"schema": self.schema, "version": self.version, "expression": self.node}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def expression_to_dict(expression: object, *, limits: ExpressionLimits = DEFAULT_LIMITS) -> dict[str, JSONValue]:
    """Return a versioned, JSON-serializable expression envelope."""

    node = parse(expression, limits=limits) if type(expression) is str else validate(expression, limits=limits)
    return {"schema": EXPRESSION_SCHEMA, "version": EXPRESSION_VERSION, "expression": node}


def expression_to_json(expression: object, *, limits: ExpressionLimits = DEFAULT_LIMITS) -> str:
    return json.dumps(expression_to_dict(expression, limits=limits), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compile_expression(expression: object, *, limits: ExpressionLimits = DEFAULT_LIMITS) -> Expression:
    return Expression(parse(expression, limits=limits) if type(expression) is str else validate(expression, limits=limits))


def parse(source: object, *, limits: ExpressionLimits = DEFAULT_LIMITS) -> dict[str, JSONValue]:
    """Parse text or validate an AST, returning a canonical AST node.

    Text uses JSON-like literals, ``input.foo`` paths, arrays/objects,
    ``!``, ``and``/``or``, comparison and arithmetic operators, and ``??``.
    A string containing ``{{...}}`` is routed through
    :func:`parse_legacy_template`.
    """

    try:
        if type(source) is str:
            # A JSON-encoded AST is convenient at RPC boundaries.  Only treat
            # it as an AST when it has an unmistakable node/envelope marker;
            # ordinary JSON-like object expressions continue through the
            # textual parser below.
            candidate = _json_ast_candidate(source)
            if candidate is not None:
                return validate(candidate, limits=limits)
            if "{{" in source or "}}" in source:
                return parse_legacy_template(source, limits=limits)
            return _TextParser(source, limits).parse()
        return validate(source, limits=limits)
    except ExpressionError:
        raise
    except RecursionError:
        # A recursion overflow from malformed deeply nested text is still a
        # structured resource error, never a raw interpreter failure.
        if type(source) is str:
            raise ExpressionParseError(
                "resource_limit",
                "expression nesting exceeds the configured limit",
                details={"limit": limits.max_depth},
            ) from None
        raise


parse_expression = parse


def validate(expression: object, *, limits: ExpressionLimits = DEFAULT_LIMITS) -> dict[str, JSONValue]:
    """Validate and normalize a JSON AST or versioned envelope.

    Validation raises :class:`ExpressionValidationError` on the first issue.
    ``is_valid`` is provided for callers that need a boolean probe.
    """

    if not isinstance(limits, ExpressionLimits):
        raise TypeError("limits must be an ExpressionLimits instance")
    if type(expression) is str:
        return parse(expression, limits=limits)
    node = _unwrap_envelope(expression, limits)
    state = {"nodes": 0}
    return _validate_node(node, limits=limits, state=state, depth=0, path=("expression",))


validate_expression = validate


def is_valid(expression: object, *, limits: ExpressionLimits = DEFAULT_LIMITS) -> bool:
    try:
        validate(expression, limits=limits)
    except (ExpressionError, TypeError, ValueError):
        return False
    return True


def evaluate(
    expression: object,
    context: ExpressionContext | dict[str, object] | None = None,
    *,
    limits: ExpressionLimits = DEFAULT_LIMITS,
    strict_paths: bool = False,
    missing: str | None = None,
) -> JSONValue:
    """Evaluate a validated expression against bounded, read-only JSON data.

    Missing dictionary keys and out-of-range list indices resolve to ``None``
    by default.  Set ``strict_paths=True`` (or ``missing='error'``) to turn a
    missing path into a structured ``missing_path`` error.
    """

    if missing is not None:
        if missing not in {"null", "none", "error"}:
            raise ValueError("missing must be 'null', 'none', or 'error'")
        strict_paths = missing == "error"
    node = parse(expression, limits=limits) if type(expression) is str else validate(expression, limits=limits)
    values = _prepare_context(context, limits)
    try:
        return _evaluate_node(node, values, limits=limits, depth=0, strict_paths=strict_paths, path=("expression",))
    except ExpressionError:
        raise
    except RecursionError:
        raise ExpressionEvaluationError(
            "resource_limit",
            "expression nesting exceeds the configured limit",
            details={"limit": limits.max_depth},
        ) from None
    except (ArithmeticError, OverflowError, ValueError, TypeError) as exc:
        raise ExpressionEvaluationError("evaluation_error", "expression evaluation failed", details={"reason": str(exc)}) from None


evaluate_expression = evaluate


def parse_legacy_template(source: str, *, limits: ExpressionLimits = DEFAULT_LIMITS) -> dict[str, JSONValue]:
    """Parse controlled ``{{ expression }}`` interpolation.

    Literal text is retained as text parts.  Each interpolation is parsed by
    the same expression parser; no name lookup or Python syntax is accepted.
    """

    if type(source) is not str:
        raise ExpressionParseError("invalid_source", "legacy template source must be a string")
    if len(source) > limits.max_string_length:
        raise ExpressionParseError(
            "resource_limit",
            "template exceeds the configured string length",
            details={"limit": limits.max_string_length},
        )
    parts: list[dict[str, JSONValue]] = []
    cursor = 0
    while cursor < len(source):
        start = source.find("{{", cursor)
        close = source.find("}}", cursor)
        if close >= 0 and (start < 0 or close < start):
            raise ExpressionParseError("template_syntax", "closing template delimiter has no opening delimiter", details={"position": close})
        if start < 0:
            _append_template_text(parts, source[cursor:], limits)
            cursor = len(source)
            break
        _append_template_text(parts, source[cursor:start], limits)
        end = source.find("}}", start + 2)
        if end < 0:
            raise ExpressionParseError("template_syntax", "template interpolation is not closed", details={"position": start})
        inner = source[start + 2 : end].strip()
        if not inner:
            raise ExpressionParseError("template_syntax", "template interpolation cannot be empty", details={"position": start})
        if "{{" in inner or "}}" in inner:
            raise ExpressionParseError("template_syntax", "nested template delimiters are not supported", details={"position": start})
        parts.append({"expr": _TextParser(inner, limits).parse()})
        cursor = end + 2
    if not parts:
        parts.append({"text": source})
    if len(parts) > limits.max_template_parts:
        raise ExpressionParseError(
            "resource_limit",
            "template has too many parts",
            details={"limit": limits.max_template_parts},
        )
    return validate({"type": "template", "parts": parts}, limits=limits)


legacy_template = parse_legacy_template


def _unwrap_envelope(expression: object, limits: ExpressionLimits) -> object:
    if type(expression) is Expression:
        if expression.schema != EXPRESSION_SCHEMA or expression.version != EXPRESSION_VERSION:
            raise ExpressionValidationError("schema_version", "unsupported expression schema or version")
        return expression.node
    if type(expression) is not dict:
        raise ExpressionValidationError("invalid_ast", "expression must be a JSON object")
    if "schema" not in expression and "version" not in expression:
        return expression
    allowed = {"schema", "version", "expression", "expr"}
    _check_keys(expression, allowed, path=("expression",), stage="validate")
    if expression.get("schema") != EXPRESSION_SCHEMA or expression.get("version") != EXPRESSION_VERSION:
        raise ExpressionValidationError(
            "schema_version",
            "unsupported expression schema or version",
            path=("expression",),
            details={"expected_schema": EXPRESSION_SCHEMA, "expected_version": EXPRESSION_VERSION},
        )
    if "expression" in expression and "expr" in expression:
        raise ExpressionValidationError("duplicate_field", "expression envelope cannot contain both expression and expr", path=("expression",))
    if "expression" in expression:
        return expression["expression"]
    if "expr" in expression:
        return expression["expr"]
    raise ExpressionValidationError("missing_field", "expression envelope is missing expression", path=("expression",))


def _json_ast_candidate(source: str) -> dict[str, JSONValue] | None:
    stripped = source.strip()
    if not stripped or stripped[0] != "{" or stripped[-1] != "}":
        return None
    try:
        candidate = json.loads(stripped)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if type(candidate) is not dict:
        return None
    if "type" in candidate or "schema" in candidate or "version" in candidate:
        return candidate
    return None


def _validate_node(
    node: object,
    *,
    limits: ExpressionLimits,
    state: dict[str, int],
    depth: int,
    path: tuple[str | int, ...],
) -> dict[str, JSONValue]:
    if depth > limits.max_depth:
        raise ExpressionValidationError("resource_limit", "expression depth exceeds the configured limit", path=path, details={"limit": limits.max_depth})
    if type(node) is not dict:
        raise ExpressionValidationError("invalid_node", "AST node must be a JSON object", path=path)
    state["nodes"] += 1
    if state["nodes"] > limits.max_nodes:
        raise ExpressionValidationError("resource_limit", "expression has too many AST nodes", path=path, details={"limit": limits.max_nodes})
    node_type = node.get("type")
    if type(node_type) is not str or node_type not in _NODE_TYPES:
        raise ExpressionValidationError("unsupported_node", "AST node type is not supported", path=path, details={"type": node_type if type(node_type) is str else None})

    if node_type == "literal":
        _check_keys(node, {"type", "value"}, path=path, stage="validate")
        if "value" not in node:
            raise ExpressionValidationError("missing_field", "literal node is missing value", path=path + ("value",))
        _validate_json_value(node["value"], limits=limits, depth=depth, state=state, path=path + ("value",), context=False)
        return {"type": "literal", "value": node["value"]}

    if node_type in {"path", "ref"}:
        _check_keys(node, {"type", "root", "segments", "path"}, path=path, stage="validate")
        root = node.get("root")
        segments: object = node.get("segments")
        if "path" in node and ("root" in node or "segments" in node):
            raise ExpressionValidationError("duplicate_field", "path node cannot mix path with root/segments", path=path)
        if "path" in node:
            root, segments = _path_from_value(node["path"], limits=limits, path=path + ("path",))
        if type(root) is not str or root not in _ROOTS:
            raise ExpressionValidationError("invalid_path", "path root must be input, item, node, or env", path=path + ("root",))
        if type(segments) is not list:
            raise ExpressionValidationError("invalid_path", "path segments must be an array", path=path + ("segments",))
        if len(segments) > limits.max_path_segments:
            raise ExpressionValidationError("resource_limit", "path has too many segments", path=path + ("segments",), details={"limit": limits.max_path_segments})
        normalized: list[JSONValue] = []
        for index, segment in enumerate(segments):
            if type(segment) is str:
                if not segment or len(segment) > limits.max_string_length or "\x00" in segment or segment.startswith("__") or segment.endswith("__"):
                    raise ExpressionValidationError("invalid_path", "path segment is not allowed", path=path + ("segments", index))
                if _is_sensitive_field(segment):
                    raise ExpressionValidationError("forbidden_path", "sensitive fields cannot be read from expression context", path=path + ("segments", index))
                normalized.append(segment)
            elif type(segment) is int and segment >= 0 and segment <= limits.max_array_length:
                normalized.append(segment)
            else:
                raise ExpressionValidationError("invalid_path", "path segment must be a safe name or non-negative index", path=path + ("segments", index))
        return {"type": "path", "root": root, "segments": normalized}

    if node_type in {"array", "list"}:
        _check_keys(node, {"type", "items"}, path=path, stage="validate")
        items = node.get("items")
        if type(items) is not list:
            raise ExpressionValidationError("invalid_node", "array items must be an array", path=path + ("items",))
        if len(items) > limits.max_array_length:
            raise ExpressionValidationError("resource_limit", "array has too many items", path=path + ("items",), details={"limit": limits.max_array_length})
        return {"type": "array", "items": [_validate_node(item, limits=limits, state=state, depth=depth + 1, path=path + ("items", index)) for index, item in enumerate(items)]}

    if node_type in {"object", "map"}:
        _check_keys(node, {"type", "fields", "entries"}, path=path, stage="validate")
        fields: object = node.get("fields")
        if "entries" in node:
            if "fields" in node:
                raise ExpressionValidationError("duplicate_field", "object node cannot contain both fields and entries", path=path)
            entries = node["entries"]
            if type(entries) is not dict:
                raise ExpressionValidationError("invalid_node", "object entries must be an object", path=path + ("entries",))
            fields = [{"key": key, "value": value} for key, value in sorted(entries.items(), key=lambda pair: pair[0])]
        if type(fields) is not list:
            raise ExpressionValidationError("invalid_node", "object fields must be an array", path=path + ("fields",))
        if len(fields) > limits.max_object_keys:
            raise ExpressionValidationError("resource_limit", "object has too many fields", path=path + ("fields",), details={"limit": limits.max_object_keys})
        normalized_fields: list[dict[str, JSONValue]] = []
        seen: set[str] = set()
        for index, field in enumerate(fields):
            field_path = path + ("fields", index)
            if type(field) is not dict:
                raise ExpressionValidationError("invalid_node", "object field must be an object", path=field_path)
            _check_keys(field, {"key", "value"}, path=field_path, stage="validate")
            key = field.get("key")
            if type(key) is not str or not key or len(key) > limits.max_string_length or "\x00" in key or key.startswith("__") or key.endswith("__"):
                raise ExpressionValidationError("invalid_key", "object field key is not allowed", path=field_path + ("key",))
            if key in seen:
                raise ExpressionValidationError("duplicate_key", "object field keys must be unique", path=field_path + ("key",), details={"key": key})
            seen.add(key)
            if "value" not in field:
                raise ExpressionValidationError("missing_field", "object field is missing value", path=field_path + ("value",))
            normalized_fields.append({"key": key, "value": _validate_node(field["value"], limits=limits, state=state, depth=depth + 1, path=field_path + ("value",))})
        return {"type": "object", "fields": normalized_fields}

    if node_type == "unary":
        _check_keys(node, {"type", "op", "arg", "operand"}, path=path, stage="validate")
        if "arg" in node and "operand" in node:
            raise ExpressionValidationError("duplicate_field", "unary node cannot contain both arg and operand", path=path)
        arg = node.get("arg", node.get("operand"))
        op = node.get("op")
        if type(op) is not str or op not in _UNARY_OPS:
            raise ExpressionValidationError("unsupported_operator", "unary operator is not supported", path=path + ("op",))
        if "arg" not in node and "operand" not in node:
            raise ExpressionValidationError("missing_field", "unary node is missing arg", path=path + ("arg",))
        return {"type": "unary", "op": op, "arg": _validate_node(arg, limits=limits, state=state, depth=depth + 1, path=path + ("arg",))}

    if node_type in {"binary", "compare", "logical"}:
        _check_keys(node, {"type", "op", "operator", "left", "right"}, path=path, stage="validate")
        if "op" in node and "operator" in node:
            raise ExpressionValidationError("duplicate_field", "binary node cannot contain both op and operator", path=path)
        op = node.get("op", node.get("operator"))
        if type(op) is not str or op not in _BINARY_OPS:
            raise ExpressionValidationError("unsupported_operator", "binary operator is not supported", path=path + ("op",))
        if "left" not in node or "right" not in node:
            raise ExpressionValidationError("missing_field", "binary node requires left and right", path=path)
        return {
            "type": "binary",
            "op": op,
            "left": _validate_node(node["left"], limits=limits, state=state, depth=depth + 1, path=path + ("left",)),
            "right": _validate_node(node["right"], limits=limits, state=state, depth=depth + 1, path=path + ("right",)),
        }

    if node_type == "coalesce":
        _check_keys(node, {"type", "items"}, path=path, stage="validate")
        items = node.get("items")
        if type(items) is not list or not items:
            raise ExpressionValidationError("invalid_node", "coalesce items must be a non-empty array", path=path + ("items",))
        if len(items) > limits.max_array_length:
            raise ExpressionValidationError("resource_limit", "coalesce has too many operands", path=path + ("items",), details={"limit": limits.max_array_length})
        return {"type": "coalesce", "items": [_validate_node(item, limits=limits, state=state, depth=depth + 1, path=path + ("items", index)) for index, item in enumerate(items)]}

    # Template
    _check_keys(node, {"type", "parts", "template"}, path=path, stage="validate")
    if "parts" in node and "template" in node:
        raise ExpressionValidationError("duplicate_field", "template node cannot contain both parts and template", path=path)
    if "template" in node:
        if type(node["template"]) is not str:
            raise ExpressionValidationError("invalid_node", "template must be a string", path=path + ("template",))
        return _validate_node(parse_legacy_template(node["template"], limits=limits), limits=limits, state=state, depth=depth, path=path)
    parts = node.get("parts")
    if type(parts) is not list:
        raise ExpressionValidationError("invalid_node", "template parts must be an array", path=path + ("parts",))
    if not parts or len(parts) > limits.max_template_parts:
        raise ExpressionValidationError("resource_limit", "template has an invalid number of parts", path=path + ("parts",), details={"limit": limits.max_template_parts})
    normalized_parts: list[dict[str, JSONValue]] = []
    for index, part in enumerate(parts):
        part_path = path + ("parts", index)
        if type(part) is not dict:
            raise ExpressionValidationError("invalid_node", "template part must be an object", path=part_path)
        _check_keys(part, {"text", "expr"}, path=part_path, stage="validate")
        if "text" in part and "expr" in part:
            raise ExpressionValidationError("duplicate_field", "template part cannot contain text and expr", path=part_path)
        if "text" in part:
            text = part["text"]
            if type(text) is not str or len(text) > limits.max_string_length or "\x00" in text:
                raise ExpressionValidationError("invalid_string", "template text is not allowed", path=part_path + ("text",))
            normalized_parts.append({"text": text})
        elif "expr" in part:
            normalized_parts.append({"expr": _validate_node(part["expr"], limits=limits, state=state, depth=depth + 1, path=part_path + ("expr",))})
        else:
            raise ExpressionValidationError("missing_field", "template part requires text or expr", path=part_path)
    return {"type": "template", "parts": normalized_parts}


def _validate_json_value(
    value: object,
    *,
    limits: ExpressionLimits,
    depth: int,
    state: dict[str, int],
    path: tuple[str | int, ...],
    context: bool,
) -> None:
    if depth > limits.max_depth:
        raise (ExpressionEvaluationError if context else ExpressionValidationError)("resource_limit", "value depth exceeds the configured limit", path=path, details={"limit": limits.max_depth})
    state["nodes"] += 1
    max_nodes = limits.max_context_nodes if context else limits.max_nodes
    if state["nodes"] > max_nodes:
        raise (ExpressionEvaluationError if context else ExpressionValidationError)("resource_limit", "value has too many nodes", path=path, details={"limit": max_nodes})
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if value.bit_length() > limits.max_number_bits:
            raise (ExpressionEvaluationError if context else ExpressionValidationError)("resource_limit", "number exceeds the configured size", path=path, details={"limit": limits.max_number_bits})
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise (ExpressionEvaluationError if context else ExpressionValidationError)("invalid_number", "number must be finite", path=path)
        return
    if type(value) is str:
        if len(value) > limits.max_string_length or "\x00" in value:
            raise (ExpressionEvaluationError if context else ExpressionValidationError)("resource_limit", "string exceeds the configured limit", path=path, details={"limit": limits.max_string_length})
        return
    if type(value) is list:
        if len(value) > limits.max_array_length:
            raise (ExpressionEvaluationError if context else ExpressionValidationError)("resource_limit", "array exceeds the configured limit", path=path, details={"limit": limits.max_array_length})
        for index, item in enumerate(value):
            _validate_json_value(item, limits=limits, depth=depth + 1, state=state, path=path + (index,), context=context)
        return
    if type(value) is dict:
        if len(value) > limits.max_object_keys:
            raise (ExpressionEvaluationError if context else ExpressionValidationError)("resource_limit", "object exceeds the configured limit", path=path, details={"limit": limits.max_object_keys})
        for key, item in value.items():
            if type(key) is not str:
                raise (ExpressionEvaluationError if context else ExpressionValidationError)("invalid_context", "object keys must be strings", path=path)
            if not key or len(key) > limits.max_string_length or "\x00" in key or key.startswith("__") or key.endswith("__"):
                raise (ExpressionEvaluationError if context else ExpressionValidationError)("invalid_key", "object key is not allowed", path=path + (key,))
            if context:
                _check_context_field(key, item, limits=limits, path=path + (key,))
            _validate_json_value(item, limits=limits, depth=depth + 1, state=state, path=path + (key,), context=context)
        return
    code = "invalid_context" if context else "invalid_literal"
    raise (ExpressionEvaluationError if context else ExpressionValidationError)(code, "value must contain only JSON-compatible built-in values", path=path)


def _prepare_context(context: ExpressionContext | dict[str, object] | None, limits: ExpressionLimits) -> dict[str, JSONValue]:
    if context is None:
        source: dict[str, object] = {"input": None, "item": None, "node": None, "env": None}
    elif type(context) is ExpressionContext:
        source = {"input": context.input, "item": context.item, "node": context.node, "env": context.env}
    elif type(context) is dict:
        source = context
    else:
        raise ExpressionEvaluationError("invalid_context", "context must be an ExpressionContext or JSON object")
    unknown = [key for key in source if type(key) is not str or key not in _ROOTS]
    if unknown:
        raise ExpressionEvaluationError("forbidden_context", "context may only contain input, item, node, and env roots", details={"roots": [key for key in unknown if type(key) is str]})
    copied: dict[str, JSONValue] = {}
    state = {"nodes": 0}
    for root in ("input", "item", "node", "env"):
        value = source.get(root)
        _validate_json_value(value, limits=limits, depth=0, state=state, path=(root,), context=True)
        copied[root] = _copy_json_value(value)
    return copied


def _copy_json_value(value: JSONValue) -> JSONValue:
    if type(value) is list:
        return [_copy_json_value(item) for item in value]
    if type(value) is dict:
        return {key: _copy_json_value(item) for key, item in value.items()}
    return value


def _evaluate_node(
    node: dict[str, JSONValue],
    values: dict[str, JSONValue],
    *,
    limits: ExpressionLimits,
    depth: int,
    strict_paths: bool,
    path: tuple[str | int, ...],
) -> JSONValue:
    if depth > limits.max_depth:
        raise ExpressionEvaluationError("resource_limit", "expression depth exceeds the configured limit", path=path, details={"limit": limits.max_depth})
    node_type = node["type"]
    if node_type == "literal":
        return _copy_json_value(node["value"])
    if node_type == "path":
        root = node["root"]
        current: JSONValue = values[root]
        walked: list[str | int] = [root]
        for segment in node["segments"]:
            walked.append(segment)
            if type(current) is dict and type(segment) is str:
                if segment not in current:
                    if strict_paths:
                        raise ExpressionEvaluationError("missing_path", "expression path does not exist", path=path, details={"path": walked})
                    return None
                current = current[segment]
            elif type(current) is list and type(segment) is int:
                if segment >= len(current):
                    if strict_paths:
                        raise ExpressionEvaluationError("missing_path", "expression path index is out of range", path=path, details={"path": walked})
                    return None
                current = current[segment]
            else:
                if strict_paths:
                    raise ExpressionEvaluationError("missing_path", "expression path cannot continue through this value", path=path, details={"path": walked})
                return None
        return _copy_json_value(current)
    if node_type == "array":
        return [_evaluate_node(item, values, limits=limits, depth=depth + 1, strict_paths=strict_paths, path=path + ("items", index)) for index, item in enumerate(node["items"])]
    if node_type == "object":
        result: dict[str, JSONValue] = {}
        for field in node["fields"]:
            result[field["key"]] = _evaluate_node(field["value"], values, limits=limits, depth=depth + 1, strict_paths=strict_paths, path=path + ("fields", field["key"]))
        return result
    if node_type == "unary":
        op = node["op"]
        value = _evaluate_node(node["arg"], values, limits=limits, depth=depth + 1, strict_paths=strict_paths, path=path + ("arg",))
        if op in {"!", "not"}:
            return not _truthy(value)
        number = _require_number(value, path=path)
        result = -number if op in {"-", "neg"} else +number
        return _check_number_result(result, limits=limits, path=path)
    if node_type == "coalesce":
        for index, item in enumerate(node["items"]):
            value = _evaluate_node(item, values, limits=limits, depth=depth + 1, strict_paths=strict_paths, path=path + ("items", index))
            if value is not None:
                return value
        return None
    if node_type == "template":
        chunks: list[str] = []
        for index, part in enumerate(node["parts"]):
            if "text" in part:
                chunks.append(part["text"])
            else:
                value = _evaluate_node(part["expr"], values, limits=limits, depth=depth + 1, strict_paths=strict_paths, path=path + ("parts", index, "expr"))
                chunks.append(_stringify(value, limits=limits, path=path + ("parts", index)))
            if sum(len(chunk) for chunk in chunks) > limits.max_string_length:
                raise ExpressionEvaluationError("resource_limit", "template result exceeds the configured string length", path=path, details={"limit": limits.max_string_length})
        return "".join(chunks)

    left = _evaluate_node(node["left"], values, limits=limits, depth=depth + 1, strict_paths=strict_paths, path=path + ("left",))
    op = node["op"]
    if op in {"&&", "and"}:
        return _truthy(left) and _truthy(_evaluate_node(node["right"], values, limits=limits, depth=depth + 1, strict_paths=strict_paths, path=path + ("right",)))
    if op in {"||", "or"}:
        return _truthy(left) or _truthy(_evaluate_node(node["right"], values, limits=limits, depth=depth + 1, strict_paths=strict_paths, path=path + ("right",)))
    if op in {"??", "coalesce"}:
        return left if left is not None else _evaluate_node(node["right"], values, limits=limits, depth=depth + 1, strict_paths=strict_paths, path=path + ("right",))
    right = _evaluate_node(node["right"], values, limits=limits, depth=depth + 1, strict_paths=strict_paths, path=path + ("right",))
    return _apply_binary(op, left, right, limits=limits, path=path)


def _apply_binary(op: str, left: JSONValue, right: JSONValue, *, limits: ExpressionLimits, path: tuple[str | int, ...]) -> JSONValue:
    if op in {"==", "eq"}:
        return _safe_equal(left, right)
    if op in {"!=", "neq"}:
        return not _safe_equal(left, right)
    if op in {"<", "<=", ">", ">=", "lt", "lte", "gt", "gte"}:
        if (type(left) in {int, float} and type(right) in {int, float}) or (type(left) is str and type(right) is str):
            if op in {"<", "lt"}:
                return left < right
            if op in {"<=", "lte"}:
                return left <= right
            if op in {">", "gt"}:
                return left > right
            return left >= right
        raise ExpressionEvaluationError("type_error", "ordering requires two numbers or two strings", path=path)
    if op in {"+", "add", "-", "sub", "*", "mul", "/", "div", "%", "mod"}:
        left_number = _require_number(left, path=path + ("left",))
        right_number = _require_number(right, path=path + ("right",))
        if op in {"+", "add"}:
            result = left_number + right_number
        elif op in {"-", "sub"}:
            result = left_number - right_number
        elif op in {"*", "mul"}:
            result = left_number * right_number
        elif op in {"/", "div"}:
            if right_number == 0:
                raise ExpressionEvaluationError("division_by_zero", "division by zero is not allowed", path=path)
            result = left_number / right_number
        else:
            if right_number == 0:
                raise ExpressionEvaluationError("division_by_zero", "remainder by zero is not allowed", path=path)
            result = left_number % right_number
        return _check_number_result(result, limits=limits, path=path)
    raise ExpressionEvaluationError("unsupported_operator", "binary operator is not supported", path=path, details={"operator": op})


def _require_number(value: JSONValue, *, path: tuple[str | int, ...]) -> int | float:
    if type(value) not in {int, float}:
        raise ExpressionEvaluationError("type_error", "arithmetic requires numbers", path=path)
    if type(value) is float and not math.isfinite(value):
        raise ExpressionEvaluationError("invalid_number", "number must be finite", path=path)
    return value


def _check_number_result(value: int | float, *, limits: ExpressionLimits, path: tuple[str | int, ...]) -> int | float:
    if type(value) is int and value.bit_length() > limits.max_number_bits:
        raise ExpressionEvaluationError("resource_limit", "number exceeds the configured size", path=path, details={"limit": limits.max_number_bits})
    if type(value) is float and not math.isfinite(value):
        raise ExpressionEvaluationError("invalid_number", "number must be finite", path=path)
    return value


def _truthy(value: JSONValue) -> bool:
    if value is None or value is False:
        return False
    if type(value) is bool:
        return True
    if type(value) in {int, float}:
        return value != 0
    if type(value) is str:
        return len(value) > 0
    if type(value) in {list, dict}:
        return len(value) > 0
    return False


def _safe_equal(left: JSONValue, right: JSONValue) -> bool:
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    if type(left) in {int, float} and type(right) in {int, float}:
        return left == right
    if type(left) is not type(right):
        return False
    return left == right


def _stringify(value: JSONValue, *, limits: ExpressionLimits, path: tuple[str | int, ...]) -> str:
    if value is None:
        result = "null"
    elif type(value) is bool:
        result = "true" if value else "false"
    elif type(value) is str:
        result = value
    elif type(value) in {int, float}:
        result = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    else:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))
    if len(result) > limits.max_string_length:
        raise ExpressionEvaluationError("resource_limit", "string value exceeds the configured limit", path=path, details={"limit": limits.max_string_length})
    return result


def _check_keys(value: dict[str, object], allowed: set[str], *, path: tuple[str | int, ...], stage: str) -> None:
    unknown = [key for key in value if type(key) is not str or key not in allowed]
    if unknown:
        error_type = ExpressionParseError if stage == "parse" else ExpressionValidationError
        raise error_type("unknown_field", "AST object contains an unsupported field", path=path, details={"fields": [key for key in unknown if type(key) is str]})


def _is_sensitive_field(name: str) -> bool:
    lowered = name.casefold()
    return lowered in _SENSITIVE_FIELDS or any(
        lowered.endswith(suffix) for suffix in ("_password", "_secret", "_token", "_api_key")
    )


def _check_context_field(key: str, value: object, *, limits: ExpressionLimits, path: tuple[str | int, ...]) -> None:
    if _is_sensitive_field(key):
        raise ExpressionEvaluationError("forbidden_context", "credential and secret fields are not available to expressions", path=path)
    if key.casefold() in _CREDENTIAL_CONTAINERS:
        if type(value) is not dict:
            raise ExpressionEvaluationError("forbidden_context", "credential context must be metadata object", path=path)
        for nested_key in value:
            if type(nested_key) is not str or nested_key.casefold() not in _CREDENTIAL_METADATA_FIELDS:
                raise ExpressionEvaluationError("forbidden_context", "credential context may contain metadata only", path=path + (nested_key,) if type(nested_key) is str else path)


def _json_safe_error_value(value: object) -> JSONValue:
    if value is None or type(value) in {bool, int, float, str}:
        return value
    if type(value) is list:
        return [_json_safe_error_value(item) for item in value]
    if type(value) is dict:
        return {str(key): _json_safe_error_value(item) for key, item in value.items()}
    return str(value)


def _path_from_value(value: object, *, limits: ExpressionLimits, path: tuple[str | int, ...]) -> tuple[str, list[JSONValue]]:
    if type(value) is list:
        if not value or type(value[0]) is not str:
            raise ExpressionValidationError("invalid_path", "path array must start with a supported root", path=path)
        return value[0], value[1:]
    if type(value) is not str:
        raise ExpressionValidationError("invalid_path", "path must be a string or array", path=path)
    if len(value) > limits.max_string_length:
        raise ExpressionValidationError("resource_limit", "path exceeds the configured string length", path=path)
    match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)(?:\.([A-Za-z_][A-Za-z0-9_]*))*", value)
    if not match:
        raise ExpressionValidationError("invalid_path", "path string must contain safe dot-separated names", path=path)
    chunks = value.split(".")
    return chunks[0], chunks[1:]


def _append_template_text(parts: list[dict[str, JSONValue]], text: str, limits: ExpressionLimits) -> None:
    if not text:
        return
    if len(text) > limits.max_string_length:
        raise ExpressionParseError("resource_limit", "template text exceeds the configured string length", details={"limit": limits.max_string_length})
    if parts and "text" in parts[-1]:
        merged = parts[-1]["text"] + text
        if len(merged) > limits.max_string_length:
            raise ExpressionParseError("resource_limit", "template text exceeds the configured string length", details={"limit": limits.max_string_length})
        parts[-1] = {"text": merged}
    else:
        parts.append({"text": text})


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    value: object
    position: int


class _Lexer:
    def __init__(self, source: str, limits: ExpressionLimits) -> None:
        self.source = source
        self.limits = limits
        self.position = 0
        self.tokens: list[_Token] = []

    def tokenize(self) -> list[_Token]:
        if len(self.source) > self.limits.max_string_length:
            raise ExpressionParseError("resource_limit", "expression exceeds the configured string length", details={"limit": self.limits.max_string_length})
        while self.position < len(self.source):
            start = self.position
            char = self.source[start]
            if char.isspace():
                self.position += 1
                continue
            if char in {"\"", "'"}:
                self.tokens.append(_Token("string", self._string(char), start))
                continue
            if char.isdigit():
                self.tokens.append(_Token("number", self._number(), start))
                continue
            if char.isascii() and (char.isalpha() or char == "_"):
                self.position += 1
                while self.position < len(self.source) and self.source[self.position].isascii() and (self.source[self.position].isalnum() or self.source[self.position] == "_"):
                    self.position += 1
                self.tokens.append(_Token("identifier", self.source[start : self.position], start))
                continue
            matched = False
            for operator in ("??", "||", "&&", "==", "!=", "<=", ">="):
                if self.source.startswith(operator, start):
                    self.position += len(operator)
                    self.tokens.append(_Token("operator", operator, start))
                    matched = True
                    break
            if matched:
                continue
            if char in "+-*/%<>!()[]{}:,.":
                self.position += 1
                self.tokens.append(_Token("operator", char, start))
                continue
            raise ExpressionParseError("syntax_error", "unexpected character in expression", details={"position": start})
        self.tokens.append(_Token("eof", "", len(self.source)))
        if len(self.tokens) > self.limits.max_nodes * 8 + 32:
            raise ExpressionParseError("resource_limit", "expression has too many tokens", details={"limit": self.limits.max_nodes * 8 + 32})
        return self.tokens

    def _string(self, quote: str) -> str:
        start = self.position
        self.position += 1
        chunks: list[str] = []
        escapes = {"\\": "\\", "\"": "\"", "'": "'", "n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "/": "/"}
        while self.position < len(self.source):
            char = self.source[self.position]
            self.position += 1
            if char == quote:
                result = "".join(chunks)
                if len(result) > self.limits.max_string_length:
                    raise ExpressionParseError("resource_limit", "string literal exceeds the configured limit", details={"position": start, "limit": self.limits.max_string_length})
                return result
            if char == "\\":
                if self.position >= len(self.source):
                    break
                escaped = self.source[self.position]
                self.position += 1
                if escaped == "u":
                    digits = self.source[self.position : self.position + 4]
                    if len(digits) != 4 or any(digit not in "0123456789abcdefABCDEF" for digit in digits):
                        raise ExpressionParseError("syntax_error", "invalid unicode escape", details={"position": self.position - 2})
                    chunks.append(chr(int(digits, 16)))
                    self.position += 4
                elif escaped in escapes:
                    chunks.append(escapes[escaped])
                else:
                    raise ExpressionParseError("syntax_error", "invalid string escape", details={"position": self.position - 1})
            else:
                if ord(char) < 0x20 or char == "\x00":
                    raise ExpressionParseError("syntax_error", "control character is not allowed in string", details={"position": self.position - 1})
                chunks.append(char)
        raise ExpressionParseError("syntax_error", "string literal is not closed", details={"position": start})

    def _number(self) -> int | float:
        start = self.position
        while self.position < len(self.source) and self.source[self.position].isdigit():
            self.position += 1
        if self.position < len(self.source) and self.source[self.position] == ".":
            self.position += 1
            fraction_start = self.position
            while self.position < len(self.source) and self.source[self.position].isdigit():
                self.position += 1
            if self.position == fraction_start:
                raise ExpressionParseError("syntax_error", "decimal point must be followed by digits", details={"position": self.position - 1})
        if self.position < len(self.source) and self.source[self.position] in {"e", "E"}:
            self.position += 1
            if self.position < len(self.source) and self.source[self.position] in {"+", "-"}:
                self.position += 1
            exponent_start = self.position
            while self.position < len(self.source) and self.source[self.position].isdigit():
                self.position += 1
            if self.position == exponent_start:
                raise ExpressionParseError("syntax_error", "exponent must contain digits", details={"position": self.position})
        token = self.source[start : self.position]
        if len(token) > 128:
            raise ExpressionParseError("resource_limit", "number literal is too long", details={"position": start})
        try:
            result: int | float = float(token) if any(marker in token for marker in ".eE") else int(token)
        except (ValueError, OverflowError):
            raise ExpressionParseError("invalid_number", "number literal is invalid", details={"position": start}) from None
        if type(result) is int and result.bit_length() > self.limits.max_number_bits:
            raise ExpressionParseError("resource_limit", "number exceeds the configured size", details={"position": start, "limit": self.limits.max_number_bits})
        if type(result) is float and not math.isfinite(result):
            raise ExpressionParseError("invalid_number", "number must be finite", details={"position": start})
        return result


class _TextParser:
    def __init__(self, source: str, limits: ExpressionLimits) -> None:
        self.limits = limits
        self.tokens = _Lexer(source, limits).tokenize()
        self.index = 0
        self.depth = 0

    def parse(self) -> dict[str, JSONValue]:
        result = self._coalesce()
        if self._current().kind != "eof":
            self._error("syntax_error", "unexpected token after expression")
        return validate(result, limits=self.limits)

    def _coalesce(self) -> dict[str, JSONValue]:
        left = self._or()
        while self._accept("??"):
            left = {"type": "binary", "op": "??", "left": left, "right": self._or()}
        return left

    def _or(self) -> dict[str, JSONValue]:
        left = self._and()
        while self._accept("||") or self._accept_identifier("or"):
            left = {"type": "binary", "op": "||", "left": left, "right": self._and()}
        return left

    def _and(self) -> dict[str, JSONValue]:
        left = self._compare()
        while self._accept("&&") or self._accept_identifier("and"):
            left = {"type": "binary", "op": "&&", "left": left, "right": self._compare()}
        return left

    def _compare(self) -> dict[str, JSONValue]:
        left = self._add()
        if self._current().value in {"==", "!=", "<", "<=", ">", ">="}:
            operator = self._advance().value
            right = self._add()
            left = {"type": "binary", "op": operator, "left": left, "right": right}
            if self._current().value in {"==", "!=", "<", "<=", ">", ">="}:
                self._error("syntax_error", "comparison chaining is not supported")
        return left

    def _add(self) -> dict[str, JSONValue]:
        left = self._multiply()
        while self._current().value in {"+", "-"}:
            operator = self._advance().value
            left = {"type": "binary", "op": operator, "left": left, "right": self._multiply()}
        return left

    def _multiply(self) -> dict[str, JSONValue]:
        left = self._unary()
        while self._current().value in {"*", "/", "%"}:
            operator = self._advance().value
            left = {"type": "binary", "op": operator, "left": left, "right": self._unary()}
        return left

    def _unary(self) -> dict[str, JSONValue]:
        current = self._current()
        if current.value in {"!", "-", "+"} or (current.kind == "identifier" and current.value == "not"):
            self._advance()
            self._enter()
            try:
                arg = self._unary()
            finally:
                self._leave()
            return {"type": "unary", "op": current.value, "arg": arg}
        return self._primary()

    def _primary(self) -> dict[str, JSONValue]:
        current = self._current()
        if current.kind == "number":
            self._advance()
            return {"type": "literal", "value": current.value}
        if current.kind == "string":
            self._advance()
            return {"type": "literal", "value": current.value}
        if current.kind == "identifier":
            self._advance()
            if current.value == "true":
                result: dict[str, JSONValue] = {"type": "literal", "value": True}
            elif current.value == "false":
                result = {"type": "literal", "value": False}
            elif current.value == "null":
                result = {"type": "literal", "value": None}
            elif current.value in _ROOTS:
                result = {"type": "path", "root": current.value, "segments": self._path_segments()}
            else:
                self._error("unknown_name", "only input, item, node, and env names are available")
            if self._current().value == "(":
                self._error("forbidden_call", "function calls are not supported")
            return result
        if self._accept("("):
            self._enter()
            try:
                result = self._coalesce()
            finally:
                self._leave()
            self._expect(")")
            return result
        if self._accept("["):
            self._enter()
            try:
                items: list[dict[str, JSONValue]] = []
                if not self._accept("]"):
                    while True:
                        items.append(self._coalesce())
                        if self._accept("]"):
                            break
                        self._expect(",")
                        if self._accept("]"):
                            break
                return {"type": "array", "items": items}
            finally:
                self._leave()
        if self._accept("{"):
            self._enter()
            try:
                fields: list[dict[str, JSONValue]] = []
                if not self._accept("}"):
                    while True:
                        key = self._advance()
                        if key.kind not in {"string", "identifier", "number"}:
                            self._error("syntax_error", "object key must be a string or name")
                        self._expect(":")
                        fields.append({"key": str(key.value), "value": self._coalesce()})
                        if self._accept("}"):
                            break
                        self._expect(",")
                        if self._accept("}"):
                            break
                return {"type": "object", "fields": fields}
            finally:
                self._leave()
        self._error("syntax_error", "expected a literal, path, array, object, or parenthesized expression")

    def _path_segments(self) -> list[JSONValue]:
        segments: list[JSONValue] = []
        while self._accept("."):
            token = self._advance()
            if token.kind != "identifier":
                self._error("invalid_path", "dot path segment must be a name")
            segments.append(token.value)
        while self._accept("["):
            token = self._advance()
            if token.kind not in {"string", "number"} or (token.kind == "number" and type(token.value) is not int):
                self._error("invalid_path", "bracket path segment must be a string or integer")
            self._expect("]")
            segments.append(token.value)
        if len(segments) > self.limits.max_path_segments:
            self._error("resource_limit", "path has too many segments")
        return segments

    def _current(self) -> _Token:
        return self.tokens[self.index]

    def _advance(self) -> _Token:
        token = self._current()
        self.index += 1
        return token

    def _accept(self, value: object) -> bool:
        if self._current().value == value:
            self.index += 1
            return True
        return False

    def _accept_identifier(self, value: str) -> bool:
        token = self._current()
        if token.kind == "identifier" and token.value == value:
            self.index += 1
            return True
        return False

    def _expect(self, value: object) -> None:
        if not self._accept(value):
            self._error("syntax_error", f"expected {value!r}")

    def _enter(self) -> None:
        self.depth += 1
        if self.depth > self.limits.max_depth:
            self._error("resource_limit", "expression depth exceeds the configured limit")

    def _leave(self) -> None:
        self.depth -= 1

    def _error(self, code: str, message: str) -> None:
        raise ExpressionParseError(code, message, details={"position": self._current().position})


__all__ = [
    "DEFAULT_LIMITS",
    "ERROR_SCHEMA",
    "ERROR_VERSION",
    "EXPRESSION_SCHEMA",
    "EXPRESSION_VERSION",
    "Expression",
    "ExpressionContext",
    "ExpressionError",
    "ExpressionEvaluationError",
    "ExpressionLimits",
    "ExpressionParseError",
    "ExpressionValidationError",
    "JSONScalar",
    "JSONValue",
    "SCHEMA",
    "VERSION",
    "compile_expression",
    "evaluate",
    "evaluate_expression",
    "expression_to_dict",
    "expression_to_json",
    "is_valid",
    "legacy_template",
    "parse",
    "parse_expression",
    "parse_legacy_template",
    "validate",
    "validate_expression",
]
