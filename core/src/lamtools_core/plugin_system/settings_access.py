"""user:“继续，无人值守模式，不要停下来”+(设置校验使用成熟JSON Schema实现；保存/修订仍由原配置存储拥有)。"""
import copy
import re
from dataclasses import replace
from urllib.parse import unquote

from jsonschema import Draft202012Validator
from referencing import Registry

from .config_access import ConfigError, ConfigValidation
from .storage_access import _encode


def _schema_guard(node, depth=0):
    if depth > 64:
        raise ConfigError("settings/schema-limit", "Schema nesting exceeds 64 levels")
    if isinstance(node, dict):
        for keyword in ("$ref", "$dynamicRef"):
            if keyword in node and (type(node[keyword]) is not str or not node[keyword].startswith("#")):
                raise ConfigError("settings/remote-reference", "Only schema-local references are supported; no documents are fetched")
        # Defaults/examples/enums are instance data, even when a value has a literal "$ref" key.
        for keyword in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas", "dependencies"):
            children = node.get(keyword)
            if isinstance(children, dict):
                for child in children.values():
                    if isinstance(child, dict):
                        _schema_guard(child, depth + 1)
        for keyword in ("items", "additionalItems", "additionalProperties", "unevaluatedProperties", "unevaluatedItems",
                        "contains", "not", "if", "then", "else", "propertyNames", "contentSchema"):
            child = node.get(keyword)
            if isinstance(child, dict):
                _schema_guard(child, depth + 1)
        for keyword in ("allOf", "anyOf", "oneOf", "prefixItems"):
            children = node.get(keyword)
            if isinstance(children, list):
                for child in children:
                    _schema_guard(child, depth + 1)


def _validate(schema, values):
    _encode(values)
    _schema_guard(schema)
    try:
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, registry=Registry())
        problems = []
        for error in validator.iter_errors(values):
            # Validator messages can contain actual secret values. Expose location and rule, never the value.
            location = "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in error.absolute_path)
            problems.append(f"{location[:256]}: rule {error.validator}")
            if len(problems) == 100:
                break
        return ConfigValidation(not problems, tuple(problems), level="json-schema-2020-12")
    except ConfigError:
        raise
    except Exception:
        raise ConfigError("settings/invalid-schema", "Schema or local reference cannot be evaluated") from None


def _local_ref(root, ref):
    if ref == "#":
        return root
    if not ref.startswith("#/"):
        return None
    node = root
    try:
        for part in unquote(ref[2:]).split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            node = node[int(key)] if isinstance(node, list) else node[key]
        return node
    except (KeyError, TypeError, IndexError, ValueError):
        return None


def _redact(value, schema, root, depth=0):
    if depth > 64 or not isinstance(schema, dict):
        return "<redacted>"
    if schema.get("writeOnly") is True or schema.get("x-secret") is True or schema.get("format") == "password" or "$dynamicRef" in schema:
        return "<redacted>"
    if "$ref" in schema:
        target = _local_ref(root, schema["$ref"])
        if not isinstance(target, dict):
            return "<redacted>"
        return _redact(_redact(value, target, root, depth + 1), {key: child for key, child in schema.items() if key != "$ref"}, root, depth + 1) if len(schema) > 1 else _redact(value, target, root, depth + 1)
    result = copy.deepcopy(value)
    if isinstance(result, dict):
        properties = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        if not isinstance(properties, dict) or not isinstance(patterns, dict):
            return "<redacted>"
        result = {key: _redact(child, properties[key], root, depth + 1) if key in properties else "<redacted>"
                  for key, child in result.items()}
        # user:“宿主能力补齐和接口完善与文档更新”+(公开投影也遵守模式属性和已触发依赖中的保密标记，不能只在校验时识别这些规则)。
        for key in result:
            for pattern, branch in patterns.items():
                if re.search(pattern, key):
                    result[key] = _redact(result[key], branch, root, depth + 1)
        for trigger, branch in schema.get("dependentSchemas", {}).items():
            if trigger in value:
                result = _redact(result, branch, root, depth + 1)
    elif isinstance(result, list):
        prefix = schema.get("prefixItems", [])
        result = [_redact(child, prefix[index] if isinstance(prefix, list) and index < len(prefix) else schema.get("items", {}), root, depth + 1)
                  for index, child in enumerate(result)]
    # Conservatively apply all branches: a non-selected branch must never reveal a possible secret.
    for keyword in ("allOf", "anyOf", "oneOf"):
        for branch in schema.get(keyword, []) if isinstance(schema.get(keyword), list) else []:
            result = _redact(result, branch, root, depth + 1)
    for keyword in ("then", "else"):
        if keyword in schema:
            result = _redact(result, schema[keyword], root, depth + 1)
    return result


def _defaults(schema):
    if not isinstance(schema, dict):
        return None
    if "default" in schema:
        return copy.deepcopy(schema["default"])
    result = {}
    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        for key, child in properties.items():
            if isinstance(child, dict) and "default" in child:
                result[key] = copy.deepcopy(child["default"])
    return result


class PluginSettingsAPI:
    def __init__(self, config, scope):
        self._config, self._scope = config, scope

    def read(self):
        self._scope.check_open()
        snapshot = self._config.read()
        return replace(snapshot, validation=_validate(snapshot.schema, snapshot.values))

    def validate(self, values):
        self._scope.check_open()
        if type(values) is not dict:
            return ConfigValidation(False, ("config must be an object",), level="json-schema-2020-12")
        return _validate(self._config.read().schema, values)

    def replace(self, values, *, expected_revision):
        validation = self.validate(values)
        if not validation.valid:
            raise ConfigError("settings/invalid-values", "; ".join(validation.problems))
        return self._config.replace(values, expected_revision=expected_revision)

    def reset(self, *, expected_revision):
        snapshot = self._config.read()
        return self.replace(_defaults(snapshot.schema), expected_revision=expected_revision)

    def public(self):
        snapshot = self.read()
        return {"values": _redact(snapshot.values, snapshot.schema, snapshot.schema), "revision": snapshot.revision,
                "valid": snapshot.validation.valid, "problems": list(snapshot.validation.problems)}
