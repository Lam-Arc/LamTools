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
from lamtools_core.member import VerificationPolicy
from lamtools_core.prompt import PromptContext, PromptPart
from lamtools_core.runtime import RuntimeState, RuntimeTurnInput
from lamtools_core.runtime.evidence import (
    evidence_context_metadata,
    known_evidence_call_ids,
    prune_turn_scoped_evidence,
    remember_evidence,
)
from lamtools_core.snapshot import reduce_run_item_events
from lamtools_core.tool import ToolCall, ToolContext, ToolResult
from lamtools_core.tool.default_toolbox import ApprovalPolicy, CoreToolbox, build_core_toolbox
from lamtools_core.tool.command_runner import command_shell_prompt
from lamtools_core.tool.workspace import line_count
from lamtools_core.app.project_context import ProjectContextLoader


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
    agent_id: str = "core-agent"
    model_id: str = ""
    instructions: str = "You are a standalone general-purpose agent runtime."
    temperature: float = 0.2
    max_tokens: int | None = None
    thinking_enabled: bool | None = None
    thinking_budget: int | None = None
    approval_policy: ApprovalPolicy = "require"
    runtime_controls: dict[str, dict[str, bool]] | None = None
    # Advanced: override the default project context file list.
    # None (default) → uses DEFAULT_PROJECT_CONTEXT_FILES.
    # Prefer load_context.jsonc in the workspace for per-project
    # customization; change this only for member-wide advanced defaults.
    project_context_files: list[tuple[str, int, str]] | None = None
    max_project_context_chars: int = 20000


