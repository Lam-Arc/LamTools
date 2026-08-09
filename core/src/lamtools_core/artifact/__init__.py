"""Artifact system: per-id manifests under ``.lam/artifact/`` with parent-child
references (reference images → generated images), prompt and source tracking,
and soft-delete tombstones."""

from lamtools_core.artifact.registry import (
    ATTACHMENT_PREFIX,
    WORKSPACE_PREFIX,
    ArtifactRecord,
    ArtifactRegistry,
    kind_from_mime,
)

__all__ = [
    "ATTACHMENT_PREFIX",
    "WORKSPACE_PREFIX",
    "ArtifactRecord",
    "ArtifactRegistry",
    "kind_from_mime",
]
