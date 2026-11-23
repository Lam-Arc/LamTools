"""搜索编排：开页 → 等待 → 提取（L1→L2→L3）→ 清洗 → 结构化返回。

user:“引擎不可用时可以尝试其他引擎；不因单一引擎失败而直接终止整个搜索任务”+
(所以 `auto` 是一串有序尝试：每一台的失败都记进 diagnostics，拿到确定答案就停)。

user:“默认不使用视觉模型解析搜索结果”+(L3 只把截图落盘并返回路径；
不发图、不发整页，默认路径永远是 L1)。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from .. import agent as browser_agent
from . import adapters, pipeline, sessions, urls
from . import text as text_tools
from .adapters.base import EngineAdapter
from .adapters.generic import GENERIC
from .models import (
    MODE_L1,
    MODE_L2,
    MODE_L3,
    STATUS_BLOCKED,
    STATUS_EMPTY,
    STATUS_FAILED,
    STATUS_OK,
    SearchRequest,
    SearchResponse,
    diagnostic,
)

# 每一步的等待上限（秒）。搜索页比普通页面慢，但也不能无限等。
TIMEOUT_OPEN = 25.0
TIMEOUT_WAIT = 20.0
TIMEOUT_HTML = 30.0
TIMEOUT_SCREENSHOT = 35.0
WAIT_RESULTS_MS = 7000
# 引擎首页的搜索框最多等这么久（首页通常比结果页轻）。
WAIT_SEARCHBOX_MS = 8000
# 加载完成最多再等这么多久：宁可多等 4 秒，也不要拿半张页面去提取。
WAIT_LOAD_MS = 4000
# 专用选择器一条都没命中时，最多重取几次页面、每次等多久。
# 导航后确认页面真的换成新查询：最多等多久、每次间隔多久。
NAVIGATION_TIMEOUT = 5.0
NAVIGATION_POLL = 0.25
EMPTY_RETRIES = 1
# 重取前等多久：Bing 的答案优先版式会先渲染一张导航卡，其余结果随后由 JS 补上。
EMPTY_RETRY_DELAY = 1.2
# 通用兜底至少要有这么多条，否则视为「没找到结果」。
L2_MIN_RESULTS = 2
# 结果与查询词的覆盖率下限：低于它说明搜索引擎按「首词/某个词」做了降级匹配（例如查公司名却返回城市）。
LOW_RELEVANCE = 0.25
# 「一张导航卡」的判定上限：结果不超过这么多条、且几乎全来自同一站点时，
# 引擎其实把查询当成了「去某官网」，并没有在回答查询。
THIN_RESULTS = 3

# 短期缓存：同一查询短时间内重复请求不重复打开页面。
CACHE_TTL = 300.0
CACHE_CAPACITY = 32


class _Cache:
    def __init__(self, ttl: float = CACHE_TTL, capacity: int = CACHE_CAPACITY) -> None:
        self._lock = threading.Lock()
        self._items: dict[tuple, tuple[float, dict]] = {}
        self.ttl = ttl
        self.capacity = capacity

    def get(self, key: tuple) -> dict | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            stamp, value = item
            if time.monotonic() - stamp > self.ttl:
                self._items.pop(key, None)
                return None
            return value

    def put(self, key: tuple, value: dict) -> None:
        with self._lock:
            self._items[key] = (time.monotonic(), value)
            while len(self._items) > self.capacity:
                oldest = min(self._items.items(), key=lambda pair: pair[1][0])[0]
                self._items.pop(oldest, None)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_CACHE = _Cache()


def cache() -> _Cache:
    return _CACHE


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _invoker(call):
    """注入点：真实路径走桌面通道，测试里换成假的宿主。"""

    if call is not None:
        def invoke(command: str, args: dict, timeout: float) -> dict:
            result = call(command, args)
            return result if isinstance(result, dict) else {}

        return invoke

    def invoke(command: str, args: dict, timeout: float) -> dict:
        payload = browser_agent.call(command, args, timeout=timeout)
        return payload if isinstance(payload, dict) else {}

    return invoke


def _field(payload: dict, *names, default=""):
    for name in names:
        if name in payload and payload[name] is not None:
            return payload[name]
    return default


def _page_html(invoke, tab: str, selectors: list[str], *, max_nodes: int, per_node: int = 12000, max_chars: int = 100000, page_text_chars: int = 2000) -> dict:
    return invoke(
        "browser_html",
        {
            "tab": tab,
            "selectors": selectors[:8],
            "maxNodes": max_nodes,
            "perNodeChars": per_node,
            "maxChars": max_chars,
            "pageTextChars": page_text_chars,
        },
        TIMEOUT_HTML,
    )


def _current_url(invoke, tab: str) -> str:
    """只取当前地址：一次最小读取（只要 <title>），别为了看地址把整页 HTML 拖回来。"""
    try:
        page = invoke(
            "browser_html",
            {"tab": tab, "selectors": ["title"], "maxNodes": 1, "perNodeChars": 400, "maxChars": 2000, "pageTextChars": 0},
            TIMEOUT_HTML,
        )
    except browser_agent.BrowserChannelError:
        return ""
    return str(_field(page, "url") or "")


def _await_target_page(invoke, tab: str, target: str, diagnostics: list[dict], engine: str) -> None:
    """user:“查询完整、结果却是上一个词”+(单标签原地导航时，旧页面的结果容器**早就在**，
    于是 wait_for 立刻返回、随后提取到的是上一页的 DOM：地址栏是新查询，内容是旧结果。
    这里按地址确认「页面已经换成这次查询」再继续，确认不了就记一条诊断并照常往下走)。"""
    deadline = time.monotonic() + NAVIGATION_TIMEOUT
    while True:
        current = _current_url(invoke, tab)
        if current and urls.same_query(current, target):
            return
        if time.monotonic() >= deadline:
            diagnostics.append(
                diagnostic(
                    "pageNotReady",
                    f"等了 {NAVIGATION_TIMEOUT:.0f} 秒，页面还停在上一页（{current or '地址为空'}）；这次结果可能来自旧页面",
                    engine=engine,
                    stage="navigate",
                )
            )
            return
        time.sleep(NAVIGATION_POLL)


def _read_answer_block(invoke, tab: str, adapter: EngineAdapter, page_url: str) -> dict | None:
    selectors = [item for item in adapter.answer_selectors if item]
    if not selectors:
        return None
    try:
        block = _page_html(invoke, tab, selectors[:4], max_nodes=2, per_node=6000, max_chars=14000, page_text_chars=0)
    except browser_agent.BrowserChannelError:
        return None
    return pipeline.read_answer(adapter, list(_field(block, "nodes", default=[]) or []), page_url)


def _wait_for_results(invoke, tab: str, adapter: EngineAdapter, diagnostics: list[dict]) -> None:
    # user:“先等结果容器，再等页面加载完”+(结果是 JS 填进容器的：只等容器会在骨架阶段就提取，
    # 专用选择器匹配 0 条，通用兜底就会把词典卡/相关搜索当结果——看起来像「把查询切成了一个字」)。
    kind = "selector" if adapter.wait_selector else "load"
    value = adapter.wait_selector
    try:
        invoke(
            "browser_wait_for",
            {"tab": tab, "kind": kind, "value": value, "state": "present", "timeoutMs": WAIT_RESULTS_MS},
            TIMEOUT_WAIT,
        )
        invoke(
            "browser_wait_for",
            {"tab": tab, "kind": "load", "value": "", "state": "present", "timeoutMs": WAIT_LOAD_MS},
            TIMEOUT_WAIT,
        )
    except browser_agent.BrowserChannelError as error:
        # 容器没等到不等于失败：页面可能改版、也可能已经加载完。记录后继续提取。
        diagnostics.append(
            diagnostic(
                "waitTimeout",
                f"等结果容器超时（{error.code}）：{adapter.wait_selector or '页面加载'}",
                engine=adapter.name,
                stage="wait",
            )
        )


def _next_page(adapter: EngineAdapter, request: SearchRequest) -> dict:
    next_page = request.page + 1
    available = next_page <= 10
    payload: dict = {"page": next_page, "available": available}
    if available:
        try:
            payload["url"] = adapter.build_query(request.query, next_page, request.type, request.freshness)
        except Exception:  # noqa: BLE001 - 分页地址构造失败不影响本次结果
            payload["available"] = False
    return payload


def _relevance(query: str, results: list[dict]) -> float:
    """查询词在结果里被覆盖的比例（CJK 用二元组、英文用整词/字母对）。

    user:“保留完整搜索词”之后还要能发现「引擎没按整句搜」+(Bing 对长中文串会退化成按首词匹配，
    返回的是另一个主题；这个函数只做一件事：让调用方知道「这页其实没回答你」)。
    """
    compact = "".join(char for char in str(query or "").lower() if char.isalnum())
    if len(compact) < 2 or not results:
        return 1.0
    grams = {compact[index:index + 2] for index in range(len(compact) - 1)}
    haystack = "".join(
        (str(item.get("title") or "") + str(item.get("snippet") or "")).lower() for item in results[:5]
    )
    haystack = "".join(char for char in haystack if char.isalnum())
    if not grams or not haystack:
        return 0.0
    return sum(1 for gram in grams if gram in haystack) / len(grams)


def _is_navigation_card(query: str, results: list[dict]) -> bool:
    """结果很少、且几乎全来自同一个站点 —— 引擎把查询当成了「去某个官网」。

    user:“是被分词截断的只剩 DeepSeek 了”+
    (实测：查「DeepSeek 4.2 Flash 发布时间」，Bing 只回一张 deepseek.com 导航卡 +
    一堆站内链接，「发布时间」这层信息完全没被回答；同一个地址在普通浏览器里
    却是 39,300 条正常结果。这种不能当搜索成功，要换引擎再试)。

    单段查询（就是搜一个品牌词）本来就该得到官网，不算降级。
    """
    terms = [item for item in str(query or "").split() if item]
    if len(terms) < 2 or not results or len(results) > THIN_RESULTS:
        return False
    hosts = {
        urls.host_of(str(item.get("originalUrl") or item.get("url") or ""))
        for item in results
    }
    hosts.discard("")
    return len(hosts) <= 1


def _close_stale_search_tabs(invoke, adapter: EngineAdapter, keep: str) -> None:
    """收掉除 keep 之外的 Agent 搜索标签：界面只留最新那一块分屏。

    user:“每次搜索都会单独开一个分屏吗？”+
    (实测：分屏和网页越积越多，界面每次开新网页都要重新布局，越来越慢，最后连指令都超时。
     只留最新一块，用户看到的永远是「这次搜索的结果」)。
    """
    try:
        payload = invoke("browser_tabs", {}, TIMEOUT_OPEN)
    except browser_agent.BrowserChannelError:
        return
    for item in list(payload.get("tabs") or []):
        tab = str(item.get("tab") or "")
        url = str(item.get("url") or "")
        if not tab or tab == keep or not url:
            continue
        if str(item.get("owner") or "") != "agent":
            continue
        host = urls.host_of(url)
        if not any(host == suffix or host.endswith('.' + suffix) for suffix in adapter.hosts):
            continue
        try:
            invoke("browser_close", {"tab": tab}, TIMEOUT_OPEN)
        except browser_agent.BrowserChannelError:
            return


def _reusable_tab(invoke, adapter: EngineAdapter) -> str:
    """找回上一次搜索用的 Agent 标签，能在原地换查询就不要新开一个网页。

    user:“加，但是我好奇为什么你搜和我搜进的网页不一样”+
    (排查实测：每搜一次都新建网页，界面开网页那一下要重新布局、主线程忙好几秒，
     后面的指令就会撞上「桌面应用没有响应这条浏览器指令」；标签越积越多还会越来越慢。
     所以只在 Agent 自己的搜索标签里原地换查询，不碰用户开的标签)。
    """
    try:
        payload = invoke("browser_tabs", {}, TIMEOUT_OPEN)
    except browser_agent.BrowserChannelError:
        return ""
    for item in list(payload.get("tabs") or []):
        if str(item.get("owner") or "") != "agent":
            continue
        url = str(item.get("url") or "")
        if not url:
            continue
        host = urls.host_of(url)
        if any(host == suffix or host.endswith('.' + suffix) for suffix in adapter.hosts):
            return str(item.get("tab") or "")
    return ""


def _type_in_search_box(invoke, tab: str, adapter: EngineAdapter, request: SearchRequest, diagnostics: list) -> bool:
    """在当前页面（引擎首页）的搜索框里输入查询并回车。成功返回 True。"""
    selectors = [item for item in adapter.search_input_selectors if item]
    if not selectors:
        return False
    selector = ", ".join(selectors)
    try:
        invoke(
            "browser_wait_for",
            {"tab": tab, "kind": "selector", "value": selector, "state": "present", "timeoutMs": WAIT_SEARCHBOX_MS},
            TIMEOUT_WAIT,
        )
    except browser_agent.BrowserChannelError as error:
        diagnostics.append(
            diagnostic(
                "searchBoxMissing",
                f"没等到 {adapter.name} 首页的搜索框（{error.code}），退回直接打开结果地址",
                engine=adapter.name,
                stage="navigate",
            )
        )
        return False
    try:
        invoke(
            "browser_act",
            {
                "tab": tab,
                "instruction": {
                    "op": "type",
                    "selector": selector,
                    "text": request.query,
                    "clear": True,
                    "submit": True,
                    # user:“不被分词等异化”+(把表单的 form 字段拨回搜索入口，避免跳进「热门轮播」视图)。
                    **({"formValue": adapter.search_form_value} if adapter.search_form_value else {}),
                },
            },
            TIMEOUT_WAIT,
        )
    except browser_agent.BrowserChannelError as error:
        diagnostics.append(
            diagnostic(
                "searchBoxFailed",
                f"在 {adapter.name} 首页搜索框里提交失败（{error.code}：{error.message}），退回直接打开结果地址",
                engine=adapter.name,
                stage="navigate",
            )
        )
        return False
    return True


def _human_search(invoke, tab: str, adapter: EngineAdapter, request: SearchRequest, diagnostics: list) -> bool:
    """像人一样搜：先回引擎首页，再在它的搜索框里输入查询、回车。

    user:“这个要的不是兜底 而是更好的底层策略，为什么我手动输入就永远不会触发这种分词异常的情况呢？
    如果不行的话，你就模拟手动输入，所有的 API 走我们内置浏览器里面最开始那个新标签页，
    它不是可以更换搜索引擎，然后填入搜索内容点击发送吗？一个搜索慢个秒级是可以接受的”+
    (实测：同一个结果地址，Agent 直接导航拿到的是「只按首词匹配」的降级页——搜
    「DeepSeek 4.2 Flash 发布时间」回了 150,000 条、全是 deepseek.com 官网；
    而人在同一个浏览器里手动进入同一个地址，是 39,300 条正常自然结果。
    所以不再直接撞结果地址，改成复刻真人动作；多花一两秒换正确结果是划算的)。
    """
    if not adapter.home_url or not adapter.search_input_selectors:
        return False
    invoke("browser_nav", {"tab": tab, "action": "navigate", "url": adapter.home_url}, TIMEOUT_WAIT)
    return _type_in_search_box(invoke, tab, adapter, request, diagnostics)


def _attempt(adapter: EngineAdapter, request: SearchRequest, invoke, work_root: str, tab: str = "") -> dict:
    """在一个引擎上完整跑一次：结果拿不到时按 L1→L2→L3 降级，并给出明确状态。"""
    attempt = {
        "engine": adapter.name,
        "tab": "",
        "status": STATUS_FAILED,
        "results": [],
        "mode": MODE_L1,
        "stats": {},
        "pageUrl": "",
        "pageTitle": "",
        "answer": None,
        "screenshot": "",
        "diagnostics": [],
    }
    diagnostics = attempt["diagnostics"]
    query_url = adapter.build_query(request.query, request.page, request.type, request.freshness)
    # user:“开一个分屏，加一个标签页”+(一次搜索只开一个标签：换引擎是**原地导航**，
    # 不是再开一个——否则每台引擎留一个分屏标签，失败的还会变成死标签)。
    # user:“不得无故覆盖用户当前标签页”+(用户中途接管了这个标签，就另开一个去搜)。
    if tab and _owner_of(invoke, tab) != "agent":
        tab = ""
    # user:“你就模拟手动输入，所有的 API 走我们内置浏览器里面最开始那个新标签页”+
    # (优先走真人路径：引擎首页 -> 在它的搜索框里输入 -> 回车；只有拿不到搜索框时才退回
    #  直接打开结果地址。同一条查询，真人路径拿到的是正常自然结果，直接撞地址会被降级)。
    # 只有第 1 页走「首页 -> 搜索框」：引擎的搜索框只能搜第一页，翻页仍然要开分页地址。
    use_human = (
        int(request.page or 1) <= 1
        and bool(adapter.home_url and adapter.search_input_selectors)
    )
    human_search = False
    if tab:
        if use_human:
            human_search = _human_search(invoke, tab, adapter, request, diagnostics)
        if not human_search:
            invoke("browser_nav", {"tab": tab, "action": "navigate", "url": query_url}, 15.0)
    else:
        opened = invoke(
            "browser_open",
            {"url": adapter.home_url if use_human else query_url, "profile": "normal"},
            TIMEOUT_OPEN,
        )
        tab = str(opened.get("tab") or "")
        if use_human and tab:
            human_search = _type_in_search_box(invoke, tab, adapter, request, diagnostics)
            if not human_search:
                invoke("browser_nav", {"tab": tab, "action": "navigate", "url": query_url}, 15.0)
    if not tab:
        raise browser_agent.BrowserChannelError("internal", "浏览器没有返回标签 id，无法继续搜索")
    attempt["tab"] = tab
    attempt["pageUrl"] = query_url

    # user:“查询完整、结果却是上一个词”+(先确认页面已经换成这次查询，再谈提取)。
    _await_target_page(invoke, tab, query_url, diagnostics, adapter.name)
    _wait_for_results(invoke, tab, adapter, diagnostics)

    page = _page_html(
        invoke,
        tab,
        [*adapter.card_selectors, *adapter.container_selectors[:2]],
        max_nodes=request.limit + 6,
        # user:“不被分词等异化”+
        # (实测：命中结果容器时整页只有一份片段，按默认 12000 字符截断就只装得下一条半结果，
        #  于是永远只回 1 条——看起来就像查询被截成首词。容器要按整页给预算)。
        per_node=40000,
        max_chars=150000,
    )
    page_url = str(_field(page, "url", default=query_url) or query_url)
    page_title = str(_field(page, "title") or "")
    page_text = str(_field(page, "pageText", "page_text") or "")
    attempt["pageUrl"] = page_url
    attempt["pageTitle"] = page_title

    skipped = _field(page, "skippedSelectors", "skipped_selectors", default=[]) or []
    if skipped:
        diagnostics.append(
            diagnostic("selectorRejected", f"页面拒收了这些选择器：{', '.join(map(str, skipped))}", engine=adapter.name, stage="extract")
        )
    counts = _field(page, "counts", default={}) or {}
    if isinstance(counts, dict) and counts.get("truncated"):
        diagnostics.append(
            diagnostic("htmlTruncated", "页面片段超出预算被截断，靠后的结果可能缺失", engine=adapter.name, stage="extract")
        )

    blocked = adapter.detect_block(page_url, page_title, page_text)
    if blocked:
        attempt["status"] = STATUS_BLOCKED
        diagnostics.append(
            diagnostic(blocked, "搜索引擎要求人机验证或拒绝了这次访问；不把这一页当作有效结果", engine=adapter.name, stage="detect")
        )
        return attempt

    on_result_page = adapter.detect_page(page_url)
    if not on_result_page:
        diagnostics.append(
            diagnostic("notResultPage", f"打开的页面不像 {adapter.name} 的结果页：{page_url}", engine=adapter.name, stage="detect")
        )

    # user:“加，但是我好奇为什么你搜和我搜进的网页不一样”+(单独抓摘要块：它只在
    # answer-first 版式里出现，不进自然排名；抓不到就是没有，不编)。
    attempt["answer"] = _read_answer_block(invoke, tab, adapter, page_url)
    nodes = _field(page, "nodes", default=[]) or []
    outcome = pipeline.extract(
        adapter,
        list(nodes),
        base_url=page_url,
        limit=request.limit,
        include_ads=request.include_ads,
        requested_type=request.type,
        mode=MODE_L1,
    )
    # user:“结果没渲染完就提取会抓到空壳”+(专用选择器一条都没命中时，先等半秒重取一次；
    # 宁可多花一次 round-trip，也不要拿骨架页去喂通用兜底)。
    # user:“是被分词截断的只剩 DeepSeek 了”+
    # (诊断出的真相：不是引擎把查询拆成了首词，而是抓得太早——Bing 的答案优先版式
    #  先渲染一张「去某官网」的导航卡，把查询里的意图词丢掉，其余自然结果随后由 JS 补上。
    #  所以「条数太少且集中在一个站点」也要重取，不能拿这一张卡当搜索成功)。
    def _too_thin() -> bool:
        if not outcome.results:
            return True
        return len(outcome.results) < THIN_RESULTS and _is_navigation_card(request.query, outcome.results)

    retries = 0
    while _too_thin() and retries < EMPTY_RETRIES:
        retries += 1
        reason = (
            "没提取到结果"
            if not outcome.results
            else f"只提取到 {len(outcome.results)} 条、且都指向同一个站点"
        )
        diagnostics.append(
            diagnostic(
                "emptyRetry",
                f"第 {retries} 次{reason}，等 {int(EMPTY_RETRY_DELAY * 1000)}ms 让页面把结果渲染完再取",
                engine=adapter.name,
                stage="extract",
            )
        )
        time.sleep(EMPTY_RETRY_DELAY)
        page = _page_html(
            invoke,
            tab,
            [*adapter.card_selectors, *adapter.container_selectors[:2]],
            max_nodes=request.limit + 6,
            per_node=40000,
            max_chars=150000,
        )
        page_url = str(_field(page, "url", default=page_url) or page_url)
        nodes = _field(page, "nodes", default=[]) or []
        outcome = pipeline.extract(
            adapter,
            list(nodes),
            base_url=page_url,
            limit=request.limit,
            include_ads=request.include_ads,
            requested_type=request.type,
            mode=MODE_L1,
        )
    attempt["stats"] = outcome.stats()
    # user:“不被分词等异化”+(结果少到不正常时，把「实际取回了哪些片段」记进诊断：
    # 只有看得见选择器命中情况，才能分清是页面变了还是抓早了，而不是继续猜)。
    if len(outcome.results) < THIN_RESULTS:
        hits: dict[str, int] = {}
        for item in nodes:
            key = str(item.get("selector") or "(none)")
            hits[key] = hits.get(key, 0) + 1
        diagnostics.append(
            diagnostic(
                "thinNodes",
                f"取回 {len(nodes)} 个片段（{hits}），清洗后只剩 {len(outcome.results)} 条",
                engine=adapter.name,
                stage="extract",
            )
        )
    if outcome.results:
        attempt.update(status=STATUS_OK, results=outcome.results, mode=MODE_L1)
        attempt["relevance"] = round(_relevance(request.query, outcome.results), 3)
        attempt["weak"] = attempt["relevance"] < LOW_RELEVANCE
        if attempt["weak"]:
            diagnostics.append(
                diagnostic(
                    "lowRelevance",
                    f"结果里只有 {attempt[chr(114) + chr(101) + chr(108) + chr(101) + chr(118) + chr(97) + chr(110) + chr(99) + chr(101)]:.0%} 的查询词被覆盖，"
                    "搜索引擎可能只按其中一部分词匹配了",
                    engine=adapter.name,
                    stage="clean",
                )
            )
        pending = sum(1 for item in outcome.results if item.get("urlPending"))
        if pending:
            diagnostics.append(
                diagnostic("urlPending", f"{pending} 条结果是搜索引擎的中转链接，未能安全解出目标地址", engine=adapter.name, stage="clean")
            )
        return attempt

    # L2：引擎专用结构没命中（改版、A/B、特殊版式）→ 用结构语义重来一次。
    diagnostics.append(
        diagnostic("engineMiss", f"{adapter.name} 的专用结构没提取到结果，改用通用结构识别", engine=adapter.name, stage="extract")
    )
    page2 = _page_html(
        invoke,
        tab,
        list(GENERIC.container_selectors),
        max_nodes=6,
        per_node=40000,
        max_chars=150000,
    )
    page2_url = str(_field(page2, "url", default=page_url) or page_url)
    page2_text = str(_field(page2, "pageText", "page_text") or page_text)
    nodes2 = _field(page2, "nodes", default=[]) or []
    outcome2 = pipeline.extract(
        GENERIC,
        list(nodes2),
        base_url=page2_url,
        limit=request.limit,
        include_ads=request.include_ads,
        requested_type=request.type,
        mode=MODE_L2,
    )
    attempt["mode"] = MODE_L2
    attempt["stats"] = outcome2.stats()
    # user:“失败状态识别 不允许静默伪装成功”+(通用兜底最容易捞到词典卡/相关搜索；
    # 条数太少或摘要普遍为空，就不算「找到了结果」，宁可报失败并换引擎)。
    solid = sum(1 for item in outcome2.results if len(item.get("snippet") or "") >= 20)
    if outcome2.results and (len(outcome2.results) < L2_MIN_RESULTS or solid * 2 < len(outcome2.results)):
        diagnostics.append(
            diagnostic(
                "l2LowConfidence",
                f"通用结构只凑出 {len(outcome2.results)} 条、其中 {solid} 条有摘要，不像搜索结果，放弃这页",
                engine=adapter.name,
                stage="extract",
            )
        )
        outcome2.results = []
    if outcome2.results:
        attempt.update(status=STATUS_OK, results=outcome2.results, pageUrl=page2_url)
        attempt["relevance"] = round(_relevance(request.query, outcome2.results), 3)
        attempt["weak"] = attempt["relevance"] < LOW_RELEVANCE
        diagnostics.append(diagnostic("l2Fallback", f"用通用结构识别到 {len(outcome2.results)} 条结果", engine=adapter.name, stage="extract"))
        return attempt

    if adapter.has_no_results(page2_text or page_text):
        attempt["status"] = STATUS_EMPTY
        diagnostics.append(diagnostic("noResults", "页面明确表示没有匹配结果", engine=adapter.name, stage="detect"))
        return attempt

    # L3：结构化解析都没成 → 留证据（截图落盘），状态明确报失败，不编结果。
    attempt["mode"] = MODE_L3
    diagnostics.append(
        diagnostic("visualFallback", "结构化解析失败，已截图为证；需要时可由模型看截图判断", engine=adapter.name, stage="extract")
    )
    try:
        shot = invoke("browser_screenshot", {"tab": tab, "target": "viewport"}, TIMEOUT_SCREENSHOT)
        data_url = str(_field(shot, "png") or "")
        from ..artifacts import save_png

        path = save_png(work_root, tab, data_url) if data_url else None
        if path is not None:
            attempt["screenshot"] = str(path)
    except browser_agent.BrowserChannelError as error:
        diagnostics.append(diagnostic("screenshotFailed", f"截图失败（{error.code}）：{error.message}", engine=adapter.name, stage="extract"))
    attempt["status"] = STATUS_FAILED
    if not on_result_page:
        diagnostics.append(diagnostic("parseFailed", "页面结构无法识别为搜索结果页", engine=adapter.name, stage="extract"))
    else:
        diagnostics.append(diagnostic("parseFailed", "结果页结构可识别，但提取不出可用结果", engine=adapter.name, stage="extract"))
    return attempt


def _close_superseded(invoke, attempts: list[dict]) -> None:
    """换引擎时把上一条失败的标签关掉，避免一次搜索开出好几个后台标签。

    被拦截的标签保留：用户可能需要在这个页面里自己过验证。
    """
    for attempt in attempts:
        tab = attempt.get("tab")
        if not tab or attempt.get("status") == STATUS_BLOCKED:
            continue
        try:
            invoke("browser_close", {"tab": tab}, 10.0)
        except browser_agent.BrowserChannelError:
            continue


def search(request: SearchRequest, *, call=None, work_root: str = "") -> dict:
    """跑一次搜索，返回统一协议的结构化结果。"""
    started = time.perf_counter()
    invoke = _invoker(call)
    key = request.cache_key()

    cached = None if request.refresh else _CACHE.get(key)
    if cached is not None:
        session = sessions.store().create(request.query, cached.get("engine") or request.engine)
        results = sessions.store().assign(session, list(cached.get("results") or []))
        response = SearchResponse(
            query=request.query,
            engine=str(cached.get("engine") or ""),
            status=str(cached.get("status") or STATUS_OK),
            results=results,
            next_page=dict(cached.get("nextPage") or {}),
            extraction_mode=str(cached.get("extractionMode") or ""),
            answer=cached.get("answer"),
            diagnostics=[diagnostic("cacheHit", f"{int(CACHE_TTL)} 秒内的同一查询直接复用结果；要最新结果请加 refresh")],
            session=session.id,
            tab=str(cached.get("tab") or ""),
            page_url=str(cached.get("pageUrl") or ""),
            page_title=str(cached.get("pageTitle") or ""),
            counts=dict(cached.get("counts") or {}),
            attempts=[],
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            fetched_at=_now_iso(),
            cached=True,
        )
        return response.to_dict()

    attempts: list[dict] = []
    diagnostics: list[dict] = []
    chosen: dict | None = None
    weak_attempt: dict | None = None
    engines = adapters.resolve(request.engine)
    # user:“每次搜索都会单独开一个分屏吗？”+
    # (每次都在一个新的、可见的网页里搜：被收起的标签视口只有 4x4，引擎会按极窄宽度
    #  渲染，结果只剩头部一条——那正是「看起来被截成首词」的现场。所以不复用后台标签，
    #  搜完把上一次的搜索标签收掉，只留最新这一块)。
    shared_tab = ""
    for index, adapter in enumerate(engines):
        try:
            attempt = _attempt(adapter, request, invoke, work_root, tab=shared_tab)
        except browser_agent.BrowserChannelError as error:
            # 通道问题（桌面不在、超时）不是「这台引擎没结果」：换引擎也没用，直接如实抛出。
            if error.code in {"unsupported", "busy"}:
                raise
            diagnostics.append(
                diagnostic(error.code, f"{adapter.name} 执行失败：{error.message}", engine=adapter.name, stage="browser")
            )
            attempts.append({"engine": adapter.name, "status": STATUS_FAILED, "results": 0, "tab": ""})
            continue
        shared_tab = attempt["tab"] or shared_tab
        attempts.append(
            {
                "engine": adapter.name,
                "status": attempt["status"],
                "results": len(attempt["results"]),
                "relevance": attempt.get("relevance"),
                "tab": attempt["tab"],
            }
        )
        diagnostics.extend(attempt["diagnostics"])
        if attempt["status"] == STATUS_EMPTY:
            chosen = attempt
            break
        if attempt["status"] == STATUS_OK:
            if not attempt.get("weak"):
                chosen = attempt
                break
            # 弱匹配：先记着，试下一台；都被降级匹配时才回头用它。
            if weak_attempt is None:
                weak_attempt = attempt
        # 标签是共用的：换引擎直接在同一标签里导航，不关也不重开。
        # (用户的浏览器界面里只会多出一块 agent-browser 分屏 + 一个标签页)。

    if chosen is None and weak_attempt is not None:
        # 所有引擎都只给了局部匹配：如实返回最接近的一份，并明确标注「这不是精确回答」。
        chosen = weak_attempt
        diagnostics = diagnostics + [
            diagnostic(
                "weakMatch",
                "每个引擎都只按查询的一部分匹配，结果是近似相关，不能当成精确命中（建议换更短/更明确的关键词）",
                engine=chosen["engine"],
                stage="clean",
            )
        ]

    if chosen is None:
        status = STATUS_BLOCKED if any(item["status"] == STATUS_BLOCKED for item in attempts) else STATUS_FAILED
        session = sessions.store().create(request.query, request.engine)
        response = SearchResponse(
            query=request.query,
            engine=attempts[-1]["engine"] if attempts else request.engine,
            status=status,
            results=[],
            next_page={"page": request.page + 1, "available": False},
            extraction_mode=MODE_L3 if status == STATUS_FAILED else "",
            diagnostics=diagnostics,
            session=session.id,
            tab=str(attempts[-1].get("tab") or "") if attempts else "",
            counts={"returned": 0},
            attempts=attempts,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            fetched_at=_now_iso(),
        )
        return response.to_dict()

    session = sessions.store().create(request.query, chosen["engine"], chosen["tab"])
    results = sessions.store().assign(session, list(chosen["results"]))
    response = SearchResponse(
        query=request.query,
        engine=chosen["engine"],
        status=chosen["status"],
        results=results,
        next_page=_next_page(adapters.get(chosen["engine"]), request) if results else {"page": request.page + 1, "available": False},
        extraction_mode=chosen["mode"],
        answer=chosen.get("answer"),
        diagnostics=diagnostics,
        session=session.id,
        tab=chosen["tab"],
        page_url=chosen["pageUrl"],
        page_title=chosen["pageTitle"],
        counts={**dict(chosen.get("stats") or {}), "returned": len(results)},
        attempts=attempts,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        fetched_at=_now_iso(),
    )
    # user:“每次搜索都会单独开一个分屏吗？”+
    # (搜完把上一次的搜索标签收掉：界面只留最新那一块，否则每搜一次就多一块分屏，
    #  越积越多、每次开网页都更慢，最后连指令都超时)。
    _close_stale_search_tabs(
        invoke, adapters.get(chosen["engine"]), str(chosen.get("tab") or "")
    )
    payload = response.to_dict()
    _CACHE.put(
        key,
        {
            "engine": payload["engine"],
            "status": payload["status"],
            "results": [dict(item, id="") for item in payload["results"]],
            "nextPage": payload["nextPage"],
            "extractionMode": payload["extractionMode"],
            "answer": payload["answer"],
            "tab": payload["tab"],
            "pageUrl": payload["pageUrl"],
            "pageTitle": payload["pageTitle"],
            "counts": payload["counts"],
        },
    )
    return payload


def _owner_of(invoke, tab: str) -> str:
    """当前标签归谁：「agent」还是「human」。

    user:“不得无故覆盖用户当前标签页”+(用户点过这个网页之后它归人：Agent 只能读，
    再打开别的结果时不能直接把这个标签导航走，要另开一个)。
    """
    try:
        payload = invoke("browser_control", {"tab": tab, "action": "status"}, 8.0)
    except browser_agent.BrowserChannelError:
        return "agent"
    return str(payload.get("owner") or "agent")


def open_result(*, session_id: str, result_id: str = "", url: str = "", call=None, wait_ms: int = 12000) -> dict:
    """通过结果 ID（或显式 URL）打开一条结果，并复用同一个结果标签。"""
    invoke = _invoker(call)
    session = sessions.store().get(session_id)
    target = urls.clean(url) if url else ""
    entry: dict = {}
    if result_id:
        entry = session.results.get(result_id) or {}
        if not entry:
            raise sessions.SessionError(
                f"结果 {result_id} 不在搜索会话 {session.id} 里（会话可能已过期，或这是另一次搜索的结果 ID）"
            )
        target = target or str(entry.get("url") or "")
    if not target:
        raise sessions.SessionError("open_result 需要 resultId 或 url")

    tab = session.result_tab
    # user:“如果这个标签页我人为操作后，agent再获取时是跟着我走的吗？”+
    # (页面本身跟着用户走；但「打开另一条结果」不能顺带把用户正在看的页面导航走：
    #  归属是人时另开一个标签，原来的页面原样留着)。
    if tab and _owner_of(invoke, tab) != "agent":
        tab = ""
    reused = bool(tab)
    if reused:
        try:
            invoke("browser_nav", {"tab": tab, "action": "navigate", "url": target}, 15.0)
        except browser_agent.BrowserChannelError as error:
            if error.code != "tab_not_found":
                raise
            reused = False
    if not reused:
        opened = invoke("browser_open", {"url": target, "profile": "normal"}, TIMEOUT_OPEN)
        tab = str(opened.get("tab") or "")
        if not tab:
            raise browser_agent.BrowserChannelError("internal", "浏览器没有返回标签 id")
        sessions.store().set_result_tab(session, tab)

    try:
        invoke("browser_wait_for", {"tab": tab, "kind": "load", "value": "", "state": "present", "timeoutMs": wait_ms}, TIMEOUT_WAIT)
        loaded = True
    except browser_agent.BrowserChannelError:
        loaded = False

    return {
        "session": session.id,
        "resultId": result_id,
        "tab": tab,
        "url": target,
        "title": str(entry.get("title") or ""),
        "reusedTab": reused,
        "loaded": loaded,
        "next": "用 browser.read_page 读这一页的正文；需要结构或截图时用 browser.inspect_page",
        "trust": "untrusted",
        "source": "web",
    }


def summarize(text: str, limit: int = 160) -> str:
    """给日志/诊断用的一行摘要。"""
    return text_tools.clip(text_tools.one_line(text), limit)
