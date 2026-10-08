"""Optional tool arguments that a model fills with a placeholder.

A model that treats every declared schema property as mandatory fills unused
string parameters with the literal text ``"null"`` (or a sibling such as
``"none"``) instead of omitting the key or sending JSON ``null``.  None of
those words can be a legitimate URL or content hash, so the readers below treat
them as "not supplied" rather than failing the call.  Real values pass through
unchanged, so a genuine mismatch still fails loudly.
"""

from __future__ import annotations

_PLACEHOLDER_WORDS = frozenset({"null", "none", "undefined", "nil", "n/a", "na"})


def optional_string(value: object) -> str:
    """Return *value* as a stripped string, mapping placeholders to ``""``.

    Non-string values (including JSON ``null``) also read as ``""``; callers
    that must reject a bad type validate it before calling this.
    """
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if text.lower() in _PLACEHOLDER_WORDS:
        return ""
    return text


__all__ = ["optional_string"]
