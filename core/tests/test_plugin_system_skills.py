"""Author-facing skills must ship with the rules they promise.

user:“这个后面在完整设计之后，我们再重新设计 create plugin 这个 skill 的
提示词”+作者工具是插件系统的一部分，内容退化要能被测试挡住。
"""

from __future__ import annotations

from lamtools_core.skill_runtime import builtin_core_skill_roots
from lamtools_core.skills import SkillRegistry


def load_skill(name: str):
    roots = builtin_core_skill_roots()
    assert roots, "built-in skill roots are missing"
    registry = SkillRegistry(explicit_roots=roots)
    skill = registry.get(None, name)
    assert skill is not None, f"skill '{name}' is not discoverable"
    return skill


def test_create_plugin_documents_the_v2_contract() -> None:
    skill = load_skill("create-plugin")
    content = skill.content

    # user:“单一系统不再需要 assembly 标记”+覆盖双键族与后果自负必须写清。
    assert "assembly" not in content
    assert "overrides" in content
    assert "@/" in content
    assert "config.schema" in content or "config/schema.jsonc" in content
    assert "run_command" in content
    assert "LamToolsPluginPanels" in content


def test_create_plugin_teaches_mcp_reuse_and_host_loading() -> None:
    content = load_skill("create-plugin").content

    # user:“像 Billy scroll 这种，我就极推荐它做成 MCP，尤其是因为它本身就是 MCP”
    # + “它本身就是 MCP，最大化利用本身的资源，不要重复造轮子”。
    assert "already exists as an MCP server" in content
    # user:“原版是 MCP 就照搬”+MCP 工具通过 mcp 查询、mcp action=run 执行。
    assert "mcp action=run" in content
    assert "approvedTools" in content
    # user:“同目录的 Python 文件在宿主里互相引用不到”+一行 sys.path 的绕法。
    assert "sys.path.insert" in content
    # user:“工具与操作要重启后才注册”+插件页不显示运行期加载失败。
    assert "visibility" in content and "on_load" in content
    assert "profiles" in content
    assert "run_profile" in content
    assert "restart the app" in content
    assert "load failed" in content


def test_port_plugin_starts_with_the_licence_check() -> None:
    skill = load_skill("port-plugin")
    content = skill.content.lower()

    assert "licence" in content or "license" in content
    assert "difference report" in content
    assert "run_command" in content


def test_port_plugin_teaches_mcp_first_and_real_host_verification() -> None:
    content = load_skill("port-plugin").content

    # user:“它本身就是 MCP……不要重复造轮子”+原版是 MCP 就照搬配置。
    assert "Port the MCP config as-is" in content
    assert "mcp action=run" in content
    assert "approvedTools" in content
    # user:“插件同目录模块导入”+装完必须重启并从宿主真实调用一次。
    assert "sys.path.insert" in content
    assert "through the host" in content
    assert "restart" in content.lower()
