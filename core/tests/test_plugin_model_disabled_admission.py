"""user:“继续，只在交互轮停下”+(禁用记录可供只读发现，但不能被SDK显式选择并实际发送请求)。"""
from dataclasses import replace

import pytest

from .test_plugin_model_access import store
from .test_plugin_llm_access import env as llm_env
from lamtools_core.llm import LLMRequest


@pytest.mark.asyncio
async def test_disabled_model_stays_discoverable_but_explicit_selection_rejects(llm_env):
    from lamtools_core.plugin_system.model_access import ModelAccessError
    ctx, _, state = llm_env
    state["records"][0] = replace(state["records"][0], enabled=False)
    assert ctx.models.resolve("route-one").id == "route-one"
    with pytest.raises(ModelAccessError) as error:
        ctx.models.select("background", ref="route-one")
    assert error.value.code == "model/unavailable"


@pytest.mark.asyncio
async def test_disabled_model_never_reaches_sdk_provider(llm_env):
    from lamtools_core.plugin_system.llm_access import LLMAccessError
    ctx, client, state = llm_env
    state["records"][0] = replace(state["records"][0], enabled=False)
    with pytest.raises(LLMAccessError) as error:
        await ctx.llm.complete(LLMRequest(), ref="route-one")
    assert error.value.code == "llm/model-unavailable" and not client.calls
