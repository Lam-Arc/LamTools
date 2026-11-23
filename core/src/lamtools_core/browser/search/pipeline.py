"""通用提取清洗层：卡片 → 结构化结果。

user:“不得发生标题、摘要、链接跨卡片错配”+
(每条结果的所有字段都只在**它自己的卡片节点**里取，因此「谁配谁」由 DOM 归属决定；
这里不做任何跨卡片补充，取不到就给空字符串)。

user:“不可靠或不存在的字段应为空，不得编造”+
(发布日期只接受能识别的日期形状，否则留空；摘要不做生成式改写，只做规范化与截断)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from . import dom, text as text_tools, urls
from .adapters.base import EngineAdapter

# 摘要兜底时允许当作「一段话」的标签。
_BLOCK_TAGS = frozenset({"p", "div", "span", "td", "li", "section", "article", "dd", "figcaption"})
# 这些标签的孩子仍然是同一段话的一部分（不要因为 <em>/<span> 就把父节点排除）。
_INLINE_TAGS = frozenset({"a", "b", "strong", "em", "i", "span", "u", "mark", "cite", "font", "small", "sup", "sub", "br"})
# 已知视频站点：只用于给结果打类型，不参与排序。
_VIDEO_HOSTS = ("youtube.com", "youtu.be", "bilibili.com", "vimeo.com", "ixigua.com", "douyin.com")

# user:“广告可以保留类型标识，但默认不作为自然搜索结果”与“词典卡/相关搜索不是结果”+
NON_RESULT_TOKENS = (
    "b_ans", "b_related", "b_entity", "b_pag", "b_context", "b_sidebar",
    "related", "entity", "pagination", "recommend", "sidebar",
)

SNIPPET_LIMIT = 400
TITLE_LIMIT = 300


@dataclass
class Outcome:
    """一次提取的结果与统计（统计用于校验与质量记录）。"""

    results: list[dict] = field(default_factory=list)
    cards: int = 0
    invalid: int = 0
    duplicate: int = 0
    sponsored: int = 0
    dropped: int = 0
    chars_in: int = 0
    chars_out: int = 0
    skipped_selectors: tuple[str, ...] = ()

    @property
    def compression(self) -> float:
        if self.chars_in <= 0:
            return 0.0
        return max(0.0, 1.0 - (self.chars_out / self.chars_in))

    def stats(self) -> dict:
        return {
            "cards": self.cards,
            "invalid": self.invalid,
            "duplicate": self.duplicate,
            "sponsored": self.sponsored,
            "dropped": self.dropped,
            "compression": round(self.compression, 3),
        }


def _anchor_href(node: dom.Node, base_url: str) -> str:
    href = node.get("href")
    if not href:
        return ""
    return urls.absolutize(base_url, href)


def _is_navigation_url(url: str, adapter: EngineAdapter) -> bool:
    """搜索引擎自己的内部链接（设置、相关搜索、账号入口）不是搜索结果。

    关键区别：`/url?q=`、`/link?url=`、`/ck/a` 是**指向结果**的中转，算结果；
    只有真正停在引擎站内的搜索/设置页才算导航。先解包再判断，否则整页结果会被误删。
    """
    if not urls.is_web_url(url):
        return True
    target, _resolved = urls.unwrap(url)
    host = urls.host_of(target)
    on_engine = bool(adapter.hosts) and any(
        host == item or host.endswith("." + item) for item in adapter.hosts
    )
    if not on_engine:
        return False
    try:
        path = urlsplit(target).path or "/"
    except ValueError:
        return True
    return path.startswith(("/search", "/preferences", "/advanced", "/setprefs", "/settings", "/account"))


def _title_of(card: dom.Node, adapter: EngineAdapter) -> tuple[str, dom.Node | None]:
    for selector in adapter.title_selectors:
        for node in card.select(selector):
            value = text_tools.one_line(node.text)
            if value:
                return value, node
    # 结构兜底：任何标题层级。
    for tag in ("h1", "h2", "h3", "h4"):
        for node in card.select(tag):
            value = text_tools.one_line(node.text)
            if value:
                return value, node
    return "", None


def _link_of(card: dom.Node, adapter: EngineAdapter, title_node: dom.Node | None, base_url: str) -> tuple[str, dom.Node | None]:
    """标题链接优先：标题节点的祖先/自身是 <a> 时用它，保证「标题 ↔ 地址」同源。"""
    if title_node is not None:
        node: dom.Node | None = title_node
        while node is not None and node is not card:
            if node.tag == "a" and node.get("href"):
                href = _anchor_href(node, base_url)
                if not _is_navigation_url(href, adapter):
                    return href, node
            anchor = node.first("a[href]") if node is not title_node else None
            if anchor is not None:
                href = _anchor_href(anchor, base_url)
                if not _is_navigation_url(href, adapter):
                    return href, anchor
            node = node.parent
    for selector in adapter.link_selectors:
        for anchor in card.select(selector):
            href = _anchor_href(anchor, base_url)
            if not href or _is_navigation_url(href, adapter):
                continue
            # 无标题时，只有带文字的链接才可能是结果标题。
            if title_node is None and len(text_tools.one_line(anchor.text)) < 2:
                continue
            return href, anchor
    return "", None


def _blocks(card: dom.Node) -> list[tuple[dom.Node, str]]:
    """把卡片里「一段话」的节点按文档顺序取出来（摘要兜底用）。"""
    found: list[tuple[dom.Node, str]] = []
    for node in card.iter_descendants():
        if node.tag not in _BLOCK_TAGS:
            continue
        child_elements = [child for child in node.children if child.tag not in _INLINE_TAGS]
        if child_elements:
            continue
        value = text_tools.one_line(node.text)
        if value:
            found.append((node, value))
    return found


def _inside(node: dom.Node, ancestor: dom.Node | None) -> bool:
    if ancestor is None:
        return False
    current: dom.Node | None = node
    while current is not None:
        if current is ancestor:
            return True
        current = current.parent
    return False


def _snippet_of(card: dom.Node, adapter: EngineAdapter, title: str, title_node: dom.Node | None, link_node: dom.Node | None) -> str:
    for selector in adapter.snippet_selectors:
        for node in card.select(selector):
            if _inside(node, title_node) or _inside(node, link_node):
                continue
            value = text_tools.strip_decoration(node.text)
            if not value or value == title or text_tools.is_decorative(value):
                continue
            return text_tools.clip(value, SNIPPET_LIMIT)
    # 结构兜底：卡片里最长的一段话（排除标题与链接本身）。
    best = ""
    for node, value in _blocks(card):
        if _inside(node, title_node) or _inside(node, link_node):
            continue
        if value == title or text_tools.is_decorative(value):
            continue
        if len(value) > len(best):
            best = value
    return text_tools.clip(best, SNIPPET_LIMIT)


def _published_of(card: dom.Node, adapter: EngineAdapter) -> str:
    for selector in adapter.published_selectors:
        for node in card.select(selector):
            stamp = node.get("datetime") or node.get("data-date") or ""
            value = text_tools.extract_date(stamp) if stamp else ""
            if value:
                return value
            value = text_tools.extract_date(node.text)
            if value:
                return value
    return ""


def _sitelinks_of(
    card: dom.Node,
    adapter: EngineAdapter,
    base_url: str,
    main_url: str,
    link_node: dom.Node | None,
) -> list[dict]:
    links: list[dict] = []
    seen: set[str] = set()
    for selector in adapter.sitelink_selectors:
        for anchor in card.select(selector):
            if _inside(anchor, link_node) or anchor is link_node:
                continue
            href = _anchor_href(anchor, base_url)
            if not href or _is_navigation_url(href, adapter):
                continue
            title = text_tools.one_line(anchor.text)
            if not title or len(title) > 60:
                continue
            key = urls.dedupe_key(href)
            if key == urls.dedupe_key(main_url) or key in seen:
                continue
            seen.add(key)
            links.append({"title": title, "url": urls.clean(href), "originalUrl": href})
            if len(links) >= 4:
                return links
    if links:
        return links
    # 结构兜底：卡片里除主链接外的短文字链接（Google 的站点链接常见这种形态）。
    for anchor in card.select("a[href]"):
        if anchor is link_node or _inside(anchor, link_node):
            continue
        href = _anchor_href(anchor, base_url)
        if not href or _is_navigation_url(href, adapter):
            continue
        title = text_tools.one_line(anchor.text)
        if not title or len(title) > 40:
            continue
        key = urls.dedupe_key(href)
        if key == urls.dedupe_key(main_url) or key in seen:
            continue
        seen.add(key)
        links.append({"title": title, "url": urls.clean(href), "originalUrl": href})
        if len(links) >= 3:
            break
    return links


def _result_type(adapter: EngineAdapter, card: dom.Node, url: str, requested: str) -> str:
    kind = str(requested or "web").lower()
    if kind in {"news", "image", "video"}:
        return kind
    special = adapter.special_kind(card)
    if special:
        return special
    host = urls.host_of(url)
    if any(host == item or host.endswith("." + item) for item in _VIDEO_HOSTS):
        return "video"
    return "web"


@dataclass
class CardRecord:
    card: dom.Node
    selector: str
    title: str
    url: str
    original_url: str
    snippet: str
    published: str
    sponsored: bool
    sitelinks: list[dict]
    type: str
    pending: bool


def _read_card(
    card: dom.Node,
    selector: str,
    adapter: EngineAdapter,
    base_url: str,
    requested_type: str,
) -> CardRecord | None:
    for selector_exclude in adapter.exclude_selectors:
        try:
            if card.matches(selector_exclude):
                return None
        except dom.SelectorError:
            continue
    title, title_node = _title_of(card, adapter)
    href, link_node = _link_of(card, adapter, title_node, base_url)
    if not href:
        return None
    absolute, resolved = urls.unwrap(href)
    cleaned = urls.clean(absolute)
    if not cleaned:
        return None
    snippet = _snippet_of(card, adapter, title, title_node, link_node)
    published = _published_of(card, adapter)
    sitelinks = _sitelinks_of(card, adapter, base_url, cleaned, link_node)
    return CardRecord(
        card=card,
        selector=selector,
        title=title,
        url=cleaned,
        original_url=href,
        snippet=snippet,
        published=published,
        sponsored=adapter.is_sponsored(card),
        sitelinks=sitelinks,
        type=_result_type(adapter, card, cleaned, requested_type),
        pending=not resolved,
    )


def _first_element(root: dom.Node) -> dom.Node | None:
    return next((node for node in root.children if node.tag), None)


def _dedupe_nested(nodes: list[dom.Node]) -> list[dom.Node]:
    """父子同时命中只留外层；保持文档顺序。"""
    kept: list[dom.Node] = []
    for node in nodes:
        if any(parent is node or _inside(node, parent) for parent in kept):
            continue
        kept.append(node)
    return kept


def _result_shape(node: dom.Node) -> bool:
    """通用兜底时的「这条像不像一条搜索结果」：有标题、有外链、有一段话，且不是已知的非结果模块。

    user:“轮播克隆项和重复结果”与“词典卡/相关搜索”+
    (搜索引擎把词典卡、相关搜索、推荐位也塞在结果容器里；没有结构判断就会把它们当结果，
    读起来像是「把查询拆成了一个字」)。
    """
    tokens = f"{node.get(chr(99) + chr(108) + chr(97) + chr(115) + chr(115))} {node.get(chr(105) + chr(100))}".lower()
    if any(token in tokens for token in NON_RESULT_TOKENS):
        return False
    if not (node.first("h1") or node.first("h2") or node.first("h3") or node.first("h4")):
        return False
    if not any(urls.is_web_url(_anchor_href(anchor, "https://example.com/")) for anchor in node.select("a[href]")):
        return False
    return len(node.text) >= 25


def _discover_cards(root: dom.Node, adapter: EngineAdapter) -> list[dom.Node]:
    """L2：在没有引擎专用卡片结构时，用结构语义重新找出「一条结果」。

    顺序：先用通用卡片选择器；一条都不中时，退回「有标题 + 有短链接 + 有一段话」的祖先块，
    并只保留最外层，避免一条结果被切成几段。
    """
    # user:“不被分词等异化”+
    # (实测：Bing 的答案优先版式里，`li.b_ans` 那条摘要卡会先命中——原来的写法「第一个命中的选择器
    #  就 return」于是整页只剩 1 条，看起来就像查询被截成了首词。改成取候选最多的那一组：
    #  选择器给得太少时，继续比一遍「标题 + 链接 + 一段话」的祖先块，谁多听谁的)。
    candidates: list[dom.Node] = []
    for selector in adapter.card_selectors:
        try:
            found = root.select(selector)
        except dom.SelectorError:
            continue
        if not found:
            continue
        shaped = [node for node in _dedupe_nested(found) if _result_shape(node)]
        if len(shaped) > len(candidates):
            candidates = shaped
        # 已经够一页了，不必再往下试。
        if len(candidates) >= 5:
            return candidates
    anchored: list[dom.Node] = []
    for heading in root.select("h1, h2, h3, h4"):
        ancestor = heading
        for _ in range(4):
            ancestor = ancestor.parent
            if ancestor is None:
                break
            if ancestor.first("a[href]"):
                length = len(ancestor.text)
                if 12 <= length <= 4000:
                    anchored.append(ancestor)
                    break
    anchored = _dedupe_nested(anchored)
    if len(anchored) > len(candidates):
        candidates = anchored
    return candidates


def read_answer(adapter: EngineAdapter, nodes: list[dict], base_url: str = "") -> dict | None:
    """读引擎自己给的「摘要/引用块」。

    user:“加，但是我好奇为什么你搜和我搜进的网页不一样”+
    (它是版式差异带来的额外内容，不是排过序的自然结果：单独返回、不占 rank，
    取不到就返回 None，绝不编一段“摘要”)。
    """
    for item in nodes:
        root = dom.parse(str(item.get("html") or ""))
        for selector in adapter.answer_selectors:
            try:
                found = root.select(selector)
            except dom.SelectorError:
                continue
            for node in found:
                text = text_tools.normalize(node.text)
                if len(text) < 20:
                    continue
                heading = ""
                for tag in ("h2", "h3", "h4"):
                    first = node.first(tag)
                    if first is not None and text_tools.normalize(first.text):
                        heading = text_tools.one_line(first.text)
                        break
                url = ""
                anchor = node.first("a[href]")
                if anchor is not None:
                    url = urls.clean(urls.absolutize(base_url, anchor.get("href")))
                return {
                    "text": text_tools.clip(text, 800),
                    "title": heading or text_tools.clip(text, 60),
                    "url": url,
                    "selector": selector,
                }
    return None


def extract(
    adapter: EngineAdapter,
    nodes: list[dict],
    *,
    base_url: str,
    limit: int = 10,
    include_ads: bool = False,
    requested_type: str = "web",
    mode: str = "l1",
) -> Outcome:
    """把页面取回来的片段清洗成结构化结果。

    ``mode="l1"``：每个片段就是一张卡片（引擎专用选择器命中）；
    ``mode="l2"``：每个片段是结果容器，卡片在容器内部按结构重新发现。
    """
    outcome = Outcome()
    natural: list[dict] = []
    ads: list[dict] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()

    candidates: list[tuple[dom.Node, str]] = []
    for item in nodes:
        html = str(item.get("html") or "")
        selector = str(item.get("selector") or "")
        outcome.chars_in += len(html)
        root = dom.parse(html)
        if mode == "l1":
            card = _first_element(root)
            # user:“不被分词等异化”+
            # (实测诊断：命中结果容器的片段（#b_results / #rso）如果当单张卡处理，
            #  整页就只会得到 1 条——看起来像查询被截成了首词。容器要按结构展开，
            #  专用提取才能和通用兜底拿到一样多的结果)。
            if card is not None and selector in adapter.card_selectors:
                candidates.append((card, selector))
                continue
            found = _discover_cards(root, adapter)
            if found:
                candidates.extend((item, selector) for item in found)
            elif card is not None:
                candidates.append((card, selector))
            else:
                outcome.invalid += 1
            continue
        found = _discover_cards(root, adapter)
        if not found:
            outcome.invalid += 1
            continue
        candidates.extend((card, selector) for card in found)

    for card, selector in candidates:
        record = _read_card(card, selector, adapter, base_url, requested_type)
        if record is None:
            outcome.invalid += 1
            continue
        outcome.cards += 1

        if record.sponsored:
            outcome.sponsored += 1
        # 标题与地址必须同时成立：只有其中一个是解析错位的典型症状。
        if len(record.title) < 2 or len(record.url) < 8:
            outcome.invalid += 1
            continue
        title = text_tools.clip(text_tools.one_line(record.title), TITLE_LIMIT)
        url_key = urls.dedupe_key(record.url)
        title_key = f"{title.lower()}@{urls.host_of(record.url)}"
        if url_key in seen_urls or title_key in seen_titles:
            outcome.duplicate += 1
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)

        entry = {
            "title": title,
            "url": record.url,
            "originalUrl": record.original_url,
            "snippet": record.snippet,
            "source": "" if record.pending else urls.host_of(record.url),
            "type": record.type,
            "publishedAt": record.published,
            "sponsored": bool(record.sponsored),
            "sitelinks": record.sitelinks,
            "extraction": mode,
        }
        if record.pending:
            entry["urlPending"] = True
        (ads if record.sponsored else natural).append(entry)

    ordered = natural + (ads if include_ads else [])
    if not include_ads:
        outcome.dropped = len(ads)
    for index, entry in enumerate(ordered):
        if index >= max(1, int(limit)):
            break
        entry["rank"] = index + 1
        outcome.results.append(entry)
        outcome.chars_out += len(entry["title"]) + len(entry["snippet"]) + len(entry["url"])
    return outcome
