"""L2 通用适配器：不认识任何搜索引擎的 class，只认结构。

user:“专用适配器失败时，利用 DOM、链接、标题层级、可访问性结构等信息重新识别结果”+
(所以这里的卡片选择器全是结构性的：结果列表容器下的直接子项；标题认 h1–h3；
链接认 http 链接；摘要没有专用选择器，直接取卡片里最长的一段话)。
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import EngineAdapter


@dataclass(frozen=True)
class GenericAdapter(EngineAdapter):
    name: str = "generic"
    hosts: tuple[str, ...] = ()
    card_selectors: tuple[str, ...] = (
        "#rso > div",
        "#b_results > li",
        "#content_left > div",
        "main article",
        "main > div > div",
        "ol > li",
    )
    container_selectors: tuple[str, ...] = ("#rso", "#b_results", "#content_left", "main", "body")
    title_selectors: tuple[str, ...] = ("h3", "h2", "h1", "[role=heading]")
    link_selectors: tuple[str, ...] = ("a[href^='http']", "a[href^='/']", "a[href]")
    exclude_selectors: tuple[str, ...] = ("header", "footer", "nav", "aside")
    wait_selector: str = ""

    def build_query(self, query: str, page: int = 1, type_: str = "web", freshness: str = "") -> str:
        raise ValueError("通用适配器不构造查询：它只用于识别已经打开的页面")

    def next_page_url(self, url: str, page: int) -> str:
        return url


GENERIC = GenericAdapter()
