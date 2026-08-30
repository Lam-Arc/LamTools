"""Generic visibility gate for sessions owned by plugins.

Core sessions may be resources of an optional plugin.  When that plugin is
disabled (or no longer installed), the host must not materialize the resource
as an ordinary chat session: its runtime/UI contract is unavailable.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .registry import PluginRegistry, PluginStateStore


SessionVisibility = Callable[[str, dict[str, Any]], bool]


class PluginSessionVisibility:
    """Dynamically decide whether a plugin-owned session may be read.

    The registry is intentionally discovered for each decision.  Plugin
    enable/disable operations update the state file live, so a long-lived
    session store must not retain an outdated enabled-plugin snapshot.
    """

    def __init__(
        self,
        *,
        plugin_roots: list[Path | str],
        state_store: PluginStateStore,
    ) -> None:
        self._plugin_roots = [Path(item) for item in plugin_roots]
        self._state_store = state_store

    def __call__(self, session_id: str, metadata: dict[str, Any]) -> bool:
        owner = str(metadata.get("owner_plugin") or "").strip()
        registry = PluginRegistry(
            plugin_roots=self._plugin_roots,
            state_store=self._state_store,
        )
        plugins = registry.discover()
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
