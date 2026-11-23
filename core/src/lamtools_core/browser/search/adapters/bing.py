"""Bing 结果页适配器。

user:“保留用户原始查询，避免因 Sunday 自身的词语处理导致搜索意图丢失”+
(查询只做整串百分号编码，不切词、不加引号、不改写；分页用 `first` 参数，从 1 开始)。
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .base import EngineAdapter

_BING_TYPE_BASE = {
    "web": "https://www.bing.com/search",
    "news": "https://www.bing.com/news/search",
    "image": "https://www.bing.com/images/search",
    "video": "https://www.bing.com/videos/search",
}
# Bing 的时间过滤：24 小时 / 一周 / 一个月（官方没有「一年」这一档）。
_BING_FRESHNESS = {"day": "ex1:\"ez1\"", "week": "ex1:\"ez2\"", "month": "ex1:\"ez3\""}


@dataclass(frozen=True)
class BingAdapter(EngineAdapter):
    name: str = "bing"
    hosts: tuple[str, ...] = ("bing.com",)
    card_selectors: tuple[str, ...] = (
        "li.b_algo", "li[class*='b_ad']", "li.b_ans", "#b_results > li",
        # user:“不被分词等异化”+
        # (实测诊断：Bing 有一版结果页根本没有 #b_results，结果挂在 #rso 下——
        #  专用选择器一条都不命中、只能靠通用兜底捞。把 #rso 也认下来，
        #  分页/提示这类没有标题+链接的项会被 pipeline 判无效丢弃)。
        "#rso > div", "#rso > li",
    )
    # #rso 是 Bing 另一版结果容器（实测某些版式只有它），放进来才能让专用提取直接命中。
    container_selectors: tuple[str, ...] = ("#b_results", "#rso", "main")
    # user:“是被分词截断的只剩 DeepSeek 了”+
    # (答案优先版式里结果标题不在 h2 上——专用选择器全空，通用兜底靠 h1/[role=heading] 才认出来)。
    title_selectors: tuple[str, ...] = ("h2 a", "h2", "h3", "h1", "[role=heading]")
    link_selectors: tuple[str, ...] = ("h2 a", "a[href^='http']", "a")
    snippet_selectors: tuple[str, ...] = (
        ".b_caption p", ".b_lineclamp2", ".b_lineclamp3", ".b_lineclamp4", ".b_algoSlug", "p"
    )
    published_selectors: tuple[str, ...] = ("span.news_dt", ".b_attribution cite", "time")
    sitelink_selectors: tuple[str, ...] = ("div.b_vlist a", ".b_deep a", ".b_sitelink a")
    sponsored_selectors: tuple[str, ...] = ("li.b_ad", "li.b_adTop", "li.b_adBottom", "#bads", "[data-bm-ad]")
    exclude_selectors: tuple[str, ...] = ("#b_header", "#b_context", "#b_footer", "footer", "nav")
    special_selectors: tuple[str, ...] = ("li.b_ans", ".b_ans", "li.b_newsitem")
    answer_selectors: tuple[str, ...] = ("li.b_ans", "div.b_ans", ".b_ans", "#b_context .b_ans")
    wait_selector: str = "#b_results"
    no_results_markers: tuple[str, ...] = (
        "没有与此相关的结果", "找不到与此相关的结果", "there are no results for", "no results found for"
    )
    block_markers: tuple[str, ...] = (
        "unusual traffic", "verify you are human", "please solve the challenge", "captcha",
        "请验证你是人类", "验证码", "人机验证", "我们的系统检测到",
    )
    search_host_suffix: str = "bing.com"
    search_path_prefixes: tuple[str, ...] = ("/search", "/news/search", "/images/search", "/videos/search")
    # 首页 + 它自己的搜索框（`#sb_form_q`）：搜索走「首页 -> 输入 -> 回车」，和真人一致。
    home_url: str = "https://cn.bing.com/"
    search_input_selectors: tuple[str, ...] = ("#sb_form_q", "#sb_form input[name=q]", "input[name=q]")
    search_form_value: str = "QBRE"

    def build_query(self, query: str, page: int = 1, type_: str = "web", freshness: str = "") -> str:
        base = _BING_TYPE_BASE.get(str(type_ or "web").lower(), _BING_TYPE_BASE["web"])
        params: list[tuple[str, str]] = [("q", str(query or "").strip()), ("count", "10")]
        page = max(1, int(page or 1))
        if page > 1:
            params.append(("first", str((page - 1) * 10 + 1)))
        window = _BING_FRESHNESS.get(str(freshness or "").lower(), "")
        if window:
            params.append(("filters", window))
        return base + "?" + urlencode(params)

    def next_page_url(self, url: str, page: int) -> str:
        try:
            parts = urlsplit(url)
        except ValueError:
            return url
        pairs = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "first"]
        pairs.append(("first", str(max(0, (max(1, int(page or 1)) - 1) * 10 + 1))))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))

