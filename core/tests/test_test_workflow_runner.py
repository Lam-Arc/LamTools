"""The faster test entry point must preserve tests and failure visibility."""

from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
import sys
from threading import Barrier, Lock

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[2] / "scripts" / "run-tests.py"
    spec = importlib.util.spec_from_file_location("lamtools_test_runner", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def test_complete_suite_commands(runner, tmp_path):
    backend, ui = runner.core_suites(tmp_path)
    assert backend.command == (sys.executable, "-m", "pytest", "tests", "--durations=10")
    assert backend.cwd == tmp_path / "core"
    assert ui.command == ("npm.cmd" if os.name == "nt" else "npm", "run", "test:contract")
    assert ui.cwd == tmp_path / "core" / "ui"


def test_independent_suites_overlap_and_finish_after_failure(runner, monkeypatch):
    barrier = Barrier(2, timeout=5)
    completed = []
    lock = Lock()

    def run(suite, env):
        barrier.wait()
        with lock:
            completed.append(suite.name)
        return 7 if suite.name == "core" else 0

    monkeypatch.setattr(runner, "run_suite", run)
    assert runner.run_suites(runner.core_suites()) == 1
    assert sorted(completed) == ["core", "core-ui"]


def test_serial_mode_preserves_order_and_environment(runner, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "existing-import-path")
    before = dict(os.environ)
    completed = []

    def run(suite, env):
        assert env["PYTHONPATH"] == f"{runner.ROOT / 'core' / 'src'}{os.pathsep}existing-import-path"
        assert env["PYTHONUNBUFFERED"] == "1"
        assert env["PYTHONIOENCODING"] == "utf-8"
        completed.append(suite.name)
        return 0

    monkeypatch.setattr(runner, "run_suite", run)
    assert runner.run_suites(runner.core_suites(), serial=True) == 0
    assert completed == ["core", "core-ui"]
    assert dict(os.environ) == before


def test_runner_exception_is_visible_and_other_suite_finishes(runner, monkeypatch, capsys):
    completed = []

    def run(suite, env):
        if suite.name == "core":
            raise RuntimeError("unexpected reporting failure")
        completed.append(suite.name)
        return 0

    monkeypatch.setattr(runner, "run_suite", run)
    assert runner.run_suites(runner.core_suites()) == 1
    assert completed == ["core-ui"]
    output = capsys.readouterr().out
    assert "[core] RUNNER FAILED" in output
    assert "RuntimeError: unexpected reporting failure" in output
    assert "TESTS FAILED" in output


@pytest.mark.parametrize("code", [0, 9])
def test_child_output_and_exit_code_are_preserved(runner, tmp_path, capsys, code):
    suite = runner.Suite(
        "sample",
        (sys.executable, "-c", f"import sys; print('输出'); print('failure detail', file=sys.stderr); sys.exit({code})"),
        tmp_path,
    )
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    assert runner.run_suite(suite, env) == code
    output = capsys.readouterr().out
    assert "[sample] 输出" in output
    assert "[sample] failure detail" in output
    assert ("PASSED" if code == 0 else "FAILED (exit 9)") in output


def test_missing_tool_is_a_failure(runner, tmp_path, capsys):
    suite = runner.Suite("missing", (str(tmp_path / "nonexistent-tool"),), tmp_path)
    assert runner.run_suite(suite, dict(os.environ)) == 1
    assert "Could not start" in capsys.readouterr().out


def test_entry_point_handles_unicode_with_legacy_console_encoding(runner, monkeypatch):
    data = io.BytesIO()
    console = io.TextIOWrapper(data, encoding="ascii")
    monkeypatch.setattr(sys, "stdout", console)
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="ascii"))
    monkeypatch.setattr(sys, "argv", ["run-tests.py", "all"])

    def run(suites, *, serial):
        runner.report("❯ ✓ 输出")
        return 1

    monkeypatch.setattr(runner, "run_suites", run)
    assert runner.main() == 1
    assert data.getvalue().decode("utf-8") == f"❯ ✓ 输出{os.linesep}"
