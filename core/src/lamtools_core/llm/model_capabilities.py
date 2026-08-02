"""Model capability classification (text vs multimodal).

Declares each known model's input modality so the request layer can strip
unsupported content (e.g. images for text-only models) before sending.

Resolution priority (see :func:`resolve_capability`):

1. ``jsonc_capability`` — the per-model jsonc ``capability`` field, when set.
2. :data:`BUILTIN_CAPABILITIES` — a hardcoded table for known providers.
3. ``"text"`` — the conservative default (strips images rather than crashing).

Members inherit this table automatically. For the Xunfei (讯飞) MaaS coding
plan models, multimodal (vision) support is declared for the Kimi, Qwen and
MiniMax families; everything else is treated as text-only.
"""

from __future__ import annotations

from typing import Literal

Capability = Literal["text", "multimodal"]

#: Hardcoded capability declarations for known model_id prefixes/values.
#: Keys are exact model_id matches; resolution also falls back to prefix
#: matching via :data:`_CAPABILITY_PREFIXES`.
BUILTIN_CAPABILITIES: dict[str, Capability] = {
    # ── Xunfei (讯飞 MaaS coding plan) ────────────────────────────────
    # Kimi family — multimodal
    "xopkimik26": "multimodal",
    "xopkimik25": "multimodal",
    # Qwen family — multimodal
    "xop3qwencodernext": "multimodal",
    "xopqwen35v35b": "multimodal",
    "xopqwen35397b": "multimodal",
    "xopqwen36v35b": "multimodal",
    # MiniMax family — multimodal
    "xminimaxm25": "multimodal",
    # Spark X2 family — text
    "xsparkx2": "text",
    "xsparkx2agent": "text",
    "xsparkx2flash": "text",
    # DeepSeek family — text
    "xopdeepseekv32": "text",
    "xopdeepseekv4pro": "text",
    "xopdeepseekv4flash": "text",
    # GLM family — text
    "xopglm5": "text",
    "xopglm51": "text",
    "xopglm52": "text",
    "xopglmv47flash": "text",
    # Xunfei routing/auto — text
    "auto": "text",
}

#: Prefix-based fallback when an exact model_id is not in the table. The first
#: matching prefix wins (insertion order is preserved in Python 3.7+).
_CAPABILITY_PREFIXES: list[tuple[str, Capability]] = [
    # Xunfei MaaS routing prefixes.
    ("xopkimik", "multimodal"),       # Kimi family
    ("xopqwen", "multimodal"),        # Qwen family
    ("xop3qwen", "multimodal"),       # Qwen3-Coder family
    ("xminimax", "multimodal"),       # MiniMax family
    ("xspark", "text"),               # Spark family
    ("xopdeepseek", "text"),          # DeepSeek family
    ("xopglm", "text"),               # GLM family
]


def resolve_capability(model_id: str, jsonc_capability: str = "") -> Capability:
    """Resolve the input modality for ``model_id``.

    A non-empty ``jsonc_capability`` (``"text"`` or ``"multimodal"``) always
    wins. Otherwise the builtin exact table is consulted, then prefix
    matching, then the conservative ``"text"`` default.
    """
    normalized = (jsonc_capability or "").strip().lower()
    if normalized in ("text", "multimodal"):
        return normalized  # type: ignore[return-value]
    mid = (model_id or "").strip()
    if mid in BUILTIN_CAPABILITIES:
        return BUILTIN_CAPABILITIES[mid]
    lowered = mid.lower()
    for prefix, capability in _CAPABILITY_PREFIXES:
        if lowered.startswith(prefix):
            return capability
    return "text"


def is_text_model(model_id: str, jsonc_capability: str = "") -> bool:
    """Convenience: True when the resolved capability is text-only."""
    return resolve_capability(model_id, jsonc_capability) == "text"


__all__ = [
    "BUILTIN_CAPABILITIES",
    "Capability",
    "is_text_model",
    "resolve_capability",
]
