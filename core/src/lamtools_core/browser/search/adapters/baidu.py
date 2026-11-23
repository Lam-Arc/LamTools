"""百度结果页适配器。

user:“正确识别自然结果与特殊卡片；广告和商业推广结果；百度跳转链接；
对于无法安全解析出最终目标的跳转 URL，保留原链接并标注待解析，不得猜测真实 URL”+
(自然结果认 `div.result` / `div.result-op`；推广认 `[data-tuiguang]` 与 `ec_result`；
`/link?url=` 是加密 token，解包在 pipeline 里会标成 pending 而不是编一个目标地址)。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .base import EngineAdapter, normalize_freshness

_BAIDU_TYPE_BASE = {
    "web": "https://www.baidu.com/s",
    "news": "https://www.baidu.com/s",
    "image": "https://image.baidu.com/search/index",
    "video": "https://www.baidu.com/sf/vsearch",
}
_FRESHNESS_SECONDS = {
    "day": 24 * 3600,
    "week": 7 * 24 * 3600,
    "month": 30 * 24 * 3600,
    "year": 365 * 24 * 3600,
}


@dataclass(frozen=True)
class BaiduAdapter(EngineAdapter):
    name: str = "baidu"
    hosts: tuple[str, ...] = ("baidu.com",)
    card_selectors: tuple[str, ...] = (
        "div.result", "div.result-op", "div.ec_result", "[data-tuiguang]", "div[class~='c-container']"
    )
    container_selectors: tuple[str, ...] = ("#content_left", "main")
    title_selectors: tuple[str, ...] = ("h3 a", "h3", "a.t")
    link_selectors: tuple[str, ...] = ("h3 a", "a[href^='http']", "a[href^='/link']", "a")
    snippet_selectors: tuple[str, ...] = (
        ".c-abstract", ".c-span-last", "[class*='content-right']", ".c-line-clamp2", ".c-line-clamp3", ".c-color-text"
    )
    published_selectors: tuple[str, ...] = (
        ".c-color-gray2", ".c-color-gray", "span[class*='date']", ".news-source", "time"
    )
    sitelink_selectors: tuple[str, ...] = ("div[class*='sitelink'] a", "div[class*='c-row'] a")
    sponsored_selectors: tuple[str, ...] = (
        "[data-tuiguang]", "div.ec_result", "div[class*='ec-tuiguang']", "#content_left > div.ec_result",
        "div[class*='ec_'], div[class*='ec-']"
    )
    exclude_selectors: tuple[str, ...] = ("#head", "#s_tab", "#foot", "#rs", "#top_left", ".s_tab", "nav")
    special_selectors: tuple[str, ...] = ("div.result-op", "div[class*='result-op']", "div[mu]")
    answer_selectors: tuple[str, ...] = ("div[class*='op-answer']", ".op-answer", "div[class*='op_exactqa']")
    wait_selector: str = "#content_left"
    no_results_markers: tuple[str, ...] = (
        "抱歉没有找到", "没有找到相关结果", "很抱歉，没有找到与", "未找到相关结果", "以下为您显示", "没有找到该"
    )
    block_markers: tuple[str, ...] = (
        "百度安全验证", "请输入验证码", "网络不给力", "访问过于频繁", "验证码", "人机验证", "安全验证"
    )
    search_host_suffix: str = "baidu.com"
    search_path_prefixes: tuple[str, ...] = ("/s", "/sf/vsearch", "/search")
    # 首页 + 它自己的搜索框（百度用 #kw）。
    home_url: str = "https://www.baidu.com/"
    search_input_selectors: tuple[str, ...] = ("#kw", "input[name=wd]")

    def build_query(self, query: str, page: int = 1, type_: str = "web", freshness: str = "") -> str:
        kind = str(type_ or "web").lower()
        base = _BAIDU_TYPE_BASE.get(kind, _BAIDU_TYPE_BASE["web"])
        keyword = str(query or "").strip()
        page = max(1, int(page or 1))
        if kind == "news":
            params: list[tuple[str, str]] = [("tn", "news"), ("word", keyword), ("rtt", "1")]
        elif kind == "image":
            params = [("tn", "baiduimage"), ("word", keyword)]
        elif kind == "video":
            params = [("pd", "video"), ("wd", keyword)]
        else:
            params = [("wd", keyword), ("rn", "10"), ("ie", "utf-8")]
        if page > 1:
            params.append(("pn", str((page - 1) * 10)))
        seconds = _FRESHNESS_SECONDS.get(normalize_freshness(freshness), 0)
        if seconds:
            end = int(time.time())
            params.append(("gpc", "stf"))
            params.append(("stft", f"{end - seconds}_{end}"))
        return base + "?" + urlencode(params)

    def next_page_url(self, url: str, page: int) -> str:
        try:
            parts = urlsplit(url)
        except ValueError:
            return url
        pairs = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "pn"]
        pairs.append(("pn", str(max(0, (max(1, int(page or 1)) - 1) * 10))))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))

