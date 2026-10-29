"""System-prompt waterfall for plugins.

The upstream DSH host exposes a ``system-prompt/assemble`` waterfall: plugins
receive the assembled prompt, may append or replace sections, and return the
new assembly.  LamTools' prompt assembly is synchronous, so the host-side
contract is a synchronous waterfall.  A handler that returns an awaitable is
rejected with a clear error instead of being silently ignored.

Managed backends use context.prompts for staged, automatically withdrawn
sections, variables and handlers. The legacy register() API remains available
and requires its caller to manage cleanup. Assembly uses detached snapshots so
errors leave the builtin prompt available for the existing application fallback.
"""

from __future__ import annotations

import inspect
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class PromptContext:
    """What a waterfall handler may inspect."""

    session_id: str = ""
    agent_id: str = ""
    agent_name: str = ""
    work_root: str = ""
    active_mode: str = ""
    actor_kind: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptSection:
    name: str
    order: int | float
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptAssembly:
    """The mutable prompt handed through the waterfall."""

    text: str = ""
    sections: list[PromptSection] = field(default_factory=list)

    def append_section(
        self,
        name: str,
        text: str,
        *,
        order: int | float = 100,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        text = str(text or "")
        if not text.strip():
            return
        self.sections.append(
            PromptSection(name=str(name), order=order, text=text, metadata=dict(metadata or {}))
        )
        current = self.text.rstrip()
        self.text = f"{current}\n\n{text}" if current else text

    def replace_section(self, name: str, text: str) -> bool:
        """Replace an existing section's text and its occurrence in ``text``."""
        text = str(text or "")
        for section in self.sections:
            if section.name != name:
                continue
            old = section.text
            section.text = text
            if old and old in self.text:
                self.text = self.text.replace(old, text, 1)
            return True
        return False

    def get_section(self, name: str) -> PromptSection | None:
        for section in self.sections:
            if section.name == name:
                return section
        return None


PromptHandler = Callable[[PromptContext, PromptAssembly], PromptAssembly | None]


class SystemPromptWaterfall:
    """Ordered, plugin-owned prompt transformations."""

    def __init__(self) -> None:
        self._handlers: list[tuple[int | float, int, str, PromptHandler]] = []
        self._sequence = 0
        from .prompt_extensions import PromptContributions
        self._contributions = PromptContributions(self)

    def for_scope(self, scope):
        return self._contributions.for_scope(scope)

    def register(
        self,
        handler: PromptHandler,
        *,
        plugin: str = "",
        order: int | float = 100,
    ) -> Callable[[], None]:
        if not callable(handler):
            raise TypeError("system prompt handler must be callable")
        self._sequence += 1
        from .prompt_extensions import _order
        entry = (_order(order), self._sequence, str(plugin or ""), handler)
        self._handlers.append(entry)

        def unregister() -> None:
            try:
                self._handlers.remove(entry)
            except ValueError:
                pass

        return unregister

    def unregister_plugin(self, plugin: str) -> None:
        self._handlers = [entry for entry in self._handlers if entry[2] != str(plugin)]

    def assemble(self, context: PromptContext, assembly: PromptAssembly) -> PromptAssembly:
        # user:“宿主能力补齐和接口完善与文档更新”+(所有变换在副本上提交，失败后主程序可以真正回退未被插件污染的原提示词)。
        context = deepcopy(context)
        assembly = self._contributions.apply(context, deepcopy(assembly))
        for _order, _sequence, plugin, handler in sorted(self._handlers, key=lambda item: (item[0], item[1])):
            try:
                result = handler(deepcopy(context), assembly)
            except Exception as exc:  # a plugin must not break prompt assembly
                raise RuntimeError(f"system prompt handler from '{plugin or 'unknown'}' failed: {exc}") from exc
            if inspect.isawaitable(result):
                close = getattr(result, "close", None)
                if callable(close):
                    close()
                raise TypeError(
                    f"system prompt handler from '{plugin or 'unknown'}' returned an awaitable; "
                    "the host prompt waterfall is synchronous"
                )
            if result is not None:
                if not isinstance(result, PromptAssembly):
                    raise TypeError(
                        f"system prompt handler from '{plugin or 'unknown'}' must return "
                        "PromptAssembly or None"
                    )
                assembly = result
        # user:“接口完善”+(插件返回损坏的结构必须在回退边界内报错，已交付结果与插件保留的对象分离)。
        from .prompt_extensions import _order
        if not isinstance(assembly.text, str) or not isinstance(assembly.sections, list):
            raise TypeError("prompt assembly requires string text and a section list")
        for section in assembly.sections:
            if (not isinstance(section, PromptSection) or not isinstance(section.name, str)
                    or not isinstance(section.text, str) or not isinstance(section.metadata, dict)):
                raise TypeError("invalid prompt section")
            _order(section.order)
        return deepcopy(assembly)

    @property
    def handler_count(self) -> int:
        return len(self._handlers)


__all__ = [
    "PromptContext",
    "PromptSection",
    "PromptAssembly",
    "PromptHandler",
    "SystemPromptWaterfall",
]
