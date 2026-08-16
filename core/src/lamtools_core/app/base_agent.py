from __future__ import annotations

import json
import logging
import re
import sys
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
from lamtools_core.runtime.plan import (
    apply_checklist_update as _apply_checklist_update,
    auto_advance_plan as _auto_advance_plan,
    new_plan_revision as _new_plan_revision,
    plan_to_active_plan as _plan_to_active_plan,
)
from lamtools_core.snapshot import reduce_run_item_events
from lamtools_core.tool import ToolCall, ToolContext, ToolResult
from lamtools_core.tool.default_toolbox import ApprovalPolicy, CoreToolbox, build_core_toolbox
from lamtools_core.tool.command_runner import command_shell_prompt
from lamtools_core.tool.loadtools import mode_prompt_line
from lamtools_core.tool.workspace import line_count
from lamtools_core.tool.workspace_files import IMAGE_DATA_URL_METADATA_KEY
from lamtools_core.app.project_context import ProjectContextLoader
from lamtools_core.config.subagent_prompt import load_subagent_guide

_logger = logging.getLogger(__name__)


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


def _find_image_data_url(result: ToolResult) -> str | None:
    """从 tool result 提取 read_file 图片分支产生的 base64 data URL。"""
    candidates: list[Any] = []
    if isinstance(result.metadata, dict):
        candidates.append(result.metadata.get(IMAGE_DATA_URL_METADATA_KEY))
    for artifact in result.artifacts:
        if isinstance(artifact.metadata, dict):
            candidates.append(artifact.metadata.get(IMAGE_DATA_URL_METADATA_KEY))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


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
    model_display_name: str = ""
    instructions: str = "You are a standalone general-purpose agent runtime."
    temperature: float = 0.2
    max_tokens: int | None = None
    thinking_enabled: bool | None = None
    thinking_budget: int | None = None
    reasoning_effort: str = ""
    approval_policy: ApprovalPolicy = "require"
    runtime_controls: dict[str, dict[str, bool]] | None = None
    active_mode: str | None = None  # loadtools.jsonc mode name (e.g. "consider", "execute")
    capability: str = ""  # model input modality: "text" | "multimodal" | "" (unknown)
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
        allow_access_outside_workdir: bool = False,
    ) -> None:
        self.work_root = Path(work_root).resolve()
        self.config = config or CoreBaseAgentConfig()
        self.toolbox = toolbox or build_core_toolbox(
            work_root=self.work_root,
            approval_policy=self.config.approval_policy,
            allow_access_outside_workdir=allow_access_outside_workdir,
        )
        self.verification_policy = verification_policy or VerificationPolicy()
        self._runtime_controls = self.config.runtime_controls or {}
        self._subagent_guide_cache: str | None = None

    def _cached_subagent_guide(self) -> str:
        if self._subagent_guide_cache is None:
            self._subagent_guide_cache = load_subagent_guide(self.work_root)
        return self._subagent_guide_cache

    def _capability_prompt_line(self, deferred_attachments: list[str] | None = None) -> str:
        """Build a system-prompt line describing the model's input modality."""
        cap = (self.config.capability or "").strip().lower()
        if cap == "text":
            # Resolve the default multimodal model from sub-agent settings,
            # falling back to the first multimodal model in the store.
            from lamtools_core.config.subagent_prompt import resolve_default_multimodal_model
            delegate_model = resolve_default_multimodal_model(self.work_root)
            if delegate_model:
                model_hint = f'（指定 model 为 "{delegate_model}"）'
            else:
                model_hint = "（指定 model 为支持图片的模型）"
            base = (
                "当前模型能力: 文本模型（不支持图片/视频/音频输入；这类附件内容不会发送给你，你无法看到图片）。"
                "当用户附带图片且任务需要理解图片内容时，用 sub_agent 委派一个多模态模型"
                f"{model_hint}去查看图片并返回文字描述，再据此继续。"
                "read_file 读取图片文件时同样只返回文件说明（文件名/大小），你不会收到像素内容；"
                "如需理解图片内容，用 sub_agent 委派多模态模型读取同一路径并返回文字描述。"
            )
            if deferred_attachments:
                ids = ", ".join(f'"{i}"' for i in deferred_attachments)
                model_arg = f', model="{delegate_model}"' if delegate_model else ""
                base += (
                    f"\n当前有以下附件你无法直接查看（id: {ids}）。"
                    f"如需理解其内容，立即用 sub_agent(task=\"查看并描述附件内容\", "
                    f"attachments=[{ids}]{model_arg}) 委派查看并返回文字描述。"
                )
            return base
        if cap == "multimodal":
            return (
                "当前模型能力: 多模态模型（支持图片输入）。"
                "使用 read_file 读取图片文件（.png/.jpg/.jpeg/.gif/.webp/.avif/.bmp）时，"
                "会随工具结果直接收到图片像素内容，可直接查看并描述。"
            )
        return ""

    async def on_run_start(self, state: RuntimeState, turn_input: RuntimeTurnInput) -> None:
        state.metadata["agent_id"] = self.config.agent_id
        state.metadata["work_root"] = str(self.work_root)
        for key in ("model_id", "thinking_enabled", "thinking_budget", "shallow_thinking_enabled", "capability", "deferred_attachments", "context_window_tokens", "compact_trigger_tokens", "compact_limit_tokens"):
            if key in turn_input.metadata:
                state.metadata[key] = turn_input.metadata[key]
        if turn_input.user_message:
            state.metadata.setdefault("original_user_message", turn_input.user_message)
        state.metadata.setdefault("activated_mcp_servers", [])
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
            f"当前项目: {state.metadata.get('work_root', '')}, 当前会话: {state.session_id}, 当前模型: {self.config.model_display_name or self.config.model_id}",
            command_shell_prompt(),
            "在有助于完成用户请求时使用可用工具。",
            "创建或修改文件时使用 write_file 或 edit_file。",
            "工作过程中不要破坏项目目录的结构性与整洁度。",
            "当可用技能与任务匹配时使用 load_skill。",
            "收到工具结果后，继续下一步或给出最终回复。",
            "将成功的工具结果视为可复用证据。在对同一文件、URL、进程、端口等资源再次使用不同参数查询之前，先说明确缺失的事实以及现有结果为何不能回答；否则直接复用现有结果。",
            "经过多个纯工具步骤后，简要汇报已确认事实、仍存疑点及下一步，再继续调用工具。保持进度摘要简洁，不重复已有证据。",
            "任务完成后向用户回复简要摘要，最终回复应总结结果并提及重要的保存路径，包括但不限于工作完成情况、范围、产物位置、需用户确认项。",
        ]
        # Model capability line: tells the agent its input modalities so it
        # does not assume image support that the model lacks.
        deferred = list(state.metadata.get("deferred_attachments") or [])
        cap_line = self._capability_prompt_line(deferred)
        if cap_line:
            system_lines.insert(1, cap_line)  # right after the instructions
        # Sub-agent delegation guide (project > global > built-in). Cached on the
        # kit so the markdown file is read at most once per kit lifetime.
        guide = self._cached_subagent_guide()
        if guide:
            system_lines.insert(2, guide)  # inject right after the "当前项目" line
        mode_line = mode_prompt_line(self.toolbox.load_tools, self.config.active_mode)
        if mode_line:
            system_lines.insert(2, mode_line)  # inject right after "当前项目" line
        skill_index = self.toolbox.skill_index()
        if skill_index:
            system_lines.extend(["", skill_index])
        # List available MCP servers for mcp_activate tool
        mcp_caller = getattr(self.toolbox, "mcp_caller", None)
        if mcp_caller is not None and hasattr(mcp_caller, "server_names"):
            servers = mcp_caller.server_names
            if servers:
                system_lines.extend(["", f"Available MCP servers (use mcp_activate to load): {', '.join(servers)}"])
        context_parts = self._build_project_context_parts()
        for part in context_parts:
            system_lines.extend(["", part.content])
        # Inject active plan from state metadata
        if "active_plan" in (state.metadata or {}):
            ap = state.metadata["active_plan"]
            plan_lines = []
            if ap.get("plan_summary"):
                plan_lines.append(f"Summary: {ap['plan_summary']}")
            if ap.get("plan_files"):
                plan_lines.append(f"Planned files: {', '.join(ap['plan_files'])}")
            if ap.get("plan_steps"):
                for s in ap["plan_steps"]:
                    sid = s.get("id", "?")
                    desc = s.get("description", "")
                    status = s.get("status", "pending")
                    plan_lines.append(f"  [{sid}] ({status}) {desc}")
            if plan_lines:
                system_lines.extend(["", "[当前计划 — 逐步执行]", "\n".join(plan_lines)])
        if self.verification_policy.required:
            verification_state = self._verification_state(state)
            system_lines.extend([
                "",
                "此成员要求工具验证证据后方可给出最终回复。使用可产生证据的工具，并基于观察到的结果作答。",
            ])
            repair_prompt = str(verification_state.get("repair_prompt") or "").strip()
            if repair_prompt:
                system_lines.append(f"验证修复要求：{repair_prompt}")
            evidence_call_ids = known_evidence_call_ids(state)
            if evidence_call_ids:
                system_lines.append(
                    "已知成功证据调用 ID 为不可见引用。当工具要求提供 evidence tool_call_id 时，原样复制以下值之一；"
                    "不要添加、删除或规范化前缀："
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
                **(
                    {"reasoning_effort": self.config.reasoning_effort}
                    if self.config.reasoning_effort
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
            # _resolve_empty_stop returns the real exhaustion message in
            # wait_reason; surface it as the visible reply so the run result
            # carries a meaningful failure message.
            reply = wait_reason or "Model stopped with no content after retries."

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
        # Retry budget is injected by the Kernel from LoopPolicy.
        # empty_response_retries=3 → allow attempts 0,1,2 (3 retries), fail on the 4th.
        max_retries = int((state.metadata or {}).get("empty_response_retries", 3) or 0)
        has_delivery = self._detect_delivery_progress(state)
        if attempts < max_retries:
            if state.metadata:
                state.metadata["empty_stop_count"] = attempts + 1
                state.metadata["empty_stop_retry_instruction"] = self._default_empty_retry_instruction(has_delivery)
            return "continue", ""
        return "failed", f"Model stopped with no content after {max_retries} retries."

    def _tool_enabled(self, name: str) -> bool:
        tools = self._runtime_controls.get("tools", {})
        return bool(tools.get(name, True))

    def _filtered_tools(self) -> list[dict[str, Any]]:
        all_tools = self.toolbox.model_tools(active_mode=self.config.active_mode)
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
        evidence = _format_model_tool_evidence(result)
        # C2 共识：hook additional_context 消费链——PreToolUse/PostToolUse
        # hook 写入 call.metadata 的注入内容拼接进模型证据（复用脱敏/截断
        # 渲染器上一步的输出；不再扩展 _MODEL_EVIDENCE_KEYS 以免污染
        # metadata 直通语义）。
        call_metadata = call.metadata if isinstance(call.metadata, dict) else {}
        hook_additional = str(call_metadata.get("hook_additional_context") or "").strip()
        if hook_additional:
            evidence = f"{evidence}\n\n{hook_additional}"
        image_data_url = _find_image_data_url(result)
        if image_data_url and (self.config.capability or "").strip().lower() == "multimodal":
            # 多模态模型：图片以 image_url 块随文本 evidence 一起发送（text 块不含 base64，
            # 12K 截断照旧只作用于文本）。文本模型不发图片块，仅保留 read_file 的说明文字。
            content: str | list[dict[str, Any]] = [
                {"type": "text", "text": evidence},
                {"type": "image_url", "image_url": {"url": image_data_url, "detail": "auto"}},
            ]
        else:
            content = evidence
        return ChatMessage(
            role="tool",
            name=call.name,
            tool_call_id=call.id,
            content=content,
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
        # parse_model_output may have already decided via _resolve_empty_stop
        # (setting decision_hint to "continue" for retry or "failed" when
        # retries are exhausted). Respect that hint *before* checking reply
        # so the empty-stop retry counter and injected retry instructions
        # actually take effect — otherwise the failure message injected by
        # parse_model_output into turn.reply would be mistaken for a real
        # answer and the run would end with "done" instead of "failed".
        if turn.decision_hint == "failed":
            return "failed"
        if turn.decision_hint == "continue":
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

        # Track task plan from write_checklist / update_checklist results
        plan_changed = False
        state.metadata.setdefault("task_plan", {})
        state.metadata.setdefault("active_plan", {})

        for tr in tool_results:
            if tr.name == "write_checklist" and tr.status == "ok" and tr.metadata:
                task_plan = tr.metadata.get("task_plan") or {}
                if isinstance(task_plan, dict):
                    task_plan.setdefault("revision", 0)
                    _new_plan_revision(task_plan, "initial checklist created", "create_plan", {
                        "files": task_plan.get("files", []),
                    })
                    state.metadata["task_plan"] = task_plan
                    plan_changed = True
                break

        for tr in tool_results:
            if tr.name != "update_checklist" or tr.status != "ok" or not tr.metadata:
                continue
            update = tr.metadata.get("checklist_update")
            if isinstance(update, dict):
                current_plan = state.metadata.get("task_plan")
                state.metadata["task_plan"] = _apply_checklist_update(
                    current_plan if isinstance(current_plan, dict) else None,
                    update,
                )
                plan_changed = True

        current_plan = state.metadata.get("task_plan")
        if isinstance(current_plan, dict) and _auto_advance_plan(current_plan, tool_results):
            state.metadata["task_plan"] = current_plan
            plan_changed = True

        if plan_changed and isinstance(state.metadata.get("task_plan"), dict):
            state.metadata["active_plan"] = _plan_to_active_plan(state.metadata["task_plan"])

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
    include_user_plugins: bool = True,
) -> dict[str, Any]:
    from lamtools_core.plugins.engine import HookEngine
    from lamtools_core.plugins.hook_config import HookRegistry
    from lamtools_core.plugins.registry import PluginRegistry, PluginStateStore
    from lamtools_core.plugins.trust import HookTrustStore

    # H 组缺口修复（2026-08-16）：空/None 一律回退默认根集合（含用户级根，
    # 与 plugin.install 默认安装到用户级根的产品语义对齐）；只有非空显式
    # 列表才按调用方指定。include_user_plugins 保留显式覆盖（向后兼容）。
    roots: list[Path] = (
        [Path(item) for item in plugin_roots]
        if plugin_roots
        else default_core_agent_plugin_roots(work_root, include_user_plugins=include_user_plugins)
    )
    # Unified config directory — user-modifiable after packaging
    # (default_core_agent_plugin_roots 已含内置根；传了自定义 plugin_roots
    # 时这里兜底补上，保证内置根永远在扫描链路里 — 缺口 #3 + D3)。
    from lamtools_core.config.root import core_plugins_root
    from lamtools_core.plugins.registry import bundled_plugins_dir

    if core_plugins_root() not in roots:
        roots.insert(0, core_plugins_root())
    if bundled_plugins_dir() not in roots:
        roots.append(bundled_plugins_dir())
    state_store = PluginStateStore(Path(data_dir) / "plugins.jsonc")
    plugins = PluginRegistry(plugin_roots=roots, state_store=state_store).discover()
    enabled_plugins = [plugin for plugin in plugins if plugin.enabled]
    # Plugin code must be importable: handler entries (module:function) are
    # resolved via importlib at toolbox build time, before any plugin code
    # runs — so the enabled plugin roots go on sys.path here (append to the
    # end to avoid shadowing stdlib; plugins are trusted, install = trust).
    for plugin in enabled_plugins:
        root = str(plugin.root)
        if root not in sys.path:
            sys.path.append(root)
    skill_roots = [
        root
        for plugin in enabled_plugins
        for root in plugin.skill_roots
        if root.exists()
    ]
    # 原生工具声明（manifest tools 字段 → PluginToolSpec 列表，按插件
    # 分组保留归属，供装配层补全 spec 时标注 plugin 来源）；
    # 清单解析失败不阻断其他插件，错误随装配结果返回（plugin.list 报状态）。
    plugin_tool_groups: list[dict[str, Any]] = []
    plugin_tool_errors: list[dict[str, Any]] = []
    from lamtools_core.plugins.tools import load_plugin_tools

    for plugin in enabled_plugins:
        declared: list[Any] = []
        for tool_file in plugin.tool_files:
            if not tool_file.exists():
                plugin_tool_errors.append(
                    {"plugin": plugin.name, "path": str(tool_file), "error": "tool file not found"}
                )
                continue
            try:
                declared.extend(load_plugin_tools([tool_file], plugin_root=plugin.root))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                _logger.warning(
                    "[plugins:tools] plugin %s tool manifest unreadable: %s",
                    plugin.name,
                    tool_file,
                    exc_info=True,
                )
                plugin_tool_errors.append(
                    {"plugin": plugin.name, "path": str(tool_file), "error": str(exc)}
                )
        if declared:
            plugin_tool_groups.append(
                {
                    "name": plugin.name,
                    "root": plugin.root,
                    "tools": declared,
                    "dependencies": list(plugin.dependencies),
                }
            )
    hook_registry = HookRegistry(
        project_root=work_root,
        plugins=enabled_plugins,
        trust_store=HookTrustStore(Path(data_dir) / "hook_trust.json"),
    )
    hooks = hook_registry.load()
    return {
        "plugins": enabled_plugins,
        "plugin_roots": roots,
        "data_dir": str(data_dir),
        "skill_roots": skill_roots,
        "plugin_tool_groups": plugin_tool_groups,
        "plugin_tool_errors": plugin_tool_errors,
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
    include_user_plugins: bool = True,
) -> list[Path]:
    from lamtools_core.plugins.registry import (
        bundled_plugins_dir,
        default_project_plugin_root,
        default_user_plugin_root,
    )
    from lamtools_core.config.root import core_plugins_root

    roots: list[Path] = []
    # 用户级根默认纳入扫描（H 组缺口修复：plugin.install 默认装用户级根，
    # 安装即可见；显式 include_user_plugins=False 的调用方不受影响）。
    if include_user_plugins:
        roots.append(default_user_plugin_root())
    roots.append(default_project_plugin_root(work_root))
    # 内置插件根统一纳入扫描（缺口 #3 + D3：包内 bundled 插件）
    roots.append(core_plugins_root())
    roots.append(bundled_plugins_dir())
    return roots


def build_core_plugin_operation_catalog(
    *,
    data_dir: str | Path,
    work_root: str | Path,
    plugin_roots: list[Path | str] | tuple[Path | str, ...] | None = None,
    include_user_plugins: bool = True,
):
    from lamtools_core.plugins.hook_config import HookRegistry
    from lamtools_core.plugins.operations import build_plugin_operation_catalog
    from lamtools_core.plugins.registry import PluginRegistry, PluginStateStore, default_user_plugin_root
    from lamtools_core.plugins.trust import HookTrustStore
    from lamtools_core.skills import SkillRegistry, SkillStateStore
    from lamtools_core.config.root import core_skills_root
    from lamtools_core.composer_commands import default_core_skill_roots

    # H 组缺口修复（2026-08-16）：空/None 一律回退默认根集合（含用户级根，
    # 与 assemble_core_agent_plugins 同语义）；非空显式列表才按调用方指定。
    roots = (
        [Path(item) for item in plugin_roots]
        if plugin_roots
        else default_core_agent_plugin_roots(work_root, include_user_plugins=include_user_plugins)
    )
    # 与 assemble_core_agent_plugins 同款兜底：内置根永远在扫描链路里
    from lamtools_core.config.root import core_plugins_root
    from lamtools_core.plugins.registry import bundled_plugins_dir

    if core_plugins_root() not in roots:
        roots.insert(0, core_plugins_root())
    if bundled_plugins_dir() not in roots:
        roots.append(bundled_plugins_dir())
    data_path = Path(data_dir)
    plugin_state_store = PluginStateStore(data_path / "plugins.jsonc")
    hook_trust_store = HookTrustStore(data_path / "hook_trust.json")
    skill_state_store = SkillStateStore(data_path / "skill_state.json")
    plugin_registry = PluginRegistry(plugin_roots=roots, state_store=plugin_state_store)

    def hook_registry_factory() -> HookRegistry:
        return HookRegistry(
            project_root=work_root,
            plugins=plugin_registry.discover(),
            trust_store=hook_trust_store,
        )

    def skill_registry_factory() -> SkillRegistry:
        return SkillRegistry(
            explicit_roots=[
                core_skills_root(),
                *default_core_skill_roots(),
            ],
        )

    return build_plugin_operation_catalog(
        plugin_registry=plugin_registry,
        plugin_state_store=plugin_state_store,
        hook_registry_factory=hook_registry_factory,
        hook_trust_store=hook_trust_store,
        skill_state_store=skill_state_store,
        skill_registry_factory=skill_registry_factory,
        work_root=work_root,
        data_dir=data_path,
        install_root=default_user_plugin_root(),
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
