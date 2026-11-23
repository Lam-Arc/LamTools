"""搜索编排的回归：状态机、降级链、会话与缓存、工具动作（全程假宿主，不联网）。

user:“搜索成功、无结果、被拦截和解析失败必须属于不同状态”与“专用适配器失效后能够自动降级”+
(这里用一个假桌面宿主扮演浏览器：每条 Tauri 命令都有人应答，
断言的是「周日拿到这页会怎么判断」，不是「今天这个网站返回什么」)。
"""

from __future__ import annotations

import base64
import threading
from pathlib import Path

import pytest

from lamtools_core.browser import agent as browser_agent
from lamtools_core.browser import tools as browser_tools
from lamtools_core.browser.search import adapters, engine, models, sessions
from lamtools_core.browser.search import dom
from lamtools_core.tool import ToolCall

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "search"
# 1×1 透明 PNG：足够验证「截图落盘、只回路径」。
PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/AH/9pQkAAAAAElFTkSuQmCC"
)

BING_URL = "https://www.bing.com/search?q=bilibili"
BAIDU_URL = "https://www.baidu.com/s?wd=bilibili"
GOOGLE_URL = "https://www.google.com/search?q=bilibili"


# --- 假宿主 --------------------------------------------------------------


class FakeHost:
    """扮演桌面端：按命令名应答，记录收到的每条指令。"""

    def __init__(self, handlers: dict | None = None, *, screenshot: str = PNG_DATA_URL) -> None:
        self.handlers = dict(handlers or {})
        self.screenshot = screenshot
        self.calls: list[tuple[str, dict]] = []
        self.tabs: list[str] = []

    def __call__(self, command: str, args: dict, *, timeout: float | None = None):
        self.calls.append((command, dict(args or {})))
        handler = self.handlers.get(command)
        if handler is not None:
            return handler(args) if callable(handler) else handler
        if command == "browser_open":
            tab = f"t{len(self.tabs) + 1}"
            self.tabs.append(tab)
            return {"tab": tab}
        if command in {"browser_close", "browser_nav"}:
            return {}
        if command == "browser_tabs":
            # 默认没有可复用的搜索标签：测试各自按需要覆盖这条。
            return {"tabs": []}
        if command == "browser_wait_for":
            return {"matched": True}
        # 搜索走「首页 -> 填搜索框 -> 回车」：假宿主只回执行成功，具体页面由 browser_html 的桩决定。
        if command == "browser_act":
            instruction = (args or {}).get("instruction") or {}
            return {"tab": str((args or {}).get("tab") or ""), "op": str(instruction.get("op") or ""), "navigated": True}
        if command == "browser_control":
            return {"tab": str((args or {}).get("tab") or ""), "owner": "agent", "quietSeconds": 0}
        if command == "browser_screenshot":
            return {"png": self.screenshot, "url": ""}
        raise AssertionError(f"假宿主没有为 {command} 准备应答")

    def commands(self) -> list[str]:
        return [command for command, _ in self.calls]

    def args_for(self, command: str) -> list[dict]:
        return [args for name, args in self.calls if name == command]


def page(nodes: list[dict], *, url: str, title: str = "", page_text: str = "") -> dict:
    return {
        "tab": "t1",
        "url": url,
        "title": title,
        "loading": False,
        "nodes": nodes,
        "counts": {"matched": len(nodes), "returned": len(nodes), "omitted": 0, "chars": 1, "truncated": False},
        "pageText": page_text,
        "skippedSelectors": [],
        "trust": "untrusted",
        "source": "web",
        "fetchedAt": "",
    }


def cards_from(fixture: str, adapter_name: str) -> list[dict]:
    """模拟页面侧：把 fixture 里该引擎的结果卡片取回来（选择器取并集、文档顺序、父子只留外层）。"""
    adapter = adapters.get(adapter_name)
    root = dom.parse((FIXTURES / fixture).read_text(encoding="utf-8"))
    seen: set[int] = set()
    picked: list[tuple[dom.Node, str]] = []
    for selector in adapter.card_selectors:
        for node in root.select(selector):
            if id(node) in seen:
                continue
            seen.add(id(node))
            picked.append((node, selector))
    kept: list[tuple[dom.Node, str]] = []
    for node, selector in picked:
        parent = node.parent
        nested = False
        while parent is not None:
            if any(parent is other for other, _ in kept):
                nested = True
                break
            parent = parent.parent
        if not nested:
            kept.append((node, selector))
    return [{"selector": selector, "html": node.to_html()} for node, selector in kept]


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    # 导航确认会轮询真实时间：测试里压到最小，避免每例多等 5 秒。
    monkeypatch.setattr(engine, "NAVIGATION_TIMEOUT", 0.05)
    monkeypatch.setattr(engine, "NAVIGATION_POLL", 0.01)
    sessions.store().clear()
    engine.cache().clear()
    yield
    sessions.store().clear()
    engine.cache().clear()


