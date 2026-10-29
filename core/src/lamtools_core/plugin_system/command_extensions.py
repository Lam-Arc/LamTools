"""user:“宿主能力补齐和接口完善与文档更新”+(受管命令贡献复用原 command.catalog/execute，回调随启动代撤回与排空)。"""

from __future__ import annotations

import inspect
import re
import uuid
from dataclasses import dataclass
from typing import Callable

from lamtools_core.composer_commands import ComposerCommandDefinition
from .services import RegistrationScope


@dataclass(frozen=True)
class CommandInvocation:
    name: str
    session_id: str
    arguments: str
    work_root: str


@dataclass(frozen=True)
class CommandResult:
    status: str = "ok"
    text: str = ""

    def __post_init__(self):
        if self.status not in {"ok", "error"} or not isinstance(self.text, str):
            raise ValueError("command result requires ok/error status and string text")


@dataclass(eq=False)
class _Entry:
    scope: RegistrationScope
    name: str
    handler: Callable
    title: str
    description: str
    accepts_args: bool
    session_id: str | None
    token: str
    live: bool = True

    def visible(self, session_id):
        return (self.live and self.scope.accepting and self.scope.published
                and (self.session_id is None or self.session_id == session_id))


class PluginCommandAPI:
    def __init__(self, host: CommandExtensionsHost, scope: RegistrationScope):
        self._host, self._scope = host, scope

    def register(self, name: str, handler: Callable, *, title="", description="", accepts_args=True, session_id=None):
        self._scope.check_open()
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
            raise ValueError("command name must match [a-z][a-z0-9_-]{0,63}")
        if not callable(handler) or not isinstance(title, str) or not isinstance(description, str) or type(accepts_args) is not bool:
            raise TypeError("command requires callable handler, string title/description and boolean accepts_args")
        if session_id is not None and (not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 256):
            raise ValueError("session_id must be a non-empty ID or None")
        return self._host.add(_Entry(self._scope, name, handler, title or name, description, accepts_args, session_id, uuid.uuid4().hex))


class CommandExtensionsHost:
    def __init__(self, reserved_names=()):
        self.reserved = set(reserved_names)
        self.entries: list[_Entry] = []
        self.known_names: set[str] = set()
        self._conflicts: dict[str, set[str]] = {}

    def reserve(self, names):
        names = set(names)
        if any(e.name in names and e.live and e.scope.accepting for e in self.entries):
            raise ValueError("command reserved name conflicts with an active registration")
        self.reserved.update(names)

    def for_scope(self, scope):
        scope.check_open()
        return PluginCommandAPI(self, scope)

    def add(self, entry):
        if entry.name in self.reserved:
            raise ValueError(f"command reserved name: {entry.name}")
        for old in self.entries:
            if old.name != entry.name or not old.live or not old.scope.accepting:
                continue
            if old.scope.owner != entry.scope.owner or old.session_id == entry.session_id:
                raise ValueError(f"command name conflict: {entry.name}")
        self.entries.append(entry)
        self.known_names.add(entry.name)
        def remove():
            entry.live = False
            if entry in self.entries:
                self.entries.remove(entry)
        entry.scope.on_dispose(remove)
        return remove

    def selected(self, session_id):
        chosen = {}
        for entry in list(self.entries):
            if entry.visible(session_id) and (entry.name not in chosen or entry.session_id is not None):
                chosen[entry.name] = entry
        return chosen

    def merge_catalog(self, definitions, *, session_id=""):
        definitions = list(definitions)
        selected = self.selected(session_id)
        conflicts = set(selected) & {d.name for d in definitions}
        self._conflicts[session_id] = conflicts
        merged = [d for d in definitions if d.name not in conflicts]
        for name, entry in sorted(selected.items()):
            if name in conflicts:
                continue
            merged.append(ComposerCommandDefinition(name=name, title=entry.title, description=entry.description,
                icon="puzzle", action="run_action", source="plugin", kind="action", accepts_args=entry.accepts_args,
                metadata={"plugin_id": entry.scope.owner, "plugin_name": entry.scope.owner,
                          "owned_command_token": entry.token, "epoch": entry.scope.epoch}))
        return merged

    async def dispatch(self, token, *, name, session_id, arguments, work_root):
        entry = self.selected(session_id).get(name)
        if entry is None or entry.token != token:
            raise RuntimeError("command registration is unavailable or changed")
        if name in self._conflicts.get(session_id, set()):
            raise RuntimeError("command provider conflict")
        if not isinstance(arguments, str) or not isinstance(work_root, str):
            raise TypeError("command arguments/work_root must be strings")
        if arguments and not entry.accepts_args:
            raise ValueError("command does not accept arguments")
        entry.scope.acquire()
        try:
            try:
                result = entry.handler(CommandInvocation(name, session_id, arguments, work_root))
                result = await result if inspect.isawaitable(result) else result
            except Exception as error:
                # user:“接口完善”+(普通处理器异常应通过原命令错误通道结算，取消仍传播并释放租约)。
                raise RuntimeError(f"Plugin command '{name}' failed: {error}") from error
            if not isinstance(result, CommandResult):
                raise TypeError("command handler must return CommandResult")
            return result
        finally:
            entry.scope.release()


def ensure_command_extensions(context, *, reserved_names=()):
    host = context.service("command_extensions")
    if host is None:
        host = CommandExtensionsHost(reserved_names)
        context.set_service("command_extensions", host)
    else:
        host.reserve(reserved_names)
    return host
