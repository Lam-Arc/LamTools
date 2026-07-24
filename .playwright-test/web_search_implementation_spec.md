# LamTools Web Search 工具 — 实现工程书

## 一、预期功能

### 1.1 核心能力

Web Search 工具让 LamTools 内部的 agent 具备联网搜索能力。agent 调用此工具后，获得一组结构化的网页搜索结果（标题、URL、摘要），用于回答需要实时信息的问题。

### 1.2 功能清单

| 编号 | 功能 | 说明 |
|------|------|------|
| F1 | 关键词搜索 | 输入查询词，返回网页搜索结果 |
| F2 | 结果数量控制 | 可指定返回结果条数（默认5，上限由后端决定） |
| F3 | 域名过滤 | 可选：只返回指定域名的结果 |
| F4 | 多后端支持 | 底层可切换不同搜索后端，通过配置选择 |
| F5 | 后端健康检测 | 调用前检测后端是否可用，不可用时返回明确错误 |
| F6 | 超时保护 | 后端响应超时时返回错误，不阻塞 agent |
| F7 | 结果格式统一 | 无论后端是什么，返回给 agent 的数据结构一致 |

### 1.3 不做的事（明确边界）

| 不做 | 原因 |
|------|------|
| 不内置任何搜索引擎爬虫 | 爬虫代码属于外部独立服务，LamTools 只做调用 |
| 不做网页内容抓取 | 搜索只返回摘要；如需全文，由单独的 web_fetch 工具负责 |
| 不做图片/视频/新闻搜索 | agent 场景下网页搜索覆盖 90% 需求 |
| 不做搜索结果缓存 | 缓存由后端服务负责，壳层保持无状态 |
| 不自动安装后端服务 | 用户按文档自行安装，LamTools 只检测和调用 |

### 1.4 统一输入输出

**输入参数：**

```python
async def web_search(
    query: str,                    # 必填，搜索关键词
    limit: int | None = 5,         # 可选，返回结果数量，默认5
    domains: list[str] | None = None,  # 可选，域名过滤
) -> dict
```

**输出结构（成功）：**

```json
{
  "query": "Python asyncio",
  "results": [
    {
      "title": "Python asyncio 官方文档",
      "url": "https://docs.python.org/3/library/asyncio.html",
      "content": "asyncio is a library to write concurrent code..."
    }
  ],
  "engine": "searxng"
}
```

**输出结构（失败）：**

```json
{
  "query": "Python asyncio",
  "results": [],
  "error": "Search backend unavailable: connection refused at localhost:8080"
}
```

**关键约定：即使失败也返回 `results: []` 而非抛异常。** agent 拿到空结果可以自行判断是否重试或换策略，不需要处理异常。`error` 字段提供诊断信息。

---

## 二、实施方案

### 2.1 架构总览

```
┌──────────────────────────────────────────────────┐
│  LamTools Agent                                   │
│                                                   │
│  ┌─────────────┐     ┌──────────────────────┐   │
│  │ LLM 调用     │────▶│  web_search 工具函数  │   │
│  │ tool_call    │     │  (壳层，~30行)        │   │
│  └─────────────┘     └──────────┬───────────┘   │
│                                 │                 │
│                                 │ 统一接口         │
│                                 ↓                 │
│                    ┌──────────────────────┐       │
│                    │  SearchAdapter       │       │
│                    │  (适配器调度层)       │       │
│                    └──────┬───────────────┘       │
│                           │                       │
│            ┌──────────────┼──────────────┐        │
│            ↓              ↓              ↓        │
│     ┌───────────┐  ┌───────────┐  ┌───────────┐  │
│     │ SearXNG   │  │ BaiduProxy│  │  (未来)   │  │
│     │ Adapter   │  │ Adapter   │  │  Adapter  │  │
│     └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  │
│           │               │              │        │
└───────────┼───────────────┼──────────────┼────────┘
            │ HTTP          │ HTTP         │ HTTP
            ↓               ↓              ↓
     ┌───────────┐  ┌───────────┐
     │ SearXNG   │  │ 百度搜索   │
     │ 实例      │  │ 代理服务   │
     │ (独立进程) │  │ (独立进程) │
     └───────────┘  └───────────┘
```

