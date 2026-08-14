"""jsonc-backed config operations (providers / models / settings).

Every operation here reads and writes jsonc files only — the former shared
config DB (``llm_providers`` / ``llm_models`` / ``app_settings`` tables) is
gone. RPC names and payload shapes are preserved so existing frontends keep
working unchanged:

* ``config.providers.list`` / ``config.provider.create|update|delete``
* ``config.models.list`` / ``config.model.create|update|delete``
* ``settings.get`` / ``settings.update`` / ``config.import_env``
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from lamtools_core.app.operation_catalog import OperationCatalog, OperationRequest, OperationResult

from .imagegen_store import IMAGEGEN_NAMESPACE, load_imagegen_config, save_imagegen_config
from .model_store import ModelConfig, ModelStore
from .provider_store import MASKED_API_KEY, ProviderConfig, ProviderStore, mask_api_key, slugify
from .settings_store import get_setting, set_setting


def build_config_operation_catalog(*, work_root: str | Path | None = None) -> OperationCatalog:
    """Build an OperationCatalog of jsonc-backed config RPCs.

    ``work_root`` is the project root used for project-scoped model/provider
    resolution; writes default to the global scope.
    """
    catalog = OperationCatalog()
    root = str(work_root) if work_root else None

    def _providers() -> ProviderStore:
        return ProviderStore()

    def _models() -> ModelStore:
        return ModelStore()

    def _provider_response(provider: ProviderConfig) -> dict[str, Any]:
        return {
            "id": provider.id,
            "name": provider.name,
            "api_type": provider.api_type,
            "base_url": provider.base_url,
            "api_key": mask_api_key(provider.api_key),
            "has_api_key": bool(provider.api_key),
            "is_default": provider.is_default,
            "extra": dict(provider.extra),
        }

    def _model_response(model: ModelConfig) -> dict[str, Any]:
        return {
            "id": model.model_id,
            "model_record_id": model.model_id,
            "provider_id": model.provider_id,
            "model_id": model.model_id,
            "display_name": model.display_name,
            "context_window": model.context_window,
            "max_output_tokens": model.max_output_tokens,
            "thinking_supported": model.thinking_supported,
            "thinking_budget": model.thinking_budget,
            "temperature": model.temperature,
            "capability": model.capability,
            "notes": model.notes,
            "extra": model.to_extra(),
        }

    def _find_provider(ref: str, *, store: ProviderStore) -> ProviderConfig | None:
        if not ref:
            return None
        return store.get_sync(ref, work_root=root)

    async def providers_list(request: OperationRequest) -> OperationResult:
        limit = _bounded_int(request.payload.get("limit"), default=200, minimum=1, maximum=500)
        providers = _providers().list_sync(work_root=root)
        return OperationResult(
            name=request.name,
            payload={"providers": [_provider_response(p) for p in providers[:limit]]},
        )

    async def provider_create(request: OperationRequest) -> OperationResult:
        params = request.payload
        missing = [key for key in ("name", "base_url", "api_key") if not str(params.get(key) or "")]
        if missing:
            return _error(request, "name, base_url and api_key are required")
        name = str(params.get("name") or "").strip()
        store = _providers()
        provider_id = str(params.get("id") or params.get("preset_id") or "").strip() or slugify(name)
        # Ensure a unique provider id when the slug/preset id is already taken.
        existing = store.list_sync(work_root=root)
        taken = {p.id for p in existing}
        candidate, suffix = provider_id, 2
        while candidate in taken:
            candidate = f"{provider_id}-{suffix}"
            suffix += 1
        provider = ProviderConfig(
            id=candidate,
            name=name,
            api_type=str(params.get("api_type") or "openai").strip(),
            base_url=str(params.get("base_url") or "").strip(),
            api_key=str(params.get("api_key") or "").strip(),
            extra=dict(params["extra"]) if isinstance(params.get("extra"), dict) else {},
        )
        store.write(provider, scope="global", work_root=root)
        # Nested models[] (UI preset creations) become per-model jsonc files.
        models_raw = params.get("models")
        if isinstance(models_raw, list):
            model_store = _models()
            for raw in models_raw:
                if not isinstance(raw, dict) or not str(raw.get("model_id") or ""):
                    continue
                model = _model_config_from_payload(raw, fallback_provider=provider)
                model_store.write(model, scope="global", work_root=root)
        return OperationResult(name=request.name, payload={"provider": _provider_response(provider)})

    async def provider_update(request: OperationRequest) -> OperationResult:
        params = request.payload
        provider_id = str(params.get("provider_id") or params.get("providerId") or params.get("id") or "")
        if not provider_id:
            return _error(request, "provider_id is required")
        store = _providers()
        provider = _find_provider(provider_id, store=store)
        if provider is None:
            return _error(request, f"provider not found: {provider_id}")
        update = _provider_update_fields(provider, params)
        scope = _scope(params, root)
        if scope == "global" and _is_project_source(provider.source_path, root):
            # Writing a global copy would be shadowed by the project file —
            # the update would "succeed" without effect (audit 09 S3).
            scope = "project"
        store.write(update, scope=scope, work_root=root)
        return OperationResult(name=request.name, payload={"provider": _provider_response(store.get_sync(update.id, work_root=root) or update)})

    async def provider_delete(request: OperationRequest) -> OperationResult:
        provider_id = str(request.payload.get("provider_id") or request.payload.get("providerId") or request.payload.get("id") or "")
        if not provider_id:
            return _error(request, "provider_id is required")
        store = _providers()
        provider = _find_provider(provider_id, store=store)
        if provider is None:
            return _error(request, f"provider not found: {provider_id}")
        path = Path(provider.source_path) if provider.source_path else store.write_path(provider.id, scope="global", work_root=root)
        if path.is_file():
            path.unlink()
        store._cached_signature = None
        store._cached_providers = None
        # Also remove model files referencing this provider (UI warns about this).
        model_store = _models()
        for model in model_store.list_sync(work_root=root):
            if model.provider_id == provider.id or model.provider == provider.name:
                model_path = Path(model.source_path)
                if model_path.is_file():
                    model_path.unlink()
        model_store._cached_signature = None
        model_store._cached_models = None
        return OperationResult(name=request.name, payload={"ok": True})

    async def models_list(request: OperationRequest) -> OperationResult:
        from lamtools_core.cli import list_llm_model_configs

        models = list_llm_model_configs(work_root=root)
        return OperationResult(name=request.name, payload={"models": models})

    async def model_create(request: OperationRequest) -> OperationResult:
        params = request.payload
        missing = [key for key in ("provider_id", "model_id") if not str(params.get(key) or "")]
        if missing:
            return _error(request, "provider_id and model_id are required")
        provider = _find_provider(str(params.get("provider_id") or ""), store=_providers())
        if provider is None:
            return _error(request, f"provider not found: {params.get('provider_id')}")
        model = _model_config_from_payload(params, fallback_provider=provider)
        model_store = _models()
        if model.is_default:
            _clear_other_defaults(model_store, model.model_id, root)
        model_store.write(model, scope=_scope(params, root), work_root=root)
        return OperationResult(name=request.name, payload={"model": _model_response(model)})

    async def model_update(request: OperationRequest) -> OperationResult:
        params = request.payload
        model_record_id = str(params.get("model_record_id") or params.get("id") or "")
        if not model_record_id:
            return _error(request, "model_record_id is required")
        model_store = _models()
        model = model_store.get_sync(model_record_id, work_root=root)
        if model is None:
            return _error(request, f"model not found: {model_record_id}")
        payload = {k: v for k, v in params.items() if k not in ("model_record_id", "id", "scope", "extra_json")}
        if "extra" in payload and isinstance(payload.get("extra"), dict):
            extra = payload.pop("extra")
            payload.setdefault("capability", str(extra.get("capability") or "").strip())
            payload.setdefault("adapter_profile_id", str(extra.get("adapter_profile_id") or "").strip())
        payload.setdefault("provider", model.provider)
        payload.setdefault("provider_id", model.provider_id)
        updated = _model_config_from_payload(payload, fallback_provider=_fallback_provider(model))
        if updated.model_id != model.model_id:
            old_path = Path(model.source_path)
            if old_path.is_file():
                old_path.unlink()
        if updated.is_default:
            _clear_other_defaults(model_store, updated.model_id, root)
        scope = _scope(params, root)
        if scope == "global" and _is_project_source(model.source_path, root):
            # Same shadow trap as provider_update (audit 09 S3).
            scope = "project"
        model_store.write(updated, scope=scope, work_root=root)
        return OperationResult(name=request.name, payload={"model": _model_response(updated)})

    async def model_delete(request: OperationRequest) -> OperationResult:
        model_record_id = str(request.payload.get("model_record_id") or request.payload.get("id") or request.payload.get("model_id") or "")
        if not model_record_id:
            return _error(request, "model_record_id is required")
        model_store = _models()
        model = model_store.get_sync(model_record_id, work_root=root)
        if model is None:
            return _error(request, f"model not found: {model_record_id}")
        path = Path(model.source_path) if model.source_path else model_store.write_path(model.model_id, scope="global", work_root=root)
        if path.is_file():
            path.unlink()
        model_store._cached_signature = None
        model_store._cached_models = None
        return OperationResult(name=request.name, payload={"ok": True})

    async def settings_get(request: OperationRequest) -> OperationResult:
        namespace = str(request.payload.get("namespace") or "").strip()
        if not namespace:
            return _error(request, "namespace is required")
        # core.imagegen lives in its own imagegen.jsonc (frontend contract kept).
        if namespace == IMAGEGEN_NAMESPACE:
            value = dict(load_imagegen_config())
            if value.get("api_key"):
                # Mirror the provider contract: never echo the real key back
                # to the client; an empty/masked submission keeps the old one
                # (audit 17 S3).
                value["api_key"] = MASKED_API_KEY
                value["has_api_key"] = True
        else:
            value = get_setting(namespace)
        return OperationResult(name=request.name, payload={"namespace": namespace, "value": value if isinstance(value, dict) else {}})

    async def settings_update(request: OperationRequest) -> OperationResult:
        namespace = str(request.payload.get("namespace") or "").strip()
        value = request.payload.get("value")
        if not namespace or not isinstance(value, dict):
            return _error(request, "namespace and object value are required")
        if namespace == IMAGEGEN_NAMESPACE:
            current = load_imagegen_config()
            incoming = dict(value)
            # Empty or masked api_key keeps the stored key (audit 17 S3).
            submitted_key = incoming.get("api_key")
            if isinstance(submitted_key, str) and submitted_key.strip() in {"", MASKED_API_KEY}:
                incoming.pop("api_key", None)
            merged = {**current, **incoming}
            save_imagegen_config(merged)
        elif namespace == "core.runtimeControls":
            # Safety-critical namespace: validate the value domain server-side
            # so a caller cannot smuggle arbitrary permission settings
            # (audit 03 S3 / 12 S2 — this namespace gates auto-approval).
            merged = _merge_runtime_controls(request, get_setting(namespace), dict(value))
            if merged is None:
                return _error(request, "invalid core.runtimeControls value")
            set_setting(namespace, merged)
        else:
            current = get_setting(namespace)
            merged = {**(current if isinstance(current, dict) else {}), **dict(value)}
            set_setting(namespace, merged)
        return OperationResult(name=request.name, payload={"namespace": namespace, "value": merged})

    async def import_environment_operation(request: OperationRequest) -> OperationResult:
        api_key = os.environ.get("LAMTOOLS_LLM_API_KEY", "").strip()
        if not api_key:
            return _error(
                request,
                "LAMTOOLS_LLM_API_KEY is not configured — 请在设置中手动添加供应商/模型"
                "（设置 → 模型与供应商），或在 CLI 中设置环境变量 LAMTOOLS_LLM_API_KEY"
                "（需同时设置 LAMTOOLS_LLM_MODEL_ID）后重试",
            )
        base_url = os.environ.get("LAMTOOLS_LLM_BASE_URL", "https://api.openai.com/v1").strip()
        model_id = os.environ.get("LAMTOOLS_LLM_MODEL_ID", "").strip()
        if not model_id:
            return _error(request, "LAMTOOLS_LLM_MODEL_ID is not configured")
        name = os.environ.get("LAMTOOLS_LLM_PROVIDER_NAME", "Default from environment").strip()
        provider = ProviderConfig(
            id=slugify(name),
            name=name,
            api_type=os.environ.get("LAMTOOLS_LLM_API_TYPE", "openai").strip(),
            base_url=base_url,
            api_key=api_key,
        )
        store = _providers()
        existing = store.get_sync(provider.id, work_root=root)
        if existing is not None:
            provider = replace(existing, api_key=api_key)
        store.write(provider, scope="global", work_root=root)
        model = ModelConfig(
            model_id=model_id,
            display_name=model_id,
            provider=provider.name,
            provider_id=provider.id,
        )
        _models().write(model, scope="global", work_root=root)
        return OperationResult(
            name=request.name,
            payload={"provider": _provider_response(provider), "model": _model_response(model)},
        )

    for name, handler in {
        "config.providers.list": providers_list,
        "config.provider.create": provider_create,
        "config.provider.update": provider_update,
        "config.provider.delete": provider_delete,
        "config.models.list": models_list,
        "config.model.create": model_create,
        "config.model.update": model_update,
        "config.model.delete": model_delete,
        "config.import_env": import_environment_operation,
        "settings.get": settings_get,
        "settings.update": settings_update,
    }.items():
        catalog.register(name, handler)
    return catalog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _model_config_from_payload(params: dict[str, Any], *, fallback_provider: ProviderConfig | None) -> ModelConfig:
    """Build a ModelConfig from an RPC payload (UI shape: model_id, display_name, …).

    ``provider_id``/``provider_name`` in the payload are used when set; the
    ``fallback_provider`` fills both when the payload lacks them (provider
    create with nested models).
    """
    extra = params.get("extra")
    if not isinstance(extra, dict):
        extra = {}
    raw_provider_id = str(params.get("provider_id") or "").strip()
    if raw_provider_id:
        provider_id = raw_provider_id
    elif fallback_provider is not None:
        provider_id = fallback_provider.id
    else:
        provider_id = ""
    provider_name = str(params.get("provider_name") or params.get("provider") or "").strip()
    if not provider_name and fallback_provider is not None:
        provider_name = fallback_provider.name
    thinking = params.get("thinking")
    thinking_supported = bool(thinking.get("supported", params.get("thinking_supported") or False)) if isinstance(thinking, dict) else bool(params.get("thinking_supported") or False)
    thinking_budget = int(thinking.get("budget", params.get("thinking_budget") or 10000)) if isinstance(thinking, dict) else int(params.get("thinking_budget") or 10000)
    return ModelConfig(
        model_id=str(params.get("model_id") or "").strip(),
        display_name=str(params.get("display_name") or "").strip(),
        provider=provider_name,
        provider_id=provider_id,
        context_window=int(params.get("context_window") or 0),
        max_output_tokens=int(params.get("max_output_tokens") or 4096),
        temperature=float(params.get("temperature") or 0.2),
        thinking_supported=thinking_supported,
        thinking_budget=thinking_budget,
        reasoning_effort=str(params.get("reasoning_effort") or "").strip(),
        adapter_profile_id=str(extra.get("adapter_profile_id") or params.get("adapter_profile_id") or "").strip(),
        request_body=dict(extra["request_body"]) if isinstance(extra.get("request_body"), dict) else {},
        capability=str(extra.get("capability") or params.get("capability") or "").strip().lower(),
        notes=str(params.get("notes") or "").strip(),
        is_default=bool(params.get("is_default") or False),
    )


def _provider_update_fields(provider: ProviderConfig, params: dict[str, Any]) -> ProviderConfig:
    """Apply an update payload to a provider; masked/empty api keys keep the old value."""
    updates: dict[str, Any] = {}
    for key in ("name", "api_type", "base_url"):
        value = params.get(key)
        if value is not None:
            updates[key] = str(value).strip()
    api_key = params.get("api_key")
    if isinstance(api_key, str) and api_key.strip() and api_key.strip() != MASKED_API_KEY:
        updates["api_key"] = api_key.strip()
    if isinstance(params.get("extra"), dict):
        updates["extra"] = dict(params["extra"])
    if isinstance(params.get("is_default"), bool):
        updates["is_default"] = params["is_default"]
    return replace(provider, **updates)


def _fallback_provider(model: ModelConfig) -> ProviderConfig | None:
    if not (model.provider or model.provider_id):
        return None
    return ProviderStore().get_sync(model.provider_id or model.provider)


def _clear_other_defaults(model_store: ModelStore, model_id: str, work_root: str | None) -> None:
    for existing in model_store.list_sync(work_root=work_root):
        if existing.model_id != model_id and existing.is_default:
            model_store.write(replace(existing, is_default=False), scope="global", work_root=work_root)


def _scope(params: dict[str, Any], work_root: str | None) -> str:
    scope = str(params.get("scope") or "global").strip()
    if scope not in ("project", "global"):
        scope = "global"
    return scope


def _is_project_source(source_path: str | None, work_root: str | None) -> bool:
    """True when the entity's source file lives under the project scope.

    An update whose source is project-scoped must write back to the project
    (not a global copy that the project file shadows — the audit 09 S3
    "silent no-op update" trap).
    """
    if not work_root or not source_path:
        return False
    try:
        return Path(source_path).resolve().is_relative_to(Path(work_root).resolve())
    except (OSError, ValueError):
        return False


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _error(request: OperationRequest, message: str) -> OperationResult:
    return OperationResult(name=request.name, status="error", payload={"error": message})


_PERMISSION_MODES = ("read_only", "limited_edit", "full_edit")
_RUNTIME_CONTROL_BOOLS = (
    "allow_agent_install_skill",
    "allow_agent_create_hooks",
    "allow_access_outside_workdir",
)


def _merge_runtime_controls(request: OperationRequest, current: Any, incoming: dict[str, Any]) -> dict[str, Any] | None:
    """Merge a ``core.runtimeControls`` update with server-side validation.

    This namespace gates auto-approval and out-of-workdir access, so values
    are validated rather than blindly merged (audit 03 S3 / 12 S2).  Unknown
    keys are ignored; a known key with an out-of-domain value rejects the
    whole update.
    """
    merged = {**(current if isinstance(current, dict) else {})}
    for key, raw in incoming.items():
        if key == "permission_mode":
            if raw not in _PERMISSION_MODES:
                return None
            merged[key] = raw
        elif key in _RUNTIME_CONTROL_BOOLS:
            if not isinstance(raw, bool):
                return None
            merged[key] = raw
        else:
            # Unknown keys are dropped rather than persisted.
            pass
    return merged


__all__ = ["build_config_operation_catalog"]
