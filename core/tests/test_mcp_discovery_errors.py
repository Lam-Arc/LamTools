"""user:“MCP 列表空”+(启动失败必须显示原因，不能伪装成没有配置)。"""
import pytest

from lamtools_core.mcp.command_service import MCPCommandService
from lamtools_core.mcp.registry import MCPToolRegistry
from lamtools_core.mcp.schemas import MCPServerConfig


@pytest.mark.asyncio
async def test_failed_server_is_reported_to_model_and_tool_call(tmp_path):
    registry = MCPToolRegistry(tmp_path, config_loader=lambda _: [
        MCPServerConfig(name='bilibili', command=str(tmp_path / 'missing-python.exe')),
    ])
    service = MCPCommandService(registry)
    try:
        result = await service.inspect('servers')
        assert result['servers'] == []
        assert result['errors']['bilibili']
        assert 'missing-python.exe' in result['errors']['bilibili']
        with pytest.raises(ValueError, match='bilibili.*missing-python'):
            await service.execute_tool('mcp__bilibili__bili_search', {})
        await service.close()
        assert registry.load_errors == {}
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_unconfigured_registry_has_no_false_failure(tmp_path):
    service = MCPCommandService(MCPToolRegistry(tmp_path, config_loader=lambda _: []))
    try:
        assert await service.inspect('servers') == {'servers': []}
    finally:
        await service.close()
