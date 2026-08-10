"""Search kernel protocol: fixed input/output contract across all providers.

Kernels are swappable — any implementation (built-in or external process)
that satisfies SearchProvider can be plugged in without changing callers.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, TypedDict, runtime_checkable

# transport 形态：
# - inproc:     同进程内自研轻量内核（无许可证风险）
# - subprocess: 调用独立 CLI 程序（外部工具，用户自行安装）
# - http:       调用自托管 SERP 服务（SearXNG/openserp 等）
Transport = Literal["inproc", "subprocess", "http"]


class SearchResult(TypedDict):
    """统一的单条搜索结果（所有内核输出此形状）。"""

    title: str
    url: str
    snippet: str
    source: str  # 固定为内核名（provider.name）


@runtime_checkable
class SearchProvider(Protocol):
    """搜索内核接口。输入参数与输出格式固定，内核可替换。"""

    name: str
    transport: Transport

    async def search(
        self,
        query: str,
        limit: int = 5,
        domains: list[str] | None = None,
    ) -> list[SearchResult]: ...