### 2.2 分层职责

| 层 | 职责 | 不做的事 |
|----|------|---------|
| **工具函数层**（web_search.py） | 接收 LLM 的参数，调用适配器，返回结果 | 不关心后端是什么 |
| **适配器调度层**（SearchAdapter） | 根据配置选择适配器，传递参数，处理超时 | 不做搜索逻辑 |
| **适配器层**（各 Adapter） | 把统一参数翻译成后端请求，把后端响应翻译成统一格式 | 不做缓存、不做限频 |
| **后端服务**（外部进程） | 实际搜索、反爬、缓存、限频 | LamTools 不管理 |

### 2.3 文件结构

```
core/src/lamtools_core/tool/
├── web_search.py              # 工具函数（壳层）+ 适配器调度
└── search_adapters/            # 适配器目录
    ├── __init__.py
    ├── base.py                 # 适配器基类（定义统一接口）
    ├── searxng.py              # SearXNG 适配器
    └── baidu_proxy.py          # 百度搜索代理适配器
```

### 2.4 配置

在 LamTools 的配置体系中增加：

```yaml
web_search:
  enabled: true
  backend: "searxng"              # "searxng" | "baidu_proxy" | ...
  endpoint: "http://localhost:8080"  # 后端服务地址
  timeout: 15                     # 超时秒数
  default_limit: 5                # 默认返回条数
```

### 2.5 工具注册

在 `default_toolbox.py` 中注册 `web_search` 函数，参照 `workspace_files.py` 的注册模式。

在 `access_tools.jsonc` 中声明权限：

```jsonc
{
  "web_search": {
    "readonly": true,
    "network": true,
    "description": "Search the web for current information"
  }
}
```

### 2.6 许可证隔离

