"""Manifest-driven CLI contributions for the unified plugin system.

user:“插件自己也提供 CLI 命令”+插件在 plugin.json 的 ``cli.commands`` 里
声明一棵 argparse 树，Core 只管装载协议；坏命令跳过并报告，不连坐。
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .host import PluginHost

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginCLIArgument:
    """One argparse-compatible argument declared by a plugin command."""

    flags: tuple[str, ...]
    dest: str = ""
    action: str = "store"
    type: str = "str"
    default: Any = None
    required: bool = False
    nargs: str | int | None = None
    choices: tuple[str, ...] = field(default_factory=tuple)
    metavar: str = ""
    help: str = ""
    const: Any = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginCLICommand:
    """A plugin CLI command or command group declared in ``plugin.json``."""

    name: str
    help: str = ""
    handler: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    arguments: list[PluginCLIArgument] = field(default_factory=list)
    commands: list["PluginCLICommand"] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginCLIContribution:
    """Manifest-declared CLI command groups contributed by a plugin."""

    commands: list[PluginCLICommand] = field(default_factory=list)


def parse_cli_contribution(value: object, manifest_path: Path) -> PluginCLIContribution | None:
    """Parse the ``cli.commands`` contribution tree (argparse data only)."""

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


def load_plugin_cli_commands(subparsers: Any, *, host: PluginHost) -> list[dict[str, str]]:
    """Mount enabled plugins' ``cli`` trees into an argparse subparser."""
    errors: list[dict[str, str]] = []
    for manifest in host.discover():
        if not manifest.enabled:
            continue
        value = manifest.raw.get("cli")
        if not isinstance(value, dict):
            continue
        try:
            contribution = parse_cli_contribution(value, manifest.root / "plugin.json")
        except ValueError as exc:
            errors.append({"plugin": manifest.name, "command": "", "error": str(exc)})
            continue
        if contribution is None:
            continue
        root_text = str(manifest.root)
        if root_text not in sys.path:
            sys.path.append(root_text)
        for command in contribution.commands:
            _mount_command(
                subparsers,
                command,
                plugin=manifest,
                path=command.name,
                errors=errors,
            )
    for item in errors:
        _logger.warning(
            "[plugins:cli] skipped %s command %s: %s",
            item.get("plugin", ""),
            item.get("command", ""),
            item.get("error", ""),
        )
    return errors


def _mount_command(
    parent: Any,
    command: PluginCLICommand,
    *,
    plugin: Any,
    path: str,
    errors: list[dict[str, str]],
) -> None:
    try:
        parser = parent.add_parser(
            command.name,
            aliases=list(command.aliases),
            help=command.help or None,
            description=command.help or None,
        )
    except (argparse.ArgumentError, ValueError) as exc:
        errors.append({"plugin": plugin.name, "command": path, "error": str(exc)})
        return

    parser.set_defaults(
        _plugin_cli_plugin=plugin.name,
        _plugin_cli_command=path,
    )
    try:
        for argument in command.arguments:
            _add_argument(parser, argument)
    except (TypeError, ValueError, argparse.ArgumentError) as exc:
        errors.append({"plugin": plugin.name, "command": path, "error": str(exc)})
        return

    if command.commands:
        children = parser.add_subparsers(
            dest=f"_plugin_cli_{plugin.name.replace('-', '_')}_command",
            required=True,
        )
        for child in command.commands:
            _mount_command(
                children,
                child,
                plugin=plugin,
                path=f"{path} {child.name}",
                errors=errors,
            )
    if command.handler:
        try:
            handler = _import_handler(command.handler)
        except (ImportError, AttributeError, TypeError, ValueError) as exc:
            errors.append(
                {
                    "plugin": plugin.name,
                    "command": path,
                    "error": f"handler import failed: {exc}",
                }
            )
            return
        parser.set_defaults(func=_dispatch(handler))


def _import_handler(entry: str) -> Any:
    module_name, separator, function_name = str(entry).partition(":")
    if not separator or not module_name.strip() or not function_name.strip():
        raise ValueError(f"invalid handler entry {entry!r}; expected module:function")
    module = importlib.import_module(module_name.strip())
    handler = getattr(module, function_name.strip())
    if not callable(handler):
        raise TypeError(f"handler {entry!r} is not callable")
    return handler


def _dispatch(handler: Any) -> Any:
    """Adapt sync and async plugin handlers to Core CLI's async entrypoint."""

    async def invoke(args: argparse.Namespace) -> int:
        result = handler(args)
        if inspect.isawaitable(result):
            result = await result
        return int(result or 0)

    return invoke


def _add_argument(parser: Any, argument: PluginCLIArgument) -> None:
    flags = list(argument.flags)
    positional = not flags[0].startswith("-")
    kwargs: dict[str, Any] = {
        "action": argument.action,
        "default": argument.default,
    }
    if argument.dest:
        kwargs["dest"] = argument.dest
    if not positional and argument.required:
        kwargs["required"] = True
    if argument.nargs is not None:
        kwargs["nargs"] = argument.nargs
    if argument.choices:
        kwargs["choices"] = list(argument.choices)
    if argument.metavar:
        kwargs["metavar"] = argument.metavar
    if argument.help:
        kwargs["help"] = argument.help
    if argument.const is not None:
        kwargs["const"] = argument.const
    if argument.action in {"store", "append"}:
        kwargs["type"] = _argument_type(argument.type)
    parser.add_argument(*flags, **kwargs)


def _argument_type(value_type: str) -> Any:
    normalized = str(value_type or "str").strip().lower()
    if normalized in {"str", "string"}:
        return str
    if normalized in {"int", "integer"}:
        return int
    if normalized == "float":
        return float
    if normalized in {"bool", "boolean"}:
        return _parse_bool
    if normalized == "path":
        return str
    if normalized == "json":
        return _parse_json
    raise ValueError(f"unsupported CLI argument type: {value_type}")


def _parse_bool(value: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected boolean, got {value!r}")


def _parse_json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid JSON: {exc}") from exc


__all__ = [
    "PluginCLIArgument",
    "PluginCLICommand",
    "PluginCLIContribution",
    "load_plugin_cli_commands",
    "parse_cli_contribution",
]
