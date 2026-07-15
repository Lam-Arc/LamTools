from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lamtools_core.event import (
    CoreEvent,
    RunItemEvent,
    runtime_group_from_event_name,
    runtime_projection_to_run_item_events,
    runtime_summary_from_event_name,
    RuntimeProjectionInput,
)
from lamtools_core.kernel.state import KernelStep, KernelTurn, VerificationResult
from lamtools_core.llm import ChatMessage, LLMRequest, LLMResponse
from lamtools_core.prompt import PromptContext
from lamtools_core.runtime import RuntimeState, RuntimeTurnInput
from lamtools_core.snapshot import reduce_run_item_events
from lamtools_core.tool import ToolCall, ToolResult
from lamtools_core.tool.default_toolbox import ApprovalPolicy, CoreToolbox, build_core_toolbox
from lamtools_core.tool.command_runner import command_shell_prompt
from lamtools_core.tool.workspace import line_count


_MODEL_TOOL_EVIDENCE_LIMIT = 12_000
_MODEL_EVIDENCE_KEYS = (
    "cwd",
    "exit_code",
    "timed_out",
    "error_type",
    "stdout_log",
    "stderr_log",
    "log_path",
)
_MODEL_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*)[^\s]+"),
)


def _redact_model_tool_evidence(value: str) -> str:
    redacted = value
    for pattern in _MODEL_SECRET_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


def _format_model_tool_evidence(result: ToolResult) -> str:
    metadata = result.metadata if isinstance(result.metadata, dict) else {}
    lines = [f"status: {result.status}"]
    if result.content:
        lines.extend(("content:", result.content))
    if result.error:
        lines.append(f"error: {result.error}")
    for key in _MODEL_EVIDENCE_KEYS:
        value = metadata.get(key)
        if value not in (None, ""):
            lines.append(f"{key}: {value}")

    artifact_metadata = next(
        (
            artifact.metadata
            for artifact in result.artifacts
            if artifact.kind == "command_output" and isinstance(artifact.metadata, dict)
        ),
        {},
    )
    content = str(result.content or "")
    if "[stdout]" not in content and artifact_metadata.get("stdout"):
        lines.append(f"stdout: {artifact_metadata['stdout']}")
    if "[stderr]" not in content and artifact_metadata.get("stderr"):
        lines.append(f"stderr: {artifact_metadata['stderr']}")

    rendered = _redact_model_tool_evidence("\n".join(lines))
    if len(rendered) > _MODEL_TOOL_EVIDENCE_LIMIT:
        rendered = rendered[:_MODEL_TOOL_EVIDENCE_LIMIT] + "\n[tool evidence truncated]"
    return rendered


@dataclass(frozen=True)
class CoreBaseAgentConfig:
    model_id: str = ""
    instructions: str = "You are a standalone general-purpose agent runtime."
    temperature: float = 0.2
    max_tokens: int | None = None
    thinking_enabled: bool | None = None
    thinking_budget: int | None = None
    approval_policy: ApprovalPolicy = "require"


