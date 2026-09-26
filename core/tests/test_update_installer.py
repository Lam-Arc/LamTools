"""The in-app update path: download a verified artifact, then hand it over.

The rules under test are the ones that keep an installer away from bytes nobody
vouched for: https only, a digest is required, a mismatch discards the download,
and only a file this process verified can be run.
"""

from __future__ import annotations

import asyncio
import hashlib
import http.server
import socketserver
import sys
import threading
from pathlib import Path

import pytest

from lamtools_core.update import installer
from lamtools_core.update.installer import UpdateInstallError, download_update, run_installer

BODY = b"sunday installer payload\n" * 4096
DIGEST = hashlib.sha256(BODY).hexdigest()


@pytest.fixture(autouse=True)
def clean_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Isolate the verified-path registry and the download directory."""
    installer._VERIFIED.clear()
    monkeypatch.setenv("LAMTOOLS_UPDATE_DIR", str(tmp_path / "updates"))
    yield
    installer._VERIFIED.clear()


@pytest.fixture()
def artifact_server():
    """Serve one artifact over loopback http, which the https rule allows."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — http.server's interface
            self.send_response(200)
            self.send_header("Content-Length", str(len(BODY)))
            self.end_headers()
            self.wfile.write(BODY)

        def log_message(self, *args):  # noqa: ARG002 — silence the test server
            return

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}/Sunday_9.9.9_x64-setup.exe"
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_downloads_verifies_and_publishes(artifact_server: str) -> None:
    result = download_update(artifact_server, DIGEST)

    target = Path(result["path"])
    assert target.read_bytes() == BODY
    assert result["sha256"] == DIGEST
    assert result["bytes"] == len(BODY)
    # The verified file is the one an installer may run; the partial is gone.
    assert not target.with_name(target.name + ".part").exists()
    assert installer._VERIFIED[str(target)] == DIGEST


def test_a_digest_mismatch_discards_the_download(artifact_server: str) -> None:
    wrong = hashlib.sha256(b"a different installer").hexdigest()

    with pytest.raises(UpdateInstallError, match="摘要不一致"):
        download_update(artifact_server, wrong)

    directory = installer.download_dir()
    assert not [path for path in directory.iterdir()], "nothing may be published"
    assert not installer._VERIFIED


def test_refuses_a_digest_it_cannot_use(artifact_server: str) -> None:
    for broken in ("", "abc", "z" * 64):
        with pytest.raises(UpdateInstallError, match="sha256"):
            download_update(artifact_server, broken)


def test_refuses_plain_http_away_from_loopback() -> None:
    with pytest.raises(UpdateInstallError, match="https"):
        download_update("http://example.com/Sunday_9.9.9_x64-setup.exe", DIGEST)


def test_a_path_is_reduced_to_its_base_name(artifact_server: str) -> None:
    """A traversal attempt cannot escape the update directory: only the base lands."""
    result = download_update(artifact_server, DIGEST, file_name="../../etc/passwd")

    target = Path(result["path"])
    assert target.parent == installer.download_dir()
    assert target.name == "passwd"


def test_refuses_a_file_name_it_cannot_use(artifact_server: str) -> None:
    with pytest.raises(UpdateInstallError, match="文件名无效"):
        download_update(artifact_server, DIGEST, file_name="bad name!.exe")


def test_run_installer_refuses_a_path_it_did_not_verify(tmp_path: Path) -> None:
    stranger = tmp_path / "Sunday_9.9.9_x64-setup.exe"
    stranger.write_bytes(BODY)

    with pytest.raises(UpdateInstallError, match="校验"):
        run_installer(str(stranger))


def test_run_installer_refuses_when_nothing_was_downloaded() -> None:
    with pytest.raises(UpdateInstallError, match="校验"):
        run_installer()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows is the platform with a single installer step")
def test_run_installer_launches_the_verified_file(
    artifact_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = download_update(artifact_server, DIGEST)
    launched: list[str] = []
    monkeypatch.setattr(installer.os, "startfile", lambda path, *a, **k: launched.append(path), raising=False)

    outcome = run_installer()

    assert launched == [result["path"]]
    assert "安装程序" in outcome["message"]


def test_the_operations_are_registered() -> None:
    from lamtools_core.update.operations import build_update_operation_catalog

    catalog = build_update_operation_catalog()

    assert {"update.check", "update.download", "update.install"} <= set(catalog.list())


def test_update_download_refuses_when_the_manifest_has_no_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    from lamtools_core.update import operations

    monkeypatch.setattr(
        operations,
        "check_update",
        lambda: {"status": "update_available", "download_url": "https://example.com/x.exe"},
    )
    catalog = operations.build_update_operation_catalog()

    result = asyncio.run(catalog.execute("update.download", {}))

    assert result.payload["ok"] is False
    assert "sha256" in result.payload["error"]


def _wait_for_state(expected: str, timeout_seconds: float = 15.0) -> dict:
    import time

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        snapshot = installer.progress_snapshot()
        if snapshot["state"] == expected:
            return snapshot
        if snapshot["state"] == "failed":
            raise AssertionError(f"download failed: {snapshot['error']}")
        time.sleep(0.02)
    raise AssertionError(f"download never reached {expected}: {installer.progress_snapshot()}")


def test_update_download_starts_and_reports_progress(
    monkeypatch: pytest.MonkeyPatch, artifact_server: str
) -> None:
    from lamtools_core.update import operations

    monkeypatch.setattr(
        operations,
        "check_update",
        lambda: {
            "status": "update_available",
            "latest_version": "9.9.9",
            "download_url": artifact_server,
            "sha256": DIGEST,
        },
    )
    catalog = operations.build_update_operation_catalog()

    started = asyncio.run(catalog.execute("update.download", {}))

    # The request returns at once: a long download must not hold the UI's call open.
    assert started.payload["ok"] is True
    assert started.payload["state"] == "downloading"

    verified = _wait_for_state("verified")
    assert verified["sha256"] == DIGEST
    assert Path(verified["path"]).read_bytes() == BODY

    status = asyncio.run(catalog.execute("update.status", {}))
    assert status.payload["state"] == "verified"
    assert "校验" in status.payload["message"]


def test_a_second_start_watches_instead_of_downloading_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reopening the panel while a download runs must not start another one."""
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def fake_worker(url: str, sha256: str, file_name: str) -> None:  # noqa: ARG001
        calls.append(url)
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(installer, "_download_worker", fake_worker)
    try:
        installer.start_download("https://example.com/a.exe", DIGEST)
        assert started.wait(timeout=5)
        again = installer.start_download("https://example.com/a.exe", DIGEST)
        assert again["state"] == "downloading"
        assert calls == ["https://example.com/a.exe"], "only one worker may run"
    finally:
        release.set()


def test_update_install_requires_a_verified_download(monkeypatch: pytest.MonkeyPatch) -> None:
    from lamtools_core.update import operations

    catalog = operations.build_update_operation_catalog()

    refused = asyncio.run(catalog.execute("update.install", {}))

    assert refused.payload["ok"] is False
    assert "校验" in refused.payload["error"]
