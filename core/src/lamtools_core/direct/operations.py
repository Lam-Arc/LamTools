"""直调 RPC：模型目录、发起、查询、取消、删除、保存为资产。

命名空间 ``direct.*``，与现有 ``config.*`` / ``artifact.*`` 并列，走同一套
OperationCatalog，因此桌面、手机与 CLI 拿到的是同一个后端能力。

user:“实现，先读现在的模型配置与管理的代码，尽可能复用，如果代码与需求不匹配，咋考虑新增功能”
+(界面只是入口；真正的调用与历史都在这里，换一个前端不用重写。)
"""
from __future__ import annotations

from typing import Any

from lamtools_core.app.operation_catalog import OperationCatalog, OperationRequest, OperationResult

from .service import DirectCallService


def build_direct_operation_catalog(
    service: DirectCallService,
    *,
    project_store: Any | None = None,
    artifact_store: Any | None = None,
) -> OperationCatalog:
    catalog = OperationCatalog()

    def _error(request: OperationRequest, message: str) -> OperationResult:
        return OperationResult(name=request.name, status="error", payload={"error": message})

    async def direct_catalog(request: OperationRequest) -> OperationResult:
        payload = request.payload if isinstance(request.payload, dict) else {}
        work_root: str | None = None
        project_id = str(payload.get("project_id") or "").strip()
        if project_id and project_store is not None:
            project = await project_store.get(project_id)
            if project is None:
                return _error(request, f"项目不存在：{project_id}")
            work_root = str(project.work_root)
        return OperationResult(name=request.name, payload=service.catalog(work_root=work_root))

    async def direct_run(request: OperationRequest) -> OperationResult:
        payload = request.payload if isinstance(request.payload, dict) else {}
        work_root: str | None = None
        project_id = str(payload.get("project_id") or "").strip()
        if project_id and project_store is not None:
            project = await project_store.get(project_id)
            if project is None:
                return _error(request, f"项目不存在：{project_id}")
            work_root = str(project.work_root)
        try:
            record = await service.submit(payload, work_root=work_root)
        except ValueError as exc:
            return _error(request, str(exc))
        return OperationResult(name=request.name, payload={"call": record.to_dict()})

    async def direct_get(request: OperationRequest) -> OperationResult:
        call_id = str(request.payload.get("call_id") or request.payload.get("id") or "").strip()
        record = service.get(call_id)
        if record is None:
            return _error(request, f"调用记录不存在：{call_id}")
        return OperationResult(name=request.name, payload={"call": record.to_dict()})

    async def direct_list(request: OperationRequest) -> OperationResult:
        payload = request.payload if isinstance(request.payload, dict) else {}
        try:
            limit = int(payload.get("limit") or 50)
        except (TypeError, ValueError):
            limit = 50
        try:
            offset = int(payload.get("offset") or 0)
        except (TypeError, ValueError):
            offset = 0
        calls = service.list_calls(
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
            output_type=str(payload.get("output_type") or ""),
            status=str(payload.get("status") or ""),
        )
        return OperationResult(name=request.name, payload={"calls": calls, "total": len(calls), "offset": offset})

    async def direct_retry(request: OperationRequest) -> OperationResult:
        payload = request.payload if isinstance(request.payload, dict) else {}
        call_id = str(payload.get("call_id") or payload.get("id") or "").strip()
        try:
            index = int(payload.get("index") or 0)
        except (TypeError, ValueError):
            index = 0
        work_root: str | None = None
        project_id = str(payload.get("project_id") or "").strip()
        if project_id and project_store is not None:
            project = await project_store.get(project_id)
            if project is None:
                return _error(request, f"项目不存在：{project_id}")
            work_root = str(project.work_root)
        try:
            record = await service.retry(call_id, index, work_root=work_root)
        except ValueError as exc:
            return _error(request, str(exc))
        return OperationResult(name=request.name, payload={"call": record.to_dict()})

    async def direct_import_imagegen(request: OperationRequest) -> OperationResult:
        try:
            result = service.import_imagegen()
        except ValueError as exc:
            return _error(request, str(exc))
        return OperationResult(name=request.name, payload=result)

    async def direct_cancel(request: OperationRequest) -> OperationResult:
        call_id = str(request.payload.get("call_id") or request.payload.get("id") or "").strip()
        cancelled = service.cancel(call_id)
        if not cancelled:
            return _error(request, "这次调用已经结束或不存在")
        return OperationResult(name=request.name, payload={"cancelled": True, "call_id": call_id})

    async def direct_delete(request: OperationRequest) -> OperationResult:
        call_id = str(request.payload.get("call_id") or request.payload.get("id") or "").strip()
        if not service.delete(call_id):
            return _error(request, f"调用记录不存在：{call_id}")
        return OperationResult(name=request.name, payload={"deleted": True, "call_id": call_id})

    async def direct_save(request: OperationRequest) -> OperationResult:
        payload = request.payload if isinstance(request.payload, dict) else {}
        call_id = str(payload.get("call_id") or payload.get("id") or "").strip()
        project_id = str(payload.get("project_id") or "").strip()
        if not project_id:
            return _error(request, "请选择一个项目再保存到资料库")
        if project_store is None or artifact_store is None:
            return _error(request, "资料库服务不可用")
        project = await project_store.get(project_id)
        if project is None:
            return _error(request, f"项目不存在：{project_id}")
        try:
            saved = await service.save_to_library(
                call_id,
                project_id=project.id,
                work_root=project.work_root,
                artifact_store=artifact_store,
            )
        except (ValueError, LookupError, OSError) as exc:
            return _error(request, str(exc))
        return OperationResult(name=request.name, payload=saved)

    for name, handler in {
        "direct.catalog": direct_catalog,
        "direct.run": direct_run,
        "direct.get": direct_get,
        "direct.list": direct_list,
        "direct.retry": direct_retry,
        "direct.import_imagegen": direct_import_imagegen,
        "direct.cancel": direct_cancel,
        "direct.delete": direct_delete,
        "direct.save": direct_save,
    }.items():
        catalog.register(name, handler)
    return catalog


__all__ = ["build_direct_operation_catalog"]
