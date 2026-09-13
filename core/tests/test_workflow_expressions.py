"""Contract tests for the standalone Workflow expression engine."""

from __future__ import annotations

import json

import pytest

from lamtools_core.plugins.bundled.workflow.backend.expressions import (
    ERROR_SCHEMA,
    EXPRESSION_SCHEMA,
    EXPRESSION_VERSION,
    ExpressionContext,
    ExpressionEvaluationError,
    ExpressionLimits,
    ExpressionParseError,
    ExpressionValidationError,
    evaluate,
    expression_to_dict,
    expression_to_json,
    is_valid,
    parse,
    parse_legacy_template,
    validate,
)


def test_text_parser_supports_paths_values_and_operators() -> None:
    assert evaluate("input.amount * 2 + 1", {"input": {"amount": 4}}) == 9
    assert evaluate("input.ok && item.name == 'Ada'", {"input": {"ok": True}, "item": {"name": "Ada"}}) is True
    assert evaluate("input.missing ?? env.fallback", {"input": {}, "env": {"fallback": "default"}}) == "default"
    assert evaluate("[input.name, 2, false]", {"input": {"name": "Ada"}}) == ["Ada", 2, False]
    assert evaluate("{name: input.name, count: 2}", {"input": {"name": "Ada"}}) == {"name": "Ada", "count": 2}


def test_canonical_ast_and_versioned_envelope_are_json_serializable() -> None:
    node = parse({"type": "binary", "op": ">", "left": {"type": "path", "root": "input", "segments": ["score"]}, "right": {"type": "literal", "value": 5}})
    assert validate(expression_to_dict(node)) == node
    envelope = expression_to_dict(node)
    assert envelope["schema"] == EXPRESSION_SCHEMA
    assert envelope["version"] == EXPRESSION_VERSION
    assert json.loads(expression_to_json(node)) == envelope
    assert evaluate(envelope, {"input": {"score": 6}}) is True
    assert parse(json.dumps(node)) == node
    assert validate("input.score") == {"type": "path", "root": "input", "segments": ["score"]}


def test_legacy_template_uses_the_same_path_and_limit_rules() -> None:
    expression = parse_legacy_template("Hello {{ input.name }}; score={{ item.score }}")
    assert evaluate(expression, {"input": {"name": "Ada"}, "item": {"score": 7}}) == "Hello Ada; score=7"
    with pytest.raises(ExpressionParseError) as caught:
        parse_legacy_template("{{ input.name }")
    assert caught.value.code == "template_syntax"


def test_missing_paths_are_null_or_structured_errors() -> None:
    assert evaluate("input.missing", {"input": {}}) is None
    assert evaluate("input.items[4]", {"input": {"items": []}}) is None
    with pytest.raises(ExpressionEvaluationError) as caught:
        evaluate("input.missing", {"input": {}}, strict_paths=True)
    assert caught.value.code == "missing_path"
    assert caught.value.to_dict()["schema"] == ERROR_SCHEMA
    assert json.loads(caught.value.to_json())["code"] == "missing_path"


def test_type_errors_and_arithmetic_fail_without_python_coercion() -> None:
    with pytest.raises(ExpressionEvaluationError, match="arithmetic requires numbers") as caught:
        evaluate("input.name + 1", {"input": {"name": "one"}})
    assert caught.value.code == "type_error"
    with pytest.raises(ExpressionEvaluationError) as caught:
        evaluate("1 / 0")
    assert caught.value.code == "division_by_zero"


def test_short_circuit_does_not_read_the_unneeded_branch() -> None:
    assert evaluate("false && input.unavailable", {"input": {"unavailable": {"value": "no"}}}) is False
    assert evaluate("true || input.unavailable", {"input": {"unavailable": {"value": "no"}}}) is True
    assert evaluate("input.value ?? input.unavailable", {"input": {"value": 0, "unavailable": {"value": "no"}}}) == 0


def test_malicious_nodes_calls_attributes_and_unsafe_roots_are_rejected() -> None:
    malicious = [
        {"type": "call", "name": "open", "args": []},
        {"type": "path", "root": "input", "segments": ["__class__"]},
        {"type": "path", "root": "input", "segments": ["password"]},
        {"type": "path", "root": "process", "segments": []},
        {"type": "binary", "op": "in", "left": {"type": "literal", "value": 1}, "right": {"type": "literal", "value": [1]}},
        {"type": "literal", "value": {"__class__": "bad"}},
    ]
    for node in malicious:
        assert is_valid(node) is False
        with pytest.raises(ExpressionValidationError):
            validate(node)
    with pytest.raises(ExpressionParseError) as caught:
        parse("input.name.strip()")
    assert caught.value.code == "forbidden_call"


def test_context_is_bounded_json_and_credential_data_is_metadata_only() -> None:
    assert evaluate("node.credentials.ref", {"node": {"credentials": {"ref": "cred-1", "provider": "demo"}}}) == "cred-1"
    with pytest.raises(ExpressionEvaluationError) as caught:
        evaluate("input.name", {"input": {"api_key": "secret"}})
    assert caught.value.code == "forbidden_context"

    class HostObject:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError("attribute access must not be attempted")

    with pytest.raises(ExpressionEvaluationError) as caught:
        evaluate("input.value", {"input": HostObject()})  # type: ignore[arg-type]
    assert caught.value.code == "invalid_context"


def test_depth_node_string_and_number_limits_are_structured() -> None:
    tiny = ExpressionLimits(max_depth=2, max_nodes=8, max_string_length=4, max_number_bits=8)
    with pytest.raises(ExpressionParseError) as caught:
        parse("((input.value))", limits=tiny)
    assert caught.value.code == "resource_limit"
    with pytest.raises(ExpressionValidationError) as caught:
        validate({"type": "literal", "value": "12345"}, limits=tiny)
    assert caught.value.code == "resource_limit"
    with pytest.raises(ExpressionValidationError) as caught:
        validate({"type": "literal", "value": 256}, limits=tiny)
    assert caught.value.code == "resource_limit"


def test_context_and_ast_mutation_cannot_change_evaluation_inputs() -> None:
    context = {"input": {"value": [1]}}
    expression = parse("input.value")
    result = evaluate(expression, context)
    result.append(2)  # type: ignore[union-attr]
    assert context == {"input": {"value": [1]}}
    assert evaluate(expression, context) == [1]


def test_context_wrapper_exposes_only_the_four_declared_roots() -> None:
    context = ExpressionContext(input={"value": 3}, env={"fallback": 5})
    assert evaluate("input.value + env.fallback", context) == 8
    with pytest.raises(ExpressionEvaluationError) as caught:
        evaluate("input.value", {"input": {"value": 3}, "credentials": {"ref": "safe"}})
    assert caught.value.code == "forbidden_context"