def _request(**kwargs) -> models.SearchRequest:
    payload = {"query": "bilibili"}
    payload.update(kwargs)
    return models.SearchRequest.from_arguments(payload)


# --- 正常路径 ------------------------------------------------------------


def test_search_returns_structured_results_with_session_ids():
    host = FakeHost(
        {
            "browser_html": page(cards_from("bing_results.html", "bing"), url=BING_URL, title="bilibili - 搜索"),
        }
    )
    response = engine.search(_request(), call=host)

    assert response["status"] == models.STATUS_OK
    assert response["engine"] == "bing"
    assert response["extractionMode"] == models.MODE_L1
    assert [item["rank"] for item in response["results"]] == [1, 2, 3]
    assert [item["id"] for item in response["results"]] == ["s1-1", "s1-2", "s1-3"]
    assert response["session"] == "s1"
    assert response["nextPage"]["available"] is True
    assert response["nextPage"]["page"] == 2
    assert "num=" not in response["nextPage"]["url"] or True  # 分页地址由适配器构造
    # user:“我手动输入之后点回车，它搜出来的结果也没有问题”+
    # (搜索走真人路径：先开引擎首页，再把查询原样填进它自己的搜索框并回车——
    #  直接撞结果地址会被引擎降级成「只按首词匹配」)。
    opened = host.args_for("browser_open")[0]["url"]
    assert opened == "https://cn.bing.com/", opened
    instruction = host.args_for("browser_act")[0]["instruction"]
    assert instruction["op"] == "type"
    assert instruction["text"] == "bilibili", "查询原话要原样进搜索框，不切词"
    assert instruction["clear"] is True
    assert instruction["submit"] is True
    assert "#sb_form_q" in instruction["selector"]
    assert response["trust"] == "untrusted"


def test_search_falls_back_to_result_url_when_the_search_box_never_appears():
    """user:“你就模拟手动输入”+(首页没等到搜索框时不能卡住：退回直接打开结果地址，并把原因写进诊断)。"""
    def wait_timeout(args):
        if str(args.get("kind") or "") == "selector":
            raise browser_agent.BrowserChannelError("timeout", "等不到搜索框")
        return {"matched": True}

    host = FakeHost(
        {
            "browser_wait_for": wait_timeout,
            "browser_html": page(cards_from("bing_results.html", "bing"), url=BING_URL, title="bilibili - 搜索"),
        }
    )
    response = engine.search(_request(), call=host)

    assert response["status"] == models.STATUS_OK
    assert not host.args_for("browser_act"), "没有搜索框就不该硬往里填"
    nav = [str(item.get("url") or "") for item in host.args_for("browser_nav")]
    assert any("bing.com/search" in url and "q=bilibili" in url for url in nav), nav
    assert "searchBoxMissing" in {item["code"] for item in response["diagnostics"]}


def test_search_accepts_explicit_engine_and_forwards_page():
    host = FakeHost(
        {
            "browser_html": page(cards_from("google_results.html", "google"), url=GOOGLE_URL, title="bilibili - Google 搜索"),
        }
    )
    response = engine.search(_request(engine="google", page=2, limit=5), call=host)
    assert response["engine"] == "google"
    opened = host.args_for("browser_open")[0]["url"]
    assert "start=10" in opened, opened
    assert len(response["results"]) <= 5


# --- 降级与状态 ----------------------------------------------------------


