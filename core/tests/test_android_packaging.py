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


def _android_project():
    source = Path(__file__).resolve().parents[1] / "android-host/scripts/android_project.py"
    spec = spec_from_file_location("android_project", source)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_android_build_passes_the_validated_runtime_to_gradle(tmp_path, monkeypatch):
    module = _android_project()
    output = tmp_path / "out"
    assets = output / "aarch64/assets"
    manifest = assets / "runtime/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"coreVersion": "0.3.51"}', encoding="utf-8")
    apk = tmp_path / "app.apk"
    apk.touch()
    monkeypatch.setattr(module, "RUNTIME_OUT", output)
    monkeypatch.setattr(module, "checkout_core_version", lambda: "0.3.51")
    monkeypatch.setattr(module, "fix_generated_node_path", lambda: None)
    monkeypatch.setattr(module, "tauri_cli", lambda: ["tauri"])
    monkeypatch.setattr(module, "apk_path", lambda debug: apk)

    def run(command, cwd, env, timeout):
        assert env["SUNDAY_RT_ABI"] == "aarch64"
        assert env["SUNDAY_RT_ASSETS"] == str(assets.resolve())
        return 0

    monkeypatch.setattr(module, "run", run)
    assert module.build({}, debug=True, target="aarch64", timeout=60) == 0


@pytest.mark.parametrize("with_runtime", [False, True])
def test_android_apk_verification_requires_the_embedded_runtime(tmp_path, with_runtime):
    import zipfile

    module = _android_project()
    apk = tmp_path / "app.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("lib/arm64-v8a/libsunday_android_host_lib.so", b"")
        archive.writestr("classes.dex", b"LifecycleBridge MainActivity SundayOverlayService")
        if with_runtime:
            archive.writestr("lib/arm64-v8a/libproot.so", b"")
            archive.writestr("assets/runtime/manifest.json", "{}")
            archive.writestr("assets/runtime/rootfs-aarch64.targz", b"")
    expected = module.EXIT_OK if with_runtime else module.EXIT_BUILD
    assert module.verify(apk) == expected
