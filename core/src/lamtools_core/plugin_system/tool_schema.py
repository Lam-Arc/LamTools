"""user:“接口完善”+(只接受能实际验证的工具参数子集，复杂 Schema 明确留给后续移植)。"""

import json
import math

PRIMITIVES = {"string", "integer", "number", "boolean", "null"}


def check_schema(schema: dict) -> None:
    if not isinstance(schema, dict):
        raise ValueError("tool schema must be an object")
    json.dumps(schema, allow_nan=False)
    if schema.get("type", "object") != "object" or set(schema) - {"type", "properties", "required", "additionalProperties", "description", "title"}:
        raise ValueError("tool schema supports object/properties/required/additionalProperties only")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list) or any(not isinstance(k, str) or k not in properties for k in required):
        raise ValueError("tool schema properties and required must name declared fields")
    if type(schema.get("additionalProperties", True)) is not bool:
        raise ValueError("tool schema additionalProperties must be a boolean")
    for key, prop in properties.items():
        if not isinstance(key, str) or not isinstance(prop, dict) or prop.get("type") not in PRIMITIVES:
            raise ValueError("tool schema fields require a primitive type")
        if set(prop) - {"type", "enum", "description", "title", "default"}:
            raise ValueError("unsupported tool schema field keyword")
        if "enum" in prop and (not isinstance(prop["enum"], list) or not prop["enum"]):
            raise ValueError("tool schema enum must be a non-empty list")
        if "enum" in prop and any(not _matches(prop["type"], item) for item in prop["enum"]):
            raise ValueError("tool schema enum values must match the primitive type")


def _matches(kind, value):
    return {"string": isinstance(value, str), "integer": type(value) is int,
            "number": type(value) is int or type(value) is float and math.isfinite(value),
            "boolean": type(value) is bool, "null": value is None}[kind]


def check_arguments(schema: dict, arguments: dict) -> None:
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    if any(not isinstance(key, str) for key in arguments):
        raise ValueError("argument keys must be strings")
    json.dumps(arguments, allow_nan=False)
    # user:“接口完善”+(额外参数也必须是实际 JSON，不能让嵌套的数字键被编码器静默改写)。
    def check_json(value):
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError("argument keys must be strings")
            for child in value.values():
                check_json(child)
        elif isinstance(value, list):
            for child in value:
                check_json(child)
        elif value is not None and type(value) not in {str, int, float, bool}:
            raise ValueError("arguments must contain JSON values only")
    check_json(arguments)
    for name in schema.get("required", []):
        if name not in arguments:
            raise ValueError(f"missing required argument '{name}'")
    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False and set(arguments) - properties.keys():
        raise ValueError("unexpected arguments: " + ", ".join(sorted(set(arguments) - properties.keys())))
    for key, value in arguments.items():
        if key not in properties:
            continue
        prop = properties[key]
        kind = prop["type"]
        valid = _matches(kind, value)
        if not valid:
            raise ValueError(f"argument '{key}' must be {kind}")
        if "enum" in prop and not any(value == item for item in prop["enum"]):
            raise ValueError(f"argument '{key}' is outside enum")
