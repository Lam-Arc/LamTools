# Web Search 模块调研报告（国内方案：百度 / Bing 中文）

> 分支：`feature/web-search`
> 日期：2026-08-10
> 目标：为 LamTools Core 的 `web_search` 工具找一个（或一类）国内可达、可维护的开源检索方案，
> 并按"内核可替换"的模块化架构落地。

---

## 0. 背景与现状（为什么不是从零开始）

LamTools Core 工具系统里 **`web_search` 工具已经存在**，但被默认禁用
（`core/src/lamtools_core/tool/default_toolbox.py`）：

```python
# FIXME: web_search 暂不上线（bug 较多），默认禁用
self.disabled_tools.add("web_search")
```

现有实现（`core/src/lamtools_core/tool/web_tools.py` 的 `make_web_search_handler`）：

- **硬编码 DuckDuckGo HTML 端点** `https://html.duckduckgo.com/html/`；
- 依赖 DDG 的 `result__a` / `result__snippet` 页面结构与正则解析；
- **国内不可达 / 不稳定**——这正是"bug 较多"和此前禁用的核心理由。

所以本次任务本质是：**用一个可替换内核的架构替换掉硬编码的 DDG 实现**，并让
国内可达的搜索引擎（百度、Bing 中文）作为默认内核。

---

## 1. 候选开源项目调研

### 1.1 python-baidusearch（百度专用）

| 项 | 值 |
|---|---|
| 仓库 | https://github.com/amazingcoderpro/python-baidusearch |
| 协议 | MIT |
| 星数 | ~163 |
| 方式 | requests + BeautifulSoup 爬百度搜索结果页 HTML |

**实现要点**（源码已核实）：
- 请求 `https://www.baidu.com/s?ie=utf-8&tn=baidu&wd=<kw>`；
- 解析 `#content_left` 下 `.c-container`（`c-container` / `result-op` / `xpath-log` 等模板类名）；
- 摘要截断 300 字；支持翻页（`a.n` 下一页按钮）；
- 纯库，无 API key、无外部服务依赖。

**评价**：
- ✅ 国内可达、结构直观、无 key；
- ⚠️ 深度绑定百度 HTML DOM，百度改版即失效；
- ⚠️ 依赖 `lxml` / `bs4`（当前项目未必已引入）；
- ⚠️ 作者自述"过度使用会被封 IP，建议间隔 15s"。

### 1.2 SearXNG（元搜索引擎，⭐35k）——**重点参考对象**

| 项 | 值 |
|---|---|
| 仓库 | https://github.com/searxng/searxng |
| 协议 | AGPL-3.0 |
| 方式 | 自托管元搜索，内置多个引擎实现 |

**内置 `searx/engines/baidu.py`（源码已核实）——百度官方 JSON 接口**：

```
GET https://www.baidu.com/s
  ?wd=<query>
  &rn=10
  &pn=<page-1>*10
  &tn=json          # ← 关键：百度隐藏 JSON API，无需 key
```

- 响应 `data.feed.entry[]`，每条含 `title` / `url` / `abs`(摘要) / `time`(时间戳)；
- **自带反爬/验证码检测**：
  - Location 跳转 `wappass.baidu.com/static/captcha` → Captcha 异常；
  - `data.antiFlag == 1` → AccessDenied（"Forbid spider access"）；
- 支持分页（pageno）、时间范围（`gpc=stf=...`）、图片搜索、IT 搜索（kaifa.baidu.com）。

**内置 `searx/engines/bing.py`（源码已核实）——Bing Web 引擎**：

- `GET https://www.bing.com/search?q=<query>&adlt=<safesearch>`
- 可选 `mkt=<zh-CN>` 地区参数 → **就是 Bing 中文版路由**（README 也提到 `cn.bing.com`）；
- 解析 `#b_results > li.b_algo`：标题 `h2/a`、摘要 `p`，并解码 Bing 跳转链接
  `https://www.bing.com/ck/a?u=a1<base64url>`（还原真实 URL）；
- 无需 API key（官方 Bing API 已废弃免费额度，SearXNG 明确 `use_official_api: False`）。

**评价**：
- ✅ **百度 JSON 接口比 HTML 爬虫稳定得多**，且自带验证码/反爬状态检测，非常适合作为
  我们"百度内核"的参考实现（可整段内联/简化，无需引 AGPL 依赖）；
