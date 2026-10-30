"""user:“写好清单，逐项打勾完成，不要出错”+(进程基础先验收环境过滤、确定查找与代际撤回，不以解析成功冒充进程已执行)。"""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from lamtools_core.plugin_system.context import PluginContext


def access(root):
    ctx = PluginContext(root)
    ctx._begin_registration_scope("example", 1)
    return ctx, ctx.processes


def test_absolute_executable_and_explicit_path_lookup(tmp_path):
    _, api = access(tmp_path)
    executable = Path(sys.executable).resolve()
    assert api.resolve_executable(str(executable)) == executable
    assert api.resolve_executable(executable.name, env={"PATH": str(executable.parent)}) == executable


def test_environment_filters_case_insensitively_and_allows_explicit_overrides(tmp_path, monkeypatch):
    _, api = access(tmp_path)
    for key in ("PRIVATE_API_KEY", "password_var", "aSecret", "auth_token", "dsh_identity", "SUNDAY_INTERNAL", "LAMTOOLS_INTERNAL"):
        monkeypatch.setenv(key, "private")
    monkeypatch.setenv("VISIBLE_VAR", "original")
    monkeypatch.delenv("NEW_VAR", raising=False)
    env = api.environment({"PRIVATE_API_KEY": "explicit", "VISIBLE_VAR": None, "NEW_VAR": "x"})
    assert env["PRIVATE_API_KEY"] == "explicit" and env["NEW_VAR"] == "x"
    assert "VISIBLE_VAR" not in env
    assert all(key.upper() not in {"PASSWORD_VAR", "ASECRET", "AUTH_TOKEN", "DSH_IDENTITY", "SUNDAY_INTERNAL", "LAMTOOLS_INTERNAL"} for key in env)
    with pytest.raises(TypeError):
        env["NEW_VAR"] = "mutate"
    assert api.environment().get("VISIBLE_VAR") == "original"
    assert "NEW_VAR" not in api.environment()


@pytest.mark.parametrize("command", ["", " ", " python", "./program", "folder/program", "folder\\program", "bad\x00name", None])
def test_relative_or_invalid_commands_are_not_guessed(tmp_path, command):
    from lamtools_core.plugin_system import ProcessAccessError
    _, api = access(tmp_path)
    with pytest.raises(ProcessAccessError) as error:
        api.resolve_executable(command)
    assert error.value.code == "process/invalid-command"


def test_missing_and_directory_are_not_executables(tmp_path):
    from lamtools_core.plugin_system import ProcessAccessError
    _, api = access(tmp_path)
    for command in (str(tmp_path), str(tmp_path / "missing.exe"), "absent_program_778899"):
        with pytest.raises(ProcessAccessError) as error:
            api.resolve_executable(command, env={"PATH": str(tmp_path)})
        assert error.value.code == "process/not-found"


def test_lookup_ignores_empty_and_relative_path_entries(tmp_path, monkeypatch):
    from lamtools_core.plugin_system import ProcessAccessError
    _, api = access(tmp_path)
    name = "only_here.exe" if os.name == "nt" else "only_here"
    program = tmp_path / name
    program.write_bytes(b"fixture, never executed")
    program.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ProcessAccessError) as error:
        api.resolve_executable(name, env={"PATH": os.pathsep.join(["", ".", "relative"])})
    assert error.value.code == "process/not-found"
    assert api.resolve_executable(name, env={"PATH": str(tmp_path)}) == program.resolve()


@pytest.mark.parametrize("overrides", [{"BAD=NAME": "x"}, {"BAD\x00NAME": "x"}, {"X": "bad\x00value"}, {1: "x"}, {"X": 1}, {"DSH_SUBPROCESS_CONTROL": "pipe"}, {"X": "x" * 1048577}])
def test_invalid_environment_never_leaks_payload(tmp_path, overrides):
    from lamtools_core.plugin_system import ProcessAccessError
    _, api = access(tmp_path)
    with pytest.raises(ProcessAccessError) as error:
        api.environment(overrides)
    assert error.value.code == "process/invalid-environment"
    assert "bad\x00value" not in str(error.value)


@pytest.mark.skipif(os.name != "nt", reason="Windows environment and PATHEXT semantics")
def test_windows_case_merging_and_pathext_order(tmp_path, monkeypatch):
    _, api = access(tmp_path)
    monkeypatch.setenv("Visible_Var", "original")
    env = api.environment({"visible_VAR": "changed"})
    assert env["VISIBLE_VAR"] == "changed"
    assert sum(k.upper() == "VISIBLE_VAR" for k in env) == 1
    for ext in (".cmd", ".exe"):
        (tmp_path / ("fixture" + ext)).write_bytes(b"never executed")
    assert api.resolve_executable("fixture", env={"path": str(tmp_path), "pathext": ".CMD;.EXE"}).suffix == ".cmd"
    assert api.resolve_executable("fixture", env={"PATH": str(tmp_path), "PATHEXT": ".EXE;.CMD"}).suffix == ".exe"


@pytest.mark.asyncio
async def test_scope_revocation_invalidates_both_operations(tmp_path):
    from lamtools_core.plugin_system.services import ServiceError
    ctx, api = access(tmp_path)
    await ctx._registration_scope.dispose()
    with pytest.raises(ServiceError):
        api.environment()
    with pytest.raises(ServiceError):
        api.resolve_executable(sys.executable)


def test_unmanaged_context_cannot_get_process_api(tmp_path):
    from lamtools_core.plugin_system.services import ServiceError
    with pytest.raises(ServiceError):
        _ = PluginContext(tmp_path).processes


def test_removed_path_does_not_fall_back_to_host_lookup(tmp_path, monkeypatch):
    from lamtools_core.plugin_system import ProcessAccessError
    _, api = access(tmp_path)
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent))
    with pytest.raises(ProcessAccessError) as error:
        api.resolve_executable(Path(sys.executable).name, env={"PATH": None})
    assert error.value.code == "process/not-found"


def test_path_entry_count_is_bounded_before_filesystem_scan(tmp_path):
    from lamtools_core.plugin_system import ProcessAccessError
    _, api = access(tmp_path)
    with pytest.raises(ProcessAccessError) as error:
        api.resolve_executable("missing_name", env={"PATH": os.pathsep.join([str(tmp_path)] * 257)})
    assert error.value.code == "process/invalid-environment"
