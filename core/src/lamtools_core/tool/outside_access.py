"""One-shot out-of-workspace access granted by an approved tool call.

The approval gate decides *whether* a call may touch paths beyond the
workspace (see :mod:`lamtools_core.tool.approval`); handlers stay fail-closed
and read this context variable so only the approved call itself is released.
A context variable — not a toolbox flag — keeps concurrent tool calls from
inheriting each other's grant.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

GRANT_METADATA_KEY = "outside_workdir_approved"

_OUTSIDE_ACCESS_GRANT: ContextVar[bool] = ContextVar(
    "lamtools_outside_access_grant", default=False
)


def outside_access_granted() -> bool:
    """True while an approved call may access paths outside the workspace."""
    return _OUTSIDE_ACCESS_GRANT.get()


@contextmanager
def outside_access_grant(enabled: bool) -> Iterator[None]:
    token = _OUTSIDE_ACCESS_GRANT.set(bool(enabled))
    try:
        yield
    finally:
        _OUTSIDE_ACCESS_GRANT.reset(token)


def call_has_outside_grant(approval: object) -> bool:
    """Read the grant marker from a call's stored approval metadata."""
    return bool(isinstance(approval, dict) and approval.get(GRANT_METADATA_KEY))


__all__ = [
    "GRANT_METADATA_KEY",
    "call_has_outside_grant",
    "outside_access_grant",
    "outside_access_granted",
]
