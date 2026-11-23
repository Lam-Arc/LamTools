"""文档转 Markdown 并登记成资料库条目。

user:“转换（复用现有 document_normalize.py 的 docx/pdf/xlsx → Markdown，若接口可用）”+
(排版预览之外还需要一份能读、能搜、能改的文本：这里只做三件事——调用既有
归一化、把结果写进稳定的「转换/」目录、立刻登记成资料库条目。产物不散落在
目录里，卡片上就能看到它，也能被标签与评分。）

为什么单独成模块而不是塞进路由：转换是「一个文档 → 一个条目」的完整业务动作，
界面入口和将来的批量转换都要复用它；放在路由里就只能被 HTTP 调用。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from lamtools_core.tool.document_normalize import (
    DocumentNormalizationError,
    normalize_document,
)
from lamtools_core.tool.workspace_files import atomic_write_bytes

#: 转换产物的归档层，和资料库里的自由层名一致。
CONVERTED_FOLDER = "转换"
#: 一次转换最多带回多少字符；超出会提示被截断，而不是悄悄少半份文档。
DEFAULT_CONVERT_TEXT_BUDGET = 200_000
#: 能转换的格式就是归一化器支持的这三种；其余一律明确报错。
CONVERTIBLE_SUFFIXES = frozenset({".docx", ".pdf", ".xlsx"})


class DocumentConversionError(RuntimeError):
    """转换失败：消息直接给用户看，不需要调用方再翻译。"""


def _unique_target(directory: Path, stem: str) -> Path:
    """不覆盖已有产物：重名依次加 -1、-2。"""
    candidate = directory / f"{stem}.md"
    suffix = 1
    while candidate.exists():
        candidate = directory / f"{stem}-{suffix}.md"
        suffix += 1
    return candidate


async def convert_document_to_artifact(
    *,
    store: Any,
    project_id: str,
    work_root: str | Path,
    path: str | Path,
    folder: str = CONVERTED_FOLDER,
    max_text_length: int = DEFAULT_CONVERT_TEXT_BUDGET,
) -> Any:
    """把一份 Office/PDF 文档转成 Markdown，落盘并登记；返回条目记录。

    ``path`` 必须落在 ``work_root`` 之内——转换结果要写进项目，越界的源文件
    不是这个项目的东西。
    """
    root = Path(work_root).resolve()
    source = Path(path)
    if not source.is_absolute():
        source = root / source
    source = source.resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise DocumentConversionError("这个文件不在项目目录里，不能转换") from exc
    if not source.is_file():
        raise DocumentConversionError("原文件不存在")
    if source.suffix.lower() not in CONVERTIBLE_SUFFIXES:
        # pptx 的文本提取仍是缺口（只能做图片式预览），这里如实报错而不是产出半份东西。
        raise DocumentConversionError("这个文件没有可转换的文本（只支持 docx / pdf / xlsx）")

    # 归一化是同步的 CPU/磁盘活；放在后台事件循环里跑会把整条 RPC（包括停止按钮）
    # 一起冻住，所以交给线程，和 workspace_files 的扫描预算同一处理方式。
    try:
        normalized = await asyncio.to_thread(
            normalize_document, source, workspace_root=root, max_text_length=max_text_length
        )
    except DocumentNormalizationError as exc:
        raise DocumentConversionError(str(exc)) from exc
    except OSError as exc:
        raise DocumentConversionError(f"文件无法读取：{exc}") from exc
    if normalized is None:  # pragma: no cover - 后缀已在上面挡过
        raise DocumentConversionError("这个文件没有可转换的文本")

    directory = root / folder
    directory.mkdir(parents=True, exist_ok=True)
    target = _unique_target(directory, source.stem or "转换结果")
    atomic_write_bytes(target, normalized.markdown.encode("utf-8"))
    relative = target.relative_to(root).as_posix()

    try:
        record = await store.register(
            project_id=project_id,
            work_root=root,
            path=f"workspace://{relative}",
            kind="file",
            mime_type="text/markdown",
            name=target.name,
            source="converted",
            role="intermediate",
            provenance={
                "converted_from": source.as_posix(),
                "document_format": normalized.document_format,
                "warnings": list(normalized.warnings),
            },
        )
        return await store.set_folder(record.artifact_id, folder)
    except (LookupError, OSError, ValueError) as exc:
        raise DocumentConversionError(str(exc)) from exc


__all__ = [
    "CONVERTED_FOLDER",
    "CONVERTIBLE_SUFFIXES",
    "DEFAULT_CONVERT_TEXT_BUDGET",
    "DocumentConversionError",
    "convert_document_to_artifact",
]
