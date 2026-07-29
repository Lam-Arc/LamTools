from __future__ import annotations

import asyncio
import ipaddress
import json
import os
from dataclasses import replace
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from .models import HookDecision, HookDefinition, HookEvent


class MCPHookCaller(Protocol):
    async def call(self, tool_name: str, arguments: dict[str, Any]) -> str: ...


class HookEngine:
    def __init__(self, hooks: list[HookDefinition], *, mcp_caller: MCPHookCaller | None = None) -> None:
        self.hooks = list(hooks)
        self.mcp_caller = mcp_caller

    def set_mcp_caller(self, mcp_caller: MCPHookCaller | None) -> None:
        self.mcp_caller = mcp_caller

    async def run(self, event: HookEvent) -> HookDecision:
        decision = HookDecision()
        audit_events: list[dict[str, Any]] = []
        current_input = dict(event.tool_input)
        current_output: dict[str, Any] | None = None
        for hook in self._matching_hooks(event):
            if not hook.trusted:
                audit_events.append({"hook_id": hook.id, "status": "skipped_untrusted"})
                continue
            # emit status message before running the hook
            if hook.handler.status_message:
                decision = replace(decision, status_message=hook.handler.status_message)
            # build the event payload: input/output reflects cumulative prior hooks
            event_for_hook = event
            if current_input != event.tool_input:
                event_for_hook = replace(event_for_hook, tool_input=current_input)
            if current_output is not None and event.tool_result:
                event_for_hook = replace(event_for_hook, tool_result=current_output)
            result, audit = await self._run_hook(hook, event_for_hook)
            audit_events.append(audit)
            # PreToolUse-style: merge updated_input
            if result.updated_input is not None:
                current_input.update(result.updated_input)
                decision = replace(decision, updated_input=dict(current_input))
            # PostToolUse-style: merge updated_output
            if result.updated_output is not None:
                if current_output is None:
                    current_output = dict(result.updated_output)
                else:
                    current_output.update(result.updated_output)
                decision = replace(decision, updated_output=dict(current_output))
            if result.additional_context:
                joined = "\n".join(
                    item for item in [decision.additional_context, result.additional_context] if item
                )
                decision = replace(decision, additional_context=joined)
            if result.permission_decision:
                decision = replace(
                    decision,
                    permission_decision=result.permission_decision,
                    permission_decision_reason=result.permission_decision_reason,
                )
            if result.status_message:
                decision = replace(decision, status_message=result.status_message)
            if result.decision == "block":
                decision = replace(decision, decision="block", reason=result.reason)
                break
        return replace(decision, audit_events=[*decision.audit_events, *audit_events])

    def _matching_hooks(self, event: HookEvent) -> list[HookDefinition]:
        return [
            hook
            for hook in self.hooks
            if hook.event == event.event_name
            and (hook.matcher in {"", "*"} or hook.matcher == event.tool_name)
        ]

    async def _run_hook(self, hook: HookDefinition, event: HookEvent) -> tuple[HookDecision, dict[str, Any]]:
        if hook.handler.type == "http":
            return await self._run_http_hook(hook, event)
        if hook.handler.type == "mcp":
            return await self._run_mcp_hook(hook, event)
        if hook.handler.type == "prompt":
            return self._run_prompt_hook(hook, event)
        if hook.handler.type != "command":
            return HookDecision(), {"hook_id": hook.id, "status": "skipped_unsupported"}
        payload = self._payload(hook, event)
        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.update({
            "LAMTOOLS_HOOK_EVENT": event.event_name,
            "LAMTOOLS_PLUGIN_ROOT": str(hook.plugin_root or ""),
        })
        proc = await asyncio.create_subprocess_shell(
            self._expanded_command(hook, event),
            cwd=event.project_root or event.cwd or None,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(body), timeout=hook.handler.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            audit = {"hook_id": hook.id, "status": "timeout"}
            if hook.handler.required:
                return HookDecision(decision="block", reason="required hook timed out"), audit
            return HookDecision(), audit
        audit = {
            "hook_id": hook.id,
            "status": "completed" if proc.returncode == 0 else "failed",
            "exit_code": proc.returncode,
            "stderr": stderr.decode("utf-8", errors="replace").splitlines()[:1],
        }
        if proc.returncode != 0:
            if hook.handler.required:
                return HookDecision(decision="block", reason="required hook failed"), audit
            return HookDecision(), audit
        text = stdout.decode("utf-8", errors="replace").strip()
        if not text:
            return HookDecision(), audit
        return self._decision_from_text(text), audit

    async def _run_http_hook(self, hook: HookDefinition, event: HookEvent) -> tuple[HookDecision, dict[str, Any]]:
        if not hook.handler.url:
            audit = {"hook_id": hook.id, "status": "failed", "error": "missing url"}
            if hook.handler.required:
                return HookDecision(decision="block", reason="required http hook missing url"), audit
            return HookDecision(), audit
        payload = self._payload(hook, event)
        try:
            host = urlparse(hook.handler.url).hostname or ""
            try:
                is_loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_loopback = host.lower() == "localhost"
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(hook.handler.timeout),
                trust_env=not is_loopback,
            ) as client:
                response = await client.post(hook.handler.url, json=payload)
            audit = {
                "hook_id": hook.id,
                "status": "completed" if response.status_code < 400 else "failed",
                "status_code": response.status_code,
            }
            if response.status_code >= 400:
                if hook.handler.required:
                    return HookDecision(decision="block", reason="required http hook failed"), audit
                return HookDecision(), audit
            text = response.text.strip()
            return (self._decision_from_text(text) if text else HookDecision()), audit
        except Exception as exc:
            audit = {"hook_id": hook.id, "status": "failed", "error": str(exc)[:200]}
            if hook.handler.required:
                return HookDecision(decision="block", reason="required http hook failed"), audit
            return HookDecision(), audit

    async def _run_mcp_hook(self, hook: HookDefinition, event: HookEvent) -> tuple[HookDecision, dict[str, Any]]:
        if self.mcp_caller is None:
            audit = {"hook_id": hook.id, "status": "skipped_unavailable"}
            if hook.handler.required:
                return HookDecision(decision="block", reason="required mcp hook unavailable"), audit
            return HookDecision(), audit
        if not hook.handler.tool:
            audit = {"hook_id": hook.id, "status": "failed", "error": "missing tool"}
            if hook.handler.required:
                return HookDecision(decision="block", reason="required mcp hook missing tool"), audit
            return HookDecision(), audit
        payload = self._payload(hook, event)
        try:
            text = await asyncio.wait_for(self.mcp_caller.call(hook.handler.tool, payload), timeout=hook.handler.timeout)
        except asyncio.TimeoutError:
            audit = {"hook_id": hook.id, "status": "timeout"}
            if hook.handler.required:
                return HookDecision(decision="block", reason="required mcp hook timed out"), audit
            return HookDecision(), audit
        except Exception as exc:
            audit = {"hook_id": hook.id, "status": "failed", "error": str(exc)[:200]}
            if hook.handler.required:
                return HookDecision(decision="block", reason="required mcp hook failed"), audit
            return HookDecision(), audit
        audit = {"hook_id": hook.id, "status": "completed"}
        return self._decision_from_text(str(text)) if text else HookDecision(), audit

    def _run_prompt_hook(self, hook: HookDefinition, event: HookEvent) -> tuple[HookDecision, dict[str, Any]]:
        prompt = self._expanded_prompt(hook, event)
        audit = {"hook_id": hook.id, "status": "completed"}
        return HookDecision(additional_context=prompt), audit

    def _decision_from_text(self, text: str) -> HookDecision:
        data = json.loads(text)
        return HookDecision(
            decision="block" if data.get("decision") == "block" else "allow",
            reason=str(data.get("reason") or ""),
            additional_context=str(data.get("additionalContext") or data.get("additional_context") or ""),
            updated_input=data.get("updatedInput") if isinstance(data.get("updatedInput"), dict) else None,
            permission_decision=str(data.get("permissionDecision") or data.get("permission_decision") or ""),
            permission_decision_reason=str(
                data.get("permissionDecisionReason") or data.get("permission_decision_reason") or ""
            ),
            updated_output=data.get("updatedOutput") if isinstance(data.get("updatedOutput"), dict) else None,
            status_message=str(data.get("statusMessage") or data.get("status_message") or ""),
        )

    def _payload(self, hook: HookDefinition, event: HookEvent) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event_name": event.event_name,
            "session_id": event.session_id,
            "run_id": event.run_id,
            "turn_id": event.turn_id,
            "cwd": event.cwd,
            "project_root": event.project_root,
            "plugin_name": hook.plugin_name or event.plugin_name,
            "plugin_root": str(hook.plugin_root or event.plugin_root or ""),
            "plugin_data": event.plugin_data,
            "transcript_path": event.transcript_path,
            "metadata": event.metadata,
            "tool_name": event.tool_name,
            "tool_input": event.tool_input,
        }
        # PostToolUse / PostToolUseFailure fields
        if event.tool_call_id:
            payload["tool_call_id"] = event.tool_call_id
        if event.tool_result:
            payload["tool_result"] = event.tool_result
        if event.error:
            payload["error"] = event.error
        if event.error_type:
            payload["error_type"] = event.error_type
        # UserPromptSubmit fields
        if event.user_message:
            payload["user_message"] = event.user_message
        # PermissionRequest fields
        if event.permission_request:
            payload["permission_request"] = event.permission_request
        return payload

    def _expanded_command(self, hook: HookDefinition, event: HookEvent) -> str:
        plugin_root = str(hook.plugin_root or event.plugin_root or "")
        return (
            hook.handler.command
            .replace("${PLUGIN_ROOT}", plugin_root)
            .replace("${PLUGIN_DATA}", event.plugin_data)
            .replace("${PROJECT_ROOT}", event.project_root)
            .replace("${TOOL_NAME}", event.tool_name)
            .replace("${TOOL_CALL_ID}", event.tool_call_id)
            .replace("${EVENT_NAME}", event.event_name)
        )

    def _expanded_prompt(self, hook: HookDefinition, event: HookEvent) -> str:
        plugin_root = str(hook.plugin_root or event.plugin_root or "")
        return (
            hook.handler.prompt
            .replace("${PLUGIN_ROOT}", plugin_root)
            .replace("${PLUGIN_DATA}", event.plugin_data)
            .replace("${PROJECT_ROOT}", event.project_root)
            .replace("${TOOL_NAME}", event.tool_name)
            .replace("${TOOL_CALL_ID}", event.tool_call_id)
            .replace("${EVENT_NAME}", event.event_name)
            .replace("${USER_MESSAGE}", event.user_message)
        )