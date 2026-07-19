from __future__ import annotations

from pathlib import Path

from scripts import member_cli


def test_sage_run_reuses_core_live_cli_with_sage_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def run(command: list[str], cwd: Path) -> int:
        captured.update(command=command, cwd=cwd)
        return 0

    monkeypatch.setattr(member_cli, "_run", run)

    assert member_cli._sage(["run", "核实这条消息"]) == 0
    assert captured["command"] == [
        "py", "-3.14", "-m", "lamtools_core.cli", "run", "核实这条消息",
        "--base-url", "http://127.0.0.1:6170",
        "--ws-path", "/api/core/app-server",
    ]
    assert captured["cwd"] == member_cli.ROOT / "core"


def test_sage_session_list_uses_sage_runtime_database(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def run(command: list[str], cwd: Path) -> int:
        captured.update(command=command, cwd=cwd)
        return 0

    monkeypatch.delenv("LAMSAGE_CORE_DB", raising=False)
    monkeypatch.delenv("LAMSAGE_DATA_DIR", raising=False)
    monkeypatch.setattr(member_cli, "_run", run)

    assert member_cli._sage(["session", "list"]) == 0
    assert captured["command"] == [
        "py", "-3.14", "-m", "lamtools_core.cli", "session", "list",
        "--core-db", str(member_cli.ROOT / "members" / "sage" / "data" / "sage.db"),
    ]


def test_sage_session_list_prefers_configured_core_database(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    core_db = tmp_path / "runtime" / "sage-core.db"

    def run(command: list[str], cwd: Path) -> int:
        captured.update(command=command, cwd=cwd)
        return 0

    monkeypatch.setenv("LAMSAGE_DATA_DIR", str(tmp_path / "other-data"))
    monkeypatch.setenv("LAMSAGE_CORE_DB", str(core_db))
    monkeypatch.setattr(member_cli, "_run", run)

    assert member_cli._sage(["session", "list"]) == 0
    assert captured["command"][-2:] == ["--core-db", str(core_db)]


def test_sage_project_uses_database_inside_configured_data_dir(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    data_dir = tmp_path / "sage-data"

    def run(command: list[str], cwd: Path) -> int:
        captured.update(command=command, cwd=cwd)
        return 0

    monkeypatch.delenv("LAMSAGE_CORE_DB", raising=False)
    monkeypatch.setenv("LAMSAGE_DATA_DIR", str(data_dir))
    monkeypatch.setattr(member_cli, "_run", run)

    assert member_cli._sage(["project", "list"]) == 0
    assert captured["command"][-2:] == ["--core-db", str(data_dir / "sage.db")]
