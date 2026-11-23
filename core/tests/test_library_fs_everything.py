"""Everything 接入的单元测试：查询编译、CSV 解析、计数与故障分类。"""

from __future__ import annotations

import subprocess

import pytest

from lamtools_core.library.everything import (
    EverythingError,
    EverythingProvider,
    SearchSpec,
    compile_query,
)


def test_compile_query_keeps_user_expression_and_appends_filters():
    query = compile_query(
        SearchSpec(
            query='miku size:>10mb',
            kinds=["image"],
            size_min=1024,
            modified_within_days=7,
        )
    )
    assert query.startswith("miku size:>10mb")
    assert "ext:jpg;jpeg;png" in query
    assert "size:>=1024" in query
    assert "dm:>=" in query


def test_compile_query_folder_only_does_not_add_extension_filter():
    query = compile_query(SearchSpec(query="LamTools", kinds=["folder"]))
    assert query == "LamTools"


def test_search_parses_csv_and_counts_without_duplicating_ext(tmp_path, monkeypatch):
    provider = EverythingProvider(es_path=tmp_path / "es.exe")
    calls: list[list[str]] = []

    def fake_run(args, *, timeout=None):
        calls.append(list(args))
        if "-get-result-count" in args:
            return subprocess.CompletedProcess(args, 0, b"42\n", b"")
        export_index = args.index("-export-csv") + 1
        export_path = args[export_index]
        content = (
            '\ufeff"miku.png","D:\\Art","2048","2026-11-20T10:00:00","2026-11-01T09:00:00","png","A"\r\n'
            '"素材","D:\\Art","","2026-11-21T10:00:00","2026-11-01T09:00:00","","D"\r\n'
        )
        with open(export_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(provider, "_run", fake_run)
    page = provider.search(SearchSpec(kinds=["image"], limit=60))

    assert page.total == 42
    assert len(page.items) == 2
    assert page.items[0].path == "D:\\Art\\miku.png"
    assert page.items[0].size == 2048
    assert page.items[0].is_dir is False
    assert page.items[1].is_dir is True
    search_args = next(args for args in calls if "-get-result-count" not in args)
    query = search_args[-1]
    assert query.count("ext:") == 1
    assert "-sort" in search_args


def test_status_reports_missing_cli(monkeypatch):
    provider = EverythingProvider(es_path="Z:\\missing\\es.exe")
    monkeypatch.setattr(provider, "resolve_es_path", lambda: None)
    monkeypatch.setattr(provider, "_everything_install_path", staticmethod(lambda: ""))
    status = provider.status(refresh=True)
    assert status["state"] == "not_installed"
    assert status["available"] is False


def test_status_reports_not_running(tmp_path, monkeypatch):
    provider = EverythingProvider(es_path=tmp_path / "es.exe")
    monkeypatch.setattr(provider, "resolve_es_path", lambda: str(tmp_path / "es.exe"))
    monkeypatch.setattr(provider, "_everything_install_path", staticmethod(lambda: "C:\\Everything\\Everything.exe"))

    def fake_run(args, *, timeout=None):
        return subprocess.CompletedProcess(args, 8, b"", b"Everything IPC window not found")

    monkeypatch.setattr(provider, "_run", fake_run)
    status = provider.status(refresh=True)
    assert status["state"] == "not_running"
    assert "Everything" in status["message"]


def test_search_raises_clear_error_when_everything_unavailable(tmp_path, monkeypatch):
    provider = EverythingProvider(es_path=tmp_path / "es.exe")
    monkeypatch.setattr(provider, "resolve_es_path", lambda: None)
    with pytest.raises(EverythingError) as excinfo:
        provider.search(SearchSpec(query="miku"))
    assert excinfo.value.code == "missing_cli"
