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
from .agent_presets import (
    AgentPreset,
    AgentPresetRegistry,
    PresetComposition,
    build_agent_preset_registry,
)
from .model_catalog import ModelCatalogService, ModelInfo
from .process_runtime import ProcessBackend, ProcessBackendError, process_runtime_spec
from .secrets import PluginSecretStore, PluginSecrets, SecretStoreError
from .prompt_waterfall import (
    PromptAssembly,
    PromptContext,
    PromptSection,
    SystemPromptWaterfall,
)
from .command_extensions import CommandInvocation, CommandResult
from .assets import resolve_plugin_asset
from .backend_runtime import PluginSupervisor, V2RuntimeManager, register_manager
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
# user:“宿主能力补齐和接口完善与文档更新”+(插件作者从公开 SDK 导入服务键和可撤回引用)。
from .services import ServiceError, ServiceKey, ServiceRef
from .sessions import SESSIONS, SessionControl, SessionError
from .tool_extensions import ToolDecision, ToolPatch, ToolInvocation, ToolOutcome
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
from .profiles import BudgetExhausted, ProfileBudget, ProfileSpec, apply_profile, available_profiles, read_profiles, resolve_profile
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
    PluginUIPage,
    PluginUIRegion,
    PluginUISpec,
    PluginWindowSpec,
    UIAssembly,
    assemble_ui,
    read_ui,
)

__all__ = [
    "CommandInvocation",
    "CommandResult",
    "MANIFEST_FILENAME",
    "SUPPORTED_SCOPES",
    "AgentAssembly",
    "AgentPlan",
    "PluginAgentSpec",
    "assemble_agents",
    "read_agent",
    "resolve_agent_plan",
    "AgentPreset",
    "AgentPresetRegistry",
    "PresetComposition",
    "build_agent_preset_registry",
    "ModelCatalogService",
    "ModelInfo",
    "ProcessBackend",
    "ProcessBackendError",
    "process_runtime_spec",
    "PluginSecretStore",
    "PluginSecrets",
    "SecretStoreError",
    "PromptAssembly",
    "PromptContext",
    "PromptSection",
    "SystemPromptWaterfall",
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
    "ServiceKey",
    "ServiceRef",
    "ServiceError",
    "SESSIONS",
    "SessionControl",
    "SessionError",
    "ToolDecision",
    "ToolPatch",
    "ToolInvocation",
    "ToolOutcome",
    "PluginHost",
    "BudgetExhausted",
    "ProfileBudget",
    "ProfileSpec",
    "apply_profile",
    "available_profiles",
    "read_profiles",
    "resolve_profile",
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
    "PluginUIPage",
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
    "PluginSupervisor",
    "assemble_capabilities",
    "load_manifest",
    "read_capabilities",
    "register_manager",
]
