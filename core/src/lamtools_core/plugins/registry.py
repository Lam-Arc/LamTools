from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from ._jsonc import load_jsonc_text
from .models import (
    PluginCLIArgument,
    PluginCLICommand,
    PluginCLIContribution,
    PluginComposerCommand,
    PluginManifest,
    PluginSidebarWidget,
    PluginUIContribution,
    PluginUIMode,
    PluginUIView,
    PluginWidgetAction,
)

_logger = logging.getLogger(__name__)

# 当前支持的 manifest 版本（未来适配器时代扩展时递增校验）
SUPPORTED_MANIFEST_VERSION = "1"

# manifest 键 → PluginManifest 字段（新增工具/依赖/配置字段）
MANIFEST_DEPENDENCIES_KEY = "dependencies"
MANIFEST_TOOLS_KEY = "tools"
MANIFEST_OPERATIONS_KEY = "operations"
MANIFEST_CONFIG_SCHEMA_KEY = "configSchema"
MANIFEST_DESKTOP_KEY = "desktop"
MANIFEST_UI_KEY = "ui"
MANIFEST_CLI_KEY = "cli"
MANIFEST_COMMANDS_KEY = "commands"
MANIFEST_SKILL_MODES_KEY = "skillModes"
DEFAULT_DESKTOP_CARD_WIDTH = 376
DEFAULT_DESKTOP_CARD_HEIGHT = 360


def _appdata_root() -> Path:
    # Green/portable mode: everything lives beside the app.
    home = os.environ.get("LAMTOOLS_HOME")
    if home:
        return Path(home)
    raw = os.environ.get("APPDATA")
    if raw:
        return Path(raw)
    return Path.home() / "AppData" / "Roaming"


def default_user_plugin_root() -> Path:
    # Green/portable mode: beside the app (no LamTools nesting).
    if os.environ.get("LAMTOOLS_HOME"):
        from lamtools_core.config.root import lam_home
        return lam_home() / "plugins"
    return _appdata_root() / "LamTools" / "plugins"


def default_project_plugin_root(project_root: Path | str) -> Path:
    return Path(project_root).resolve() / ".lamtools" / "plugins"


def bundled_plugins_dir() -> Path:
    """内置插件根（git/websearch/imagegen，D3 共识：包内只读资源）。

    dev 指向源码包内 ``plugins/bundled``；frozen（PyInstaller）从
    ``_MEIPASS/resources/plugins/bundled`` 读（hatch force-include 目标，
    照抄 live_operations._bundled_config_resources_dir 双分支模式）。
    """
    import sys

    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return meipass / "resources" / "plugins" / "bundled"
    return Path(__file__).resolve().parent / "bundled"


