from __future__ import annotations

import os
import signal
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from .models import BackendInfo, OfficeBackendUnavailable, OfficeRendererError, OfficeRenderTimeout


class OfficeBackend(Protocol):
    info: BackendInfo

    def render_pdf(self, source: Path, destination: Path, *, timeout: float) -> None: ...


@dataclass(slots=True)
class PdfPassthroughBackend:
    info: BackendInfo = BackendInfo("pdf_passthrough", None)

    def render_pdf(self, source: Path, destination: Path, *, timeout: float) -> None:
        del timeout
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)


@dataclass(slots=True)
class MicrosoftOfficeComBackend:
    powershell: str
    info: BackendInfo

    @classmethod
    def discover(cls, source: Path, *, timeout: float = 8.0) -> MicrosoftOfficeComBackend | None:
        if os.name != "nt":
            return None
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if not powershell:
            return None
        prog_id = _prog_id(source.suffix)
        if prog_id is None:
            return None
        escaped = prog_id.replace("'", "''")
        script = (
            f"$t=[type]::GetTypeFromProgID('{escaped}'); if($null-eq $t){{exit 3}}; "
            "$app=$null; try{$app=[Activator]::CreateInstance($t); [Console]::Out.Write([string]$app.Version)} "
            "finally{if($null-ne $app){$app.Quit(); [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($app)}}"
        )
        try:
            result = _run_process(
                [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return cls(powershell, BackendInfo("microsoft_office_com", result.stdout.strip() or None))

    def render_pdf(self, source: Path, destination: Path, *, timeout: float) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        suffix = source.suffix.casefold()
        body = _com_script(suffix, str(source.resolve()), str(destination.resolve()))
        try:
            result = _run_process(
                [self.powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", body],
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise OfficeRenderTimeout(f"Microsoft Office conversion timed out after {timeout:g}s") from exc
        except OSError as exc:
            raise OfficeRendererError(f"failed to start PowerShell for Office conversion: {exc}") from exc
        if result.returncode != 0 or not destination.is_file():
            detail = (result.stderr or result.stdout).strip()
            raise OfficeRendererError(f"Microsoft Office conversion failed ({result.returncode}): {detail}")


@dataclass(slots=True)
class LibreOfficeBackend:
    executable: str
    info: BackendInfo

    @classmethod
    def discover(cls, *, timeout: float = 8.0) -> LibreOfficeBackend | None:
        path_candidates = [shutil.which("soffice"), shutil.which("libreoffice")]
        candidates: list[str | None] = []
        if os.name == "nt":
            for item in path_candidates:
                if item:
                    candidates.extend([str(Path(item).with_name("soffice.com")), item])
            candidates.extend(
                [
                    r"C:\Program Files\LibreOffice\program\soffice.com",
                    r"C:\Program Files\LibreOffice\program\soffice.exe",
                    r"C:\Program Files (x86)\LibreOffice\program\soffice.com",
                    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                ]
            )
        else:
            candidates.extend(path_candidates)
        executable = next((str(Path(item)) for item in candidates if item and Path(item).is_file()), None)
        if executable is None:
            return None
        try:
            result = _run_process([executable, "--version"], timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return cls(executable, BackendInfo("libreoffice", result.stdout.strip() or None))

    def render_pdf(self, source: Path, destination: Path, *, timeout: float) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="lamtools-office-profile-") as profile_name, tempfile.TemporaryDirectory(prefix="lamtools-office-output-") as output_name:
            profile_uri = "file:///" + quote(Path(profile_name).resolve().as_posix(), safe="/:")
            command = [
                self.executable,
                "--headless",
                "--nologo",
                "--nodefault",
                "--nolockcheck",
                f"-env:UserInstallation={profile_uri}",
                "--convert-to",
                "pdf",
                "--outdir",
                output_name,
                str(source.resolve()),
            ]
            try:
                result = _run_process(command, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                raise OfficeRenderTimeout(f"LibreOffice conversion timed out after {timeout:g}s") from exc
            except OSError as exc:
                raise OfficeRendererError(f"failed to start LibreOffice: {exc}") from exc
            generated = Path(output_name) / f"{source.stem}.pdf"
            if result.returncode != 0 or not generated.is_file():
                detail = (result.stderr or result.stdout).strip()
                raise OfficeRendererError(f"LibreOffice conversion failed ({result.returncode}): {detail}")
            shutil.copy2(generated, destination)


def select_backend(source: Path, *, requested: str = "auto", discovery_timeout: float = 8.0) -> OfficeBackend:
    if requested not in {"auto", "microsoft", "libreoffice"}:
        raise ValueError("backend must be auto, microsoft, or libreoffice")
    if source.suffix.casefold() == ".pdf":
        return PdfPassthroughBackend()
    if requested in {"auto", "microsoft"}:
        com = MicrosoftOfficeComBackend.discover(source, timeout=discovery_timeout)
        if com is not None:
            return com
        if requested == "microsoft":
            raise OfficeBackendUnavailable("Microsoft Office COM is not available")
    if requested in {"auto", "libreoffice"}:
        libreoffice = LibreOfficeBackend.discover(timeout=discovery_timeout)
        if libreoffice is not None:
            return libreoffice
        if requested == "libreoffice":
            raise OfficeBackendUnavailable("LibreOffice is not available")
    raise OfficeBackendUnavailable("neither Microsoft Office COM nor LibreOffice is available")


def _prog_id(suffix: str) -> str | None:
    return {".pptx": "PowerPoint.Application", ".docx": "Word.Application", ".xlsx": "Excel.Application"}.get(suffix.casefold())


def _ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _com_script(suffix: str, source: str, destination: str) -> str:
    src = _ps_literal(source)
    dst = _ps_literal(destination)
    prefix = "$ErrorActionPreference='Stop'; $app=$null; $doc=$null; try { "
    suffix = suffix.casefold()
    if suffix == ".pptx":
        operation = f"$app=New-Object -ComObject PowerPoint.Application; $doc=$app.Presentations.Open({src},$true,$false,$false); $doc.SaveAs({dst},32);"
        close = "if($null-ne $doc){$doc.Close()}"
    elif suffix == ".docx":
        operation = f"$app=New-Object -ComObject Word.Application; $app.Visible=$false; $doc=$app.Documents.Open({src},$false,$true); $doc.ExportAsFixedFormat({dst},17);"
        close = "if($null-ne $doc){$doc.Close($false)}"
    elif suffix == ".xlsx":
        operation = f"$app=New-Object -ComObject Excel.Application; $app.Visible=$false; $app.DisplayAlerts=$false; $doc=$app.Workbooks.Open({src},0,$true); $doc.ExportAsFixedFormat(0,{dst});"
        close = "if($null-ne $doc){$doc.Close($false)}"
    else:
        raise OfficeRendererError(f"Microsoft Office COM does not support {suffix}")
    cleanup = (
        close
        + "; if($null-ne $doc){[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($doc)}"
        + "; if($null-ne $app){$app.Quit(); [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($app)}"
        + "; [GC]::Collect(); [GC]::WaitForPendingFinalizers()"
    )
    return prefix + operation + " } finally { " + cleanup + " }"


def _run_process(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        taskkill = shutil.which("taskkill")
        if taskkill:
            try:
                subprocess.run([taskkill, "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False, timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if process.poll() is None:
            process.kill()
    else:  # pragma: no cover - Windows is the primary deployment target
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
