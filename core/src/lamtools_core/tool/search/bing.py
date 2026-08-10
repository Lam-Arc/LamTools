"""Bing 中文版搜索内核（自研，inproc）。

GET https://cn.bing.com/search?q=<kw>&mkt=zh-CN
解析 `#b_results li.b_algo`：
- 标题 h2>a；
- 摘要 p（剔除 algoSlug_icon 装饰图标）；
- 链接若是 `https://www.bing.com/ck/a?...&u=a1<base64url>` 则 base64 解码还原真实 URL。
实测（2026-08-10）：cn.bing.com 国内可达，返回 10 条 b_algo，无需 key。
"""

from __future__ import annotations

import base64
import re
from html import unescape
from urllib.parse import parse_qs, urlparse

import httpx

from .protocol import SearchResult

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_CONFIG: dict = {
    "endpoint": "https://cn.bing.com/search",
    "market": "zh-CN",
    "timeout": 15,
}


def _decode_bing_redirect(href: str) -> str:
    """把 Bing /ck/a 跳转链接还原为真实 URL。"""
    if not href.startswith("https://www.bing.com/ck/a"):
        return href
    qs = parse_qs(urlparse(href).query)
    u_values = qs.get("u")
    if not u_values:
        return href
    u_val = u_values[0]
    if not u_val.startswith("a1"):
        return href
    encoded = u_val[2:]
    encoded += "=" * (-len(encoded) % 4)  # base64url padding
    try:
        return base64.urlsafe_b64decode(encoded).decode("utf-8", errors="replace")
    except Exception:
        return href


class BingSearchProvider:
    """Bing 中文版 HTML 内核。"""

    name = "bing"
    transport = "inproc"

    def __init__(self, config: dict | None = None) -> None:
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        self.endpoint = str(cfg["endpoint"])
        self.market = str(cfg.get("market") or "zh-CN")
        self.timeout = float(cfg.get("timeout") or 15)
        self._client: httpx.AsyncClient | None = None

    async def _session(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                headers={
                    "User-Agent": DEFAULT_UA,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                },
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

        resp = await client.get(
            self.endpoint,
            params={"q": search_query, "mkt": self.market, "setlang": "zh-hans"},
        )
        if resp.status_code != 200:
            raise BingSearchBlocked(f"Bing 返回 HTTP {resp.status_code}")
        # 疑似验证码/挑战页（页面结构消失）快速判别
        if "b_results" not in resp.text and "b_algo" not in resp.text:
            if any(m in resp.text.lower() for m in ("captcha", "challenge", "verify")):
                raise BingSearchBlocked("Bing 触发验证码/挑战")
            raise BingSearchBlocked("Bing 响应中未找到结果结构（可能被反爬）")

        text = resp.text
        results: list[SearchResult] = []
        # 逐条提取 h2>a（标题+URL 在 b_algo 内唯一、结构稳定）
        items = re.findall(
            r'<li class="b_algo"[^>]*>.*?<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?</li>',
            text,
            re.DOTALL,
        )
        for href, title_html in items[:limit]:
            title = re.sub(r"<[^>]+>", "", title_html).strip()
            if not title or not href:
                continue
            results.append(
                {
                    "title": unescape(title),
                    "url": _decode_bing_redirect(href),
                    "snippet": "",
                    "source": "bing",
                }
            )

        # 摘要在每条结果中通过紧跟的 <p> 获取（用结果块内的 <p> 而非全局）
        if results:
            blocks = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', text, re.DOTALL)
            for i, block in enumerate(blocks[: limit]):
                p_m = re.search(r"<p[^>]*>(.*?)</p>", block, re.DOTALL)
                if p_m:
                    results[i]["snippet"] = unescape(
                        re.sub(r"<[^>]+>", "", p_m.group(1))
                        .replace('<span class="algoSlug_icon">', "")
                        .strip()
                    )
        # 相关性自检：Bing 中文分词不可靠（如"人工智能"常被切成"人工"）。
        # 若首条标题与 query 无任何公共词元（交集为空），视为分词失败——
        # 返回可恢复错误而非错误结果，让上层换内核/换措辞。
        if results:
            q_words = [
                w for w in re.split(r"[\s\-—/·,，。.]+", query) if len(w) >= 2
            ]
            first_title = results[0]["title"]
            common = [w for w in q_words if w in first_title]
            if q_words and not common and len(q_words) >= 2:
                raise BingSearchBlocked(
                    f"Bing 中文分词异常：查询 {query!r} 被误判（首条结果 '{first_title[:20]}...' 与查询无公共词元），请换用 baidu 内核或调整措辞"
                )
        return results


class BingSearchBlocked(Exception):
    """Bing 反爬/异常响应。"""


DEFAULT = BingSearchProvider