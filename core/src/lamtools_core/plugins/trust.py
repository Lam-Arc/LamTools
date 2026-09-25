from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any


class HookTrustStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"trusted_hashes": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            # 截断/损坏的信任账本曾经会把 hook_registry.load() 整条打断，
            # 进而让 Agent 装配失败（2026-09-25 审计 P3）：降级成"没有信任项"。
            logging.getLogger(__name__).warning("unreadable hook trust store: %s", self.path, exc_info=True)
            return {"trusted_hashes": []}
        return data if isinstance(data, dict) else {"trusted_hashes": []}

    def _save(self, data: dict[str, Any]) -> None:
        from lamtools_core.config.root import atomic_write_text

        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, indent=2) + chr(10))

    def trusted_hashes(self) -> set[str]:
        values = self._load().get("trusted_hashes", [])
        if not isinstance(values, list):
            return set()
        return {str(item) for item in values if str(item).strip()}

    def is_trusted(self, value: str) -> bool:
        return str(value or "") in self.trusted_hashes()

    def trust(self, value: str) -> None:
        digest = str(value or "").strip()
        if not digest:
            return
        hashes = self.trusted_hashes()
        hashes.add(digest)
        self._save({"trusted_hashes": sorted(hashes)})

    def untrust(self, value: str) -> None:
        hashes = self.trusted_hashes()
        hashes.discard(str(value or "").strip())
        self._save({"trusted_hashes": sorted(hashes)})
