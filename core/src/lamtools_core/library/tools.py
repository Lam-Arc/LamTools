"""Agent 的 Library 统一文件工具。

user:“Sunday Agent 应能够直接使用 Library 的统一文件能力”“高风险文件操作
继续受 Sunday 的原有授权机制约束”+(模型能搜、能看属性、能按标签/评分筛、
能定位与展示、能收藏与入集合；移动/删除这类写操作不放进这个工具，继续走
Sunday 原有的授权通道)。
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from lamtools_core.tool import ToolCall, ToolResult, ToolSpec
from lamtools_core.tool.permission import AUTO_ALLOW

LIBRARY_FILES_TOOL_NAME = "library_files"

_OPERATION_EXECUTOR = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[Any]]

_DESCRIPTION = (
    "Library 的本机文件工作区：搜索整台电脑、查看文件属性、按标签/评分/收藏筛选、"
    "定位文件、用系统程序打开，以及把文件收藏/打分/打标签/加入集合。搜索复用本机 "
    "Everything 索引，不建立第二套索引；搜索结果只是“找到”，只有你显式执行 collect "
    "才会产生 Library 管理记录。这个工具不提供移动、重命名或删除文件的动作。"
    "Actions: search (关键词/类型/范围/大小/时间/排序，返回带路径与资产信息的结果)；"
    "stat (看一个文件的属性与资产信息)；list_assets (按标签、最低评分、收藏或集合筛选已管理资产)；"
    "collect (对若干路径设置收藏/评分/标签/备注，或用 collection_id/new_collection 加入集合)；"
    "collections (列出现有集合)；locate (在资源管理器中定位)；open (用系统默认程序打开)。"
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {
            "type": "string",
            "enum": ["search", "stat", "list_assets", "collect", "collections", "locate", "open"],
            "description": "要执行的动作。",
        },
        "query": {"type": "string", "description": "搜索词；支持 Everything 表达式，如 *.png、size:>1gb、dm:7days。"},
        "kinds": {
            "type": "array",
            "items": {"type": "string", "enum": ["image", "video", "audio", "document", "archive", "folder"]},
            "description": "按文件类型筛选。",
        },
        "scope": {"type": "string", "description": "只在这个目录（含子目录）里搜索；空 = 整机。"},
        "extensions": {"type": "array", "items": {"type": "string"}, "description": "扩展名白名单，如 png、jpg。"},
        "size_min": {"type": "integer", "description": "最小字节数。"},
        "size_max": {"type": "integer", "description": "最大字节数。"},
        "modified_within_days": {"type": "integer", "description": "最近 N 天修改过。"},
        "sort": {
            "type": "string",
            "enum": ["relevance", "name", "path", "size", "date_modified", "date_created", "recent", "rating"],
        },
        "descending": {"type": "boolean", "description": "是否倒序。"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 200, "description": "返回多少条，默认 30。"},
        "path": {"type": "string", "description": "stat/locate/open 的目标文件或目录。"},
        "paths": {"type": "array", "items": {"type": "string"}, "description": "collect 要处理的文件路径。"},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "collect 时设置标签；list_assets 时按这些标签筛选（全部匹配）。",
        },
        "rating": {"type": "integer", "minimum": 0, "maximum": 5, "description": "collect 时设置评分。"},
        "rating_min": {"type": "integer", "minimum": 0, "maximum": 5, "description": "list_assets 的最低评分。"},
        "favorite": {"type": "boolean", "description": "collect 时设置收藏；list_assets 时只看收藏。"},
        "favorite_only": {"type": "boolean", "description": "list_assets 只看收藏。"},
        "display_name": {"type": "string", "description": "collect 时设置 Library 显示名。"},
        "note": {"type": "string", "description": "collect 时写备注。"},
        "collection_id": {"type": "string", "description": "collect 时加入这个已有集合。"},
        "new_collection": {"type": "string", "description": "collect 时新建并加入这个集合。"},
    },
    "required": ["action"],
}


def library_tool_spec() -> ToolSpec:
    return ToolSpec(
        name=LIBRARY_FILES_TOOL_NAME,
        description=_DESCRIPTION,
        input_schema=_SCHEMA,
        permission=AUTO_ALLOW,
        metadata={"category": "library", "display": "资料库"},
    )


def _args(call: ToolCall) -> dict[str, Any]:
    return call.arguments if isinstance(call.arguments, dict) else {}


def _metadata(call: ToolCall) -> dict[str, Any]:
    metadata = getattr(call, "metadata", None)
    return dict(metadata) if isinstance(metadata, dict) else {}


def _failed(call: ToolCall, message: str) -> ToolResult:
    return ToolResult(call_id=call.id, name=call.name, status="failed", error=message, error_code="library_failed")


def _unwrap(result: Any) -> dict[str, Any]:
    payload = getattr(result, "payload", result)
    return payload if isinstance(payload, dict) else {}


def _format_size(size: int) -> str:
    value = float(max(0, int(size or 0)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _format_item(item: dict[str, Any]) -> str:
    asset = item.get("asset") if isinstance(item.get("asset"), dict) else {}
    parts = [
        str(item.get("path") or ""),
        _format_size(int(item.get("size") or 0)),
        str(item.get("modified_at") or ""),
    ]
    if asset:
        flags = []
        if asset.get("favorite"):
            flags.append("favorite")
        if int(asset.get("rating") or 0):
            flags.append(f"rating={asset.get('rating')}")
        tags = asset.get("tags") or []
        if tags:
            flags.append("tags=" + ",".join(str(tag) for tag in tags))
        if asset.get("missing"):
            flags.append("offline")
        if flags:
            parts.append(" ".join(flags))
    if item.get("missing"):
        parts.append("offline")
    return " | ".join(parts)


def make_library_files_handler(execute_operation: _OPERATION_EXECUTOR):
    async def handler(call: ToolCall) -> ToolResult:
        args = _args(call)
        action = str(args.get("action") or "").strip().lower()
        if action == "search":
            payload = {
                "query": str(args.get("query") or ""),
                "kinds": args.get("kinds") or [],
                "scope": str(args.get("scope") or ""),
                "extensions": args.get("extensions") or [],
                "size_min": args.get("size_min"),
                "size_max": args.get("size_max"),
                "modified_within_days": args.get("modified_within_days"),
                "sort": str(args.get("sort") or "relevance"),
                "descending": bool(args.get("descending")),
                "limit": int(args.get("limit") or 30),
            }
            data = _unwrap(await execute_operation("libraryfs.search", payload, _metadata(call)))
            error = data.get("error")
            if error:
                return _failed(call, str(error.get("message") if isinstance(error, dict) else error))
            items = data.get("items") or []
            lines = [_format_item(item) for item in items]
            total = data.get("total")
            header = f"{len(lines)} shown" + (f" / {total} total" if total is not None else "")
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok",
                content=header + ("\n" + "\n".join(lines) if lines else "\n(no results)"),
                metadata={"items": items[:60], "total": total},
            )
        if action == "stat":
            path = str(args.get("path") or "").strip()
            if not path:
                return _failed(call, "stat 需要 path")
            data = _unwrap(await execute_operation("libraryfs.stat", {"path": path}, _metadata(call)))
            item = data.get("item") or {}
            if not item:
                return _failed(call, str(data.get("error") or "文件不存在"))
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok",
                content=_format_item(item),
                metadata={"item": item},
            )
        if action in {"list_assets", "collections"} and action == "collections":
            data = _unwrap(await execute_operation("libraryfs.collection.list", {}, _metadata(call)))
            collections = data.get("collections") or []
            lines = [
                f"{item.get('collection_id')} | {item.get('name')} | {item.get('kind')} | {item.get('count', 0)} items"
                for item in collections
            ]
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok",
                content="\n".join(lines) or "(no collections)",
                metadata={"collections": collections},
            )
        if action == "list_assets":
            payload = {
                "query": str(args.get("query") or ""),
                "kinds": args.get("kinds") or [],
                "tags": args.get("tags") or [],
                "rating_min": int(args.get("rating_min") or 0),
                "favorite_only": bool(args.get("favorite_only") or args.get("favorite")),
                "sort": str(args.get("sort") or "recent"),
                "descending": bool(args.get("descending")),
                "limit": int(args.get("limit") or 30),
            }
            data = _unwrap(await execute_operation("libraryfs.asset.list", payload, _metadata(call)))
            assets = data.get("assets") or []
            lines = [
                f"{item.get('path')} | {_format_size(int(item.get('size') or 0))}"
                + (" | favorite" if item.get("favorite") else "")
                + (f" | rating={item.get('rating')}" if item.get("rating") else "")
                + (" | tags=" + ",".join(item.get("tags") or []) if item.get("tags") else "")
                + (" | offline" if item.get("missing") else "")
                for item in assets
            ]
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok",
                content=f"{len(lines)} of {data.get('total', len(lines))}\n" + "\n".join(lines),
                metadata={"assets": assets, "total": data.get("total")},
            )
        if action == "collect":
            paths = [str(item) for item in (args.get("paths") or []) if str(item).strip()]
            if not paths:
                return _failed(call, "collect 需要 paths")
            updated = 0
            for path in paths[:100]:
                payload: dict[str, Any] = {"path": path}
                if "favorite" in args:
                    payload["favorite"] = bool(args.get("favorite"))
                if "rating" in args:
                    payload["rating"] = args.get("rating")
                if "tags" in args:
                    payload["tags"] = args.get("tags") or []
                if "display_name" in args:
                    payload["display_name"] = args.get("display_name")
                if "note" in args:
                    payload["note"] = args.get("note")
                result = _unwrap(await execute_operation("libraryfs.asset.update", payload, _metadata(call)))
                if result.get("asset"):
                    updated += 1
            collection_message = ""
            collection_id = str(args.get("collection_id") or "").strip()
            if not collection_id and args.get("new_collection"):
                created = _unwrap(await execute_operation(
                    "libraryfs.collection.create",
                    {"name": args.get("new_collection"), "kind": "manual"},
                    _metadata(call),
                ))
                collection_id = str((created.get("collection") or {}).get("collection_id") or "")
            if collection_id:
                added = _unwrap(await execute_operation(
                    "libraryfs.collection.add",
                    {"collection_id": collection_id, "paths": paths},
                    _metadata(call),
                ))
                collection_message = f"; added {added.get('added', 0)} to collection"
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok",
                content=f"updated {updated} asset(s){collection_message}",
                metadata={"updated": updated, "collection_id": collection_id},
            )
        if action in {"locate", "open"}:
            path = str(args.get("path") or "").strip()
            if not path:
                return _failed(call, f"{action} 需要 path")
            operation = "libraryfs.reveal" if action == "locate" else "libraryfs.open"
            data = _unwrap(await execute_operation(operation, {"path": path}, _metadata(call)))
            if data.get("error"):
                return _failed(call, str(data.get("error")))
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok",
                content=("located " if action == "locate" else "opened ") + path,
            )
        return _failed(call, "action 必须是 search、stat、list_assets、collect、collections、locate 或 open")

    return handler


def library_tool_handlers(execute_operation: _OPERATION_EXECUTOR) -> dict[str, Callable[[ToolCall], Awaitable[ToolResult]]]:
    return {LIBRARY_FILES_TOOL_NAME: make_library_files_handler(execute_operation)}
