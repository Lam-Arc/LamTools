---
状态: 执行中
摘要: 内置浏览器搜索适配器（Google/Bing/百度）——PRD V1.0 原文 + 实施落位 + 可打勾验收清单
---

# 浏览器搜索适配器 · PRD / SPEC V1.0

> 本文档 = 用户提交的 PRD 原文（Part A–D，逐条保留）+ 实施落位（Part E）+ 打勾清单（Part F）。
> 打勾规则：**代码与测试都落地才打勾**；只在真机上跑过才能证明的项，标「未验证」并留证据位。
> 查询方式：按 PRD 编号（P1–P5 / S1–S6 / §7 / §8 / §9 / §11 / §13）检索本文，右侧是落地位置与状态。

| 项 | 含义 |
|---|---|
| 状态 | 草稿 / 就绪 / 执行中 / 完成（本文档：执行中） |
| 范围 | 浏览器搜索、搜索结果提取、网页内容清洗 |
| 适配目标 | Google / Bing / Baidu |
| 技术环境 | Sunday · Tauri 2 · Agent Loop |

---

## Part A｜PRD 产品需求

### 1. 产品目标

让 Sunday 的内置浏览器同时承担普通网页浏览、Agent 网页搜索和网页信息获取的任务。

用户只需提出搜索需求，Agent 即可调用内置浏览器完成搜索、筛选、阅读与结果整理。

核心要求：以真实浏览器作为网页访问入口，以结构化数据作为 Agent 的主要输入，以视觉感知作为补充。

不依赖第三方收费搜索 API，也不将原始网页全文直接提交给模型。

### 2. 用户需要得到什么

**P1｜稳定搜索**

- 支持 Google、Bing、百度。
- 不要求用户申请 API Key。
- 能够使用浏览器已有网络环境、代理配置与登录状态。
- 默认自动选择搜索引擎，支持指定与切换。
- 引擎不可用时可以尝试其他引擎。
- 不因单一引擎失败而直接终止整个搜索任务。
- 保留完整搜索词，不随意拆分长查询。

**P2｜准确获取搜索结果**

Agent 能获取：

- 搜索结果标题、摘要、目标 URL。
- 搜索结果排名、来源网站。
- 可识别的发布日期和结果类型。
- 搜索结果对应的站内子链接。
- 多页搜索结果。

不得发生标题、摘要、链接跨卡片错配。

**P3｜自动清除无关内容**

不向 Agent 发送：

- 无障碍导航、顶部工具栏、账户入口。
- 页脚、重复导航和搜索设置。
- 与任务无关的广告和推荐区域。
- 无意义的 URL 跟踪参数。
- 轮播克隆项和重复结果。
- 不必要的 HTML、CSS 和脚本。

广告可以保留类型标识，但默认不作为自然搜索结果参与排序。

**P4｜浏览器与 Agent 协作**

- Agent 可以在后台标签页搜索。
- 用户正常浏览不被无故打断。
- Agent 可以打开结果，继续读取网页正文。
- 用户可以查看 Agent 正在访问的页面。
- 支持用户接管、停止或继续操作。
- 搜索结果可追溯到原始页面。
- 必要时使用 DOM、可访问性结构和截图补充信息。

**P5｜控制成本**

- 默认不使用视觉模型解析搜索结果。
- 默认不发送完整搜索结果页。
- 支持按数量、相关性和分页请求结果。
- 支持按需展开完整摘要、子链接和页面正文。
- 相同搜索允许短期缓存，刷新时能够获得最新结果。

### 3. 功能边界

**V1 包含**

1. 三个搜索引擎的结果页适配。
2. 通用网页结构识别与文本清洗。
3. 统一搜索结果格式。
4. Agent 搜索接口。
5. 页面正文读取接口对接。
6. 解析失败的自动降级。
7. 搜索状态、错误和诊断信息。
8. 基础性能与可靠性测试。

**V1 不包含**

- 自建搜索引擎或搜索索引。
- 自建代理服务器。
- 自动破解 CAPTCHA。
- 绕过搜索平台的访问限制。
- 通用视频、音频内容理解。
- 对所有网站建立独立适配器。
- 完整的自动化深度研究产品。

---

## Part B｜SPEC 功能规格

### 4. 总体架构

采用三层架构：

A. **Engine Adapter（引擎适配层）** — 负责理解不同搜索引擎的结果页面结构。

B. **Common Extractor & Cleaner（通用提取清洗层）** — 负责提取、清洗、规范化、校验、去重和输出。

