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
from urllib.parse import urlsplit, urlunsplit

from lamtools_core.app.operation_catalog import OperationCatalog, OperationRequest, OperationResult
from lamtools_core.context_compaction_budget import (
    CONTEXT_COMPACTION_NAMESPACE,
    MAX_RETAINED_STEPS,
)

from .imagegen_store import IMAGEGEN_NAMESPACE, load_imagegen_config, save_imagegen_config
from .model_store import ModelConfig, ModelStore, make_model_record_id
from .model_group_store import ModelGroupRevisionConflict, ModelGroupStore
from .provider_store import (
    MASKED_API_KEY,
    ApiKeyValidationError,
    ProviderConfig,
    ProviderStore,
    mask_api_key,
    slugify,
    validate_api_key_text,
)
from .settings_store import get_setting, set_setting


def build_config_operation_catalog(
    *,
    work_root: str | Path | None = None,
    data_dir: str | Path | None = None,
) -> OperationCatalog:
    """Build an OperationCatalog of jsonc-backed config RPCs.

    ``work_root`` is the project root used for project-scoped model/provider
    resolution; writes default to the global scope.
    ``data_dir`` routes the imagegen namespace to the plugin config location
    (D5 共识：配置迁入插件配置，旧位置自动迁移)。
    """
    catalog = OperationCatalog()
    root = str(work_root) if work_root else None

    def _providers() -> ProviderStore:
        return ProviderStore()

    def _models() -> ModelStore:
        return ModelStore()

    def _groups() -> ModelGroupStore:
        return ModelGroupStore()

    def _provider_response(provider: ProviderConfig) -> dict[str, Any]:
        return {
            "id": provider.id,
            "name": provider.name,
            "api_type": provider.api_type,
            "base_url": provider.base_url,
            "api_key": mask_api_key(provider.api_key),
            "has_api_key": bool(provider.api_key),
            "is_default": provider.is_default,
            "extra": provider.to_extra(),
        }

    def _model_response(model: ModelConfig) -> dict[str, Any]:
        return {
            "id": model.id,
            "model_record_id": model.id,
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
        try:
            api_key = validate_api_key_text(str(params.get("api_key") or ""))
        except ApiKeyValidationError as exc:
            return _error(request, str(exc))
        provider_id = str(params.get("id") or params.get("preset_id") or "").strip() or slugify(name)
        # Ensure a unique provider id when the slug/preset id is already taken.
        store = _providers()
        existing = store.list_sync(work_root=root)
        taken = {p.id for p in existing}
        candidate, suffix = provider_id, 2
        while candidate in taken:
            candidate = f"{provider_id}-{suffix}"
            suffix += 1
        provider_extra = params.get("extra") if isinstance(params.get("extra"), dict) else {}
        provider = ProviderConfig(
            id=candidate,
            name=name,
            api_type=str(params.get("api_type") or "openai").strip(),
            base_url=str(params.get("base_url") or "").strip(),
            api_key=api_key,
            adapter_profile_id=str(
                params.get("adapter_profile_id")
                or provider_extra.get("adapter_profile_id")
                if provider_extra
                else params.get("adapter_profile_id") or ""
            ).strip(),
            request_body=(
                dict(params["request_body"])
                if isinstance(params.get("request_body"), dict)
                else dict(provider_extra["request_body"])
                if isinstance(provider_extra.get("request_body"), dict)
                else {}
            ),
            adapter_profile_override=(
                dict(params["adapter_profile_override"])
                if isinstance(params.get("adapter_profile_override"), dict)
                else dict(provider_extra["adapter_profile_override"])
                if isinstance(provider_extra.get("adapter_profile_override"), dict)
                else {}
            ),
            reasoning=(
                dict(params["reasoning"])
                if isinstance(params.get("reasoning"), dict)
                else dict(provider_extra["reasoning"])
                if isinstance(provider_extra.get("reasoning"), dict)
                else {}
            ),
            extra=dict(provider_extra),
        )
        store.write(provider, scope="global", work_root=root)
        # Nested models[] (UI preset creations) become per-model jsonc files.
        #
        # Adding a provider must NOT change which model is currently in use:
        # the payload's ``is_default`` (the preset's intended model) is no
        # longer written as a global default, and no other model's flag is
        # cleared.  It is only used as a *first-run seed* for the main-chat
        # scene when no model has ever been used there — i.e. when there is
        # nothing to inherit from at all.
        models_raw = params.get("models")
        created_models: list[ModelConfig] = []
        seed_candidate = ""
        if isinstance(models_raw, list):
            model_store = _models()
            for raw in models_raw:
                if not isinstance(raw, dict) or not str(raw.get("model_id") or ""):
                    continue
                model = _model_config_from_payload(raw, fallback_provider=provider)
                model.id = _unique_model_record_id(model, model_store, root)
                if model.is_default and not seed_candidate:
                    seed_candidate = model.id
                model.is_default = False  # never a global default anymore
                model_store.write(model, scope="global", work_root=root)
                created_models.append(model)
        if seed_candidate:
            # First-run seed for scenes that have nothing remembered yet (the
            # preset's intended model). Never touches a scene that already has
            # a model, so adding a provider cannot change what is in use.
            from .model_selection import seed_scenes_with_model

            seed_scenes_with_model(seed_candidate)
        return OperationResult(
            name=request.name,
            payload={
                "provider": _provider_response(provider),
                "models": [_model_response(model) for model in created_models],
            },
        )

    async def provider_update(request: OperationRequest) -> OperationResult:
        params = request.payload
        provider_id = str(params.get("provider_id") or params.get("providerId") or params.get("id") or "")
        if not provider_id:
            return _error(request, "provider_id is required")
        store = _providers()
        provider = _find_provider(provider_id, store=store)
        if provider is None:
            return _error(request, f"provider not found: {provider_id}")
        try:
            update = _provider_update_fields(provider, params)
        except ApiKeyValidationError as exc:
            return _error(request, str(exc))
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
        removed_model_ids: list[str] = []
        for model in model_store.list_sync(work_root=root):
            if model.provider_id == provider.id or model.provider == provider.name:
                removed_model_ids.append(model.id)
                model_path = Path(model.source_path)
                if model_path.is_file():
                    model_path.unlink()
        model_store._cached_signature = None
        model_store._cached_models = None
        _groups().remove_model_ids(removed_model_ids)
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
        model.id = _unique_model_record_id(model, model_store, root)
        if model.is_default:
            _clear_other_defaults(model_store, model.id, root)
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
        payload.setdefault("provider", model.provider)
        payload.setdefault("provider_id", model.provider_id)
        updated = _model_config_from_payload(payload, fallback_provider=_fallback_provider(model))
        updated.id = model.id
        if updated.is_default:
            _clear_other_defaults(model_store, updated.id, root)
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
        path = Path(model.source_path) if model.source_path else model_store.write_path(model.id, scope="global", work_root=root)
        if path.is_file():
            path.unlink()
        model_store._cached_signature = None
        model_store._cached_models = None
        _groups().remove_model_ids([model.id])
        return OperationResult(name=request.name, payload={"ok": True})

    async def model_groups_list(request: OperationRequest) -> OperationResult:
        models = _models().list_sync(work_root=root)
        return OperationResult(
            name=request.name,
            payload=_groups().snapshot(available_model_ids=(model.id for model in models)),
        )

    async def model_group_create(request: OperationRequest) -> OperationResult:
        try:
            model_ids = _validated_existing_model_ids(request.payload.get("model_ids"), _models(), root)
            payload = _groups().create(
                str(request.payload.get("name") or ""),
                model_ids=model_ids,
                expected_revision=_optional_int(request.payload.get("expected_revision")),
            )
            return OperationResult(name=request.name, payload=payload)
        except (ValueError, LookupError, ModelGroupRevisionConflict) as exc:
            return _error(request, str(exc))

    async def model_group_update(request: OperationRequest) -> OperationResult:
        try:
            payload = _groups().update(
                str(request.payload.get("group_id") or request.payload.get("id") or ""),
                name=str(request.payload.get("name") or ""),
                expected_revision=_optional_int(request.payload.get("expected_revision")),
            )
            return OperationResult(name=request.name, payload=payload)
        except (ValueError, LookupError, ModelGroupRevisionConflict) as exc:
            return _error(request, str(exc))

    async def model_group_delete(request: OperationRequest) -> OperationResult:
        try:
            payload = _groups().delete(
                str(request.payload.get("group_id") or request.payload.get("id") or ""),
                expected_revision=_optional_int(request.payload.get("expected_revision")),
            )
            return OperationResult(name=request.name, payload=payload)
        except (ValueError, LookupError, ModelGroupRevisionConflict) as exc:
            return _error(request, str(exc))

    async def model_group_members_set(request: OperationRequest) -> OperationResult:
        try:
            model_ids = _validated_existing_model_ids(request.payload.get("model_ids"), _models(), root)
            payload = _groups().set_members(
                str(request.payload.get("group_id") or ""),
                model_ids,
                expected_revision=_optional_int(request.payload.get("expected_revision")),
            )
            return OperationResult(name=request.name, payload=payload)
        except (ValueError, LookupError, ModelGroupRevisionConflict) as exc:
            return _error(request, str(exc))

    async def model_groups_reorder(request: OperationRequest) -> OperationResult:
        try:
            raw_ids = request.payload.get("group_ids")
            if not isinstance(raw_ids, list):
                raise ValueError("group_ids must be an array")
            payload = _groups().reorder(
                [str(item) for item in raw_ids],
                expected_revision=_optional_int(request.payload.get("expected_revision")),
            )
            return OperationResult(name=request.name, payload=payload)
        except (ValueError, LookupError, ModelGroupRevisionConflict) as exc:
            return _error(request, str(exc))

    async def model_create_with_provider(request: OperationRequest) -> OperationResult:
        params = request.payload
        model_raw = params.get("model")
        provider_raw = params.get("provider")
        if not isinstance(model_raw, dict) or not isinstance(provider_raw, dict):
            return _error(request, "model and provider objects are required")
        group_id = str(params.get("group_id") or "").strip()
        group_snapshot = _groups().snapshot()
        group = next((item for item in group_snapshot["groups"] if item["id"] == group_id), None)
        if group is None:
            return _error(request, f"model group not found: {group_id}")
        try:
            expected_revision = _optional_int(params.get("expected_revision"))
            if expected_revision is not None and expected_revision != int(group_snapshot["revision"]):
                raise ModelGroupRevisionConflict(
                    f"model group revision conflict: expected {expected_revision}, current {group_snapshot['revision']}"
                )
            base_url = _normalize_provider_base_url(provider_raw.get("base_url"))
            mode = str(provider_raw.get("mode") or "").strip().lower()
            provider_store = _providers()
            created_provider = False
            if mode == "existing":
                provider = _find_provider(str(provider_raw.get("provider_id") or ""), store=provider_store)
                if provider is None:
                    raise LookupError(f"provider not found: {provider_raw.get('provider_id')}")
                if _normalize_provider_base_url(provider.base_url) != base_url:
                    raise ValueError("base_url does not match the selected provider")
            elif mode == "new":
                name = str(provider_raw.get("name") or "").strip()
                if not name:
                    raise ValueError("provider.name is required for mode=new")
                base_id = str(provider_raw.get("id") or "").strip() or slugify(name)
                candidate, suffix = base_id, 2
                taken = {item.id for item in provider_store.list_sync(work_root=root)}
                while candidate in taken:
                    candidate = f"{base_id}-{suffix}"
                    suffix += 1
                provider = _provider_config_from_nested(candidate, name, base_url, provider_raw)
                provider_store.write(provider, scope="global", work_root=root)
                created_provider = True
            else:
                raise ValueError("provider.mode must be existing or new")

            model_id = str(model_raw.get("model_id") or "").strip()
            if not model_id:
                raise ValueError("model.model_id is required")
            model_store = _models()
            model_payload = dict(model_raw)
            model_payload["provider_id"] = provider.id
            model_payload["provider"] = provider.name
            model = _model_config_from_payload(model_payload, fallback_provider=provider)
            model.id = _unique_model_record_id(model, model_store, root)
            try:
                model_store.write(model, scope="global", work_root=root)
            except Exception:
                if created_provider:
                    provider_path = Path(provider.source_path) if provider.source_path else provider_store.write_path(
                        provider.id, scope="global", work_root=root
                    )
                    if provider_path.is_file():
                        provider_path.unlink()
                raise
            model_ids = [*group["model_ids"], *group["dangling_model_ids"]]
            if model.id not in model_ids:
                model_ids.append(model.id)
            try:
                groups_payload = _groups().set_members(
                    group_id,
                    model_ids,
                    expected_revision=expected_revision,
                )
            except (ModelGroupRevisionConflict, OSError):
                model_path = Path(model.source_path) if model.source_path else model_store.write_path(
                    model.id, scope="global", work_root=root
                )
                if model_path.is_file():
                    model_path.unlink()
                model_store._cached_signature = None
                model_store._cached_models = None
                if created_provider:
                    provider_path = Path(provider.source_path) if provider.source_path else provider_store.write_path(
                        provider.id, scope="global", work_root=root
                    )
                    if provider_path.is_file():
                        provider_path.unlink()
                    provider_store._cached_signature = None
                    provider_store._cached_providers = None
                raise
            return OperationResult(
                name=request.name,
                payload={
                    "provider": _provider_response(provider),
                    "model": _model_response(model),
                    "groups": groups_payload,
                    "created_provider": created_provider,
                },
            )
        except (ValueError, LookupError, ModelGroupRevisionConflict, OSError) as exc:
            return _error(request, str(exc))

    async def settings_get(request: OperationRequest) -> OperationResult:
        namespace = str(request.payload.get("namespace") or "").strip()
        if not namespace:
            return _error(request, "namespace is required")
        # core.imagegen lives in its own imagegen.jsonc (frontend contract kept).
        if namespace == IMAGEGEN_NAMESPACE:
            value = dict(load_imagegen_config(data_dir))
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
            current = load_imagegen_config(data_dir)
            incoming = dict(value)
            # Empty or masked api_key keeps the stored key (audit 17 S3).
            submitted_key = incoming.get("api_key")
            if isinstance(submitted_key, str) and submitted_key.strip() in {"", MASKED_API_KEY}:
                incoming.pop("api_key", None)
            merged = {**current, **incoming}
            save_imagegen_config(merged, data_dir)
        elif namespace == "core.runtimeControls":
            # Safety-critical namespace: validate the value domain server-side
            # so a caller cannot smuggle arbitrary permission settings
            # (audit 03 S3 / 12 S2 — this namespace gates auto-approval).
            merged = _merge_runtime_controls(request, get_setting(namespace), dict(value))
            if merged is None:
                return _error(request, "invalid core.runtimeControls value")
            set_setting(namespace, merged)
        elif namespace == CONTEXT_COMPACTION_NAMESPACE:
            merged = _merge_context_compaction(
                get_setting(namespace), dict(value)
            )
            if merged is None:
                return _error(request, "invalid core.contextCompaction value")
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
        try:
            api_key = validate_api_key_text(api_key)
        except ApiKeyValidationError as exc:
            return _error(request, f"LAMTOOLS_LLM_API_KEY 无效：{exc}")
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

    # ── workspace.search：文件/内容搜索（搜索对话框 UI 直调，与工具
    #    search_files/search_content 同语义的轻量 operation 封装）──
    # 跳过：构建/依赖/版本库等基础设施目录；.lam 为 LamTools 本地配置根，
    # 整体跳过会漏掉用户文档——仅保留 .lam/docs（RAG 插件同名文档根约定），
    # 其余 .lam 子目录（config/plugins/tools/loadtools/…）不进工作区搜索。
    _SEARCH_SKIP_DIRS = frozenset(
        {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
         ".lamtools", ".lam", "target", ".acceptance", ".cache"}
    )

    def _keep_dir(dirname: str, dirpath: str) -> bool:
        # .lam 本身放行进入，其子目录仅保留 docs（其余 config/plugins/... 跳过）
        if dirname == ".lam":
            return True
        if Path(dirpath).name == ".lam":
            return dirname == "docs"
        return dirname not in _SEARCH_SKIP_DIRS

    async def workspace_search(request: OperationRequest) -> OperationResult:
        payload = request.payload if isinstance(request.payload, dict) else {}
        query = str(payload.get("query") or "").strip()
        if not query:
            return OperationResult(name=request.name, status="error", payload={"error": "query 不能为空"})
        mode = str(payload.get("mode") or "content")
        if mode not in ("files", "content"):
            return OperationResult(name=request.name, status="error", payload={"error": f"mode 无效: {mode}"})
        limit = max(1, min(int(payload.get("limit") or 20), 100))
        search_root = Path(root or ".")  # work_root 闭包

        def _iter_files(base: Path):
            if base.is_file():
                yield base
                return
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if _keep_dir(d, dirpath)]
                for fname in filenames:
                    yield Path(dirpath) / fname

        results: list[dict] = []
        try:
            for fpath in _iter_files(search_root):
                if len(results) >= limit:
                    break
                try:
                    rel = fpath.relative_to(search_root).as_posix()
                except ValueError:
                    continue
                if mode == "files":
                    if query.lower() not in fpath.name.lower():
                        continue
                    results.append({"path": rel})
                    continue
                # content：子串行匹配
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for line_no, line in enumerate(text.splitlines(), 1):
                    if query in line:
                        results.append({"path": rel, "line": line_no, "content": line.strip()[:200]})
                        if len(results) >= limit:
                            break
        except OSError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": f"搜索失败: {exc}"})
        return OperationResult(
            name=request.name,
            payload={
                "mode": mode,
                "query": query,
                "results": results,
                "total": len(results),
                "truncated": len(results) >= limit,
            },
        )

    async def config_notices_drain(request: OperationRequest) -> OperationResult:
        """Return and clear pending "config changed behind your back" notices.

        The provider/model/settings jsonc files are watched for external edits
        (cloud sync, another editor/instance, restored backup).  The UI drains
        this endpoint and shows each notice, so a reload is never silent.
        """
        from .change_notice import drain_config_change_notices
        from .model_selection import drain_model_notices

        notices = [*drain_config_change_notices(), *drain_model_notices()]
        return OperationResult(
            name=request.name,
            payload={"notices": notices},
        )

    for name, handler in {
        "config.providers.list": providers_list,
        "config.provider.create": provider_create,
        "config.provider.update": provider_update,
        "config.notices.drain": config_notices_drain,
        "workspace.search": workspace_search,
        "config.provider.delete": provider_delete,
        "config.models.list": models_list,
        "config.model.create": model_create,
        "config.model.create_with_provider": model_create_with_provider,
        "config.model.update": model_update,
        "config.model.delete": model_delete,
        "config.model_groups.list": model_groups_list,
        "config.model_group.create": model_group_create,
        "config.model_group.update": model_group_update,
        "config.model_group.delete": model_group_delete,
        "config.model_group.members.set": model_group_members_set,
        "config.model_groups.reorder": model_groups_reorder,
        "config.import_env": import_environment_operation,
        "settings.get": settings_get,
        "settings.update": settings_update,
    }.items():
        catalog.register(name, handler)
    return catalog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dict_value(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    return dict(value) if isinstance(value, dict) else {}


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _validated_existing_model_ids(value: Any, store: ModelStore, work_root: str | None) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("model_ids must be an array")
    existing = {item.id for item in store.list_sync(work_root=work_root)}
    result: list[str] = []
    for raw in value:
        model_id = str(raw or "").strip()
        if model_id not in existing:
            raise ValueError(f"model not found: {model_id}")
        if model_id not in result:
            result.append(model_id)
    return result


def _normalize_provider_base_url(value: Any) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("provider.base_url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("provider.base_url must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("provider.base_url must not contain a query or fragment")
    path = parsed.path.rstrip("/")
    if path.lower().endswith("/chat/completions"):
        raise ValueError("provider.base_url must be an API base URL, not a /chat/completions endpoint")
    if len(raw) > 2048:
        raise ValueError("provider.base_url is too long")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, path, "", ""))


