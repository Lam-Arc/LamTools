"""DuckDuckGo HTML 内核（海外备胎，inproc）。

原 web_tools.py 中 web_search 逻辑迁址于此，保持对外行为不变。
国内默认不可用（html.duckduckgo.com 被墙），仅在海外网络或显式 provider=ddg 时使用。
"""

from __future__ import annotations

import asyncio
import re
from html import unescape
from urllib.parse import urlsplit

import httpx

from .protocol import SearchResult
from .image_candidates import extract_image_candidates

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
        try:
            proxy_port = int(cfg.get("proxy_port") or 0)
        except (TypeError, ValueError):
            proxy_port = 0
        self.proxy = f"http://127.0.0.1:{proxy_port}" if 1 <= proxy_port <= 65535 else None
        self._client: httpx.AsyncClient | None = None

    async def _session(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                headers={"User-Agent": DEFAULT_UA},
                proxy=self.proxy,
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

    async def search_images(
        self,
        query: str,
        limit: int = 5,
        domains: list[str] | None = None,
    ) -> list[SearchResult]:
        """Find image candidates on accurate DuckDuckGo source results.

        DuckDuckGo's undocumented image JSON endpoint is not a stable public
        contract and currently rejects this client.  Use the working HTML web
        search to discover source pages, then extract source-backed image
        metadata without applying semantic filters; the model judges which
        candidate actually helps the task.
        """
        source_limit = min(max(limit * 2, 6), 12)
        sources = await self.search(query, limit=source_limit, domains=domains)
        client = await self._session()

        async def from_source(source: SearchResult) -> SearchResult | None:
            source_url = str(source.get("url") or "").strip()
            if urlsplit(source_url).scheme not in {"http", "https"}:
                return None
            try:
                response = await client.get(
                    source_url,
                    headers={"Range": "bytes=0-2097151"},
                    timeout=min(self.timeout, 8.0),
                )
            except Exception:
                return None
            content_type = response.headers.get("content-type", "").lower()
            if response.status_code >= 400 or "html" not in content_type:
                return None
            candidates = extract_image_candidates(
                response.text[:2_097_152],
                str(response.url),
                limit=1,
            )
            if not candidates:
                return None
            candidate = candidates[0]
            return {
                "title": candidate.get("alt") or source.get("title") or query,
                "url": str(response.url),
                "snippet": source.get("snippet") or "",
                "source": "ddg_images",
                "image_url": candidate["url"],
                "thumbnail_url": "",
            }

        discovered = await asyncio.gather(*(from_source(source) for source in sources))
        results: list[SearchResult] = []
        seen_images: set[str] = set()
        for item in discovered:
            if item is None:
                continue
            image_url = str(item.get("image_url") or "")
            if image_url in seen_images:
                continue
            seen_images.add(image_url)
            results.append(item)
            if len(results) >= limit:
                break
        return results


class DuckDuckGoSearchBlocked(Exception):
    """DuckDuckGo 反爬/异常响应。"""


DEFAULT = DuckDuckGoSearchProvider
