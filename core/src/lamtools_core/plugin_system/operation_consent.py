"""user:“继续”+(复用宿主权限判定，一次确认只执行已捕获的操作，不能重放或替换参数)。"""
from __future__ import annotations

import copy
import json
import secrets
import time
from collections import OrderedDict
from typing import Any

from lamtools_core.app import OperationRequest, OperationResult


class OperationConsent:
    def __init__(self, host):
        self.host = host
        self.pending: OrderedDict[str, Any] = OrderedDict()
        self._grant = object()

    def _fingerprint(self, spec):
        manifest = self.host.get(spec.plugin)
        return (self.host._fingerprint(), manifest.version if manifest else None)

    def check(self, spec, request):
        from .backend_runtime import context_for

        context = context_for(spec.plugin, self.host)
        gate = getattr(context, "permission_service", None)
        if spec.permission == "hard_block" or gate is None:
            return OperationResult(name=spec.name, status="blocked", payload={"error": "操作被禁止或宿主权限服务不可用"})
        decision = gate.check(spec.name, request.payload)
        if decision.blocked:
            return OperationResult(name=spec.name, status="blocked", payload={"error": decision.reason})
        if decision.allowed:
            return None
        if request.metadata.get("_plugin_operation_grant") is self._grant:
            return None
        # Existing host authorization remains authoritative; the confirmation
        # is only needed when the shared gate has not already authorized it.
        now = time.monotonic()
        self.pending = OrderedDict((key, row) for key, row in self.pending.items() if row[0] > now)
        while len(self.pending) >= 128:
            self.pending.popitem(last=False)
        request_id = secrets.token_urlsafe(24)
        captured = OperationRequest(request.name, copy.deepcopy(request.payload), copy.deepcopy(request.metadata))
        self.pending[request_id] = (now + 120, spec, captured, self._fingerprint(spec))
        details = {key: captured.payload[key] for key in spec.approval_fields if key in captured.payload}
        impact = spec.impact
        if details:
            impact += " · " + json.dumps(details, ensure_ascii=False)[:1500]
        return OperationResult(name=spec.name, status="approval_required", payload={"approval": {
            "id": request_id, "plugin": spec.plugin, "operation": spec.name,
            "impact": impact, "expires_in": 120,
        }})

    async def respond(self, request):
        decision = request.payload.get("decision")
        if decision not in {"approve", "deny"}:
            return OperationResult(name=request.name, status="error", payload={"error": "无效的审批决定"})
        row = self.pending.pop(str(request.payload.get("id") or ""), None)
        if row is None:
            return OperationResult(name=request.name, status="error", payload={"error": "审批不存在或已处理"})
        expires, spec, captured, fingerprint = row
        if decision == "deny":
            return OperationResult(name=spec.name, status="cancelled", payload={"cancelled": True})
        manifest = self.host.get(spec.plugin)
        if expires < time.monotonic() or manifest is None or not manifest.enabled or fingerprint != self._fingerprint(spec):
            return OperationResult(name=spec.name, status="error", payload={"error": "审批已过期或插件已更改，请重新操作"})
        from .operation_bridge import build_handler

        metadata = {**captured.metadata, "_plugin_operation_grant": self._grant}
        return await build_handler(spec, self.host, self)(OperationRequest(spec.name, captured.payload, metadata))
