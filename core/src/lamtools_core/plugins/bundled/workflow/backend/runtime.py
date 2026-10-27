"""Compatibility entry point; implementation lives in responsibility modules."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import ast
import asyncio
import hashlib
import inspect
import json
import math
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from lamtools_core.config.network import subprocess_env
from lamtools_core.event.run_item import RunItemEvent, RunItemStatus
from .adapters import (
    AgentInvoker,
    AgentInvokerAdapter,
    LLMInvoker,
    LegacyAgentInvokerAdapter,
    LegacyLLMAdapter,
    LegacyModelInvokerAdapter,
    LegacyNodeExecutorAdapter,
    LegacySubAgentAdapter,
    ModelInvoker,
    ModelInvokerAdapter,
    NodeExecutor,
    NodeExecutorAdapter,
    SubAgentInvoker,
    SubAgentInvokerAdapter,
    adapt_agent_invoker,
    adapt_data_packet,
    adapt_model_invoker,
    adapt_node_executor,
)
from .cache import WorkflowCacheLookup, WorkflowContentCache, content_signature
from .claims import WorkflowClaimStore, claim_store_for_runtime
from .credentials import CredentialError, CredentialRef, is_credential_ref
from .data_packet import WorkflowDataPacket, is_data_packet, packet_to_legacy
from .durable import (
    NodeExecutionPolicy,
    WorkflowRunEvent,
    WorkflowRunEventStore,
    attempt_identity,
    definition_digest,
)
from .executors import (
    DynamicNodeExpansion,
    Expansion,
    NodeExecutionResult,
    WorkflowDynamicExpansion,
    WorkflowExecutorError,
    WorkflowExecutorRegistry,
    WorkflowExpansion,
    WorkflowExpansionError,
    WorkflowNodeExecutionResult,
    normalize_execution_result,
    normalize_node_execution_result,
    normalize_node_result,
)
from .expressions import Expression, ExpressionContext, ExpressionError, evaluate as evaluate_expression
from .flow_control import (
    FlowControlDecision,
    FlowControlLease,
    FlowControlPolicy,
    FlowControlStore,
    stable_scope_key,
)
from .models import (
    NodeStateStatus,
    PortDirection,
    WorkflowDef,
    WorkflowEdge,
    WorkflowInputParam,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowNodeState,
    WorkflowPort,
    WorkflowRunResult,
    _PUBLIC_PRIVATE_KEYS,
    _as_int,
    _io_to_port_dicts,
    _is_private_public_key,
    _json_copy,
    _new_id,
    _parse_dt,
    _public_key,
    _utcnow,
    ensure_workflow_id,
    public_workflow_value,
)
from .persistence import WorkflowPersistenceError
from .registry import WorkflowNodeRegistry
from .runner import WorkflowRunner
from .runner_authority import _BUILTIN_EXECUTORS
from .runner_cancellation import (
    _await_with_context_cancel,
    _call_with_supported_kwargs,
    _cancellation_requested,
    _pause_requested,
)
from .runner_context import (
    LazyInput,
    LazyValue,
    WorkflowCapabilityError,
    WorkflowConflictError,
    WorkflowExecutionContext,
    WorkflowExpressionError,
    WorkflowNestingError,
    WorkflowPermissionError,
    WorkflowRecursionError,
    WorkflowValidationError,
)
from .runner_expressions import (
    _CONDITION_BUILTINS,
    _EXPRESSION_CREDENTIAL_FIELDS,
    _EXPRESSION_NO_ITEM,
    _EXPRESSION_SECRET_FIELDS,
    _eval_condition,
    _evaluate_workflow_expression,
    _expression_item,
    _expression_safe_value,
    _expression_secret_field,
    _is_structured_expression,
    _source_node,
)
from .runner_graph import (
    SKIP_SENTINEL,
    _MAP_LINE_RE,
    _apply_transform,
    _bind_inputs,
    _default_output_port,
    _feeding_edges,
    _input_value_key,
    _inputs_ready,
    _is_lazy_port,
    _lazy_input,
    _parse_map,
    _port_type,
    _resolve_output,
    _serialize_map,
    _topological_order,
    _workflow_input_default,
    _workflow_input_names,
)
from .runner_manager import WorkflowManager, _WORKFLOW_MUTATION_LOCKS
from .runner_process import (
    _PYTHON3_SHIM_DIR,
    _VAR_TOKEN_RE,
    _coerce_value,
    _create_workflow_process,
    _json_object,
    _normalise_type,
    _ports_to_io,
    _python3_shim_dir,
    _read_hash,
    _response_content,
    _substitute_env_vars,
    _terminate_workflow_process,
    _types_compatible,
    _write_runner,
)
from .runner_security import (
    _WorkflowAuthorizationGrants,
    _contains_credential_ref,
    _credential_ref,
    _grant_names,
    _redact_exception_text,
    _redact_runtime_secrets,
    _resolve_workflow_credentials,
    _workflow_authorization_grants,
    _workflow_resource_authorized,
)
from .runner_state import (
    WorkflowEventCallback,
    _ActiveWorkflowRun,
    _PROCESS_RUN_LOCKS,
    _PROCESS_RUN_LOCK_USERS,
    _PROCESS_SIGNAL_LOCKS,
    _PROCESS_SIGNAL_LOCK_USERS,
    _claim_request_fingerprint,
    _coordination_store_key,
)
from .runner_validation import _WORKFLOW_TYPES, _validate_run_inputs, validate_workflow
from .runner_values import (
    _agent_audit_metadata,
    _as_float,
    _assert_json_value,
    _assert_json_workflow_data,
    _cache_facts,
    _coerce_expansion_input_param,
    _contains_lazy_input,
    _execution_model_id,
    _executor_result_to_legacy,
    _field,
    _inherited_allowed_tools,
    _is_executor_surface,
    _mark_cancelled,
    _materialize_inputs,
    _model_audit_metadata,
    _packet_view_for_inputs,
    _safe_tool_calls,
    _serialize_prompt_value,
    _summarize,
)
from .snapshots import WorkflowSnapshotStore


__all__ = [
    "AgentInvoker",
    "AgentInvokerAdapter",
    "LLMInvoker",
    "LegacyLLMAdapter",
    "LegacyAgentInvokerAdapter",
    "LegacyModelInvokerAdapter",
    "LegacySubAgentAdapter",
    "LegacyNodeExecutorAdapter",
    "ModelInvoker",
    "ModelInvokerAdapter",
    "NodeExecutionResult",
    "WorkflowNodeExecutionResult",
    "Expansion",
    "DynamicNodeExpansion",
    "NodeExecutor",
    "NodeExecutorAdapter",
    "SubAgentInvoker",
    "SubAgentInvokerAdapter",
    "LazyInput",
    "LazyValue",
    "NodeStateStatus",
    "PortDirection",
    "SKIP_SENTINEL",
    "WorkflowDef",
    "WorkflowConflictError",
    "WorkflowCapabilityError",
    "WorkflowExpansion",
    "WorkflowDynamicExpansion",
    "WorkflowExpansionError",
    "WorkflowExecutorError",
    "WorkflowExpressionError",
    "WorkflowExecutorRegistry",
    "WorkflowExecutionContext",
    "WorkflowEdge",
    "WorkflowInputParam",
    "WorkflowManager",
    "WorkflowNode",
    "WorkflowNodeKind",
    "WorkflowNodeState",
    "WorkflowPort",
    "WorkflowRunResult",
    "WorkflowRunner",
    "normalize_execution_result",
    "normalize_node_result",
    "WorkflowNestingError",
    "WorkflowPermissionError",
    "WorkflowRecursionError",
]