C. **Browser Agent Bridge（Agent 接口层）** — 向 Agent 提供统一搜索与阅读能力，管理浏览器状态和交互。

逻辑流程：用户请求 → Agent 制定搜索 → Browser 执行查询 → Engine Adapter 识别结果 → Common Cleaner 清洗 → 结构化结果返回 Agent → 按需打开网页深读。

不得依靠模型逐条手动清洗普通搜索结果。

### 5. 引擎适配器

#### 5.1 通用接口

每个搜索引擎适配器需要支持：

| 能力 | 说明 |
|---|---|
| `buildQuery` | 构建搜索请求 |
| `detectPage` | 识别搜索结果页面 |
| `extractResults` | 提取结果卡片 |
| `extractPagination` | 获取分页信息 |
| `detectBlock` | 检测验证码、访问拒绝等 |
| `validateResults` | 验证解析结果 |

每个适配器负责识别自身引擎的 DOM 特征，不承担通用清洗逻辑。

#### 5.2 Google Adapter

需要识别：常规网页搜索结果；站点链接与搜索摘要；广告及推广结果；新闻、视频、图片等特殊卡片；AI 摘要与普通搜索结果的边界；分页与相关搜索。

避免把 Google 的导航、账号链接、追踪 URL 误认为搜索结果。

#### 5.3 Bing Adapter

需要识别：常规搜索结果卡片；站点链接与摘要；广告及特殊结果；Copilot / AI 摘要区域；分页及搜索类型。

要求保留用户原始查询，避免因 Sunday 自身的词语处理导致搜索意图丢失。

#### 5.4 Baidu Adapter

需要识别：常规自然搜索结果；百度百科、贴吧、知道等特殊卡片；广告和商业推广结果；百度跳转链接；摘要与发布时间；分页结构。

对于无法安全解析出最终目标的跳转 URL，保留原链接并标注待解析，不得猜测真实 URL。

#### 5.5 可扩展性

新增搜索引擎原则上只需新增适配器，不修改 Agent 接口和通用清洗模块。

页面选择器不得作为跨版本稳定的唯一识别依据。

### 6. 通用提取与清洗

**S1｜DOM 优先提取** — 在网页 DOM 尚未被展平为 Markdown 前完成结构化提取。保留每条结果的父子关系、链接归属及结果类型。避免先转为一维文本，再依赖模型重新猜测卡片边界。

**S2｜内容过滤** — 过滤页面导航、页脚、登录提示、非搜索结果的无关链接、重复卡片和隐藏模板、不相关的推荐和装饰元素。过滤应优先依据结构和语义，不能只根据关键词删除节点。

**S3｜URL 处理** — 识别真实目标链接与搜索引擎中转链接；清除明确无意义的追踪参数；保留业务必需的查询参数、签名与锚点；保留原始 URL 以便追溯；不对无法确认语义的参数进行破坏性清理。

**S4｜文本规范化** — 处理重复空格、换行及不可见字符；清理纯装饰性文字；保留标题原文和关键摘要；不通过模型生成内容来替代原始摘要；日期、数字、单位不得被无依据地改写。

**S5｜去重** — 依据规范化 URL、标题和结果归属判断重复。不能把同一域名下的不同页面错误合并。

**S6｜相关性保留** — 通用清洗层不应自行大幅改写搜索引擎的原始排序。默认保留自然结果顺序，允许 Agent 后续根据任务进行重排。

### 7. 统一数据协议

#### 7.1 SearchRequest

| 字段 | 说明 |
|---|---|
| `query` | 原始搜索内容 |
| `engine` | auto / google / bing / baidu |
| `limit` | 需要返回的结果数量 |
| `page` | 目标页码 |
| `type` | web / news / image / video |
| `freshness` | 可选时间约束 |
| `includeAds` | 是否包含广告 |

默认搜索类型为 `web`，默认返回 10 条结果。

#### 7.2 SearchResult

每条结果至少具有：

| 字段 | 说明 |
|---|---|
| `id` | 本次搜索的结果标识 |
| `rank` | 结果排名 |
| `title` | 标题 |
| `url` | 清洗后的目标 URL |
| `originalUrl` | 原始链接 |
| `snippet` | 搜索摘要 |
| `source` | 来源域名 |
| `type` | 内容类型 |
| `publishedAt` | 可识别的发布时间 |
| `sponsored` | 是否为推广结果 |
| `sitelinks` | 可选站点链接 |

不可靠或不存在的字段应为空，不得编造。

