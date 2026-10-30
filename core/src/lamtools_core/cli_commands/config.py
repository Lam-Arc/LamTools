"""Model-store context, provider resolution and command-line resource paths."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from lamtools_core.config.model_store import ModelConfig, ModelStore
from lamtools_core.config.provider_store import ProviderConfig, ProviderStore
from lamtools_core.config.root import ensure_projects_root
from lamtools_core.config.settings_store import get_setting
from lamtools_core.llm.http_client import LLMConfig
from lamtools_core.llm.profiles import (
    declared_reasoning_levels,
    load_adapter_profiles_from_dirs,
    reasoning_off_supported,
    resolve_adapter_profile_from_profiles,
)


_default_model_store: ModelStore | None = None


_model_store_work_root: str | None = None


def configure_model_store_context(*, work_root: str | None, store: ModelStore | None = None) -> None:
    """Register the shared ModelStore + work_root for the running process."""
    global _default_model_store, _model_store_work_root
    _model_store_work_root = work_root
    if store is not None:
        _default_model_store = store


def _get_model_store() -> ModelStore:
    return _default_model_store if _default_model_store is not None else ModelStore()


def load_llm_config(*, model_ref: str = "", work_root: str | None = None) -> LLMConfig:
    """Resolve an LLM config from jsonc model + provider definitions.

    Model definitions come from the ModelStore (jsonc files); provider
    connection info (base_url / api_key / api_type) comes from the
    ProviderStore (jsonc files). There is no database and no fallback path —
    an unresolvable model_ref raises ``ValueError``.
    """
    store = _get_model_store()
    ref = model_ref.strip()
    if not ref:
        # An explicit routing setting is a deliberate route, not a default.
        ref = _model_ref_from_routing()
    if not ref:
        # There is no "global default model": replacing a missing model with
        # whatever is marked default is exactly the silent switch that made the
        # UI show one model while another ran. Callers that have a scene (the
        # live turn path, plugin backends, background tasks) resolve via
        # ``lamtools_core.config.model_selection`` before reaching here.
        raise ValueError(
            "model id is required — no model was specified by the caller and no "
            "session/scene has a model to inherit; 请先添加供应商/模型"
            "（GUI：设置 → 模型与供应商；CLI：--model-id 或 lamtools.modelRouting 路由设置）"
        )
    # user:“继续，把 2 阶段都做完”+(插件实际模型调用显式固定项目，不修改进程全局模型上下文)。
    effective_root = work_root if work_root is not None else _model_store_work_root
    model = store.get_sync(ref, work_root=effective_root)
    if model is None:
        raise ValueError(f"model not found: {model_ref}")
    provider = _resolve_provider_for_model(model, work_root=work_root) if work_root is not None else _resolve_provider_for_model(model)
    if provider is None:
        raise ValueError(
            f"provider not found for model: {ref} (provider={model.provider or model.provider_id or '?'})"
        )
    base_url = (provider.base_url or "").strip().rstrip("/")
    parsed_base_url = urlsplit(base_url)
    if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
        raise ValueError(
            f"provider base_url must be an absolute HTTP(S) URL for model: {ref}"
        )
    return LLMConfig(
        provider_name=provider.name,
        provider_api_type=provider.api_type or "openai",
        base_url=base_url,
        api_key=provider.api_key,
        model_record_id=model.id,
        model_id=model.model_id,
        display_name=model.display_name or model.model_id,
        notes=model.notes,
        context_window=model.context_window,
        max_output_tokens=model.max_output_tokens,
        temperature=model.temperature,
        thinking_supported=model.thinking_supported,
        thinking_budget=model.thinking_budget,
        reasoning_effort=model.reasoning_effort,
        capability=model.resolved_capability,
        provider_extra=_provider_extra(provider),
        model_extra=model.to_extra(),
    )


def _provider_extra(provider: ProviderConfig) -> dict[str, Any]:
    """Surface the provider's adapter_profile_id through the extra plumbing."""
    return provider.to_extra()


def _resolve_provider_for_model(model: ModelConfig, *, work_root: str | None = None) -> ProviderConfig | None:
    """Look up a provider by the model's provider_id then by name.

    A model with an explicit provider reference must never be rebound to an
    unrelated default provider.  The default is only a compatibility fallback
    for legacy model records that contain no provider identity at all.
    """
    store = ProviderStore()
    effective_root = work_root if work_root is not None else _model_store_work_root
    if model.provider_id:
        provider = store.get_sync(model.provider_id, work_root=effective_root)
        if provider is not None:
            return provider
    if model.provider:
        provider = store.get_sync(model.provider, work_root=effective_root)
        if provider is not None:
            return provider
    if model.provider_id or model.provider:
        return None
    # Last resort for legacy records with no provider identity.
    return store.default_sync(work_root=effective_root)


def _model_ref_from_routing() -> str:
    """Resolve the routed model_id from settings.jsonc (lamtools.modelRouting)."""
    data = get_setting("lamtools.modelRouting")
    if isinstance(data, dict):
        routes = data.get("routes") if isinstance(data.get("routes"), dict) else {}
        for route_name in ("core", "default"):
            route = routes.get(route_name) if isinstance(routes.get(route_name), dict) else {}
            model_id = str(route.get("model_id") or "").strip()
            if model_id:
                return model_id
    return ""


def configured_model_ref() -> str:
    """The model the settings route as the default, or "" when none is set.

    Public wrapper so boot code can tell "no global default is configured (which
    is the normal state — the model is chosen per turn)" apart from "the
    configured default exists but is unusable (a real misconfiguration)".
    """
    return _model_ref_from_routing()


