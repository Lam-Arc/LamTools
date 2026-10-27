"""Chat-command registry shared by channel plugins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .types import ChannelMessage, ChannelSession


@dataclass
class ChannelCommandContext:
    session: ChannelSession
    message: ChannelMessage
    args: list[str]
    raw: str
    runtime: Any


@dataclass
class ChannelCommand:
    names: tuple[str, ...]
    description: str
    handler: Callable[[ChannelCommandContext], Awaitable[str | None] | str | None]
    category: str = "channel"
    hidden: bool = False

    @property
    def name(self) -> str:
        return self.names[0]


class CommandRegistry:
    def __init__(self, commands: list[ChannelCommand] | None = None) -> None:
        self.commands: list[ChannelCommand] = list(commands or [])
        self._by_name: dict[str, ChannelCommand] = {}
        for command in self.commands:
            for name in command.names:
                self._by_name[name.lower()] = command

    def register(self, command: ChannelCommand) -> None:
        self.commands.append(command)
        for name in command.names:
            self._by_name[name.lower()] = command

    def find(self, name: str) -> ChannelCommand | None:
        return self._by_name.get(str(name or "").lower())

    def parse(self, text: str, *, prefix: str = "/") -> tuple[ChannelCommand, list[str], str] | None:
        text = str(text or "").strip()
        if not text.startswith(prefix):
            return None
        body = text[len(prefix):]
        parts = body.split(None, 1)
        if not parts:
            return None
        command = self.find(parts[0])
        if command is None:
            return None
        raw = parts[1].strip() if len(parts) > 1 else ""
        return command, raw.split() if raw else [], raw


__all__ = ["ChannelCommand", "ChannelCommandContext", "CommandRegistry"]
