"""Composer command bridge for v2 plugins.

user:“五类是斜杠命令”+v2 插件声明的命令要进同一张命令表，执行时仍然走
``operation``，不引入第二套执行通道。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .capabilities import assemble_capabilities
from .host import PluginHost


@dataclass(frozen=True)
class ComposerCommandHandle:
    """The shape ``build_composer_command_catalog`` reads from a plugin."""

    name: str
    title: str
    description: str = ""
    icon: str = "puzzle"
    kind: str = "action"
    action: str = "run_action"
    accepts_args: bool = False
    operation: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    effect: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ComposerPluginHandle:
    """A v2 plugin as the composer catalog sees it."""

    name: str
    id: str
    enabled: bool
    desktop_title: str
    commands: tuple[ComposerCommandHandle, ...] = ()


def composer_plugin_handles(host: PluginHost) -> list[ComposerPluginHandle]:
    """Expose enabled plugin commands in the legacy catalog's plugin shape."""
    manifests = host.runtime_manifests()
    assembly = assemble_capabilities(manifests)
    grouped: dict[str, list[ComposerCommandHandle]] = {}
    for command in assembly.commands:
        grouped.setdefault(command.plugin, []).append(
            ComposerCommandHandle(
                name=command.name,
                title=command.title or command.name,
                description=command.description,
                # 命令带 operation 时允许把斜杠后面的文字原样交给它。
                accepts_args=bool(command.operation),
                operation=command.operation,
                payload=dict(command.payload),
                effect=dict(command.effect),
            )
        )
    return [
        ComposerPluginHandle(
            name=name,
            id=name,
            enabled=True,
            desktop_title=name,
            commands=tuple(commands),
        )
        for name, commands in grouped.items()
    ]


__all__ = ["ComposerCommandHandle", "ComposerPluginHandle", "composer_plugin_handles"]
