# LamTools 代码质量全面评估报告

> 评估日期：2026-06-17
> 评估范围：LamTools monorepo 全部源代码（core/、members/writer/、members/artist/、scripts/、e2e/、根目录）
> 评估依据：AGENTS.md 三原则 + 行业最佳实践（OpenAI/Claude/成熟开源项目）
> 评估方法：4 个并行子代理深度审查 + 联网调研 + 守护测试验证

## 目录

- [一、代码审查文档（交付 a）](#一代码审查文档交付-a)
- [二、技术调研文档（交付 b）](#二技术调研文档交付-b)
- [三、对比文档（交付 c）](#三对比文档交付-c)
- [四、客观评价文档（交付 d）](#四客观评价文档交付-d)
- [五、本次已处理的债务](#五本次已处理的债务)

---

## 一、代码审查文档（交付 a）

### 1.1 评估分类标准

| 分类 | 定义 | 处理策略 |
|------|------|----------|
| **可靠** | 与 OpenAI/Claude/成熟开源项目高度一致，属于经过验证的成熟方案 | 保留 |
| **存疑** | 完全或部分自研，但功能闭环完备，需联网调研是否有更成熟方案 | 调研后酌情更换 |
| **债务** | 增加复杂度无收益 / 误伤其它项 / 无用代码 / 负面收益 | 立即处理（减法优先） |

### 1.2 模块评估总览

| 模块 | 文件数 | 可靠 | 存疑 | 债务 | 整体评价 |
|------|--------|------|------|------|----------|
| `core/src/lamtools_core/` | 35+ | 高 | 4 项 | 3 项 | 架构优秀，Kernel/Kit 边界清晰 |
| `core/ui/` | 15+ | 高 | 0 | 4 项 | Vue3 标准实现，CSS 类名有产品名污染 |
| `core/tests/` | 20 | 高 | 0 | 2 项 | 覆盖度高，守护测试有 bug |
| `members/writer/backend/` | 60+ | 高 | 5 项 | 多项 | 核心代码成熟，tests/ 混入大量脚本 |
| `members/writer/frontend/` | 20+ | 高 | 0 | 1 项 | Vue3+Electron 标准实现 |
| `members/artist/backend/` | 40+ | 高 | 2 项 | 0 项（已清理） | ArtistKit 实现规范 |
| `members/artist/frontend/` | 15+ | 高 | 0 | 0 | Vue3 标准实现 |
| `members/artist/desktop/` | 5 | 高 | 1 项 | 1 项 | pywebview 标准桌面架构 |
| `scripts/` | 6 | 高 | 0 | 0 | 仓库最干净的部分 |
| `e2e/` | 5 + 20 夹具 | 可靠 | 0 | 全部 test-apps | smoke 测试规范，test-apps 是 agent 产物 |
| 根目录 | - | - | 2 项 | 多项（已清理） | 大量实验性 test-* 目录 |

### 1.3 可靠代码清单（带依据）

#### core/ 模块

| 代码 | 依据 |
|------|------|
| `kernel/loop.py`（940 行） | Core Loop Kernel 与 OpenAI Codex Agents SDK 风格一致：流式模型调用、并行/串行工具执行、历史压缩、cancel 信号、step 持久化、retry/backoff/timeout 分层 |
| `kernel/kit.py` | RuntimeKit Protocol 10 个生命周期方法，Kernel/Kit 边界清晰，符合 AGENTS.md 第 1 条 |
| `llm/adapter.py` + `llm/helpers.py` | OpenAI 兼容协议成熟实现，URL 规范化、payload 构建、流式 chunk delta 合并与 OpenAI 官方 SDK 行为一致 |
| `llm/policy.py` | BackoffStrategy + RetryPolicy 与 OpenAI/Anthropic SDK retry 设计一致 |
| `tool/permission.py` | 三层权限模型（auto_allow/ask_user/hard_block）是工具调用安全的标准设计 |
| `kernel/tracing.py` | Tracer Protocol + Noop/InMemory 实现，OpenTelemetry 风格 span |
| `test_kernel.py`（1537 行） | 覆盖 continue/wait/done/failed、tool failure、verification、max_steps、events、repair loop、cancellation |
| `test_kit_boundary.py` | 契约测试证明 RuntimeKit 只有协议桥接、无业务逻辑 |

**Python 层面产品名污染验证**：`core/src/lamtools_core/` 下无 `if product ==` 分支，Writer/Artist 仅在注释/docstring 中作为示例出现。`test_kernel_source_no_artist_writer_imager` 测试守护此原则。

#### members/writer/

| 代码 | 依据 |
|------|------|
| `app/utils/llm_client.py`（400 行） | 全局 aiohttp 连接池（TCPConnector limit=10/limit_per_host=5），双 API（OpenAI/Anthropic）支持，与官方 SDK 行为一致 |
| `app/services/task_manager.py`（167 行） | 单例 SSE pub/sub，每 session 一个 queue set，replay 最近 500 条，30s keepalive，与 FastAPI 官方 SSE 示例一致 |
| `app/core/writer/core_kernel_adapter.py`（2754 行） | 完整 WriterKit 实现，与 Core Kernel 对接，11 个测试场景覆盖 |
| `app/core/writer/completion_verifier.py` | 非 LLM 验证（python_compile/pytest/npm build/browser_e2e） |
| `frontend/src/composables/useSSE.ts` | readSSEStream 与 WHATWG Fetch Streaming 规范一致，支持 abort signal + [DONE] sentinel |
| `frontend/electron/main.cjs`（138 行） | findFreePort → startBackend → waitForHealth → createWindow，preload.cjs 使用 contextBridge 安全隔离 |

#### members/artist/

| 代码 | 依据 |
|------|------|
| `app/core/artist/core_kernel_adapter.py`（2049 行） | ArtistKit 完整实现 RuntimeKit 协议，业务逻辑（生图、修图、看图验收、lineage）全部留在 Kit 内部 |
| `app/utils/crypto.py`（63 行） | AES-256-GCM 标准库用法（cryptography.hazmat），文件种子方案合理解决桌面应用跨机器问题 |
| `app/main.py`（268 行） | 正确使用 create_app 工厂模式，MemberManifest 注册规范，图片代理含 SSRF 防护 |
| `desktop/main.py`（278 行） | pywebview + pystray + uvicorn 标准桌面架构，filelock 单例锁 + stale lock 检测 |

#### scripts/

| 代码 | 依据 |
|------|------|
| `member_cli.py` | 实现了 AGENTS.md 承诺的 `writer run ...` / `artist run ...` CLI |
| `scaffold-member.ps1` | 完善的模板脚手架，支持 -DryRun、端口自动分配、CLI shim 生成 |
| 全部 6 个文件 | 风格统一（$ErrorActionPreference="Stop"、Split-Path 推断根目录、彩色日志），是仓库最干净的部分 |

### 1.4 存疑代码清单（详见第二节调研）

| 模块 | 自研点 | 调研结论 |
|------|--------|----------|
| `core/guardrail/` | `_ACTION_RANK` 多策略合并逻辑 | 建议保留自研轻量版，见 2.1 |
| `core/mem/` | `SimpleMemoryBudget` hot/warm/cold/permanent 分层 | 建议保留自研，见 2.2 |
| `core/prompt/` | `fit_parts_by_budget` token 预算分配 | 建议保留，见 2.3 |
| `writer/core/writer/design_fsm.py` | 4 轮 FSM 自研 | 建议保留，见 2.4 |
| `artist/database.py` | 手写 SQL schema 迁移 | 建议迁移到 Alembic，见 2.5 |
| `writer/core/writer/novel/`（17 文件） | 完整小说引擎自研 | 建议保留，见 2.6 |

### 1.5 技术债务清单

#### 高优先级（安全/守护测试）

| 债务项 | 文件 | 状态 |
|--------|------|------|
| 6 个文件硬编码真实 API key | writer/backend/tests/diag_*.py 等 | **已删除**（key 需轮换） |
| test_kernel.py 重复断言 bug（Artist 检查两次，Imager 漏检） | core/tests/test_kernel.py:1015-1017 | **已修复** |

#### 中优先级（deprecated/产品名污染）

| 债务项 | 文件 | 状态 |
|--------|------|------|
| hooks.py 标注 DEPRECATED 但仍被 Writer/Artist 导入 | core/src/lamtools_core/kernel/hooks.py | **存疑**：DEPRECATED 注释误导，实际仍在使用，建议移除 DEPRECATED 标注 |
| WorkspaceShell.vue CSS 类名 `writer-shell`/`writer-drawer`/`writer-main` | core/ui/src/components/WorkspaceShell.vue:2,13,49,91 | 待处理：重命名为 `shell-root`/`shell-drawer`/`shell-main` |
| coreApiMappers.ts `nullFallback` @deprecated 字段 | core/ui/src/helpers/coreApiMappers.ts:57 | 待处理：删除 deprecated 字段 |
| sse format_thinking_chunk @deprecated | core/src/lamtools_core/sse/__init__.py:90 | 待处理：确认无调用后删除 |
| test_hooks.py 含 @pytest.mark.skip | core/tests/test_hooks.py | 待处理：hooks.py 仍在使用，测试应恢复或重写 |

#### 已清理的债务（本次处理）

见 [第五节](#五本次已处理的债务)。

---

## 二、技术调研文档（交付 b）

### 2.1 Guardrail 框架调研

**自研点**：`core/guardrail/__init__.py` 的 `_ACTION_RANK` 字典 + BaseGuardrailPipeline，按 action 优先级合并多个 GuardrailCheck 结果。

**业界成熟方案**：
- **Guardrails AI**：40+ 内置验证器，Rail Spec（YAML/XML）声明式定义，Pydantic schema 验证
- **NeMo Guardrails**（NVIDIA）：Colang DSL 定义对话流控制，支持 input/output rails、jailbreak 检测
- **LLM Guard**：all-in-one 扫描器（prompt injection + PII + toxicity）
- **LlamaGuard 3**：Meta 的安全分类器，AgentDojo benchmark 上将攻击成功率从 17.6% 降至 1.75%

**对比**：

| 维度 | LamTools 自研 | Guardrails AI | NeMo Guardrails |
|------|--------------|---------------|-----------------|
| 定位 | action 优先级合并 | 结构化输出验证 | 对话流控制 |
| 复杂度 | 低（~100 行） | 中（需学习 Rail Spec） | 高（Colang DSL + GPU 加速） |
| 依赖 | 0 | guardrails-ai + hub | nemoguardrails + Colang |
| 延迟 | <1ms | 10-50ms | 200-500ms |
| 适用场景 | 已有 Kernel 内 action 合并 | LLM 输出 schema 验证 | 多轮对话安全控制 |

**结论**：**保留自研**。LamTools 的 guardrail 是 Kernel 内的 action 合并逻辑（auto_allow/ask_user/hard_block 优先级），不是独立的 LLM 输出验证层。引入 Guardrails AI 或 NeMo 会增加重依赖和延迟，且功能定位不同。自研的 ~100 行代码功能闭环、无外部依赖，符合"减法优先"原则。

**建议**：如果未来需要 LLM 输出内容安全验证（如 PII 检测、prompt injection 防护），可考虑引入 Guardrails AI 作为独立层，但不替换现有 Kernel 内 action 合并逻辑。

### 2.2 Memory 框架调研

**自研点**：`core/mem/__init__.py` 的 `SimpleMemoryBudget`，hot/warm/cold/permanent 四层 + token 预算。

**业界成熟方案**：
- **Mem0**：开源 AI 记忆层，LOCOMO 基准上比 OpenAI 原生记忆提升 26%，Token 降低 90%
- **Letta（旧 MemGPT）**：OS 风格记忆管理，agent 主动编辑记忆，LongMemEval 83%
- **Zep（Graphiti）**：时序知识图谱，LongMemEval 63.8%
- **LangMem**：LangChain 原生，episodic/semantic/procedural 三类记忆

**对比**：

| 维度 | LamTools 自研 | Mem0 | Letta | Zep |
|------|--------------|------|-------|-----|
| 架构 | 四层 token 预算 | 智能压缩 + 图存储 | Agent 自编辑记忆 | 时序知识图谱 |
| 依赖 | 0 | mem0 + 向量库 | letta runtime | zep + graphiti |
| LongMemEval | N/A | 49.0% | 83.0% | 63.8% |
| 框架锁定 | 无 | 低 | 高 | 低 |
| 适用场景 | Kernel 内 token 预算管理 | 跨会话个性化 | 长期状态 agent | 时序推理 |

**结论**：**保留自研**。LamTools 的 `SimpleMemoryBudget` 是 Kernel 内的 token 预算管理器，负责在上下文窗口内分配 hot/warm/cold/permanent 记忆的 token 配额。这与 Mem0/Letta/Zep 的定位不同——后者是跨会话的持久记忆系统，需要向量库或图数据库支持。

LamTools 已有独立的 `members/writer/backend/app/core/mem/`（7 文件）实现 Writer 的跨会话记忆（recall/provenance/lifecycle/stores），这是业务层记忆，与 Core 的 token 预算管理正交。

**建议**：保留 Core 的 `SimpleMemoryBudget`。如果 Writer/Artist 的跨会话记忆需求增长到需要向量检索或时序推理，可考虑在 member 层引入 Mem0 或 Zep，但不替换 Core 的 token 预算管理。

### 2.3 Prompt Token Budget 调研

**自研点**：`core/prompt/__init__.py` 的 `fit_parts_by_budget`，按 priority 排序后用 `estimate_tokens`（启发式 `len(text)/4`）估算并截断。

**业界方案**：
- **tiktoken**：OpenAI 官方 tokenizer，精确计算 token 数
- **transformers tokenizer**：HuggingFace 通用 tokenizer
- **LangGraph TokenBudget**：@langgraphjs/toolkit 提供

**对比**：

| 维度 | LamTools 自研 | tiktoken |
|------|--------------|----------|
| 精度 | 启发式（中文 ~1.5 chars/token，英文 ~4 chars/token） | 精确（按实际 BPE 分词） |
| 依赖 | 0 | tiktoken（需下载 encoding 文件） |
| 性能 | 极快（字符串长度） | 快（Rust 实现） |
| 适用场景 | 预算分配（允许误差） | 精确计费/截断 |

**结论**：**保留自研**。`fit_parts_by_budget` 的目的是在 prompt 拼装阶段做预算分配，允许 ±10% 误差。引入 tiktoken 会增加依赖和初始化时间（需下载 encoding 文件），而当前的启发式估算对预算分配足够。

**建议**：在 `estimate_tokens` 中增加对 thinking/reasoning 模型的特殊处理（这类模型 token 消耗与文本长度比例不同），但不需要替换为 tiktoken。

### 2.4 FSM 框架调研

**自研点**：`members/writer/backend/app/core/writer/design_fsm.py`，4 轮 FSM（intent → candidates → revision → decision）。

**业界方案**：
- **LangGraph**：LangChain 的 StateGraph，32K+ GitHub stars，Klarna/Uber/LinkedIn 生产使用，支持 cyclic graph + checkpoint + conditional edges
- **XState/statecharts**：前端 FSM 标准
- **Pydantic AI**：SDK 封装范式

**对比**：

| 维度 | LamTools 自研 | LangGraph |
|------|--------------|-----------|
| 定位 | Writer 设计流水线 4 轮 FSM | 通用 agent 编排 |
| 复杂度 | 低（单文件 FSM） | 中（StateGraph + checkpointer） |
| 依赖 | 0 | langgraph + langchain-core |
| 持久化 | 通过 Kernel state_store | 内置 PostgresSaver/MemorySaver |
| 适用场景 | 固定 4 轮设计流程 | 任意复杂 agent workflow |

**结论**：**保留自研**。Writer 的 design_fsm 是一个固定的 4 轮设计流水线（intent → candidates → revision → decision），状态转换逻辑明确且封闭。引入 LangGraph 会带来整个 langchain 生态依赖，且 LamTools 已有 CoreLoopKernel 作为通用 agent 编排层，design_fsm 只是 WriterKit 内部的一个业务子流程。

**建议**：保留自研。如果未来 design 流程需要动态分支（如根据设计评分跳过 revision 轮），可考虑迁移到 LangGraph，但当前 4 轮固定流程不需要。

### 2.5 数据库迁移调研

**自研点**：`members/artist/backend/app/database.py`（23-171 行），手写 SQL schema 迁移：ALTER TABLE 加列、重建表拓宽 VARCHAR、DROP TABLE、UPDATE status。

**业界标准方案**：**Alembic**（SQLAlchemy 官方迁移工具，1.18.4 稳定版）

**对比**：

| 维度 | LamTools 手写 | Alembic |
|------|--------------|---------|
| 版本控制 | 无（每次启动跑全部 PRAGMA 检查） | 有（revision 链 + alembic_version 表） |
| 回滚 | 不支持 | upgrade/downgrade |
| 数据安全 | 重建表有数据丢失风险 | 事务支持，出错自动回滚 |
| 审计 | 无 | migration 文件即审计记录 |
| 自动生成 | 无 | --autogenerate 从模型差异生成 |
| SQLite 支持 | 手写 ALTER | render_as_batch=True 模式 |

**结论**：**建议迁移到 Alembic**。这是本次调研中唯一明确建议更换的存疑项。理由：
1. 手写迁移每次启动都跑全部 PRAGMA 检查，增加启动延迟
2. 重建表逻辑（CREATE _new → INSERT → DROP → RENAME）有数据丢失风险
3. 无回滚能力，生产事故时无法快速回退
4. Writer 后端已使用 SQLAlchemy 2.0 async，Alembic 是其官方配套工具

**迁移建议**：
```
1. pip install alembic
2. cd members/artist/backend && alembic init alembic
3. 配置 env.py: target_metadata = Base.metadata, render_as_batch=True
4. alembic revision --autogenerate -m "initial schema"
5. alembic stamp head（标记当前数据库为最新，不实际执行）
6. 后续 schema 变更用 alembic revision --autogenerate
```

### 2.6 Novel Engine 调研

**自研点**：`members/writer/backend/app/core/writer/novel/`（17 文件），完整小说引擎：planner/tag_system/drift_detector/guardrail/reviewer/wiki_enricher/character_bible/canon_extractor。

**业界方案**：业界无成熟的开源小说生成框架。NovelAI/AI Dungeon 均为闭源商业产品。

**结论**：**保留自研**。小说生成是 Writer 的核心业务差异化能力，业界无成熟开源方案可替代。drift_detector 的两层架构（layer1_stats 统计 + layer2_llm 语义）是合理的工程设计。

**建议**：保留自研，但考虑将 17 文件按职责拆分到子目录（planner/、style/、review/、memory/），降低单目录文件数。

---

## 三、对比文档（交付 c）

### 3.1 架构对比：LamTools vs OpenAI Agents SDK vs LangGraph

| 维度 | LamTools CoreLoopKernel | OpenAI Agents SDK | LangGraph |
|------|------------------------|-------------------|-----------|
| 核心模式 | Kernel + RuntimeKit | Runner + Agent | StateGraph + Nodes |
| 业务注入 | RuntimeKit Protocol（10 方法） | Tools + Handoffs | Nodes + Edges |
| 状态管理 | RuntimeStateStore Protocol | Session state | Checkpointer |
| 流式支持 | LLMResponse stream + SSE | RunResult stream | Stream events |
| 工具执行 | 串行/并行（Kit 决定） | 串行 | 并行（reducer 合并） |
| 取消 | cancel_event | cancellation_token | timeout/interrupt |
| 验收 | VerificationResult + repair loop | 无内置 | 无内置 |
| 产品中立 | 强制（测试守护） | N/A | N/A |

**结论**：LamTools 的 Kernel/Kit 模式与 OpenAI Agents SDK 的 Runner/Agent 模式理念一致（"骨架与业务分离"），但增加了 VerificationResult + repair loop 这一 LamTools 特有的验收循环。这是合理的业务驱动设计，不是过度工程。

### 3.2 现有实现 vs 建议方案对比

#### 3.2.1 手写 SQL 迁移 vs Alembic

| 对比项 | 现有实现（手写 SQL） | 建议方案（Alembic） | 优劣 |
|--------|---------------------|---------------------|------|
| 启动检查 | 每次启动跑全部 PRAGMA | 仅检查 alembic_version 表 | Alembic 更快 |
| 回滚 | 不支持 | upgrade/downgrade | Alembic 更安全 |
| 数据迁移 | 重建表（风险） | 事务内 ALTER | Alembic 更安全 |
| 团队协作 | 无版本历史 | revision 链 + Git | Alembic 更规范 |
| 学习成本 | 0 | 需学习 Alembic CLI | 手写更简单 |
| 依赖 | 0 | alembic | 手写更轻量 |

**综合判断**：Alembic 的安全性和可回滚性远超手写迁移，建议更换。

#### 3.2.2 自研 Guardrail vs Guardrails AI

| 对比项 | 现有实现（自研 _ACTION_RANK） | 建议方案（Guardrails AI） | 优劣 |
|--------|-------------------------------|---------------------------|------|
| 定位 | Kernel 内 action 优先级合并 | LLM 输出 schema 验证 | 定位不同 |
| 代码量 | ~100 行 | 40+ 验证器 | 自研更轻量 |
| 依赖 | 0 | guardrails-ai + hub | 自研更轻量 |
| 延迟 | <1ms | 10-50ms | 自研更快 |
| 验证能力 | action 合并 | PII/毒性/注入检测 | Guardrails AI 更全面 |

**综合判断**：定位不同，保留自研。如需内容安全验证，Guardrails AI 作为独立层补充。

#### 3.2.3 自研 Memory Budget vs Mem0

| 对比项 | 现有实现（SimpleMemoryBudget） | 建议方案（Mem0） | 优劣 |
|--------|-------------------------------|------------------|------|
| 定位 | Kernel 内 token 预算分配 | 跨会话持久记忆 | 定位不同 |
| 存储 | 内存 | 向量库 + 图存储 | Mem0 更持久 |
| 依赖 | 0 | mem0 + 向量库 | 自研更轻量 |
| 个性化 | 无 | LOCOMO 提升 26% | Mem0 更智能 |
| 适用 | 单会话 token 管理 | 跨会话用户画像 | 互补 |

**综合判断**：定位正交，保留自研。Writer 已有独立的跨会话记忆（core/mem/），不需要在 Core 层引入 Mem0。

### 3.3 DEPRECATED hooks.py 现状对比

| 对比项 | 文档标注 | 实际状态 |
|--------|---------|----------|
| hooks.py | "DEPRECATED: HookSet has been eliminated" | **仍被 Writer/Artist 导入** |
| HookSet/HookResult | "kept only for backward compatibility" | **Writer/Artist 的 hooks.py 依赖这些类型** |
| test_hooks.py | @pytest.mark.skip | **测试被跳过，但被测代码仍在使用** |

**结论**：DEPRECATED 标注是**错误的债务**。hooks.py 仍被 `members/writer/backend/app/core/writer/hooks.py` 和 `members/artist/backend/app/core/artist/hooks.py` 导入。应移除 DEPRECATED 标注，或完成 Writer/Artist 的 hooks → Kit 迁移后再删除。

---

## 四、客观评价文档（交付 d）

### 4.1 整体代码质量评估

**评分：B+（良好，接近优秀）**

| 维度 | 评分 | 说明 |
|------|------|------|
| 架构设计 | A | Kernel/Kit 分离是亮点，Protocol-based 设计统一，产品中立性有测试守护 |
| 代码质量 | A- | 核心生产代码（LLMClient/TaskManager/WriterKit/ArtistKit）达到成熟开源水准 |
| 测试覆盖 | B+ | core/ 覆盖度高（test_kernel.py 1537 行），但 writer/tests/ 混入大量非测试脚本 |
| 仓库整洁 | C+ | 大量临时调试脚本、agent 实验产物、截图散落（本次已清理大部分） |
| 文档质量 | B | 架构文档优秀（core-loop-kernel-design.md），但有 3 个"未命名"文档（已清理） |
| 安全性 | B- | 有 6 个文件硬编码 API key（已删除，需轮换），图片代理有 SSRF 防护 |
| 依赖管理 | B | 核心依赖合理，但 .opencode-source/ 整体 vendored 是膨胀源 |

### 4.2 主要问题点

#### 问题 1：仓库膨胀（已部分处理）

**现象**：根目录有 10+ 个 test-* 实验目录、e2e/test-apps/ 有 20 个 agent 产物目录、test-output/ 有 35 个截图、.opencode-source/ 是完整 vendored 项目。

**影响**：增加 AI agent 上下文噪声、增加克隆/构建时间、新成员接入困惑。

**处理**：本次已删除 test-output/ 截图、e2e/test-apps/ 散落文件、Artist 根目录 23 个 test_*.py。剩余 test-* 目录和 .opencode-source/ 需用户决策。

#### 问题 2：tests/ 目录混入脚本（Writer）

**现象**：`members/writer/backend/tests/` 有 33+ 个非测试脚本（algo_score.py、bench_v2.py、run_*.py、e2e_*.py 等），混在 35+ 个真实 pytest 测试中。

**影响**：误导测试统计、增加维护负担、CI 可能误收集。

**建议**：将脚本移到 `members/writer/scripts/`，tests/ 只保留 `test_*.py` 真实测试。

#### 问题 3：守护测试 bug（已修复）

**现象**：`test_kernel.py:1015,1017` 重复断言 `"Artist" not in source`，导致 `"Imager"` 漏检。

**影响**：如果 kernel 源码中出现 "Imager" 业务名，测试不会失败，违反 AGENTS.md 第 2 条。

**处理**：已修复为 `assert "Imager" not in source`，测试通过。

#### 问题 4：DEPRECATED 标注误导

**现象**：`core/src/lamtools_core/kernel/hooks.py` 标注 DEPRECATED，但仍被 Writer/Artist 导入。

**影响**：维护者可能误以为可删除，导致 Writer/Artist 运行时崩溃。

**建议**：移除 DEPRECATED 标注，或完成 hooks → Kit 迁移。

#### 问题 5：版本号不一致（Artist）

**现象**：Artist 有 4 处版本号不一致：pyproject.toml(0.5.0)、config.py(0.4.0-alpha)、desktop/__init__.py(0.3.1-beta)、frontend/package.json(0.4.2-beta)。

**影响**：桌面端更新检查（updater.py）基于过旧版本误报更新。

**建议**：统一为 pyproject.toml 单一版本源。

#### 问题 6：UI 产品名污染

**现象**：`core/ui/src/components/WorkspaceShell.vue` 的 CSS 类名 `writer-shell`/`writer-drawer`/`writer-main` 违反"Core 不认产品名"原则。

**影响**：新成员复用 WorkspaceShell 时看到 `writer-*` 类名，造成困惑和命名冲突。

**建议**：重命名为 `shell-root`/`shell-drawer`/`shell-main`。

### 4.3 改进建议（按优先级）

#### P0 — 立即处理

1. **轮换 API key**：6 个已删除文件中的 GLM API key 已泄露，需在 GLM 平台轮换
2. ~~修复 test_kernel.py 重复断言~~ **已完成**
3. **清理 .gitignore**：添加 test-output/、test-results/、test-*/、e2e/test-apps/、e2e/real-task-runs/ 到 .gitignore

#### P1 — 短期处理（1-2 周）

1. **移除 hooks.py 的 DEPRECATED 标注**：或完成 hooks → Kit 迁移
2. **修复 WorkspaceShell.vue CSS 类名**：`writer-*` → `shell-*`
3. **统一 Artist 版本号**：pyproject.toml 为单一源
4. **整理 Writer tests/ 目录**：33 个脚本移到 scripts/
5. **删除剩余 deprecated 代码**：sse.format_thinking_chunk、coreApiMappers.nullFallback

#### P2 — 中期处理（1 个月）

1. **Artist 数据库迁移到 Alembic**：替代手写 SQL 迁移
2. **处理 .opencode-source/**：删除或转 git submodule
3. **删除根目录 test-* 实验目录**：10 个目录
4. **拆分大文件**：core_kernel_adapter.py（2754 行）、writer_cli/__main__.py（1683 行）

#### P3 — 长期处理

1. **重命名 writer/backend/app/core/**：避免与 monorepo core/ 混淆
2. **统一技术栈版本**：Vite 5/6、vue-tsc 1/2、TypeScript 5.4/5.6/5.7（见 bug-audit X-STK-01~09）
3. **修复 bug-audit 中的 90 个 bug**：按 bug-audit-2026-06-16.md 优先级处理

### 4.4 架构亮点（值得保持）

1. **Kernel/Kit 分离**：CoreLoopKernel 只管循环/调模型/保存状态，RuntimeKit 注入业务。`test_kit_boundary.py` 契约测试守护此边界。这是 monorepo 最突出的架构优点。

2. **产品中立性测试守护**：`test_kernel_source_no_artist_writer_imager` 测试确保 kernel 源码不出现产品名（本次修复了 Imager 漏检 bug）。

3. **Protocol-based 设计**：全部使用 `typing.Protocol + runtime_checkable`，允许 Writer/Artist 各自实现，Core 不绑定具体类。

4. **OpenAI 兼容性强**：LLM adapter 的 URL 规范化、payload 构建、流式 delta 合并与 OpenAI 官方 SDK 行为一致。

5. **scripts/ 风格统一**：6 个 PowerShell/Python 脚本风格一致（$ErrorActionPreference="Stop"、彩色日志、端口注册表），是仓库最干净的部分。

---

## 五、本次已处理的债务

### 5.1 已删除文件（共 91 个）

#### 根目录（2 个）
- `nul` — Windows 保留名误创建的 0 字节文件
- `test_rpc.py` — 14 行临时 RPC 探测脚本

#### Artist 根目录（24 个）
- 23 个 `test_*.py` — 临时调试脚本（硬编码旧路径 `e:/lamartist/`、旧端口 `8000`、引用已删除功能）
- `pytest.ini` — 与 pyproject.toml [tool.pytest.ini_options] 重复

#### Artist backend（7 个）
- `analyze_lgt1.py`、`artist.py`、`check_api.py`、`check_db.py`、`check_desktop.py` — 临时调试脚本
- `err.txt`、`out.txt` — 2026-05-08 旧日志

#### Artist docs（3 个）
- `未命名.md`、`未命名 1.md`、`未命名 2.md` — 无标题草稿

#### Writer backend（20 个）
- `frontend/src/app.js`（583 行） — legacy vanilla JS，已被 Vue 迁移替代
- `frontend/src/styles.css` — legacy 样式
- `test_sage_delegation.py` — 引用已删除的 runtime.py
- `uitest/helloworld.py`、`uitest/helloworld.html` — 空壳文件
- `writer_tui/widgets/permission_dialog.py` — 1 行 "Done" 空壳
- 6 个 .png 截图 — 散落在 backend/ 和 writer 根目录
- 6 个含硬编码 API key 的临时脚本 — `diag_second_call.py`、`diag_writer_payload.py`、`manual_glm51_tool_result.py`、`manual_test_multiturn.py`、`quick_api_test.py`、`investigate_plan.py`

#### 测试产物（35 个）
- `test-output/*.png`（35 个） — tests/*.spec.ts 运行截图产物
- `test-results/.last-run.json` — Playwright 单次运行状态

#### e2e/test-apps/ 散落文件（4 个）
- `pipeline_result.txt`、`result.json`、`test_output.txt` — agent 运行日志
- `poll.py` — 临时轮询脚本（硬编码 session_id）

### 5.2 已修复 bug（1 个）

- `core/tests/test_kernel.py:1015-1017` — 重复断言 `"Artist" not in source` 导致 `"Imager"` 漏检。已修复为 `assert "Imager" not in source`，测试通过。

### 5.3 待用户决策的债务（未处理）

| 债务 | 理由 |
|------|------|
| `.opencode-source/`（数百文件） | vendored 外部项目，删除是重大决策，需用户确认 |
| 根目录 10 个 test-* 实验目录 | 可能被引用，需用户确认 |
| `tests/` 下 4 个 spec 文件 | 早期截图调试脚本，与 e2e/ 重叠，需用户确认整合方式 |
| Writer tests/ 33 个非测试脚本 | 需移到 scripts/，涉及路径引用更新 |
| `core/kernel/hooks.py` DEPRECATED 标注 | 实际仍被使用，需决策是移除标注还是完成迁移 |
| WorkspaceShell.vue CSS 类名重命名 | 涉及 CSS 选择器依赖检查 |
| Artist 版本号统一 | 需确认目标版本号 |
| Artist 手写 SQL → Alembic 迁移 | 中期重构，需专项计划 |

---

## 参考资料

- [LLM Guardrails: Enterprise Implementation Guide](https://beyondscale.tech/blog/llm-guardrails-implementation-guide)
- [Best AI Agent Security & Guardrails Tools 2026](https://agdex.ai/blog/best-ai-agent-security-guardrails-2026)
- [NVIDIA NeMo Guardrails Overview](https://docs.nvidia.com/nemo/guardrails/latest/about/overview.html)
- [Best MemGPT Alternatives for AI Agent Memory in 2026](https://evermind.ai/blogs/memgpt-alternative)
- [AI Memory Systems Compared June 2026](https://www.web3aiblog.com/blog/ai-memory-systems-compared-mem0-letta-zep-langmem-june-2026)
- [Best AI Agent Memory Frameworks in 2026](https://atlan.com/know/best-ai-agent-memory-frameworks-2026/)
- [What is LangGraph? State, Agents, and Production Use Cases (2026)](https://atlan.com/know/ai-agent/ai-agent-memory/what-is-langgraph/)
- [LangGraph State Management in Practice: 2026](https://eastondev.com/blog/en/posts/ai/20260424-langgraph-agent-architecture/)
- [Alembic and SQLModel: Database Migrations in Python](https://lucasgabrielb.com/en/posts/alembic-and-sqlmodel-database-migrations-in-python/)
- [Mastering Python Alembic: The Definitive Guide](https://getkt.com/neotam/mastering-python-alembic-the-definitive-guide-to-database-migrations/)
- [How to Automate Database Migrations with Alembic and SQLAlchemy](https://botmonster.com/posts/automate-database-migrations-alembic-sqlalchemy/)
