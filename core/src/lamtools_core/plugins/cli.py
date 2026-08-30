"""Generic manifest-driven CLI contributions.

Plugins declare a small argparse tree in ``plugin.json`` under
``cli.commands``.  Core owns only the mounting protocol; command handlers and
their live operation details stay inside the contributing plugin.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import logging
import sys
from pathlib import Path
from typing import Any

from .models import PluginCLIArgument, PluginCLICommand, PluginManifest
from .registry import PluginRegistry, PluginStateStore

_logger = logging.getLogger(__name__)


def load_plugin_cli_commands(
    subparsers: Any,
    *,
    plugins: list[PluginManifest] | None = None,
    plugin_roots: list[Path | str] | None = None,
    state_path: Path | str | None = None,
) -> list[dict[str, str]]:
    """Mount enabled plugin CLI contributions into an argparse subparser.

    ``subparsers`` is the object returned by ``ArgumentParser.add_subparsers``.
    Discovery is injectable so hosts and tests can use an explicit plugin
    set; omitted plugins are discovered from the supplied roots.  Broken
    optional commands are reported and skipped instead of breaking Core's
    built-in command set.
    """
    if plugins is None:
        roots = [Path(item).resolve() for item in (plugin_roots or [])]
        state = PluginStateStore(state_path) if state_path is not None else None
        plugins = PluginRegistry(plugin_roots=roots, state_store=state).discover()

    errors: list[dict[str, str]] = []
    for plugin in plugins:
        if not plugin.enabled or plugin.cli is None:
            continue
        root_text = str(plugin.root)
        if root_text not in sys.path:
            sys.path.append(root_text)
        for command in plugin.cli.commands:
            _mount_command(
                subparsers,
                command,
                plugin=plugin,
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
    plugin: PluginManifest,
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


__all__ = ["load_plugin_cli_commands"]
