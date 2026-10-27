"""Stable model catalog exposed to plugin backends.

Plugins previously imported ``lamtools_core.config.model_store`` directly,
which made an internal storage detail part of every port.  This service is the
public contract: list, resolve, default, capability and provider information.
It wraps the existing store so project/global/built-in precedence and the
jsonc capability field remain the single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lamtools_core.config.model_store import ModelStore, resolve_model_capability


@dataclass(frozen=True)
class ModelInfo:
    id: str
    display_name: str
    provider: str
    provider_id: str
    capability: str
    context_window: int = 0
    max_output_tokens: int = 0
    is_default: bool = False
    source_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "displayName": self.display_name,
            "provider": self.provider,
            "providerId": self.provider_id,
            "capability": self.capability,
            "contextWindow": self.context_window,
            "maxOutputTokens": self.max_output_tokens,
            "isDefault": self.is_default,
            "sourcePath": self.source_path,
        }


def _to_info(record: Any, *, default_id: str = "") -> ModelInfo:
    model_id = str(getattr(record, "model_id", "") or getattr(record, "id", "") or "")
    return ModelInfo(
        id=model_id,
        display_name=str(getattr(record, "display_name", "") or model_id),
        provider=str(getattr(record, "provider", "") or ""),
        provider_id=str(getattr(record, "provider_id", "") or ""),
        capability=str(getattr(record, "resolved_capability", "") or getattr(record, "capability", "") or "text"),
        context_window=int(getattr(record, "context_window", 0) or 0),
        max_output_tokens=int(getattr(record, "max_output_tokens", 0) or 0),
        is_default=bool(getattr(record, "is_default", False)) or (bool(default_id) and model_id == default_id),
        source_path=str(getattr(record, "source_path", "") or ""),
    )


class ModelCatalogService:
    """Read-only model catalog for plugins."""

    def __init__(self, *, work_root: str | Path | None = None) -> None:
        self._work_root = str(Path(work_root).resolve()) if work_root else ""

    def set_work_root(self, work_root: str | Path | None) -> None:
        self._work_root = str(Path(work_root).resolve()) if work_root else ""

    def _store(self) -> ModelStore:
        return ModelStore()

    def list(self) -> list[ModelInfo]:
        store = self._store()
        try:
            default_id = store.default_model_id_sync(work_root=self._work_root or None)
        except Exception:
            default_id = ""
        try:
            records = store.list_sync(work_root=self._work_root or None)
        except Exception:
            return []
        return [_to_info(record, default_id=default_id) for record in records]

    def resolve(self, ref: str) -> ModelInfo | None:
        ref = str(ref or "").strip()
        if not ref:
            return None
        try:
            record = self._store().get_sync(ref, work_root=self._work_root or None)
        except Exception:
            return None
        return _to_info(record) if record is not None else None

    def default(self) -> ModelInfo | None:
        try:
            default_id = self._store().default_model_id_sync(work_root=self._work_root or None)
        except Exception:
            return None
        return self.resolve(default_id) if default_id else None

    def capability(self, ref: str) -> str:
        return str(resolve_model_capability(str(ref or ""), work_root=self._work_root or None) or "text")

    def providers(self) -> list[str]:
        seen: list[str] = []
        for model in self.list():
            name = model.provider or model.provider_id
            if name and name not in seen:
                seen.append(name)
        return seen

    def to_dict(self) -> dict[str, Any]:
        return {
            "models": [model.to_dict() for model in self.list()],
            "providers": self.providers(),
            "default": (self.default().to_dict() if self.default() else None),
        }


__all__ = ["ModelInfo", "ModelCatalogService"]
