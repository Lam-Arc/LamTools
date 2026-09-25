"""Shared identifier validation for config file names.

Audit 09 S2: ``model_id`` / ``provider_id`` from RPC payloads were joined
into file paths verbatim, so ``config/models/../../../../x.jsonc`` resolved
outside the config directory and could overwrite arbitrary ``.jsonc`` files
(or create directories via ``mkdir``).  Every id that becomes a file name
must pass this allow-list.
"""

from __future__ import annotations

import re

# Letters, digits, '.', '_', '-' only; must start with an alphanumeric
# character (rejects ``..``, ``.env``-style hidden names and anything with
# path separators).
_ID_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# Anything usable as ONE path component: no separators, no drive colon, no
# Windows-reserved characters or control bytes. Display names may contain
# spaces ("Display Alpha"), but must not carry path semantics.
_PATH_COMPONENT_RE = re.compile(r'^[^/\\:*?"<>|\x00-\x1f]{1,128}$')


def validate_config_id(kind: str, value: str) -> str:
    value = str(value or "").strip()
    if not _ID_SAFE_RE.match(value):
        raise ValueError(
            f"invalid {kind} id {value!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators, '..' or leading dots)"
        )
    return value


def validate_path_component(kind: str, value: str) -> str:
    """Validate a value that will be used as a single file/directory name.

    Looser than :func:`validate_config_id` on purpose: a plugin's ``name`` is a
    display name and may contain spaces, but it must not contain separators or
    ``..`` (2026-09-25 审计 P1 — the installer joined it into a path).
    """
    value = str(value or "").strip()
    if value in {"", ".", ".."} or not _PATH_COMPONENT_RE.match(value):
        raise ValueError(
            f"invalid {kind} name {value!r}: must be a single path component "
            "(no path separators, '..', or reserved characters)"
        )
    return value