#### 7.3 SearchResponse

整体返回：`query`、`engine`、`status`、`results`、`nextPage`、`extractionMode`、`diagnostics`。

搜索成功、无结果、被拦截和解析失败必须属于不同状态。

### 8. Agent 工具接口

- `browser.search()` — 完整搜索流程：自动导航搜索引擎、提取结果、清洗并返回结构化数据。
- `browser.open_result()` — 通过结果 ID 或 URL 打开指定搜索结果，优先复用当前浏览器会话。
- `browser.read_page()` — 读取指定页面的正文和结构化内容，支持局部读取和分段。
- `browser.inspect_page()` — 提供更完整的页面上下文，包括结构信息、交互元素，以及按需获取的截图。

上述接口共享浏览器会话和页面标识，避免重复打开网页。结果 ID 只在其所属搜索会话中有效，不应假定跨刷新或跨导航稳定。

### 9. 解析降级机制

采用三级解析：

- **L1｜专用引擎适配器** — 正常路径。根据对应搜索引擎的页面结构提取结果。
- **L2｜通用语义提取器** — 专用适配器失败时，利用 DOM、链接、标题层级、可访问性结构等信息重新识别结果。
- **L3｜视觉辅助解析** — 结构化解析均无法可靠完成时，根据页面截图辅助理解和定位。

视觉解析仅作为兜底，不应默认触发。

当页面出现验证码、访问限制或必须由用户完成的验证时，返回明确状态。可以切换其他引擎或请求用户操作，但不得把错误页当作有效搜索结果。

每次解析必须检查结果数量、字段完整性和异常卡片比例。

### 10. 浏览器协作规则

- **用户主动浏览**：用户自己打开的网页保持正常使用。Agent 不得无故跳转、关闭或覆盖用户当前标签页。
- **Agent 主动搜索**：默认使用独立的后台任务标签页。用户能够查看任务页面并接管，Agent 可继续使用同一网页会话。
- **状态同步**：Agent 操作后，应同步实际页面状态。当用户操作改变页面时，旧的页面元素定位和结果状态需要重新验证。
- **安全边界**：网页文本属于不可信内容，不能作为 Agent 的系统指令执行。不得将 Cookie、令牌、密码等敏感浏览器数据混入搜索结果并发送给模型。

---

## Part C｜测试与验收

### 11. 关键测试场景

| 测试 | 预期结果 |
|---|---|
| Google 搜索 "bilibili" | 返回正确标题、摘要及网址 |
| Bing 搜索中文长句 | 原查询完整传递，不因 Sunday 自身逻辑错误切词 |
| 百度搜索中文关键词 | 正确识别自然结果与特殊卡片 |
| 搜索页面含长追踪 URL | 清理噪声，同时保留有效目标链接 |
| 搜索结果包含广告 | 正确标记，不混入自然排名 |
| 同一结果包含多个站点链接 | 归属关系正确 |
| 搜索引擎 DOM 改版 | 检测专用适配器异常并进入通用提取 |
| 页面出现验证码 | 返回受阻状态，不生成伪结果 |
| 用户中途切换标签页 | 不影响 Agent 后台任务 |
| Agent 打开搜索结果 | 能继续读取网页正文 |
| 搜索结果为空 | 区分真实无结果与解析失败 |
| 同时执行多项搜索 | 搜索上下文、结果 ID 不串扰 |

### 12. 初版质量目标

| 指标 | 初版目标 |
|---|---|
| 正常结果页提取成功率 | ≥95% |
| 结果标题与链接正确配对率 | ≥99% |
| 无关文本压缩率 | ≥80% |
| 常规搜索视觉模型调用 | 0 次 |
| 单页 DOM 提取与清洗 P95 | ≤500ms，不含网页加载 |
| 失败状态识别 | 不允许静默伪装成功 |

验证应覆盖三个引擎的不同查询语言、结果类型、页面结构和登录状态。

### 13. 完成标准

- [ ] Google、Bing、百度搜索均可通过统一接口调用。
- [ ] 普通搜索无需视觉模型参与。
- [ ] 原始页面噪声不直接进入 Agent 上下文。
- [ ] 标题、摘要、URL 正确归属。
- [ ] URL 清洗不会破坏正常链接。
- [ ] 支持分页、去重及结果类型标识。
- [ ] Agent 能打开结果并继续读取网页。
- [ ] 专用适配器失效后能够自动降级。
- [ ] 验证码、网络错误和解析失败可准确区分。
- [ ] 不影响用户现有浏览器标签页。
- [ ] 有可重复执行的测试及质量记录。

