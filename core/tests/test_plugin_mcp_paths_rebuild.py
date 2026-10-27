"""user:“该调的模块就是该写的东西”+(插件解释器与路径展开是通用能力，不把 B站目录写进宿主)。"""
import json
from lamtools_core.mcp.config import load_mcp_server_configs


def test_plugin_interpreter_template_and_custom_python_are_expanded_after_json(tmp_path):
    root = tmp_path / "plugin"
    (root / "data").mkdir(parents=True)
    (root / "plugin.json").write_text('{"name":"demo","version":"1"}')
    path = root / "server.json"
    path.write_text(json.dumps({"mcpServers": {"demo": {"command": "{{PLUGIN_PYTHON:./data/custom-env}}", "args": ["{{PLUGIN_DIR}}/server.py"]}}}))
    config = next(item for item in load_mcp_server_configs(tmp_path, config_files=[path], default_paths=[]) if item.name == "demo")
    assert str(root) in config.command and "custom-env" in config.command
    assert config.args[0] == str(root) + "/server.py"
    custom = tmp_path / "python.exe"
    custom.touch()
    (root / "data/config.jsonc").write_text(json.dumps({"pythonPath": str(custom)}))
    config = next(item for item in load_mcp_server_configs(tmp_path, config_files=[path], default_paths=[]) if item.name == "demo")
    assert config.command == str(custom)
