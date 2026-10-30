"""user:“继续，把 2 阶段都做完”+(目标与计划复用原目录、持久管理器和 Runner，固定插件命名空间及项目，不另建状态机)。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class DurableAccessError(RuntimeError):
    def __init__(self, code, message, *, may_have_changed=False):
        self.code, self.may_have_changed = code, may_have_changed
        super().__init__(message)


def _json(value, maximum=1048576):
    try:
        def validate(item):
            if type(item) is dict:
                if any(type(key) is not str for key in item):
                    raise ValueError
                for child in item.values():
                    validate(child)
            elif type(item) is list:
                for child in item:
                    validate(child)
            elif item is not None and type(item) not in {str, int, float, bool}:
                raise ValueError
        validate(value)
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(raw.encode("utf-8")) > maximum:
            raise ValueError
        return json.loads(raw)
    except Exception:
        raise DurableAccessError("durable/invalid-payload", "Use bounded finite JSON") from None


def _identifier(value):
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise DurableAccessError("durable/invalid-id", "Identifiers must be nonblank strings of at most 256 characters")
    return value.strip()


class PluginDurableAPI:
    def __init__(self, context, scope, kind):
        self._context, self._scope, self._kind = context, scope, kind
        self._root = str(Path(context.work_root).resolve())
        self._prefix = "plugin_" + hashlib.sha256(json.dumps([scope.owner, self._root, kind]).encode()).hexdigest()[:24] + "_"
        self._catalog = None

    async def _call(self, action, payload, *, missing=False):
        self._scope.acquire()
        try:
            catalog = self._context.resolved_operation_catalog()
            if self._catalog is None:
                self._catalog = catalog
            if catalog is not self._catalog:
                raise DurableAccessError("durable/host-changed", "Operation host changed")
            name = self._kind + "." + action
            if catalog is None or not catalog.has(name):
                raise DurableAccessError("durable/unavailable", "Required durable operation is unavailable")
            try:
                result = await catalog.execute(name, _json(payload), metadata={"source": "plugin-sdk", "plugin": self._scope.owner})
            except Exception:
                raise DurableAccessError("durable/operation-failed", "Durable host failed; inspect persistent state before retrying", may_have_changed=action not in {"get", "list"}) from None
            if result.status != "ok":
                if missing and result.payload.get("code") == "not-found":
                    return None
                raise DurableAccessError("durable/operation-failed", "Durable operation was rejected", may_have_changed=action not in {"get", "list"})
            return _json(result.payload, maximum=8388608)
        finally:
            self._scope.release()

    def _owns(self, row):
        return (isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"].startswith(self._prefix)
                and (self._kind == "goal" or row.get("work_root") == self._root))

    async def _get(self, identifier, *, missing=False):
        self._scope.check_open()
        identifier = _identifier(identifier)
        if not identifier.startswith(self._prefix):
            raise DurableAccessError("durable/not-found", "Record is unknown or unavailable")
        key = "goal" if self._kind == "goal" else "job"
        result = await self._call("get", {key + "_id": identifier}, missing=missing)
        if result is None:
            return None
        row = result.get(key)
        if not self._owns(row):
            raise DurableAccessError("durable/not-found", "Record is unknown or unavailable")
        return row

    async def get(self, identifier):
        return await self._get(identifier)

    async def list(self, *, thread_id=None, after_id="", limit=100):
        self._scope.check_open()
        if type(limit) is not int or not 1 <= limit <= 100:
            raise DurableAccessError("durable/invalid-limit", "limit must be within [1, 100]")
        if type(after_id) is not str:
            raise DurableAccessError("durable/invalid-id", "after_id must be a string")
        payload = {"work_root": self._root} if self._kind == "arrange" else {"thread_id": _identifier(thread_id)}
        if thread_id is not None:
            payload["thread_id"] = _identifier(thread_id)
        result = await self._call("list", payload)
        rows = result["goals" if self._kind == "goal" else "jobs"]
        if not isinstance(rows, list):
            raise DurableAccessError("durable/invalid-response", "Host returned no durable record list")
        owned = sorted((row for row in rows if self._owns(row) and row["id"] > after_id), key=lambda row: row["id"])
        more = len(owned) > limit
        items = owned[:limit]
        return {"items": items, "has_more": more, "next_after": items[-1]["id"] if more else None}

    async def create(self, *, thread_id, request_id, **fields):
        self._scope.check_open()
        thread_id, request_id = _identifier(thread_id), _identifier(request_id)
        identifier = self._prefix + hashlib.sha256(json.dumps([thread_id, request_id]).encode()).hexdigest()[:32]
        previous = await self._get(identifier, missing=True)
        if previous is not None:
            return previous
        allowed = ({"objective", "completion_criteria", "metadata"} if self._kind == "goal" else
                   {"operation", "payload", "trigger", "kind", "title", "session_strategy", "model_id", "max_runs"})
        if set(fields) - allowed:
            raise DurableAccessError("durable/invalid-payload", "Unsupported creation fields")
        payload = {**_json(fields), "thread_id": thread_id}
        key = "goal" if self._kind == "goal" else "job"
        payload[key + "_id"] = identifier
        if self._kind == "goal":
            if type(payload.get("metadata", {})) is not dict:
                raise DurableAccessError("durable/invalid-payload", "Goal metadata must be a JSON object")
            payload["metadata"] = {**payload.get("metadata", {}), "plugin_owner": self._scope.owner, "work_root": self._root}
        else:
            payload["work_root"] = self._root
            payload.setdefault("kind", "focus")
            payload.setdefault("session_strategy", "fixed")
        try:
            result = await self._call("create", payload)
        except DurableAccessError:
            # Deterministic request identity recovers a concurrent/uncertain create only when its own durable row exists.
            previous = await self._get(identifier, missing=True)
            if previous is not None:
                return previous
            raise
        row = result.get(key)
        if not self._owns(row):
            raise DurableAccessError("durable/invalid-response", "Host returned an unexpected durable identity", may_have_changed=True)
        return row

    async def update(self, identifier, **fields):
        current = await self.get(identifier)
        allowed = ({"objective", "completion_criteria", "status", "status_reason", "metadata"} if self._kind == "goal" else
                   {"title", "instruction", "trigger", "session_strategy", "model_id"})
        if set(fields) - allowed:
            raise DurableAccessError("durable/invalid-payload", "Unsupported update fields")
        key = "goal" if self._kind == "goal" else "job"
        payload = {**_json(fields), key + "_id": current["id"]}
        if self._kind == "goal" and "metadata" in payload:
            if type(payload["metadata"]) is not dict:
                raise DurableAccessError("durable/invalid-payload", "Goal metadata must be a JSON object")
            payload["metadata"].update(plugin_owner=self._scope.owner, work_root=self._root)
        row = (await self._call("update", payload)).get(key)
        if not self._owns(row) or row["id"] != current["id"]:
            raise DurableAccessError("durable/invalid-response", "Host returned an unexpected durable identity", may_have_changed=True)
        return row

    async def control(self, identifier, action):
        if self._kind != "arrange" or action not in {"pause", "resume", "cancel"}:
            raise DurableAccessError("durable/invalid-action", "Schedule controls are pause/resume/cancel")
        current = await self.get(identifier)
        row = (await self._call(action, {"job_id": current["id"]})).get("job")
        if not self._owns(row) or row["id"] != current["id"]:
            raise DurableAccessError("durable/invalid-response", "Host returned an unexpected durable identity", may_have_changed=True)
        return row


__all__ = ["PluginDurableAPI", "DurableAccessError"]
