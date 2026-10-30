"""user:“给我把 2 阶段做完，前端除外”+(插件反馈保存到现有会话元数据，消息版本和会话修订同时控制并发，不冒充DSH事件)。"""
import copy
import json

from lamtools_core.plugin_system.session_data import SessionDataError
from .persistence_host import RevisionConflictError


async def feedback_call(service, scope, root, kind, method, session_id, fields):
    for attempt in range(3):
        _, record, revision = await service._read(session_id, root)
        scope.check_open()
        metadata = copy.deepcopy(record.metadata)
        owners = metadata.setdefault("plugin_feedback", {})
        owner = owners.setdefault(scope.owner, {"messages": {}, "sessions": {}})
        rows = owner["messages" if kind == "message-feedback" else "sessions"]
        if method == "list":
            return {"items": [copy.deepcopy(item) for _, item in sorted(rows.items()) if not item.get("deleted")]}
        if kind == "message-feedback":
            message_id = fields["message_id"]
            if not any(message.id == message_id for message in await service._store.list_messages(session_id)):
                raise SessionDataError("session-data/target-not-found", "Message is unknown in this session")
            old = rows.get(message_id)
            version = old["version"] if old else None
            if fields["if_version"] != version:
                raise SessionDataError("session-data/conflict", "Message feedback version changed")
            if old is None and len(rows) >= 200:
                raise SessionDataError("session-data/feedback-limit", "At most 200 versioned message-feedback entries per plugin/session")
            result = {"message_id": message_id, "version": (version or 0) + 1, "deleted": method == "delete"}
            if method == "put":
                result.update({key: fields[key] for key in ("rating", "note", "category")})
            rows[message_id] = result
        else:
            key = fields["request_id"]
            if key in rows:
                return copy.deepcopy(rows[key])
            if len(rows) >= 100:
                raise SessionDataError("session-data/feedback-limit", "At most 100 session-feedback submissions per plugin/session")
            result = {"request_id": key, "text": fields["text"], "category": fields["category"], "recorded": True}
            rows[key] = result
        if len(json.dumps(owners, ensure_ascii=False, allow_nan=False).encode("utf8")) > 1048576:
            raise SessionDataError("session-data/feedback-limit", "Session feedback state exceeds 1 MiB")
        scope.check_open()
        try:
            saved = await service._store.patch(session_id, metadata=metadata, expected_revision=revision)
        except RevisionConflictError:
            continue
        if saved is None:
            raise SessionDataError("session-data/not-found", "Session became unavailable")
        return copy.deepcopy(result)
    raise SessionDataError("session-data/conflict", "Session kept changing; read feedback before retrying")
