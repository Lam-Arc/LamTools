# RAG 插件设计规格（lamtools-rag）v2

> 日期：2026-08-15（v2 修订）
> v2 变更：① 文档解析改为 **format router**（数字 PDF 确定性提取 / 其余 VLM 页面图批量理解），独立 OCR 环节取消；② 表格**文本化 + citation target**，无多模态向量；③ 新增**会话历史检索**（独立 `rag_search_sessions` 工具 + source 维度 + 消息级数据模型）；④ 新增**附件/产物元数据**索引。
> 前置：`docs/plugin-system-rework.md` 落地后启动；复盘见 `docs/rag-design-qa.md`
> 原则：整个 RAG 类功能插件化，core 零 RAG 依赖；embedding 等重依赖可选安装、可降级。

---

## 1. 形态与发布（2026-08-16 决策更新：随主仓库走，不单开独立仓库）

- **随主仓库发布**：源码位于仓库 `plugins/lamtools-rag/`，与 LamTools 主版本同发布链（tag `vX.Y.Z` → `release.yml` 构建时把插件目录打成 `lamtools-rag-vX.Y.Z.zip` 挂到 Release 资产）。
- **安装途径**（用户侧，插件系统已支持，B7）：插件管理 UI → 安装 → GitHub Release URL / 本地 zip / 本地目录；`plugin.install` 自动装依赖（pip 装入 core 运行环境）。
- **为什么不打进 Tauri 安装包**：与"安装器不打包 `.lam`"同源的 NSIS 覆盖语义——插件若放程序目录内置位，用户升级安装包会被抹掉；**用户级插件根（`%APPDATA%/LamTools/plugins/`）才是正确落点**（H 组已修复默认可见）。
- **版本同步**：插件 `plugin.json` version 与主仓库 tag 同步（bump-version.ps1 时一并 bump）。
- **许可与信任**：插件 = 可执行代码（工具 handler + VLM 调用），安装时显式信任提示。

## 2. 插件结构

```
lamtools-rag/
├── plugin.json              # name/version/skills/tools/dependencies/configSchema
├── skills/
│   ├── rag-indexer/SKILL.md        # 建立：低频/批量/审批/范围参数
│   │   └── references/             # 建库协议/断点续跑/范围语义
│   └── rag-for-agent/SKILL.md      # 查询与回答：高频/引用规范/答案闸门/对比流程
│       └── references/             # 引用格式/检索协议/scope 语义
├── tools/tools.jsonc       # 工具清单（见 §4）
├── config/schema.jsonc     # 插件配置 schema（embeddingSource / autoRoots / vlm 等）
├── rag_engine/             # 纯 Python 引擎（依赖 sqlite-vec）
│   ├── router.py           # format router：文档类型判定与分流（§3）
│   ├── extract.py          # 确定性解析（pypdf / python-docx / xlsx，复用 document_normalize 管线）
│   ├── vlm.py              # VLM 页面图批量理解（JSON schema 结构化输出）
│   ├── chunker.py          # 分片（结构锚点 + token 预算）
│   ├── indexer.py          # 入库（workspace_doc / artifact 元数据）
│   ├── session_indexer.py  # core.db 只读 → 会话消息分块入库（水位增量）
│   ├── retriever.py        # FTS5 + vec0 混合召回（source/scope 过滤）
│   ├── citation.py         # 引用校验（submit_answer 闸门）
│   └── aggregate.py        # 确定性聚合（SQL count）
├── hooks/hooks.json        # Stop → 会话结束索引；PostToolUse 补引用块；UserPromptSubmit 注入引用要求
└── requirements.txt        # sqlite-vec, fastembed(可选), onnxruntime(可选)
```

**Skill 分两类（已共识）**——共享底层引擎，协议与可见性分组分开：

| 维度 | rag-indexer | rag-for-agent |
|---|---|---|
| 触发 | "给 XX 范围建 rag"（低频、批量、要审批） | 提问（高频、轻量） |
| 权限面 | `rag_index` / `rag_extract` = ASK_USER | `rag_search` / `rag_search_sessions` / `rag_read` / `submit_answer` = AUTO_ALLOW |
| 上下文 | 分开加载 → 每次查询不注入建库协议 | 查询不注入建库协议 |
| 运行 | 支持 headless / CLI 批量 | 绑定会话 |

