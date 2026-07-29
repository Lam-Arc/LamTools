from .engine import HookEngine
from .hook_config import HookRegistry, default_project_hooks_path, default_user_hooks_path
from .models import (
    HookDecision,
    HookDefinition,
    HookEvent,
    HookHandler,
    PluginManifest,
    PluginResource,
    # canonical hook event names
    HOOK_EVENT_PRE_TOOL_USE,
    HOOK_EVENT_POST_TOOL_USE,
    HOOK_EVENT_POST_TOOL_USE_FAILURE,
    HOOK_EVENT_SESSION_START,
    HOOK_EVENT_SESSION_STOP,
    HOOK_EVENT_USER_PROMPT_SUBMIT,
    HOOK_EVENT_PERMISSION_REQUEST,
)
from .operations import build_plugin_operation_catalog
from .registry import (
    PluginRegistry,
    PluginStateStore,
    default_project_plugin_root,
    default_user_plugin_root,
)
from .trust import HookTrustStore

__all__ = [
    "HookDecision",
    "HookDefinition",
    "HookEngine",
    "HookEvent",
    "HookHandler",
    "HookRegistry",
    "HookTrustStore",
    "PluginManifest",
    "PluginRegistry",
    "PluginResource",
    "PluginStateStore",
    "build_plugin_operation_catalog",
    "default_project_hooks_path",
    "default_project_plugin_root",
    "default_user_hooks_path",
    "default_user_plugin_root",
    # canonical hook event names
    "HOOK_EVENT_PRE_TOOL_USE",
    "HOOK_EVENT_POST_TOOL_USE",
    "HOOK_EVENT_POST_TOOL_USE_FAILURE",
    "HOOK_EVENT_SESSION_START",
    "HOOK_EVENT_SESSION_STOP",
    "HOOK_EVENT_USER_PROMPT_SUBMIT",
    "HOOK_EVENT_PERMISSION_REQUEST",
]