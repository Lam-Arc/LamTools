"""A copied optional Workflow plugin must load with no bundled package present."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_optional_workflow_bootstrap_without_bundled_package(tmp_path):
    source = Path(__file__).resolve().parents[1] / "src/lamtools_core/plugins/bundled/workflow"
    target = tmp_path / "plugins/workflow"
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    script = '''
import importlib, importlib.util, sys
from pathlib import Path
from lamtools_core.plugin_system.context import PluginContext
import lamtools_core.plugins.bundled as bundled
# Reproduce the frozen runtime's exclusion of Workflow source/modules.
bundled.__path__ = []
for name in list(sys.modules):
    if name.startswith('lamtools_core.plugins.bundled.workflow'):
        del sys.modules[name]
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('external_workflow', root/'bootstrap.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
runtime = module.create_plugin(PluginContext(work_root=root, data_dir=root/'data'))
assert runtime is not None
operations = importlib.import_module('lamtools_core.plugins.bundled.workflow.backend.operations')
assert callable(operations.workflow_save)
assert callable(operations.workflow_get)
assert Path(sys.modules['lamtools_core.plugins.bundled.workflow'].__file__).parent == root
'''
    env = dict(os.environ, LAMTOOLS_CORE_CONFIG_ROOT=str(tmp_path / "config"))
    result = subprocess.run([sys.executable, "-c", script, str(target)], env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