## 3. 文档解析：format router（v2 核心）

### 3.1 路由判定

| 判定 | 路径 | 实现 |
|---|---|---|
| 文本层完好的数字 PDF / DOCX / XLSX | **确定性提取**（无损、秒级） | `extract.py`：pypdf / python-docx / xlsx 解析 |
| 扫描件（文本层空或覆盖率低）/ 图表密集 / 复杂版面 | **VLM 页面图批量理解** | `vlm.py` |

- 判定指标：pypdf `extract_text` 非空字符比例阈值（默认 >60% 走文本路径，可配置）；低于阈值转 VLM。
- **独立 OCR 环节不存在**——扫描件由 VLM 直接读图（原设计"OCR + 多模态转写"取消，统一为 VLM 路径）。

### 3.2 VLM 调用规格

- 输入：页面渲染图（批 8-30 页，多图拼接 + 页码标注），本地（ollama/vllm）或 API，**复用现有多模态模型配置**（`default_multimodal_model`，走 llm client，继承重试/profiling）。
- 输出 JSON schema（一次调用产出全部，**无独立摘要 pass**）：

```jsonc
{
  "pages": [{
    "page": 12,
    "heading_chain": "第三章/违约责任",
    "blocks": [{"type": "paragraph|table|list", "content": "..."}],
    "tables": [{"header": ["条款", "内容"], "summary": "...", "markdown": "|...|"}],
    "summary": "本页要点",          // 块级上下文（prev/next 摘要由同批产出）
    "metadata": {"source": "scanned", "confidence": 0.9}
  }]
}
```

- 成本模型：8 页/批 ≈ 8-12k 图像 token + 1-2k 输出；1w 页 ≈ 1250 批；本地 ~120 tok/s ≈ 10 小时单机（一次性+增量可断点续跑）；个人用户常见 30 页/批 ≈ 1.5 分钟。
- 失败页标记 `ocr_failed`（status 字段），检索结果显式提示，不静默漏检。

### 3.3 残余风险与缓解（诚实记录）

- **扫描件引用校验循环性**：VLM 输出是唯一事实源，"引用 vs 索引文本"校验成立，但无法校验"索引文本 vs 原件"。缓解：**抽样人工核对**（首月每 100 页抽 1 页）+ 可选**高相关块二次 VLM 复核**。
- **VLM 数字误读**（"30%"→"3%"）：数字类断言在 submit_answer LLM 层做强化校验；高价值文档（合同/审计）建议走确定性路径。

## 4. 工具族与权限（v2 更新）

| 工具 | 权限 | visibility | 职责 |
|---|---|---|---|
| `rag_index` | ASK_USER | on_load（rag-indexer） | 全量/增量建索引（范围参数、断点续跑、进度） |
| `rag_extract` | ASK_USER | on_load（rag-indexer） | 表格/图片结构化提取（VLM 批量） |
| `rag_search` | AUTO_ALLOW | on_load（rag-for-agent） | 工作区文档检索（scope: `docs` 默认 / `artifact` 元数据） |
| `rag_search_sessions` | AUTO_ALLOW | on_load（rag-for-agent） | **会话历史检索**（独立工具，LLM 自主选用，无正则路由） |
| `rag_read` | AUTO_ALLOW | on_load（rag-for-agent） | 读取指定文档页（带页码定位） |
| `submit_answer` | AUTO_ALLOW | on_load（rag-for-agent） | 答案闸门：提交带引用的最终答案，校验不过打回 |

- **工具描述即路由**：`rag_search_sessions` 的描述明确"当问题涉及历史会话 / 之前讨论过 / 上次说过时使用"，与 `rag_search` 的分工靠描述表达——模型自主选择，不依赖正则识别"之前/上次"（正则脆弱）。
- **配套 RPC operation**：`rag_search_sessions` 另有 operation 形态 `rag.sessions.search`（UI 全局搜索直调，共用检索内核，见 §8.4）——工具走 agent 链路，operation 走 UI 链路，同一内核两个出口。
- 权限三层照常：manifest 逐工具 `PermissionTier` + `access_tools.jsonc` 档位
  （read_only 含全部 AUTO_ALLOW 工具；limited/full 才含 `rag_index`/`rag_extract`）+ ApprovalGate 硬规则。