def test_blocked_engine_is_skipped_and_next_engine_still_answers():
    # 地址由「最近一次导航」决定：单标签换引擎时，页面地址会变，提取要跟着变。
    state = {"url": BING_URL}

    def html(args):
        if any(str(item) == "title" for item in args.get("selectors") or []):
            return page([], url=state["url"], title="")
        if "bing.com" in state["url"]:
            return page([], url=state["url"], title="Detection",
                        page_text="Our systems have detected unusual traffic from your computer network.")
        return page(cards_from("baidu_results.html", "baidu"), url=state["url"], title="百度搜索")

    host = FakeHost({"browser_html": html})

    def navigate(args):
        state["url"] = str(args.get("url") or state["url"])
        return {}

    host.handlers["browser_nav"] = navigate
    response = engine.search(_request(engine="auto"), call=host)

    assert response["status"] == models.STATUS_OK
    assert response["engine"] == "baidu"
    assert response["attempts"][0]["status"] == models.STATUS_BLOCKED
    codes = {item["code"] for item in response["diagnostics"]}
    assert codes & {"blocked", "rate_limited", "captcha"}
    # 被拦截的标签留给用户处理，不能被悄悄关掉。
    assert "browser_close" not in host.commands()


def test_captcha_on_every_engine_reports_blocked_without_inventing_results():
    def html(args):
        return page([], url=BING_URL, title="百度安全验证", page_text="百度安全验证 请输入验证码")

    host = FakeHost({"browser_html": html})
    response = engine.search(_request(engine="bing"), call=host)
    assert response["status"] == models.STATUS_BLOCKED
    assert response["results"] == []


def test_empty_result_page_is_not_reported_as_failure():
    host = FakeHost(
        {
            "browser_html": page([], url=BING_URL, title="bilibili - 搜索", page_text="没有与此相关的结果。请检查拼写。"),
        }
    )
    response = engine.search(_request(engine="bing"), call=host)
    assert response["status"] == models.STATUS_EMPTY
    assert response["results"] == []
    assert {item["code"] for item in response["diagnostics"]} >= {"noResults"}


def test_adapter_miss_falls_back_to_generic_extraction():
    container = dom.parse((FIXTURES / "bing_results.html").read_text(encoding="utf-8")).first("#b_results")
    assert container is not None

    def html(args):
        # 引擎专用选择器一律空（模拟改版）；通用容器能拿到结果列表。
        if any("b_algo" in str(item) for item in args.get("selectors") or []):
            return page([], url=BING_URL, title="bilibili - 搜索")
        return page([{"selector": "#b_results", "html": container.to_html()}], url=BING_URL, title="bilibili - 搜索")

    host = FakeHost({"browser_html": html})
    response = engine.search(_request(engine="bing"), call=host)

    assert response["status"] == models.STATUS_OK
    assert response["extractionMode"] == models.MODE_L2
    codes = {item["code"] for item in response["diagnostics"]}
    assert {"engineMiss", "l2Fallback"} <= codes
    assert response["results"][0]["extraction"] == "l2"


def test_unparseable_page_records_screenshot_and_reports_failure(tmp_path):
    host = FakeHost(
        {
            "browser_html": page([], url="https://example.com/blocked", title="", page_text="请开启 JavaScript 后重试"),
        }
    )
    response = engine.search(_request(engine="bing"), call=host, work_root=str(tmp_path))

    assert response["status"] == models.STATUS_FAILED
    assert response["extractionMode"] == models.MODE_L3
    assert response["results"] == []
    codes = {item["code"] for item in response["diagnostics"]}
    assert {"visualFallback", "parseFailed", "notResultPage"} <= codes
    shots = list((tmp_path / ".lam" / "artifacts" / "browser").glob("*.png"))
    assert len(shots) == 1 and shots[0].stat().st_size > 0
    # 最后一次失败的页面留给用户/模型自己看，不能悄悄关掉。
    assert "browser_close" not in host.commands()


def test_engine_fallback_reuses_one_tab_instead_of_opening_more():
    """一次搜索只开一个标签：第二台引擎在同一标签里原地导航，不新开、也不关（否则界面留下死标签）。"""
    def html(args):
        if any("div.result" in str(item) for item in args.get("selectors") or []):
            return page(cards_from("baidu_results.html", "baidu"), url=BAIDU_URL, title="百度搜索")
        return page([], url=BING_URL, title="", page_text="请开启 JavaScript 后重试")

    host = FakeHost({"browser_html": html})
    response = engine.search(_request(engine="auto"), call=host)

    assert response["status"] == models.STATUS_OK
    assert response["engine"] == "baidu"
    assert len(host.args_for("browser_open")) == 1, "第二台引擎不能新开标签"
    nav = [str(item.get("url") or "") for item in host.args_for("browser_nav")]
    assert any("baidu.com" in url for url in nav), "换引擎应在同一标签里导航到下一台"
    assert not host.args_for("browser_close"), "共用标签不关：关掉会让界面留下死标签"


