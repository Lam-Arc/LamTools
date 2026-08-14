# RAG 插件实施计划与量化验收标准（lamtools-rag）

> 日期：2026-08-15
> 状态：实施中（P0 环境实测 → P1 骨架）
> 配套：`docs/rag-plugin-design.md`（v2 规格）· `docs/rag-design-qa.md`（知识复盘）· `docs/plugin-system-rework.md`（G 组前置）
> 原则：**量化标准先行，实测鉴证**；评测流程尽量复用开源工具（RAGAS），保证结果可复现、可对照。

---

## 1. 阶段计划（P0-P6）

| 阶段 | 内容 | 出口标准（量化） |
|---|---|---|
| **P0** 环境实测 | sqlite-vec @ py3.14、FTS5 trigram 中文、onnxruntime（可选） | §2-A 全过或明确降级路径 |
| **P1** 骨架 + 文档检索 | 插件骨架（manifest/skills/tools/handler）+ 工作区文档确定性索引/混合检索 + snippet | §2-B 文档段、C、D 文档段 |
| **P2** 会话历史 | core.db 只读索引（消息级/turn_index/水位）+ rag_search_sessions + operation（G 组落地后） | §2-B 会话段 |
| **P3** format router + VLM | 扫描件/图表 → VLM 页面图批量理解（JSON schema）、表格文本化 + citation target | §2-D VLM 段 |
| **P4** 答案闸门 | submit_answer（规则层页码/原文/message_id 校验 + 可选 LLM 层）+ hooks | §2-C 引用段 |
| **P5** 评测体系 | golden set（jsonl）+ RAGAS runner + 行为指标 runner，**贯穿 P1-P4 每阶段跑分** | §3 流程就绪 |
| **P6** 1w 合同模拟 | 合成语料（标注答案）+ 两阶段流水线 + 压测 | §2-E |

每阶段结束：跑分 → 报告 → 与标准对比；不达标则修到达标才进下一阶段（回归门槛 §3.4）。

## 2. 量化验收标准（实测门槛）

### A. 环境（P0）
| 项 | 标准 | 失败预案 |
|---|---|---|
| sqlite-vec 安装 + vec0 CRUD 冒烟 | 100% 通过 | 切 faiss 1.15.0（cp314 已确认） |
| FTS5 trigram 中文检索 | ≥3 字词命中率 100%（20 词验证集） | 降级 BM25-only（jieba 分词） |
| onnxruntime py3.14（fastembed 底座） | 可安装可加载 | 降级 BM25-only / api embedding |
| 插件 handler 动态导入（sys.path 补丁） | 端到端工具调用成功 | 回滚补丁并走 pip -e 安装 |

### B. 检索质量（P5 起每阶段跑分；golden set 50-100 问）
| 指标 | 标准 | 测量 |
|---|---|---|
| 文档 recall@10 | ≥ 0.80 | 自建 golden（gold chunk 标注） |
| context_precision | ≥ 0.70 | RAGAS |
| context_recall | ≥ 0.75 | RAGAS |
| 会话历史消息级 recall@10 | ≥ 0.75 | golden 含"上次讨论"类问题 |
| scope 路由正确率 | ≥ 0.95 | 行为 runner（历史问题 → rag_search_sessions） |
| 混合 vs 单腿消融 | 混合 ≥ max(单腿) | 同 golden 对比 BM25-only / vector-only |

### C. 生成与行为（P4 起）
| 指标 | 标准 | 测量 |
|---|---|---|
| faithfulness | ≥ 0.85 | RAGAS |
| answer_relevancy | ≥ 0.80 | RAGAS |
| 引用合规率（submit_answer 一次通过） | ≥ 0.90 | 行为 runner |
| 无引用回答拦截率 | = 100%（零漏） | 闸门日志审计 |
| 工具调用成功率 | = 100%（无未预期异常） | 行为 runner |

### D. 性能（桌面单机，10 万块规模）
| 项 | 标准 |
|---|---|
| 确定性索引吞吐 | ≥ 20 页/秒 |
| VLM 批量（8 页/批，本地预算 120 tok/s） | ≤ 30s/批 |
| rag_search P95 | ≤ 200ms |
| 会话增量索引（1k 消息） | ≤ 5s |
| 1w 合同首次索引（断点续跑） | ≤ 12h 单机 |

### E. 1w 合同场景（合成语料，标注答案）
| 指标 | 标准 |
|---|---|
| 条款抽取 precision / recall | ≥ 0.95 / ≥ 0.95 |
| 聚合 Top-3 与标注一致率 | = 100% |
| 扫描件占比模拟（≥20%）下指标不降 | 同左 |

## 3. 开源评测流程（鉴证）

### 3.1 RAGAS 主评测（Apache-2.0，开源可鉴证）
- 四维指标：`context_precision` / `context_recall` / `faithfulness` / `answer_relevancy`；
- **适配本地模型**：RAGAS 默认依赖 OpenAI——通过其 custom LLM 接口接入 lamtools llm 栈
  （provider/model 配置 + 重试参数），评测链路与产品链路同模型同配置；
- 评测产物：`e2e/rag-eval/reports/<date>-<commit>.json`（指标 + golden 逐条明细 + 模型/配置指纹）。

### 3.2 golden set（自建，`e2e/rag-eval/golden/`）
- 格式：jsonl，`{question, answer(参考), ground_truth_context[doc/page 或 session/message], citation(期望引用), category}`；
- 覆盖：char/context/page 三维、会话历史、跨文档对比、扫描件（P3 后）、聚合型（P6 专用集）；
- **黄金上下文必须来自真实检索管线**（0.91 vs 0.40 教训），拒绝手工挑 chunk。

### 3.3 行为指标 runner（自建脚本，随 e2e）
- 引用合规率、无引用拦截率、scope 路由正确率、工具调用成功率；
- 走真实 agent 链路（load skill → 工具调用 → submit_answer）而非单测桩。

### 3.4 回归门槛与 LLM-as-judge 校准
- 每阶段跑分存档；**核心指标不得低于上次 ≥0.02**（超阈值 = 阻塞合并，先定位再推进）；
- LLM-as-judge（答案质量补充维度）：与人工标注 Cohen's κ ≥ 0.7 才启用，κ 值随报告存档；
- 报告含模型/embedding/索引版本指纹，杜绝"换了模型分数变了分不清谁干的"。

## 4. 风险与降级路径

| 风险 | 降级 |
|---|---|
| sqlite-vec 与 py3.14 内置 SQLite 兼容失败 | faiss 1.15.0（cp314 wheel 已确认）+ SQLite 元数据层 |
| fastembed/onnxruntime 装不上 | BM25-only 运行 + api embedding（双模式已设计） |
| G 组 operations 通道未落地 | 工具路径先行（对话内），UI 直搜后置 |
| 本地 VLM 不可用/太慢 | API 多模态模型（复用 default_multimodal_model 配置） |
| 插件 handler 导入问题 | 已补 sys.path 补丁（P0-A 验证）；备选 pip -e 安装插件包 |

## 5. 开发顺序速记

```
P0 冒烟（今天） → P1 文档检索可用 → P5 评测就绪（先测 P1）→ P2 会话 →
P3 VLM → P4 闸门 → P6 1w 合同模拟
```