- ✅ Bing 引擎实现清晰，含真实 URL 解码逻辑；
- ⚠️ 整个 SearXNG 是重型自托管服务（Flask + 多引擎），**不适合直接引入**，但引擎文件
  是单文件、可移植的，可直接借鉴其算法（注意 AGPL 传染性——建议以"参考协议/思路"
  方式重写，而非复制整段代码）。

### 1.3 第二轮补充调研（2026-08-10 追加，多关键词：`baidu search api` / `BaiduSpider` / `baidu searcher` / `baidu serp` / `百度搜索 爬虫` / `baidu search html` / `baidusearch3`）

| 项目 | 协议 | 星数 | 方式 | 结论 |
|---|---|---|---|---|
| `karust/openserp` | MIT | ⭐1.2k | **Go** 自托管 SERP API（browser-rendered），内置 `baidu/` `bing/` 独立包（`search.go` + `parse_html.go` + `selectors.go`，含 `search_captcha.html`/`search_no_results.html`/`search_results.html` 测试夹具） | 架构参考价值高（错误归一化、测试夹具齐全），但 Go 语言、需自托管服务，**不适合直接作 Python 内核**；算法思路可借鉴 |
| `any4ai/AnyCrawl` | MIT | ⭐3.4k | **Node/TS** 爬虫，可提取 Google/Bing/Baidu SERP | Node 生态，非 Python，排除 |
| `ohblue/baidu-serp-api` | GPL-3.0 | ⭐36 | Python 库，爬百度 PC/移动 SERP 转 JSON；模拟完整浏览器 Cookie（BAIDUID/H_PS_645EC 等）、连接池/代理轮换、错误码体系（501=百度安全验证、403/429 等） | 反爬模拟最彻底、工程化最完整，**适合作为"百度 HTML 内核"的增强参考**；但 GPL-3.0 传染性 + 启发式 Cookie 维护成本高，仅参考不引入 |
| `baidusearch3` | - | - | GitHub 上**无此项目**（搜 0 结果） | 排除 |
| F9y4ng/GreasyFork-Scripts | GPL-3.0 | ⭐1.5k | 油猴脚本（浏览器端 Google↔Baidu 切换） | 浏览器脚本，非服务端方案，排除 |
| Py_WebCrawler / BaiduAOISpider / UItestframework / reverse-image-search / china-dictatorship 等 | - | - | 百度地图点名无关爬虫、UI 测试、无关内容 | 与 web_search 无关，排除 |

**补充调研结论**：百度系方案整体分三类——
1. **JSON 接口类**（SearXNG `tn=json`，最稳、无 key、反爬状态位齐全）→ **首选**；
2. **HTML 爬虫类**（python-baidusearch / baidu-serp-api / openserp，需模拟 Cookie、易被改版破坏）→ 增强备胎，参考其错误码与 UA/Cookie 模拟思路；
3. **重型自托管/异语言类**（SearXNG / openserp / AnyCrawl）→ 架构与算法参考，不引入依赖。

---

## 2. 结论：推荐的内核组合

**首选内核（默认）**：**百度 `tn=json` 接口**（采用 SearXNG `baidu.py` 的思路，
用 httpx 单文件实现，无 bs4/lxml 依赖）——国内可达、返回结构化 JSON、自带反爬状态位。

**备选内核 #2**：**Bing 中文版 HTML 解析**（`cn.bing.com` / `mkt=zh-CN`，采用 SearXNG
`bing.py` 思路：`b_algo` + ck/a 解码）——微软域国内可达、无需 key。

**备选内核 #3（未来扩展）**：DuckDuckGo（海外）、SearXNG 自托管实例、私有搜索 API
（如博查/Bocha、腾讯混元搜索等有 key 服务），只要实现同一接口即可。

> 复用现有 `web_tools.py` 的 httpx 会话与 `_extract_readable_text`，不新增第三方依赖。

---

## 3. 模块化架构设计（s4 交付）

### 3.1 设计原则

> **搜索内核可替换**：`web_search` 工具的**输入参数与输出格式固定**（对上层 LLM 与
> 调用方透明），内核即插即用。内核选择通过配置（`websearch.jsonc` 或环境变量）驱动。

### 3.2 接口定义（输入/输出契约）

**工具输入（ToolSpec.input_schema，维持现有对外形状，可增加可选字段）：**

