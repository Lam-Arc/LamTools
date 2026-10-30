"""user:“给我把 2 阶段做完，前端除外”+(会话候选和摘录直接读取原可见存储，显式返回截断和未发布状态)。"""
import hashlib
from pathlib import Path


async def reference_call(service, scope, root, method, session_id, fields):
    if method == "candidates":
        rows, more = await service._store.scan_readonly(after_id="", scan_limit=1000)
        scope.check_open()
        items = []
        for _, record in rows:
            if record is None or record.id == session_id:
                continue
            project = record.metadata.get("work_root")
            if not project or Path(project).resolve() != Path(root).resolve():
                continue
            if fields["query"].casefold() not in record.title.casefold():
                continue
            items.append({"session_id": record.id, "title": record.title[:1024]})
        return {"items": items[:fields["limit"]], "truncated": more or len(items) > fields["limit"]}
    prepared, remaining = [], fields["max_chars"]
    for ref in fields["references"]:
        _, record, revision = await service._read(ref, root)
        messages = await service._store.list_messages(ref)
        scope.check_open()
        fragments, size = [], 0
        total = sum(len(message.content) + len(message.role) + 3 for message in messages)
        # Bound construction before joining; large saved messages are not duplicated in full.
        for message in messages:
            if size >= remaining:
                break
            fragment = (f"{message.role}: " + message.content[:remaining - size])[:remaining - size]
            fragments.append(fragment)
            size += len(fragment) + 1
        text = "\n".join(fragments)[:remaining]
        prepared.append({"session_id": ref, "title": record.title[:1024], "text": text,
                         "metadata_revision_observed": revision, "truncated": total > len(text),
                         "sha256": hashlib.sha256(text.encode("utf8")).hexdigest()})
        remaining -= len(text)
    return {"references": prepared, "published": False, "max_chars": fields["max_chars"]}