---

## Part D｜实施优先级

- **阶段一：统一清洗核心** — 标准化结果协议、DOM 提取、内容清洗、URL 处理和去重。
- **阶段二：三引擎适配** — 依次接入 Google、Bing、百度，建立对应解析测试样本。
- **阶段三：Agent 集成** — 接入 Sunday Agent Loop，实现搜索、打开结果、正文读取与浏览器状态同步。
- **阶段四：可靠性增强** — 通用语义提取、视觉兜底、错误识别、质量检测和回归测试。

### 最终产品原则

Sunday Browser 负责获取网页，Search Adapter 负责理解搜索结果结构，Cleaner 负责压缩噪声，Agent 负责搜索决策与信息利用。四者职责独立，但共享同一浏览器上下文。

最终用户体验应当是：无需配置搜索 API、无需关心不同搜索引擎的页面结构，直接让 Sunday 使用浏览器完成网页搜索与研究。

---

## Part E｜实施落位（本机现状 + 取舍 + 步骤）

### E.1 现状盘点（已核实的代码事实）

| 事实 | 证据 |
|---|---|
| 内置浏览器已能开标签、导航、快照、点击、输入、等待、截图 | `core/desktop/src-tauri/src/browser/mod.rs`（`browser_open`/`browser_nav`/`browser_snapshot`/`browser_act`/`browser_wait_for`/`browser_screenshot`） |
| Agent → 宿主唯一通道 = Core 内存队列 + 主窗口轮询执行 | `core/src/lamtools_core/browser/agent.py`、`core/ui/src/browser/agentBridge.ts`、`core/src/lamtools_core/http/routes.py`（`/browser/agent/pending`、`/result`） |
| 页面侧能力是固定注入脚本，命令集写死，禁止任意 JS | `core/desktop/src-tauri/src/browser/bridge_script.js`、`bridge.rs`（`OPS` 白名单） |
| 页面快照只给「可交互元素 + 文本块」，**拿不到链接地址** | `bridge_script.js` 的 `snapshot()`：`refs` 有 role/name，无 `href` |
| 因此搜索结果结构化**必须先有一条把 DOM 片段取回来的能力** | 方案 `内置浏览器-01-总体方案.md` 附录 §3.7 已把 `getHtml` 列为目标指令，当前未实现 |
| 默认搜索引擎目前是 Bing，仅用于地址栏识别 | `core/desktop/src-tauri/src/browser/url_policy.rs`（`DEFAULT_SEARCH_TEMPLATE`） |
| CDP 已决策不启用（安全面，需重新批准） | 同上 §3.7 决策记录 2026-11-16 |

### E.2 关键取舍

**取舍一：搜索结果结构化放在 Python，页面侧只加一个通用「读 DOM 片段」指令。**

- 采用：页面侧新增固定指令 `html`（按选择器返回清洗过的 outerHTML 片段 + 页面文本前缀），Python 侧完成卡片识别、字段配对、清洗、去重、校验。
- 理由：① DOM 在页面里，取回来必须经注入脚本（不能任意 JS）；② 适配器逻辑放 Python 才能用 HTML 样本做离线回归——改版第一天就能复现；③ 新增引擎只加一个 `.py` 文件，不重编 Rust。
- 放弃的方案 A：页面内写死三套搜索引擎解析脚本。理由：不可离线测试，改版要重编宿主二进制，且把「理解搜索结果结构」的职责塞进最不该变动的一层。
- 放弃的方案 B：CDP `Runtime.evaluate` 直接跑解析脚本。理由：等于开一条任意 JS 通道，安全面变更需重新批准（已决策不启用）。
- 放弃的方案 C：第三方搜索 API。理由：PRD 明确排除。

**取舍二：单条 `html` 指令同时服务搜索提取与正文阅读。**

搜索页和正文页只需要同一件事：把某些选择器命中的 DOM 片段取回来。两个用途共用一条指令，宿主能力集合只增一项（可审计），不为搜索单独开侧门。

**取舍三：降级三级都实现，但 L3 只做「把它变成人能看/模型能看的证据」，不假装解析。**

L3 产出截图落盘路径 + 页面文本前缀 + 明确状态 `extractionFailed`，交给多模态模型按需判断；默认不触发、不发图给模型。

**取舍四：结果 ID 是搜索会话内的短编号（`s1-3`），不做永久存根。**

PRD §8 明确「结果 ID 只在所属搜索会话中有效」。会话存进程内，带 TTL 与容量上限；跨刷新不保证。

