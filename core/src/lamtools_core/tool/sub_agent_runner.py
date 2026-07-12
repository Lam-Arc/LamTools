from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from lamtools_core.agent import SUB_AGENT_TOOL_NAME
from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
from lamtools_core.event import CollectingEventSink
from lamtools_core.kernel import CoreLoopKernel, LoopPolicy
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeTurnInput
from lamtools_core.tool import ToolSpec
from lamtools_core.tool.default_toolbox import ApprovalPolicy, DEFAULT_TOOL_ORDER, build_core_toolbox
from lamtools_core.tool.mcp_tools import MCPToolCaller
from lamtools_core.tool.sub_agent import (
    SubAgentDefinition,
    definition_map,
    normalize_agent_key,
    parse_sub_agent_definition,
)


class KernelSubAgentRunner:
    def __init__(
        self,
        *,
        work_root: str | Path,
        llm_client: Any,
        model_id: str = "",
        instructions: str = "",
        approval_policy: ApprovalPolicy = "require",
        loaded_skill_roots: set[Path] | None = None,
        agent_roots: list[Path | str] | tuple[Path | str, ...] | None = None,
        mcp_caller: MCPToolCaller | None = None,
        mcp_tool_specs: list[ToolSpec] | None = None,
    ) -> None:
        self.work_root = Path(work_root)
        self.llm_client = llm_client
        self.model_id = model_id
        self.instructions = instructions or (
            "You are a delegated sub-agent. Complete only the delegated task, "
            "return a concise result, and do not call other sub-agents."
        )
        self.approval_policy = approval_policy
        self.loaded_skill_roots = set(loaded_skill_roots or set())
        self.agent_roots = tuple(Path(item) for item in agent_roots or ())
        self.mcp_caller = mcp_caller
        self.mcp_tool_specs = list(mcp_tool_specs or [])

    async def run(
        self,
        *,
        task: str,
        agent: str = "",
        model: str = "",
        expected_output: str = "",
        context: Any = None,
    ) -> str:
        definition = self._definition_for(agent)
        allowed_tools = set(definition.tools) if definition is not None and definition.tools else None
        disabled_tools = {SUB_AGENT_TOOL_NAME}
        if allowed_tools is not None:
            all_tool_names = {*DEFAULT_TOOL_ORDER, *{spec.name for spec in self.mcp_tool_specs}}
            disabled_tools.update(name for name in all_tool_names if name not in allowed_tools)
        toolbox = build_core_toolbox(
            work_root=self.work_root,
            approval_policy=self.approval_policy,
            loaded_skill_roots=self.loaded_skill_roots,
            mcp_caller=self.mcp_caller,
            mcp_tool_specs=self.mcp_tool_specs,
            disabled_tools=disabled_tools,
        )
        kernel = CoreLoopKernel(
            kit=CoreBaseAgentKit(
                work_root=self.work_root,
                config=CoreBaseAgentConfig(
                    model_id=(definition.model if definition is not None and definition.model else model or self.model_id),
                    instructions=self._instructions(
                        agent=agent,
                        expected_output=expected_output,
                        definition=definition,
                    ),
                    approval_policy=self.approval_policy,
                ),
                toolbox=toolbox,
            ),
            llm_client=self.llm_client,
            state_store=InMemoryRuntimeStateStore(),
            event_sink=CollectingEventSink(),
            policy=LoopPolicy(model_timeout_seconds=360, model_retries=3, persist_steps=True),
        )
        result = await kernel.run(
            RuntimeTurnInput(
                user_message=self._message(task=task, expected_output=expected_output, context=context),
                metadata={"session_id": f"core-sub-agent-{uuid.uuid4().hex[:8]}"},
            )
        )
        if result.message:
            return result.message
        if result.error:
            return f"SUB_AGENT ERROR: {result.error}"
        return ""

    def _instructions(
        self,
        *,
        agent: str,
        expected_output: str,
        definition: SubAgentDefinition | None,
    ) -> str:
        parts = [self.instructions]
        if definition is not None:
            parts.append(f"Sub-agent role: {definition.role}.")
            if definition.developer_instructions:
                parts.append(definition.developer_instructions)
        elif agent:
            parts.append(f"Sub-agent role: {agent}.")
        if expected_output:
            parts.append(f"Expected output: {expected_output}.")
        return "\n".join(parts)

    def _message(self, *, task: str, expected_output: str, context: Any) -> str:
        parts = [f"Delegated task:\n{task.strip()}"]
        if expected_output:
            parts.append(f"Expected output:\n{expected_output.strip()}")
        if context is not None:
            if isinstance(context, str):
                rendered = context
            else:
                rendered = json.dumps(context, ensure_ascii=False, indent=2)
            parts.append(f"Context:\n{rendered}")
        return "\n\n".join(parts)

    def _definition_for(self, agent: str) -> SubAgentDefinition | None:
        key = normalize_agent_key(agent)
        if not key:
            return None
        definitions: list[SubAgentDefinition] = []
        for root in self._candidate_agent_roots():
            if not root.exists() or not root.is_dir():
                continue
            for path in sorted(root.glob("*.md")):
                definition = parse_sub_agent_definition(path, source=str(root))
                if definition is not None:
                    definitions.append(definition)
        return definition_map(tuple(definitions)).get(key)

    def _candidate_agent_roots(self) -> list[Path]:
        roots = [self.work_root / ".lamtools" / "agents", *self.agent_roots]
        seen: set[Path] = set()
        unique: list[Path] = []
        for root in roots:
            resolved = root.resolve() if root.exists() else root
            if resolved in seen:
                continue
            seen.add(resolved)
            unique.append(root)
        return unique


__all__ = ["KernelSubAgentRunner"]