- 惰性暴露：两类 skill 各自暴露自己的工具，模型可见列表 = 基础工具 + 已加载 skill 的工具，零膨胀。

## 5. 检索底座：sqlite-vec（FTS5 + vec0 同库，+ source 维度）

- 选型不变（实测 2026-08：sqlite-vec 0.1.10 纯 wheel / faiss 1.15.0 cp314 备选 / chroma 依赖重 3.14 未验证弃 / lancedb 不支持 3.14 排除）。
- 索引库：`.lamtools/rag-index/rag.db`，**混合检索**：FTS5 全文（BM25）+ vec0 向量同库；中文用 **trigram 分词器**（unicode61 不切中文，环境实测必测项）。
- 检索支持 **source/scope 过滤**：`scope=docs|sessions|artifact` + 元数据过滤器（session_id/role/time_range/文档类型）。
- 环境实测清单（开发第一件事）：① sqlite-vec 与 Python 3.14 内置 SQLite 3.50 兼容；② onnxruntime 3.14 兼容（fastembed 底座）；③ FTS5 trigram 中文切分效果；④ Windows 打包下扩展 .dll 收集。实测不过按序切 faiss。

## 6. 数据模型（v2 完整 DDL）

```sql
-- ① 文档/语料表（source 维度）
documents(
  doc_id TEXT PRIMARY KEY,          -- workspace_doc: sha256(文件)；session: 'session:{session_id}'
  source TEXT,                      -- workspace_doc | session_history | artifact
  path TEXT,                        -- 工作区相对路径 / 会话无路径为空
  title TEXT,                       -- 文件名 / 会话标题
  sha256 TEXT,                      -- 指纹（增量检测）
  mtime REAL,                       -- 修改时间 / 最后消息时间（增量用）
  document_format TEXT,             -- pdf/docx/xlsx/md/txt/session/artifact
  pages INTEGER,
  status TEXT,                      -- indexed | ocr_failed | unindexed | partial（会话进行中）
  indexed_at REAL,
  version INTEGER                   -- 重索引递增（"索引版本"）
)

-- ② 块表（检索原子单位；会话历史复用同一张表）
chunks(
  chunk_id INTEGER PRIMARY KEY,
  doc_id TEXT REFERENCES documents(doc_id),
  source TEXT,                      -- 冗余 source（分区过滤）
  chunk_index INTEGER,              -- 块在文档内序号 / 会话内消息序号
  turn_index INTEGER,               -- 会话：轮次序号（同轮 user/assistant 相同）；文档：0
  message_id TEXT,                  -- 会话：消息 id（core.db 主键；跳转定位锚点，UI 点击卡片跳转用）
  role TEXT,                        -- 会话：user | assistant；文档：NULL
  page INTEGER,                     -- 页号（1-based）
  char_offset INTEGER,              -- 页内字符偏移
  heading TEXT,                     -- 标题链锚点（"第三十条/违约责任"）
  block_type TEXT,                  -- paragraph|heading|table|list|user_msg|assistant_msg
  context TEXT,                     -- 块正文（检索返回的原文片段/消息正文，含引用标记）
  tool_names TEXT,                  -- 会话：该轮工具调用名列表（JSON，正文不索引）
  ts REAL,                          -- 会话：消息时间
  tokens INTEGER,                   -- 估算 token（预算裁剪）
  table_id TEXT,                    -- 关联表格提取产物（citation target）
  image_id TEXT,                    -- 关联图片/扫描页资产（citation target）
  emb_source TEXT                   -- local|api|none（BM25-only 时 none）
)

-- ③ FTS5 全文虚拟表（BM25；中文 trigram）
CREATE VIRTUAL TABLE chunks_fts USING fts5(
  context, heading,
  chunk_id UNINDEXED, doc_id UNINDEXED,
  source UNINDEXED, role UNINDEXED, page UNINDEXED
);

-- ④ vec0 向量虚拟表
CREATE VIRTUAL TABLE chunks_vec USING vec0(
  chunk_id INTEGER PRIMARY KEY,
  embedding float[512] distance_metric=cosine
);

-- ⑤ 结构化提取产物（表格/图片 + citation target）
extractions(
  extraction_id TEXT PRIMARY KEY,
  doc_id TEXT, page INTEGER,
  kind TEXT,                        -- table | image | page_scan
  raw TEXT,                         -- markdown 表格 / 资产路径
  structured TEXT,                  -- VLM/解析器的 schema 输出（JSON）
  model_id TEXT, created_at REAL
)
```

