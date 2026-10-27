"""user:“安装的时候直接从 GitHub 上”+(市场插件在冻结宿主中不得误把应用当作独立 Python)。"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def service():
    from lamtools_core.plugin_system.loading import load_module
    return load_module(Path(__file__).resolve().parents[1], "service")


def test_missing_python_in_frozen_host_never_starts_another_backend(service, tmp_path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/bootstrap_env.py").write_text("# test bootstrap")
    (tmp_path / "logs").mkdir()
    monkeypatch.setattr(service, "ROOT", tmp_path)
    monkeypatch.setattr(service.common, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(service.common, "ensure_dirs", lambda: None)
    monkeypatch.setattr(service.common, "log", lambda *args: None)
    monkeypatch.setattr(service, "_base_python", lambda: [])
    monkeypatch.setattr(service.sys, "frozen", True, raising=False)
    spawn = Mock(return_value=Mock(pid=42))
    monkeypatch.setattr(service.subprocess, "Popen", spawn)
    monkeypatch.setattr(service, "PROCESSES", set())
    result = service._spawn_detached("bootstrap_env.py", [], "install.log")
    assert not result["ok"]
    assert "Python" in result["error"]
    spawn.assert_not_called()


@pytest.mark.parametrize("version", ["Python 2.7.18", "Python 3.9.13"])
def test_bootstrap_rejects_an_incompatible_system_python(service, monkeypatch, version):
    monkeypatch.setattr(service.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=version, stderr=""))
    assert service._base_python() == []


@pytest.mark.parametrize("stdout,stderr", [("Python 3.10.11", ""), ("", "Python 3.14.0")])
def test_bootstrap_accepts_supported_python_on_either_output(service, monkeypatch, stdout, stderr):
    monkeypatch.setattr(service.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr))
    assert service._base_python() == ["py", "-3"]
