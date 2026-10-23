"""The redesigned plugin system.

The package is intentionally small at this step: manifest parsing, discovery,
enablement and uninstall. Capability assembly, UI contributions, agent takeover
and module overrides land in later steps behind the same host object.
"""

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
    "PluginHost",
    "PluginManifest",
    "PluginManifestError",
    "PluginStateStore",
    "load_manifest",
]
