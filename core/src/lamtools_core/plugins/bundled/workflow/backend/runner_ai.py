"""Model and agent node execution through host adapters."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import re
from typing import Any
from .models import WorkflowNode, _as_int
from .runner_context import WorkflowExecutionContext


async def _execute_ai(
    runner, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str,
    execution_context: WorkflowExecutionContext | None = None,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Unified AI node. ``config.mode`` selects the execution strategy:

    * ``single`` (default) — one LLM completion call.
    * ``loop`` — self-judging loop: the model prefixes its final answer
      with ``[DONE]``; iterate up to ``loop_max_iterations``.
    * ``agent`` — full sub-agent with tools and multi-turn decision.
    """
    cfg = node.config
    mode = str(cfg.get("mode") or "single")
    if mode == "agent":
        return await runner._execute_ai_agent(
            node, bound_inputs, work_root, execution_context, audit=audit
        )
    return await runner._execute_ai_llm(
        node, bound_inputs, work_root, mode == "loop", execution_context, audit=audit
    )


async def _execute_ai_llm(
    runner, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str, is_loop: bool,
    execution_context: WorkflowExecutionContext | None = None,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .runner_graph import SKIP_SENTINEL
    from .runner_process import _normalise_type, _response_content
    from .runner_values import _execution_model_id, _model_audit_metadata, _serialize_prompt_value
    cfg = node.config
    instruction = str(cfg.get("instruction") or cfg.get("system_prompt") or "")
    output_format_text = str(cfg.get("output_format_text") or "")
    model_id = str(cfg.get("model_id") or _execution_model_id(execution_context) or "")
    temperature = cfg.get("temperature")
    reasoning_effort = str(cfg.get("reasoning_effort") or "")
    max_tokens = cfg.get("max_tokens")
    top_p = cfg.get("top_p")

    if runner.model_invoker is None:
        raise RuntimeError("AI node requires a model invoker (none configured)")
    from lamtools_core.llm import ChatMessage, LLMRequest

    out_ports = node.output_ports()
    structured = bool(out_ports)

    def _interpolate(text: str) -> str:
        def _repl(m: re.Match) -> str:
            key = m.group(1).strip()
            val = bound_inputs.get(key)
            if val is None or val == SKIP_SENTINEL:
                return ""
            return _serialize_prompt_value(val) if not isinstance(val, str) else val
        return re.sub(r"\{\{(\w+)\}\}", _repl, text)

    instruction_rendered = _interpolate(instruction)
    has_tokens = "{{" in instruction and instruction_rendered != instruction
    system_parts: list[str] = [instruction_rendered]
    if output_format_text:
        system_parts.append(f"Output format:\n{output_format_text}")
    if structured:
        field_desc = ", ".join(
            f"{p.name}({_normalise_type(p.type)})"
            + (f": {p.description}" if p.description else "")
            for p in out_ports
        )
        system_parts.append(
            f"You MUST respond with a single JSON object containing these fields: {field_desc}. "
            "Do not wrap it in markdown fences. Output only the JSON."
        )
    system_prompt = "\n\n".join(p for p in system_parts if p).strip()

    if has_tokens:
        user_content = "(rendered from template — see system prompt)" if not bound_inputs else "(inputs embedded in instruction)"
    else:
        context_lines = [f"- {k}: {_serialize_prompt_value(v)}" for k, v in bound_inputs.items() if v is not None and v != SKIP_SENTINEL]
        user_content = "\n".join(context_lines) if context_lines else "(no additional input)"

    messages: list[ChatMessage] = []
    if system_prompt:
        messages.append(ChatMessage(role="system", content=system_prompt))
    messages.append(ChatMessage(role="user", content=user_content))

    response_format: dict[str, Any] | None = {"type": "json_object"} if structured else None
    max_iter = max(1, _as_int(cfg.get("loop_max_iterations"), default=3)) if is_loop else 1

    transcript = list(messages)
    last_content = ""
    for i in range(max_iter):
        request = LLMRequest(
            messages=transcript,
            model=model_id,
            temperature=float(temperature) if temperature is not None else None,
            max_tokens=int(max_tokens) if max_tokens is not None else None,
            top_p=float(top_p) if top_p is not None else None,
            response_format=response_format,
            metadata={
                **({"reasoning_effort": reasoning_effort} if reasoning_effort else {}),
                **(execution_context.metadata() if execution_context else {}),
            },
        )
        response = await runner.model_invoker.invoke(
            request,
            context=execution_context,
            attachments=list(execution_context.attachments) if execution_context else [],
            runtime_snapshot=execution_context.runtime_snapshot if execution_context else None,
            snapshot=execution_context.snapshot if execution_context else None,
            environment=dict(execution_context.environment) if execution_context else {},
            capabilities=dict(execution_context.capabilities) if execution_context else {},
            trace_id=execution_context.trace_id if execution_context else "",
            lineage=list(execution_context.lineage) if execution_context else [],
        )
        if audit is not None:
            audit.update(_model_audit_metadata(response, model_id=model_id, rounds=i + 1))
        last_content = _response_content(response)
        if is_loop and "[DONE]" in last_content:
            last_content = last_content.replace("[DONE]", "").strip()
            break
        if is_loop:
            transcript.append(ChatMessage(role="assistant", content=last_content))
            transcript.append(
                ChatMessage(role="user", content="If the result is final, prefix your next message with [DONE]. Otherwise continue refining.")
            )
    return runner._split_or_fallback(node, last_content)


async def _execute_ai_agent(
    runner, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str,
    execution_context: WorkflowExecutionContext | None = None,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .runner_cancellation import _call_with_supported_kwargs
    from .runner_graph import SKIP_SENTINEL
    from .runner_process import _normalise_type
    from .runner_values import _agent_audit_metadata, _execution_model_id, _inherited_allowed_tools, _serialize_prompt_value, _summarize
    cfg = node.config
    goal = str(cfg.get("instruction") or cfg.get("goal") or "")
    out_ports = node.output_ports()
    structured = bool(out_ports)

    def _interpolate(text: str) -> str:
        def _repl(m: re.Match) -> str:
            val = bound_inputs.get(m.group(1).strip())
            if val is None or val == SKIP_SENTINEL:
                return ""
            return _serialize_prompt_value(val) if not isinstance(val, str) else val
        return re.sub(r"\{\{(\w+)\}\}", _repl, text)

    goal_rendered = _interpolate(goal)
    context_lines = [f"- {k}: {_serialize_prompt_value(v)}" for k, v in bound_inputs.items() if v is not None and v != SKIP_SENTINEL and f"{{{{{k}}}}}" not in goal]
    task = goal_rendered + ("\n\nContext:\n" + "\n".join(context_lines) if context_lines else "")
    if structured:
        field_desc = ", ".join(f"{p.name}({_normalise_type(p.type)})" for p in out_ports)
        task += (
            f"\n\nYou MUST finish with a single JSON object containing these fields: {field_desc}. "
            "Output only the JSON."
        )
    raw_allowed = cfg.get("tools") or cfg.get("allowed_tools")
    allowed_tools = (
        [str(item) for item in raw_allowed if str(item).strip()]
        if isinstance(raw_allowed, list)
        else None
    )
    # Child agents inherit the parent's authority.  A node may narrow an
    # allow-list, but it cannot request tools outside a parent capability
    # declaration.
    inherited_allowed = _inherited_allowed_tools(execution_context)
    if inherited_allowed is not None:
        if allowed_tools is None:
            allowed_tools = list(inherited_allowed)
        else:
            allowed_tools = [name for name in allowed_tools if name in inherited_allowed]
    if runner.agent_invoker is None:
        raise RuntimeError("AI agent mode requires an agent invoker (none configured)")
    kwargs: dict[str, Any] = {
        "task": task, "agent": str(cfg.get("agent") or ""),
        "model": str(cfg.get("model_id") or _execution_model_id(execution_context) or ""), "mode": str(cfg.get("mode") or ""),
        "attachments": list(execution_context.attachments) if execution_context else [],
        "allowed_tools": allowed_tools,
        "context": execution_context,
        "runtime_snapshot": execution_context.runtime_snapshot if execution_context else None,
        "snapshot": execution_context.snapshot if execution_context else None,
        "environment": dict(execution_context.environment) if execution_context else {},
        "capabilities": dict(execution_context.capabilities) if execution_context else {},
        "permissions": dict(execution_context.permissions) if execution_context else {},
        "trace_id": execution_context.trace_id if execution_context else "",
        "lineage": list(execution_context.lineage) if execution_context else [],
    }
    if execution_context is not None:
        kwargs.update({
            "parent_call_id": execution_context.parent_call_id or node.id,
            "parent_run_id": execution_context.parent_run_id,
            "parent_turn_id": execution_context.parent_turn_id,
            "execution_context": execution_context,
        })
    result = await _call_with_supported_kwargs(runner.agent_invoker.invoke, kwargs)
    if audit is not None:
        audit.update(_agent_audit_metadata(result, node=node, configured_model=kwargs["model"]))
    if isinstance(result, str):
        content = result
    elif isinstance(result, dict):
        content = result.get(
            "message",
            result.get(
                "content",
                result.get("text", result.get("output", result.get("result", ""))),
            ),
        )
    else:
        content = getattr(result, "message", None) or getattr(result, "content", None) or ""
    if not isinstance(content, str):
        content = _summarize(content)
    return runner._split_or_fallback(node, content)


def _split_or_fallback(runner, node: WorkflowNode, raw: str) -> dict[str, Any]:
    """Distribute structured JSON output across named ports, else fall back.

    When the node has named output ports and ``raw`` parses to a JSON object,
    each key matching a port name flows to that port (missing keys default to
    None). When there are no named ports, or parsing fails, the entire value
    goes to the default output port as a string.
    """
    from .runner_graph import _default_output_port
    from .runner_process import _coerce_value, _json_object
    out_ports = node.output_ports()
    default_port = _default_output_port(node) or "output"
    if not out_ports:
        return {default_port: raw}
    parsed = _json_object(raw)
    if parsed is None:
        # Fallback: whole value to the first output port.
        return {out_ports[0].name: raw}
    result: dict[str, Any] = {}
    for port in out_ports:
        if port.name in parsed:
            result[port.name] = _coerce_value(parsed[port.name], port.type)
        else:
            result[port.name] = None
    return result
