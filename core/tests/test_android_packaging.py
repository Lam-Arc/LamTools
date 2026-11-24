from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


@pytest.mark.parametrize("arguments", ['"tauri"', '"run", "--", "tauri"'])
def test_generated_android_build_runs_cli_js_directly(tmp_path, monkeypatch, arguments):
    source = Path(__file__).resolve().parents[1] / "android-host/scripts/android_project.py"
    spec = spec_from_file_location("android_project", source)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    project = tmp_path / "generated"
    task = project / "buildSrc/src/main/java/com/lamtools/sunday/core/kotlin/BuildTask.kt"
    task.parent.mkdir(parents=True)
    task.write_text(
        'val executable = """npm"""\n'
        f'val args = listOf({arguments}, "android", "android-studio-script");\n',
        encoding="utf-8",
    )
    cli = tmp_path / "tauri.js"
    monkeypatch.setattr(module, "PROJECT", project)
    monkeypatch.setattr(module.shutil, "which", lambda name: str(tmp_path / "node.exe"))
    monkeypatch.setattr(module, "tauri_cli_js", lambda: cli)
    module.fix_generated_node_path()
    result = task.read_text(encoding="utf-8")
    assert f'val executable = """{(tmp_path / "node.exe").as_posix()}"""' in result
    assert f'val args = listOf("{cli.as_posix()}", "android", "android-studio-script")' in result
