"""Scene-scoped model memory and the single runtime model-resolution contract.

There is deliberately **no "global default model"**: the only things that decide
which model a call uses are

* an explicit model named by the caller, and
* otherwise the model the *same scene* used last (the session's own last-used
  model for a conversation turn, or the scene's most recent model for a
  non-conversation call).

Scenes are kept separate on purpose: the desktop pet's cheap model must never
leak into the main conversation just because it was used most recently.  Every
inheritance/fallback is explicit — either the same model continues, or the
resolver reports exactly which model replaced which, or it fails with a clear
message.  A silent cross-provider substitution is never acceptable, because the
user cannot see it happen (that is the whole point of this module).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .model_store import ModelConfig, ModelStore
from .provider_store import ProviderConfig, ProviderStore

SCENE_CHAT = "chat"
SCENE_STUDY = "study"
SCENE_DESKTOP_PET = "desktop_pet"
SCENE_BACKGROUND = "background"

SCENES = (SCENE_CHAT, SCENE_STUDY, SCENE_DESKTOP_PET, SCENE_BACKGROUND)

SCENE_LABELS = {
    SCENE_CHAT: "主对话",
    SCENE_STUDY: "学习",
    SCENE_DESKTOP_PET: "桌宠",
    SCENE_BACKGROUND: "后台任务",
}

#: settings.jsonc namespace holding the per-scene recent-model list.
SCENE_MEMORY_NAMESPACE = "lamtools.modelSceneMemory"

#: How many recently-used models each scene remembers (for same-scene fallback).
MAX_SCENE_RECENT = 8

NO_MODEL_MESSAGE = "请先添加供应商/模型（设置 → 模型与供应商）"


class ModelResolutionError(ValueError):
    """No usable model could be resolved for a scene — never silently guessed."""


@dataclass(frozen=True)
class SceneModelResolution:
    """Outcome of resolving a scene's model.

    ``replaced_from`` is the model the scene wanted but could no longer use;
    it is empty when the resolved model is the one the scene actually
    remembered.  ``notice`` is the user-facing sentence for that replacement.
    """

    model_id: str
    replaced_from: str = ""
    notice: str = ""

    @property
    def replaced(self) -> bool:
        return bool(self.replaced_from)


_lock = threading.RLock()
#: Notices about model substitution / missing models, drained by the UI.
_pending_notices: list[str] = []
MAX_PENDING_NOTICES = 50


def scene_label(scene: str) -> str:
    return SCENE_LABELS.get(scene, scene)


def scene_for_plugin(plugin: Any = None, *, name: str = "") -> str:
    """Map a plugin to its model scene.

    A manifest may declare ``model_scene`` explicitly; otherwise the bundled
    Study / desktop-pet plugins are recognised by name and every other plugin
    defaults to ``background`` (never ``chat`` — a plugin must not be handed
    the conversation's model by accident).
    """
    raw = getattr(plugin, "raw", None)
    if isinstance(raw, dict):
        declared = str(raw.get("model_scene") or "").strip().lower()
        if declared in SCENES:
            return declared
    if not name:
        name = str(getattr(plugin, "name", "") or getattr(plugin, "id", "") or "")
    lowered = name.strip().lower()
    if lowered.startswith("study"):
        return SCENE_STUDY
    if "pet" in lowered or lowered.startswith("emotion"):
        return SCENE_DESKTOP_PET
    return SCENE_BACKGROUND


# -- scene memory (settings.jsonc) -----------------------------------------


def _read_memory() -> dict[str, list[str]]:
    from .settings_store import get_setting

    raw = get_setting(SCENE_MEMORY_NAMESPACE)
    memory: dict[str, list[str]] = {}
    if not isinstance(raw, dict):
        return memory
    for scene in SCENES:
        value = raw.get(scene)
        if isinstance(value, list):
            memory[scene] = [str(item).strip() for item in value if str(item or "").strip()]
        elif isinstance(value, str) and value.strip():
            # Tolerate an older/hand-written single-value shape.
            memory[scene] = [value.strip()]
    return memory


def scene_recent_models(scene: str) -> list[str]:
    """Return the scene's remembered model record ids, most recent first."""
    return list(_read_memory().get(scene, []))


def remember_scene_model(scene: str, model_id: str) -> None:
    """Record ``model_id`` as the most recent model used by ``scene``."""
    normalized = str(model_id or "").strip()
    if not normalized or scene not in SCENES:
        return
    from .settings_store import set_setting

    with _lock:
        memory = _read_memory()
        recent = [normalized, *(item for item in memory.get(scene, []) if item != normalized)]
        memory[scene] = recent[:MAX_SCENE_RECENT]
        set_setting(SCENE_MEMORY_NAMESPACE, memory)


# -- availability ----------------------------------------------------------


def resolve_provider_for_model(
    model: ModelConfig,
    *,
    work_root: str | None = None,
    provider_store: ProviderStore | None = None,
) -> ProviderConfig | None:
    """Look up a model's provider by ``provider_id`` then by ``name``.

    A model that names a provider must never be rebound to an unrelated
    provider; when the named provider is gone the model is simply unusable.
    """
    store = provider_store or ProviderStore()
    if model.provider_id:
        provider = store.get_sync(model.provider_id, work_root=work_root)
        if provider is not None:
            return provider
    if model.provider:
        provider = store.get_sync(model.provider, work_root=work_root)
        if provider is not None:
            return provider
    return None


def model_is_usable(model: ModelConfig | None, *, work_root: str | None = None) -> bool:
    """True when the model exists, its provider resolves, and the URL is valid."""
    if model is None:
        return False
    provider = resolve_provider_for_model(model, work_root=work_root)
    if provider is None:
        return False
    base_url = (provider.base_url or "").strip().rstrip("/")
    parsed = urlsplit(base_url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _usable_model_ids(*, work_root: str | None) -> set[str]:
    store = ModelStore()
    provider_store = ProviderStore()
    usable: set[str] = set()
    for model in store.list_sync(work_root=work_root):
        provider = resolve_provider_for_model(
            model, work_root=work_root, provider_store=provider_store
        )
        if provider is None:
            continue
        base_url = (provider.base_url or "").strip().rstrip("/")
        parsed = urlsplit(base_url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            usable.add(model.id)
    return usable


# -- notices ---------------------------------------------------------------


def record_model_notice(text: str) -> None:
    normalized = str(text or "").strip()
    if not normalized:
        return
    with _lock:
        if normalized in _pending_notices:
            return
        _pending_notices.append(normalized)
        if len(_pending_notices) > MAX_PENDING_NOTICES:
            del _pending_notices[: len(_pending_notices) - MAX_PENDING_NOTICES]


def drain_model_notices() -> list[dict[str, str]]:
    with _lock:
        drained = list(_pending_notices)
        _pending_notices.clear()
        return [{"kind": "model", "change": "fallback", "message": text} for text in drained]


def reset_model_notices() -> None:
    with _lock:
        _pending_notices.clear()


# -- resolution ------------------------------------------------------------


def resolve_scene_model(
    scene: str,
    *,
    work_root: str | None = None,
) -> SceneModelResolution:
    """Resolve the model a scene should use, or raise with a clear reason.

    Order: the scene's most recent remembered model, then the same scene's next
    remembered model that is still usable (reported as a replacement).  There is
    no cross-scene and no cross-provider fallback — if nothing in this scene is
    usable, the caller must surface :class:`ModelResolutionError`.
    """
    if scene not in SCENES:
        raise ModelResolutionError(f"unknown model scene: {scene}")
    recent = scene_recent_models(scene)
    if not recent:
        raise ModelResolutionError(NO_MODEL_MESSAGE)
    usable = _usable_model_ids(work_root=work_root)
    for index, model_id in enumerate(recent):
        if model_id not in usable:
            continue
        if index == 0:
            return SceneModelResolution(model_id=model_id)
        notice = (
            f"{scene_label(scene)}原来使用的模型「{recent[0]}」已不可用，"
            f"已改用同场景最近可用的模型「{model_id}」"
        )
        return SceneModelResolution(model_id=model_id, replaced_from=recent[0], notice=notice)
    raise ModelResolutionError(
        f"{scene_label(scene)}没有可用模型（原模型已删除或其供应商配置不可用），"
        f"{NO_MODEL_MESSAGE}"
    )


def seed_scenes_with_model(model_id: str) -> list[str]:
    """Seed every scene that has nothing remembered yet with ``model_id``.

    This is the "first run / empty config" rule: when there is no model to
    inherit from anywhere (the app was started with an explicit model, or the
    user just added their first provider), that model becomes each scene's
    starting point.  A scene that already remembers a model is never touched —
    that is what keeps the desktop pet's model out of the main conversation.
    """
    normalized = str(model_id or "").strip()
    if not normalized:
        return []
    from .settings_store import set_setting

    with _lock:
        memory = _read_memory()
        seeded: list[str] = []
        for scene in SCENES:
            if memory.get(scene):
                continue
            memory[scene] = [normalized]
            seeded.append(scene)
        if seeded:
            set_setting(SCENE_MEMORY_NAMESPACE, memory)
        return seeded


def remember_and_resolve(    scene: str,
    model_id: str,
    *,
    work_root: str | None = None,
) -> SceneModelResolution:
    """Record an explicitly chosen model for a scene, then return it.

    Used when the caller (user selection, session record) already names the
    model: the scene memory is updated so the *next* call in this scene
    inherits it, and the model is validated so an unavailable choice fails
    loudly instead of at request-construction time.
    """
    normalized = str(model_id or "").strip()
    if not normalized:
        raise ModelResolutionError(NO_MODEL_MESSAGE)
    store = ModelStore()
    model = store.get_sync(normalized, work_root=work_root)
    if model is None:
        raise ModelResolutionError(f"模型不存在：{normalized}")
    if not model_is_usable(model, work_root=work_root):
        raise ModelResolutionError(
            f"模型「{model.display_name or model.model_id or model.id}」不可用："
            "其供应商配置缺失或服务地址无效"
        )
    remember_scene_model(scene, model.id)
    return SceneModelResolution(model_id=model.id)


__all__ = [
    "MAX_SCENE_RECENT",
    "NO_MODEL_MESSAGE",
    "SCENES",
    "SCENE_BACKGROUND",
    "SCENE_CHAT",
    "SCENE_DESKTOP_PET",
    "SCENE_LABELS",
    "SCENE_MEMORY_NAMESPACE",
    "SCENE_STUDY",
    "ModelResolutionError",
    "SceneModelResolution",
    "drain_model_notices",
    "model_is_usable",
    "record_model_notice",
    "remember_and_resolve",
    "remember_scene_model",
    "reset_model_notices",
    "resolve_provider_for_model",
    "resolve_scene_model",
    "scene_for_plugin",
    "scene_label",
    "scene_recent_models",
    "seed_scenes_with_model",
]
