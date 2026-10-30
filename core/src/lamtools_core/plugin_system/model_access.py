"""user:“宿主能力补齐和接口完善与文档更新”+(模型目录和场景查询复用原存储与选择权威，禁止跨场景猜测与重名路由误选)。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .services import RegistrationScope


class ModelAccessError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ModelDescriptor:
    id: str
    model_id: str
    display_name: str
    provider_id: str
    provider: str
    capability: str
    context_window: int
    max_output_tokens: int

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ModelSelection:
    scene: str
    model: ModelDescriptor
    replaced_from: str = ""
    notice: str = ""

    def to_dict(self):
        return asdict(self)


class PluginModelAPI:
    """Read-only metadata, pinned to the requester's epoch and workspace."""

    def __init__(self, store_factory, scope: RegistrationScope, work_root):
        self._store_factory = store_factory
        self._scope = scope
        self._work_root = str(Path(work_root).resolve())

    def _records(self):
        self._scope.check_open()
        try:
            return list(self._store_factory().list_sync(work_root=self._work_root))
        except Exception as error:
            # user:“接口完善”+(发现失败不能伪装成空目录，也不把底层异常中的配置数据暴露给调用方)。
            raise ModelAccessError("model/store-error", "Unable to read configured model records") from error

    @staticmethod
    def _descriptor(record):
        try:
            result = ModelDescriptor(id=str(record.id or ""), model_id=str(record.model_id or ""),
                display_name=str(record.display_name or record.model_id or ""),
                provider_id=str(record.provider_id or ""), provider=str(record.provider or ""),
                capability=str(record.resolved_capability), context_window=int(record.context_window or 0),
                max_output_tokens=int(record.max_output_tokens or 0))
            if not result.id or not result.model_id or min(result.context_window, result.max_output_tokens) < 0:
                raise ValueError("invalid record")
            return result
        except Exception as error:
            raise ModelAccessError("model/invalid-record", "Invalid configured model metadata") from error

    def list(self) -> list[ModelDescriptor]:
        return [self._descriptor(record) for record in self._records()]

    @staticmethod
    def _find(records, ref):
        if not isinstance(ref, str) or not ref.strip():
            raise ModelAccessError("model/invalid-ref", "Model reference must be a non-empty string")
        ref = ref.strip()
        exact = [record for record in records if record.id == ref]
        if len(exact) == 1:
            return exact[0]
        aliases = exact or [record for record in records
                            if record.model_id == ref or record.display_name.casefold() == ref.casefold()]
        if len(aliases) == 1:
            return aliases[0]
        if aliases:
            raise ModelAccessError("model/ambiguous", "Model reference matches several records; use an exact record ID")
        raise ModelAccessError("model/not-found", "Model reference is not present in the configured catalog")

    def resolve(self, ref: str) -> ModelDescriptor:
        return self._descriptor(self._find(self._records(), ref))

    def select(self, scene: str, *, ref: str | None = None) -> ModelSelection:
        self._scope.check_open()
        from lamtools_core.config import model_selection
        if not isinstance(scene, str) or scene not in model_selection.SCENES:
            raise ModelAccessError("model/invalid-scene", "Scene must be chat, study or background")
        records = self._records()
        replaced_from, notice = "", ""
        if ref is None:
            try:
                resolution = model_selection.resolve_scene_model(scene, work_root=self._work_root)
            except model_selection.ModelResolutionError as error:
                raise ModelAccessError("model/no-selection", "No usable remembered model in this scene") from error
            except Exception as error:
                raise ModelAccessError("model/store-error", "Unable to resolve the scene model") from error
            # Re-read metadata after the shared resolver: a concurrently edited
            # catalog must not bind the choice to a different alias or route.
            records = self._records()
            record = next((record for record in records if record.id == resolution.model_id), None)
            if record is None:
                raise ModelAccessError("model/not-found", "Selected model record is no longer in the catalog")
            replaced_from, notice = resolution.replaced_from, resolution.notice
        else:
            record = self._find(records, ref)
        try:
            usable = model_selection.model_is_usable(record, work_root=self._work_root)
        except Exception as error:
            raise ModelAccessError("model/store-error", "Unable to read model provider configuration") from error
        if not usable:
            raise ModelAccessError("model/unavailable", "Selected model provider is missing or has an invalid endpoint")
        return ModelSelection(scene=scene, model=self._descriptor(record), replaced_from=replaced_from, notice=notice)


__all__ = ["ModelAccessError", "ModelDescriptor", "ModelSelection", "PluginModelAPI"]
