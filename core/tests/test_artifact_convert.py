"""资料库条目上的「转换」：docx/pdf/xlsx → Markdown，且产物必须成为条目。

对应 Easy Tools 第一批的第三件事。断言落在磁盘与库上（不经过 UI）：
产物写在「转换/」这一层、原文件不会被覆盖、产物带来源信息、以及失败时给出
能看懂的错误而不是静默无反应。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.artifact.convert import (
    CONVERTED_FOLDER,
    DocumentConversionError,
    convert_document_to_artifact,
)


async def _make_project(tmp_path: Path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    db = await open_core_app_db(tmp_path / "core.db")
    project, _ = await db.project_store.create(work_root)
    return db, project, work_root


def _write_docx(path: Path, text: str) -> None:
    from docx import Document

    document = Document()
    document.add_paragraph(text)
    document.save(str(path))


@pytest.mark.asyncio
async def test_conversion_writes_markdown_into_the_library_and_registers_it(tmp_path: Path) -> None:
    # user:“转换产物要注册为 Library 条目…不要散落在目录里”+(产物必须能被卡片看到)。
    db, project, work_root = await _make_project(tmp_path)
    try:
        source = work_root / "说明.docx"
        _write_docx(source, "这是转换后的正文")

        record = await convert_document_to_artifact(
            store=db.artifact_store,
            project_id=project.id,
            work_root=work_root,
            path=source,
        )

        # 产物落在「转换/」这一层，扩展名是 Markdown。
        assert record.folder == CONVERTED_FOLDER
        assert record.name == "说明.md"
        produced = work_root / CONVERTED_FOLDER / "说明.md"
        assert produced.is_file()
        assert "这是转换后的正文" in produced.read_text(encoding="utf-8")
        # 原文件没有被改写。
        assert source.is_file()

        # 它真的在资料库里，且带得回来源。
        listed = await db.artifact_store.list(project.id)
        assert any(item.artifact_id == record.artifact_id for item in listed)
        assert record.source == "converted"
        provenance = dict(record.provenance or {})
        assert provenance.get("converted_from", "").endswith("说明.docx")
        assert provenance.get("document_format") == "docx"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_a_second_conversion_does_not_overwrite_the_first(tmp_path: Path) -> None:
    db, project, work_root = await _make_project(tmp_path)
    try:
        source = work_root / "重复.docx"
        _write_docx(source, "第一份")

        first = await convert_document_to_artifact(
            store=db.artifact_store, project_id=project.id, work_root=work_root, path=source,
        )
        second = await convert_document_to_artifact(
            store=db.artifact_store, project_id=project.id, work_root=work_root, path=source,
        )

        assert first.name == "重复.md"
        assert second.name == "重复-1.md"
        assert (work_root / CONVERTED_FOLDER / "重复.md").is_file()
        assert (work_root / CONVERTED_FOLDER / "重复-1.md").is_file()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_an_unsupported_format_explains_itself_instead_of_doing_nothing(tmp_path: Path) -> None:
    # user:“失败要有明确错误，不允许点了没反应”+(错在哪种格式、能转哪些，都说清楚)。
    db, project, work_root = await _make_project(tmp_path)
    try:
        source = work_root / "deck.pptx"
        source.write_bytes(b"not really a deck")

        with pytest.raises(DocumentConversionError) as failure:
            await convert_document_to_artifact(
                store=db.artifact_store, project_id=project.id, work_root=work_root, path=source,
            )
        assert "docx / pdf / xlsx" in str(failure.value)
        # 失败不留半份产物。
        assert not (work_root / CONVERTED_FOLDER / "deck.md").exists()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_a_missing_source_is_reported_clearly(tmp_path: Path) -> None:
    db, project, work_root = await _make_project(tmp_path)
    try:
        with pytest.raises(DocumentConversionError) as failure:
            await convert_document_to_artifact(
                store=db.artifact_store,
                project_id=project.id,
                work_root=work_root,
                path=work_root / "没有这个.docx",
            )
        assert "原文件不存在" in str(failure.value)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_a_file_outside_the_project_is_refused(tmp_path: Path) -> None:
    # 转换产物要写进项目；越界的源文件不属于这个项目。
    db, project, work_root = await _make_project(tmp_path)
    try:
        outside = tmp_path / "外部.docx"
        _write_docx(outside, "项目外的内容")

        with pytest.raises(DocumentConversionError) as failure:
            await convert_document_to_artifact(
                store=db.artifact_store, project_id=project.id, work_root=work_root, path=outside,
            )
        assert "不在项目目录里" in str(failure.value)
    finally:
        await db.close()
