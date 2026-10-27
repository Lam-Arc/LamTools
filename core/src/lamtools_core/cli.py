"""Compatibility entry point; implementation lives in responsibility modules."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
import asyncio
import httpx
import importlib
import inspect
import json
import logging
import os
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlsplit, urlunsplit
from lamtools_core.app.base_agent import (
    CoreBaseAgentConfig,
    CoreBaseAgentKit,
    DEFAULT_CORE_INSTRUCTIONS,
    assemble_core_agent_plugins,
    core_events_to_run_items,
)
from lamtools_core.app.cli_live import (
    CliLiveFormatter,
    OutputChunk,
    approval_decision_from_reply,
    execute_compaction_command_live,
    format_compaction_result,
    watch_live_events,
)
from lamtools_core.app.core_db import (
    list_core_sessions,
    open_core_app_db,
    persist_core_run_items,
    show_core_session,
)
from lamtools_core.app.live_client import CoreAppServerClient
from lamtools_core.app.project_visuals import PROJECT_COLOR_KEYS, PROJECT_ICON_KEYS
from lamtools_core.app.runtime_permissions import (
    load_global_runtime_controls,
    read_global_runtime_controls,
    resolve_permission_preset,
    resolve_session_permissions,
    runtime_snapshot as build_runtime_snapshot,
    session_runtime_preferences,
)
from lamtools_core.cli_commands.agents import (
    _subagent_roles_require_project_root,
    cmd_arrange_create,
    cmd_arrange_edit,
    cmd_arrange_list,
    cmd_arrange_show,
    cmd_arrange_update,
    cmd_subagent_guide_edit,
    cmd_subagent_guide_set,
    cmd_subagent_guide_show,
    cmd_subagent_lifecycle,
    cmd_subagent_roles_delete,
    cmd_subagent_roles_set,
    cmd_subagent_roles_show,
    cmd_subagent_strategy_set,
    cmd_subagent_strategy_show,
    cmd_subagent_strategy_unset,
)
from lamtools_core.cli_commands.config import (
    _default_adapter_dirs,
    _default_cli_plugin_roots,
    _default_cli_plugin_state_path,
    _default_model_store,
    _default_run_dir,
    _default_work_root,
    _get_model_store,
    _model_ref_from_routing,
    _model_store_work_root,
    _provider_extra,
    _repo_root,
    _resolve_adapter_profile,
    _resolve_cli_context_window,
    _resolve_cli_max_output_tokens,
    _resolve_core_db,
    _resolve_provider_for_model,
    _resolve_thread_id,
    configure_model_store_context,
    configured_model_ref,
    list_llm_model_configs,
    load_llm_config,
)
from lamtools_core.cli_commands.connection import (
    _add_live_connection_args,
    _add_live_connection_arguments,
    _invoke_live,
    _office_positive_float,
    _office_positive_int,
    _positive_timeout_or_none,
    _print_live_result,
)
from lamtools_core.cli_commands.entry import main
from lamtools_core.cli_commands.library import (
    _plan_library_command_error,
    _plan_library_path,
    _print_project_result,
    cmd_goal_create,
    cmd_goal_list,
    cmd_goal_show,
    cmd_goal_update,
    cmd_plan_library_create,
    cmd_plan_library_delete,
    cmd_plan_library_favorite,
    cmd_plan_library_folder,
    cmd_plan_library_list,
    cmd_plan_library_move,
    cmd_plan_library_rename,
    cmd_plan_library_show,
    cmd_project_agents_get,
    cmd_project_agents_set,
    cmd_project_create,
    cmd_project_delete,
    cmd_project_list,
    cmd_project_rename,
    cmd_project_show,
    cmd_project_update,
)
from lamtools_core.cli_commands.office import (
    OFFICE_EXIT_DATA_MISMATCH,
    OFFICE_EXIT_LAYOUT_CONFLICT,
    OFFICE_EXIT_MANIFEST_MISMATCH,
    OFFICE_EXIT_RENDER_FAILURE,
    OFFICE_EXIT_RENDER_UNAVAILABLE,
    OFFICE_EXIT_SUCCESS,
    _cmd_office,
    _invoke_office_service,
    _office_exception_payload,
    _office_issue_values,
    _office_jsonable,
    _office_operation_kwargs,
    _office_paths,
    _office_payload_exit_code,
    _office_service_operation,
    _office_usage_payload,
    _office_write_report,
    cmd_office_check,
    cmd_office_render,
    cmd_office_validate,
)
from lamtools_core.cli_commands.parser import build_parser
from lamtools_core.cli_commands.plugins import (
    _plugin_widget_scope_payload,
    cmd_plugin_config_get,
    cmd_plugin_config_set,
    cmd_plugin_deps,
    cmd_plugin_disable,
    cmd_plugin_enable,
    cmd_plugin_install,
    cmd_plugin_list,
    cmd_plugin_operations_list,
    cmd_plugin_uninstall,
    cmd_plugin_widget_action,
    cmd_plugin_widget_list,
    cmd_plugin_widget_show,
    cmd_skill_create,
    cmd_skill_delete,
    cmd_skill_disable,
    cmd_skill_enable,
    cmd_skill_list,
)
from lamtools_core.cli_commands.preferences import (
    _ONBOARDING_NAMESPACE,
    _onboarding_providers_configured,
    _onboarding_settings,
    cmd_ask_auto_continue_get,
    cmd_ask_auto_continue_set,
    cmd_command_shell_get,
    cmd_command_shell_set,
    cmd_keep_awake_get,
    cmd_keep_awake_set,
    cmd_language_get,
    cmd_language_set,
    cmd_load_context_get,
    cmd_load_context_set,
    cmd_memory_resume_get,
    cmd_memory_resume_set,
    cmd_network_get,
    cmd_network_set,
    cmd_onboarding_complete,
    cmd_onboarding_reset,
    cmd_onboarding_show,
)
from lamtools_core.cli_commands.resources import (
    _artifact_store_for_cli,
    _artifact_work_root,
    _format_artifact,
    cmd_artifact_delete,
    cmd_artifact_list,
    cmd_artifact_open,
    cmd_artifact_preview,
    cmd_artifact_restore,
    cmd_artifact_show,
    cmd_attachment_upload,
    cmd_loadtools_delete_mode,
    cmd_loadtools_edit_mode,
    cmd_loadtools_show,
    cmd_memory,
)
from lamtools_core.cli_commands.server import (
    cmd_maintenance_checkpoint_baseline,
    cmd_maintenance_dialogue_records,
    cmd_maintenance_prune_checkpoints,
    cmd_maintenance_strip_snapshot_images,
    cmd_migrate_projects,
    cmd_mobile_control,
    cmd_serve,
    cmd_setup,
    cmd_update_check,
    normalize_remote_server_base_url,
)
from lamtools_core.cli_commands.sessions import (
    cmd_session_checkpoints,
    cmd_session_export,
    cmd_session_fork,
    cmd_session_list,
    cmd_session_outline,
    cmd_session_permissions,
    cmd_session_rollback,
    cmd_session_show,
    list_core_cli_sessions,
    show_core_cli_session,
)
from lamtools_core.cli_commands.settings import (
    _context_compaction_settings,
    _imagegen_settings,
    _loadtools_for_cli,
    _mask_api_key,
    _now_iso,
    _run_config_cli_operation,
    cmd_context_compaction_config,
    cmd_context_compaction_show,
    cmd_imagegen_config,
    cmd_imagegen_show,
    cmd_model_group_members_set,
    cmd_model_groups_create,
    cmd_model_groups_delete,
    cmd_model_groups_list,
    cmd_model_groups_rename,
    cmd_model_groups_reorder,
    cmd_models_create,
    cmd_models_default,
    cmd_models_list,
    cmd_models_set,
    cmd_models_show,
    cmd_permissions_config,
    cmd_permissions_show,
)
from lamtools_core.cli_commands.task import (
    CoreCliRunOptions,
    _watch_live_cli,
    cmd_run,
    cmd_run_local,
    cmd_watch,
    run_core_cli_task,
)
from lamtools_core.cli_commands.turns import (
    _format_process_row,
    cmd_approval_respond,
    cmd_cancel,
    cmd_command_catalog,
    cmd_command_execute,
    cmd_pause_turn,
    cmd_process_forget,
    cmd_process_kill,
    cmd_process_list,
    cmd_process_logs,
    cmd_queue_create,
    cmd_queue_delete,
    cmd_queue_guide,
    cmd_queue_update,
    cmd_resume_turn,
    cmd_start,
    cmd_steer,
    cmd_terminate_turn,
)
from lamtools_core.cli_reporting import (
    _build_summary,
    _compact_large_event_strings,
    _part_summary,
    _redact_embedded_data_urls,
    _redact_event,
    _replace_large_stream_field,
    _should_collect_cli_event,
)
from lamtools_core.config.model_store import ModelConfig, ModelStore
from lamtools_core.config.network import httpx_client_kwargs
from lamtools_core.config.provider_store import ProviderConfig, ProviderStore
from lamtools_core.config.root import ensure_projects_root
from lamtools_core.config.settings_store import delete_setting, get_setting, set_setting
from lamtools_core.context_compaction_budget import (
    CONTEXT_COMPACTION_NAMESPACE,
    DEFAULT_RETAINED_STEPS,
    MAX_RETAINED_STEPS,
    load_retained_steps,
)
from lamtools_core.event import CollectingEventSink, RunItemEvent
from lamtools_core.export import ConversationExportService, build_handoff_context
from lamtools_core.export.serializers import (
    full_to_zip,
    to_json,
    transcript_to_jsonl,
    transcript_to_markdown,
    transcript_to_text,
)
from lamtools_core.kernel import CoreLoopKernel, LoopPolicy
from lamtools_core.llm import (
    ChatMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMToolCall,
    normalize_usage,
)
from lamtools_core.llm.http_client import (
    CoreHttpLLMClient,
    LLMConfig,
    _http_provider_error,
    _llm_tool_calls_from_raw,
    _messages_with_model_notes,
    _normalize_anthropic_stream_event,
    _parse_retry_after,
)
from lamtools_core.llm.model_capabilities import resolve_capability
from lamtools_core.llm.profiles import (
    declared_reasoning_levels,
    load_adapter_profiles_from_dirs,
    reasoning_off_supported,
    resolve_adapter_profile_from_profiles,
)
from lamtools_core.llm.reasoning import reasoning_level_from_legacy
from lamtools_core.llm.shallow_thinking import ShallowThinkingClient
from lamtools_core.runtime import RuntimeTurnInput
from lamtools_core.tool.default_toolbox import ApprovalPolicy, build_core_toolbox


if __name__ == "__main__":
    raise SystemExit(main())
