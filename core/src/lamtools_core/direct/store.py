"""直调记录：一次调用（含批量里的每一条）的可回看状态。

记录落在 ``{data_dir}/direct_calls/<call_id>.json``，一个调用一个文件。
不建数据库表：直调历史是低频、按次读取的数据，文件式与项目现有的 jsonc
配置风格一致，也省掉一次 schema 迁移。

user:“实现，先读现在的模型配置与管理的代码，尽可能复用，如果代码与需求不匹配，咋考虑新增功能”
+(直调的历史与产物要能在重启后还在，所以每次状态变化都落盘，而不是只放内存。)
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_CALL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class DirectCallResult:
    """批量里的一条：一个提示词对应一个结果。"""

    index: int = 0
    prompt: str = ""
    status: str = "pending"  # pending | ok | error | cancelled
    text: str = ""
    files: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    # user:“该做的你都做一下 把它给打磨成熟”+(配了价格就报这一次的钱，没配就留空，不编数字。)
    cost: float | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DirectCallResult":
        return cls(
            index=int(data.get("index") or 0),
            prompt=str(data.get("prompt") or ""),
            status=str(data.get("status") or "pending"),
            text=str(data.get("text") or ""),
            files=[dict(item) for item in data.get("files") or [] if isinstance(item, dict)],
            error=str(data.get("error") or ""),
            usage=dict(data.get("usage") or {}),
            cost=float(data["cost"]) if isinstance(data.get("cost"), (int, float)) else None,
            duration_ms=int(data.get("duration_ms") or 0),
        )


@dataclass
class DirectCallRecord:
    """一次直接调用。批量时 ``prompts`` 有多条，``results`` 一一对应。"""

    id: str = ""
    model_record_id: str = ""
    model_id: str = ""
    display_name: str = ""
    provider_id: str = ""
    provider_name: str = ""
    output_type: str = "text"
    status: str = "queued"  # queued | running | completed | failed | cancelled
    prompts: list[str] = field(default_factory=list)
    system: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    results: list[DirectCallResult] = field(default_factory=list)
    error: str = ""
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    project_id: str = ""

    @property
    def finished(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["results"] = [item.to_dict() for item in self.results]
        data["finished"] = self.finished
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DirectCallRecord":
        return cls(
            id=str(data.get("id") or ""),
            model_record_id=str(data.get("model_record_id") or ""),
            model_id=str(data.get("model_id") or ""),
            display_name=str(data.get("display_name") or ""),
            provider_id=str(data.get("provider_id") or ""),
            provider_name=str(data.get("provider_name") or ""),
            output_type=str(data.get("output_type") or "text"),
            status=str(data.get("status") or "queued"),
            prompts=[str(item) for item in data.get("prompts") or []],
            system=str(data.get("system") or ""),
            params=dict(data.get("params") or {}),
            results=[
                DirectCallResult.from_dict(item)
                for item in data.get("results") or []
                if isinstance(item, dict)
            ],
            error=str(data.get("error") or ""),
            created_at=str(data.get("created_at") or ""),
            started_at=str(data.get("started_at") or ""),
            finished_at=str(data.get("finished_at") or ""),
            project_id=str(data.get("project_id") or ""),
        )


class DirectCallStore:
    """``<data_dir>/direct_calls`` 下的记录读写。"""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _path(self, call_id: str) -> Path:
        if not _CALL_ID_RE.match(call_id or ""):
            raise ValueError(f"invalid direct call id: {call_id!r}")
        return self.root / f"{call_id}.json"

    def save(self, record: DirectCallRecord) -> Path:
        from lamtools_core.config.root import atomic_write_text

        path = self._path(record.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
        return path

    def get(self, call_id: str) -> DirectCallRecord | None:
        try:
            path = self._path(call_id)
        except ValueError:
            return None
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return DirectCallRecord.from_dict(data) if isinstance(data, dict) else None

    def list(self, *, limit: int = 50, offset: int = 0, output_type: str = "", status: str = "") -> list[DirectCallRecord]:
        if not self.root.is_dir():
            return []
        records: list[DirectCallRecord] = []
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            record = DirectCallRecord.from_dict(data)
            if output_type and record.output_type != output_type:
                continue
            if status and record.status != status:
                continue
            records.append(record)
        records.sort(key=lambda item: (item.created_at, item.id), reverse=True)
        return records[max(0, offset): max(0, offset) + max(1, limit)]

    def delete(self, call_id: str) -> bool:
        try:
            path = self._path(call_id)
        except ValueError:
            return False
        if not path.is_file():
            return False
        path.unlink()
        return True

    def recover(self) -> int:
        """把上次进程留下的未完成记录标成中断，避免界面永远转圈。"""
        count = 0
        if not self.root.is_dir():
            return 0
        # 逐文件扫全量：走 list 的 limit 会把更早的 queued/running 记录漏在外面，
        # 界面就永远停在运行中。
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            record = DirectCallRecord.from_dict(data)
            if record.status in ("queued", "running"):
                record.status = "failed"
                record.error = "应用重启，任务已中断"
                record.finished_at = _now()
                self.save(record)
                count += 1
        return count


__all__ = [
    "DirectCallRecord",
    "DirectCallResult",
    "DirectCallStore",
    "TERMINAL_STATUSES",
]