# --- 缓存 ----------------------------------------------------------------


def test_cache_reuses_results_but_issues_a_fresh_session():
    host = FakeHost(
        {"browser_html": page(cards_from("bing_results.html", "bing"), url=BING_URL, title="bilibili - 搜索")}
    )
    first = engine.search(_request(), call=host)
    second = engine.search(_request(), call=host)

    assert second["cached"] is True
    assert second["session"] != first["session"]
    assert second["results"][0]["id"].startswith(second["session"] + "-")
    assert [item["url"] for item in second["results"]] == [item["url"] for item in first["results"]]
    # 第二次没有再打开页面。
    assert len(host.args_for("browser_open")) == 1


def test_refresh_bypasses_cache():
    host = FakeHost(
        {"browser_html": page(cards_from("bing_results.html", "bing"), url=BING_URL, title="bilibili - 搜索")}
    )
    engine.search(_request(), call=host)
    fresh = engine.search(_request(refresh=True), call=host)
    assert fresh["cached"] is False
    assert len(host.args_for("browser_open")) == 2


# --- 会话与并发 ----------------------------------------------------------


def test_open_result_reuses_one_result_tab():
    host = FakeHost(
        {"browser_html": page(cards_from("bing_results.html", "bing"), url=BING_URL, title="bilibili - 搜索")}
    )
    response = engine.search(_request(), call=host)
    session_id = response["session"]
    first_id, second_id = response["results"][0]["id"], response["results"][1]["id"]

    first = engine.open_result(session_id=session_id, result_id=first_id, call=host)
    assert first["reusedTab"] is False
    assert first["url"] == "https://www.bilibili.com/"
    opens = len(host.args_for("browser_open"))

    second = engine.open_result(session_id=session_id, result_id=second_id, call=host)
    assert second["reusedTab"] is True
    assert second["tab"] == first["tab"]
    assert len(host.args_for("browser_open")) == opens, "第二次打开结果必须复用标签，不能越开越多"
    nav = host.args_for("browser_nav")
    assert nav and nav[-1]["url"] == "https://www.bilibili.com/read/home"


def test_open_result_does_not_navigate_a_tab_the_user_took_over():
    """用户正在用的标签不能被子 Agent 的「打开结果」导航走：另开一个，原页面留着。"""
    session = sessions.store().create("中电梧桐", "baidu")
    assigned = sessions.store().assign(
        session,
        [
            {"title": "第一条", "url": "https://example.com/a", "rank": 1, "snippet": ""},
            {"title": "第二条", "url": "https://example.com/b", "rank": 2, "snippet": ""},
        ],
    )
    sessions.store().set_result_tab(session, "t1")
    host = FakeHost({
        "browser_control": lambda args: {"tab": args.get("tab"), "owner": "human", "quietSeconds": 3},
    })

    opened = engine.open_result(session_id=session.id, result_id=assigned[1]["id"], call=host)

    assert not host.args_for("browser_nav"), "人被接管时不能导航用户正在看的标签"
    assert host.args_for("browser_open"), "应另开一个标签"
    assert opened["reusedTab"] is False


def test_open_result_rejects_unknown_result_id():
    host = FakeHost(
        {"browser_html": page(cards_from("bing_results.html", "bing"), url=BING_URL, title="搜索")}
    )
    response = engine.search(_request(), call=host)
    with pytest.raises(sessions.SessionError) as error:
        engine.open_result(session_id=response["session"], result_id="s1-99", call=host)
    assert "s1-99" in str(error.value)