**取舍五：缓存 5 分钟，`refresh` 绕过。**

PRD P5「相同搜索允许短期缓存，刷新时能够获得最新结果」。缓存键 = 引擎 + 查询 + 页 + 类型 + 时间约束。

### E.3 分层与文件（新增/修改）

```
core/desktop/src-tauri/src/browser/bridge_script.js   + extractHtml() 与 op 'html'
core/desktop/src-tauri/src/browser/bridge.rs          OPS 白名单加 'html'
core/desktop/src-tauri/src/browser/mod.rs             + browser_html 命令（只读、无 human-owned 闸门）
core/desktop/src-tauri/src/main.rs                    generate_handler 注册
core/ui/src/browser/agentBridge.ts                    ALLOWED_COMMANDS 加 'browser_html'

core/src/lamtools_core/browser/search/__init__.py     对外导出
core/src/lamtools_core/browser/search/dom.py          HTML 片段 → 轻量 DOM → 卡片候选
core/src/lamtools_core/browser/search/urls.py         URL 清洗/中转解包/去重键
core/src/lamtools_core/browser/search/text.py         文本规范化
core/src/lamtools_core/browser/search/adapters/       google.py / bing.py / baidu.py / generic.py
core/src/lamtools_core/browser/search/pipeline.py     卡片 → SearchResult（清洗、配对、去重、校验）
core/src/lamtools_core/browser/search/engine.py       编排：开页 → 等待 → 提取 → 降级 → 状态
core/src/lamtools_core/browser/search/sessions.py     搜索会话与结果 ID
core/src/lamtools_core/browser/search/reader.py       正文读取与分段
core/src/lamtools_core/browser/tools.py               + search / open_result / read_page / inspect_page
core/src/lamtools_core/tool/operation_levels.py       新增动作分级
core/src/lamtools_core/tool/default_toolbox.py        schema 与描述更新

core/tests/test_browser_search_adapters.py            适配器 + 清洗（HTML 样本驱动）
core/tests/test_browser_search_engine.py              编排、降级、状态、会话、缓存
core/tests/fixtures/search/*.html                     三引擎真实结构样本 + 验证码页 + 空结果页
```

### E.4 步骤与验证

1. **页面读取通道**：桥 `html` 指令 + Rust `browser_html` + 前端白名单。
   验证：`cargo test`（bridge 白名单/参数校验）通过；`browser_html` 出现在 `generate_handler`；Python 工具能排到 `browser_html` 请求。
2. **清洗核心**：`dom.py` / `text.py` / `urls.py` / `models.py`。
   验证：pytest 覆盖 URL 中转解包（Google `/url?q=`、百度 `link?url=`、Bing `ck/a?u=`）、追踪参数剔除、未知参数保留、去重键。
3. **三引擎适配器**：选择器优先级 + 特殊卡片 + 广告标记 + 分页 + 受阻识别。
   验证：每引擎 HTML 样本 → 断言标题/摘要/链接**配对**、广告不与自然结果混排、分页能取到下一页。
4. **统一协议与编排**：`SearchResponse` 的 `status`（ok/empty/blocked/failed）、`extractionMode`（l1/l2/l3）、`diagnostics`、`nextPage`。
   验证：状态矩阵测试（成功/无结果/验证码/选择器全失效各一例）。
5. **Agent 接口**：`search` / `open_result` / `read_page` / `inspect_page` 四个动作 + 分级 + schema。
   验证：假宿主（复用 `test_browser_agent_tools.py` 的队列扮演）跑通四个动作；注册与分级断言。
6. **降级**：L1 结构识别失败 → L2 通用语义 → L3 视觉证据；每级都有可断言信号。
   验证：坏页面样本触发 L2 并给出 `extractionMode: l2`；L2 也失败时 `status=failed` 且带截图路径（假宿主返回）。
7. **真机端到端**：桌面里对三引擎各跑一次真实搜索并记录质量数字。
   验证：§12 指标表填真实数字；未跑之前该行保持「未验证」。

---

## Part F｜打勾清单（边实现边勾）

> 打勾依据都是可重复执行的测试，测试名写在括号里（文件：`core/tests/test_browser_search_adapters.py`、
> `core/tests/test_browser_search_engine.py`）。只有真机（真实网页 + 真实桌面端）能证明的项单独标注，
> 在跑过之前保持空格——不拿「看起来对」冒充「验证过」。

### F.1 §13 完成标准

