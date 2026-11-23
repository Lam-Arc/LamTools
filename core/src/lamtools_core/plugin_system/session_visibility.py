"""Generic visibility gate for sessions owned by plugins.

user:“study/workflow 会话被误判禁用”+可见性必须读唯一账本（PluginHost），
每次查询重新读取，开关插件在下一次查询生效。
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
        return self.snapshot()(session_id, metadata)

    def snapshot(self) -> SessionVisibility:
        plugins = self._host.discover()
        enabled = {plugin.name for plugin in plugins if plugin.enabled}
        legacy = tuple(
            (prefix, plugin.enabled)
            for plugin in plugins
            for prefix in _legacy_prefixes(plugin.raw)
        )

        def visible(session_id: str, metadata: dict[str, Any]) -> bool:
            owner = str(metadata.get("owner_plugin") or "").strip()
            if owner:
                return owner in enabled
            # Legacy resources identify their owner by a manifest prefix.
            session_id = str(session_id)
            for prefix, plugin_enabled in legacy:
                if session_id.startswith(prefix):
                    return plugin_enabled
            return True

        return visible


def _visible_without_plugin_owner(_session_id: str, metadata: dict[str, Any]) -> bool:
    return not bool(str(metadata.get("owner_plugin") or "").strip())


def session_visibility_for_batch(visibility: SessionVisibility) -> SessionVisibility:
    # user:“优化”+(批量查询只扫描一次插件目录，下一次查询重新读取插件状态)。
    snapshot = visibility.snapshot if isinstance(visibility, PluginSessionVisibility) else None
    resolver = visibility

    def visible(session_id: str, metadata: dict[str, Any]) -> bool:
        nonlocal resolver, snapshot
        if snapshot is not None:
            try:
                resolver = snapshot()
            except Exception:  # Keep an unavailable owner gate closed for this batch.
                resolver = _visible_without_plugin_owner
            snapshot = None
        try:
            return bool(resolver(session_id, metadata))
        except Exception:
            return _visible_without_plugin_owner(session_id, metadata)

    return visible


def _legacy_prefixes(raw: dict[str, Any]) -> list[str]:
    session = raw.get("session") if isinstance(raw.get("session"), dict) else {}
    prefixes = session.get("legacyPrefixes") if isinstance(session.get("legacyPrefixes"), list) else []
    return [str(item) for item in prefixes if isinstance(item, str) and str(item)]


__all__ = ["PluginSessionVisibility", "SessionVisibility", "session_visibility_for_batch"]