**分片规则**（文档侧）：层级 文档→页→块；块边界 = 标题/段落锚点（块不跨标题，合同"第X条"整条一块）；默认 300-500 tokens（评测集定）；合同场景关闭 overlap（锚点天然分界）。会话侧：**按消息分块**（见 §8）。

## 7. Embedding：双模式 + 降级

- 配置：`embeddingSource: "local" | "api"`（插件配置，默认 local——合同类敏感数据不出本机）。
- **local**：fastembed（onnxruntime 底座，无 torch）+ `BAAI/bge-small-zh-v1.5` onnx（≈30-100MB）；模型首次下载缓存。
- **api**：provider `/embeddings` 端点——新增 embedding adapter（`llm/profiles.py` 目前只有 chat payload；模型配置加 embedding 类型字段）。
- **降级路径（装不齐也能跑）**：sqlite-vec 缺失 → 报错附安装命令；fastembed/onnxruntime 缺失 → 降级 **BM25-only**（FTS5 仍可用）或提示切 api。
- 会话历史块同样走 embedding（与文档同一向量空间，可跨 scope 语义检索——但默认不混合，见 §8）。

## 8. 会话历史检索（v2 新增）

**需求**：搜索支持 DB 内查询——会话历史（核心）+ 附件/产物元数据。记忆（core_memories）不纳入（已有加载进 prompt 的机制）。

### 8.1 粒度决策：按消息分块 + turn_index 关联

- **不是按模型调用**：中间调用 = 推理 + 工具参数（可能含密钥）+ 工具结果（可能巨大）——安全与成本双风险，且搜索语义不落在中间调用；
- **不是整轮一块**：user/assistant 揉一起，角色过滤做不到，块偏大；
- **按消息**：user 消息一块、assistant 最终回答一块，同轮同 `turn_index`——角色可过滤、命中精确、可 small-to-big（命中消息 → 返回整轮上下文）。

**索引规则**：

```
user 消息                → 入库（role=user）
assistant 最终回答       → 入库（role=assistant，保留引用标记原文）
带 tool_calls 的中间消息 → 不索引正文，工具名列表记入同轮元数据（tool_names）
tool 角色消息            → 不入库
```

### 8.2 触发与增量

- 触发：**会话 Stop（插件 hook）** 批量读 core.db（同进程只读，sqlalchemy 现成依赖）→ 分块 → 入库；会话进行中 status=partial。
- 增量：`last_message_id` 水位，只索引新增消息；幂等（消息 id 唯一）。
- 元数据：会话标题、开始/结束时间、消息时间、角色。

### 8.3 工具形态

- **独立工具 `rag_search_sessions(query, filters={session_id, role, time_range}, top=10)`**（AUTO_ALLOW，on_load rag-for-agent）。
- **无正则路由**：工具描述驱动 LLM 自主选用（"当问题涉及历史会话/之前讨论过/上次说过时使用"）。工具描述即行为契约。
- 默认 scope 分离：普通问题只搜工作区文档（`rag_search`）；历史问题走 `rag_search_sessions`——历史不污染默认召回，行为可预期。

### 8.4 前端入口：全局搜索对话框（用户拍板）

- **入口形态**：Ctrl+K 全局搜索对话框（core/ui 组件），**UI 直搜，不经 agent**。
- **RPC 面**：UI 不能直接调工具（工具执行走 kernel/toolbox）——插件额外暴露 **operation `rag.sessions.search`**，与工具共用同一检索内核（`retriever.query(source="session_history")`）。
- **跳转链路**：结果卡片（会话标题 / 时间 / 角色徽标 / 高亮片段）→ 点击 → 打开会话（session_id）→ 定位消息（**message_id 锚点**，chunks 表已存）→ `scrollIntoView` + 高亮渐隐（2-3s）。
- **虚拟滚动/懒加载**：会话消息未全部渲染时，打开会话需支持"带 target_message_id 定位到消息窗口"。
- **UI 能力归属**：搜索对话框 + 结果卡片渲染在 core/ui（通用"可定位结果"机制）；插件只提供数据。
- **依赖**：插件系统改造需支持「插件声明 operations」（见 `plugin-system-rework.md` §2/§3）——`rag.sessions.search` 是第一个消费方。

