"""Hook declarations, trust ledger and the unified hook registry.

user:“钩子每轮重新加载”+用户/项目钩子文件与 v2 插件钩子声明汇成一张表，
信任判定只认哈希；坏文件跳过不连坐。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .capabilities import CapabilityAssembly
from .manifest import PluginManifest


HookSource = Literal["user", "project", "plugin", "managed"]
HookHandlerType = Literal["command", "http", "mcp", "prompt"]
HookDecisionKind = Literal["allow", "block"]

SUPPORTED_HANDLER_TYPES = {"command", "http", "mcp", "prompt"}


def default_user_hooks_path() -> Path:
    # Green/portable mode: everything lives beside the app.
    home = os.environ.get("LAMTOOLS_HOME")
    if home:
        return Path(home) / "hooks.json"
    if sys.platform.startswith("linux"):
        xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
        root = Path(xdg_config_home) if xdg_config_home else Path.home() / ".config"
        return root / "LamTools" / "hooks.json"
    appdata = os.environ.get("APPDATA")
    root = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return root / "LamTools" / "hooks.json"


def default_project_hooks_path(project_root: Path | str) -> Path:
    return Path(project_root).resolve() / ".lamtools" / "hooks.json"


@dataclass(frozen=True)
class HookHandler:
    type: HookHandlerType
    command: str = ""
    url: str = ""
    tool: str = ""
    prompt: str = ""
    timeout: float = 10.0
    required: bool = False
    status_message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookDefinition:
    id: str
    event: str
    matcher: str
    source: HookSource
    source_name: str
    config_path: Path
    plugin_name: str = ""
    plugin_root: Path | None = None
    handler: HookHandler = field(default_factory=lambda: HookHandler(type="command"))
    definition_hash: str = ""
    trusted: bool = False
    status: str = "pending_review"


@dataclass(frozen=True)
class HookEvent:
    event_name: str
    session_id: str = ""
    run_id: str = ""
    turn_id: str = ""
    cwd: str = ""
    project_root: str = ""
    plugin_name: str = ""
    plugin_root: str = ""
    plugin_data: str = ""
    transcript_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    # ── PostToolUse / PostToolUseFailure ─────────────────────
    tool_call_id: str = ""
    tool_result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    error_type: str = ""
    # ── UserPromptSubmit ─────────────────────────────────────
    user_message: str = ""
    # ── PermissionRequest ────────────────────────────────────
    permission_request: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookDecision:
    decision: HookDecisionKind = "allow"
    reason: str = ""
    additional_context: str = ""
    updated_input: dict[str, Any] | None = None
    permission_decision: str = ""
    permission_decision_reason: str = ""
    audit_events: list[dict[str, Any]] = field(default_factory=list)
    # ── PostToolUse 输出改写 ─────────────────────────────────
    updated_output: dict[str, Any] | None = None
    # ── 用户可见的状态消息 ──────────────────────────────────
    status_message: str = ""


class HookTrustStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"trusted_hashes": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            # 截断/损坏的信任账本不能把 hook_registry.load() 整条打断（审计
            # 共识）：降级成"没有信任项"。
            logging.getLogger(__name__).warning(
                "unreadable hook trust store: %s", self.path, exc_info=True
            )
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


def _load_jsonc(path: Path) -> dict[str, Any]:
    from .jsonc import load_jsonc_text

    data = load_jsonc_text(path)
    return data if isinstance(data, dict) else {}


class HookRegistry:
    """Load hooks from config / project / user files.

    Plugin-declared hooks come from the v2 manifest assembly instead
    (:func:`plugin_hook_definitions`); this registry only owns files.
    """

    def __init__(
        self,
        *,
        project_root: Path | str | None = None,
        user_hooks_path: Path | str | None = None,
        trust_store: HookTrustStore | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve() if project_root else None
        self.user_hooks_path = Path(user_hooks_path).resolve() if user_hooks_path else default_user_hooks_path()
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
        return hooks

    def _load_file(
        self,
        path: Path,
        *,
        source: HookSource,
        source_name: str,
    ) -> list[HookDefinition]:
        if not path.exists():
            return []
        try:
            # 随包 hooks.json 是带注释的 JSONC（"取消注释即可启用"），因此这里
            # 必须按 JSONC 解析——严格 json.loads 会让开箱配置永远加载不到任何
            # 钩子，而且只在日志里留一行 warning。
            raw = _load_jsonc(path)
        except (OSError, ValueError):
            # A corrupt or empty hooks file must never take the whole app down.
            logging.getLogger(__name__).warning("Skipping unreadable hooks file: %s", path)
            return []
        hooks_section = raw.get("hooks", {}) if isinstance(raw, dict) else {}
        if not isinstance(hooks_section, dict):
            # A structurally broken hooks file must never take the whole app down.
            logging.getLogger(__name__).warning(
                "Skipping hooks file with invalid 'hooks' section: %s", path
            )
            return []
        loaded: list[HookDefinition] = []
        for event, groups in hooks_section.items():
            if not isinstance(groups, list):
                logging.getLogger(__name__).warning(
                    "Skipping non-list hook groups: %s:%s", path, event
                )
                continue
            for group_index, group in enumerate(groups):
                if not isinstance(group, dict):
                    logging.getLogger(__name__).warning(
                        "Skipping non-object hook group: %s:%s:%s", path, event, group_index
                    )
                    continue
                matcher = str(group.get("matcher") or "*")
                handlers = group.get("hooks", [])
                if not isinstance(handlers, list):
                    logging.getLogger(__name__).warning(
                        "Skipping non-list hook handlers: %s:%s:%s", path, event, group_index
                    )
                    continue
                for handler_index, raw_handler in enumerate(handlers):
                    try:
                        handler = self._handler(raw_handler)
                    except ValueError:
                        logging.getLogger(__name__).warning(
                            "Skipping invalid hook handler: %s:%s:%s:%s",
                            path,
                            event,
                            group_index,
                            handler_index,
                        )
                        continue
                    stable = {
                        "config_path": str(path),
                        "event": str(event),
                        "handler": handler.raw,
                        "matcher": matcher,
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
        try:
            timeout = float(raw.get("timeout") or 10)
        except (TypeError, ValueError):
            timeout = 10.0
        return HookHandler(
            type=handler_type,  # type: ignore[arg-type]
            command=str(raw.get("command") or ""),
            url=str(raw.get("url") or ""),
            tool=str(raw.get("tool") or ""),
            prompt=str(raw.get("prompt") or ""),
            timeout=timeout,
            required=bool(raw.get("required") or False),
            status_message=str(raw.get("statusMessage") or raw.get("status_message") or ""),
            raw=dict(raw),
        )


def plugin_hook_definitions(
    manifests: list[PluginManifest],
    assembly: CapabilityAssembly | None = None,
) -> list[HookDefinition]:
    """Convert v2 plugin hook declarations into the engine's definitions.

    Enabled plugins' hook files are trusted by declaration: installing a
    plugin is an explicit act of trust, so plugin hooks never enter the
    per-hook pending-review flow.
    """
    from .capabilities import assemble_capabilities

    resolved = assembly if assembly is not None else assemble_capabilities(manifests)
    roots = {item.name: item.root for item in manifests}
    definitions: list[HookDefinition] = []
    for index, spec in enumerate(resolved.hooks):
        plugin_root = roots.get(spec.plugin)
        for handler_index, raw in enumerate(spec.handlers):
            try:
                timeout = float(raw.get("timeout") or 10)
            except (TypeError, ValueError):
                timeout = 10.0
            handler = HookHandler(
                type=str(raw.get("type") or "command"),  # type: ignore[arg-type]
                command=str(raw.get("command") or ""),
                url=str(raw.get("url") or ""),
                tool=str(raw.get("tool") or ""),
                prompt=str(raw.get("prompt") or ""),
                timeout=timeout,
                required=bool(raw.get("required") or False),
                status_message=str(raw.get("statusMessage") or raw.get("status_message") or ""),
                raw=dict(raw),
            )
            definitions.append(
                HookDefinition(
                    id=f"plugin:{spec.plugin}:{spec.event}:{index}:{handler_index}",
                    event=spec.event,
                    matcher=spec.matcher,
                    source="plugin",
                    source_name=spec.plugin,
                    config_path=(plugin_root or Path()) / "plugin.json",
                    plugin_name=spec.plugin,
                    plugin_root=plugin_root,
                    handler=handler,
                    definition_hash="",
                    trusted=True,
                    status="trusted",
                )
            )
    return definitions


def load_all_hooks(
    *,
    project_root: Path | str | None,
    trust_store: HookTrustStore | None = None,
    manifests: list[PluginManifest] | None = None,
    user_hooks_path: Path | str | None = None,
) -> list[HookDefinition]:
    """File hooks plus plugin-declared hooks in definition order."""
    hooks = HookRegistry(
        project_root=project_root,
        user_hooks_path=user_hooks_path,
        trust_store=trust_store,
    ).load()
    if manifests:
        hooks.extend(plugin_hook_definitions(manifests))
    return hooks


__all__ = [
    "HookDecision",
    "HookDefinition",
    "HookEvent",
    "HookHandler",
    "HookRegistry",
    "HookTrustStore",
    "SUPPORTED_HANDLER_TYPES",
    "default_project_hooks_path",
    "default_user_hooks_path",
    "load_all_hooks",
    "plugin_hook_definitions",
]
