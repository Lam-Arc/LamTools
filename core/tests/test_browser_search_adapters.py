"""搜索适配器与清洗层的离线回归（HTML 结构样本驱动，不联网）。

user:“不得发生标题、摘要、链接跨卡片错配”与“URL 清洗不会破坏正常链接”+
(这里用三条真实结构样本钉住：字段归属、广告分离、中转解包、去重、分页、受阻识别)。
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

from lamtools_core.browser.search import adapters, dom, pipeline, urls
from lamtools_core.browser.search import text as text_tools
from lamtools_core.browser.search.adapters.generic import GENERIC
from lamtools_core.browser.search import reader

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "search"
BASE_URL = {
    "bing": "https://www.bing.com/search?q=bilibili",
    "google": "https://www.google.com/search?q=bilibili",
    "baidu": "https://www.baidu.com/s?wd=bilibili",
}


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _has_ancestor(node: dom.Node, candidate: dom.Node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent is candidate:
            return True
        parent = parent.parent
    return False


def _outer_only(nodes: list[dom.Node]) -> list[dom.Node]:
    kept: list[dom.Node] = []
    for node in nodes:
        if any(node is other or _has_ancestor(node, other) for other in kept):
            continue
        kept.append(node)
    return kept


def nodes_for(html: str, selectors: tuple[str, ...]) -> list[dict]:
    """模拟页面侧：把所有选择器命中的卡片片段取回来（同一元素只算一次，父子只留外层）。

    页面侧（`bridge_script.js` 的 `extractHtml`）就是「多个选择器取并集 + 文档顺序」，
    所以这里必须并集；只取第一个命中的选择器会把广告卡片整类漏掉。
    """
    root = dom.parse(html)
    seen: set[int] = set()
    ordered: list[tuple[dom.Node, str]] = []
    for selector in selectors:
        for node in root.select(selector):
            marker = id(node)
            if marker in seen:
                continue
            seen.add(marker)
            ordered.append((node, selector))
    kept: list[tuple[dom.Node, str]] = []
    for node, selector in ordered:
        if any(node is other or _has_ancestor(node, other) for other, _ in kept):
            continue
        kept.append((node, selector))
    return [{"selector": selector, "html": node.to_html()} for node, selector in kept]


def extract(engine: str, name: str, **kwargs) -> pipeline.Outcome:
    adapter = adapters.get(engine)
    nodes = nodes_for(fixture(name), adapter.card_selectors)
    kwargs.setdefault("base_url", BASE_URL[engine])
    kwargs.setdefault("limit", 10)
    return pipeline.extract(adapter, nodes, requested_type=kwargs.pop("requested_type", "web"), **kwargs)


# --- Bing ---------------------------------------------------------------


def test_bing_cards_pair_their_own_title_snippet_and_url():
    outcome = extract("bing", "bing_results.html")
    titles = [item["title"] for item in outcome.results]
    assert titles[0].startswith("哔哩哔哩")
    assert titles[1] == "哔哩哔哩专栏 - 文章频道"
    assert [item["rank"] for item in outcome.results] == [1, 2, 3]

    first = outcome.results[0]
    # 跟踪参数被清掉，目标地址与业务参数保留。
    assert first["url"] == "https://www.bilibili.com/"
    assert first["originalUrl"].startswith("https://www.bilibili.com/?spm_id_from=")
    assert first["source"] == "bilibili.com"
    assert "视频弹幕网站" in first["snippet"]
    assert "专栏" not in first["snippet"]
    # 站点链接只属于它自己那张卡片。
    assert [link["title"] for link in first["sitelinks"]] == ["热门", "番剧"]
    assert all(link["title"] != "热门" for link in outcome.results[1]["sitelinks"])

    assert outcome.results[1]["publishedAt"] == "2024-05-01"


def test_bing_drops_ads_by_default_and_marks_them_when_requested():
    default = extract("bing", "bing_results.html")
    assert all(not item["sponsored"] for item in default.results)
    assert default.sponsored == 1
    assert default.dropped == 1

    with_ads = extract("bing", "bing_results.html", include_ads=True)
    assert with_ads.results[-1]["sponsored"] is True
    assert "会员" in with_ads.results[-1]["title"]
    assert all(not item["sponsored"] for item in with_ads.results[:-1])
    assert with_ads.results[-1]["rank"] == len(with_ads.results)


def test_bing_duplicate_card_is_dropped_not_merged_with_other_pages():
    outcome = extract("bing", "bing_results.html")
    assert outcome.duplicate == 1
    assert len({item["url"] for item in outcome.results}) == len(outcome.results)


# --- Google -------------------------------------------------------------


def test_google_unwraps_redirect_and_keeps_meaningful_query_params():
    outcome = extract("google", "google_results.html")
    assert outcome.results[0]["url"] == "https://www.bilibili.com/"
    assert outcome.results[1]["url"] == "https://www.bilibili.com/read/home"
    # 中文路径不能被“解码坏”：百分号编码的百科地址原样保留。
    assert "zh.wikipedia.org/wiki/" in outcome.results[2]["url"]
    assert outcome.results[1]["publishedAt"] == "2024年4月30日"
    assert all(item["sponsored"] is False for item in outcome.results)


def test_google_engine_internal_links_are_not_results():
    outcome = extract("google", "google_results.html")
    for item in outcome.results:
        assert "/search?" not in item["url"]
        assert "/preferences" not in item["url"]
        assert "/url?" not in item["url"]


# --- Baidu --------------------------------------------------------------


def test_baidu_unresolved_redirect_is_kept_and_flagged():
    outcome = extract("baidu", "baidu_results.html")
    first = outcome.results[0]
    assert first["url"].startswith("http://www.baidu.com/link?url=")
    assert first.get("urlPending") is True
    # 目标地址未知时不许编来源。
    assert first["source"] == ""


def test_baidu_separates_ads_and_marks_special_cards():
    outcome = extract("baidu", "baidu_results.html")
    assert outcome.sponsored == 1
    assert outcome.dropped == 1
    types = {item["title"]: item["type"] for item in outcome.results}
    assert types["哔哩哔哩_百度百科"] == "special"
    assert [item["rank"] for item in outcome.results] == list(range(1, len(outcome.results) + 1))
    assert outcome.duplicate == 1


def test_baidu_block_page_is_detected_as_captcha():
    adapter = adapters.get("baidu")
    page_text = dom.parse(fixture("baidu_blocked.html")).text
    assert adapter.detect_block("https://www.baidu.com/s?wd=bilibili", "百度安全验证", page_text) == "captcha"
    # 正常结果页不能误判成受阻。
    normal = dom.parse(fixture("baidu_results.html")).text
    assert adapter.detect_block(BASE_URL["baidu"], "哔哩哔哩_百度搜索", normal) == ""


# --- 通用层 --------------------------------------------------------------


def test_query_is_passed_through_whole_without_splitting():
    query = "如何在 Sunday 里用内置浏览器搜索长篇中文句子并且不丢词"
    for name in adapters.SUPPORTED:
        adapter = adapters.get(name)
        built = adapter.build_query(query, page=1, type_="web")
        # 解回查询参数，必须与用户原话逐字相同（不切词、不改写、不截断）。
        fields = dict(parse_qsl(urlsplit(built).query, keep_blank_values=True))
        carried = fields.get("q") or fields.get("wd") or fields.get("word") or ""
        assert carried == query, f"{name} 把查询改坏了：{built}"


def test_pagination_advances_page_parameters():
    for name in adapters.SUPPORTED:
        adapter = adapters.get(name)
        first = adapter.build_query("bilibili", page=1)
        second = adapter.build_query("bilibili", page=2)
        assert first != second
        assert adapter.next_page_url(first, 2) == second, f"{name} 分页参数不一致"


def test_url_cleaning_never_touches_unknown_parameters():
    url = "https://shop.example.com/item?id=42&sig=ab%2Fcd&utm_source=x&gclid=y#reviews"
    cleaned = urls.clean(url)
    assert "id=42" in cleaned and "sig=ab%2Fcd" in cleaned
    assert "utm_source" not in cleaned and "gclid" not in cleaned
    assert cleaned.endswith("#reviews")
    assert urls.dedupe_key("https://example.com/a/?utm_source=x") == urls.dedupe_key("https://example.com/a")


def test_dedupe_key_keeps_distinct_pages_apart():
    assert urls.dedupe_key("https://example.com/a") != urls.dedupe_key("https://example.com/b")
    assert urls.dedupe_key("https://example.com/a?id=1") != urls.dedupe_key("https://example.com/a?id=2")


def test_text_normalization_keeps_numbers_and_dates_untouched():
    raw = "  哔哩哔哩\u200b  \n\n  2024-05-01 · 1.2万次播放 \u00a0 "
    cleaned = text_tools.normalize(raw)
    assert cleaned == "哔哩哔哩\n\n2024-05-01 · 1.2万次播放"
    assert text_tools.extract_date("发布于 2024年5月1日") == "2024年5月1日"
    assert text_tools.extract_date("没有日期") == ""


def test_navigation_footer_and_sidebars_never_reach_the_payload():
    outcome = extract("bing", "bing_results.html", include_ads=True)
    blob = " ".join(
        f"{item['title']} {item['snippet']} {item['url']} {item['source']}" for item in outcome.results
    )
    for noise in ("登录", "设置", "隐私", "侧栏推荐", "© 2024 Microsoft"):
        assert noise not in blob, f"页面噪声漏进了结果：{noise}"
    # 卡片 HTML → 结构化字段必须明显变短（方案 §12 的压缩率指标）。
    assert outcome.chars_in > 0 and outcome.chars_out > 0
    assert outcome.compression >= 0.5, outcome.stats()


def test_generic_adapter_recovers_cards_from_container_html():
    container = dom.parse(fixture("bing_results.html"))
    holder = container.first("#b_results")
    assert holder is not None
    outcome = pipeline.extract(
        GENERIC,
        [{"selector": "#b_results", "html": holder.to_html()}],
        base_url=BASE_URL["bing"],
        limit=10,
        mode="l2",
    )
    assert len(outcome.results) >= 3
    assert outcome.results[0]["title"].startswith("哔哩哔哩")
    assert outcome.results[0]["extraction"] == "l2"


def test_article_reader_drops_navigation_and_keeps_structure():
    html = """
    <html><body>
      <header><nav><a href="/a">首页</a><a href="/b">关于</a></nav></header>
      <main>
        <article>
          <h1>Sunday 的内置浏览器</h1>
          <p>第一段：内置浏览器负责取网页。</p>
          <h2>分层</h2>
          <p>第二段：适配器负责理解结果页结构。</p>
          <ul><li>清洗层压缩噪声</li><li>Agent 负责决策</li></ul>
        </article>
      </main>
      <footer>版权所有</footer>
    </body></html>
    """
    payload = reader.read([{"selector": "body", "html": html}], max_chars=400, offset=0)
    texts = [block["text"] for block in payload["blocks"]]
    assert texts[0] == "Sunday 的内置浏览器"
    assert payload["blocks"][0]["level"] == 1
    assert "第二段：适配器负责理解结果页结构。" in texts
    assert all("版权所有" not in text for text in texts)
    assert all("首页" not in text for text in texts)
    assert payload["headings"] == ["Sunday 的内置浏览器", "分层"]


def test_reader_supports_paging_with_offset():
    html = "<html><body><article>" + "".join(
        f"<p>第 {index} 段内容，用来测试分段读取。</p>" for index in range(1, 11)
    ) + "</article></body></html>"
    first = reader.read([{"selector": "body", "html": html}], max_chars=80, offset=0)
    assert first["truncated"] is True
    assert first["nextOffset"] == len(first["blocks"])
    second = reader.read([{"selector": "body", "html": html}], max_chars=80, offset=first["nextOffset"])
    assert second["blocks"][0]["text"] != first["blocks"][0]["text"]


def test_engine_page_detection_uses_url_shape_not_selectors():
    assert adapters.get("bing").detect_page("https://cn.bing.com/search?q=x")
    assert adapters.get("google").detect_page("https://www.google.com/search?q=x")
    assert adapters.get("baidu").detect_page("https://www.baidu.com/s?wd=x")
    assert not adapters.get("baidu").detect_page("https://www.baidu.com/link?url=x")
    assert adapters.detect("https://www.bing.com/search?q=x").name == "bing"


def test_unknown_engine_is_rejected_with_actionable_message():
    with pytest.raises(ValueError) as error:
        adapters.get("yahoo")
    assert "baidu" in str(error.value)


def test_highlighted_query_words_keep_their_position():
    """搜索引擎用 <strong>/<em> 包住命中的词，标题不能被拼成「引擎把查询切了」。"""
    html = """
    <li class="b_algo">
      <h2><a href="https://aiqicha.baidu.com/company_detail_1">北京<strong>中电梧桐</strong>科技有限公司 - 爱企查</a></h2>
      <div class="b_caption"><p>北京<strong>中电梧桐</strong>科技有限公司成立于2017年，做电力综合解决方案。</p></div>
    </li>
    """
    adapter = adapters.get("bing")
    outcome = pipeline.extract(
        adapter,
        [{"selector": "li.b_algo", "html": html}],
        base_url="https://cn.bing.com/search?q=x",
        limit=5,
    )
    assert outcome.results[0]["title"] == "北京中电梧桐科技有限公司 - 爱企查"
    assert "北京中电梧桐科技有限公司" in outcome.results[0]["snippet"]
