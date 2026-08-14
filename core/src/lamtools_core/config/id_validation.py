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


def validate_config_id(kind: str, value: str) -> str:
    value = str(value or "").strip()
    if not _ID_SAFE_RE.match(value):
        raise ValueError(
            f"invalid {kind} id {value!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators, '..' or leading dots)"
        )
    return value
