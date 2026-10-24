"""收尾方案步骤 4 验收：更新回滚 / 残留目录 / boot 单一来源。

user:“更新失败后 data 在原位；残留点目录不再被当插件；boot 与运行时
读同一份根列表和账本。”
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from lamtools_core.plugin_system.host import PluginHost


def _make_plugin(root: Path, name: str, version: str) -> Path:
    plugin = root / name
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / "plugin.json").write_text(
        json.dumps({"name": name, "version": version}), encoding="utf-8"
    )
    (plugin / "code.txt").write_text(version, encoding="utf-8")
    return plugin


def test_update_failure_restores_data_and_original(tmp_path, monkeypatch):
    roots = tmp_path / "roots"
    roots.mkdir()
    plugin = _make_plugin(roots, "keeper", "1.0.0")
    data = plugin / "data"
    data.mkdir()
    (data / "state.json").write_text('{"saved": true}', encoding="utf-8")
    host = PluginHost(roots=[roots], state_path=tmp_path / "s.jsonc")
    upgrade = _make_plugin(tmp_path / "src", "keeper", "2.0.0")

    real_replace = os.replace
    calls: list[str] = []

    def flaky_replace(src, dst, *args, **kwargs):
        calls.append(f"{src}->{dst}")
        # 第二次替换（staging → target）失败：模拟 Windows 上目录被占用。
        if len(calls) == 2:
            raise OSError("directory is locked")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", flaky_replace)

    with pytest.raises(OSError):
        host.update_from_directory(upgrade)

    # 回滚：本体恢复 1.0.0，data 回到原位，内容原样。
    manifest = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "1.0.0"
    assert (plugin / "data" / "state.json").read_text(encoding="utf-8") == '{"saved": true}'
    # 插件根里不留任何残留目录（staging 在系统临时目录里）。
    assert [item.name for item in roots.iterdir()] == ["keeper"]


def test_discover_ignores_and_sweeps_stale_dot_directories(tmp_path):
    roots = tmp_path / "roots"
    roots.mkdir()
    _make_plugin(roots, "real", "1.0.0")
    stale_update = roots / ".update-real-4242"
    stale_backup = roots / ".backup-real-4242"
    for stale in (stale_update, stale_backup):
        stale.mkdir()
        (stale / "plugin.json").write_text(
            json.dumps({"name": "real", "version": "9.9.9"}), encoding="utf-8"
        )

    host = PluginHost(roots=[roots], state_path=tmp_path / "s.jsonc")

    discovered = host.discover()
    # 点目录不算插件：没有 duplicate 报错，real 只有本尊。
    assert [item.name for item in discovered] == ["real"]
    assert host.errors == []
    # 残留目录被清扫掉。
    assert not stale_update.exists()
    assert not stale_backup.exists()


def test_boot_overrides_use_explicit_roots_and_ledger(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from lamtools_boot.overrides import load_boot_overrides

    plugin = _make_plugin(tmp_path / "plugins", "overrider", "1.0.0")
    (plugin / "overrides").mkdir()
    (plugin / "overrides" / "mod.py").write_text("value = 'plugin'\n", encoding="utf-8")
    (plugin / "plugin.json").write_text(
        json.dumps(
            {
                "name": "overrider",
                "version": "1.0.0",
                "overrides": {"lamtools_core.demo_module": "./overrides/mod.py"},
            }
        ),
        encoding="utf-8",
    )
    state = tmp_path / "data" / "plugin-system.jsonc"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({"plugins": {"overrider": {"enabled": True}}}), encoding="utf-8"
    )

    # user:“boot 与运行时同一份根与账本”+显式传参，不做第二套默认推导。
    mapping, errors = load_boot_overrides(
        environ={},
        roots=[tmp_path / "plugins"],
        state_path=state,
    )

    assert errors == []
    assert mapping["lamtools_core.demo_module"].name == "mod.py"


def test_boot_overrides_ledger_disables_a_plugin(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from lamtools_boot.overrides import load_boot_overrides

    plugin = _make_plugin(tmp_path / "plugins", "off", "1.0.0")
    (plugin / "overrides").mkdir()
    (plugin / "overrides" / "mod.py").write_text("value = 'off'\n", encoding="utf-8")
    (plugin / "plugin.json").write_text(
        json.dumps(
            {
                "name": "off",
                "version": "1.0.0",
                "overrides": {"lamtools_core.demo_module": "./overrides/mod.py"},
            }
        ),
        encoding="utf-8",
    )
    state = tmp_path / "data" / "plugin-system.jsonc"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({"plugins": {"off": {"enabled": False}}}), encoding="utf-8"
    )

    mapping, _ = load_boot_overrides(environ={}, roots=[tmp_path / "plugins"], state_path=state)

    # 账本说停用：启动覆盖不装。
    assert mapping == {}


def test_boot_override_file_with_bom_loads(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from lamtools_boot.import_hook import OverrideLoader

    source = tmp_path / "mod.py"
    # UTF-8 BOM：Windows 记事本写出来的形态，读文件必须容忍。
    source.write_bytes("﻿value = 'bom'\n".encode("utf-8"))

    import types

    module = types.ModuleType("_bom_test")
    OverrideLoader(source).exec_module(module)
    assert module.value == "bom"


def test_boot_default_state_path_covers_linux(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from lamtools_boot import overrides as boot_overrides

    # Linux 无 APPDATA：账本落 XDG 数据目录，读得到已停用的插件。
    environ = {
        "XDG_DATA_HOME": str(tmp_path / "share"),
    }
    state = tmp_path / "share" / "LamTools" / "plugin-system.jsonc"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({"plugins": {"off": {"enabled": False}}}), encoding="utf-8"
    )
    assert boot_overrides._default_state_path(environ) == state
    assert not boot_overrides._is_enabled(
        {"plugins": {"off": {"enabled": False}}}, "off"
    )


def test_boot_roots_mirror_matches_the_runtime_roots(monkeypatch, tmp_path):
    """boot 的 stdlib 根清单必须与 plugin_system.paths 的默认根逐项相等。"""
    import lamtools_boot.overrides as boot
    from lamtools_core.plugin_system import paths as runtime

    for env in (
        {"LAMTOOLS_HOME": str(tmp_path / "lam")},
        {"APPDATA": str(tmp_path / "appdata")},
        {"LAMTOOLS_HOME": str(tmp_path / "lam"), "LAMTOOLS_CORE_WORK_ROOT": str(tmp_path / "proj")},
    ):
        for key in ("LAMTOOLS_HOME", "APPDATA", "LAMTOOLS_CORE_WORK_ROOT", "LAMTOOLS_CORE_CONFIG_ROOT"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        work_root = env.get("LAMTOOLS_CORE_WORK_ROOT", str(tmp_path / "w"))
        boot_roots = [Path(item) for item in boot.default_plugin_roots(dict(env), work_root)]
        runtime_roots = runtime.default_plugin_roots(work_root)
        assert boot_roots == runtime_roots, (env, boot_roots, runtime_roots)
