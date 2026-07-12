"""Core-owned continuation of a runtime tool approval."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable

from lamtools_core.event import CoreEvent
from lamtools_core.tool.approval_continuation import (
    ApprovedToolExecution,
    approved_tool_continuation_prompt,
    guidance_continuation_prompt,
    resolve_waiting_decision,
)

from .operation_catalog import OperationRequest, OperationResult


async def _call(callback: Callable[..., Any], *args: Any) -> Any:
    value = callback(*args)
    return await value if inspect.isawaitable(value) else value


@dataclass
class CoreApprovalContinuationCoordinator:
    state_store: Any
    emit_event: Callable[[CoreEvent], Any]
    execute_tool: Callable[[dict[str, Any]], Any]
    continue_turn: Callable[[str, Any], Any]

    async def respond(
        self,
        *,
        thread_id: str,
        request_id: str,
        decision: str,
        guidance: str = "",
    ) -> dict[str, Any]:
        state = await self.state_store.get(thread_id)
        if state is None:
            raise ValueError("Runtime state not found")
        pending = state.metadata.get("pending_approval")
        if not isinstance(pending, dict):
            raise ValueError("Runtime has no pending approval")
        expected_request_id = str(pending.get("request_id") or "")
        if request_id != expected_request_id:
            raise ValueError("Approval request id does not match pending runtime state")
        tool_call = pending.get("tool_call")
        if not isinstance(tool_call, dict):
            raise ValueError("Pending approval has no tool call")

        resolved = resolve_waiting_decision(decision, guidance)
        pending = {**pending, "status": "executing", "decision": resolved.action}
        state.metadata["pending_approval"] = pending
        await self.state_store.save(state)
        await _call(self.emit_event, self._event(
            state,
            "runtime.approval_response",
            {
                "request_id": request_id,
                "tool_call_id": str(tool_call.get("id") or request_id),
                "decision": resolved.action,
                "action": resolved.action,
                "guidance": resolved.guidance_text,
                "status": "resolved",
            },
        ))

        state.metadata.pop("pending_approval", None)
        state.metadata.pop("pending_waiting_request", None)
        if resolved.action == "deny":
            state.status = "cancelled"
            state.loop_state = "failed"
            await self.state_store.save(state)
            await _call(self.emit_event, self._event(
                state, "runtime.cancelled", {"message": "approval denied", "decision": "denied"}
            ))
            return {"status": "cancelled", "decision": "deny"}

        state.status = "running"
        state.loop_state = "continue"
        await self.state_store.save(state)
        original_task = str(state.metadata.get("original_user_message") or "")
        tool_name = str(tool_call.get("name") or "")
        tool_args = tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else {}
        if resolved.action == "guide":
            prompt = guidance_continuation_prompt(
                original_task=original_task,
                tool_name=tool_name,
                tool_args=tool_args,
                guidance_text=resolved.guidance_text,
            )
        else:
            try:
                execution = await _call(self.execute_tool, tool_call)
                if not isinstance(execution, ApprovedToolExecution):
                    raise TypeError("Approved tool adapter returned an invalid result")
                await _call(self.emit_event, self._event(
                    state,
                    "runtime.tool.finished",
                    {
                        "tool_name": execution.tool_name,
                        "call_id": str(tool_call.get("id") or request_id),
                        "status": "completed" if execution.completed else "failed",
                        "content": execution.tool_content if execution.completed else "",
                        "error": "" if execution.completed else execution.tool_content,
                    },
                ))
                if not execution.completed:
                    raise RuntimeError(execution.tool_content or "Approved tool failed")
                prompt = approved_tool_continuation_prompt(
                    original_task=original_task,
                    approved_tool=execution,
                )
            except BaseException as exc:
                state.status = "failed"
                state.loop_state = "failed"
                await self.state_store.save(state)
                await _call(self.emit_event, self._event(
                    state,
                    "runtime.failed",
                    {"error": str(exc), "failure_reason": str(exc), "decision": "approval_resolution_failed"},
                ))
                raise

        await _call(self.continue_turn, prompt, state)
        return {"status": "continued", "decision": resolved.action}

    @staticmethod
    def _event(state: Any, name: str, payload: dict[str, Any]) -> CoreEvent:
        return CoreEvent(
            name=name,
            category="decision" if name == "runtime.approval_response" else "lifecycle",
            payload=payload,
            event_id=f"{state.session_id}:{state.run_id}:{name}:{payload.get('request_id') or payload.get('call_id') or 'terminal'}",
            session_id=state.session_id,
            run_id=state.run_id,
        )


def build_core_approval_operation(coordinator_provider: Callable[[str], Any]):
    """Build the Core-owned approval.respond operation around member adapters."""

    async def approval_respond(request: OperationRequest) -> OperationResult:
        payload = request.payload
        thread_id = str(payload.get("thread_id") or payload.get("threadId") or "").strip()
        request_id = str(payload.get("request_id") or payload.get("requestId") or "").strip()
        decision = str(payload.get("decision") or payload.get("action") or "").strip()
        guidance = str(payload.get("guidance") or payload.get("response") or "")
        if not thread_id or not request_id or not decision:
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": "thread_id, request_id and decision are required"},
            )
        try:
            coordinator = await _call(coordinator_provider, thread_id)
            result = await coordinator.respond(
                thread_id=thread_id,
                request_id=request_id,
                decision=decision,
                guidance=guidance,
            )
        except (LookupError, ValueError) as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(name=request.name, payload=result)

    return approval_respond


__all__ = ["CoreApprovalContinuationCoordinator", "build_core_approval_operation"]
