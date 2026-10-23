"""The redesigned plugin system.

The package is intentionally small at this step: manifest parsing, discovery,
enablement, uninstall, and the six declarative capabilities. UI contributions,
agent takeover and module overrides land in later steps behind the same host.
"""

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
from .host import PluginHost
from .manifest import (
    MANIFEST_FILENAME,
    SUPPORTED_SCOPES,
    PluginManifest,
    PluginManifestError,
    load_manifest,
)
from .state import PluginStateStore

__all__ = [
    "MANIFEST_FILENAME",
    "SUPPORTED_SCOPES",
    "CapabilityAssembly",
    "CapabilityError",
    "PluginCapabilities",
    "PluginCommandSpec",
    "PluginContextSpec",
    "PluginHookSpec",
    "PluginHost",
    "PluginManifest",
    "PluginManifestError",
    "PluginSkillSpec",
    "PluginStateStore",
    "PluginToolSpec",
    "assemble_capabilities",
    "load_manifest",
    "read_capabilities",
]
