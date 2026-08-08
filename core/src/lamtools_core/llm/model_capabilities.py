"""Model capability classification (text vs multimodal).

Declares each model's input modality so the request layer can strip
unsupported content (e.g. images for text-only models) before sending.

The **jsonc model definition is the single source of truth**. Each model's
``capability`` field (``"text"`` or ``"multimodal"``) in its jsonc file
(core/config/resources/models, ~/.lam/config/models, or
<work_root>/.lam/config/models) decides its modality. There is deliberately no
hardcoded fallback table here: a model with an empty ``capability`` is treated
as ``"text"`` (conservative default — strips images rather than crashing).

Callers must resolve a model's capability from its jsonc definition via
:attr:`ModelConfig.resolved_capability` / :func:`ModelStore.resolve_model_capability`
— never by model_id alone. See ``lamtools_core.config.model_store``.
"""

from __future__ import annotations

from typing import Literal

Capability = Literal["text", "multimodal"]


def resolve_capability(model_id: str = "", jsonc_capability: str = "") -> Capability:
    """Resolve a model's input modality from its jsonc ``capability`` field.

    ``model_id`` is accepted only for backward-compatible call sites and is NOT
    consulted — the jsonc ``capability`` value is authoritative. An empty or
    unknown value collapses to ``"text"`` (safe default).
    """
    normalized = (jsonc_capability or "").strip().lower()
    return normalized if normalized in ("text", "multimodal") else "text"


def is_text_model(model_id: str = "", jsonc_capability: str = "") -> bool:
    """True when the jsonc ``capability`` resolves to text-only."""
    return resolve_capability(jsonc_capability=jsonc_capability) == "text"


__all__ = [
    "Capability",
    "is_text_model",
    "resolve_capability",
]