```jsonc
{
  "query":  { "type": "string",  "description": "搜索关键词" },          // 必填
  "limit":  { "type": "integer", "description": "最大结果条数（1-20，默认 5）" },
  "domains": { "type": "array", "items": {"type": "string"}, "description": "按域名过滤（site:）" },
  "provider": { "type": "string", "description": "可选：指定搜索内核（baidu/bing/ddg/auto）" }
}
```

**统一输出（ToolResult.content + metadata + artifacts）：**

```jsonc
// metadata.results[] 固定字段（无论哪个内核）
{
  "title":    "结果标题",
  "url":      "真实落地 URL（Bing 跳转链接已解码）",
  "snippet":  "摘要",
  "source":   "内核名（baidu / bing / ddg ...）"
}
```

artifacts 保留 `kind="web_search_result"`，`uri=<provider>`，`content=results[]`。

### 3.3 内核接口（Python Protocol）

```python
# core/src/lamtools_core/tool/search/protocol.py
class SearchResult(TypedDict):
    title: str
    url: str
    snippet: str
    source: str          # 固定为内核名

class SearchProvider(Protocol):
    name: str            # "baidu" / "bing" / "baidu-serp-cli" / "searxng-http" ...
    transport: str = "inproc"   # "inproc" | "subprocess" | "http"
    async def search(self, query: str, limit: int = 5,
                     domains: list[str] | None = None) -> list[SearchResult]: ...
```

> `transport` 标识接入形态。**独立进程内核**（GPL/AGPL 或任何外部工具）只允许
> `subprocess` / `http`，见 §3.8。

### 3.4 目录与文件规划

```
core/src/lamtools_core/tool/search/
├── __init__.py          # 公开 get_provider(name) / list_providers()
├── protocol.py          # SearchResult / SearchProvider Protocol（含 transport）
├── base.py              # 公共：HTTP 会话复用、UA、错误码归一化、domains→site: 拼接
├── baidu.py             # 百度 tn=json 内核（自研，inproc，默认）
├── bing.py              # Bing 中文版内核（b_algo + ck/a 解码，inproc）
├── duckduckgo.py        # 保留原 DDG 内核(海外备胎)，迁出 web_tools.py 逻辑
├── external.py          # 独立进程内核（subprocess / http，通用，见 §3.8）
└── factory.py           # 组装：读配置 → 选内核 → 返回 make_web_search_handler
```

### 3.5 与现有工具系统的接线（无侵入）

| 位置 | 改动 |
|---|---|
| `default_toolbox.py` `build_handlers()` | `"web_search": make_web_search_handler(...)` 改为经 search 包 factory 构造；**移除 `disabled_tools.add("web_search")` 禁用行** |
| `web_tools.py` | DDG 解析逻辑迁入 `search/duckduckgo.py`，保留 `web_fetch` 不动 |
| `loadtools.py` / access 配置 | `web_search` 已登记，无需改 |
| 配置 | 新增 `core/.lam/core/config/websearch.jsonc`（可选）：`{ "provider": "baidu", "baidu": {...}, "bing": {...} }`，默认 `baidu`，缺失时回退内置默认 |

### 3.6 错误归一化

所有内核统一抛出/返回四类可识别错误（延续现有 `ToolResult.status` 语义）：

| 错误 | 语义 | ToolResult |
|---|---|---|
| 参数缺失 | query 为空 | `failed` + 提示 |
| 网络错误 | httpx.HTTPError | `failed` + network error |
| 反爬/验证码 | 百度 antiFlag / wappass、Bing 429 | `failed` + provider 专属提示，可恢复 |
| 无结果 | 正常空结果集 | `ok` + result_count=0 |

### 3.7 验收标准（后续实施时核对）

- [ ] 默认内核=百度，国内网络可搜出中文结果；
- [ ] `provider=bing` 可切换到 Bing 中文；
- [ ] `provider=ddg` 可切换回原 DDG（海外）；
- [ ] 同一 `ToolResult` 形状，metadata.results 字段一致；
- [ ] 移除禁用后 `web_search` 出现在工具列表，permission 仍为 AUTO_ALLOW；
- [ ] 不新增第三方 Python 依赖。

### 3.8 独立进程内核（subprocess / http）—— 外部工具一等公民

> 用户已确认：**GPL/AGPL 组件（baidu-serp-api、SearXNG、openserp、AnyCrawl 等）一律不内置**，
> LamTools 不在乎其内部实现，只把它当"用的顺手的工具"，通过进程边界按固定契约调用。

