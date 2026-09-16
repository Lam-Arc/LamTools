"""Unified Office data validation, rendering, and deterministic visual QA."""

from .manifest import sha256_file
from .models import (
    BackendInfo,
    OfficeBackendUnavailable,
    OfficeIssue,
    OfficeRenderReport,
    OfficeRendererError,
    OfficeRenderTimeout,
)
from .service import check_office, render_office, validate_office

__all__ = [
    "BackendInfo",
    "OfficeBackendUnavailable",
    "OfficeIssue",
    "OfficeRenderReport",
    "OfficeRendererError",
    "OfficeRenderTimeout",
    "check_office",
    "render_office",
    "sha256_file",
    "validate_office",
]