- [x] Google、Bing、百度搜索均可通过统一接口调用。
      （`test_search_accepts_explicit_engine_and_forwards_page`、`test_blocked_engine_is_skipped_and_next_engine_still_answers`；
      三引擎结构样本 `core/tests/fixtures/search/google_results.html`、`bing_results.html`、`baidu_results.html`）
- [x] 普通搜索无需视觉模型参与。
      （`test_search_returns_structured_results_with_session_ids` 全程只有 open/wait/html 三条指令，没有截图；
      截图只出现在 `status=failed` 的 `test_unparseable_page_records_screenshot_and_reports_failure`）
- [x] 原始页面噪声不直接进入 Agent 上下文。
      （`test_navigation_footer_and_sidebars_never_reach_the_payload`：导航/页脚/侧栏文字不出现在结果里，
      卡片 HTML 压缩率 ≥50%）
- [x] 标题、摘要、URL 正确归属。
      （`test_bing_cards_pair_their_own_title_snippet_and_url`、`test_google_unwraps_redirect_and_keeps_meaningful_query_params`）
- [x] URL 清洗不会破坏正常链接。
      （`test_url_cleaning_never_touches_unknown_parameters`：未知参数与签名原样保留，只删跟踪参数）
- [x] 支持分页、去重及结果类型标识。
      （`test_pagination_advances_page_parameters`、`test_bing_duplicate_card_is_dropped_not_merged_with_other_pages`、
      `test_baidu_separates_ads_and_marks_special_cards`）
- [x] Agent 能打开结果并继续读取网页。
      （`test_tool_search_and_read_page_round_trip`、`test_open_result_reuses_one_result_tab`）
- [x] 专用适配器失效后能够自动降级。
      （`test_adapter_miss_falls_back_to_generic_extraction` 验 L2；`test_unparseable_page_records_screenshot_and_reports_failure` 验 L3）
- [x] 验证码、网络错误和解析失败可准确区分。
      （`test_baidu_block_page_is_detected_as_captcha`、`test_captcha_on_every_engine_reports_blocked_without_inventing_results`、
      `test_empty_result_page_is_not_reported_as_failure`、`test_unparseable_page_records_screenshot_and_reports_failure`）
- [x] 不影响用户现有浏览器标签页。
      （机制：搜索永远 `browser_open` 新标签；`open_result` 只复用本会话自己的结果标签，
      `test_open_result_reuses_one_result_tab` 断言不会多开。真机确认「用户正在看的标签不动」仍待补）
- [x] 有可重复执行的测试及质量记录。
      （离线 43 例 + 现有 browser 工具 21 例 + 桌面契约 4 例；质量数字见 F.3）

### F.2 §11 关键测试场景

- [x] Google 搜索 "bilibili" → 标题/摘要/网址正确。（`test_google_unwraps_redirect_and_keeps_meaningful_query_params`，结构样本）
- [x] Bing 中文长句 → 原查询完整传递。（`test_query_is_passed_through_whole_without_splitting`，三引擎都验）
- [x] 百度中文关键词 → 自然结果与特殊卡片区分。（`test_baidu_separates_ads_and_marks_special_cards`）
- [x] 长追踪 URL → 清噪声、留目标。（`test_bing_cards_pair_their_own_title_snippet_and_url`、`test_url_cleaning_never_touches_unknown_parameters`）
- [x] 含广告结果页 → 标记正确、不混入自然排名。（`test_bing_drops_ads_by_default_and_marks_them_when_requested`）
- [x] 多站点链接 → 归属正确。（`test_bing_cards_pair_their_own_title_snippet_and_url` 里的 sitelinks 归属断言）
- [x] DOM 改版 → 进通用提取。（`test_adapter_miss_falls_back_to_generic_extraction`）
- [x] 验证码页 → 受阻状态、无伪结果。（`test_captcha_on_every_engine_reports_blocked_without_inventing_results`）
- [ ] 用户切换标签页 → 不影响后台任务。**真机待验**：需要桌面端在跑，人工切标签同时看搜索是否照常。
- [x] 打开搜索结果 → 能读正文。（`test_tool_search_and_read_page_round_trip`、`test_article_reader_drops_navigation_and_keeps_structure`）
- [x] 空结果 → 与解析失败区分。（`test_empty_result_page_is_not_reported_as_failure` vs 解析失败用例）
- [x] 并发多搜索 → 上下文与 ID 不串扰。（`test_concurrent_searches_do_not_mix_sessions_or_ids`）

### F.3 §12 质量记录（真机填数）

