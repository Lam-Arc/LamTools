from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable

from lamtools_core.event import CoreEvent
from lamtools_core.tool import ToolCall, ToolResult
from lamtools_core.tool.default_toolbox import DEFAULT_TOOL_ORDER, CoreToolbox, build_core_toolbox

from app.core.writer import management_tools
from app.core.writer.read_tools import ReadOnlyToolExecutor

_DEFAULT_COMMAND_TIMEOUT = 120
_DEFAULT_MAX_LIST_ITEMS = 100
_DEFAULT_MAX_TEXT_LENGTH = 50_000
_DEFAULT_MAX_SEARCH_RESULTS = 50
_CORE_EXECUTOR_TOOL_NAMES = tuple(
    name for name in DEFAULT_TOOL_ORDER
    if name not in {"mcp_tool"}
)


class ReadWriteToolExecutor(ReadOnlyToolExecutor):
    """Writer default tool assembly over Core toolkits and Writer policy tools."""

    def __init__(
        self,
        work_root: str | Path,
        *,
        max_list_items: int = _DEFAULT_MAX_LIST_ITEMS,
        max_text_length: int = _DEFAULT_MAX_TEXT_LENGTH,
        max_search_results: int = _DEFAULT_MAX_SEARCH_RESULTS,
        command_timeout: int = _DEFAULT_COMMAND_TIMEOUT,
        core_event_callback: Callable[[CoreEvent], Awaitable[None]] | None = None,
        sub_agent_runner: Any | None = None,
    ) -> None:
        super().__init__(
            work_root,
            max_list_items=max_list_items,
            max_text_length=max_text_length,
            max_search_results=max_search_results,
        )
        self._command_timeout = command_timeout
        self._core_event_callback = core_event_callback
        self._core_toolbox: CoreToolbox = build_core_toolbox(
            work_root=self._work_root,
            max_list_items=max_list_items,
            max_text_length=max_text_length,
            max_search_results=max_search_results,
            command_timeout=self._command_timeout,
            skill_registry=self._skills,
            core_event_callback=self._core_event_callback,
            sub_agent_runner=sub_agent_runner,
        )

    def as_dict(self) -> dict[str, Callable[[ToolCall], Awaitable[ToolResult]]]:
        base = {name: self._core_handler(name) for name in _CORE_EXECUTOR_TOOL_NAMES}
        base["request_commit_review"] = management_tools.request_commit_review
        base["write_checklist"] = management_tools.write_checklist
        base["update_checklist"] = management_tools.update_checklist
        base["verify_design"] = self.verify_design
        base["inspect_project"] = self.inspect_project
        return base

    def _core_handler(self, tool_name: str) -> Callable[[ToolCall], Awaitable[ToolResult]]:
        async def handle(call: ToolCall) -> ToolResult:
            return await self._execute_core_tool(tool_name, call)

        return handle

    async def _execute_core_tool(self, tool_name: str, call: ToolCall) -> ToolResult:
        self._core_toolbox.skill_registry = self._skills
        if call.name != tool_name:
            call = ToolCall(
                id=call.id,
                name=tool_name,
                arguments=call.arguments,
                reason=call.reason,
                goal=call.goal,
                requires_approval=call.requires_approval,
                raw=call.raw,
                metadata=dict(call.metadata),
            )
        return await self._core_toolbox.execute(call)

    async def read_file(self, call: ToolCall) -> ToolResult:
        return await self._execute_core_tool("read_file", call)

    async def list_dir(self, call: ToolCall) -> ToolResult:
        return await self._execute_core_tool("list_dir", call)

    async def search_files(self, call: ToolCall) -> ToolResult:
        return await self._execute_core_tool("search_files", call)

    async def search_content(self, call: ToolCall) -> ToolResult:
        return await self._execute_core_tool("search_content", call)

    async def load_skill(self, call: ToolCall) -> ToolResult:
        return await self._execute_core_tool("load_skill", call)

    async def write_file(self, call: ToolCall) -> ToolResult:
        return await self._execute_core_tool("write_file", call)

    async def edit_file(self, call: ToolCall) -> ToolResult:
        return await self._execute_core_tool("edit_file", call)

    async def run_command(self, call: ToolCall) -> ToolResult:
        return await self._execute_core_tool("run_command", call)

    async def run_tests(self, call: ToolCall) -> ToolResult:
        return await self._execute_core_tool("run_tests", call)

    async def git_status(self, call: ToolCall) -> ToolResult:
        return await self._execute_core_tool("git_status", call)

    async def git_diff(self, call: ToolCall) -> ToolResult:
        return await self._execute_core_tool("git_diff", call)

    async def web_search(self, call: ToolCall) -> ToolResult:
        return await self._execute_core_tool("web_search", call)

    async def web_fetch(self, call: ToolCall) -> ToolResult:
        return await self._execute_core_tool("web_fetch", call)

    async def browser_check(self, call: ToolCall) -> ToolResult:
        return await self._execute_core_tool("browser_check", call)

    async def request_commit_review(self, call: ToolCall) -> ToolResult:
        return await management_tools.request_commit_review(call)

    async def write_checklist(self, call: ToolCall) -> ToolResult:
        return await management_tools.write_checklist(call)

    async def update_checklist(self, call: ToolCall) -> ToolResult:
        return await management_tools.update_checklist(call)

    async def verify_design(self, call: ToolCall) -> ToolResult:
        return await management_tools.verify_design(call, work_root=self._work_root)


def resolve_tool_executor(
    tool_executor: dict[str, Callable[..., Awaitable[ToolResult]]]
    | Callable[[ToolCall], Awaitable[ToolResult]]
    | None,
    work_root: str | None,
    core_event_callback: Callable[[CoreEvent], Awaitable[None]] | None = None,
    operation_executor: Any | None = None,
    sub_agent_runner: Any | None = None,
) -> dict[str, Callable[..., Awaitable[ToolResult]]] | Callable[[ToolCall], Awaitable[ToolResult]] | None:
    if tool_executor is None:
        if work_root is None:
            return None
        return ReadWriteToolExecutor(work_root, core_event_callback=core_event_callback, sub_agent_runner=sub_agent_runner).as_dict()

    if callable(tool_executor) and not isinstance(tool_executor, dict):
        return tool_executor

    if work_root is None:
        return tool_executor

    defaults = ReadWriteToolExecutor(work_root, core_event_callback=core_event_callback, sub_agent_runner=sub_agent_runner).as_dict()
    return {**defaults, **tool_executor}


__all__ = ["ReadWriteToolExecutor", "resolve_tool_executor"]
