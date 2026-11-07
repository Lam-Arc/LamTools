"""user:“给我把 2 阶段做完，前端除外”+(实际Office到PDF转换、限额、临时文件和取消验收)。"""
import asyncio
import io
import tempfile
import sys
import zipfile
from pathlib import Path

import pytest

from .test_plugin_working_directory import env


def document(extension="docx"):
    text = "Sunday DSH Office conversion acceptance"
    if extension == "docx":
        from docx import Document
        doc = Document()
        doc.add_paragraph(text)
    elif extension == "xlsx":
        from openpyxl import Workbook
        doc = Workbook()
        doc.active["A1"] = text
    else:
        from pptx import Presentation
        from pptx.util import Inches
        doc = Presentation()
        slide = doc.slides.add_slide(doc.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1)).text = text
    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("extension", ["docx", "xlsx", "pptx"])
async def test_real_libreoffice_bytes_to_valid_pdf_and_scratch_cleanup(env, monkeypatch, extension):
    from pypdf import PdfReader
    ctx, _, _, root = env
    directories=[]
    create=tempfile.TemporaryDirectory
    def observe_directory(*args,**kwargs):
        value=create(*args,**kwargs)
        directories.append(Path(value.name))
        return value
    # user:“不要出错”+(使用真实系统临时根，记录实际scratch核对清理；不把长pytest路径强加给LibreOffice profile)。
    monkeypatch.setattr(tempfile,"TemporaryDirectory",observe_directory)
    original = document(extension)
    result = await ctx.office_to_pdf.convert(original, extension=extension, timeout=45)
    assert result["pdf"].startswith(b"%PDF-")
    reader = PdfReader(io.BytesIO(result["pdf"]))
    assert len(reader.pages) == 1
    assert "Sunday DSH" in reader.pages[0].extract_text()
    assert result["engine"] == "libreoffice-cli" and result["missing_fonts"] is None
    assert directories and all(not path.exists() for path in directories)
    assert document()[:2] == original[:2] == b"PK"


@pytest.mark.asyncio
async def test_invalid_office_admission_never_launches_converter(env, monkeypatch):
    from lamtools_core.plugin_system.office_access import OfficeAccessError
    ctx, _, _, _ = env
    api = ctx.office_to_pdf
    monkeypatch.setattr(api._processes, "run", lambda *a, **k: pytest.fail("Invalid input launched converter"))
    for content, ext, timeout in [(b"not a zip", "docx", 30), (b"", "exe", 30),
                                  (b"x" * (16 * 1024 * 1024 + 1), "docx", 30),
                                  (document(), "docx", float('nan'))]:
        with pytest.raises(OfficeAccessError):
            await api.convert(content, extension=ext, timeout=timeout)
    malformed = io.BytesIO()
    with zipfile.ZipFile(malformed, "w") as z:
        z.writestr("../escape", "x")
        z.writestr("[Content_Types].xml", "x")
    with pytest.raises(OfficeAccessError):
        await api.convert(malformed.getvalue(), extension="docx")


@pytest.mark.asyncio
async def test_converter_cancellation_removes_scratch_and_releases_admission(env, monkeypatch):
    ctx, _, _, root = env
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    api = ctx.office_to_pdf
    entered, cancelled = asyncio.Event(), asyncio.Event()
    async def wait(*a, **kw):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    monkeypatch.setattr(api._processes, "run", wait)
    task = asyncio.create_task(api.convert(document(), extension="docx"))
    await asyncio.wait_for(entered.wait(), 3)
    assert list(root.glob("sunday-office-*"))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set() and not list(root.glob("sunday-office-*"))
    assert api._active == 0


@pytest.mark.asyncio
async def test_missing_converter_is_explicit_and_old_facade_revoked(env, monkeypatch):
    from lamtools_core.plugin_system.office_access import OfficeAccessError
    from lamtools_core.plugin_system.services import ServiceError
    ctx, _, _, _ = env
    api = ctx.office_to_pdf
    def missing():
        raise OfficeAccessError("office/unavailable", "No converter")
    monkeypatch.setattr(api, "_executable", missing)
    with pytest.raises(OfficeAccessError, match="No converter"):
        await api.convert(document(), extension="docx")
    await ctx._registration_scope.dispose()
    with pytest.raises(ServiceError):
        await api.convert(document(), extension="docx")


@pytest.mark.asyncio
async def test_owned_converter_timeout_and_invalid_output_are_errors(env, monkeypatch):
    from lamtools_core.plugin_system.office_access import OfficeAccessError
    ctx, _, _, root = env
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    api = ctx.office_to_pdf
    original = api._processes.run
    outcomes = []
    async def hang(argv, **kwargs):
        result = await original([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        outcomes.append(result[0])
        return result
    monkeypatch.setattr(api._processes, "run", hang)
    with pytest.raises(OfficeAccessError) as error:
        await api.convert(document(), extension="docx", timeout=0.2)
    assert error.value.code == "office/timeout" and outcomes[0].quiescent
    assert not list(root.glob("sunday-office-*"))
    from types import SimpleNamespace
    async def no_pdf(*a, **kw):
        return SimpleNamespace(status="exited", exit_code=0, quiescent=True), None
    monkeypatch.setattr(api._processes, "run", no_pdf)
    with pytest.raises(OfficeAccessError) as error:
        await api.convert(document(), extension="docx")
    assert error.value.code == "office/invalid-output"
