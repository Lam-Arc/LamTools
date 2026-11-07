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
    """Isolate the verified-path registry, the progress state and the download dir."""
    installer._VERIFIED.clear()
    installer._CANCEL.clear()
    installer._set_progress(state="idle", received=0, total=0, name="", sha256="", path="", error="")
    monkeypatch.setenv("LAMTOOLS_UPDATE_DIR", str(tmp_path / "updates"))
    yield
    installer._VERIFIED.clear()
    installer._CANCEL.clear()


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


class FakeSetup:
    """A spawned setup that keeps running outside any job unless told otherwise."""

    def __init__(self, exit_code: int | None = None) -> None:
        self.pid = 4321
        self._exit_code = exit_code
        self.terminated = False
        self.closed = False
        self.returncode = exit_code

    def poll(self) -> int | None:
        return self._exit_code

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        self._exit_code = 1
        self.returncode = 1
        return 1

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def fast_launch_confirmation(monkeypatch: pytest.MonkeyPatch):
    """The real wait is 1.5s of proving the setup survived; tests do not need it."""
    monkeypatch.setattr(installer, "LAUNCH_CONFIRM_SECONDS", 0.05)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows is the platform with a single installer step")
def test_run_installer_launches_the_verified_file(
    artifact_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = download_update(artifact_server, DIGEST)
    spawned: list[dict] = []
    fake = FakeSetup()
    monkeypatch.setattr(installer, "_process_is_in_a_job", lambda pid: False)
    monkeypatch.setattr(
        installer.subprocess,
        "Popen",
        lambda argv, **kwargs: (spawned.append({"argv": argv, **kwargs}), fake)[1],
    )

    outcome = run_installer()

    expected_arguments = installer.installer_arguments(
        installer.download_dir() / "install-last.log",
        installer.download_dir() / "install-failure.txt",
    )
    assert spawned == [{
        "argv": [result["path"], *expected_arguments],
        "cwd": str(Path(result["path"]).parent),
        "creationflags": installer.INSTALLER_SPAWN_FLAGS,
        "close_fds": True,
    }]
    # The app must exit: the installer replaces the files this process owns.
    assert outcome["quit"] is True
    assert "退出" in outcome["message"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows is the platform with a single installer step")
def test_the_in_app_install_runs_quietly_and_brings_the_app_back() -> None:
    """What the in-app update promises: no questions, no reboot prompt, app back.

    A silent install skips the [Run] entry that launches Sunday, so the setup is
    told explicitly to start it again — otherwise the update ends with the user
    staring at a closed window. The log travels with it because the app is gone
    while the installer works.
    """
    arguments = installer.installer_arguments(Path("C:/tmp/sunday-update/install-last.log"))

    assert "/SILENT" in arguments
    assert "/NORESTART" in arguments
    assert "/AUTORESTART=1" in arguments
    assert "/LOG=C:\\tmp\\sunday-update\\install-last.log" in arguments or \
        "/LOG=C:/tmp/sunday-update/install-last.log" in arguments


def test_the_launch_names_the_failure_report_it_wants_written() -> None:
    """A refusal has to leave its reason where the app can still read it.

    The setup writes process names, PIDs and files to this path; without it the
    reason only exists in a log nobody looks at.
    """
    arguments = installer.installer_arguments(
        Path("C:/tmp/sunday-update/install-last.log"),
        Path("C:/tmp/sunday-update/install-failure.txt"),
    )

    assert "/FAILREPORT=C:\\tmp\\sunday-update\\install-failure.txt" in arguments or \
        "/FAILREPORT=C:/tmp/sunday-update/install-failure.txt" in arguments


def test_a_cancelled_download_stops_and_leaves_nothing_behind(artifact_server: str) -> None:
    installer._CANCEL.set()
    try:
        with pytest.raises(installer.UpdateCancelled):
            download_update(artifact_server, DIGEST)
    finally:
        installer._CANCEL.clear()

    leftovers = list(installer.download_dir().iterdir())
    assert leftovers == [], f"a cancelled download left {leftovers} behind"
    assert str(installer.download_dir() / "sunday-installer.bin") not in installer._VERIFIED


def test_the_worker_reports_a_cancel_as_cancelled_not_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def cancelled(*_args: object, **_kwargs: object) -> None:
        raise installer.UpdateCancelled("下载已取消")

    monkeypatch.setattr(installer, "download_update", cancelled)

    installer._download_worker("https://example.com/x.exe", "a" * 64, "x.exe")

    assert installer.progress_snapshot()["state"] == "cancelled"


def test_cancelling_when_nothing_runs_is_a_no_op() -> None:
    """A card can be asked to cancel twice; the second ask must not become an error."""
    before = installer.progress_snapshot()

    assert installer.cancel_download() == before
    assert installer._CANCEL.is_set() is False
    assert installer.progress_snapshot()["state"] == "idle"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows is the platform with a single installer step")
def test_run_installer_leaves_the_backend_job_so_the_installer_survives(
    artifact_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The desktop shell's job object kills its members when the app exits.

    Without the breakaway flag the installer would die at exactly the moment the
    app quits to let it work, so the flags are part of the contract, not a detail.
    """
    download_update(artifact_server, DIGEST)
    monkeypatch.setattr(installer.subprocess, "Popen", lambda *a, **k: FakeSetup())
    monkeypatch.setattr(installer, "_process_is_in_a_job", lambda pid: False)

    run_installer()

    assert installer.INSTALLER_SPAWN_FLAGS & installer.CREATE_BREAKAWAY_FROM_JOB
    assert installer.INSTALLER_SPAWN_FLAGS & installer.DETACHED_PROCESS


@pytest.mark.skipif(sys.platform != "win32", reason="Windows is the platform with a single installer step")
def test_a_setup_still_inside_a_job_is_handed_to_the_shell_instead(
    artifact_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A setup that is still a job member dies with the app, so it must not be used.

    Breaking away only leaves the innermost job; an outer one (a launcher, a
    terminal, another installer) still kills the setup when this process exits.
    The check is real, and the fallback is what keeps that machine updating.
    """
    download_update(artifact_server, DIGEST)
    fake = FakeSetup()
    launched: list[str] = []
    monkeypatch.setattr(installer.subprocess, "Popen", lambda *a, **k: fake)
    monkeypatch.setattr(installer, "_process_is_in_a_job", lambda pid: True)
    monkeypatch.setattr(installer.os, "startfile", lambda path, *a, **k: launched.append(path), raising=False)

    outcome = run_installer()

    assert fake.terminated, "the doomed setup must be ended before the hand-off"
    assert launched, "the shell hand-off has to start the installer"
    assert outcome["quit"] is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows is the platform with a single installer step")
def test_a_setup_that_exits_at_once_keeps_the_app_running(
    artifact_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quitting for an installer that already died leaves no app and no update.

    A blocked executable, a refused command line or a broken artifact all show up
    as an immediate exit code; the app must stay up and say so instead of closing.
    """
    download_update(artifact_server, DIGEST)
    monkeypatch.setattr(installer.subprocess, "Popen", lambda *a, **k: FakeSetup(exit_code=5))
    monkeypatch.setattr(installer, "_process_is_in_a_job", lambda pid: False)

    with pytest.raises(UpdateInstallError, match="退出码 5"):
        run_installer()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows is the platform with a single installer step")
def test_the_launch_is_recorded_for_support(
    artifact_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The app is gone while the setup works: this file is what is left to read."""
    import json

    result = download_update(artifact_server, DIGEST)
    monkeypatch.setattr(installer.subprocess, "Popen", lambda *a, **k: FakeSetup())
    monkeypatch.setattr(installer, "_process_is_in_a_job", lambda pid: False)

    run_installer()

    record = json.loads((installer.download_dir() / "install-launch.json").read_text(encoding="utf-8"))
    assert record["installer"] == result["path"]
    assert record["process_id"] == 4321
    assert record["mode"] == "detached"
    assert record["log"].endswith("install-last.log")
    assert record["failure_report"].endswith("install-failure.txt")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows is the platform with a single installer step")
def test_a_stale_failure_report_is_cleared_before_the_launch(
    artifact_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Yesterday's refusal must not be read as this attempt's verdict."""
    stale = installer.download_dir() / "install-failure.txt"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("old failure", encoding="utf-8")
    download_update(artifact_server, DIGEST)
    monkeypatch.setattr(installer.subprocess, "Popen", lambda *a, **k: FakeSetup())
    monkeypatch.setattr(installer, "_process_is_in_a_job", lambda pid: False)

    run_installer()

    assert not stale.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows is the platform with a single installer step")
def test_run_installer_falls_back_to_the_shell_hand_off(
    artifact_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host without a job object (a plain CLI run) refuses the breakaway flag.

    Losing the update there would be worse than a hand-off the shell can still
    complete, so the fallback runs the same verified file.
    """
    result = download_update(artifact_server, DIGEST)
    launched: list[str] = []

    def refuse(*args, **kwargs):  # noqa: ANN002, ANN003
        raise OSError(13, "permission denied")

    monkeypatch.setattr(installer.subprocess, "Popen", refuse)
    monkeypatch.setattr(installer.os, "startfile", lambda path, *a, **k: launched.append(path), raising=False)

    outcome = run_installer()

    assert launched == [result["path"]]
    assert outcome["quit"] is True


def test_run_installer_reveals_without_quitting_elsewhere(
    artifact_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only Windows hands the update to something that replaces the running app.

    Elsewhere the verified file is revealed and the app stays up; `quit: False`
    is what keeps the UI from closing a window that has nothing to wait for.
    """
    result = download_update(artifact_server, DIGEST)
    revealed: list[Path] = []
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(installer, "_reveal", lambda directory: revealed.append(directory))

    outcome = run_installer()

    assert revealed == [Path(result["path"]).parent]
    assert outcome["quit"] is False


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

    def fake_worker(url: str, sha256: str, file_name: str, fallback_url: str = "") -> None:  # noqa: ARG001
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