`external.py` 实现通用 `ExternalProvider`，两种 transport：

```python
class ExternalProvider:
    def __init__(self, name: str, transport: str,  # "subprocess" | "http"
                 command: list[str] | None = None,     # subprocess: ["baidu-serp-cli", "--json"]
                 url: str | None = None,               # http: "http://127.0.0.1:8888/search"
                 timeout: float = 30):
        ...

    # 统一输入：{"query","limit","domains"}；统一输出：{"results":[{title,url,snippet}]}
    async def search(self, query, limit=5, domains=None) -> list[SearchResult]: ...
```

- **subprocess**：子进程一次一搜（传 stdin/argv JSON，读 stdout JSON）；
- **http**：POST 固定契约（`/search`，body 同上）到用户自托管服务；
- 外部程序由用户自行安装/启动，**仓库不携带其代码**，README/配置注释标注许可证边界；
- 输出解析失败、超时、退出码非 0 → 统一归一化为可恢复错误（见 §3.6）；
- 可选 `EXTERNAL_SEARCH_BIN` 环境变量注入命令路径。

---

## 附录 A：许可证边界与合规接线（GPL / AGPL）

### A.1 结论先行

- **模块化封装 ≠ 法律隔离**：把 GPL/AGPL 代码放成独立 `.py` 模块、或`import` 进同进程，
  都不规避传染；只有**进程边界**（subprocess / HTTP）才是社区通行的隔离方式。
- **既定策略（用户已确认）**：外部 GPL/AGPL 工具（`baidu-serp-api`、SearXNG、openserp、
  AnyCrawl 等）一律**不内置、不 import**——LamTools 只把它当独立工具，按固定契约经
  subprocess/http 调用（§3.8），组件由用户自行安装，仓库不携带其代码。
- LamTools 对外分发安装包 → **默认内核必须自研（百度 `tn=json` 是公开 HTTP 协议，
  协议本身不受版权保护），绝不 import/内联 GPL/AGPL 代码**。

### A.2 判定表（mere aggregation 视角）

| 接入方式 | 是否独立作品 | 传染 |
|---|---|---|
| 独立进程 + HTTP/CLI/socket 调用（不 import、不内联、不捆绑进同一二进制） | ✅ | ❌ |
| `pip install` + `import`（同进程链接，即使库由用户单独下载） | ❌ | ✅ |
| 复制 GPL 源码进仓库（哪怕单独 directory） | ❌ | ✅ |
| 纯内部使用、不对外分发/不提供 SaaS | —— | ⚠️ GPL 本身不管内部使用；AGPL 管"网络远程交互提供修改版" |

> AGPL §13 触发条件：修改 AGPL 程序 + 通过网络向远程用户提供服务。部署**原版**实例
> 自用、自己调用，不触发。

### A.3 transport 字段（架构内建隔离能力）

`SearchProvider` 增加可选 `transport`，让"进程外调用"成为一等公民：

```python
class SearchProvider(Protocol):
    name: str                    # "baidu" / "bing" / "baidu-gpl-cli" ...
    transport: str = "inproc"    # "inproc" | "subprocess" | "http"
    async def search(self, query: str, limit: int = 5,
                     domains: list[str] | None = None) -> list[SearchResult]: ...
```

- `inproc`：自研轻量内核（默认，无许可证风险）；
- `subprocess`：调用独立 CLI 程序（GPL 组件只能以此形态接入，由用户自行安装）；
- `http`：调用自托管 SERP 服务（SearXNG/openserp 等，部署原版、不改源码）。

factory 依据配置创建对应 provider；subprocess/http provider 在代码注释与 README 中
明确标注许可证边界，杜绝误用。默认配置不启用任何 GPL/AGPL provider。

---

## 4. 参考链接

- SearXNG baidu engine: https://raw.githubusercontent.com/searxng/searxng/master/searx/engines/baidu.py
- SearXNG bing engine: https://raw.githubusercontent.com/searxng/searxng/master/searx/engines/bing.py
- python-baidusearch: https://github.com/amazingcoderpro/python-baidusearch
- pydork: https://github.com/blacknon/pydork
- openserp（Go SERP API，含百度/必应单文件实现）: https://github.com/karust/openserp
- AnyCrawl（Node/TS SERP 提取）: https://github.com/any4ai/AnyCrawl
- ohblue/baidu-serp-api（百度 SERP 增强反爬模拟参考）: https://github.com/ohblue/baidu-serp-api