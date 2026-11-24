"""Everything 接入的单元测试：查询编译、CSV 解析、计数与故障分类。"""

from __future__ import annotations

import io
import subprocess
import zipfile

import pytest

from lamtools_core.library.everything import (
    EverythingError,
    EverythingProvider,
    SearchSpec,
    compile_query,
    install_es,
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


def _zip_with_es(payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("es.exe", payload)
    return buffer.getvalue()


def test_install_es_extracts_official_layout(tmp_path):
    target_dir = tmp_path / "tools"
    result = install_es(target_dir, zip_bytes=_zip_with_es(b"MZ" + b"0" * 30_000))
    assert result["installed"] is True
    assert (target_dir / "es.exe").read_bytes().startswith(b"MZ")
    again = install_es(target_dir, zip_bytes=b"not-used")
    assert again["already_present"] is True


def test_install_es_rejects_invalid_payload(tmp_path):
    with pytest.raises(EverythingError) as excinfo:
        install_es(tmp_path / "tools", zip_bytes=b"not a zip")
    assert excinfo.value.code == "install_failed"


def test_missing_cli_status_offers_install(tmp_path, monkeypatch):
    provider = EverythingProvider(data_dir=tmp_path, es_path=tmp_path / "none.exe")
    monkeypatch.setattr(provider, "resolve_es_path", lambda: None)
    monkeypatch.setattr(
        provider,
        "_everything_install_path",
        staticmethod(lambda: "C:\\Program Files\\Everything\\Everything.exe"),
    )
    status = provider.status(refresh=True)
    assert status["state"] == "missing_cli"
    assert status["can_install"] is True
    assert status["es_install_dir"] == str(tmp_path / "tools")


@pytest.mark.asyncio
async def test_engine_install_shares_work_after_rpc_cancellation(tmp_path, monkeypatch):
    import asyncio
    import threading
    from types import SimpleNamespace

    from lamtools_core.library import service as library

    entered = asyncio.Event()
    release = threading.Event()
    calls = []
    loop = asyncio.get_running_loop()

    def install(directory):
        calls.append(directory)
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)
        return {"installed": True}

    monkeypatch.setattr(library, "install_es", install)
    service = library.LibraryFileService(
        None,
        SimpleNamespace(es_install_dir=lambda: tmp_path, refresh=lambda: None),
    )

    async def status():
        return {"available": True}

    monkeypatch.setattr(service, "status", status)
    first = asyncio.create_task(service.install_engine())
    await asyncio.wait_for(entered.wait(), timeout=5)
    try:
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        calls_after_cancel = [
            asyncio.create_task(service.install_engine()) for _ in range(2)
        ]
        await asyncio.sleep(0)
    finally:
        release.set()
    assert await asyncio.gather(*calls_after_cancel) == [
        {"installation": {"installed": True}, "status": {"available": True}},
    ] * 2
    assert calls == [tmp_path]


def test_install_es_stops_reading_oversized_download(tmp_path, monkeypatch):
    import requests

    class OversizedDownload:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            block = b"x" * chunk_size
            for _ in range((10 * 1024 * 1024 // chunk_size) + 1):
                yield block
            pytest.fail("oversized download was not stopped")

    def get(_url, **options):
        assert options["stream"] is True
        return OversizedDownload()

    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(EverythingError, match="超过预期大小"):
        install_es(tmp_path / "tools")
    assert not (tmp_path / "tools" / "es.exe").exists()