## 9. 附件/产物元数据（v2 新增）

- 范围：attachments（`data_dir/attachments/<session>/`）与 artifacts 的**元数据级**索引：文件名、扩展、大小、所属会话、时间、文本预览（`read_text_preview` 先例）；正文不强制入索引（工作区文档已由 docs 覆盖）。
- 入库：documents(source=artifact) + chunks（context = 文件名 + 元数据 + 文本预览）。
- 检索：`rag_search(query, scope="artifact")`——支持"找一下上周上传的文件"类查询；citation target 指向原文件路径。

## 10. 索引时机：自动 + 手动

- **自动**：`autoRoots` 配置（项目内子目录白名单，如 `["docs/contracts"]`）——会话启动增量扫描（sha256/mtime 变更检测），**仅限白名单范围**；长任务 JSONL 进度 + 断点续跑。
- **手动**：会话内自然语言指令（"给 docs/contracts 建 rag"）→ load rag-indexer → `rag_index` 工具（范围参数，ASK_USER 审批一次）。
- **会话历史**：Stop hook 自动触发（§8.2）。
- 查询路径永不现解析/OCR/VLM/embedding——重活全在索引期。

## 11. 防幻觉：答案闸门（submit_answer）+ 辅助 hooks

**机制**（不变）：`submit_answer`（AUTO_ALLOW）工具——模型最终回答前必须调用，提交"答案 + 引用列表（页码 + 原文精确片段）"；内置校验器：规则层（引用格式合法、原文片段与索引文本一致）+ 可选 LLM 层（断言与引用支持关系核对）；失败 → blocked/failed 回填 → 模型自纠（现有 loop 语义）。

**v2 更新（确定性 vs 循环性）**：

- **数字 PDF**（确定性提取路径）：索引文本 = 原件事实，规则层可精确校验（页码 + 原文一致）——强保证；
- **扫描件**（VLM 路径）：规则层校验"引用 vs 索引文本"成立，但存在**源头循环性**（VLM 读的 → 校验 VLM 读的）——LLM 层强化（数字断言二次核对）+ 抽样人工核对兜底（§3.3）。

**辅助 hooks**（插件声明，逐条信任）：PostToolUse 给 rag 工具结果补引用块；UserPromptSubmit 注入引用要求；PermissionRequest 对 `rag_index`/`rag_extract` 审批裁决；**Stop → 会话历史索引触发**。

**输出规范**：检索结果返回 Top-N（默认 10）+ 每项 `(doc_id, page, char_offset, heading, context)` 定位；最终答案强制页码 + 原文精确片段引用。

## 12. 评测

| 层 | 方法 |
|---|---|
| RAG 链路质量 | RAGAS 四维（faithfulness / answer relevancy / context precision / context recall），适配本地模型 |
| 行为指标 | 引用合规率（submit_answer 一次通过率）、检索工具调用成功率、**scope 路由正确率**（历史问题是否被正确路由到 rag_search_sessions）、任务完成率 |
| golden 集 | 自建 50-100 问（答案 + 引用标注），覆盖 char/context/page 三维 + **会话历史检索**（"上次讨论的结论"类）|
| LLM-as-judge | 复用 `runtime/goal.py:192` `ModelGoalEvaluator` 模式；Cohen's κ 校准 |

**会话历史检索评测**：golden 集含历史类问题（检索目标 = 特定会话/消息）；指标 = 消息级 recall@k + 路由正确率。

## 13. 真实业务场景：1w 份合同 PDF（设计验证）

**输入**：1w 份合同 PDF（纯文本 + 扫描件混合）；**提问**："违约最多的三个条款是什么？"

**问题本质**：**穷尽统计型**（全量扫描 + 计数），**不是 top-k 召回型**——纯向量召回漏数必错。两阶段流水线：

