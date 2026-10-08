"""SQLite-backed artifact facts for the project library.

成果只记录"当前是什么"：路径、类型、来源、角色与出处。内容就是磁盘上的
那个文件（或附件系统托管的上传原件），不再保留历史版本——改错了直接改回来，
项目自带的版本管理也在。
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

_logger = logging.getLogger(__name__)

from lamtools_core.app.core_db import (
    CoreArtifact,
    CoreArtifactAlias,
    CoreAttachment,
    CoreDbMetadata,
    CoreProject,
)
from lamtools_core.app.sqlite_write import SQLiteWriteCoordinator

from .registry import ATTACHMENT_PREFIX, WORKSPACE_PREFIX, ArtifactRecord, kind_from_mime

ELIGIBLE_OUTPUT_KINDS = {"file_change", "image"}
EXCLUDED_KINDS = {
    "command_output", "file_read", "web_fetch", "web_fetch_content",
    "web_search", "web_search_result", "test_evidence", "verification",
}

_MARKDOWN_LINK_PATH = re.compile(r"\[[^\]\r\n]*\]\(<?([^)>\r\n]+)>?\)")
_INLINE_CODE_PATH = re.compile(r"`([^`\r\n]+)`")
_WINDOWS_ABSOLUTE_PATH = re.compile(
    r"(?<![\w])([A-Za-z]:[\\/][^\r\n<>|?*\"]+?\.[A-Za-z0-9]{1,16})"
    r"(?=$|[\s)\]};,，。；])"
)
_LINE_SUFFIX = re.compile(r":\d+(?::\d+)?$")


class ArtifactStore:
    """Durable artifact registry sharing Core's runtime SQLite database."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        write_coordinator: SQLiteWriteCoordinator | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator or SQLiteWriteCoordinator(session_factory)

    async def migrate_legacy(self, *, project_id: str, work_root: str | Path) -> int:
        root = Path(work_root).resolve()
        marker_key = f"artifact_v2_legacy_migrated:{project_id}"
        async with self.session_factory() as db:
            if await db.get(CoreDbMetadata, marker_key) is not None:
                return 0
        manifest_root = root / ".lam" / "artifact"
        imported = 0
        for manifest in sorted(manifest_root.glob("*.json")) if manifest_root.is_dir() else []:
            try:
                raw = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(raw, dict):
                continue
            legacy = ArtifactRecord.from_dict({"artifact_id": manifest.stem, **raw})
            record = await self.register(
                project_id=project_id,
                work_root=root,
                path=legacy.path,
                kind=legacy.kind,
                mime_type=legacy.mime_type,
                name=legacy.name,
                source=legacy.source,
                role="input" if legacy.source == "user_upload" else "deliverable",
                prompt=legacy.prompt,
                parent_ids=legacy.parent_ids,
                preferred_id=legacy.artifact_id,
                deleted=legacy.deleted,
                provenance={"legacy_manifest": str(manifest)},
                reactivate=False,
            )
            await self.add_alias(legacy.artifact_id, record.artifact_id)
            imported += 1
        async def mark(db: Any) -> None:
            if await db.get(CoreDbMetadata, marker_key) is None:
                db.add(CoreDbMetadata(key=marker_key, value=datetime.now().isoformat(), updated_at=datetime.now()))
        await self.write_coordinator.run(mark)
        return imported

    async def register(
        self,
        *,
        project_id: str,
        work_root: str | Path,
        path: str,
        kind: str,
        mime_type: str = "",
        name: str = "",
        source: str = "agent_generated",
        role: str = "deliverable",
        prompt: str = "",
        parent_ids: list[str] | None = None,
        preferred_id: str = "",
        deleted: bool = False,
        provenance: dict[str, Any] | None = None,
        reactivate: bool = True,
    ) -> ArtifactRecord:
        """登记（或刷新）一份成果：只记"当前是什么"，内容就是路径上的文件。

        同一路径再次登记仍是同一条成果——刷新元信息，默认把软删状态复活；
        不保留任何历史版本。
        """
        root = Path(work_root).resolve()
        normalized, canonical_path, _local_path = _normalize_path(root, path)
        if not mime_type:
            mime_type = mimetypes.guess_type(name or canonical_path)[0] or ""
        now = datetime.now()
        provenance = dict(provenance or {})

        async def write(db: Any) -> ArtifactRecord:
            row = (await db.execute(select(CoreArtifact).where(
                CoreArtifact.project_id == project_id,
                CoreArtifact.normalized_path == normalized,
            ))).scalar_one_or_none()
            if row is None:
                row = CoreArtifact(
                    id=preferred_id or uuid.uuid4().hex,
                    project_id=project_id,
                    work_root=str(root),
                    normalized_path=normalized,
                    kind=kind_from_mime(mime_type) if kind == "file_change" else (kind or "file"),
                    mime_type=mime_type,
                    name=name or Path(canonical_path.removeprefix(WORKSPACE_PREFIX)).name,
                    path=canonical_path,
                    source=source,
                    role=role,
                    prompt=prompt,
                    parent_ids_json=list(parent_ids or []),
                    provenance_json=provenance,
                    deleted=deleted,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
                await db.flush()
            else:
                row.kind = kind_from_mime(mime_type) if kind == "file_change" else (kind or row.kind)
                row.mime_type = mime_type or row.mime_type
                row.name = name or row.name
                row.source = source or row.source
                row.role = role or row.role
                row.prompt = prompt or row.prompt
                if reactivate:
                    row.deleted = False
                row.updated_at = now
                if provenance:
                    row.provenance_json = {**dict(row.provenance_json or {}), **provenance}

            for parent_id in list(parent_ids or []):
                parent = await db.get(CoreArtifact, parent_id)
                if parent is not None and row.id not in list(parent.children_ids_json or []):
                    parent.children_ids_json = [*list(parent.children_ids_json or []), row.id]

            row.thread_id = str(provenance.get("thread_id") or row.thread_id or "")
            row.turn_id = str(provenance.get("turn_id") or row.turn_id or "")
            row.item_id = str(provenance.get("item_id") or row.item_id or "")
            row.tool_name = str(provenance.get("tool_name") or row.tool_name or "")
            await db.flush()
            return _artifact_record(row)

        return await self.write_coordinator.run(write)

    async def ingest_run_item(
        self,
        item: Any,
        *,
        project_id: str = "",
        work_root: str | Path,
    ) -> Any:
        item_kind = str(getattr(item, "kind", "") or "")
        if item_kind == "message":
            return await self._ingest_final_message_paths(
                item,
                project_id=project_id,
                work_root=work_root,
            )
        if item_kind != "tool_result":
            return item
        if not project_id:
            async with self.session_factory() as db:
                project = (await db.execute(select(CoreProject).where(
                    CoreProject.work_root == str(Path(work_root).resolve())
                ))).scalar_one_or_none()
                project_id = str(project.id) if project is not None else ""
        if not project_id:
            return item
        tool_name = str(getattr(item, "payload", {}).get("tool_name") or "")
        canonical: list[dict[str, Any]] = []
        for raw in list(getattr(item, "artifacts", []) or []):
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind") or "")
            if kind in EXCLUDED_KINDS or kind not in ELIGIBLE_OUTPUT_KINDS:
                canonical.append(raw)
                continue
            metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
            path = str(raw.get("uri") or raw.get("path") or metadata.get("path") or "")
            if not path:
                canonical.append(raw)
                continue
            if _workspace_candidate(Path(work_root).resolve(), path) is None:
                # An approved out-of-workspace file is not a project artifact:
                # the library only means something inside the project.  Keep the
                # tool's own entry (the file card still renders) instead of
                # failing the turn.
                _logger.info("[artifact] skipped out-of-workspace path %s", path)
                canonical.append(raw)
                continue
            record = await self.register(
                project_id=project_id,
                work_root=work_root,
                path=path,
                kind=kind,
                mime_type=str(metadata.get("mime_type") or ""),
                name=Path(path).name,
                source=str(raw.get("source") or "agent_generated"),
                role=str(raw.get("role") or metadata.get("role") or "deliverable"),
                prompt=str(metadata.get("prompt") or ""),
                parent_ids=[str(value) for value in (raw.get("parent_ids") or metadata.get("parent_ids") or [])],
                provenance={
                    "event_id": str(getattr(item, "event_id", "") or ""),
                    "thread_id": str(getattr(item, "thread_id", "") or ""),
                    "turn_id": str(getattr(item, "turn_id", "") or ""),
                    "item_id": str(getattr(item, "item_id", "") or ""),
                    "tool_name": tool_name,
                    "tool_metadata": metadata,
                },
            )
            projected = {k: v for k, v in raw.items() if k != "content"}
            historical_id = str(raw.get("artifact_id") or raw.get("id") or "")
            if historical_id and historical_id != record.artifact_id:
                await self.add_alias(historical_id, record.artifact_id)
            projected["artifact_id"] = record.artifact_id
            projected["path"] = record.path
            canonical.append(projected)
        item.artifacts = canonical
        return item

    async def _ingest_final_message_paths(
        self,
        item: Any,
        *,
        project_id: str,
        work_root: str | Path,
    ) -> Any:
        """Attach existing workspace files named in a completed agent answer.

        Tool artifacts remain the primary source of provenance. This fallback
        covers deliverables produced indirectly by shell commands, Office
        applications, or helper programs that cannot emit ToolArtifact data.
        """

        payload = getattr(item, "payload", {})
        metadata = getattr(item, "metadata", {})
        if (
            getattr(item, "status", "") != "completed"
            or not isinstance(payload, dict)
            or str(payload.get("type") or "") != "agentMessage"
            or payload.get("sub_agent_terminal") is True
            or (isinstance(metadata, dict) and isinstance(metadata.get("sub_agent"), dict))
        ):
            return item
        content = str(payload.get("content") or "").strip()
        if not content:
            return item

        root = Path(work_root).resolve()
        if not project_id:
            async with self.session_factory() as db:
                project = (await db.execute(select(CoreProject).where(
                    CoreProject.work_root == str(root)
                ))).scalar_one_or_none()
                project_id = str(project.id) if project is not None else ""
        if not project_id:
            return item

        canonical = list(getattr(item, "artifacts", []) or [])
        existing_paths = {
            str(raw.get("path") or raw.get("uri") or "")
            for raw in canonical
            if isinstance(raw, dict)
        }
        for candidate in _existing_workspace_paths(content, root):
            relative = candidate.relative_to(root).as_posix()
            workspace_path = f"{WORKSPACE_PREFIX}{relative}"
            if relative in existing_paths or workspace_path in existing_paths:
                continue
            mime_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            record = await self.register(
                project_id=project_id,
                work_root=root,
                path=relative,
                kind="file_change",
                mime_type=mime_type,
                name=candidate.name,
                source="agent_generated",
                role="deliverable",
                provenance={
                    "event_id": str(getattr(item, "event_id", "") or ""),
                    "thread_id": str(getattr(item, "thread_id", "") or ""),
                    "turn_id": str(getattr(item, "turn_id", "") or ""),
                    "item_id": str(getattr(item, "item_id", "") or ""),
                    "tool_name": "agent_final_response",
                    "discovered_from": "final_response_path",
                },
            )
            canonical.append({
                "artifact_id": record.artifact_id,
                "kind": "file_change",
                "name": record.name,
                "path": record.path,
                "uri": relative,
                "mime_type": record.mime_type,
                "role": "deliverable",
                "source": "agent_generated",
                "metadata": {
                    "mime_type": record.mime_type,
                    "role": "deliverable",
                    "path": record.path,
                    "discovered_from": "final_response_path",
                },
            })
            existing_paths.update({relative, workspace_path})
        item.artifacts = canonical
        return item

    async def get(self, artifact_id_or_alias: str) -> ArtifactRecord | None:
        async with self.session_factory() as db:
            row = await db.get(CoreArtifact, artifact_id_or_alias)
            if row is None:
                alias = await db.get(CoreArtifactAlias, artifact_id_or_alias)
                row = await db.get(CoreArtifact, alias.artifact_id) if alias is not None else None
            return _artifact_record(row) if row is not None else None

    async def list(self, project_id: str, *, include_deleted: bool = False) -> list[ArtifactRecord]:
        async with self.session_factory() as db:
            query = select(CoreArtifact).where(CoreArtifact.project_id == project_id)
            if not include_deleted:
                query = query.where(CoreArtifact.deleted.is_(False))
            rows = list((await db.execute(query.order_by(CoreArtifact.created_at, CoreArtifact.id))).scalars())
            return [_artifact_record(row) for row in rows]

    async def resolve_project_id(self, work_root: str | Path) -> str:
        """按工作根定位项目；当前运行时没有对应项目就返回空串。"""
        async with self.session_factory() as db:
            project = (await db.execute(select(CoreProject).where(
                CoreProject.work_root == str(Path(work_root).resolve())
            ))).scalar_one_or_none()
            return str(project.id) if project is not None else ""

    async def content_path(self, artifact_id: str) -> Path | None:
        """成果当前内容的落点；文件不在了就返回 ``None``。"""
        record = await self.get(artifact_id)
        if record is None:
            return None
        return await self.current_content_path(record)

    async def current_content_path(self, record: ArtifactRecord) -> Path | None:
        """把成果的路径解析到磁盘上的当前文件（工作区文件或上传原件）。"""
        path = str(record.path or "")
        if path.startswith(ATTACHMENT_PREFIX):
            attachment_id = path[len(ATTACHMENT_PREFIX):].strip()
            async with self.session_factory() as db:
                row = await db.get(CoreAttachment, attachment_id)
            if row is None:
                return None
            candidate = Path(row.storage_path)
        elif path.startswith(WORKSPACE_PREFIX):
            relative = path[len(WORKSPACE_PREFIX):]
            try:
                candidate = _safe_workspace_path(Path(record.work_root), relative)
            except ValueError:
                return None
        else:
            return None
        return candidate if candidate.is_file() else None

    async def set_favorite(self, artifact_id: str, favorite: bool) -> ArtifactRecord:
        """资料库里的收藏标记；只改这一个字段，不动 updated_at（整理不等于修改）。"""
        async def write(db: Any) -> ArtifactRecord:
            row = await db.get(CoreArtifact, artifact_id)
            if row is None:
                raise LookupError(f"Artifact not found: {artifact_id}")
            row.favorite = bool(favorite)
            return _artifact_record(row)
        return await self.write_coordinator.run(write)

    async def set_folder(self, artifact_id: str, folder: str) -> ArtifactRecord:
        """把一个成果归到资料库的某一层（空串 = 取消归档）。"""
        cleaned = _clean_artifact_folder(folder)
        async def write(db: Any) -> ArtifactRecord:
            row = await db.get(CoreArtifact, artifact_id)
            if row is None:
                raise LookupError(f"Artifact not found: {artifact_id}")
            row.folder = cleaned
            return _artifact_record(row)
        return await self.write_coordinator.run(write)

    async def upload(
        self,
        *,
        project_id: str,
        work_root: str | Path,
        name: str,
        content: bytes,
        mime_type: str = "",
        folder: str = "",
        role: str = "input",
    ) -> ArtifactRecord:
        """用户从资料库放进来的文件。

        落在「资料/」下（真实文件，助手能直接读，和方案同一套语义），并登记成
        一份 source=user_upload 的成果；重名自动改名，不覆盖既有文件。
        """
        root = Path(work_root).resolve()
        safe_name = _safe_upload_name(name)
        cleaned = _clean_artifact_folder(folder)
        prefix = f"{UPLOAD_DIRNAME}/{cleaned}/" if cleaned else f"{UPLOAD_DIRNAME}/"
        target = _unique_workspace_path(root, f"{prefix}{safe_name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        relative = target.relative_to(root).as_posix()
        record = await self.register(
            project_id=project_id,
            work_root=root,
            path=f"{WORKSPACE_PREFIX}{relative}",
            kind=kind_from_mime(mime_type or safe_name),
            mime_type=mime_type,
            name=target.name,
            source="user_upload",
            role=role,
        )
        return await self.set_folder(record.artifact_id, cleaned) if cleaned else record

    async def stats(self, project_id: str) -> dict[str, int]:
        """资料库的占用：成果条数，以及各成果当前文件的字节合计。"""
        records = await self.list(project_id)
        total = 0
        for record in records:
            path = await self.current_content_path(record)
            if path is None:
                continue
            # 带路径的成果按磁盘上的当前文件计；上传原件按附件登记的大小计。
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return {"count": len(records), "bytes": int(total)}

    async def soft_remove(
        self,
        artifact_ids: list[str],
        *,
        deleted: bool = True,
        project_id: str = "",
    ) -> int:
        async def write(db: Any) -> int:
            changed = 0
            for artifact_id in artifact_ids:
                row = await db.get(CoreArtifact, artifact_id)
                if row is None:
                    alias = await db.get(CoreArtifactAlias, artifact_id)
                    row = await db.get(CoreArtifact, alias.artifact_id) if alias is not None else None
                if (
                    row is not None
                    and (not project_id or row.project_id == project_id)
                    and bool(row.deleted) != deleted
                ):
                    row.deleted = deleted
                    row.updated_at = datetime.now()
                    changed += 1
            return changed
        return await self.write_coordinator.run(write)

    async def add_alias(self, alias: str, artifact_id: str) -> None:
        if not alias:
            return
        async def write(db: Any) -> None:
            if await db.get(CoreArtifactAlias, alias) is None:
                db.add(CoreArtifactAlias(alias=alias, artifact_id=artifact_id))
        await self.write_coordinator.run(write)


def _workspace_candidate(work_root: Path, value: str) -> Path | None:
    """Resolve a stored path against the project root, or ``None`` when it lands outside.

    Tool results name files relative to the workspace, but for a file the
    operator allowed outside it (``relative_workspace_uri`` falls back to an
    absolute path) the name is absolute.  Artifact records only mean something
    inside the project, so callers that ingest run items skip those instead
    of failing the turn that produced them.
    """

    rel = str(value or "").strip().removeprefix(WORKSPACE_PREFIX).replace("\\", "/")
    if not rel:
        return None
    candidate = Path(rel)
    if candidate.is_absolute():
        candidate = candidate.resolve()
    else:
        candidate = (work_root / candidate).resolve()
    try:
        candidate.relative_to(work_root)
    except ValueError:
        return None
    return candidate


def _normalize_path(work_root: Path, value: str) -> tuple[str, str, Path | None]:
    raw = str(value or "").strip()
    if raw.startswith(ATTACHMENT_PREFIX):
        attachment_id = raw.removeprefix(ATTACHMENT_PREFIX).strip()
        return f"attachment:{attachment_id}", f"{ATTACHMENT_PREFIX}{attachment_id}", None
    candidate = _workspace_candidate(work_root, raw)
    if candidate is None:
        raise ValueError("Artifact path escapes project")
    normalized_rel = candidate.relative_to(work_root).as_posix()
    return f"workspace:{normalized_rel.casefold()}", f"{WORKSPACE_PREFIX}{normalized_rel}", candidate


def _safe_workspace_path(root: Path, relative: str) -> Path:
    candidate = (root.resolve() / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("Artifact path escapes project") from exc
    return candidate


#: 用户从资料库放进来的文件所在目录（项目根下，和「方案/」同一层语义）。
UPLOAD_DIRNAME = "资料"


def _clean_artifact_folder(value: str) -> str:
    """资料库的归档层级：相对路径，逐段校验，拒绝越界。"""
    raw = str(value or "").strip().replace("\\", "/").strip("/")
    if not raw:
        return ""
    segments = [segment.strip() for segment in raw.split("/") if segment.strip()]
    if any(segment in {".", ".."} for segment in segments):
        raise ValueError("folder must not contain '..'")
    return "/".join(segments)


def _safe_upload_name(value: str) -> str:
    name = Path(str(value or "").strip()).name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("upload name is required")
    return name


def _unique_workspace_path(root: Path, relative: str) -> Path:
    """重名就加序号（name (2).ext），绝不覆盖既有文件。"""
    candidate = _safe_workspace_path(root, relative)
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for index in range(2, 1000):
        candidate = _safe_workspace_path(root, f"{candidate.parent.relative_to(root).as_posix()}/{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError("too many files with the same name")


def _artifact_record(row: CoreArtifact) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=row.id,
        kind=row.kind,
        mime_type=row.mime_type,
        name=row.name,
        path=row.path,
        source=row.source,
        prompt=row.prompt,
        parent_ids=list(row.parent_ids_json or []),
        children_ids=list(row.children_ids_json or []),
        created_at=row.created_at.isoformat(),
        deleted=bool(row.deleted),
        role=row.role,
        project_id=row.project_id,
        work_root=row.work_root,
        thread_id=row.thread_id,
        turn_id=row.turn_id,
        item_id=row.item_id,
        tool_name=row.tool_name,
        provenance=dict(row.provenance_json or {}),
        availability="available" if _content_exists(row) else "missing",
        favorite=bool(row.favorite),
        folder=row.folder or "",
        updated_at=row.updated_at.isoformat() if row.updated_at else row.created_at.isoformat(),
    )


def _content_exists(row: CoreArtifact) -> bool:
    """工作区成果看文件在不在；附件与别的形态交给读取时判定。"""
    path = str(row.path or "")
    if not path.startswith(WORKSPACE_PREFIX):
        return True
    try:
        return _safe_workspace_path(Path(row.work_root), path[len(WORKSPACE_PREFIX):]).is_file()
    except (OSError, ValueError):
        return False


__all__ = ["ArtifactStore", "ELIGIBLE_OUTPUT_KINDS", "EXCLUDED_KINDS"]


def _existing_workspace_paths(content: str, root: Path) -> list[Path]:
    """Return de-duplicated regular files explicitly named by an agent."""

    raw_candidates = [
        *(match.group(1) for match in _MARKDOWN_LINK_PATH.finditer(content)),
        *(match.group(1) for match in _INLINE_CODE_PATH.finditer(content)),
        *(match.group(1) for match in _WINDOWS_ABSOLUTE_PATH.finditer(content)),
    ]
    resolved: list[Path] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        value = str(raw).strip().strip("<>\"'").rstrip(".,;，。；")
        if not value or value.startswith(("http://", "https://", "data:", "attachment://")):
            continue
        if value.startswith(WORKSPACE_PREFIX):
            value = value.removeprefix(WORKSPACE_PREFIX)
        value = value.replace("%20", " ")
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        if not candidate.is_file() and _LINE_SUFFIX.search(str(candidate)):
            candidate = Path(_LINE_SUFFIX.sub("", str(candidate))).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        resolved.append(candidate)
    return resolved
