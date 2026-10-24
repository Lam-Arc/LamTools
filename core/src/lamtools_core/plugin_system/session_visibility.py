"""Generic visibility gate for sessions owned by plugins.

user:“study/workflow 会话被误判禁用”+可见性必须读唯一账本（PluginHost），
不再经过旧 v1 注册表；每判一次都重新发现，开关插件立刻生效。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .host import PluginHost


SessionVisibility = Callable[[str, dict[str, Any]], bool]


class PluginSessionVisibility:
    """Dynamically decide whether a plugin-owned session may be read."""

    def __init__(self, *, host: PluginHost) -> None:
        self._host = host

    def __call__(self, session_id: str, metadata: dict[str, Any]) -> bool:
        owner = str(metadata.get("owner_plugin") or "").strip()
        plugins = self._host.discover()
        if owner:
            return any(
                plugin.name == owner and plugin.enabled
                for plugin in plugins
            )

        # Pre-plugin resource sessions did not have owner metadata. Plugins
        # may declare their historical identifiers in the same manifest that
        # owns their runtime, allowing Core to keep compatibility without
        # knowing any plugin-specific prefix.
        for plugin in plugins:
            if any(str(session_id).startswith(prefix) for prefix in _legacy_prefixes(plugin.raw)):
                return plugin.enabled
        return True


def _legacy_prefixes(raw: dict[str, Any]) -> list[str]:
    session = raw.get("session") if isinstance(raw.get("session"), dict) else {}
    prefixes = session.get("legacyPrefixes") if isinstance(session.get("legacyPrefixes"), list) else []
    return [str(item) for item in prefixes if isinstance(item, str) and str(item)]


__all__ = ["PluginSessionVisibility", "SessionVisibility"]