class CoreBaseAgentKit:
    name = "core-base-agent"

    def __init__(
        self,
        *,
        work_root: str | Path,
        config: CoreBaseAgentConfig | None = None,
        toolbox: CoreToolbox | None = None,
        verification_policy: VerificationPolicy | None = None,
    ) -> None:
        self.work_root = Path(work_root).resolve()
        self.config = config or CoreBaseAgentConfig()
        self.toolbox = toolbox or build_core_toolbox(
            work_root=self.work_root,
            approval_policy=self.config.approval_policy,
        )
        self.verification_policy = verification_policy or VerificationPolicy()
        self._runtime_controls = self.config.runtime_controls or {}

    async def on_run_start(self, state: RuntimeState, turn_input: RuntimeTurnInput) -> None:
        state.metadata["agent_id"] = self.config.agent_id
        state.metadata["work_root"] = str(self.work_root)
        for key in ("model_id", "thinking_enabled", "thinking_budget", "shallow_thinking_enabled"):
            if key in turn_input.metadata:
                state.metadata[key] = turn_input.metadata[key]
        if turn_input.user_message:
            state.metadata.setdefault("original_user_message", turn_input.user_message)
        if self.verification_policy.required:
            self._verification_state(state)

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

    def _build_project_context_parts(self) -> list[PromptPart]:
        loader = ProjectContextLoader(
            file_specs=self.config.project_context_files,
            max_chars_per_file=self.config.max_project_context_chars,
        )
        return loader.to_prompt_parts(self.work_root)

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
        context_parts = self._build_project_context_parts()
        for part in context_parts:
            system_lines.extend(["", part.content])
        if self.verification_policy.required:
            verification_state = self._verification_state(state)
            system_lines.extend([
                "",
                (
                    "This member requires tool-backed verification evidence before a final answer can complete. "
                    "Use an eligible evidence-producing tool and ground the answer in its observed result."
                ),
            ])
            repair_prompt = str(verification_state.get("repair_prompt") or "").strip()
            if repair_prompt:
                system_lines.append(f"Verification repair required: {repair_prompt}")
            evidence_call_ids = known_evidence_call_ids(state)
            if evidence_call_ids:
                system_lines.append(
                    "Known successful evidence call IDs are opaque references. "
                    "When a tool asks for an evidence tool_call_id, copy one of these values exactly; "
                    "do not add, remove, or normalize a prefix: "
                    + json.dumps(evidence_call_ids, ensure_ascii=False)
                )
        empty_stop_retry = (state.metadata or {}).get("empty_stop_retry_instruction")
        if empty_stop_retry and isinstance(empty_stop_retry, str):
            system_lines.extend(["", str(empty_stop_retry)])
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
            tools=self._filtered_tools(),
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
        decision_hint: LoopDecision = "continue"
        wait_reason = ""

        if response.tool_calls:
            if state.metadata:
                state.metadata.pop("empty_stop_count", None)
                state.metadata.pop("empty_stop_retry_instruction", None)
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
        elif response.finish_reason == "stop":
            content = (response.content or "").strip()
            if not content:
                decision_hint, wait_reason = self._resolve_empty_stop(state)
            else:
                if state.metadata:
                    state.metadata.pop("empty_stop_count", None)
                    state.metadata.pop("empty_stop_retry_instruction", None)
                decision_hint = "done"
        elif response.finish_reason == "length":
            decision_hint = "continue"
        else:
            decision_hint = "done"

        reply = response.content or ""
        if decision_hint == "failed" and not reply:
            reply = "Model produced empty output twice with no tool calls."

        return KernelTurn(reply=reply, tool_calls=calls, decision_hint=decision_hint, wait_reason=wait_reason)

    def _detect_delivery_progress(self, state: RuntimeState) -> bool:
        written_files = (state.metadata or {}).get("written_files")
        if isinstance(written_files, list) and any(str(item).strip() for item in written_files):
            return True
        recent_tools = (state.metadata or {}).get("recent_tools")
        if isinstance(recent_tools, list) and any(str(tool) in {"write_file", "edit_file"} for tool in recent_tools):
            return True
        return False

    def _default_empty_retry_instruction(self, has_delivery: bool) -> str:
        if has_delivery:
            return (
                "The previous model turn stopped with no final text and no tool calls. "
                "Deliverables already exist, so provide a concise visible final answer "
                "summarizing completed files, verification, and any caveats. Do not call "
                "more tools unless required to verify the final answer."
            )
        return (
            "The previous model turn stopped with no final text and no tool calls. "
            "Continue the task now: either call the needed tools to create and verify "
            "deliverables, or provide a visible failure reason if the task cannot proceed."
        )

    def _resolve_empty_stop(self, state: RuntimeState) -> tuple[LoopDecision, str]:
        attempts = int((state.metadata or {}).get("empty_stop_count", 0))
        has_delivery = self._detect_delivery_progress(state)
        if attempts <= 0:
            if state.metadata:
                state.metadata["empty_stop_count"] = 1
                state.metadata["empty_stop_retry_instruction"] = self._default_empty_retry_instruction(has_delivery)
            return "continue", ""
        if state.metadata:
            state.metadata["empty_stop_count"] = attempts + 1
        return "failed", "Model stopped twice with no content and no tools."

    def _tool_enabled(self, name: str) -> bool:
        tools = self._runtime_controls.get("tools", {})
        return bool(tools.get(name, True))

    def _filtered_tools(self) -> list[dict[str, Any]]:
        all_tools = self.toolbox.model_tools()
        controls = self._runtime_controls.get("tools", {})
        if not controls:
            return all_tools
        return [tool for tool in all_tools if self._tool_enabled(str(tool.get("function", {}).get("name", "")))]

    async def execute_tool(self, state: RuntimeState, call: ToolCall) -> ToolResult:
        routed = await self._pre_dispatch(state, call)
        if routed is not None:
            return routed

        call.metadata["_runtime_session_id"] = state.session_id
        call.metadata["_runtime_run_id"] = state.run_id
        if call.name == "sub_agent":
            call.metadata["parent_run_id"] = state.run_id
            call.metadata["parent_turn_id"] = str(state.metadata.get("turn_id") or state.run_id)
        result = await self.toolbox.execute(
            call,
            ToolContext(
                session_id=state.session_id,
                run_id=state.run_id,
                work_root=str(self.work_root),
                state=state,
                metadata=evidence_context_metadata(state),
            ),
        )
        await self._post_dispatch(state, call, result)
        return result

    async def _pre_dispatch(self, state: RuntimeState, call: ToolCall) -> ToolResult | None:
        if call.name == "invalid_tool_call":
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error="模型返回了无效工具调用：工具名为空。",
                content="请重新选择一个已注册工具，并提供完整参数。",
                metadata=dict(call.arguments if isinstance(call.arguments, dict) else {}),
            )
        return None

    async def _post_dispatch(
        self, state: RuntimeState, call: ToolCall, result: ToolResult
    ) -> None:
        if result.status == "ok":
            activated_goal_id = str(result.metadata.get("activate_goal_id") or "").strip()
            if activated_goal_id:
                state.metadata["goal_id"] = activated_goal_id
        if result.status == "ok" and call.name in {"write_file", "edit_file"}:
            self._record_written_file(state, result)

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
        passed_tools = all(result.status == "ok" for result in tool_results)
        if not self.verification_policy.required:
            passed = not tool_results or passed_tools
            return VerificationResult(
                passed=passed,
                required=bool(tool_results),
                summary="ok" if passed else "tool failed",
            )

        verification_state = self._verification_state(state)
        evidence = verification_state.setdefault("evidence", [])
        known_call_ids = {
            str(item.get("call_id") or "")
            for item in evidence
            if isinstance(item, dict)
        }
        for result in tool_results:
            record = self._evidence_record(result)
            if record is None or record["call_id"] in known_call_ids:
                continue
            evidence.append(record)
            known_call_ids.add(record["call_id"])
            if record.get("evidence_scope") != "turn":
                remember_evidence(
                    state,
                    [record],
                    run_id=state.run_id,
                    turn_id=str(state.metadata.get("turn_id") or state.run_id),
                )

        minimum_evidence = self._policy_positive_int("minimum_evidence", default=1)
        evidence_count = len(evidence)
        evidence_sufficient = evidence_count >= minimum_evidence
        natural_completion = not turn.tool_calls and bool(turn.reply.strip())
        attempt = int(verification_state.get("attempt") or 0)
        if natural_completion and (not passed_tools or not evidence_sufficient):
            attempt += 1
            verification_state["attempt"] = attempt

        passed = passed_tools and evidence_sufficient
        if passed:
            verification_state.pop("repair_prompt", None)
            summary = f"verification evidence satisfied ({evidence_count}/{minimum_evidence})"
            repair_prompt = ""
        elif not passed_tools:
            summary = "verification tool failed"
            repair_prompt = "Resolve the failed tool result and obtain successful verification evidence."
        else:
            summary = f"verification evidence missing ({evidence_count}/{minimum_evidence})"
            repair_prompt = str(
                self.verification_policy.metadata.get("repair_instruction")
                or "Obtain tool-backed evidence before making the final claim."
            ).strip()
        if repair_prompt:
            verification_state["repair_prompt"] = repair_prompt

        return VerificationResult(
            passed=passed,
            required=True,
            summary=summary,
            repair_prompt=repair_prompt,
            attempt=attempt,
            max_attempts=self._policy_positive_int("max_attempts", default=2),
            metadata={
                "policy": self.verification_policy.name,
                "evidence_count": evidence_count,
                "minimum_evidence": minimum_evidence,
                "evidence": list(evidence),
            },
        )

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
            if verification.required and not verification.passed:
                if verification.attempt >= verification.max_attempts:
                    state.metadata["pending_waiting_request"] = {
                        "request_kind": "verification",
                        "message": (
                            "Required verification evidence was not produced. "
                            "Provide a source or guidance to continue."
                        ),
                        "verification": verification.metadata,
                    }
                    return "wait"
                return "continue"
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

    def _verification_state(self, state: RuntimeState) -> dict[str, Any]:
        turn_scoped_tools = {
            spec.name
            for spec in self.toolbox.tool_specs()
            if str(spec.metadata.get("evidence_scope") or "") == "turn"
        }
        prune_turn_scoped_evidence(state, tool_names=turn_scoped_tools)
        raw = state.metadata.get("member_verification")
        if not isinstance(raw, dict) or raw.get("run_id") != state.run_id:
            if isinstance(raw, dict):
                remember_evidence(
                    state,
                    raw.get("evidence"),
                    run_id=str(raw.get("run_id") or ""),
                    turn_id=str(raw.get("run_id") or ""),
                )
            raw = {"run_id": state.run_id, "attempt": 0, "evidence": []}
            state.metadata["member_verification"] = raw
        return raw

    def _policy_positive_int(self, key: str, *, default: int) -> int:
        value = self.verification_policy.metadata.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        return default

    def _evidence_record(self, result: ToolResult) -> dict[str, str] | None:
        if result.status != "ok" or (not str(result.content or "").strip() and not result.artifacts):
            return None
        spec = next((item for item in self.toolbox.tool_specs() if item.name == result.name), None)
        category = str(spec.metadata.get("category") or "") if spec is not None else ""
        evidence_scope = str(spec.metadata.get("evidence_scope") or "") if spec is not None else ""
        metadata = self.verification_policy.metadata
        raw_tools = metadata.get("evidence_tools")
        allowed_tools = {
            str(item).strip()
            for item in raw_tools
            if str(item).strip()
        } if isinstance(raw_tools, (list, tuple, set)) else set()
        raw_categories = metadata.get("evidence_categories")
        allowed_categories = {
            str(item).strip()
            for item in raw_categories
            if str(item).strip()
        } if isinstance(raw_categories, (list, tuple, set)) else set()
        if allowed_tools or allowed_categories:
            if result.name not in allowed_tools and category not in allowed_categories:
                return None
        record = {
            "call_id": str(result.call_id or result.name),
            "tool": result.name,
            "category": category,
        }
        if evidence_scope:
            record["evidence_scope"] = evidence_scope
        return record

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
