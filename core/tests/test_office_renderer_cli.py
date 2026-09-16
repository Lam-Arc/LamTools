from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lamtools_core import cli as core_cli
from lamtools_core.cli import build_parser, main
import lamtools_core.skill_runtime as skill_runtime


def _forget_office_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(sys.modules):
        if name == "lamtools_office_renderer" or name.startswith("lamtools_office_renderer."):
            monkeypatch.delitem(sys.modules, name, raising=False)


def test_office_cli_parser_accepts_positional_and_option_paths(tmp_path: Path) -> None:
    parser = build_parser()
    source = tmp_path / "input.pptx"
    manifest = tmp_path / "manifest.json"
    output = tmp_path / "rendered"

    positional = parser.parse_args(["office", "render", str(source), str(manifest), str(output)])
    assert positional.command == "office"
    assert positional.office_command == "render"
    assert positional.source_pos == str(source)
    assert positional.manifest_pos == str(manifest)
    assert positional.output_pos == str(output)
    assert positional.backend == "auto"

    options = parser.parse_args(
        [
            "office",
            "render",
            "--source",
            str(source),
            "--manifest",
            str(manifest),
            "--output-dir",
            str(output),
            "--backend",
            "libreoffice",
            "--timeout",
            "12.5",
            "--dpi",
            "96",
            "--report",
            str(tmp_path / "report.json"),
        ]
    )
    assert options.source_path == str(source)
    assert options.manifest_path == str(manifest)
    assert options.output_dir_path == str(output)
    assert (options.backend, options.timeout, options.dpi) == ("libreoffice", 12.5, 96)


