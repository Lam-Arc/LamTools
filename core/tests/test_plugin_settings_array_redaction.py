"""user:“宿主能力补齐和接口完善与文档更新”+(数组约束中的保密声明也须覆盖公开设置投影)。"""
import json
import pytest
from .test_plugin_settings_controller_write import settings_env

@pytest.mark.asyncio
@pytest.mark.parametrize('keyword', ['contains', 'unevaluatedItems'])
async def test_array_schema_secret_is_not_returned_by_controller(settings_env, keyword):
    schema = {'type':'object', 'properties': {'entries': {'type':'array', keyword: {'type':'string','writeOnly':True}}}}
    (settings_env.work_root / 'schema.json').write_text(json.dumps(schema), encoding='utf8')
    api = settings_env.settings_controller
    value = {'entries':['temporary-array-secret']}
    saved = api.replace(value, expected_revision=api.describe()['revision'])
    assert 'temporary-array-secret' not in repr(saved)
    assert 'temporary-array-secret' not in repr(api.describe())
    assert settings_env.config.read().values == value
