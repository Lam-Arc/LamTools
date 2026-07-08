from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class HookTrustStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"trusted_hashes": []}
        data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {"trusted_hashes": []}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

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
