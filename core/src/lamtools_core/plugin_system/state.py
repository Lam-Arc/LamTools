"""Enable/disable ledger for the redesigned plugin system.

user:“能装、能禁用、能卸载”+启停是用户意图，卸载不丢数据；账本坏了也不能
让整个插件列表消失，所以读失败一律退回默认值。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class PluginStateStore:
    """Persist per-plugin enablement in a small JSON file next to the data dir."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        plugins = raw.get("plugins")
        return plugins if isinstance(plugins, dict) else {}

    def _save(self, plugins: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"plugins": plugins}, ensure_ascii=False, indent=2)
        handle_fd, temp_path = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".plugins-", suffix=".tmp"
        )
        try:
            with os.fdopen(handle_fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload + "\n")
            os.replace(temp_path, self.path)
        except BaseException:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

    def is_enabled(self, name: str, *, default: bool = True) -> bool:
        entry = self._load().get(name)
        if isinstance(entry, dict) and isinstance(entry.get("enabled"), bool):
            return entry["enabled"]
        return default

    def set_enabled(self, name: str, enabled: bool) -> None:
        plugins = self._load()
        entry = plugins.get(name)
        entry = dict(entry) if isinstance(entry, dict) else {}
        entry["enabled"] = bool(enabled)
        plugins[name] = entry
        self._save(plugins)

    def forget(self, name: str) -> None:
        plugins = self._load()
        if name in plugins:
            del plugins[name]
            self._save(plugins)


__all__ = ["PluginStateStore"]