class PluginStateStore:
    """插件启停状态 + 安装记录，持久化于 ``{data_dir}/plugins.jsonc``。

    迁移（F1 共识）：历史 ``plugins.json`` 仍可读——jsonc 文件不存在时
    回退读旧 json 并立即写一份 jsonc，旧文件保留（不删除，避免误伤
    用户数据）。
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _legacy_json_path(self) -> Path:
        if self.path.suffix == ".jsonc":
            return self.path.with_suffix(".json")
        return self.path

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                data = load_jsonc_text(self.path)
            except (OSError, ValueError, json.JSONDecodeError):
                _logger.warning(
                    "[plugins:state] unreadable %s, treating as empty",
                    self.path,
                    exc_info=True,
                )
                return {"plugins": {}}
            return data if isinstance(data, dict) else {"plugins": {}}
        legacy = self._legacy_json_path()
        if legacy.exists():
            try:
                data = json.loads(legacy.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                return {"plugins": {}}
            if not isinstance(data, dict):
                return {"plugins": {}}
            # 首次读到旧 json → 立即写 jsonc（幂等迁移，不删旧文件）
            try:
                self._save(data)
            except OSError:
                _logger.warning("[plugins:state] failed to migrate %s", legacy, exc_info=True)
            return data
        return {"plugins": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from lamtools_core.config.root import atomic_write_text

        atomic_write_text(
            self.path,
            json.dumps(data, ensure_ascii=False, indent=2),
        )

    def is_enabled(self, name: str) -> bool:
        plugins = self._load().get("plugins", {})
        if not isinstance(plugins, dict):
            return True
        raw = plugins.get(name, {})
        return bool(raw.get("enabled", True)) if isinstance(raw, dict) else True

    def set_enabled(self, name: str, enabled: bool) -> None:
        data = self._load()
        plugins = data.setdefault("plugins", {})
        if not isinstance(plugins, dict):
            plugins = {}
            data["plugins"] = plugins
        entry = plugins.setdefault(name, {})
        if not isinstance(entry, dict):
            entry = {}
            plugins[name] = entry
        entry["enabled"] = bool(enabled)
        self._save(data)

    def get_entry(self, name: str) -> dict[str, Any]:
        """读取插件注册表条目（安装记录/依赖清单等，缺省空 dict）。"""
        plugins = self._load().get("plugins", {})
        if not isinstance(plugins, dict):
            return {}
        raw = plugins.get(name, {})
        return dict(raw) if isinstance(raw, dict) else {}

    def update_entry(self, name: str, **fields: Any) -> None:
        data = self._load()
        plugins = data.setdefault("plugins", {})
        if not isinstance(plugins, dict):
            plugins = {}
            data["plugins"] = plugins
        entry = plugins.setdefault(name, {})
        if not isinstance(entry, dict):
            entry = {}
            plugins[name] = entry
        entry.update(fields)
        self._save(data)


class PluginRegistry:
    def __init__(
        self,
        *,
        plugin_roots: list[Path | str],
        state_store: PluginStateStore | None = None,
    ) -> None:
        self.plugin_roots = [Path(root).resolve() for root in plugin_roots]
        self.state_store = state_store
        # discover 收集的加载错误（E6：损坏插件在 plugin.list 报状态，不静默）
        self.discover_errors: list[dict[str, Any]] = []

    def discover(self) -> list[PluginManifest]:
        items: list[PluginManifest] = []
        self.discover_errors = []
        seen: set[Path] = set()
        for root in self.plugin_roots:
            if not root.exists():
                continue
            for manifest_path in sorted(root.glob("*/plugin.json")):
                if manifest_path in seen:
                    continue
                seen.add(manifest_path)
                try:
                    items.append(self._read_manifest(manifest_path))
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    # One corrupt plugin must never hide every other plugin
                    # (audit 11) — skip it, keep going, but surface it in
                    # plugin.list (E6 共识：加载错误可见，不静默跳过).
                    _logger.warning(
                        "[plugins:discover] skipping unreadable manifest %s",
                        manifest_path,
                        exc_info=True,
                    )
                    self.discover_errors.append(
                        {
                            "name": manifest_path.parent.name,
                            "path": str(manifest_path),
                            "error": str(exc),
                        }
                    )
        return sorted(items, key=lambda item: item.name)

    def _read_manifest(self, manifest_path: Path) -> PluginManifest:
        raw = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError(f"plugin manifest must be an object: {manifest_path}")
        name = str(raw.get("name") or manifest_path.parent.name).strip()
        if not name:
            raise ValueError(f"plugin name is required: {manifest_path}")
        plugin_id = str(raw.get("id") or name).strip()
        if not plugin_id:
            raise ValueError(f"plugin id is required: {manifest_path}")
        manifest_version = str(raw.get("manifest_version") or SUPPORTED_MANIFEST_VERSION).strip()
        if manifest_version != SUPPORTED_MANIFEST_VERSION:
            raise ValueError(
                f"unsupported manifest_version '{manifest_version}' "
                f"(supported: '{SUPPORTED_MANIFEST_VERSION}'): {manifest_path}"
            )
        root = manifest_path.parent.resolve()
        hook_files = self._paths(root, raw.get("hooks"))
        if not hook_files and (root / "hooks" / "hooks.json").exists():
            hook_files = [root / "hooks" / "hooks.json"]
        mcp_files = self._paths(root, raw.get("mcpServers"))
        if not mcp_files:
            if (root / ".mcp.json").exists():
                mcp_files = [root / ".mcp.json"]
            elif (root / "mcp" / "mcp.json").exists():
                mcp_files = [root / "mcp" / "mcp.json"]
        desktop_raw = raw.get(MANIFEST_DESKTOP_KEY)
        desktop_entry: Path | None = None
        desktop_title = ""
        desktop_window: dict[str, Any] = {}
        desktop_card_width = DEFAULT_DESKTOP_CARD_WIDTH
        desktop_card_height = DEFAULT_DESKTOP_CARD_HEIGHT
        desktop_file_drop = False
        if desktop_raw is not None:
            if not isinstance(desktop_raw, dict):
                raise ValueError(f"plugin desktop manifest must be an object: {manifest_path}")
            entries = self._paths(root, desktop_raw.get("entry"))
            if (
                len(entries) != 1
                or entries[0].suffix.lower() != ".html"
                or not entries[0].is_file()
            ):
                raise ValueError(
                    f"plugin desktop.entry must name one existing './'-relative HTML file: {manifest_path}"
                )
            desktop_entry = entries[0]
            desktop_title = str(desktop_raw.get("title") or name).strip() or name
            raw_window = desktop_raw.get("window")
            if raw_window is not None and not isinstance(raw_window, dict):
                raise ValueError(f"plugin desktop.window must be an object: {manifest_path}")
            desktop_window = dict(raw_window or {})
            desktop_card_width = _positive_int(
                desktop_window.get("cardWidth"),
                key="desktop.window.cardWidth",
                default=DEFAULT_DESKTOP_CARD_WIDTH,
            )
            desktop_card_height = _positive_int(
                desktop_window.get("cardHeight"),
                key="desktop.window.cardHeight",
                default=DEFAULT_DESKTOP_CARD_HEIGHT,
            )
            desktop_file_drop = desktop_raw.get("fileDrop", False)
            if not isinstance(desktop_file_drop, bool):
                raise ValueError(f"plugin desktop.fileDrop must be a boolean: {manifest_path}")
        ui = self._ui_contribution(root, raw.get(MANIFEST_UI_KEY), manifest_path)
        cli = self._cli_contribution(raw.get(MANIFEST_CLI_KEY), manifest_path)
        commands = self._composer_commands(raw.get(MANIFEST_COMMANDS_KEY), manifest_path)
        backend_entry = self._backend_entry(root, raw.get("backend"), manifest_path)
        enabled = self.state_store.is_enabled(name) if self.state_store else True
        skill_roots = self._paths(root, raw.get("skills"))
        raw_skill_modes = raw.get(MANIFEST_SKILL_MODES_KEY, {})
        if raw_skill_modes is not None and not isinstance(raw_skill_modes, dict):
            raise ValueError(f"plugin skillModes must be an object: {manifest_path}")
        skill_modes: dict[Path, tuple[str, ...]] = {}
        for relative, modes in (raw_skill_modes or {}).items():
            paths = self._paths(root, relative)
            if len(paths) != 1 or not isinstance(modes, list) or any(not isinstance(mode, str) for mode in modes):
                raise ValueError(f"plugin skillModes entries require one path and a string list: {manifest_path}")
            if paths[0] not in skill_roots:
                raise ValueError(f"plugin skillModes path must also appear in skills: {manifest_path}")
            skill_modes[paths[0]] = tuple(mode.strip() for mode in modes if mode.strip())
        return PluginManifest(
            name=name,
            id=plugin_id,
            version=str(raw.get("version") or "0.0.0"),
            description=str(raw.get("description") or ""),
            builtin=bool(raw.get("builtin", False)),
            manifest_version=manifest_version,
            root=root,
            enabled=enabled,
            skill_roots=skill_roots,
            skill_modes=skill_modes,
            hook_files=hook_files,
            mcp_files=mcp_files,
            tool_files=self._paths(root, raw.get(MANIFEST_TOOLS_KEY)),
            operation_files=self._paths(root, raw.get(MANIFEST_OPERATIONS_KEY)),
            dependencies=[
                str(item).strip()
                for item in raw.get(MANIFEST_DEPENDENCIES_KEY, [])
                if isinstance(item, str) and str(item).strip()
            ]
            if isinstance(raw.get(MANIFEST_DEPENDENCIES_KEY), list)
            else [],
            config_schema=(
                self._paths(root, raw.get(MANIFEST_CONFIG_SCHEMA_KEY))[0]
                if raw.get(MANIFEST_CONFIG_SCHEMA_KEY)
                else None
            ),
            desktop_entry=desktop_entry,
            desktop_title=desktop_title,
            desktop_window=desktop_window,
            desktop_card_width=desktop_card_width,
            desktop_card_height=desktop_card_height,
            desktop_file_drop=desktop_file_drop,
            ui=ui,
            cli=cli,
            commands=commands,
            backend_entry=backend_entry,
            raw=dict(raw),
        )

    def _composer_commands(
        self, value: object, manifest_path: Path
    ) -> list[PluginComposerCommand]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError(f"plugin commands must be an array: {manifest_path}")
        commands: list[PluginComposerCommand] = []
        seen: set[str] = set()
        for index, raw_command in enumerate(value):
            if not isinstance(raw_command, dict):
                raise ValueError(f"plugin commands[{index}] must be an object: {manifest_path}")
            name = str(raw_command.get("name") or "").strip().lstrip("/").lower()
            if not name or any(char.isspace() for char in name):
                raise ValueError(f"plugin commands[{index}].name must be one token: {manifest_path}")
            if name in seen:
                raise ValueError(f"duplicate plugin command '{name}': {manifest_path}")
            seen.add(name)
            kind = str(raw_command.get("kind") or "action").strip().lower()
            action = str(raw_command.get("action") or "run_action").strip().lower()
            if kind != "action" or action != "run_action":
                raise ValueError(
                    f"plugin command '{name}' currently requires kind=action and action=run_action: {manifest_path}"
                )
            operation = str(raw_command.get("operation") or "").strip()
            payload = raw_command.get("payload") or {}
            effect = raw_command.get("effect") or {}
            if not isinstance(payload, dict) or not isinstance(effect, dict):
                raise ValueError(f"plugin command '{name}' payload/effect must be objects: {manifest_path}")
            if not operation and not effect:
                raise ValueError(f"plugin command '{name}' requires operation or effect: {manifest_path}")
            if effect:
                effect_type = str(effect.get("type") or "").strip()
                effect_action = str(effect.get("action") or "").strip()
                if effect_type != "desktop_plugin" or effect_action != "show":
                    raise ValueError(f"plugin command '{name}' has unsupported effect: {manifest_path}")
            commands.append(
                PluginComposerCommand(
                    name=name,
                    title=str(raw_command.get("title") or name).strip() or name,
                    description=str(raw_command.get("description") or "").strip(),
                    icon=str(raw_command.get("icon") or "puzzle").strip() or "puzzle",
                    kind=kind,
                    action=action,
                    accepts_args=bool(raw_command.get("acceptsArgs", raw_command.get("accepts_args", False))),
                    operation=operation,
                    payload=dict(payload),
                    effect=dict(effect),
                )
            )
        return commands

    def _cli_contribution(
        self, value: object, manifest_path: Path
    ) -> PluginCLIContribution | None:
        """Parse the generic ``cli.commands`` contribution tree.

        The manifest deliberately describes only argparse data.  Handler
        imports happen in :mod:`lamtools_core.plugins.cli` after discovery so
        one broken optional command cannot make the whole plugin registry
        unusable.
        """
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError(f"plugin cli manifest must be an object: {manifest_path}")
        raw_commands = value.get("commands", [])
        if not isinstance(raw_commands, list):
            raise ValueError(f"plugin cli.commands must be an array: {manifest_path}")

        def parse_arguments(raw_command: dict[str, Any], command_path: str) -> list[PluginCLIArgument]:
            raw_arguments = raw_command.get("arguments", raw_command.get("args", []))
            if raw_arguments is None:
                return []
            if not isinstance(raw_arguments, list):
                raise ValueError(
                    f"plugin cli command '{command_path}'.arguments must be an array: {manifest_path}"
                )
            arguments: list[PluginCLIArgument] = []
            seen_flags: set[str] = set()
            for index, raw_argument in enumerate(raw_arguments):
                if not isinstance(raw_argument, dict):
                    raise ValueError(
                        f"plugin cli command '{command_path}'.arguments[{index}] must be an object: {manifest_path}"
                    )
                raw_flags = raw_argument.get("flags", raw_argument.get("flag"))
                if isinstance(raw_flags, str):
                    flags = (raw_flags.strip(),)
                elif isinstance(raw_flags, list):
                    flags = tuple(str(item).strip() for item in raw_flags)
                else:
                    flags = ()
                if not flags or any(not item for item in flags):
                    raise ValueError(
                        f"plugin cli command '{command_path}'.arguments[{index}] requires non-empty flags: {manifest_path}"
                    )
                if len(set(flags)) != len(flags) or seen_flags.intersection(flags):
                    raise ValueError(
                        f"plugin cli command '{command_path}'.arguments[{index}] contains duplicate flags: {manifest_path}"
                    )
                seen_flags.update(flags)
                positional = not flags[0].startswith("-")
                if any(item.startswith("-") != (not positional) for item in flags):
                    raise ValueError(
                        f"plugin cli command '{command_path}'.arguments[{index}] mixes positional and option flags: {manifest_path}"
                    )
                action = str(raw_argument.get("action") or "store").strip()
                if action not in {"store", "store_true", "store_false", "append"}:
                    raise ValueError(
                        f"plugin cli command '{command_path}'.arguments[{index}] has invalid action '{action}': {manifest_path}"
                    )
                value_type = str(raw_argument.get("type") or "str").strip().lower()
                if value_type not in {"str", "string", "int", "integer", "float", "bool", "boolean", "path", "json"}:
                    raise ValueError(
                        f"plugin cli command '{command_path}'.arguments[{index}] has invalid type '{value_type}': {manifest_path}"
                    )
                raw_nargs = raw_argument.get("nargs")
                nargs: str | int | None = None
                if raw_nargs is not None:
                    if isinstance(raw_nargs, bool):
                        raise ValueError(
                            f"plugin cli command '{command_path}'.arguments[{index}] has invalid nargs: {manifest_path}"
                        )
                    if isinstance(raw_nargs, int):
                        if raw_nargs < 0:
                            raise ValueError(
                                f"plugin cli command '{command_path}'.arguments[{index}] has invalid nargs: {manifest_path}"
                            )
                        nargs = raw_nargs
                    elif isinstance(raw_nargs, str) and raw_nargs in {"?", "*", "+"}:
                        nargs = raw_nargs
                    else:
                        raise ValueError(
                            f"plugin cli command '{command_path}'.arguments[{index}] has invalid nargs: {manifest_path}"
                        )
                raw_choices = raw_argument.get("choices", [])
                if raw_choices is None:
                    raw_choices = []
                if not isinstance(raw_choices, list) or any(
                    not isinstance(item, (str, int, float, bool)) for item in raw_choices
                ):
                    raise ValueError(
                        f"plugin cli command '{command_path}'.arguments[{index}].choices must be an array: {manifest_path}"
                    )
                choices = tuple(str(item) for item in raw_choices)
                arguments.append(
                    PluginCLIArgument(
                        flags=flags,
                        dest=str(raw_argument.get("dest") or "").strip(),
                        action=action,
                        type=value_type,
                        default=raw_argument.get("default"),
                        required=bool(raw_argument.get("required", False)),
                        nargs=nargs,
                        choices=choices,
                        metavar=str(raw_argument.get("metavar") or "").strip(),
                        help=str(raw_argument.get("help") or ""),
                        const=raw_argument.get("const"),
                        raw=dict(raw_argument),
                    )
                )
            return arguments

        def parse_commands(raw_items: list[Any], parent_path: str = "") -> list[PluginCLICommand]:
            commands: list[PluginCLICommand] = []
            seen_names: set[str] = set()
            for index, raw_command in enumerate(raw_items):
                if not isinstance(raw_command, dict):
                    raise ValueError(
                        f"plugin cli.commands[{index}] must be an object: {manifest_path}"
                    )
                name = str(raw_command.get("name") or "").strip()
                if not name or any(char.isspace() for char in name):
                    raise ValueError(
                        f"plugin cli command name must be one token: {manifest_path}"
                    )
                if name in seen_names:
                    raise ValueError(
                        f"duplicate plugin cli command '{name}' at '{parent_path or '<root>'}': {manifest_path}"
                    )
                seen_names.add(name)
                raw_aliases = raw_command.get("aliases", [])
                if raw_aliases is None:
                    raw_aliases = []
                if not isinstance(raw_aliases, list) or any(
                    not isinstance(item, str) or not item.strip() or any(char.isspace() for char in item.strip())
                    for item in raw_aliases
                ):
                    raise ValueError(
                        f"plugin cli command '{name}'.aliases must be an array of one-token strings: {manifest_path}"
                    )
                aliases = tuple(str(item).strip() for item in raw_aliases)
                if name in aliases or len(set(aliases)) != len(aliases):
                    raise ValueError(
                        f"plugin cli command '{name}' has duplicate aliases: {manifest_path}"
                    )
                child_raw = raw_command.get("commands", raw_command.get("subcommands", []))
                if child_raw is None:
                    child_raw = []
                if not isinstance(child_raw, list):
                    raise ValueError(
                        f"plugin cli command '{name}'.commands must be an array: {manifest_path}"
                    )
                command_path = f"{parent_path} {name}".strip()
                handler = str(raw_command.get("handler") or "").strip()
                if handler and ":" not in handler:
                    raise ValueError(
                        f"plugin cli command '{command_path}' handler must be module:function: {manifest_path}"
                    )
                children = parse_commands(child_raw, command_path)
                if not handler and not children:
                    raise ValueError(
                        f"plugin cli command '{command_path}' needs a handler or subcommands: {manifest_path}"
                    )
                commands.append(
                    PluginCLICommand(
                        name=name,
                        help=str(raw_command.get("help") or ""),
                        handler=handler,
                        aliases=aliases,
                        arguments=parse_arguments(raw_command, command_path),
                        commands=children,
                        raw=dict(raw_command),
                    )
                )
            return commands

        return PluginCLIContribution(commands=parse_commands(raw_commands))

    def _backend_entry(self, root: Path, value: object, manifest_path: Path) -> Path | None:
        if value is None:
            candidate = root / "backend" / "__init__.py"
            return candidate if candidate.is_file() else None
        if not isinstance(value, str) or not value.strip().startswith("./"):
            raise ValueError(f"plugin backend must be a './'-relative path: {manifest_path}")
        candidate = (root / value.strip()[2:]).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise ValueError(f"plugin backend must name one existing './'-relative file: {manifest_path}")
        return candidate

    def _ui_contribution(
        self, root: Path, value: object, manifest_path: Path
    ) -> PluginUIContribution | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError(f"plugin ui manifest must be an object: {manifest_path}")

        def parse_items(key: str, cls: Any) -> list[Any]:
            raw_items = value.get(key, [])
            if raw_items is None:
                return []
            if not isinstance(raw_items, list):
                raise ValueError(f"plugin ui.{key} must be an array: {manifest_path}")
            parsed: list[Any] = []
            seen: set[str] = set()
            for index, raw_item in enumerate(raw_items):
                if not isinstance(raw_item, dict):
                    raise ValueError(
                        f"plugin ui.{key}[{index}] must be an object: {manifest_path}"
                    )
                item_id = str(raw_item.get("id") or "").strip()
                if not item_id:
                    raise ValueError(
                        f"plugin ui.{key}[{index}] is missing 'id': {manifest_path}"
                    )
                if item_id in seen:
                    raise ValueError(
                        f"duplicate plugin ui {key} id '{item_id}': {manifest_path}"
                    )
                seen.add(item_id)
                entry_value = raw_item.get("entry")
                entries = self._paths(root, entry_value)
                if len(entries) != 1 or not entries[0].is_file():
                    raise ValueError(
                        f"plugin ui.{key}[{index}].entry must name one existing './'-relative file: {manifest_path}"
                    )
                title = str(raw_item.get("title") or item_id).strip() or item_id
                icon = str(raw_item.get("icon") or "").strip()
                raw_tools = raw_item.get("tools", [])
                if raw_tools is None:
                    raw_tools = []
                if not isinstance(raw_tools, list) or any(
                    not isinstance(tool, str) or not tool.strip() for tool in raw_tools
                ):
                    raise ValueError(
                        f"plugin ui.{key}[{index}].tools must be an array of non-empty strings: {manifest_path}"
                    )
                tools = [tool.strip() for tool in raw_tools]
                if len(set(tools)) != len(tools):
                    raise ValueError(
                        f"plugin ui.{key}[{index}].tools contains duplicates: {manifest_path}"
                    )
                values: dict[str, Any] = {
                    "id": item_id,
                    "title": title,
                    "entry": entries[0],
                    "icon": icon,
                }
                if cls is PluginUIMode:
                    values["tools"] = tools
                parsed.append(cls(**values))
            return parsed

        sidebar = value.get("sidebar", {})
        if sidebar is None:
            sidebar = {}
        if not isinstance(sidebar, dict):
            raise ValueError(f"plugin ui.sidebar must be an object: {manifest_path}")
        raw_widgets = sidebar.get("widgets", [])
        if raw_widgets is None:
            raw_widgets = []
        if not isinstance(raw_widgets, list):
            raise ValueError(f"plugin ui.sidebar.widgets must be an array: {manifest_path}")
        widgets: list[PluginSidebarWidget] = []
        widget_ids: set[str] = set()
        for index, raw_widget in enumerate(raw_widgets):
            prefix = f"plugin ui.sidebar.widgets[{index}]"
            if not isinstance(raw_widget, dict):
                raise ValueError(f"{prefix} must be an object: {manifest_path}")
            widget_id = str(raw_widget.get("id") or "").strip()
            if not widget_id:
                raise ValueError(f"{prefix} is missing 'id': {manifest_path}")
            if widget_id in widget_ids:
                raise ValueError(f"duplicate plugin sidebar widget id '{widget_id}': {manifest_path}")
            widget_ids.add(widget_id)
            renderer = str(raw_widget.get("renderer") or raw_widget.get("kind") or "blocks").strip().lower()
            if renderer not in {"blocks", "component"}:
                raise ValueError(f"{prefix}.renderer must be blocks or component: {manifest_path}")
            scope = str(raw_widget.get("scope") or "workspace").strip().lower()
            if scope not in {"global", "workspace", "session"}:
                raise ValueError(f"{prefix}.scope must be global, workspace, or session: {manifest_path}")
            raw_order = raw_widget.get("order", 0)
            if isinstance(raw_order, bool) or not isinstance(raw_order, int):
                raise ValueError(f"{prefix}.order must be an integer: {manifest_path}")
            snapshot_operation = str(
                raw_widget.get("snapshotOperation") or raw_widget.get("snapshot_operation") or ""
            ).strip()
            if renderer == "blocks" and not snapshot_operation:
                raise ValueError(f"{prefix}.snapshotOperation is required for blocks: {manifest_path}")
            entry: Path | None = None
            if renderer == "component":
                entries = self._paths(root, raw_widget.get("entry"))
                if len(entries) != 1 or not entries[0].is_file():
                    raise ValueError(
                        f"{prefix}.entry must name one existing './'-relative file: {manifest_path}"
                    )
                entry = entries[0]
            raw_actions = raw_widget.get("actions", [])
            if raw_actions is None:
                raw_actions = []
            if not isinstance(raw_actions, list):
                raise ValueError(f"{prefix}.actions must be an array: {manifest_path}")
            actions: list[PluginWidgetAction] = []
            action_ids: set[str] = set()
            for action_index, raw_action in enumerate(raw_actions):
                action_prefix = f"{prefix}.actions[{action_index}]"
                if not isinstance(raw_action, dict):
                    raise ValueError(f"{action_prefix} must be an object: {manifest_path}")
                action_id = str(raw_action.get("id") or "").strip()
                operation = str(raw_action.get("operation") or "").strip()
                if not action_id or not operation:
                    raise ValueError(f"{action_prefix} requires id and operation: {manifest_path}")
                if action_id in action_ids:
                    raise ValueError(f"duplicate widget action id '{action_id}': {manifest_path}")
                action_ids.add(action_id)
                input_schema = raw_action.get("inputSchema", raw_action.get("input_schema", {}))
                if not isinstance(input_schema, dict):
                    raise ValueError(f"{action_prefix}.inputSchema must be an object: {manifest_path}")
                for boolean_key in ("dangerous", "mutates"):
                    if boolean_key in raw_action and not isinstance(raw_action[boolean_key], bool):
                        raise ValueError(f"{action_prefix}.{boolean_key} must be a boolean: {manifest_path}")
                actions.append(
                    PluginWidgetAction(
                        id=action_id,
                        title=str(raw_action.get("title") or action_id).strip() or action_id,
                        operation=operation,
                        input_schema=dict(input_schema),
                        dangerous=bool(raw_action.get("dangerous", False)),
                        mutates=bool(raw_action.get("mutates", False)),
                    )
                )
            widgets.append(
                PluginSidebarWidget(
                    id=widget_id,
                    title=str(raw_widget.get("title") or widget_id).strip() or widget_id,
                    renderer=renderer,
                    scope=scope,
                    icon=str(raw_widget.get("icon") or "").strip(),
                    order=raw_order,
                    snapshot_operation=snapshot_operation,
                    entry=entry,
                    actions=actions,
                )
            )

        return PluginUIContribution(
            views=parse_items("views", PluginUIView),
            modes=parse_items("modes", PluginUIMode),
            sidebar_widgets=widgets,
        )

    def _paths(self, root: Path, value: object) -> list[Path]:
        values = value if isinstance(value, list) else [value] if isinstance(value, str) else []
        paths: list[Path] = []
        for raw in values:
            text = str(raw or "").strip()
            if not text:
                continue
            if not text.startswith("./"):
                raise ValueError(f"plugin resource path must start with './': {text}")
            path = (root / text[2:]).resolve()
            if not path.is_relative_to(root):
                raise ValueError(f"plugin resource path is outside plugin root: {text}")
            paths.append(path)
        return paths


def _positive_int(value: object, *, key: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return value