def list_llm_model_configs(*, work_root: str | None = None) -> list[dict[str, Any]]:
    """List all jsonc model definitions with resolved provider info.

    Model definitions are authoritative (jsonc only); each entry resolves its
    provider id / api_type through the ProviderStore so the UI can render
    providers without any database.
    """
    effective_root = work_root or _model_store_work_root
    store = _get_model_store()
    models = store.list_sync(work_root=effective_root)
    providers = ProviderStore().list_sync(work_root=effective_root)
    provider_map: dict[str, ProviderConfig] = {}
    for provider in providers:
        provider_map[provider.id] = provider
        provider_map[provider.name] = provider
    resolved: list[dict[str, Any]] = []
    for m in models:
        provider = provider_map.get(m.provider_id) or provider_map.get(m.provider) or None
        adapter_profile = _resolve_adapter_profile(
            LLMConfig(
                provider_name=provider.name if provider is not None else m.provider,
                provider_api_type=provider.api_type if provider is not None else "openai",
                base_url=(provider.base_url if provider is not None else "").rstrip("/"),
                api_key="",
                model_record_id=m.id,
                model_id=m.model_id,
                display_name=m.display_name,
                context_window=m.context_window,
                max_output_tokens=m.max_output_tokens,
                temperature=m.temperature,
                thinking_supported=m.thinking_supported,
                thinking_budget=m.thinking_budget,
                reasoning_effort=m.reasoning_effort,
                capability=m.resolved_capability,
                provider_extra=_provider_extra(provider) if provider is not None else {},
                model_extra=m.to_extra(),
            ),
            (),
        )
        resolved.append(
            {
                "id": m.id,
                "model_record_id": m.id,
                "provider_id": m.provider_id or (provider.id if provider is not None else ""),
                "provider_name": provider.name if provider is not None else m.provider,
                "provider_api_type": provider.api_type if provider is not None else "openai",
                "model_id": m.model_id,
                "display_name": m.display_name,
                "context_window": m.context_window,
                "max_output_tokens": m.max_output_tokens,
                "thinking_supported": m.thinking_supported,
                "thinking_budget": m.thinking_budget,
                "temperature": m.temperature,
                "capability": m.resolved_capability,
                "reasoning_off_supported": reasoning_off_supported(adapter_profile),
                "reasoning_levels": declared_reasoning_levels(adapter_profile),
                "notes": m.notes,
                "is_default": m.is_default,
                "adapter_profile_id": m.adapter_profile_id,
                "extra": m.to_extra(),
            }
        )
    return resolved


def _resolve_adapter_profile(config: LLMConfig, adapter_dirs: tuple[Path | str, ...]) -> dict[str, Any]:
    profiles = load_adapter_profiles_from_dirs([*_default_adapter_dirs(), *[Path(item) for item in adapter_dirs]])
    return resolve_adapter_profile_from_profiles(
        profiles,
        api_type=config.provider_api_type,
        base_url=config.base_url,
        model_id=config.model_id,
        provider_name=config.provider_name,
        provider_extra=config.provider_extra,
        model_extra=config.model_extra,
    )


def _default_adapter_dirs() -> list[Path]:
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        # PyInstaller: adapter profiles are bundled under _MEIPASS/config/.
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        dirs.append(meipass / "config" / "llm_adapters")
    else:
        dirs.append(_repo_root() / "core" / "config" / "llm_adapters")
    env_dir = os.environ.get("LAMTOOLS_LLM_ADAPTER_DIR")
    if env_dir:
        dirs.append(Path(env_dir))
    return dirs


def _resolve_core_db(value: Path | str | None) -> Path:
    if value:
        return Path(value)
    env = os.environ.get("LAMTOOLS_CORE_DB")
    if env:
        return Path(env)
    return _repo_root() / "data" / "core.db"


def _resolve_cli_context_window(args: argparse.Namespace) -> int | None:
    model_id = getattr(args, "model_id", "") or ""
    if not model_id:
        return None
    try:
        config = load_llm_config(model_ref=model_id)
        return config.context_window if config.context_window > 0 else None
    except Exception:
        return None


def _resolve_cli_max_output_tokens(args: argparse.Namespace) -> int | None:
    explicit = getattr(args, "max_tokens", None)
    if explicit is not None:
        return int(explicit) if int(explicit) > 0 else None
    model_id = getattr(args, "model_id", "") or ""
    try:
        config = load_llm_config(model_ref=model_id)
        return config.max_output_tokens if config.max_output_tokens > 0 else None
    except Exception:
        return None


def _resolve_thread_id(value: str | None) -> str:
    clean = str(value or "").strip()
    return clean or f"core-cli-{uuid.uuid4().hex[:8]}"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _default_run_dir() -> Path:
    return _repo_root() / "tmp" / f"core-cli-run-{time.strftime('%Y%m%d-%H%M%S')}"


def _default_cli_plugin_roots() -> list[Path]:
    """Resolve the same plugin roots used by the Core HTTP/GUI host."""
    from lamtools_core.app.base_agent import default_core_agent_plugin_roots
    from lamtools_core.config.root import default_projects_root

    configured_work_root = os.environ.get("LAMTOOLS_CORE_WORK_ROOT")
    work_root = Path(configured_work_root) if configured_work_root else default_projects_root() / "default"
    return default_core_agent_plugin_roots(work_root)


def _default_cli_plugin_state_path() -> Path:
    """Resolve the persistent plugin ledger used by the HTTP host."""
    data_dir = os.environ.get("LAMTOOLS_CORE_DATA_DIR")
    if data_dir:
        return Path(data_dir) / "plugin-system.jsonc"
    return _resolve_core_db(None).resolve().parent / "core-agent" / "plugin-system.jsonc"


def _default_work_root() -> Path:
    return ensure_projects_root() / "default"