class CoreBaseAgentKit:
    name = "core-base-agent"

    def __init__(
        self,
        *,
        work_root: str | Path,
        config: CoreBaseAgentConfig | None = None,
        toolbox: CoreToolbox | None = None,
    ) -> None:
        self.work_root = Path(work_root).resolve()
        self.config = config or CoreBaseAgentConfig()
        self.toolbox = toolbox or build_core_toolbox(
            work_root=self.work_root,
            approval_policy=self.config.approval_policy,
        )

    async def on_run_start(self, state: RuntimeState, turn_input: RuntimeTurnInput) -> None:
        state.metadata["agent_id"] = "core-agent"
        state.metadata["work_root"] = str(self.work_root)
        for key in ("model_id", "thinking_enabled", "thinking_budget", "shallow_thinking_enabled"):
            if key in turn_input.metadata:
                state.metadata[key] = turn_input.metadata[key]
        if turn_input.user_message:
            state.metadata.setdefault("original_user_message", turn_input.user_message)

    async def build_context(
        self,
        state: RuntimeState,
        turn_input: RuntimeTurnInput,
        history: list[ChatMessage],
        step_index: int,
    ) -> PromptContext:
        return PromptContext(
            session_id=state.session_id,
            history=list(history),
            tools=self.toolbox.tool_specs(),
            metadata={"step_index": step_index},
        )

    async def build_model_request(self, state: RuntimeState, context: PromptContext) -> LLMRequest:
        system_lines = [
            self.config.instructions,
            command_shell_prompt(),
            "Use the available tools when they help complete the user's request.",
            "If the user explicitly asks to use a sub-agent, call sub_agent before producing the final result.",
            "When the user assigns a deliverable to a sub-agent, delegate the complete requested deliverable, including any requested file creation or tool action. The Parent Agent should verify the result instead of recreating that deliverable itself.",
            "When asked to create or modify files, use write_file or edit_file.",
            "When asked for one document or one file, create exactly one final file unless the user explicitly asks for multiple files.",
            "After a requested file is successfully written, stop tool use and answer with the saved path and a concise summary.",
            "Use load_skill when an available skill matches the task.",
            "After tool results are returned, continue with the next useful step or final answer.",
            (
                "Treat successful tool results as reusable evidence. Before querying the same file, URL, process, "
                "port, or other resource again with different syntax, state the exact missing fact and why the "
                "existing result does not answer it; otherwise reuse the existing result."
            ),
            (
                "After several tool-only steps, briefly report confirmed facts, remaining uncertainty, and the next "
                "action before calling more tools. Keep this progress note concise and do not repeat prior evidence."
            ),
            "Final answers should summarize the outcome and mention important saved paths.",
        ]
        skill_index = self.toolbox.skill_index()
        if skill_index:
            system_lines.extend(["", skill_index])
        messages = [
            ChatMessage(
                role="system",
                content="\n".join(system_lines),
            ),
            *context.history,
        ]
        return LLMRequest(
            messages=messages,
            model=self.config.model_id,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            tools=self.toolbox.model_tools(),
            tool_choice="auto",
            metadata={
                "core_base_agent": True,
                **(
                    {"thinking_enabled": self.config.thinking_enabled}
                    if self.config.thinking_enabled is not None
                    else {}
                ),
                **(
                    {"thinking_budget": self.config.thinking_budget}
                    if self.config.thinking_budget is not None
                    else {}
                ),
            },
        )

    async def parse_model_output(self, state: RuntimeState, response: LLMResponse) -> KernelTurn:
        calls: list[ToolCall] = []
        for raw in response.tool_calls or []:
            args = raw.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append(
                self.toolbox.prepare_call(
                    ToolCall(
                        id=raw.id or uuid.uuid4().hex,
                        name=raw.name,
                        arguments=args if isinstance(args, dict) else {},
                        raw=raw.raw,
                    )
                )
            )
        return KernelTurn(reply=response.content or "", tool_calls=calls)

    async def execute_tool(self, state: RuntimeState, call: ToolCall) -> ToolResult:
        call.metadata["_runtime_session_id"] = state.session_id
        call.metadata["_runtime_run_id"] = state.run_id
        if call.name == "sub_agent":
            call.metadata["parent_run_id"] = state.run_id
            call.metadata["parent_turn_id"] = str(state.metadata.get("turn_id") or state.run_id)
        result = await self.toolbox.execute(call)
        if result.status == "ok" and call.name in {"write_file", "edit_file"}:
            self._record_written_file(state, result)
        return result

    async def format_tool_result_for_model(
        self,
        state: RuntimeState,
        call: ToolCall,
        result: ToolResult,
    ) -> ChatMessage:
        return ChatMessage(
            role="tool",
            name=call.name,
            tool_call_id=call.id,
            content=_format_model_tool_evidence(result),
        )

    async def verify(
        self,
        state: RuntimeState,
        turn: KernelTurn,
        tool_results: list[ToolResult],
    ) -> VerificationResult:
        passed = not tool_results or all(result.status == "ok" for result in tool_results)
        return VerificationResult(passed=passed, required=bool(tool_results), summary="ok" if passed else "tool failed")

    async def decide_next(
        self,
        state: RuntimeState,
        turn: KernelTurn,
        verification: VerificationResult,
        step: KernelStep,
    ):
        delegated_wait = next(
            (
                result.metadata
                for tool_step in step.tool_steps
                if tool_step.result is not None
                for result in [tool_step.result]
                if (
                    result.name == "sub_agent"
                    and isinstance(result.metadata, dict)
                    and result.metadata.get("decision") == "wait"
                )
            ),
            None,
        )
        if isinstance(delegated_wait, dict):
            pending = delegated_wait.get("pending_approval")
            delegated = delegated_wait.get("delegated_session")
            if isinstance(pending, dict) and isinstance(delegated, dict):
                waiting = delegated_wait.get("pending_waiting_request")
                state.metadata["pending_approval"] = {
                    **pending,
                    "delegated_session": dict(delegated),
                }
                if isinstance(waiting, dict):
                    state.metadata["pending_waiting_request"] = dict(waiting)
                step.metadata["pending_approval"] = dict(state.metadata["pending_approval"])
                return "wait"
        if turn.tool_calls:
            return "continue"
        if turn.reply.strip():
            return "done"
        return "failed"

    async def writeback(
        self,
        state: RuntimeState,
        turn: KernelTurn,
        tool_results: list[ToolResult],
        verification: VerificationResult,
        decision: str,
    ) -> None:
        state.metadata["last_decision"] = decision

    async def on_run_end(self, state: RuntimeState, result: Any) -> None:
        state.metadata["ended_decision"] = result.decision

    def _record_written_file(self, state: RuntimeState, result: ToolResult) -> None:
        raw_path = result.metadata.get("path") if isinstance(result.metadata, dict) else ""
        if not isinstance(raw_path, str) or not raw_path:
            return
        target = (self.work_root / raw_path).resolve()
        record: dict[str, Any] = {"path": str(target)}
        if target.is_file():
            try:
                record["line_count"] = line_count(target.read_text(encoding="utf-8"))
            except OSError:
                record["line_count"] = int(result.metadata.get("new_line_count") or 0)
        state.metadata.setdefault("written_files", []).append(record)
        state.metadata["last_written_path"] = record["path"]
        state.metadata["last_written_line_count"] = int(record.get("line_count") or 0)
        state.metadata["document_path"] = record["path"]
        state.metadata["document_line_count"] = int(record.get("line_count") or 0)


