"""DuckDuckGo HTML 内核（海外备胎，inproc）。

原 web_tools.py 中 web_search 逻辑迁址于此，保持对外行为不变。
国内默认不可用（html.duckduckgo.com 被墙），仅在海外网络或显式 provider=ddg 时使用。
"""

from __future__ import annotations

import re
from html import unescape

import httpx

from .protocol import SearchResult

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_CONFIG: dict = {
    "endpoint": "https://html.duckduckgo.com/html/",
    "timeout": 30,
}


class DuckDuckGoSearchProvider:
    """DuckDuckGo HTML 内核（海外备胎）。"""

    name = "ddg"
    transport = "inproc"

    def __init__(self, config: dict | None = None) -> None:
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        self.endpoint = str(cfg["endpoint"])
        self.timeout = float(cfg.get("timeout") or 30)
        self._client: httpx.AsyncClient | None = None

    async def _session(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                headers={"User-Agent": DEFAULT_UA},
            )
        return self._client

    async def search(
        self,
        query: str,
        limit: int = 5,
        domains: list[str] | None = None,
    ) -> list[SearchResult]:
        client = await self._session()
        search_query = query
        if domains:
            search_query = f"{query} " + " ".join(f"site:{d}" for d in domains)

        resp = await client.post(self.endpoint, data={"q": search_query})
        if resp.status_code != 200:
            raise DuckDuckGoSearchBlocked(f"DuckDuckGo 返回 HTTP {resp.status_code}")

        text = resp.text
        link_pattern = re.compile(r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL)
        snippet_pattern = re.compile(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
        links = link_pattern.findall(text)
        snippets = snippet_pattern.findall(text)

        def _clean(s: str) -> str:
            s = re.sub(r"<[^>]+>", "", s).strip()
            return (
                s.replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&quot;", '"')
                .replace("&#39;", "'")
            )

        results: list[SearchResult] = []
        for i, (url, title) in enumerate(links[:limit]):
            title_clean = _clean(title)
            snippet = _clean(snippets[i]) if i < len(snippets) else ""
            if not title_clean or not url:
                continue
            results.append(
                {
                    "title": unescape(title_clean),
                    "url": url,
                    "snippet": unescape(snippet),
                    "source": "ddg",
                }
            )
        return results


class DuckDuckGoSearchBlocked(Exception):
    """DuckDuckGo 反爬/异常响应。"""


DEFAULT = DuckDuckGoSearchProvider