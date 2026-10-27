"""System-prompt waterfall for plugins.

The upstream DSH host exposes a ``system-prompt/assemble`` waterfall: plugins
receive the assembled prompt, may append or replace sections, and return the
new assembly.  LamTools' prompt assembly is synchronous, so the host-side
contract is a synchronous waterfall.  A handler that returns an awaitable is
rejected with a clear error instead of being silently ignored.

The waterfall is deliberately independent from the plugin manifest: a backend
registers a handler at runtime (and unregisters it on stop), which keeps
prompt text out of global config and lets a plugin scope its section by
agent/session.
"""

from __future__ import annotations

import inspect
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
    order: int
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
        order: int = 100,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        text = str(text or "")
        if not text.strip():
            return
        self.sections.append(
            PromptSection(name=str(name), order=int(order), text=text, metadata=dict(metadata or {}))
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
        self._handlers: list[tuple[int, int, str, PromptHandler]] = []
        self._sequence = 0

    def register(
        self,
        handler: PromptHandler,
        *,
        plugin: str = "",
        order: int = 100,
    ) -> Callable[[], None]:
        if not callable(handler):
            raise TypeError("system prompt handler must be callable")
        self._sequence += 1
        entry = (int(order), self._sequence, str(plugin or ""), handler)
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
        for _order, _sequence, plugin, handler in sorted(self._handlers, key=lambda item: (item[0], item[1])):
            try:
                result = handler(context, assembly)
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
        return assembly

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