def core_events_to_run_items(
    events: list[CoreEvent],
    *,
    thread_id: str,
    include_transient: bool = False,
) -> list[RunItemEvent]:
    run_items: list[RunItemEvent] = []
    for index, event in enumerate(events, 1):
        if event.metadata.get("delivery") == "transient" and not include_transient:
            continue
        payload = event.payload if isinstance(event.payload, dict) else {}
        event_thread_id = event.session_id or thread_id
        event_run_id = event.run_id or "unknown"
        canonical_prefix = f"{event_thread_id}:turn:"
        event_turn_id = event.turn_id or (
            event_run_id if event_run_id.startswith(canonical_prefix) else f"{canonical_prefix}{event_run_id}"
        )
        text_preview = str(
            payload.get("content")
            or payload.get("summary")
            or payload.get("message")
            or payload.get("error")
            or ""
        )
        fact = RuntimeProjectionInput(
            id=event.event_id,
            thread_id=event_thread_id,
            group=runtime_group_from_event_name(event.name),
            source=event.source or "core-agent",
            phase=event.name,
            status=str(payload.get("status") or ""),
            sequence=event.sequence if event.sequence is not None else index,
            summary=runtime_summary_from_event_name(event.name, payload),
            preview=text_preview,
            full_text=str(payload.get("content") or payload.get("message") or payload.get("error") or ""),
            metadata={
                "payload": payload,
                "run_id": event.run_id,
                "turn_id": event_turn_id,
            },
            created_at=datetime.fromtimestamp(event.timestamp_ms / 1000, timezone.utc),
        )
        projected = runtime_projection_to_run_item_events(fact)
        for item in projected:
            item.seq = item.seq or index
            run_items.append(item)
    return run_items


