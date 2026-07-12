from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.services.llm_config_service import (
    MODEL_ROUTING_NAMESPACE,
    ensure_model_routing_state,
    set_route_model,
)


CORE_SETTING_PREFIXES = ("core.", "lamtools.")
WRITER_SETTING_PREFIXES = ("writer.",)
LEGACY_SHARED_NAMESPACES = {MODEL_ROUTING_NAMESPACE}
LEGACY_WRITER_NAMESPACES = {"lamwriter.runtimeControls", "lamwriter.ui"}


def setting_response(namespace: str, value: dict[str, Any], updated_at: Any = None) -> dict[str, Any]:
    return {"namespace": namespace, "value": value, "updated_at": updated_at}


def is_shared_setting_namespace(namespace: str) -> bool:
    if namespace in LEGACY_SHARED_NAMESPACES:
        return True
    if namespace in LEGACY_WRITER_NAMESPACES:
        return False
    if namespace.startswith(CORE_SETTING_PREFIXES):
        return True
    if namespace.startswith(WRITER_SETTING_PREFIXES):
        return False
    return False


def is_writer_setting_namespace(namespace: str) -> bool:
    if namespace in LEGACY_WRITER_NAMESPACES:
        return True
    return namespace.startswith(WRITER_SETTING_PREFIXES)


def _target_db(db: AsyncSession, namespace: str, shared_db: AsyncSession | None) -> AsyncSession:
    if is_shared_setting_namespace(namespace) and shared_db is not None:
        return shared_db
    return db


async def get_app_setting_value(
    db: AsyncSession,
    namespace: str,
    *,
    shared_db: AsyncSession | None = None,
) -> dict[str, Any]:
    target_db = _target_db(db, namespace, shared_db)
    if namespace == MODEL_ROUTING_NAMESPACE:
        value = await ensure_model_routing_state(target_db)
        await target_db.commit()
        setting = await target_db.get(AppSetting, namespace)
        return setting_response(namespace, value, setting.updated_at if setting is not None else None)
    setting = await target_db.get(AppSetting, namespace)
    if setting is None:
        return setting_response(namespace, {}, None)
    return setting_response(setting.namespace, setting.value or {}, setting.updated_at)


async def update_app_setting_value(
    db: AsyncSession,
    namespace: str,
    value: dict[str, Any],
    *,
    shared_db: AsyncSession | None = None,
) -> dict[str, Any]:
    target_db = _target_db(db, namespace, shared_db)
    if namespace == MODEL_ROUTING_NAMESPACE:
        routes = value.get("routes") if isinstance(value.get("routes"), dict) else {}
        for task_type, entry in routes.items():
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("model_id") or "") if entry.get("mode") == "model" else ""
            if str(task_type) == "writer" and not model_id:
                continue
            await set_route_model(target_db, str(task_type), model_id or None)
        routed_value = await ensure_model_routing_state(target_db)
        await target_db.commit()
        setting = await target_db.get(AppSetting, namespace)
        return setting_response(namespace, routed_value, setting.updated_at if setting is not None else None)
    setting = await target_db.get(AppSetting, namespace)
    if setting is None:
        setting = AppSetting(namespace=namespace, value=value)
        target_db.add(setting)
    else:
        setting.value = value
    await target_db.commit()
    await target_db.refresh(setting)
    return setting_response(setting.namespace, setting.value or {}, setting.updated_at)


async def move_writer_settings_from_shared_to_writer(
    db: AsyncSession,
    shared_db: AsyncSession,
) -> list[str]:
    result = await shared_db.execute(select(AppSetting))
    moved: list[str] = []
    for shared_setting in result.scalars().all():
        namespace = str(shared_setting.namespace or "")
        if not is_writer_setting_namespace(namespace):
            continue
        writer_setting = await db.get(AppSetting, namespace)
        if writer_setting is None:
            db.add(AppSetting(namespace=namespace, value=shared_setting.value or {}))
        else:
            writer_setting.value = shared_setting.value or {}
        await shared_db.delete(shared_setting)
        moved.append(namespace)
    if moved:
        await db.commit()
        await shared_db.commit()
    return moved


__all__ = [
    "get_app_setting_value",
    "is_shared_setting_namespace",
    "is_writer_setting_namespace",
    "move_writer_settings_from_shared_to_writer",
    "setting_response",
    "update_app_setting_value",
]