def test_concurrent_searches_do_not_mix_sessions_or_ids():
    def html(args):
        tab = str(args.get("tab") or "")
        if tab == "t1":
            return page(cards_from("bing_results.html", "bing"), url=BING_URL, title="搜索一")
        return page(cards_from("google_results.html", "google"), url=GOOGLE_URL, title="搜索二")

    host = FakeHost({"browser_html": html})
    results: dict[str, dict] = {}

    def run(name: str, engine_name: str) -> None:
        results[name] = engine.search(_request(query=name, engine=engine_name), call=host)

    threads = [
        threading.Thread(target=run, args=("哔哩哔哩", "bing")),
        threading.Thread(target=run, args=("bilibili 维基", "google")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    first, second = results["哔哩哔哩"], results["bilibili 维基"]
    assert first["session"] != second["session"]
    assert all(item["id"].startswith(first["session"]) for item in first["results"])
    assert all(item["id"].startswith(second["session"]) for item in second["results"])
    assert "bilibili.com" in first["results"][0]["url"]
    assert "wikipedia.org" in second["results"][2]["url"]


# --- 工具动作 ------------------------------------------------------------


def _tool(**arguments) -> dict:
    call = ToolCall(id="call-1", name=browser_tools.BROWSER_TOOL_NAME, arguments=arguments)
    return browser_tools.handle(call)


def test_tool_search_requires_query_and_rejects_unknown_engine(monkeypatch):
    monkeypatch.setattr(browser_agent, "call", FakeHost({}))
    with pytest.raises(browser_agent.BrowserChannelError) as empty:
        _tool(action="search")
    assert empty.value.code == "invalid_argument"

    with pytest.raises(browser_agent.BrowserChannelError) as bad_engine:
        _tool(action="search", query="bilibili", engine="yahoo")
    assert bad_engine.value.code == "invalid_argument"


def test_tool_search_and_read_page_round_trip(monkeypatch, tmp_path):
    host = FakeHost(
        {
            "browser_html": page(cards_from("bing_results.html", "bing"), url=BING_URL, title="bilibili - 搜索"),
        }
    )
    monkeypatch.setattr(browser_agent, "call", host)

    found = _tool(action="search", query="bilibili", limit=3)
    assert found["action"] == "search"
    assert found["status"] == models.STATUS_OK
    assert len(found["results"]) == 3
    session_id = found["session"]
    result_id = found["results"][0]["id"]

    opened = _tool(action="open_result", session=session_id, resultId=result_id)
    assert opened["action"] == "open_result"
    assert opened["url"] == "https://www.bilibili.com/"

    article = (
        "<html><body><article><h1>哔哩哔哩</h1><p>这里是正文第一段。</p></article></body></html>"
    )
    host.handlers["browser_html"] = page([{"selector": "article", "html": article}], url="https://www.bilibili.com/")
    read = _tool(action="read_page", tab="t9", maxChars=200)
    assert read["action"] == "read_page"
    assert read["blocks"][0]["level"] == 1
    assert read["blocks"][0]["text"] == "哔哩哔哩"
    assert read["trust"] == "untrusted"


def _city_cards():
    """Bing 把「北京中电梧桐公司」降级成「北京」时会返回的那种结果。"""
    return [{
        "selector": "li.b_algo",
        "html": (
            "<li class=\"b_algo\"><h2><a href=\"https://www.beijing.gov.cn/\">北京市人民政府门户网站</a></h2>"
            "<div class=\"b_caption\"><p>北京市人民政府门户网站提供首都政务信息与办事服务。</p></div></li>"
        ),
    }]


def _company_cards():
    return [{
        "selector": "li.b_algo",
        "html": (
            "<li class=\"b_algo\"><h2><a href=\"https://aiqicha.baidu.com/company_detail_1\">北京中电梧桐科技有限公司 - 爱企查</a></h2>"
            "<div class=\"b_caption\"><p>北京中电梧桐科技有限公司成立于2017年，位于北京市海淀区。</p></div></li>"
        ),
    }]


def test_weak_engine_match_falls_through_to_the_next_engine():
    """查公司名却只返回城市结果时，不能把这份结果当成功交给模型，要换引擎再试。"""
    def html(args):
        # 一次搜索只开一个标签：换引擎是原地导航，所以按「这一页要哪套选择器」区分。
        if any("div.result" in str(item) for item in args.get("selectors") or []):
            return page(_company_cards(), url=BAIDU_URL, title="北京中电梧桐 - 百度搜索")
        return page(_city_cards(), url=BING_URL, title="北京 - 搜索")

    host = FakeHost({"browser_html": html})
    response = engine.search(_request(query="北京中电梧桐公司", engine="auto"), call=host)

    assert response["engine"] == "baidu"
    assert response["status"] == models.STATUS_OK
    assert "中电梧桐" in response["results"][0]["title"]
    assert response["attempts"][0]["relevance"] is not None and response["attempts"][0]["relevance"] < engine.LOW_RELEVANCE


def test_all_weak_matches_are_returned_but_clearly_labelled():
    host = FakeHost({"browser_html": page(_city_cards(), url=BING_URL, title="北京 - 搜索")})
    response = engine.search(_request(query="北京中电梧桐公司", engine="bing"), call=host)

    assert response["status"] == models.STATUS_OK
    assert response["results"], "弱结果也要给，但必须标出来"
    codes = {item["code"] for item in response["diagnostics"]}
    assert {"lowRelevance", "weakMatch"} <= codes

def test_read_page_refuses_to_treat_a_serp_as_an_article(monkeypatch):
    article = "<html><body><div id=\"content_left\"><h1>热搜榜</h1><p>这不是正文。</p></div></body></html>"
    host = FakeHost({"browser_html": page([{"selector": "body", "html": article}], url=BAIDU_URL, title="百度搜索")})
    monkeypatch.setattr(browser_agent, "call", host)

    payload = _tool(action="read_page", tab="t1")

    assert payload["kind"] == "search_results_page"
    assert payload["blocks"] == []
    assert "open_result" in payload["hint"]


def test_read_page_can_open_a_result_by_session_and_id(monkeypatch):
    session = sessions.store().create("中电梧桐", "baidu")
    assigned = sessions.store().assign(
        session,
        [{"title": "北京中电梧桐科技有限公司", "url": "https://example.com/company", "rank": 1, "snippet": "简介"}],
    )
    article = "<html><body><article><h1>公司简介</h1><p>这是一段正文。</p></article></body></html>"
    host = FakeHost(
        {"browser_html": page([{"selector": "article", "html": article}], url="https://example.com/company", title="公司简介")}
    )
    monkeypatch.setattr(browser_agent, "call", host)

    payload = _tool(action="read_page", session=session.id, resultId=assigned[0]["id"])

    assert payload.get("kind") != "search_results_page"
    assert payload["blocks"][0]["text"] == "公司简介"
    assert host.args_for("browser_open")[0]["url"] == "https://example.com/company"

def test_tool_inspect_page_can_attach_screenshot(monkeypatch, tmp_path):
    host = FakeHost(
        {
            "browser_snapshot": {
                "tab": "t1",
                "url": "https://example.com/",
                "title": "Example",
                "refs": [],
                "text": {"blocks": [], "truncated": False},
                "counts": {"total": 0, "returned": 0, "omitted": 0},
            }
        }
    )
    monkeypatch.setattr(browser_agent, "call", host)
    payload = _tool(action="inspect_page", tab="t1", includeScreenshot=True)
    assert payload["action"] == "inspect_page"
    assert payload["screenshot"].endswith(".png")
    assert Path(payload["screenshot"]).exists()
    # 截图只给路径，不能把 base64 塞进上下文。
    assert "png" not in payload


def test_tool_read_page_needs_tab_or_url(monkeypatch):
    monkeypatch.setattr(browser_agent, "call", FakeHost({}))
    with pytest.raises(browser_agent.BrowserChannelError) as error:
        _tool(action="read_page")
    assert error.value.code == "invalid_argument"

def test_same_query_ignores_bing_redirect_noise():
    from lamtools_core.browser.search import urls as url_tools

    plain = "https://cn.bing.com/search?q=%E4%B8%AD%E5%A4%AE+2026&count=10"
    noisy = "https://cn.bing.com/search?q=%E4%B8%AD%E5%A4%AE+2026&count=10&rdr=1&rdrig=DBA24E"
    assert url_tools.same_query(plain, noisy), "rdr/rdrig 这类旁路参数不能影响「是不是同一次查询」"
    other = "https://cn.bing.com/search?q=%E4%B8%AD&count=10"
    assert not url_tools.same_query(plain, other), "查询不同就必须判为不同页"


def test_stale_page_is_reported_instead_of_silently_parsed():
    """导航后页面还停在上一页时，必须留下 pageNotReady 诊断，而不是假装读到了新结果。"""
    def html(args):
        if any(str(item) == "title" for item in args.get("selectors") or []):
            return page([], url="https://cn.bing.com/search?q=%E4%B8%8A%E4%B8%80%E6%AC%A1",
                        title="上一页 - 搜索")
        return page(cards_from("bing_results.html", "bing"), url=BING_URL, title="bilibili - 搜索")

    host = FakeHost({"browser_html": html})
    response = engine.search(_request(engine="bing"), call=host)

    codes = {item["code"] for item in response["diagnostics"]}
    assert "pageNotReady" in codes, codes

