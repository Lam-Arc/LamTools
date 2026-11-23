"""Google 结果页适配器。

user:“避免把 Google 的导航、账号链接、追踪 URL 误认为搜索结果”+
(卡片只认结果容器（`.MjjYud` / `.g`），标题只认 h3；导航与账号入口在 exclude 里，
URL 解包在 pipeline 统一做——`/url?q=` 会被还原成目标地址)。
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .base import EngineAdapter, normalize_freshness

_GOOGLE_TBM = {"web": "", "news": "nws", "image": "isch", "video": "vid"}
_FRESHNESS_QDR = {"day": "qdr:d", "week": "qdr:w", "month": "qdr:m", "year": "qdr:y"}


@dataclass(frozen=True)
class GoogleAdapter(EngineAdapter):
    name: str = "google"
    hosts: tuple[str, ...] = ("google.com", "google.com.hk", "google.co.jp", "google.co.uk", "google.com.tw")
    card_selectors: tuple[str, ...] = (
        "div.MjjYud", "div.g", "div.tF2Cxc", "div.uEierd", "[data-text-ad]", "div[data-hveid][lang]"
    )
    container_selectors: tuple[str, ...] = ("#rso", "#search", "main")
    title_selectors: tuple[str, ...] = ("h3", "[role=heading]")
    link_selectors: tuple[str, ...] = ("a[href^='/url']", "a[href^='http']", "a")
    snippet_selectors: tuple[str, ...] = (
        "div.VwiC3b", "div.IsZvec", "span.aCOpRe", "div[data-sncf]", "div.lyLwlc", "div.s", "div.kb0PBd"
    )
    published_selectors: tuple[str, ...] = ("span.LEwnQ", "div.YrbPuc", "time")
    sitelink_selectors: tuple[str, ...] = ("div.HiH0rd a", "table a", "div.jh0Tpd a", "div[role=heading] a")
    sponsored_selectors: tuple[str, ...] = (
        "#tads", "#tadsb", ".uEierd", "[data-text-ad]", ".commercial-unit-desktop-top", ".ads-ad"
    )
    exclude_selectors: tuple[str, ...] = ("header", "footer", "nav", "#searchform", "#top_nav", "#sfooter", "#foot")
    special_selectors: tuple[str, ...] = ("g-section-with-header", "block-component")
    answer_selectors: tuple[str, ...] = (".hgKElc", "block-component", "g-section-with-header")
    wait_selector: str = "#search"
    no_results_markers: tuple[str, ...] = (
        "找不到和您查询的", "没有找到与", "未找到任何结果", "did not match any documents", "no results found for"
    )
    block_markers: tuple[str, ...] = (
        "unusual traffic", "detected unusual traffic", "reCAPTCHA", "not a robot", "verify you are human",
        "检测到异常流量", "人机验证", "验证你是人类", "访问过于频繁", "自动化查询",
    )
    search_host_suffix: str = "google.com"
    search_path_prefixes: tuple[str, ...] = ("/search",)
    # 首页 + 它自己的搜索框（Google 用 textarea[name=q]）。
    home_url: str = "https://www.google.com/"
    search_input_selectors: tuple[str, ...] = ("textarea[name=q]", "input[name=q]")

    def build_query(self, query: str, page: int = 1, type_: str = "web", freshness: str = "") -> str:
        params: list[tuple[str, str]] = [("q", str(query or "").strip()), ("num", "10")]
        tbm = _GOOGLE_TBM.get(str(type_ or "web").lower(), "")
        if tbm:
            params.append(("tbm", tbm))
        qdr = _FRESHNESS_QDR.get(normalize_freshness(freshness), "")
        if qdr:
            params.append(("tbs", qdr))
        page = max(1, int(page or 1))
        if page > 1:
            params.append(("start", str((page - 1) * 10)))
        return "https://www.google.com/search?" + urlencode(params)

    def next_page_url(self, url: str, page: int) -> str:
        try:
            parts = urlsplit(url)
        except ValueError:
            return url
        pairs = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "start"]
        pairs.append(("start", str(max(0, (max(1, int(page or 1)) - 1) * 10))))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))