def test_office_help_does_not_load_companion_runtime(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _forget_office_runtime(monkeypatch)

    with pytest.raises(SystemExit) as stopped:
        build_parser().parse_args(["office", "--help"])

    assert stopped.value.code == 0
    assert "lamtools_office_renderer" not in sys.modules
    assert "check" in capsys.readouterr().out


def test_office_loader_finds_companion_runtime_in_source_skill_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forget_office_runtime(monkeypatch)
    monkeypatch.setattr(core_cli.sys, "path", list(sys.path))
    source_skills = Path(__file__).resolve().parents[1] / "skills"
    monkeypatch.setattr(skill_runtime, "builtin_core_skill_roots", lambda: (source_skills,))

    operation = core_cli._office_service_operation("validate")

    assert operation.__module__ == "lamtools_office_renderer.service"
    assert str((source_skills / "office-renderer" / "scripts").resolve()) in sys.path


def test_office_loader_finds_companion_runtime_in_packaged_skill_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _forget_office_runtime(monkeypatch)
    monkeypatch.setattr(core_cli.sys, "path", list(sys.path))
    packaged_skills = tmp_path / "resources" / "skills"
    package = packaged_skills / "office-renderer" / "scripts" / "lamtools_office_renderer"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "def validate_office(*args, **kwargs):\n    return 'packaged'\n"
        "def render_office(*args, **kwargs):\n    return 'packaged'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_runtime, "builtin_core_skill_roots", lambda: (packaged_skills,))

    operation = core_cli._office_service_operation("render")

    assert operation() == "packaged"
    assert str((packaged_skills / "office-renderer" / "scripts").resolve()) in sys.path
    assert not (package / "__pycache__").exists()


def test_office_check_prints_one_readiness_line_and_writes_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = tmp_path / "office-check.json"
    observed: dict[str, object] = {}

    def fake_check(*, backend: str, timeout: float) -> dict[str, object]:
        observed.update({"backend": backend, "timeout": timeout})
        return {
            "ok": True,
            "exit_class": "success",
            "message": "Office 应用已就绪 · Test Passed 3/3",
            "passed": 3,
            "total": 3,
            "tests": [],
        }

    monkeypatch.setattr(core_cli, "_office_service_operation", lambda action: fake_check)
    assert main(["office", "check", "--timeout", "9", "--report", str(report)]) == 0
    assert capsys.readouterr().out.strip() == "Office 应用已就绪 · Test Passed 3/3"
    assert observed == {"backend": "auto", "timeout": 9.0}
    assert json.loads(report.read_text(encoding="utf-8"))["passed"] == 3


def test_bundled_office_script_is_runnable_from_an_unrelated_working_directory(
    tmp_path: Path,
) -> None:
    script = Path(__file__).resolve().parents[1] / "skills" / "office-renderer" / "scripts" / "office.py"
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0
    assert "validate" in completed.stdout
    assert "render" in completed.stdout


def test_bundled_office_script_reports_failures_as_json(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "skills" / "office-renderer" / "scripts" / "office.py"
    source = tmp_path / "missing.xlsx"
    manifest = tmp_path / "missing.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "validate",
            "--source",
            str(source),
            "--manifest",
            str(manifest),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == core_cli.OFFICE_EXIT_MANIFEST_MISMATCH
    assert payload["ok"] is False
    assert payload["exit_class"] in {"manifest_mismatch", "structure_invalid"}
    assert "Traceback" not in completed.stderr


def test_office_validate_is_a_service_adapter_and_writes_only_report(monkeypatch, tmp_path: Path, capsys) -> None:
    source = tmp_path / "input.xlsx"
    manifest = tmp_path / "manifest.json"
    report = tmp_path / "report.json"
    observed: dict[str, object] = {}

    def fake_validate(manifest_value, *, source=None):
        observed.update({"manifest": manifest_value, "source": source})
        return {"ok": True, "exit_class": "success", "issues": []}

    monkeypatch.setattr(core_cli, "_office_service_operation", lambda action: fake_validate)
    assert main(["office", "validate", "--source", str(source), "--manifest", str(manifest), "--report", str(report)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True, "exit_class": "success", "issues": []}
    assert observed == {"manifest": manifest, "source": source}
    assert json.loads(report.read_text(encoding="utf-8")) == payload
    assert not (tmp_path / "input-pages").exists()


def test_office_render_passes_auto_backend_and_classifies_failures(monkeypatch, tmp_path: Path, capsys) -> None:
    source = tmp_path / "input.docx"
    manifest = tmp_path / "manifest.json"
    output = tmp_path / "rendered"
    observed: dict[str, object] = {}

    def fake_render(manifest_value, output_value, *, source=None, backend="auto", timeout=0, dpi=0):
        observed.update(
            {
                "manifest": manifest_value,
                "output": output_value,
                "source": source,
                "backend": backend,
                "timeout": timeout,
                "dpi": dpi,
            }
        )
        return {"ok": False, "exit_class": "visual_unavailable", "issues": []}

    monkeypatch.setattr(core_cli, "_office_service_operation", lambda action: fake_render)
    assert main(["office", "render", str(source), str(manifest), str(output)]) == core_cli.OFFICE_EXIT_RENDER_FAILURE
    assert json.loads(capsys.readouterr().out)["exit_class"] == "visual_unavailable"
    assert observed == {
        "manifest": manifest,
        "output": output,
        "source": source,
        "backend": "auto",
        "timeout": 120.0,
        "dpi": 144,
    }


def test_office_cli_maps_manifest_and_layout_classes(monkeypatch, tmp_path: Path, capsys) -> None:
    source = tmp_path / "input.pptx"
    manifest = tmp_path / "manifest.json"
    output = tmp_path / "rendered"

    monkeypatch.setattr(
        core_cli,
        "_office_service_operation",
        lambda action: lambda *args, **kwargs: {
            "ok": False,
            "exit_class": "data_mismatch",
            "statuses": {"data": "failed", "structure": "passed", "visual": "not_run"},
            "issues": [],
        },
    )
    assert main(["office", "validate", str(source), str(manifest)]) == core_cli.OFFICE_EXIT_MANIFEST_MISMATCH
    capsys.readouterr()

    monkeypatch.setattr(
        core_cli,
        "_office_service_operation",
        lambda action: lambda *args, **kwargs: {
            "ok": False,
            "exit_class": "visual_issue",
            "statuses": {"data": "passed", "structure": "passed", "visual": "failed"},
            "issues": [{"code": "visual_overlap"}],
        },
    )
    assert main(["office", "render", str(source), str(manifest), str(output)]) == core_cli.OFFICE_EXIT_LAYOUT_CONFLICT
