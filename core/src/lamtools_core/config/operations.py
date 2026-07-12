from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.exc import OperationalError

from lamtools_core.app.operation_catalog import OperationCatalog, OperationRequest, OperationResult

from .read import list_model_configs, list_provider_configs
from .write import (
    create_model_config,
    create_provider_config,
    delete_model_config,
    delete_provider_config,
    update_model_config,
    update_provider_config,
)

ConfigSessionFactory = Callable[[], Any]
ConfigWrite = Callable[[Any], Awaitable[Any]]

_SQLITE_LOCK_RETRY_DELAYS = (0.05, 0.15)


def build_shared_config_operation_catalog(
    session_factory: ConfigSessionFactory,
    *,
    locked_message: str = "database is busy, retry later",
    sqlite_lock_retry_delays: tuple[float, ...] = _SQLITE_LOCK_RETRY_DELAYS,
    list_providers: Callable[..., Awaitable[list[dict[str, Any]]]] = list_provider_configs,
    create_provider: Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any]]] = create_provider_config,
    update_provider: Callable[[Any, str, dict[str, Any]], Awaitable[dict[str, Any]]] = update_provider_config,
    delete_provider: Callable[[Any, str], Awaitable[None]] = delete_provider_config,
    list_models: Callable[..., Awaitable[list[dict[str, Any]]]] = list_model_configs,
    create_model: Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any]]] = create_model_config,
    update_model: Callable[[Any, str, dict[str, Any]], Awaitable[dict[str, Any]]] = update_model_config,
    delete_model: Callable[[Any, str], Awaitable[None]] = delete_model_config,
) -> OperationCatalog:
    catalog = OperationCatalog()

    async def providers_list(request: OperationRequest) -> OperationResult:
        limit = _bounded_int(request.payload.get("limit"), default=50, minimum=1, maximum=200)
        offset = _bounded_int(request.payload.get("offset"), default=0, minimum=0, maximum=100000)
        async with session_factory() as db:
            providers = await list_providers(db, limit=limit, offset=offset)
        return OperationResult(name=request.name, payload={"providers": providers})

    async def provider_create(request: OperationRequest) -> OperationResult:
        params = request.payload
        missing = [key for key in ("name", "base_url", "api_key") if not str(params.get(key) or "")]
        if missing:
            return _error(request, "name, base_url and api_key are required")
        payload = {
            "name": str(params.get("name") or ""),
            "api_type": str(params.get("api_type") or "openai"),
            "base_url": str(params.get("base_url") or ""),
            "api_key": str(params.get("api_key") or ""),
            "extra": params.get("extra") if isinstance(params.get("extra"), dict) else None,
        }
        try:
            provider = await _retry_sqlite_locked_write(
                session_factory,
                lambda db: create_provider(db, payload),
                retry_delays=sqlite_lock_retry_delays,
            )
        except OperationalError as exc:
            if _is_sqlite_locked_error(exc):
                return _error(request, locked_message)
            raise
        return OperationResult(name=request.name, payload={"provider": provider})

    async def provider_update(request: OperationRequest) -> OperationResult:
        params = request.payload
        provider_id = str(params.get("provider_id") or params.get("providerId") or params.get("id") or "")
        if not provider_id:
            return _error(request, "provider_id is required")
        update_data = {
            key: value
            for key, value in {
                "name": params.get("name"),
                "api_type": params.get("api_type"),
                "base_url": params.get("base_url"),
                "api_key": params.get("api_key"),
                "extra": params.get("extra"),
            }.items()
            if value is not None
        }
        try:
            provider = await _retry_sqlite_locked_write(
                session_factory,
                lambda db: update_provider(db, provider_id, update_data),
                retry_delays=sqlite_lock_retry_delays,
            )
        except OperationalError as exc:
            if _is_sqlite_locked_error(exc):
                return _error(request, locked_message)
            raise
        except LookupError as exc:
            return _error(request, str(exc))
        return OperationResult(name=request.name, payload={"provider": provider})

    async def provider_delete(request: OperationRequest) -> OperationResult:
        provider_id = str(request.payload.get("provider_id") or request.payload.get("providerId") or request.payload.get("id") or "")
        if not provider_id:
            return _error(request, "provider_id is required")
        try:
            await _retry_sqlite_locked_write(
                session_factory,
                lambda db: delete_provider(db, provider_id),
                retry_delays=sqlite_lock_retry_delays,
            )
        except OperationalError as exc:
            if _is_sqlite_locked_error(exc):
                return _error(request, locked_message)
            raise
        except LookupError as exc:
            return _error(request, str(exc))
        return OperationResult(name=request.name, payload={"ok": True})

    async def models_list(request: OperationRequest) -> OperationResult:
        limit = _bounded_int(request.payload.get("limit"), default=50, minimum=1, maximum=200)
        offset = _bounded_int(request.payload.get("offset"), default=0, minimum=0, maximum=100000)
        provider_id = request.payload.get("provider_id") or request.payload.get("providerId")
        async with session_factory() as db:
            models = await list_models(
                db,
                provider_id=str(provider_id) if provider_id else None,
                limit=limit,
                offset=offset,
            )
        return OperationResult(name=request.name, payload={"models": models})

    async def model_create(request: OperationRequest) -> OperationResult:
        params = request.payload
        missing = [key for key in ("provider_id", "model_id") if not str(params.get(key) or "")]
        if missing:
            return _error(request, "provider_id and model_id are required")
        payload = _model_payload(params)
        try:
            model = await _retry_sqlite_locked_write(
                session_factory,
                lambda db: create_model(db, payload),
                retry_delays=sqlite_lock_retry_delays,
            )
        except OperationalError as exc:
            if _is_sqlite_locked_error(exc):
                return _error(request, locked_message)
            raise
        except LookupError as exc:
            return _error(request, str(exc))
        return OperationResult(name=request.name, payload={"model": model})

    async def model_update(request: OperationRequest) -> OperationResult:
        params = request.payload
        model_record_id = str(params.get("model_record_id") or params.get("id") or "")
        if not model_record_id:
            return _error(request, "model_record_id is required")
        update_data = {
            key: value
            for key, value in {
                "provider_id": params.get("provider_id"),
                "model_id": params.get("model_id"),
                "display_name": params.get("display_name"),
                "context_window": params.get("context_window"),
                "max_output_tokens": params.get("max_output_tokens"),
                "thinking_supported": params.get("thinking_supported"),
                "thinking_budget": params.get("thinking_budget"),
                "temperature": params.get("temperature"),
                "extra": params.get("extra"),
            }.items()
            if value is not None
        }
        try:
            model = await _retry_sqlite_locked_write(
                session_factory,
                lambda db: update_model(db, model_record_id, update_data),
                retry_delays=sqlite_lock_retry_delays,
            )
        except OperationalError as exc:
            if _is_sqlite_locked_error(exc):
                return _error(request, locked_message)
            raise
        except (LookupError, ValueError) as exc:
            return _error(request, str(exc))
        return OperationResult(name=request.name, payload={"model": model})

    async def model_delete(request: OperationRequest) -> OperationResult:
        model_record_id = str(request.payload.get("model_record_id") or request.payload.get("id") or "")
        if not model_record_id:
            return _error(request, "model_record_id is required")
        try:
            await _retry_sqlite_locked_write(
                session_factory,
                lambda db: delete_model(db, model_record_id),
                retry_delays=sqlite_lock_retry_delays,
            )
        except OperationalError as exc:
            if _is_sqlite_locked_error(exc):
                return _error(request, locked_message)
            raise
        except LookupError as exc:
            return _error(request, str(exc))
        return OperationResult(name=request.name, payload={"ok": True})

    for name, handler in {
        "config.providers.list": providers_list,
        "config.provider.create": provider_create,
        "config.provider.update": provider_update,
        "config.provider.delete": provider_delete,
        "config.models.list": models_list,
        "config.model.create": model_create,
        "config.model.update": model_update,
        "config.model.delete": model_delete,
    }.items():
        catalog.register(name, handler)
    return catalog