| 指标 | 目标 | 实测 | 证据 |
|---|---|---|---|
| 正常结果页提取成功率 | ≥95% | 未验证（需真机） | — |
| 标题与链接正确配对率 | ≥99% | 未验证（需真机） | — |
| 无关文本压缩率 | ≥80% | 未验证（需真机） | 离线样本 ≥50% 已断言 |
| 常规搜索视觉模型调用 | 0 次 | 0（代码路径上不会截图） | 引擎测试无 `browser_screenshot` 调用 |
| 单页提取+清洗 P95 | ≤500ms | 未验证（需真机） | — |
| 失败状态识别 | 不允许伪装成功 | 已实现四种状态且都有用例 | F.1 第 9 条 |

**怎么填这张表**：在 dev 窗口里直接让 Agent 搜一次，`browser.search` 的返回里就带着填表所需的全部字段：

```
搜索 bilibili（引擎 auto，10 条）
→ 看返回的 status / engine / extractionMode / elapsedMs / counts.compression / counts.returned / attempts
```

`elapsedMs` 就是「DOM 提取与清洗」这一段（不含网页加载），拿它记 P95；`attempts` 里能看到每个引擎的死活。
某个引擎不对时，把那一页 Ctrl+S 另存成 HTML，用离线复现脚本对着改选择器（不重启、不联网）：

```
python core/scripts/browser_search_extract.py --html E:/tmp/bing.html --engine bing
```

它会打印：取回多少片段、每张卡片的标题/地址/摘要、哪张被判广告、中转未解的条目、以及
`cards/invalid/duplicate/sponsored/compression` 统计——适合边看边调。

### F.4 离线验证记录（本轮已跑）

| 命令 | 结果 |
|---|---|
| `python -m pytest tests/test_browser_search_adapters.py -q --allow-dirty` | 20 passed |
| `python -m pytest tests/test_browser_search_engine.py -q --allow-dirty` | 23 passed |
| `python -m pytest tests/test_browser_agent_tools.py tests/test_browser_approval_chain.py -q --allow-dirty` | 21 passed（既有能力无回归） |
| `python -m pytest tests/test_default_toolbox.py -q --allow-dirty` | 通过（工具目录与 schema 无回归） |
| `cargo check`（`core/desktop/src-tauri`） | 通过（仅既有 warning） |
| `cargo test --manifest-path core/desktop/browser-assert/Cargo.toml` | 4 passed（含「每条 browser 命令都已注册且进入 Agent 桥白名单」） |

### F.5 改动的文件（本轮）

| 文件 | 改动 |
|---|---|
| `core/desktop/src-tauri/src/browser/bridge_script.js` | 新增固定指令 `html`：按选择器取回清洗后的 DOM 片段 + 页面文本前缀 |
| `core/desktop/src-tauri/src/browser/bridge.rs` | 页面应答的 `op` 白名单加入 `html` |
| `core/desktop/src-tauri/src/browser/mod.rs` | 新增只读命令 `browser_html`（选择器数量/长度/体积三重上限，超时自动前台重试一次） |
| `core/desktop/src-tauri/src/main.rs` | 注册 `browser::browser_html` |
| `core/ui/src/browser/agentBridge.ts` | Agent 桥白名单加入 `browser_html` |
| `core/desktop/browser-assert/tests/security_assert.rs` | 命令清单扫描跳过 `#[cfg(test)]`（修掉测试函数名造成的假红） |
| `core/src/lamtools_core/browser/artifacts.py` | 截图落盘共用实现 |
| `core/src/lamtools_core/browser/search/` | 新增：`models` / `dom` / `text` / `urls` / `pipeline` / `engine` / `reader` / `sessions` / `adapters/*` |
| `core/src/lamtools_core/browser/tools.py` | 新增 `search` / `open_result` / `read_page` / `inspect_page` 四个动作与参数 |
| `core/src/lamtools_core/tool/operation_levels.py` | 四个动作分级（均为只读 1 级） |
| `core/tests/test_browser_search_adapters.py`、`core/tests/test_browser_search_engine.py` | 新增 43 例回归 |
| `core/tests/fixtures/search/*.html` | 三引擎结构样本 + 验证码页样本 |
| `core/src/lamtools_core/browser/search/dom.py` | 文本按 DOM 交错顺序收集（`flow`）：搜索引擎 `<strong>` 高亮词不再被挪到标题末尾 |
| `core/src/lamtools_core/browser/search/engine.py` | 结果容器 + `load` 两次等待、空提取重取一次、L2 置信度闸门、查询覆盖率（`lowRelevance`/`weakMatch`） |
| `core/src/lamtools_core/browser/tools.py` | `read_page` 拒绝把搜索结果页当正文（`kind=search_results_page`），并支持 `session`+`resultId` 直读 |
| `core/scripts/browser_search_extract.py` | 离线复现脚本：把另存下来的结果页 HTML 喂给适配器，打印提取结果与统计（调选择器用） |