```
Phase 1 批量抽取（LLM，并行）           Phase 2 确定性聚合（代码，不靠 LLM）
1w 份 → 分片 → worker 批量抽取           JSONL → SQL count 条款频次
每份输出 JSON：条款名/原文/是否违约/页码  → Top-3 条款 + 示例合同（带页码引用）
→ .lamtools/rag-index/contracts.jsonl
```

- **v2 更新**：扫描件占比 → format router 批量分流（文本层走确定性提取、扫描件走 VLM 8-30 页/批）→ 统一文本进抽取；模板化合同优先"规则切条款 + LLM 判违约"（便宜一个数量级）。
- 抽取用 LLM、**计数用代码**——防幻觉根本。
- 并行限制规避：`sub_agent_runner.py:119` 同 agent 名串行锁 → 多 worker agent 名或批内循环。
- 成本量级：1w 份 × 每份抽取 ~1-2k token ≈ 10-20M 输入 token；扫描件 VLM 另计（§3.2）；sha256 缓存重跑不重复计费。
- 模拟验证：合成模板化合同语料（注入违约条款变体、答案可标注）→ 全链路跑通 → 标注答案算抽取 precision/recall + 聚合准确率 → 1w 规模压测（时间/成本/错误率）→ 验证报告（e2e/real-task-runs/ 先例）。

## 14. 已共识决策汇总（v2）

| # | 决策 | 结论 |
|---|---|---|
| 1 | 整个 RAG 功能 | 插件化（**随主仓库发布**，Release 资产 zip 分发；2026-08-16 从"独立仓库"变更），core 零 RAG 依赖 |
| 2 | Skill 组织 | 分两类：rag-indexer（建立）+ rag-for-agent（查询与回答）；内部树状、对外平铺检索 |
| 3 | 工具执行 | 原生工具注册（manifest 声明 + 注入 CoreToolbox），弃 run_command / MCP 路线 |
| 4 | 工具膨胀 | 惰性暴露（visibility=on_load 跟随 skill 加载），零膨胀 |
| 5 | 权限 | 逐工具 PermissionTier + access_tools.jsonc 档位 + ApprovalGate |
| 6 | 检索底座 | sqlite-vec（FTS5 + vec0 同库混合，中文 trigram）；实测不过切 faiss 1.15.0 |
| 7 | embedding | 双模式 local\|api 可配，默认 local（fastembed/bge-small-zh，无 torch）；缺失降级 BM25-only |
| 8 | **文档解析** | **format router（v2）：文本层完好的数字文档确定性提取；扫描件/复杂版面 VLM 页面图批量理解（JSON schema 一次出结构+摘要+元数据）；独立 OCR 取消** |
| 9 | **表格** | **文本化（表头+摘要+markdown）按文本索引；citation target 回原表格；无多模态向量（v2）** |
| 10 | **会话历史** | **消息级分块 + turn_index；Stop hook 触发 + 水位增量；独立 rag_search_sessions 工具（描述路由，无正则）（v2）** |
| 11 | **DB 覆盖** | **会话历史（核心）+ 附件/产物元数据；记忆不纳入（v2）** |
| 12 | 索引时机 | autoRoots 白名单自动扫描 + 会话内手动指令；JSONL 断点续跑；查询路径永不现重活 |
| 13 | 防幻觉 | submit_answer 答案闸门（规则层 + 可选 LLM 层）+ 辅助 hooks；VLM 源头循环性风险显式记录与缓解 |
| 14 | 评测 | RAGAS 四维 + 自建 golden 集（含会话历史检索）+ 行为指标（含 scope 路由正确率） |
| 15 | 1w 合同场景 | 两阶段（worker 批量抽取 + 确定性 SQL 聚合）+ format router 分流 + 合成语料模拟验证 |
| 16 | **会话搜索入口** | **全局搜索对话框（Ctrl+K，core/ui 组件，UI 直调 operation `rag.sessions.search`，不经 agent）；跳转 = session_id 打开会话 + message_id 锚点定位 + 高亮渐隐（v2）** |
| 17 | 前置依赖 | 插件系统改造（`docs/plugin-system-rework.md`）落地后启动 |
