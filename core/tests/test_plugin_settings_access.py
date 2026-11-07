"""user:“继续，无人值守模式，不要停下来”+(设置使用成熟JSON Schema校验、原CAS存储和保守secret投影，不另建配置权威)。"""
import json

import pytest

from lamtools_core.plugin_system import PluginContext
from lamtools_core.plugin_system.manifest import PluginManifest
from lamtools_core.plugin_system.config_access import ConfigError


@pytest.mark.asyncio
@pytest.mark.parametrize("keyword",["patternProperties","dependentSchemas"])
@pytest.mark.parametrize("annotation",[{"writeOnly":True},{"x-secret":True},{"format":"password"}])
async def test_public_projection_honors_secret_annotations_from_applicable_object_schemas(ctx,keyword,annotation):
    # user:“真实近似差异和剩余移植工作必须准确记录”+(已支持的JSON Schema对象规则中的secret声明也必须用于公开投影，不能仅校验时识别)。
    schema = {"type":"object","properties":{"token":{"type":"string"},"label":{"type":"string"},"switch":{"type":"boolean"}}}
    if keyword == "patternProperties":
        schema[keyword] = {"^token$":annotation}
    else:
        schema[keyword] = {"switch":{"properties":{"token":annotation,"label":{}}}}
    (ctx.work_root / "schema.json").write_text(json.dumps(schema),encoding="utf8")
    values = {"token":"private-from-object-schema","label":"visible","switch":True}
    try:
        api = ctx.settings
        api.replace(values,expected_revision=api.read().revision)
        public = api.public()
        assert public["values"]["token"] == "<redacted>"
        assert public["values"]["label"] == "visible"
        assert "private-from-object-schema" not in str(public)
        assert ctx.config.read().values == values
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_public_projection_only_applies_triggered_dependent_schema(ctx):
    # user:“宿主能力补齐和接口完善与文档更新”+(条件保密按原JSON Schema属性存在语义生效，不以真值判断，也不污染未触发分支)。
    schema = {"type":"object","properties":{"token":{"type":"string"},"switch":{"type":"boolean"}},
        "dependentSchemas":{"switch":{"properties":{"token":{"writeOnly":True}}}}}
    (ctx.work_root / "schema.json").write_text(json.dumps(schema),encoding="utf8")
    try:
        api = ctx.settings
        api.replace({"token":"visible-without-trigger"},expected_revision=api.read().revision)
        assert api.public()["values"]["token"] == "visible-without-trigger"
        api.replace({"token":"hidden-with-false-trigger","switch":False},expected_revision=api.read().revision)
        assert api.public()["values"]["token"] == "<redacted>"
        assert ctx.config.read().values["token"] == "hidden-with-false-trigger"
    finally:
        await ctx._registration_scope.dispose()


@pytest.fixture
def ctx(tmp_path):
    schema = {"type": "object", "additionalProperties": False, "properties": {
        "count": {"type": "integer", "minimum": 1, "maximum": 5, "default": 2},
        "account": {"$ref": "#/$defs/account"}},
        "$defs": {"account": {"type": "object", "properties": {
            "label": {"type": "string"}, "token": {"type": "string", "writeOnly": True}},
            "required": ["label", "token"]}}}
    (tmp_path / "schema.json").write_text(json.dumps(schema), encoding="utf8")
    context = PluginContext(tmp_path, data_dir=tmp_path / "data")
    manifest = PluginManifest("settings", "1", root=tmp_path, raw={"config": {"schema": "./schema.json"}})
    context._begin_registration_scope("settings", 1, manifest=manifest)
    return context


@pytest.mark.asyncio
async def test_full_nested_validation_refusal_preserves_original_config_and_revision(ctx):
    api = ctx.settings
    original = api.read()
    invalid = api.validate({"count": 9, "account": {"label": "Name"}})
    assert not invalid.valid and invalid.level == "json-schema-2020-12"
    with pytest.raises(ConfigError):
        api.replace({"count": 9}, expected_revision=original.revision)
    assert ctx.config.read().revision == original.revision
    saved = api.replace({"count": 3, "account": {"label": "Name", "token": "private-token"}}, expected_revision=original.revision)
    assert saved.saved and not saved.applied and saved.requires_reload
    with pytest.raises(ConfigError) as error:
        api.replace({"count": 4}, expected_revision=original.revision)
    assert error.value.code == "config/conflict"
    await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_public_projection_follows_local_refs_and_reset_uses_declared_defaults(ctx):
    api = ctx.settings
    before = api.read()
    api.replace({"count": 3, "account": {"label": "Public", "token": "private-token"}}, expected_revision=before.revision)
    public = api.public()
    assert public["values"]["account"]["label"] == "Public"
    assert public["values"]["account"]["token"] == "<redacted>"
    assert "private-token" not in str(public)
    api.reset(expected_revision=api.read().revision)
    assert ctx.config.read().values == {"count": 2}
    await ctx._registration_scope.dispose()
    with pytest.raises(Exception):
        api.public()


@pytest.mark.asyncio
async def test_remote_schema_reference_is_rejected_without_fetching(ctx):
    path = ctx.work_root / "schema.json"
    path.write_text(json.dumps({"$ref": "https://example.invalid/remote-schema"}), encoding="utf8")
    with pytest.raises(ConfigError) as error:
        ctx.settings.validate({})
    assert error.value.code == "settings/remote-reference"
    await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_ref_shaped_default_is_data_and_never_treated_as_a_schema_fetch(ctx):
    value = {"$ref": "https://example.invalid/plain-data"}
    schema = {"type": "object", "properties": {"reference": {"type": "object", "default": value}}}
    (ctx.work_root / "schema.json").write_text(json.dumps(schema), encoding="utf8")
    ctx.settings.reset(expected_revision=ctx.config.read().revision)
    assert ctx.config.read().values == {"reference": value}
    await ctx._registration_scope.dispose()
