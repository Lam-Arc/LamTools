"""Interface language preference; independent of model and conversation language."""
from __future__ import annotations

from typing import Any

LANGUAGE_NAMESPACE = "core.language"
UI_LANGUAGES = ("zh-CN", "zh-TW", "ja", "en")
DEFAULT_UI_LANGUAGE = "zh-CN"


def merge_language(current: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    if set(incoming) - {"locale"}:
        raise ValueError("core.language only accepts locale")
    merged = {**(current if isinstance(current, dict) else {}), **incoming}
    locale = merged.get("locale", DEFAULT_UI_LANGUAGE)
    if not isinstance(locale, str) or locale not in UI_LANGUAGES:
        raise ValueError("locale must be zh-CN, zh-TW, ja or en")
    return {"locale": locale}


def language_status() -> dict[str, Any]:
    from lamtools_core.config import get_setting

    current = get_setting(LANGUAGE_NAMESPACE)
    try:
        return merge_language(current, {})
    except ValueError:
        return {"locale": DEFAULT_UI_LANGUAGE}
