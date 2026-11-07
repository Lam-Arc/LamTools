"""user:“给我把 2 阶段做完，前端除外”+(Office字节用真实LibreOffice和原Windows Job转换，退出后回收临时文件)。"""
import io
import math
import tempfile
import zipfile
import zlib
from pathlib import Path, PurePosixPath

from .process_access import ProcessAccessError


class OfficeAccessError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class PluginOfficeAPI:
    def __init__(self, context, scope):
        self._scope, self._processes = scope, context.processes
        self._active = 0

    def _executable(self):
        # user:“宿主能力补齐和接口完善与文档更新”+(使用既有office-renderer的LibreOffice命令及标准安装位置，不启动用户Office实例)。
        for command in (r"C:\Program Files\LibreOffice\program\soffice.com",
                        r"C:\Program Files (x86)\LibreOffice\program\soffice.com", "soffice.com", "soffice", "libreoffice"):
            try:
                return self._processes.resolve_executable(command)
            except ProcessAccessError as error:
                if error.code != "process/not-found":
                    raise
        raise OfficeAccessError("office/unavailable", "LibreOffice converter is not installed or discoverable")

    @staticmethod
    def _admit(content, extension, timeout):
        if (type(extension) is not str or extension not in {"docx", "xlsx", "pptx"}
                or type(content) is not bytes or not 0 < len(content) <= 16 * 1024 * 1024
                or type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 120):
            raise OfficeAccessError("office/invalid-input", "Use OOXML bytes up to 16 MiB, docx/xlsx/pptx and timeout within (0,120]")
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                rows = archive.infolist()
                names = [row.filename for row in rows]
                main = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}[extension]
                if (len(rows) > 2048 or len(names) != len(set(names)) or "[Content_Types].xml" not in names or main not in names
                        or sum(row.file_size for row in rows) > 64 * 1024 * 1024
                        or any(row.flag_bits & 1 or "\\" in row.filename or ":" in row.filename
                               or PurePosixPath(row.filename).is_absolute() or ".." in PurePosixPath(row.filename).parts
                               or row.filename.casefold().endswith("vbaproject.bin") for row in rows)):
                    raise ValueError
                if archive.testzip() is not None:
                    raise ValueError
        except (ValueError, OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, zlib.error):
            raise OfficeAccessError("office/invalid-document", "OOXML archive is invalid, encrypted, macro-bearing or exceeds admission limits") from None

    async def convert(self, content, *, extension, timeout=60):
        self._scope.acquire()
        admitted = False
        try:
            self._admit(content, extension, timeout)
            if self._active >= 2:
                raise OfficeAccessError("office/busy", "At most two conversions per plugin project view")
            executable = self._executable()
            self._active += 1
            admitted = True
            with tempfile.TemporaryDirectory(prefix="sunday-office-") as directory:
                root = Path(directory)
                source = root / ("source." + extension)
                source.write_bytes(content)
                output, profile = root / "output", root / "profile"
                output.mkdir()
                (profile / "user").mkdir(parents=True)
                (profile / "user" / "registrymodifications.xcu").write_text(
                    '<?xml version="1.0" encoding="UTF-8"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
                    '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
                    '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item></oor:items>', encoding="utf8")
                argv = [str(executable), "--headless", "--nologo", "--nodefault", "--nolockcheck",
                        "-env:UserInstallation=" + profile.as_uri(), "--convert-to", "pdf", "--outdir", str(output), str(source)]
                result, _ = await self._processes.run(argv, timeout=timeout, max_output_bytes=8192)
                self._scope.check_open()
                if result.status == "timed_out":
                    raise OfficeAccessError("office/timeout", "Office conversion exceeded its deadline")
                if result.status != "exited" or result.exit_code != 0 or not result.quiescent:
                    raise OfficeAccessError("office/failed", "Office converter did not finish successfully")
                pdf_path = output / "source.pdf"
                if not pdf_path.is_file() or not 0 < pdf_path.stat().st_size <= 32 * 1024 * 1024:
                    raise OfficeAccessError("office/invalid-output", "Converter did not produce a bounded PDF")
                data = pdf_path.read_bytes()
                if not data.startswith(b"%PDF-"):
                    raise OfficeAccessError("office/invalid-output", "Converter output is not a PDF")
                response = {"pdf": data, "bytes": len(data), "engine": "libreoffice-cli", "missing_fonts": None}
            return response
        except OSError:
            raise OfficeAccessError("office/io-failed", "Office scratch input/output or cleanup failed") from None
        finally:
            if admitted:
                self._active -= 1
            self._scope.release()