| 组件 | 属于 LamTools？ | 包含 GPL 代码？ |
|------|----------------|----------------|
| web_search.py | 是（闭源） | 否，只有 httpx 调用 |
| search_adapters/* | 是（闭源） | 否，只有 httpx 调用 |
| SearXNG 实例 | 否（独立进程） | 是（AGPL），但不影响 LamTools |
| 百度搜索代理 | 否（独立进程） | 是（GPLv3，因 import baidu-serp-api），但不影响 LamTools |

**原则：LamTools 代码中不出现任何对 GPL 库的 import。所有 GPL 代码只存在于外部独立进程中，通过 HTTP 通信。**

---

## 三、关键功能实现

### 3.1 适配器基类

```python
# search_adapters/base.py

from abc import ABC, abstractmethod

class SearchAdapter(ABC):
    """所有搜索适配器的基类。定义统一接口。"""

    def __init__(self, endpoint: str, timeout: int = 15):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    @abstractmethod
    async def search(
        self,
        query: str,
        limit: int = 5,
        domains: list[str] | None = None,
    ) -> dict:
        """
        执行搜索，返回统一格式。

        返回:
            {
                "query": str,
                "results": [{"title": str, "url": str, "content": str}],
                "engine": str,           # 后端标识
                "error": str | None,     # 错误信息，无错误为 None
            }
        """
        ...

    async def health_check(self) -> bool:
        """检测后端是否可用。子类可覆盖。"""
        import httpx
        try:
            resp = await httpx.AsyncClient(timeout=3).get(
                f"{self.endpoint}/health"
            )
            return resp.status_code == 200
        except Exception:
            return False
```

**分歧点：health_check 是否在每次 search 前调用？**

**决定：不主动调用。** 原因：health_check 本身是一次 HTTP 请求，每次搜索前先检查等于多一次往返。直接发起搜索请求，如果后端不可用，httpx 会抛 `ConnectError`，在异常处理中捕获即可。health_check 方法保留，供 LamTools 的 UI 或诊断功能主动调用。

### 3.2 SearXNG 适配器

```python
# search_adapters/searxng.py

import httpx
from .base import SearchAdapter

class SearXNGAdapter(SearchAdapter):
    """SearXNG 后端适配器。"""

    async def search(self, query, limit=5, domains=None):
        params = {
            "q": query,
            "format": "json",
            "pageno": 1,
        }
        if domains:
            params["engines"] = ",".join(domains)  # SearXNG 用 engines 参数做域名过滤

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.endpoint}/search",
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError:
            return {
                "query": query,
                "results": [],
                "engine": "searxng",
                "error": f"SearXNG unavailable at {self.endpoint}",
            }
        except httpx.TimeoutException:
            return {
                "query": query,
                "results": [],
                "engine": "searxng",
                "error": f"SearXNG timeout after {self.timeout}s",
            }
        except Exception as e:
            return {
                "query": query,
                "results": [],
                "engine": "searxng",
                "error": str(e),
            }

        results = []
        for item in data.get("results", [])[:limit]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
            })

        return {
            "query": query,
            "results": results,
            "engine": "searxng",
            "error": None,
        }
```

**分歧点：SearXNG 的 `domains` 参数怎么传？**

SearXNG 没有直接的"域名过滤"参数。它有 `engines`（选搜索引擎）和 `categories`（选分类），但没有"只返回 example.com 的结果"。

**决定：在适配器层做客户端过滤。** 拿到全部结果后，在 Python 侧按 domains 过滤。虽然浪费了部分后端返回的结果，但逻辑简单且对所有后端统一。

```python
# 修改：domains 过滤在客户端做
if domains:
    results = [
        r for r in results
        if any(d in r["url"] for d in domains)
    ]
results = results[:limit]  # 过滤后再截断
```

### 3.3 百度搜索代理适配器

```python
# search_adapters/baidu_proxy.py

import httpx
from .base import SearchAdapter

class BaiduProxyAdapter(SearchAdapter):
    """
    百度搜索代理适配器。
    对接 tl456/searxng-baidu-proxy 或类似服务。
    该服务内部使用 baidu-serp-api（GPLv3），但本适配器
    只通过 HTTP 调用，不 import 任何 GPL 库。
    """

    async def search(self, query, limit=5, domains=None):
        params = {
            "q": query,
            "format": "json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.endpoint}/search",
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError:
            return {
                "query": query,
                "results": [],
                "engine": "baidu_proxy",
                "error": f"Baidu proxy unavailable at {self.endpoint}",
            }
        except httpx.TimeoutException:
            return {
                "query": query,
                "results": [],
                "engine": "baidu_proxy",
                "error": f"Baidu proxy timeout after {self.timeout}s",
            }
        except Exception as e:
            return {
                "query": query,
                "results": [],
                "engine": "baidu_proxy",
                "error": str(e),
            }

        results = []
        for item in data.get("results", [])[:limit]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
            })

        # 客户端域名过滤
        if domains:
            results = [
                r for r in results
                if any(d in r["url"] for d in domains)
            ]

        return {
            "query": query,
            "results": results,
            "engine": "baidu_proxy",
            "error": None,
        }
```

**分歧点：百度代理返回的 `content` 字段可能叫 `description` 而非 `content`。**

不同后端返回的字段名可能不同。SearXNG 用 `content`，百度代理（SearXNG 兼容格式）也用 `content`，但如果对接的是非 SearXNG 兼容的服务，可能用 `description` 或 `snippet`。

**决定：适配器负责字段名归一化。** 每个适配器在翻译时把后端的字段名映射到统一格式。如果后端用 `description`，适配器里写 `item.get("content", item.get("description", ""))`。**这个逻辑封装在适配器内，不泄漏到壳层。**

### 3.4 适配器调度层

```python
# web_search.py

import httpx
from .search_adapters.base import SearchAdapter
from .search_adapters.searxng import SearXNGAdapter
from .search_adapters.baidu_proxy import BaiduProxyAdapter

# 适配器注册表：backend 名 → 适配器类
ADAPTER_REGISTRY = {
    "searxng": SearXNGAdapter,
    "baidu_proxy": BaiduProxyAdapter,
}

# 全局缓存适配器实例（避免每次调用都创建）
_adapter_instance: SearchAdapter | None = None
_adapter_configured_backend: str | None = None


def _get_adapter(config: dict) -> SearchAdapter:
    """
    根据配置获取适配器实例。
    配置变化时重新创建，否则复用。
    """
    global _adapter_instance, _adapter_configured_backend

    ws_config = config.get("web_search", {})
    backend = ws_config.get("backend", "searxng")
    endpoint = ws_config.get("endpoint", "http://localhost:8080")
    timeout = ws_config.get("timeout", 15)

    if _adapter_instance and _adapter_configured_backend == backend:
        return _adapter_instance

    adapter_cls = ADAPTER_REGISTRY.get(backend)
    if not adapter_cls:
        raise ValueError(
            f"Unknown web_search backend: {backend}. "
            f"Available: {list(ADAPTER_REGISTRY.keys())}"
        )

    _adapter_instance = adapter_cls(endpoint, timeout)
    _adapter_configured_backend = backend
    return _adapter_instance


async def web_search(
    query: str,
    limit: int | None = 5,
    domains: list[str] | None = None,
) -> dict:
    """
    Search the web and return structured results.

    Args:
        query: Search query string
        limit: Maximum number of results (default 5)
        domains: Optional domain filter

    Returns:
        {"query": str, "results": [{"title", "url", "content"}], "engine": str, "error": str | None}
    """
    # 获取 LamTools 配置（具体获取方式参照现有工具的实现）
    config = _get_lamtools_config()

    ws_config = config.get("web_search", {})
    if not ws_config.get("enabled", False):
        return {
            "query": query,
            "results": [],
            "engine": "none",
            "error": "Web search is disabled. Enable it in config.",
        }

    limit = limit or ws_config.get("default_limit", 5)

    adapter = _get_adapter(config)
    result = await adapter.search(query, limit, domains)
    return result


def _get_lamtools_config() -> dict:
    """
    获取 LamTools 配置。
    具体实现参照 LamTools 现有的配置获取方式
    （可能是从 config/operations.py 或全局 config 对象获取）。
    """
    # TODO: 接入 LamTools 实际的配置系统
    from lamtools_core.config.operations import get_config  # 示例
    return get_config()
```

**分歧点：适配器实例是每次创建还是缓存复用？**

**决定：缓存复用。** 原因：httpx.AsyncClient 在适配器内部按请求创建（用 `async with`），适配器本身是无状态的（只存 endpoint 和 timeout），可以安全复用。配置变化时（backend 或 endpoint 变了）才重建。

**分歧点：`_get_lamtools_config()` 怎么接入实际配置系统？**

**决定：这里留一个 TODO，实现时参照 `workspace_files.py` 等现有工具怎么获取配置的。** 不同 LamTools 版本的配置获取方式可能不同，壳层不应该假设特定的配置 API。关键是：配置中要有 `web_search` 这个 section，包含 `enabled`、`backend`、`endpoint`、`timeout`、`default_limit` 字段。

### 3.5 错误处理策略

**核心原则：web_search 永远返回 dict，不抛异常。**

agent 调用工具时，如果工具抛异常，agent runtime 可能会中断当前轮次。web_search 作为信息获取工具，失败时应该返回空结果 + 错误信息，让 agent 自己决定怎么办（换措辞重试、告诉用户搜索不可用等）。

```python
# 错误分级
# 1. 后端不可用（连接失败）→ results: [], error: "backend unavailable"
# 2. 后端超时 → results: [], error: "timeout"
# 3. 后端返回错误（4xx/5xx）→ results: [], error: "backend error: {status}"
# 4. 后端返回格式异常 → results: [], error: "parse error"
# 5. 工具未启用 → results: [], error: "disabled"
# 6. query 为空 → results: [], error: "empty query"（不调用后端）
```

**分歧点：query 为空时是否调用后端？**

**决定：不调用。** 空查询没有意义，直接返回错误，节省一次网络请求。

```python
# 在 web_search 函数开头加：
if not query or not query.strip():
    return {
        "query": query or "",
        "results": [],
        "engine": "none",
        "error": "Empty query",
    }
```

### 3.6 超时处理

**分歧点：超时设在哪一层？**

| 层 | 超时 | 说明 |
|----|------|------|
| 适配器层 | httpx 请求超时 | 每个适配器的 httpx.AsyncClient 设 timeout |
| 调度层 | 不设 | 不在调度层包一层超时，避免双重超时 |

**决定：只在适配器层设超时。** 超时值从配置读取（默认15秒）。适配器捕获 `httpx.TimeoutException` 后返回错误 dict，不向上传播。

### 3.7 domains 过滤的统一逻辑

**分歧点：domains 过滤在后端做还是客户端做？**

不同后端对域名过滤的支持不同：
- SearXNG：没有直接的域名过滤参数
- 百度代理：不支持域名过滤
- 未来的直接爬虫：可以在请求时加 `site:` 操作符

**决定：统一在客户端做。** 适配器拿到全部结果后，在 Python 侧按 domains 过滤，再截断到 limit。这样所有适配器的行为一致，不依赖后端能力。

```python
# 统一过滤逻辑（放在基类或工具函数中）
def _filter_by_domains(results: list[dict], domains: list[str] | None) -> list[dict]:
    if not domains:
        return results
    return [r for r in results if any(d in r["url"] for d in domains)]
```

**注意：先过滤再截断。** 如果后端返回10条，过滤后剩3条，就返回3条。不要先截断到5条再过滤（可能过滤后只剩1条）。

### 3.8 添加新适配器的流程

未来要加一个新的搜索后端（比如 Bing 中文爬虫代理），步骤：

1. 在 `search_adapters/` 下新建 `bing_proxy.py`
2. 继承 `SearchAdapter`，实现 `search()` 方法
3. 在 `ADAPTER_REGISTRY` 中注册：`"bing_proxy": BingProxyAdapter`
4. 用户在配置中设 `backend: "bing_proxy"`

不需要改 web_search.py 的任何逻辑，不需要改 default_toolbox.py，不需要改 access_tools.jsonc。

### 3.9 后端服务的安装文档（不内置）

LamTools 的文档中提供安装指南，但不自动安装：

```markdown
## 安装搜索后端（可选）

Web Search 工具需要一个搜索后端服务。以下是可选的后端：

### 选项 A：SearXNG（推荐，多引擎聚合）

1. 安装 Docker
2. 运行：docker run -d -p 8080:8080 searxng/searxng
3. 在 LamTools 配置中设置：
   web_search:
     backend: searxng
     endpoint: http://localhost:8080

### 选项 B：百度搜索代理（中国大陆推荐）

1. pip install flask baidu-serp-api
2. 下载 SearxBaiduService.py
3. 运行：python SearxBaiduService.py
4. 在 LamTools 配置中设置：
   web_search:
     backend: baidu_proxy
     endpoint: http://localhost:8888
```

### 3.10 测试验证

| 测试用例 | 输入 | 预期输出 |
|---------|------|---------|
| 正常搜索 | `web_search("Python教程", limit=3)` | 3条结果，每条含 title/url/content |
| 空查询 | `web_search("")` | `results: [], error: "Empty query"` |
| 后端未启动 | `web_search("test")`（后端没跑） | `results: [], error: "unavailable"` |
| 域名过滤 | `web_search("Python", domains=["python.org"])` | 结果 URL 全含 python.org |
| 超时 | 后端响应 >15s | `results: [], error: "timeout"` |
| 工具未启用 | config 中 enabled=false | `results: [], error: "disabled"` |
| limit 为 None | `web_search("test", limit=None)` | 用 default_limit（5） |
| limit 为 0 | `web_search("test", limit=0)` | `results: []`（0条） |

---

## 四、实现顺序建议

| 步骤 | 内容 | 依赖 |
|------|------|------|
| 1 | 创建 `search_adapters/base.py`（基类） | 无 |
| 2 | 创建 `search_adapters/searxng.py`（SearXNG 适配器） | 步骤1 |
| 3 | 创建 `web_search.py`（壳层 + 调度） | 步骤1、2 |
| 4 | 注册到 `default_toolbox.py` | 步骤3 |
| 5 | 配置 `access_tools.jsonc` | 步骤4 |
| 6 | 在配置体系中增加 `web_search` section | 步骤3 |
| 7 | 部署一个 SearXNG 实例做测试 | 步骤2 |
| 8 | 端到端测试 | 步骤4-7 |
| 9 | 创建 `search_adapters/baidu_proxy.py` | 步骤1 |
| 10 | 在 ADAPTER_REGISTRY 注册百度适配器 | 步骤9 |

步骤1-8 是最小可用版本（SearXNG 后端）。步骤9-10 是中国大陆适配。

---

## 五、风险与注意事项

| 风险 | 影响 | 应对 |
|------|------|------|
| SearXNG 实例挂掉 | 搜索不可用 | 返回明确错误，agent 可降级为不搜索 |
| 百度代理被限流 | 百度后端间歇不可用 | 适配器返回错误，用户可切换到 SearXNG 后端 |
| 后端返回格式变化 | 适配器解析失败 | 适配器用 `.get()` 容错，解析失败返回空结果 |
| httpx 版本不兼容 | import 失败 | LamTools 已依赖 httpx，版本应已兼容 |
| 配置缺失 web_search section | 工具报错 | 壳层检测 enabled 字段，缺失时视为未启用 |

---

## 六、调研附录：已评估的外部项目

### 6.1 lcg0558/web-search

- **语言**：PHP 8.0+
- **引擎**：百度、Bing、搜狗、360、夸克（5个）
- **API 兼容**：SearXNG 格式
- **状态**：❌ 不完整。README 描述了 `src/` 目录结构，但 GitHub 文件树显示 `src/` 目录未提交，核心搜索引擎实现代码缺失。配置文件 `config.php` 完整（5引擎配置），但执行搜索的 PHP 类未上传。
- **结论**：不可直接使用。

### 6.2 tl456/searxng-baidu-proxy

- **语言**：Python（单文件 ~300行）
- **引擎**：仅百度
- **依赖**：`baidu-serp-api`（PyPI 包，GPLv3，v1.1.7，2025年8月更新）
- **API 兼容**：SearXNG 格式
- **状态**：✅ 代码完整，可运行。
- **质量评估**：
  - 好的部分：SearXNG API 兼容、反爬策略（UA轮换+随机延迟+请求间隔+错误冷却）、线程安全锁、内存缓存、Windows 一键启动
  - 差的部分：只有百度一个引擎、同步阻塞（Flask + time.sleep）、串行瓶颈（全局锁）、内存缓存无持久化、无配置文件（硬编码）、UA列表太小（仅3个）、无重试逻辑、健康检查是假的（永远返回ok）
- **核心价值**：它依赖的 `baidu-serp-api` 库才是真正有价值的东西——自动生成 BAIDUID/H_PS_PSSID 等17个Cookie、rsv_pq/rsv_t 等请求参数、PC版和移动版两套模拟、完整的错误码体系（404-523）、代理轮换支持、活跃维护。
- **结论**：SearxBaiduService.py 本身质量一般（5/10），不值得作为基础重构。但 `baidu-serp-api` 库质量高（7.5/10），值得作为外部后端服务使用。

### 6.3 pengong101/openclaw-searxng-search

- **方式**：部署真正的 SearXNG + Docker
- **引擎**：百度、Bing中文、Wikipedia中文
- **状态**：Docker 部署配置，有测试报告。
- **结论**：需要 Docker，文档不够详细，未深入验证。

### 6.4 BingLiHanShuang/SearXNGChina

- **状态**：只是一个 AI agent 技能配置（prompt 指令），无实际代码。
- **结论**：无用，跳过。

### 6.5 baidu-serp-api（PyPI 包）

- **版本**：1.1.7（2025-08-01）
- **许可**：GPLv3
- **能力**：自动模拟百度浏览器请求（17个Cookie + 请求参数）、PC版（BaiduPc）和移动版（BaiduMobile）、连接模式可选（single/pooled/custom）、代理轮换、性能监控、完整的错误码体系
- **Python 要求**：>=3.12
- **结论**：作为独立外部服务的依赖使用，通过 HTTP 隔离 GPL 许可证。
