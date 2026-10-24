"""The unified plugin system.

user:“删 v1 成单一系统”+清单、装配、生命周期、钩子、路径权威、会话可见性
全部落在这一包；``lamtools_core.plugins`` 只保留随包 ``bundled`` 目录。
"""

from .agent import (
    AgentAssembly,
    AgentPlan,
    PluginAgentSpec,
    assemble_agents,
    read_agent,
    resolve_agent_plan,
)
from .assets import resolve_plugin_asset
from .backend_runtime import V2RuntimeManager, register_manager
from .capabilities import (
    CapabilityAssembly,
    CapabilityError,
    PluginCapabilities,
    PluginCommandSpec,
    PluginContextSpec,
    PluginHookSpec,
    PluginSkillSpec,
    PluginToolSpec,
    assemble_capabilities,
    read_capabilities,
)
from .config_store import (
    config_path,
    read_config_values,
    read_schema,
    validate_config,
    write_config_values,
)
from .context import PluginContext
from .engine import PluginEngine, check_engine, host_engine_info, read_engine
from .host import PluginHost, shared_host
from .hook_engine import HookEngine
from .hooks import (
    HookDecision,
    HookDefinition,
    HookEvent,
    HookHandler,
    HookRegistry,
    HookTrustStore,
    load_all_hooks,
    plugin_hook_definitions,
)
from .lifecycle import (
    PluginLifecycleError,
    PluginRuntimeHandle,
    await_plugin_backends,
    backend_entry,
    load_enabled_plugin_backends,
    load_plugin_backend,
    plugin_backend_available,
    shutdown_plugin_backends,
    start_plugin_backend,
    stop_plugin_backend,
)
from .manifest import (
    MANIFEST_FILENAME,
    SUPPORTED_SCOPES,
    PluginManifest,
    PluginManifestError,
    load_manifest,
)
from .overrides import (
    OverrideAssembly,
    PluginOverrideSpec,
    assemble_overrides,
    override_paths,
    read_overrides,
)
from .paths import (
    bundled_plugins_dir,
    core_plugins_root,
    default_plugin_roots,
    default_project_plugin_root,
    default_user_plugin_root,
)
from .runtime import PluginSystemRuntime, RuntimeArtifacts
from .session_visibility import PluginSessionVisibility, SessionVisibility
from .settings import PluginConfigSpec, read_config
from .state import PluginStateStore
from .ui import (
    PluginAssetSpec,
    PluginUIAction,
    PluginUIBlock,
    PluginUIRegion,
    PluginUISpec,
    PluginWindowSpec,
    UIAssembly,
    assemble_ui,
    read_ui,
)

__all__ = [
    "MANIFEST_FILENAME",
    "SUPPORTED_SCOPES",
    "AgentAssembly",
    "AgentPlan",
    "PluginAgentSpec",
    "assemble_agents",
    "read_agent",
    "resolve_agent_plan",
    "PluginConfigSpec",
    "read_config",
    "PluginEngine",
    "check_engine",
    "host_engine_info",
    "read_engine",
    "config_path",
    "read_config_values",
    "read_schema",
    "validate_config",
    "write_config_values",
    "CapabilityAssembly",
    "CapabilityError",
    "PluginCapabilities",
    "PluginCommandSpec",
    "PluginContextSpec",
    "PluginHookSpec",
    "PluginSkillSpec",
    "PluginContext",
    "PluginHost",
    "shared_host",
    "PluginManifest",
    "PluginManifestError",
    "HookDecision",
    "HookDefinition",
    "HookEngine",
    "HookEvent",
    "HookHandler",
    "HookRegistry",
    "HookTrustStore",
    "load_all_hooks",
    "plugin_hook_definitions",
    "PluginLifecycleError",
    "PluginRuntimeHandle",
    "await_plugin_backends",
    "backend_entry",
    "load_enabled_plugin_backends",
    "load_plugin_backend",
    "plugin_backend_available",
    "shutdown_plugin_backends",
    "start_plugin_backend",
    "stop_plugin_backend",
    "OverrideAssembly",
    "PluginOverrideSpec",
    "assemble_overrides",
    "read_overrides",
    "override_paths",
    "bundled_plugins_dir",
    "core_plugins_root",
    "default_plugin_roots",
    "default_project_plugin_root",
    "default_user_plugin_root",
    "PluginAssetSpec",
    "PluginUIAction",
    "PluginUIBlock",
    "PluginUIRegion",
    "PluginUISpec",
    "PluginWindowSpec",
    "UIAssembly",
    "assemble_ui",
    "read_ui",
    "resolve_plugin_asset",
    "PluginSessionVisibility",
    "SessionVisibility",
    "PluginSkillSpec",
    "PluginStateStore",
    "PluginSystemRuntime",
    "PluginToolSpec",
    "RuntimeArtifacts",
    "V2RuntimeManager",
    "assemble_capabilities",
    "load_manifest",
    "read_capabilities",
    "register_manager",
]
