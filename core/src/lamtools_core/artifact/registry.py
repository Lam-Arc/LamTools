"""Artifact registry: per-id JSON manifests under ``{work_root}/.lam/artifact/``.

每个 artifact 一个 manifest（``.lam/artifact/<id>.json``），记录类型、来源
（agent 生成 / 用户上传）、生成 prompt、父子引用（参考图 → 生成图）与软删
墓碑。删除只标记 ``deleted``，保留 manifest（id 不清理、父子关系引用保留）。

path 用协议区分产物位置：
- ``workspace://<相对 work_root 的 posix 路径>`` — work_root 内文件（如生图产物）
- ``attachment://<attachment_id>`` — 附件系统托管的上传文件
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKSPACE_PREFIX = "workspace://"
ATTACHMENT_PREFIX = "attachment://"

_DOCUMENT_MIME_HINTS = (
    "application/vnd.openxmlformats-officedocument",
    "application/msword",
    "application/vnd.ms-excel",
    "application/json",
    "text/",
    "application/octet-stream",
)


def kind_from_mime(mime_type: str) -> str:
    """Map a MIME type to the artifact kind used by the UI/panel."""
    mime = (mime_type or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    if mime.endswith("pdf") or mime == "application/pdf":
        return "pdf"
    if mime.startswith(_DOCUMENT_MIME_HINTS):
        return "document"
    return "file"


@dataclass
class ArtifactRecord:
    artifact_id: str
    kind: str
    mime_type: str
    name: str
    path: str
    source: str  # agent_generated | user_upload
    prompt: str = ""
    parent_ids: list[str] = field(default_factory=list)
    children_ids: list[str] = field(default_factory=list)
    created_at: str = ""
    deleted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactRecord":
        data = dict(data)
        artifact_id = str(data.pop("artifact_id", ""))
        return cls(
            artifact_id=artifact_id,
            kind=str(data.get("kind") or "file"),
            mime_type=str(data.get("mime_type") or ""),
            name=str(data.get("name") or ""),
            path=str(data.get("path") or ""),
            source=str(data.get("source") or "user_upload"),
            prompt=str(data.get("prompt") or ""),
            parent_ids=[str(i) for i in data.get("parent_ids") or []],
            children_ids=[str(i) for i in data.get("children_ids") or []],
            created_at=str(data.get("created_at") or ""),
            deleted=bool(data.get("deleted")),
        )


class ArtifactRegistry:
    """Filesystem-backed artifact registry rooted at ``{work_root}/.lam/artifact``."""

    def __init__(self, work_root: str | Path) -> None:
        self.work_root = Path(work_root).resolve()
        self.root = self.work_root / ".lam" / "artifact"
        self.root.mkdir(parents=True, exist_ok=True)

    # ── registration ────────────────────────────────────────────────────────

    def register(
        self,
        *,
        kind: str,
        mime_type: str,
        name: str,
        path: str,
        source: str,
        prompt: str = "",
        parent_ids: list[str] | None = None,
    ) -> ArtifactRecord:
        """Register a new artifact and link it into its parents' children lists."""
        artifact_id = uuid.uuid4().hex
        record = ArtifactRecord(
            artifact_id=artifact_id,
            kind=kind,
            mime_type=mime_type,
            name=name,
            path=path,
            source=source,
            prompt=prompt,
            parent_ids=[str(i) for i in parent_ids or []],
            created_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        )
        self._write(record)
        for parent_id in record.parent_ids:
            parent = self._read(parent_id)
            if parent is not None and artifact_id not in parent.children_ids:
                parent.children_ids.append(artifact_id)
                self._write(parent)
        return record

    def register_generated_images(
        self,
        *,
        prompt: str,
        files: list[tuple[str, int, str]],
        parent_ids: list[str] | None = None,
    ) -> list[str]:
        """Register generated images: files = [(mime, size_bytes, rel_path), ...].

        Returns the artifact ids (aligned with ``files`` order).
        """
        ids: list[str] = []
        for mime, _size, rel in files:
            record = self.register(
                kind="image",
                mime_type=mime,
                name=Path(rel).name,
                path=f"{WORKSPACE_PREFIX}{rel}",
                source="agent_generated",
                prompt=prompt,
                parent_ids=parent_ids,
            )
            ids.append(record.artifact_id)
        return ids

    # ── lookup / listing ────────────────────────────────────────────────────

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        return self._read(artifact_id)

    def list(self, include_deleted: bool = False) -> list[ArtifactRecord]:
        records: list[ArtifactRecord] = []
        for path in sorted(self.root.glob("*.json")):
            record = self._read(path.stem)
            if record is None:
                continue
            if not include_deleted and record.deleted:
                continue
            records.append(record)
        records.sort(key=lambda r: (r.created_at, r.artifact_id))
        return records

    def resolve_artifact_id(self, ref: str, work_root: str | Path | None = None) -> str | None:
        """Best-effort map of a reference (URL / relative path / workspace URI /
        attachment id) to a registered artifact id, or None."""
        ref = (ref or "").strip()
        if not ref:
            return None
        base = Path(work_root or self.work_root).resolve()
        # attachment://<id> — exact match against path
        if ref.startswith(ATTACHMENT_PREFIX):
            target_id = ref[len(ATTACHMENT_PREFIX):].strip()
            for record in self.list(include_deleted=True):
                if record.path == ref or record.path.endswith(target_id):
                    return record.artifact_id
            return None
        # workspace://rel or plain relative path → normalize to workspace URI
        if ref.startswith(WORKSPACE_PREFIX):
            rel = ref[len(WORKSPACE_PREFIX):]
        else:
            candidate = Path(ref)
            if candidate.is_absolute():
                try:
                    rel = candidate.resolve().relative_to(base).as_posix()
                except ValueError:
                    return None
            else:
                rel = candidate.as_posix()
        target_uri = f"{WORKSPACE_PREFIX}{rel}"
        for record in self.list(include_deleted=True):
            if record.path == target_uri:
                return record.artifact_id
        # http(s) URL references cannot be matched to local files.
        return None

    # ── deletion (soft) ─────────────────────────────────────────────────────

    def soft_delete(self, artifact_ids: list[str]) -> int:
        """Mark artifacts deleted; keep manifests (id 保留、父子引用保留)."""
        deleted = 0
        for artifact_id in artifact_ids:
            record = self._read(artifact_id)
            if record is None or record.deleted:
                continue
            record.deleted = True
            self._write(record)
            deleted += 1
        return deleted

    # ── internals ───────────────────────────────────────────────────────────

    def _manifest_path(self, artifact_id: str) -> Path:
        return self.root / f"{artifact_id}.json"

    def _read(self, artifact_id: str) -> ArtifactRecord | None:
        path = self._manifest_path(artifact_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        data.setdefault("artifact_id", artifact_id)
        return ArtifactRecord.from_dict(data)

    def _write(self, record: ArtifactRecord) -> None:
        path = self._manifest_path(record.artifact_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)


__all__ = [
    "ATTACHMENT_PREFIX",
    "WORKSPACE_PREFIX",
    "ArtifactRecord",
    "ArtifactRegistry",
    "kind_from_mime",
]
