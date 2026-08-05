from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .models import HookDefinition, HookHandler, HookSource, PluginManifest
from .trust import HookTrustStore


SUPPORTED_HANDLER_TYPES = {"command", "http", "mcp", "prompt"}


def default_user_hooks_path() -> Path:
    # Green/portable mode: everything lives beside the app.
    home = os.environ.get("LAMTOOLS_HOME")
    if home:
        return Path(home) / "hooks.json"
    appdata = os.environ.get("APPDATA")
    root = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return root / "LamTools" / "hooks.json"


def default_project_hooks_path(project_root: Path | str) -> Path:
    return Path(project_root).resolve() / ".lamtools" / "hooks.json"


class HookRegistry:
    def __init__(
        self,
        *,
        project_root: Path | str | None = None,
        user_hooks_path: Path | str | None = None,
        plugins: list[PluginManifest] | None = None,
        trust_store: HookTrustStore | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve() if project_root else None
        self.user_hooks_path = Path(user_hooks_path).resolve() if user_hooks_path else default_user_hooks_path()
        self.plugins = list(plugins or [])
        self.trust_store = trust_store

    def load(self) -> list[HookDefinition]:
        hooks: list[HookDefinition] = []

        # 1. Unified config directory (user-modifiable after packaging)
        from lamtools_core.config.root import core_config_file

        hooks.extend(
            self._load_file(
                core_config_file("hooks.json"),
                source="user",
                source_name="config",
            )
        )

        # 2. Project hooks
        if self.project_root is not None:
            hooks.extend(
                self._load_file(
                    default_project_hooks_path(self.project_root),
                    source="project",
                    source_name="project",
                )
            )
        # 3. User hooks (legacy)
        hooks.extend(self._load_file(self.user_hooks_path, source="user", source_name="user"))
        for plugin in self.plugins:
            if not plugin.enabled:
                continue
            for path in plugin.hook_files:
                hooks.extend(self._load_file(path, source="plugin", source_name=plugin.name, plugin=plugin))
        return hooks

    def _load_file(
        self,
        path: Path,
        *,
        source: HookSource,
        source_name: str,
        plugin: PluginManifest | None = None,
    ) -> list[HookDefinition]:
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        hooks_section = raw.get("hooks", {}) if isinstance(raw, dict) else {}
        if not isinstance(hooks_section, dict):
            raise ValueError(f"hooks must be an object: {path}")
        loaded: list[HookDefinition] = []
        for event, groups in hooks_section.items():
            if not isinstance(groups, list):
                raise ValueError(f"hook event groups must be a list: {path}:{event}")
            for group_index, group in enumerate(groups):
                if not isinstance(group, dict):
                    raise ValueError(f"hook group must be an object: {path}:{event}:{group_index}")
                matcher = str(group.get("matcher") or "*")
                handlers = group.get("hooks", [])
                if not isinstance(handlers, list):
                    raise ValueError(f"hook handlers must be a list: {path}:{event}:{group_index}")
                for handler_index, raw_handler in enumerate(handlers):
                    handler = self._handler(raw_handler)
                    stable = {
                        "config_path": str(path),
                        "event": str(event),
                        "handler": handler.raw,
                        "matcher": matcher,
                        "plugin_name": plugin.name if plugin else "",
                        "source": source,
                        "source_name": source_name,
                    }
                    digest = hashlib.sha256(
                        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
                    ).hexdigest()
                    trusted = self.trust_store.is_trusted(digest) if self.trust_store else False
                    loaded.append(
                        HookDefinition(
                            id=f"{source}:{source_name}:{event}:{group_index}:{handler_index}:{digest[:12]}",
                            event=str(event),
                            matcher=matcher,
                            source=source,
                            source_name=source_name,
                            config_path=path,
                            plugin_name=plugin.name if plugin else "",
                            plugin_root=plugin.root if plugin else None,
                            handler=handler,
                            definition_hash=digest,
                            trusted=trusted,
                            status="trusted" if trusted else "pending_review",
                        )
                    )
        return loaded

    def _handler(self, raw: object) -> HookHandler:
        if not isinstance(raw, dict):
            raise ValueError("hook handler must be an object")
        handler_type = str(raw.get("type") or "command")
        if handler_type not in SUPPORTED_HANDLER_TYPES:
            raise ValueError(f"unsupported hook handler type: {handler_type}")
        return HookHandler(
            type=handler_type,  # type: ignore[arg-type]
            command=str(raw.get("command") or ""),
            url=str(raw.get("url") or ""),
            tool=str(raw.get("tool") or ""),
            prompt=str(raw.get("prompt") or ""),
            timeout=float(raw.get("timeout") or 10),
            required=bool(raw.get("required") or False),
            status_message=str(raw.get("statusMessage") or raw.get("status_message") or ""),
            raw=dict(raw),
        )
