"""独立进程内核（subprocess / http）。

外部工具形态（用户已确认）：GPL/AGPL 或任何第三方搜索工具（baidu-serp-api、
SearXNG、openserp 等）一律**不内置、不 import**，LamTools 只把它当独立工具，
按固定契约经进程边界调用。仓库不携带其代码，组件由用户自行安装。

契约（JSON）：
    输入  ->  argv[1]（subprocess）或 POST body（http）：
              {"query": str, "limit": int, "domains": [str] | null}
    输出  <-  stdout（subprocess）或 response body（http）：
              {"results": [{"title": str, "url": str, "snippet": str}]}
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx

from .protocol import SearchResult

DEFAULT_CONFIG: dict = {
    "timeout": 30,
}


class ExternalSearchProvider:
    """通过进程边界调用外部搜索工具的内核。"""

    name: str
    transport: str  # "subprocess" | "http"

    def __init__(
        self,
        name: str,
        transport: str,
        command: list[str] | None = None,
        url: str | None = None,
        timeout: float = 30,
    ) -> None:
        assert transport in ("subprocess", "http"), f"unsupported transport: {transport}"
        self.name = name
        self.transport = transport
        self.command = command
        self.url = url
        self.timeout = timeout

    async def search(
        self,
        query: str,
        limit: int = 5,
        domains: list[str] | None = None,
    ) -> list[SearchResult]:
        payload = {"query": query, "limit": limit, "domains": domains}
        if self.transport == "subprocess":
            return await self._search_subprocess(payload)
        return await self._search_http(payload)

    async def _search_subprocess(self, payload: dict) -> list[SearchResult]:
        if not self.command:
            raise ExternalSearchError("subprocess 内核未配置 command")
        # 把 JSON 作为 argv 尾参传入（避免 Windows 跨进程 stdin 编码问题）
        proc = await asyncio.create_subprocess_exec(
            *(list(self.command) + [json.dumps(payload, ensure_ascii=False)]),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise ExternalSearchError(f"外部搜索工具超时（>{self.timeout}s）")
        if proc.returncode != 0:
            raise ExternalSearchError(
                f"外部搜索工具退出码 {proc.returncode}: {err.decode(errors='replace')[:200]}"
            )
        return self._parse_output(out.decode(errors="replace"))

    async def _search_http(self, payload: dict) -> list[SearchResult]:
        if not self.url:
            raise ExternalSearchError("http 内核未配置 url")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout)) as client:
                resp = await client.post(self.url, json=payload)
        except httpx.HTTPError as exc:
            raise ExternalSearchError(f"外部搜索服务请求失败: {exc}") from exc
        if resp.status_code != 200:
            raise ExternalSearchError(f"外部搜索服务 HTTP {resp.status_code}")
        return self._parse_output(resp.text)

    @staticmethod
    def _parse_output(raw: str) -> list[SearchResult]:
        try:
            data = json.loads(raw)
            results = data.get("results")
        except (json.JSONDecodeError, AttributeError) as exc:
            raise ExternalSearchError("外部搜索工具输出不是合法 JSON") from exc
        if not isinstance(results, list):
            raise ExternalSearchError("外部搜索工具输出缺少 results 数组")
        out: list[SearchResult] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            if not title or not url:
                continue
            out.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": str(item.get("snippet") or "").strip(),
                    "source": item.get("source") or "external",
                }
            )
        return out


class ExternalSearchError(Exception):
    """外部搜索工具（进程/HTTP）调用异常。"""


DEFAULT = ExternalSearchProvider