"""Node retry, cache and executor invocation policy."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from .adapters import NodeExecutor
from .cache import content_signature
from .durable import NodeExecutionPolicy, WorkflowRunEvent, attempt_identity
from .executors import WorkflowExecutorError, normalize_node_execution_result
from .models import WorkflowNode, WorkflowNodeState, public_workflow_value
from .persistence import WorkflowPersistenceError
from .runner_context import WorkflowExecutionContext


async def _execute_with_retries(
    runner,
    node: WorkflowNode,
    bound_inputs: dict[str, Any],
    work_root: str,
    state: WorkflowNodeState,
    values: dict[str, Any] | None = None,
    *,
    thread_id: str = "",
    run_id: str = "",
    execution_context: WorkflowExecutionContext | None = None,
) -> dict[str, Any]:
    from .runner_cancellation import _await_with_context_cancel
    from .runner_security import _contains_credential_ref, _redact_exception_text, _redact_runtime_secrets, _resolve_workflow_credentials
    from .runner_values import _contains_lazy_input, _executor_result_to_legacy, _materialize_inputs
    policy = NodeExecutionPolicy.from_config(node.config)
    cache_key = ""
    # A lazy value has deliberately not been observed yet.  Including the
    # resolver object in a cache key would be unstable and, more
    # importantly, would turn a declared lazy input into an eager read.
    cache_enabled = (
        runner._cache_enabled(node)
        and not _contains_lazy_input(bound_inputs)
        and not _contains_credential_ref(node.config)
        and not _contains_credential_ref(bound_inputs)
    )
    # Capability/resource declarations are checked before the first
    # durable attempt event or executor side effect.
    runner._check_node_authority(node, execution_context)
    if cache_enabled:
        workflow_id = ""
        workflow_revision = 0
        active = runner._active_runs.get((thread_id, run_id))
        if active is not None:
            workflow_id = active.workflow.id
            workflow_revision = active.workflow.revision
        cache_key = content_signature(
            workflow_id=workflow_id,
            workflow_revision=workflow_revision,
            node_id=node.id,
            node_kind=node.kind,
            node_config=node.config,
            bound_inputs=bound_inputs,
        )
        state.cache_key = cache_key
        lookup = await runner.cache_store.lookup(cache_key)
        if lookup.hit:
            state.cache_status = "hit"
            state.attempts = max(1, state.attempts)
            now = runner.clock()
            state.attempt_history.append({
                "number": state.attempts,
                "status": "cache_hit",
                "started_at": now.isoformat(),
                "finished_at": now.isoformat(),
                "cache_status": "hit",
                "cache_key": cache_key,
            })
            return dict(lookup.value) if isinstance(lookup.value, dict) else {"output": lookup.value}
        state.cache_status = "miss"
    else:
        state.cache_status = "bypass"
        state.cache_key = ""
    last_exc: Exception | None = None
    resuming_attempt = bool(state.attempt_id and state.idempotency_key and state.error == "interrupted")
    first_number = max(1, state.attempts if resuming_attempt else state.attempts + 1)
    # A persisted in-flight attempt is always allowed to finish once with
    # the same idempotency key, even when its configured retry budget is 0.
    final_number = max(first_number, policy.max_attempts)
    for number in range(first_number, final_number + 1):
        if resuming_attempt and number == first_number:
            attempt_id, idempotency_key = state.attempt_id, state.idempotency_key
        else:
            attempt_id, idempotency_key = attempt_identity(run_id, node.id, number)
        state.attempts = number
        state.attempt_id = attempt_id
        state.idempotency_key = idempotency_key
        state.error = ""
        attempt_started_at = runner.clock()
        attempt_audit: dict[str, Any] = {}
        attempt_record: dict[str, Any] = {
            "attempt_id": attempt_id,
            "number": number,
            "status": "started",
            "started_at": attempt_started_at.isoformat(),
            "finished_at": None,
        }
        state.attempt_history.append(attempt_record)
        attempt_context = execution_context
        builtin_name = runner._builtin_executor_name(node)
        engine_timeout = None if builtin_name in {"command", "script"} else policy.timeout_seconds
        # Preserve the legacy adapter's execution-context object identity
        # for direct, non-durable callers. Durable/plugin runs receive the
        # explicit attempt/idempotency boundary.
        if execution_context is not None and (runner.event_store is not None or "execution" in node.config):
            attempt_context = replace(
                execution_context,
                event_metadata={
                    **execution_context.event_metadata,
                    "workflow_attempt_id": attempt_id,
                    "idempotency_key": idempotency_key,
                },
                environment={
                    **execution_context.environment,
                    "__workflow_timeout_seconds": engine_timeout,
                },
            )
        if attempt_context is not None and attempt_context.runtime_credentials:
            attempt_context = replace(attempt_context, runtime_credentials={})
        await runner._append_durable_event(
            WorkflowRunEvent(
                event_id=f"{attempt_id}:started",
                run_id=run_id,
                kind="attempt.started",
                workflow_id=runner._active_runs.get((thread_id, run_id)).workflow.id if runner._active_runs.get((thread_id, run_id)) else "",
                workflow_revision=runner._active_runs.get((thread_id, run_id)).workflow.revision if runner._active_runs.get((thread_id, run_id)) else 0,
                node_id=node.id,
                attempt_id=attempt_id,
                payload={"number": number, "idempotency_key": idempotency_key},
            )
        )
        active_run = runner._active_runs.get((thread_id, run_id))
        if active_run is not None:
            await runner._persist_active_snapshot(
                workflow=active_run.workflow,
                thread_id=thread_id,
                run_id=run_id,
                inputs=active_run.inputs,
                node_states=active_run.node_states,
                values=active_run.values,
                steps_remaining=max(0, len(active_run.order) - active_run.steps_taken),
            )
        try:
            # Resolve each attempt into a fresh node/context pair.  The
            # caller's node/context are shared graph inputs and remain
            # reference-only, while a retry receives a new short-lived
            # credential scope.
            attempt_execution_context = attempt_context
            execution_node = node
            execution_inputs = bound_inputs
            resolved_credentials: dict[str, Any] = {}
            resolved_secrets: list[Any] = []
            if _contains_credential_ref(node.config) or _contains_credential_ref(bound_inputs):
                base_context = attempt_context or WorkflowExecutionContext()
                resolved_config = await _resolve_workflow_credentials(
                    node.config,
                    runner.credential_resolver,
                    execution_context,
                    resolved_credentials,
                    resolved_secrets,
                    path=f"node[{node.id}].config",
                )
                resolved_inputs = await _resolve_workflow_credentials(
                    bound_inputs,
                    runner.credential_resolver,
                    execution_context,
                    resolved_credentials,
                    resolved_secrets,
                    path=f"node[{node.id}].inputs",
                )
                execution_node = replace(node, config=resolved_config)
                attempt_execution_context = replace(
                    base_context,
                    runtime_credentials=dict(resolved_credentials),
                )
                execution_inputs = resolved_inputs
            executor = runner._executor_for_node(execution_node)
            builtin_executor = runner._builtin_executor_name(execution_node)
            if executor is not None and builtin_executor is None:
                # LazyInput objects are intentionally preserved for trusted
                # plugin executors; they decide whether/when to resolve.
                raw_result = await _await_with_context_cancel(
                    runner._invoke_node_executor(
                        executor, execution_node, execution_inputs, attempt_execution_context
                    ),
                    attempt_execution_context,
                )
                normalized = normalize_node_execution_result(
                    _executor_result_to_legacy(raw_result, node=execution_node)
                )
                outputs = dict(normalized.outputs)
                expansion = normalized.normalized_expansion()
                if expansion is not None:
                    expanded_outputs = await _await_with_context_cancel(
                        runner._execute_expansion(
                            execution_node,
                            expansion,
                            execution_inputs,
                            work_root,
                            thread_id,
                            run_id,
                            attempt_execution_context,
                        ),
                        attempt_execution_context,
                    )
                    outputs = {**outputs, **expanded_outputs}
            elif builtin_executor == "ai":
                outputs = await _await_with_context_cancel(
                    runner._execute_ai(
                        execution_node,
                        await _materialize_inputs(execution_inputs),
                        work_root,
                        attempt_execution_context,
                        audit=attempt_audit,
                    ),
                    attempt_execution_context,
                )
            elif builtin_executor == "model":
                outputs = await _await_with_context_cancel(
                    runner._execute_ai_llm(
                        execution_node, await _materialize_inputs(execution_inputs), work_root,
                        str(execution_node.config.get("mode") or "single") == "loop",
                        attempt_execution_context, audit=attempt_audit,
                    ), attempt_execution_context,
                )
            elif builtin_executor == "agent":
                outputs = await _await_with_context_cancel(
                    runner._execute_ai_agent(
                        execution_node, await _materialize_inputs(execution_inputs), work_root,
                        attempt_execution_context, audit=attempt_audit,
                    ), attempt_execution_context,
                )
            elif builtin_executor == "content":
                outputs = await _await_with_context_cancel(
                    runner._execute_content(
                        execution_node,
                        await _materialize_inputs(execution_inputs),
                        work_root,
                    ),
                    attempt_execution_context,
                )
            elif builtin_executor == "subgraph":
                outputs = await _await_with_context_cancel(
                    runner._execute_subgraph(
                        execution_node,
                        await _materialize_inputs(execution_inputs),
                        work_root,
                        thread_id,
                        run_id,
                        attempt_execution_context,
                    ),
                    attempt_execution_context,
                )
            elif builtin_executor == "command":
                outputs = await _await_with_context_cancel(
                    runner._execute_command(
                        execution_node,
                        await _materialize_inputs(execution_inputs),
                        work_root,
                        attempt_execution_context,
                    ),
                    attempt_execution_context,
                )
            elif builtin_executor == "script":
                outputs = await _await_with_context_cancel(
                    runner._execute_script(
                        execution_node,
                        await _materialize_inputs(execution_inputs),
                        work_root,
                        attempt_execution_context,
                    ),
                    attempt_execution_context,
                )
            elif builtin_executor == "passthrough":
                outputs = runner._execute_passthrough(execution_node, await _materialize_inputs(execution_inputs))
            elif builtin_executor == "template":
                outputs = runner._execute_template(
                    execution_node,
                    await _materialize_inputs(execution_inputs),
                    execution_context=attempt_execution_context,
                )
            elif builtin_executor == "condition":
                outputs = runner._execute_condition(
                    execution_node,
                    await _materialize_inputs(execution_inputs),
                    execution_context=attempt_execution_context,
                )
            elif builtin_executor == "merge":
                outputs = runner._execute_merge(execution_node, await _materialize_inputs(execution_inputs))
            elif builtin_executor == "join":
                outputs = runner._execute_join(execution_node, await _materialize_inputs(execution_inputs))
            else:
                raise WorkflowExecutorError(
                    f"workflow node executor is not registered: {node.kind}"
                )
            safe_outputs = _redact_runtime_secrets(outputs, resolved_secrets)
            outputs = (
                dict(safe_outputs)
                if isinstance(safe_outputs, Mapping)
                else {"output": safe_outputs}
            )
            if cache_enabled:
                await runner.cache_store.set(cache_key, outputs)
            await runner._append_durable_event(
                WorkflowRunEvent(
                    event_id=f"{attempt_id}:completed",
                    run_id=run_id,
                    kind="attempt.completed",
                    node_id=node.id,
                    attempt_id=attempt_id,
                    payload={"number": number, "idempotency_key": idempotency_key},
                )
            )
            attempt_record["status"] = "completed"
            attempt_record["finished_at"] = runner.clock().isoformat()
            if attempt_audit:
                safe_audit = public_workflow_value(attempt_audit)
                attempt_record["audit"] = safe_audit
                state.audit = safe_audit
            return outputs
        except asyncio.CancelledError:
            attempt_record["status"] = "interrupted"
            attempt_record["finished_at"] = runner.clock().isoformat()
            raise
        except WorkflowPersistenceError:
            # A journal/checkpoint failure is not an executor failure and
            # must never cause a second side-effecting attempt.
            raise
        except Exception as exc:  # noqa: BLE001 — retry boundary
            timed_out = isinstance(exc, TimeoutError)
            error_text = _redact_exception_text(exc, locals().get("resolved_secrets", []))
            last_exc = (
                RuntimeError(f"node execution timed out after {policy.timeout_seconds}s")
                if timed_out and policy.timeout_seconds is not None
                else RuntimeError(error_text)
            )
            attempt_record["status"] = "timed_out" if timed_out else "failed"
            attempt_record["finished_at"] = runner.clock().isoformat()
            attempt_record["error"] = _redact_exception_text(
                last_exc, locals().get("resolved_secrets", [])
            )
            await runner._append_durable_event(
                WorkflowRunEvent(
                    event_id=f"{attempt_id}:{'timed_out' if timed_out else 'failed'}",
                    run_id=run_id,
                    kind=f"attempt.{'timed_out' if timed_out else 'failed'}",
                    node_id=node.id,
                    attempt_id=attempt_id,
                    payload={
                        "number": number,
                        "idempotency_key": idempotency_key,
                        "error": _redact_exception_text(last_exc, locals().get("resolved_secrets", [])),
                    },
                )
            )
            if number < final_number:
                await asyncio.sleep(policy.delay_after(number - first_number))
    raise last_exc if last_exc is not None else RuntimeError("node execution failed")


def _cache_enabled(runner, node: WorkflowNode) -> bool:
    """Return true only for an explicit pure + deterministic declaration."""
    if node.config.get("cache") is False or node.config.get("cache_enabled") is False:
        return False
    spec = runner.node_registry.get(node.kind) if runner.node_registry is not None else None
    pure = node.config.get("pure") if "pure" in node.config else (spec.pure if spec else False)
    deterministic = (
        node.config.get("deterministic")
        if "deterministic" in node.config
        else (spec.deterministic if spec else False)
    )
    return pure is True and deterministic is True


async def _invoke_node_executor(
    runner,
    executor: NodeExecutor,
    node: WorkflowNode,
    bound_inputs: dict[str, Any],
    execution_context: WorkflowExecutionContext | None,
) -> Any:
    """Call a registered executor through the explicit adapter boundary."""
    # ``LegacyNodeExecutorAdapter`` accepts both modern ``context`` and
    # legacy ``execution_context`` call signatures.  Adapters supplied by
    # a host may expose the protocol directly, so keep a small fallback
    # for objects that implement the method but are not wrapped.
    from .runner_cancellation import _call_with_supported_kwargs
    from .runner_values import _packet_view_for_inputs
    call = getattr(executor, "execute", None)
    if not callable(call):
        raise WorkflowExecutorError("workflow node executor has no execute()")
    packet = _packet_view_for_inputs(bound_inputs)
    return await _call_with_supported_kwargs(
        call,
        {
            "node": node,
            "inputs": bound_inputs,
            "bound_inputs": bound_inputs,
            "packet": packet,
            "data_packet": packet,
            "context": execution_context,
            "execution_context": execution_context,
        },
    )
