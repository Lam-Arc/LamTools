"""The redesigned plugin system.

The package is intentionally small at this step: manifest parsing, discovery,
enablement, uninstall, and the six declarative capabilities. UI contributions,
agent takeover and module overrides land in later steps behind the same host.
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
from .engine import PluginEngine, check_engine, host_engine_info, read_engine
from .host import PluginHost
from .manifest import (
    MANIFEST_FILENAME,
    SUPPORTED_SCOPES,
    PluginManifest,
    PluginManifestError,
    load_manifest,
)
from .runtime import PluginSystemRuntime, RuntimeArtifacts
from .overrides import (
    OverrideAssembly,
    PluginOverrideSpec,
    assemble_overrides,
    override_paths,
    read_overrides,
)
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
    "PluginHost",
    "PluginManifest",
    "PluginManifestError",
    "OverrideAssembly",
    "PluginOverrideSpec",
    "assemble_overrides",
    "read_overrides",
    "override_paths",
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
    "PluginSkillSpec",
    "PluginStateStore",
    "PluginSystemRuntime",
    "PluginToolSpec",
    "RuntimeArtifacts",
    "assemble_capabilities",
    "load_manifest",
    "read_capabilities",
]