async def _retry_sqlite_locked_write(
    session_factory: ConfigSessionFactory,
    write: ConfigWrite,
    *,
    retry_delays: tuple[float, ...],
) -> Any:
    for attempt in range(len(retry_delays) + 1):
        try:
            async with session_factory() as db:
                return await write(db)
        except OperationalError as exc:
            if not _is_sqlite_locked_error(exc) or attempt >= len(retry_delays):
                raise
            await asyncio.sleep(retry_delays[attempt])
    raise RuntimeError("SQLite write retry exhausted")


def _model_payload(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_id": str(params.get("provider_id") or ""),
        "model_id": str(params.get("model_id") or ""),
        "display_name": str(params.get("display_name") or ""),
        "context_window": int(params.get("context_window") or 128000),
        "max_output_tokens": int(params.get("max_output_tokens") or 16384),
        "thinking_supported": bool(params.get("thinking_supported")),
        "thinking_budget": int(10000 if params.get("thinking_budget") is None else params["thinking_budget"]),
        "temperature": float(0.7 if params.get("temperature") is None else params["temperature"]),
        "extra": params.get("extra") if isinstance(params.get("extra"), dict) else None,
    }


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _is_sqlite_locked_error(exc: BaseException) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


def _error(request: OperationRequest, message: str) -> OperationResult:
    return OperationResult(name=request.name, status="error", payload={"error": message})


__all__ = ["build_shared_config_operation_catalog"]