def _provider_config_from_nested(
    provider_id: str,
    name: str,
    base_url: str,
    payload: dict[str, Any],
) -> ProviderConfig:
    return ProviderConfig(
        id=provider_id,
        name=name,
        api_type=str(payload.get("api_type") or "openai").strip(),
        base_url=base_url,
        api_key=str(payload.get("api_key") or "").strip(),
        adapter_profile_id=str(payload.get("adapter_profile_id") or "").strip(),
        request_body=_dict_value(payload, "request_body"),
        adapter_profile_override=_dict_value(payload, "adapter_profile_override"),
        reasoning=_dict_value(payload, "reasoning"),
        notes=str(payload.get("notes") or "").strip(),
    )


def _unique_model_record_id(model: ModelConfig, store: ModelStore, work_root: str | None) -> str:
    requested = str(model.id or "").strip()
    base = requested or make_model_record_id(model.provider_id or model.provider, model.model_id)
    candidate, suffix = base, 2
    while store.get_sync(candidate, work_root=work_root) is not None:
        candidate = f"{base[:124]}-{suffix}"
        suffix += 1
    return candidate


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
        id=str(params.get("id") or params.get("model_record_id") or "").strip(),
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
        request_body=(
            dict(extra["request_body"])
            if isinstance(extra.get("request_body"), dict)
            else _dict_value(params, "request_body")
        ),
        adapter_profile_override=(
            dict(extra["adapter_profile_override"])
            if isinstance(extra.get("adapter_profile_override"), dict)
            else _dict_value(params, "adapter_profile_override")
        ),
        reasoning=(
            dict(extra["reasoning"])
            if isinstance(extra.get("reasoning"), dict)
            else _dict_value(params, "reasoning")
        ),
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
        updates["api_key"] = validate_api_key_text(api_key)
    extra = params.get("extra") if isinstance(params.get("extra"), dict) else {}
    if isinstance(params.get("extra"), dict):
        updates["extra"] = dict(extra)
    for key in ("request_body", "adapter_profile_override", "reasoning"):
        value = params.get(key) if isinstance(params.get(key), dict) else extra.get(key)
        if isinstance(value, dict):
            updates[key] = dict(value)
    if params.get("adapter_profile_id") is not None or "adapter_profile_id" in extra:
        updates["adapter_profile_id"] = str(
            params.get("adapter_profile_id") or extra.get("adapter_profile_id") or ""
        ).strip()
    if isinstance(params.get("is_default"), bool):
        updates["is_default"] = params["is_default"]
    return replace(provider, **updates)


def _fallback_provider(model: ModelConfig) -> ProviderConfig | None:
    if not (model.provider or model.provider_id):
        return None
    return ProviderStore().get_sync(model.provider_id or model.provider)


def _clear_other_defaults(model_store: ModelStore, model_id: str, work_root: str | None) -> None:
    for existing in model_store.list_sync(work_root=work_root):
        if existing.id != model_id and existing.is_default:
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
_DEFAULT_PERMISSION_PRESETS = ("ask", "auto", "full_access")
_RUNTIME_CONTROL_BOOLS = (
    "allow_access_outside_workdir",
)


def _merge_context_compaction(current: Any, incoming: dict[str, Any]) -> dict[str, Any] | None:
    """Merge context-compaction settings with strict retained-step bounds."""
    merged = {**(current if isinstance(current, dict) else {})}
    if "retained_steps" in incoming:
        raw = incoming["retained_steps"]
        if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= MAX_RETAINED_STEPS:
            return None
        merged["retained_steps"] = raw
    return merged


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
        elif key == "permission_preset":
            if raw not in _DEFAULT_PERMISSION_PRESETS:
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
