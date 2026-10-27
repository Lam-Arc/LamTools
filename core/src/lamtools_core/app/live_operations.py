"""Compatibility entry point; implementation lives in responsibility modules."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
import contextlib
import inspect
import json
import logging
import os
import sys
import time as time_module
import uuid
from collections.abc import Callable, Coroutine, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from lamtools_core.attachment import AttachmentService
from lamtools_core.composer_commands import (
    build_composer_command_catalog,
    default_core_resource_roots,
    normalize_command_name,
)
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import (
    RuntimeStateConflictError,
    RuntimeStateStore,
    default_runtime_task_registry,
    normalize_run_id,
)
from lamtools_core.runtime.background_processes import default_background_process_registry, status_to_dict
from lamtools_core.runtime.goal_continuation import goal_continuation_text, should_continue_goal
from lamtools_core.runtime.memory_guard import (
    HOST_MEMORY_EXHAUSTED,
    ensure_pending_memory_resume,
    memory_exhausted_message_for,
    state_is_memory_exhaustion,
)
from lamtools_core.snapshot import is_sub_agent_child_item
from lamtools_core.tool.approval import (
    PermissionMode,
    TierTools,
    load_access_tools,
    normalize_command_policies,
)
from lamtools_core.tool.loadtools import LoadTools, default_load_tools, load_loadtools, mode_names
from lamtools_core.turn.model import TERMINAL_TURN_STATUSES
from sqlalchemy.ext.asyncio import AsyncSession
from .command_execution import execute_command_action
from .event_store import AppEventEnvelope, AppEventInput, CORE_RUN_ITEM_METHOD, SqlAlchemyAppEventStore
from .live.approvals import handle_approval_respond_operation
from .live.attachments import (
    handle_attachment_get_operation,
    handle_attachment_list_operation,
    handle_attachment_open_operation,
    handle_attachment_operation,
    handle_attachment_preview_operation,
)
from .live.background import (
    CANCEL_ESCALATION_DELAYS_SECONDS,
    CANCEL_FINALIZER_TASK_WAIT_CAP_SECONDS,
    _LIVE_BACKGROUND_TASKS,
    _logger,
    _spawn_live_background,
    wait_live_background_tasks,
)
from .live.commands import (
    _compact_command_event,
    _compact_command_ids,
    _compact_command_terminal_event,
    _execute_claimed_compact_live_command,
    _execute_compact_live_command,
    _execute_live_command_action,
    _live_command_catalog,
    _persist_command_run_item,
    _publish_transient_compaction_delta,
    handle_command_catalog_operation,
    handle_command_execute_operation,
)
from .live.context import CoreLiveContext, CoreLiveOperationHost, CoreLiveOperationOutcome, SessionBusyError
from .live.continuations import (
    _approval_continuation_params,
    _approval_job_key,
    _continuation_turn_is_settled,
    _execute_continuation_job,
    _pending_approval_record,
    _run_continuation_job,
    _settle_continuation_waiters,
    _turn_has_control_decision,
)
from .live.dispatch import _CORE_LIVE_OPERATION_EXECUTORS
from .live.events import (
    _app_event_input,
    _append_app_event,
    _append_run_item,
    _get_running_loop,
    _persist_operation_result,
)
from .live.interactions import (
    _append_interaction_lifecycle_event,
    _cancel_superseded_interactions,
    _close_open_interactions,
    _execute_inline_approval_operation,
    _interaction_for_request,
    _resolved_interaction_for_request,
    handle_interaction_list_operation,
    handle_interaction_respond_operation,
    reconcile_open_interactions,
)
from .live.params import (
    SERIALIZED_SESSION_OPERATIONS,
    _command_arguments,
    _command_kind,
    _expected_revision,
    _include_snapshot_param,
    _is_active_turn,
    _is_stoppable_turn,
    _load_snapshot_outside_write_lock,
    _serialized_actor_key,
    _thread_id_from_params,
)
from .live.permissions import handle_session_permissions_set_operation
from .live.processes import (
    _background_process_registry_of,
    _invalid_pid_response,
    _process_scope_thread_id,
    _publish_process_changed,
    handle_process_forget_operation,
    handle_process_kill_operation,
    handle_process_list_operation,
    handle_process_log_operation,
)
from .live.queue import (
    handle_queue_create_operation,
    handle_queue_delete_operation,
    handle_queue_guidance_operation,
    handle_queue_update_operation,
)
from .live.queue_dispatch import _dispatch_next_queue_item, _goal_reminder, _session_current_model
from .live.recovery import (
    _active_turn_awaits_user_decision,
    _arm_pending_memory_resume,
    _latest_turn_id_any_status,
    _recover_missing_approval_card,
    _turn_execution_id,
    _turn_is_terminal,
    reconcile_terminal_turns,
    recover_stale_active_turns,
)
from .live.runtime_tasks import (
    _auto_title_session,
    _ensure_turn_terminal,
    _fail_runtime_start,
    _mirror_turn_started,
    _mirror_turn_status,
    _run_core_turn,
    _start_runtime_task,
)
from .live.steering import (
    _activate_stored_guidance,
    _queue_refused_guidance,
    _reference_input,
    _turn_has_ended,
    handle_turn_steer_operation,
)
from .live.terminal_state import (
    _active_thread_ids,
    _build_interrupted_tool_event,
    _close_active_turns,
    _collect_non_terminal_turn_item_ids,
    _patch_runtime_state,
    _paused_turn_id,
    _persist_cancelled_runtime_state,
    _persist_cancelled_terminal,
    _reconcile_cancelled_runtime_state,
    _save_runtime_state_with_retry,
    _terminal_verdict,
)
from .live.threads import (
    _load_thread_page,
    handle_sync_start_operation,
    handle_thread_history_operation,
    handle_thread_outline_operation,
    handle_thread_read_operation,
    handle_thread_resume_operation,
    handle_thread_start_operation,
)
from .live.turn_cancel import (
    _append_interrupting_record,
    _escalate_and_wait_cancel,
    _interrupt_session_members,
    _turn_cancel_finalizer,
    handle_turn_cancel_operation,
    handle_turn_force_reset_operation,
    handle_turn_terminate_operation,
)
from .live.turn_options import (
    _bundled_config_resources_dir,
    _latest_persisted_active_mode,
    _load_load_tools,
    _load_tier_tools,
    _queue_runtime_snapshot,
    _resolve_imagegen_config,
    _resolve_turn_approval_policy,
    _runtime_snapshot_with_turn_options,
)
from .live.turn_pause import (
    _PauseTarget,
    _build_paused_status_event,
    _ensure_paused_status,
    _pause_session_members,
    _pause_target_current,
    _resume_session_members,
    _settle_paused_runtime_state,
    _settle_thread_continuations,
    _turn_pause_finalizer,
    handle_turn_pause_operation,
)
from .live.turn_start import handle_turn_resume_operation, handle_turn_start_operation
from .live_approval import normalize_approval_request
from .live_hub import CoreAppEventHub, hub as default_hub
from .live_member import DefaultCoreLiveMemberHooks, PreparedLiveInput
from .live_protocol import INVALID_REQUEST, int_param as _int_param, rpc_error, rpc_result
from .operation_catalog import OperationCatalog, OperationHandler, OperationRequest, OperationResult
from .operation_groups import CORE_WORKBENCH_OPERATION_NAMES
from .persistence_host import AppPersistenceHost, RevisionConflictError
from .queue_state import (
    ACTIVE_TURN_STATUSES,
    build_queue_guidance_plan,
    build_queue_update_plan,
    effective_thread_status,
    input_items_text,
    latest_active_turn_id,
    next_dispatchable_queue_item,
    queue_delete_payload,
    queue_dispatch_payload,
    queue_item_payload,
)
from .runtime_permissions import (
    RUNTIME_PERMISSION_KEYS,
    load_global_runtime_controls,
    normalize_permission_mode,
    normalize_permission_preset,
    overlay_runtime_permissions,
    permissions_from_snapshot,
    resolve_permission_preset,
    resolve_session_permissions,
    runtime_snapshot as build_runtime_snapshot,
    session_runtime_preferences,
    with_session_runtime_preferences,
)
from .session_actor import SessionActorBusyError, SessionActorRegistry
from .session_autotitle import generate_session_title, is_default_title
from .snapshot_store import SqlAlchemyThreadSnapshotStore
from .sync_store import SYNC_CURSOR_EXPIRED
from .thread_history import (
    ARTIFACT_AVAILABILITY_REFERENCE,
    DEFAULT_THREAD_HISTORY_CHAR_LIMIT,
    DEFAULT_THREAD_HISTORY_PAGE_BYTES,
    DEFAULT_THREAD_HISTORY_TURN_LIMIT,
    MAX_INLINE_ARTIFACT_BYTES,
    MAX_THREAD_HISTORY_CHAR_LIMIT,
    MAX_THREAD_HISTORY_PAGE_BYTES,
    MAX_THREAD_HISTORY_TURN_LIMIT,
    MIN_THREAD_HISTORY_PAGE_BYTES,
    _artifact_has_large_inline_body,
    _artifact_reference,
    _character_page_snapshot,
    _decoded_data_url_size,
    _history_byte_budget,
    _history_char_limit,
    _history_cursor,
    _history_turn_limit,
    _mime_from_data_url,
    _page_item_byte_budget,
    _reference_oversized_item_artifacts,
)
from .thread_outline import build_thread_outline, normalize_thread_outline_char_limit
from .turn_acceptance import (
    CoreAppEventSpec,
    QUEUE_ITEM_ACCEPTED_METHODS,
    TURN_ACCEPTED_METHODS,
    build_cancelled_turn_event,
    build_turn_acceptance_plan,
)


__all__ = [
    "CoreLiveContext",
    "CoreLiveOperationHost",
    "CoreLiveOperationOutcome",
    "handle_queue_create_operation",
    "handle_queue_delete_operation",
    "handle_queue_guidance_operation",
    "handle_queue_update_operation",
    "handle_approval_respond_operation",
    "handle_interaction_list_operation",
    "handle_interaction_respond_operation",
    "handle_session_permissions_set_operation",
    "handle_thread_read_operation",
    "handle_thread_history_operation",
    "handle_thread_outline_operation",
    "handle_thread_start_operation",
    "handle_thread_resume_operation",
    "handle_sync_start_operation",
    "handle_turn_cancel_operation",
    "handle_turn_force_reset_operation",
    "handle_turn_start_operation",
    "handle_turn_resume_operation",
    "handle_turn_steer_operation",
    "handle_process_list_operation",
    "handle_process_kill_operation",
    "handle_process_forget_operation",
    "handle_process_log_operation",
]
