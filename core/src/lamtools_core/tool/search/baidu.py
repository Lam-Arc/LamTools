"""百度搜索内核（自研，inproc）。

走百度官方迁移接口 ``tn=json``（公开 HTTP 协议，无 API key）：
    GET https://www.baidu.com/s?wd=<kw>&rn=10&pn=<p>&tn=json

反爬实战结论（2026-08-10 国内网络实测）：
- 首次无 Cookie 直连会 302 跳到 wappass 验证码页；
- 先 GET https://www.baidu.com/ 拿 BAIDUID 等 Cookie，再带 Referer 请求即返回 JSON；
- 更稳也可附带 rsv_pq / rsv_t / oq 浏览器参数（可选）。
- 响应含反爬状态位：Location 含 wappass -> 验证码；JSON antiFlag==1 -> 拒绝。

结果形状：feed.entry[]，每条含 title / url / abs(摘要) / time(时间戳) / source。
"""

from __future__ import annotations

import asyncio
import json
import random
import string
import time
from html import unescape

import httpx

from .protocol import SearchResult

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_CONFIG: dict = {
    "endpoint": "https://www.baidu.com/s",
    "results_per_page": 10,
    "warmup_url": "https://www.baidu.com/",
    "timeout": 15,
    "use_browser_params": True,
}


def _rand_hex(n: int) -> str:
    return "".join(random.choice(string.hexdigits.lower()) for _ in range(n))


class BaiduSearchProvider:
    """百度 tn=json 内核。"""

    name = "baidu"
    transport = "inproc"

    def __init__(self, config: dict | None = None) -> None:
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        self.endpoint = str(cfg["endpoint"])
        self.results_per_page = int(cfg.get("results_per_page") or 10)
        self.warmup_url = str(cfg.get("warmup_url") or "https://www.baidu.com/")
        self.timeout = float(cfg.get("timeout") or 15)
        self.use_browser_params = bool(cfg.get("use_browser_params", True))
        self._client: httpx.AsyncClient | None = None
        self._warmed = False

    async def _session(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=False,
                headers={
                    "User-Agent": DEFAULT_UA,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                },
            )
            # warmup：先拿 Cookies（BAIDUID 等），否则 tn=json 会 302 到验证码
            try:
                await self._client.get(self.warmup_url)
            except httpx.HTTPError:
                pass  # warmup 失败不致命，后续请求仍会尝试
            self._warmed = True
        return self._client

    async def search(
        self,
        query: str,
        limit: int = 5,
        domains: list[str] | None = None,
    ) -> list[SearchResult]:
        # 偶发反爬（wappass/antiFlag）自动重试 2 次，间隔短暂退避
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                return await self._search_once(query, limit, domains)
            except (BaiduSearchBlocked, httpx.HTTPError) as exc:
                last_exc = exc
                if attempt < 2:
                    await asyncio.sleep(1.0 + attempt)
        raise last_exc  # type: ignore[misc]

    async def _search_once(
        self,
        query: str,
        limit: int = 5,
        domains: list[str] | None = None,
    ) -> list[SearchResult]:
        client = await self._session()
        search_query = query
        if domains:
            search_query = f"{query} " + " ".join(f"site:{d}" for d in domains)

        params: dict[str, object] = {
            "wd": search_query,
            "rn": self.results_per_page,
            "pn": 0,
            "tn": "json",
        }
        if self.use_browser_params:
            params.update(
                {
                    "rsv_pq": _rand_hex(16),
                    "rsv_t": str(int(time.time() * 1000)),
                    "oq": query,
                }
            )

        resp = await client.get(self.endpoint, params=params)
        # 验证码 / 反爬检测
        if resp.status_code in (300, 301, 302, 303, 307, 308):
            loc = resp.headers.get("location", "")
            if "wappass" in loc or "captcha" in loc:
                raise BaiduSearchBlocked("百度安全验证（wappass captcha），请稍后重试或更换内核")
            raise BaiduSearchBlocked(f"百度重定向（HTTP {resp.status_code}），可能被反爬拦截")
        if resp.status_code != 200:
            raise BaiduSearchBlocked(f"百度返回 HTTP {resp.status_code}")

        data = json.loads(resp.text)
        if data.get("antiFlag") in (1, "1"):
            raise BaiduSearchBlocked("百度拒绝爬虫访问（antiFlag==1）")

        entries = (data.get("feed") or {}).get("entry") or []
        results: list[SearchResult] = []
        for e in entries[:limit]:
            title = unescape(str(e.get("title") or "")).strip()
            url = str(e.get("url") or "").strip()
            if not title or not url:
                continue
            results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": unescape(str(e.get("abs") or "")).strip(),
                    "source": "baidu",
                }
            )
        return results


class BaiduSearchBlocked(Exception):
    """百度反爬/验证码/异常响应。"""


DEFAULT = BaiduSearchProvider