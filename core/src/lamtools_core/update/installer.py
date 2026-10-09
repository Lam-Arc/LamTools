"""Download a verified update artifact and hand it to the platform's installer.

Host-side twice over: the artifact is only published (renamed out of its
``.part`` name) after its bytes match the digest the manifest carries, and only a
file this process verified can be run. The UI supplies neither a URL nor a path,
so it cannot point the installer at something the release did not publish.

Installing stays a user decision — the caller sees the message from
:func:`run_installer` and the platform's own installer takes over from there.
On Windows that hand-off ends this process: the returned ``quit`` flag tells the
desktop host to exit, so the old app is gone while the installer replaces its
files.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_log = logging.getLogger(__name__)

#: The Windows installer is ~95 MB; this is a sanity bound against a wrong URL,
#: not a budget anyone should reach.
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
CHUNK_BYTES = 1 << 20
#: Generous overall budget: a slow but healthy download must not be aborted.
DOWNLOAD_TIMEOUT_SECONDS = 1800.0

#: How the in-app install runs the installer: no questions (progress still shows),
#: no reboot prompt, and the app is started again once the files are in place —
#: an update that ends with the user staring at a closed window is not finished.
#: The log lands next to the verified download so a failed install leaves
#: something to read (the app itself is gone by then).
INSTALLER_ARGUMENTS = ("/SILENT", "/NORESTART", "/AUTORESTART=1")

#: How the installer is started on Windows. It must outlive this process: the
#: desktop shell runs the backend inside a job object that kills every member
#: when the app exits (``create_backend_job``), and the app exits as part of this
#: hand-off. ``CREATE_BREAKAWAY_FROM_JOB`` leaves that job — allowed because the
#: shell sets ``JOB_OBJECT_LIMIT_BREAKAWAY_OK`` — while the other two flags
#: detach the installer from this process's console and process group.
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
INSTALLER_SPAWN_FLAGS = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB

#: Paths this process downloaded and verified, and the digest each matched.
_VERIFIED: dict[str, str] = {}

#: Live download state, so the UI can show progress instead of a blind spinner.
_PROGRESS_LOCK = threading.Lock()
_PROGRESS: dict[str, Any] = {
    "state": "idle",  # idle | downloading | verified | failed
    "received": 0,
    "total": 0,
    "name": "",
    "sha256": "",
    "path": "",
    "error": "",
}


class UpdateInstallError(RuntimeError):
    """A download or install step that cannot proceed."""


class UpdateCancelled(UpdateInstallError):
    """The running download was cancelled by the caller (not a failure)."""


#: Set while a cancel is pending; the download worker checks it between chunks.
_CANCEL = threading.Event()


def download_dir() -> Path:
    override = os.environ.get("LAMTOOLS_UPDATE_DIR", "").strip()
    root = Path(override) if override else Path(tempfile.gettempdir()) / "sunday-update"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_name(value: str) -> str:
    name = Path(str(value or "")).name.strip()
    if not name or len(name) > 120 or not all(character.isalnum() or character in "._-" for character in name):
        raise UpdateInstallError("安装包文件名无效")
    return name


def progress_snapshot() -> dict[str, Any]:
    """The current download state, safe to read from another thread or task."""
    with _PROGRESS_LOCK:
        return dict(_PROGRESS)


def _set_progress(**fields: Any) -> None:
    with _PROGRESS_LOCK:
        _PROGRESS.update(fields)


def start_download(url: str, sha256: str, file_name: str = "") -> dict[str, Any]:
    """Begin a download in a worker thread and return at once.

    Long downloads must not hold the UI's request open: the caller polls
    :func:`progress_snapshot` instead. A second call while one is running is a
    no-op, so a reopened panel resumes watching the same download.
    """
    current = progress_snapshot()
    if current["state"] == "downloading":
        return current
    _CANCEL.clear()
    _set_progress(state="downloading", received=0, total=0, name="", sha256="", path="", error="")
    threading.Thread(
        target=_download_worker, args=(url, sha256, file_name), daemon=True, name="sunday-update-download"
    ).start()
    return progress_snapshot()


def cancel_download() -> dict[str, Any]:
    """Ask the running download to stop and report the state right away.

    The worker checks the flag between chunks, so the transfer stops within one
    chunk (1 MB) and then removes the partial file through its own cleanup; the
    state it leaves behind is ``cancelled``, never ``failed``. Cancelling when
    nothing runs is a no-op rather than an error — the card can be clicked twice.
    """
    if progress_snapshot()["state"] != "downloading":
        return progress_snapshot()
    _CANCEL.set()
    return progress_snapshot()


def _download_worker(url: str, sha256: str, file_name: str) -> None:
    try:
        result = download_update(url, sha256, file_name)
    except UpdateCancelled:
        _set_progress(state="cancelled", error="")
    except UpdateInstallError as exc:
        _set_progress(state="failed", error=str(exc))
    except Exception as exc:  # noqa: BLE001 — the worker must never take the process down
        _set_progress(state="failed", error=f"下载安装包失败：{exc}")
    else:
        _set_progress(
            state="verified",
            received=result["bytes"],
            total=result["bytes"],
            name=result["name"],
            sha256=result["sha256"],
            path=result["path"],
            error="",
        )


def download_update(url: str, sha256: str, file_name: str = "") -> dict[str, Any]:
    """Stream ``url`` into the update directory, verifying ``sha256``.

    Returns ``{"path", "name", "bytes", "sha256"}`` for the verified file. A
    digest mismatch removes the partial download and raises.
    """
    import httpx

    expected = str(sha256 or "").strip().lower()
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise UpdateInstallError("发布清单没有提供可用的 sha256，无法校验安装包")
    parsed = urlparse(url)
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        # The same rule the mobile host applies: https everywhere except the
        # loopback servers the tests use, where there is no network to protect.
        raise UpdateInstallError("安装包必须通过 https 下载")
    name = _safe_name(file_name or url.rsplit("/", 1)[-1])
    target = download_dir() / name
    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    received = 0
    try:
        with httpx.stream(
            "GET",
            url,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": _user_agent(), "Accept": "application/octet-stream"},
        ) as response:
            response.raise_for_status()
            length = response.headers.get("content-length", "")
            if length.isdigit() and int(length) > MAX_ARTIFACT_BYTES:
                raise UpdateInstallError("安装包超出预期大小")
            declared = int(length) if length.isdigit() else 0
            _set_progress(received=0, total=declared)
            with open(partial, "wb") as handle:
                for chunk in response.iter_bytes(CHUNK_BYTES):
                    if _CANCEL.is_set():
                        raise UpdateCancelled("下载已取消")
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > MAX_ARTIFACT_BYTES:
                        raise UpdateInstallError("安装包超出预期大小")
                    digest.update(chunk)
                    handle.write(chunk)
                    _set_progress(received=received)
        if _CANCEL.is_set():
            raise UpdateCancelled("下载已取消")
        if digest.hexdigest() != expected:
            raise UpdateInstallError("下载的安装包与清单摘要不一致，已丢弃")
        os.replace(partial, target)
    except UpdateInstallError:
        raise
    except Exception as exc:  # noqa: BLE001 — every transport failure is one user-facing reason
        raise UpdateInstallError(f"下载安装包失败：{exc}") from exc
    finally:
        partial.unlink(missing_ok=True)
    _VERIFIED[str(target)] = expected
    _log.info("Update: downloaded %s (%s bytes, sha256 verified)", name, received)
    return {"path": str(target), "name": name, "bytes": received, "sha256": expected}


def run_installer(path: str = "") -> dict[str, Any]:
    """Run the installer this process verified, or reveal it where that is unsupported.

    ``quit`` in the result is the caller's instruction: on Windows the installer
    is already running on its own and the app must exit for it to replace files,
    while on the other platforms nothing was started and the app stays up.
    """
    candidate = Path(path) if path else next(
        (Path(known) for known in reversed(list(_VERIFIED))), None
    )
    if candidate is None or str(candidate) not in _VERIFIED:
        raise UpdateInstallError("只能运行本次下载并校验通过的安装包")
    if not candidate.is_file():
        raise UpdateInstallError("安装包已不存在，请重新下载")
    if sys.platform != "win32":
        # Linux and macOS have no single "run this installer" contract: an
        # AppImage needs its own permissions and a .deb belongs to the package
        # manager. Reveal the verified file and say so.
        _reveal(candidate.parent)
        return {
            "path": str(candidate),
            "quit": False,
            "message": "已打开安装包所在文件夹；自动安装目前仅支持 Windows。",
        }
    _launch_installer(candidate)
    _log.info("Update: started installer %s", candidate.name)
    return {
        "path": str(candidate),
        "quit": True,
        "message": "正在安装；Sunday 即将退出，装好后会自动打开。",
    }


def installer_arguments(log_path: Path | None = None) -> list[str]:
    """The switches the in-app install hands the setup.

    ``/LOG`` goes next to the verified download: the app is gone while the
    installer works, so that file is the only record a failed install leaves.
    """
    arguments = list(INSTALLER_ARGUMENTS)
    if log_path is not None:
        arguments.append(f"/LOG={log_path}")
    return arguments


def _launch_installer(candidate: Path) -> None:
    """Start the verified installer so it survives this process's exit.

    ``os.startfile`` would make the installer a member of whatever job object
    this process belongs to, and the desktop shell's job is kill-on-close: the
    installer would die exactly when the app exits to let it work. The explicit
    spawn asks to leave that job. A host with no job object at all (a plain CLI
    run, a test) refuses the breakaway flag, and there the shell hand-off is the
    right answer — so the failure falls back to it instead of losing the update.
    """
    arguments = installer_arguments(download_dir() / "install-last.log")
    try:
        subprocess.Popen(  # noqa: S603 — the digest was verified before publishing the file
            [str(candidate), *arguments],
            cwd=str(candidate.parent),
            creationflags=INSTALLER_SPAWN_FLAGS,
            close_fds=True,
        )
    except OSError:
        _log.info("Update: detached spawn refused, falling back to the shell hand-off")
        # The shell hand-off takes one command line, so the switches travel as
        # text; quoting keeps a path with spaces (a temp dir under a user name
        # often has one) a single argument.
        os.startfile(  # noqa: S606 — digest verified before publishing the file
            str(candidate),
            arguments=" ".join(f'"{item}"' if " " in item else item for item in arguments),
        )


def _reveal(directory: Path) -> None:
    for command in (["xdg-open", str(directory)], ["open", str(directory)]):
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue


def _user_agent() -> str:
    from lamtools_core import __version__

    return f"Sunday/{__version__} (update-download)"


__all__ = [
    "MAX_ARTIFACT_BYTES",
    "UpdateCancelled",
    "UpdateInstallError",
    "cancel_download",
    "download_dir",
    "download_update",
    "installer_arguments",
    "progress_snapshot",
    "run_installer",
    "start_download",
]
