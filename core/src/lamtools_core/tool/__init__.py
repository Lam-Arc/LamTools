"""Tool protocol types and registry."""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from lamtools_core.llm import LLMUsage

ToolResultStatus = Literal["ok", "failed", "skipped", "blocked"]


@dataclass
class ToolSpec:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    permission: str = "unspecified"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "permission": self.permission,
        }
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    goal: str = ""
    # OpenAI Codex-style approval flag: when True, Kernel emits
    # runtime.approval_request before execution. Kit is responsible for
    # deciding whether to block, skip, or proceed in execute_tool.
    requires_approval: bool = False
    raw: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
        }
        if self.reason:
            d["reason"] = self.reason
        if self.goal:
            d["goal"] = self.goal
        if self.requires_approval:
            d["requires_approval"] = True
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class ToolArtifact:
    kind: str
    uri: str = ""
    content: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "uri": self.uri, "content": self.content}
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class ToolResult:
    call_id: str
    name: str
    status: ToolResultStatus = "ok"
    content: str = ""
    error: str = ""
    artifacts: list[ToolArtifact] = field(default_factory=list)
    usage: LLMUsage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "call_id": self.call_id,
            "name": self.name,
            "status": self.status,
            "content": self.content,
        }
        if self.error:
            d["error"] = self.error
        if self.artifacts:
            d["artifacts"] = [a.to_dict() for a in self.artifacts]
        if self.usage is not None:
            d["usage"] = self.usage.to_dict()
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class ToolError:
    call_id: str
    name: str
    error: str
    recoverable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "call_id": self.call_id,
            "name": self.name,
            "error": self.error,
            "recoverable": self.recoverable,
        }
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class ToolPermission:
    name: str
    level: str = "unspecified"
    auto_approve: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolContext:
    session_id: str = ""
    run_id: str = ""
    work_root: str = ""
    state: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ToolExecutorProtocol(Protocol):
    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult: ...


ToolExecutor = ToolExecutorProtocol


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._executors: dict[str, ToolExecutorProtocol] = {}

    def register(self, spec: ToolSpec, executor: ToolExecutorProtocol | None = None) -> None:
        self._specs[spec.name] = spec
        if executor is not None:
            self._executors[spec.name] = executor

    def list(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def get_executor(self, name: str) -> ToolExecutorProtocol | None:
        return self._executors.get(name)

    def has(self, name: str) -> bool:
        return name in self._specs

    def unregister(self, name: str) -> None:
        self._specs.pop(name, None)
        self._executors.pop(name, None)


__all__ = [
    "ToolResultStatus",
    "ToolSpec",
    "ToolCall",
    "ToolArtifact",
    "ToolResult",
    "ToolError",
    "ToolPermission",
    "ToolContext",
    "ToolExecutor",
    "ToolExecutorProtocol",
    "ToolRegistry",
    # loadtools
    "LoadToolMode",
    "LoadTools",
    "ModeName",
    "default_load_tools",
    "load_loadtools",
    "mode_names",
    "mode_prompt_line",
    "mode_tool_set",
]
