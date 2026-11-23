"""把工作区检索结果整形给界面。

user:“给现有 search_files 能力一个可见入口…检索带扫描预算与进度反馈，
结果过多要分页/截断并明示；不要自研全盘索引”+
(匹配与预算全部由 `workspace_files.WorkspaceReadOnlyTools` 决定，这里只做两件事：
把工具输出拆成「命中条目」与「给人看的说明」，以及把「扫了多少 / 有没有扫完 /
有没有截断」显式交出去——界面必须能说清这份结果全不全。)

为什么单独成模块：这是「一次检索 → 一份可展示结果」的完整判定，界面、
将来的命令面板与插件页都要复用它；放在路由里既测不到，也会长出第二份。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from lamtools_core.tool import ToolCall
from lamtools_core.tool.workspace_files import WorkspaceReadOnlyTools

#: 界面一次最多要多少条；再大就把压力交给「缩小条件」而不是翻页。
DEFAULT_UI_SEARCH_LIMIT = 50
MAX_UI_SEARCH_LIMIT = 200

#: 工具把「扫描预算用尽」「还有更多命中」写成以 [...] 开头的说明行。
_NOTE_PREFIX = "[..."
#: 内容命中：`路径:行号: 原文`。路径可能含冒号（Windows 盘符），所以行号从右找。
_CONTENT_HIT = re.compile(r"^(?P<path>.*?):(?P<line>\d+): (?P<text>.*)$")

CONTENT_MODE = "content"
NAME_MODE = "name"


def _shape_hit(line: str, content_mode: bool) -> dict[str, Any] | None:
    if content_mode:
        found = _CONTENT_HIT.match(line)
        if found is None:
            return None
        return {
            "path": found.group("path"),
            "line": int(found.group("line")),
            "text": found.group("text"),
        }
    return {"path": line, "line": None, "text": ""}


async def search_workspace(
    *,
    work_root: str | Path,
    query: str,
    mode: str = NAME_MODE,
    path: str = ".",
    limit: int | None = DEFAULT_UI_SEARCH_LIMIT,
    max_scan_entries: int | None = None,
    time_budget_seconds: float | None = None,
) -> dict[str, Any]:
    """按文件名或内容检索工作区；返回可直接渲染的命中与完整性说明。

    返回值里的三个布尔量是这一层的重点：
    - ``scan_exhausted``：扫描预算用尽，工作区**没有被完整搜过**；
    - ``truncated``：命中数达到上限，还有结果没返回；
    - （命中为空且未耗尽）才是真的「没有」。
    """
    root = Path(work_root)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("项目目录不存在")

    keyword = (query or "").strip()
    # 注意不能写 `limit or DEFAULT`：0 是「只要 1 条」的合法请求，不是「没给」。
    requested = DEFAULT_UI_SEARCH_LIMIT if limit is None else int(limit)
    capped = max(1, min(requested, MAX_UI_SEARCH_LIMIT))
    if not keyword:
        return {
            "matches": [],
            "match_count": 0,
            "scanned_entries": 0,
            "scan_exhausted": False,
            "truncated": False,
            "mode": NAME_MODE,
        }

    content_mode = (mode or NAME_MODE).strip().lower() == CONTENT_MODE
    # 界面可以比后台默认更保守：一次交互检索不该占住 20 秒。
    tool_options: dict[str, Any] = {"max_search_results": capped}
    if max_scan_entries is not None:
        tool_options["max_search_scan_entries"] = int(max_scan_entries)
    if time_budget_seconds is not None:
        tool_options["search_time_budget_seconds"] = float(time_budget_seconds)
    tools = WorkspaceReadOnlyTools(root, **tool_options)
    call = ToolCall(
        id="ui-file-search",
        name="search_content" if content_mode else "search_files",
        arguments={"pattern": keyword, "path": path},
    )
    result = await (tools.search_content(call) if content_mode else tools.search_files(call))
    if result.status != "ok":
        raise ValueError(result.error or "检索失败")

    metadata = dict(result.metadata or {})
    matches: list[dict[str, Any]] = []
    for line in (result.content or "").splitlines():
        if not line or line.startswith(_NOTE_PREFIX):
            continue
        hit = _shape_hit(line, content_mode)
        if hit is not None:
            matches.append(hit)

    match_count = int(metadata.get("match_count", len(matches)) or 0)
    return {
        "matches": matches,
        "match_count": match_count,
        "scanned_entries": int(metadata.get("scanned_entries", 0) or 0),
        "scan_exhausted": bool(metadata.get("scan_exhausted", False)),
        # 命中数触到上限就意味着「还有没回来的」；预算耗尽另有 scan_exhausted 表达。
        "truncated": match_count >= capped,
        "mode": CONTENT_MODE if content_mode else NAME_MODE,
    }


__all__ = [
    "CONTENT_MODE",
    "DEFAULT_UI_SEARCH_LIMIT",
    "MAX_UI_SEARCH_LIMIT",
    "NAME_MODE",
    "search_workspace",
]
