"""引擎适配器的共同形状：每个引擎只描述「自己的页面长什么样」，不做通用清洗。

user:“每个适配器负责识别自身引擎的 DOM 特征，不承担通用清洗逻辑”+
(所以这里只有选择器、等待标记、受阻标记、查询构造与分页；字段配对、去重、URL 清洗、
排序与校验都在 pipeline 里，写一次对三个引擎同时生效)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote_plus, urlsplit

from .. import text as text_tools

# 时间约束的归一化名字（调用方说 day/week/month/year，或者直接给 qdr 之类的引擎参数）。
FRESHNESS_ALIASES = {
    "day": "day", "d": "day", "24h": "day", "today": "day", "今天": "day", "一天": "day",
    "week": "week", "w": "week", "7d": "week", "本周": "week", "一周": "week",
    "month": "month", "m": "month", "30d": "month", "本月": "month", "一个月": "month",
    "year": "year", "y": "year", "一年": "year",
}


def normalize_freshness(value: str | None) -> str:
    if not value:
        return ""
    return FRESHNESS_ALIASES.get(str(value).strip().lower(), "")


@dataclass(frozen=True)
class EngineAdapter:
    """一个搜索引擎的页面知识。所有选择器都按优先级排列，第一个能用的胜出。"""

    name: str
    hosts: tuple[str, ...]
    card_selectors: tuple[str, ...]
    container_selectors: tuple[str, ...]
    title_selectors: tuple[str, ...]
    link_selectors: tuple[str, ...]
    snippet_selectors: tuple[str, ...] = ()
    published_selectors: tuple[str, ...] = ()
    sitelink_selectors: tuple[str, ...] = ()
    sponsored_selectors: tuple[str, ...] = ()
    exclude_selectors: tuple[str, ...] = ()
    # 特殊卡片（百科/贴吧/知道、新闻、视频）的结构标记。
    special_selectors: tuple[str, ...] = ()
    # user:“加，但是我好奇为什么你搜和我搜进的网页不一样”+
    # (回答/摘要块只在引擎投放的 enriched 版式里出现。实测它与 URL 参数无关：
    #  裸请求即便拼全套“搜索框提交”参数（qs/form/pq/cvid）也拿不到，所以这里只做
    #  “页面里真有就取、没有就算了”，不指望靠改地址去逼它出现。
    #  它不属于自然排名结果，单独返回，不混进 rank)。
    answer_selectors: tuple[str, ...] = ()

    # user:“我手动输入之后点回车，它搜出来的结果也没有问题”+
    # (直接打开结果地址时，引擎会把请求当成「重定向/导航」掉进另一种版式——同一个查询
    #  只按首词匹配、结果全是某官网。走「首页 -> 在搜索框里输入 -> 回车」才是真人路径，
    #  所以适配器要说清楚自己的首页和它那个搜索框)。
    home_url: str = ""
    search_input_selectors: tuple[str, ...] = ()
    # 提交搜索框时表单里 form 字段该是什么值。
    # user:“不被分词等异化”+(Bing 首页会被设成「热门内容」入口，提交后跳进
    #  popularnow.carousel 视图、只回一两条；拨回 QBRE 才是真正的搜索入口)。
    search_form_value: str = ""
    wait_selector: str = ""
    no_results_markers: tuple[str, ...] = ()
    block_markers: tuple[str, ...] = ()
    # 结果页的判定：URL 主机后缀 + 路径前缀。
    search_host_suffix: str = ""
    search_path_prefixes: tuple[str, ...] = ("/search",)
    # 额外字段（各引擎自己用得上，比如分页参数名）。
    extra: dict = field(default_factory=dict)

    # --- 查询 ---------------------------------------------------------

    def build_query(self, query: str, page: int = 1, type_: str = "web", freshness: str = "") -> str:
        raise NotImplementedError

    def next_page_url(self, url: str, page: int) -> str:
        raise NotImplementedError

    # --- 判定 ---------------------------------------------------------

    def detect_page(self, url: str, page_text: str = "") -> bool:
        """URL 形状对得上就算「这是本引擎的结果页」。

        不依赖选择器：页面改版时选择器会失效，但 URL 形状一直稳定。
        """
        try:
            parts = urlsplit(url or "")
        except ValueError:
            return False
        host = (parts.hostname or "").lower()
        if not host:
            return False
        if not any(host == item or host.endswith("." + item) for item in self.hosts):
            return False
        path = parts.path or "/"
        return any(path.startswith(prefix) for prefix in self.search_path_prefixes)

    def detect_block(self, url: str = "", title: str = "", page_text: str = "") -> str:
        """返回受阻类型（空字符串表示没受阻）。只认页面上的明确信号，不猜。"""
        haystack = text_tools.one_line(f"{title} {page_text}").lower()
        if not haystack:
            return ""
        for marker in self.block_markers:
            if marker.lower() in haystack:
                if "captcha" in marker.lower() or "验证" in marker or "robot" in marker.lower():
                    return "captcha"
                if "异常" in marker or "unusual" in marker.lower() or "频繁" in marker:
                    return "rate_limited"
                return "blocked"
        return ""

    def has_no_results(self, page_text: str) -> bool:
        haystack = text_tools.one_line(page_text).lower()
        if not haystack:
            return False
        return any(marker.lower() in haystack for marker in self.no_results_markers)

    def is_sponsored(self, node) -> bool:
        """结构优先：命中广告容器/标记才算推广，不靠摘要里出现「广告」两个字。"""
        for selector in self.sponsored_selectors:
            try:
                if node.matches(selector) or node.first(selector) is not None:
                    return True
            except Exception:  # noqa: BLE001 - 选择器写错不该让整页解析失败
                continue
        # 广告标记（很短的标签文本），避免把正文里的词误判成广告。
        for marker in ("广告", "赞助", "推广", "sponsored", "ad ·", "广告·"):
            for candidate in node.select("span, div, label"):
                label = text_tools.strip_decoration(candidate.text).lower()
                if not label or len(label) > 12:
                    continue
                if label == marker or label.startswith(marker):
                    return True
        return False

    def special_kind(self, node) -> str:
        """特殊卡片（新闻/视频/百科贴吧知道这类）。"""
        for selector in self.special_selectors:
            try:
                if node.matches(selector) or node.first(selector) is not None:
                    return "special"
            except Exception:  # noqa: BLE001
                continue
        return ""

    # --- 工具 ---------------------------------------------------------

    @staticmethod
    def quote(query: str) -> str:
        """整句编码：不切词、不改写（PRD：保留完整搜索词）。"""
        return quote_plus(str(query or "").strip(), safe="")