### F.6 真机排查：「搜索只回一条、像是被截成首词」

user:“是不一样了吧”“是被分词截断的只剩 DeepSeek 了”“优先保证查询正常可用，不被分词等异化”+
(真机里同一个查询，Agent 只拿到 1 条、全是某品牌官网，看起来像查询被引擎拆成了首词。
逐层查下去，根因不在引擎的分词，而在「我们怎么取页面」这条链上，一共四层)。

**实测判据**：正常结果页应是 10 条自然结果（`cards=10, returned=10`、`diagnostics` 为空）。
出问题时表现为 `cards=1`，且诊断里出现 `thinNodes` / `engineMiss` / `l2Fallback`。

**四层根因（按发现顺序，全部已修）**

| # | 根因 | 表现 | 修复 |
|---|---|---|---|
| 1 | 直接导航到结果地址 | URL 被引擎改写成 `rdr=1&rdrig=…`，掉进「导航卡」版式 | 改走真人路径：引擎首页 → 在它自己的搜索框里输入 → 回车（`_human_search`） |
| 2 | 表单默认按钮被设成「热门内容」入口 | URL 出现 `form=BHPPHT&…Segment="popularnow.carousel"`，整页只有一两张卡 | 提交前把表单 `form` 字段拨回搜索入口 `QBRE`（`search_form_value`），并让 `browser_act` 支持 `formValue` |
| 3 | 只抓一次、页面还没渲染完 | `cards` 时多时少、结果不稳定 | 「条数太少且集中在一个站点」也重取一次（`EMPTY_RETRY_DELAY = 1.2`） |
| 4 | **每个片段的字符预算太小** | 命中结果容器时整页只有一份片段，按默认 12000 字符截断只装得下一条半结果 | L1 提取给容器 40000 字符 / 150000 总量，与通用兜底对齐 |

**另外还修了三处，让提取器本身更稳**

- **容器不能被当成单张卡**：命中 `#b_results` / `#rso` 的片段按结构展开（`pipeline.extract`）。
- **选择器要取候选最多的那组**：原来「第一个命中的选择器就返回」，Bing 的 `li.b_ans` 摘要卡先命中就只剩 1 条；改成和「标题 + 链接 + 一段话」的祖先块比数量，谁多听谁的（`_discover_cards`）。
- **补上 Bing 另一版容器 `#rso`**：有些版式根本没有 `#b_results`，结果挂在 `#rso` 下。

**通道层（不是引擎问题，但会让搜索整体失败）**

- `drain()` 串行执行，某条命令的 `invoke` 不返回就会把锁占死，之后所有浏览器指令都撞「桌面应用没有响应」。已给每条命令加 30 秒硬超时（`COMMAND_TIMEOUT_MS`），到点写回失败并释放锁。
- 「没人认领」门槛从 3 秒放宽到 20 秒（首次开网页要初始化 WebView2 环境，实测能慢到十几秒）。

**验证（dev 真机，三条查询，`refresh=true`）**

| 查询 | counts | diagnostics | 前几条来源 |
|---|---|---|---|
| DeepSeek 4.2 Flash 发布时间 | cards=10 / returned=10 | 空 | deepseek.com、IT之家、新浪财经、知乎 |
| 中央经济工作会议 2026年经济工作 部署 重点任务 | cards=10 / returned=10 | 空 | 百度百科、新浪财经、发改委、搜狐、商务部 |
| 十五五规划纲要 主要目标 2026年两会 通过 全文 | cards=10 / returned=10 | 空 | gov.cn、新华网、观察者网 |

**遗留**：dev 重启后的第一次搜索仍可能因为首次创建网页较慢而超时，第二次起稳定。
这不是引擎问题，是 WebView2 首次初始化耗时；`CLAIM_TIMEOUT` 已放宽到 20 秒仍偶发，暂不改更多。

**不属于问题、也不打算做的**：AI 摘要块（`answer`）。
user:“AI摘要没有就没有，优先保证查询正常可用”+(摘要只做「页面里真有就取」，取不到返回 null，不追求)。
