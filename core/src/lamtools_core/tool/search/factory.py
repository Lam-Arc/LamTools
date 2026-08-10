"""Search provider factory: 配置驱动内核选择 + 兼容 make_web_search_handler 的组装器。

配置来源（优先级从高到低）:
1. 显式传入的 provider 名（调用侧 web_search 工具参数 provider=...）
2. websearch.jsonc 配置（可选，位于 .lam/core/config/ 或 work_root）
3. 内置默认：baidu（inproc 自研）

外部内核（subprocess/http）在配置中显式声明 command/url，不内置任何第三方代码。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Awaitable, Callable

from lamtools_core.tool import ToolArtifact, ToolCall, ToolResult, ToolResultStatus
from lamtools_core.tool.search.protocol import SearchProvider, SearchResult

DEFAULT_PROVIDER = "baidu"

_MAX_RESULT_COUNT = 20
_MAX_CONTENT_LEN = 8000


def _strip_jsonc_comments(text: str) -> str:
    import re

    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.DOTALL)


def _load_config(work_root: str | None = None) -> dict:
    """读取 websearch.jsonc（可选）。文件缺失返回空 dict。"""
    candidates: list[Path] = []
    if work_root:
        candidates.append(Path(work_root).resolve() / ".lam" / "core" / "config" / "websearch.jsonc")
    candidates.append(Path(".lam/core/config/websearch.jsonc"))
    env_path = os.environ.get("WEBSEARCH_CONFIG")
    if env_path:
        candidates.insert(0, Path(env_path))
    for path in candidates:
        try:
            raw = Path(path).read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            continue
        try:
            data = json.loads(_strip_jsonc_comments(raw))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _default_config(work_root: str | None = None) -> dict:
    cfg = _load_config(work_root)
    provider = str(cfg.get("provider") or os.environ.get("WEBSEARCH_PROVIDER") or DEFAULT_PROVIDER)
    # 顶层通用字段（limit/timeout 等）作为默认，provider 内联配置可覆盖
    merged: dict = {
        "provider": provider,
        "limit": cfg.get("limit", 5),
        "timeout": cfg.get("timeout", 15),
        "command": cfg.get("command"),
        "url": cfg.get("url"),
        "transport": cfg.get("transport"),
    }
    provider_cfg = cfg.get(provider)
    if isinstance(provider_cfg, dict):
        merged.update(provider_cfg)
    return merged


def list_providers() -> list[str]:
    """内置可用的内核名。"""
    return ["baidu", "bing", "ddg"]


def get_provider(name: str | None = None, config: dict | None = None) -> SearchProvider:
    """按名字构造内核；配置可覆盖（如 websearch.jsonc 中的 baidu={...}）。"""
    from .baidu import BaiduSearchProvider
    from .bing import BingSearchProvider
    from .duckduckgo import DuckDuckGoSearchProvider
    from .external import ExternalSearchProvider

    provider = (name or DEFAULT_PROVIDER).strip().lower()
    cfg = dict(config or {})

    if provider == "baidu":
        return BaiduSearchProvider(cfg.get("baidu") or cfg)
    if provider == "bing":
        return BingSearchProvider(cfg.get("bing") or cfg)
    if provider == "ddg":
        return DuckDuckGoSearchProvider(cfg.get("ddg") or cfg)
    # 外部内核：通过配置声明 transport / command / url
    if provider in ("subprocess", "http"):
        return ExternalSearchProvider(
            name=provider,
            transport=provider,
            command=cfg.get("command"),
            url=cfg.get("url"),
            timeout=float(cfg.get("timeout") or 30),
        )
    # 显式外部 provider 名（配置里写 provider: "my-serp" 且带 transport）
    if cfg.get("transport") in ("subprocess", "http"):
        return ExternalSearchProvider(
            name=provider,
            transport=str(cfg["transport"]),
            command=cfg.get("command"),
            url=cfg.get("url"),
            timeout=float(cfg.get("timeout") or 30),
        )
    raise ValueError(f"未知搜索内核: {provider}（可选: baidu/bing/ddg 或配置 external transport）")


def build_web_search_handler(work_root: str) -> Callable[[ToolCall], Awaitable[ToolResult]]:
    """构造 web_search 工具 handler（与 default_toolbox 现有接线形式一致）。"""
    cfg = _default_config(work_root)
    default_provider = get_provider(cfg.get("provider"), cfg)

    async def web_search(call: ToolCall) -> ToolResult:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        query = args.get("query", "")
        if not query or not isinstance(query, str) or not query.strip():
            return ToolResult(call_id=call.id, name=call.name, status="failed", error="Missing 'query' argument")
        try:
            cfg_limit = int(cfg.get("limit") or 5)
        except (TypeError, ValueError):
            cfg_limit = 5
        try:
            limit = max(1, min(int(args.get("limit", cfg_limit) or cfg_limit), _MAX_RESULT_COUNT))
        except (TypeError, ValueError):
            limit = cfg_limit
        raw_domains = args.get("domains")
        domains = (
            [str(item).strip() for item in raw_domains if str(item).strip()]
            if isinstance(raw_domains, list)
            else []
        )
        provider_name = str(args.get("provider") or "").strip().lower() or None
        provider = default_provider
        if provider_name:
            try:
                provider = get_provider(provider_name, cfg)
            except ValueError:
                return ToolResult(
                    call_id=call.id, name=call.name, status="failed",
                    error=f"未知搜索内核: {provider_name}（可选: baidu/bing/ddg 或 subprocess/http）",
                )

        try:
            results = await provider.search(query, limit=limit, domains=domains)
        except Exception as exc:
            return ToolResult(
                call_id=call.id, name=call.name, status="failed",
                error=f"web_search {provider.name} error: {exc}",
                metadata={"query": query, "provider": provider.name, "result_count": 0, "results": []},
            )

        if not results:
            return ToolResult(
                call_id=call.id, name=call.name, status="ok",
                content=f"[web_search] No results found for query: {query}",
                metadata={"query": query, "domains": domains, "provider": provider.name,
                          "result_count": 0, "results": []},
            )

        lines = [
            f"{i+1}. {r['title']}\n   URL: {r['url']}\n   {r['snippet']}" for i, r in enumerate(results)
        ]
        content = f"[web_search results for '{query}']\n\n" + "\n\n".join(lines)
        if len(content) > _MAX_CONTENT_LEN:
            content = content[:_MAX_CONTENT_LEN] + "\n[... truncated]"
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="ok",
            content=content,
            metadata={
                "query": query,
                "domains": domains,
                "provider": provider.name,
                "result_count": len(results),
                "results": results,
            },
            artifacts=[
                ToolArtifact(
                    kind="web_search_result",
                    uri=provider.name,
                    content=[dict(r) for r in results],
                    metadata={"query": query, "domains": domains,
                              "result_count": len(results)},
                )
            ],
        )

    return web_search