def core_events_to_snapshot(events: list[CoreEvent], *, thread_id: str) -> dict[str, Any]:
    return reduce_run_item_events(thread_id, core_events_to_run_items(events, thread_id=thread_id))


def assemble_core_agent_plugins(
    *,
    data_dir: str | Path,
    work_root: str | Path,
    plugin_roots: list[Path | str] | tuple[Path | str, ...] | None,
    include_user_plugins: bool = False,
) -> dict[str, Any]:
    from lamtools_core.plugins.engine import HookEngine
    from lamtools_core.plugins.hook_config import HookRegistry
    from lamtools_core.plugins.registry import PluginRegistry, PluginStateStore
    from lamtools_core.plugins.trust import HookTrustStore

    roots = (
        [Path(item) for item in plugin_roots]
        if plugin_roots is not None
        else default_core_agent_plugin_roots(work_root, include_user_plugins=include_user_plugins)
    )
    state_store = PluginStateStore(Path(data_dir) / "plugins.json")
    plugins = PluginRegistry(plugin_roots=roots, state_store=state_store).discover()
    enabled_plugins = [plugin for plugin in plugins if plugin.enabled]
    skill_roots = [
        root
        for plugin in enabled_plugins
        for root in plugin.skill_roots
        if root.exists()
    ]
    hook_registry = HookRegistry(
        project_root=work_root,
        plugins=enabled_plugins,
        trust_store=HookTrustStore(Path(data_dir) / "hook_trust.json"),
    )
    hooks = hook_registry.load()
    return {
        "plugins": enabled_plugins,
        "skill_roots": skill_roots,
        "mcp_files": [
            path
            for plugin in enabled_plugins
            for path in plugin.mcp_files
            if path.exists()
        ],
        "hook_engine": HookEngine(hooks) if hooks else None,
    }


def default_core_agent_plugin_roots(
    work_root: str | Path,
    *,
    include_user_plugins: bool = False,
) -> list[Path]:
    from lamtools_core.plugins.registry import default_project_plugin_root, default_user_plugin_root

    roots: list[Path] = []
    if include_user_plugins:
        roots.append(default_user_plugin_root())
    roots.append(default_project_plugin_root(work_root))
    return roots


def build_core_plugin_operation_catalog(
    *,
    data_dir: str | Path,
    work_root: str | Path,
    plugin_roots: list[Path | str] | tuple[Path | str, ...] | None = None,
    include_user_plugins: bool = False,
):
    from lamtools_core.plugins.hook_config import HookRegistry
    from lamtools_core.plugins.operations import build_plugin_operation_catalog
    from lamtools_core.plugins.registry import PluginRegistry, PluginStateStore
    from lamtools_core.plugins.trust import HookTrustStore

    roots = (
        [Path(item) for item in plugin_roots]
        if plugin_roots is not None
        else default_core_agent_plugin_roots(work_root, include_user_plugins=include_user_plugins)
    )
    data_path = Path(data_dir)
    plugin_state_store = PluginStateStore(data_path / "plugins.json")
    hook_trust_store = HookTrustStore(data_path / "hook_trust.json")
    plugin_registry = PluginRegistry(plugin_roots=roots, state_store=plugin_state_store)

    def hook_registry_factory() -> HookRegistry:
        return HookRegistry(
            project_root=work_root,
            plugins=plugin_registry.discover(),
            trust_store=hook_trust_store,
        )

    return build_plugin_operation_catalog(
        plugin_registry=plugin_registry,
        plugin_state_store=plugin_state_store,
        hook_registry_factory=hook_registry_factory,
        hook_trust_store=hook_trust_store,
    )


__all__ = [
    "assemble_core_agent_plugins",
    "build_core_plugin_operation_catalog",
    "CoreBaseAgentConfig",
    "CoreBaseAgentKit",
    "core_events_to_run_items",
    "core_events_to_snapshot",
    "default_core_agent_plugin_roots",
]
