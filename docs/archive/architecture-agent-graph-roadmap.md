<!-- 历史参考，不代表当前架构 -->
# ArchitectureAgent Graph Roadmap

## 目标

ArchitectureAgent 要从“单次大 JSON 设计器”演进成真正的节点图 agent，但外部合同保持稳定：

- Writer 仍只通过 `call_agent(name="architecture")` 调用。
- GUI 仍消费 `agent_progress` / `agent_completed` 事件。
- Writer 后续仍拿 `handoff`、`design_report`、`trace` 三类产物。
- 旧别名 `design`、`design_agent`、`architect` 继续兼容。

内部可以从轻量节点 runner 迁移到 LangGraph 包，但不能要求 WriterRuntime、前端、CLI 再次大改。

## 稳定合同

### 输入

```text
task_desc: str
mode: toy|low|medium|high|crazy|max
session_id: str
research briefs: optional search/ui/dependency summaries
```

### 输出

```text
DesignAgentResult
  handoff: 给 Writer/Planner 的执行合同
  design_report: 给用户看的完整架构方案
  trace: 给 GUI/debug 的结构化过程
  execution_estimate: 执行规模估计
  valid_design: 本地质量门是否通过
```

### Artifact

未来每次 agent 调用应稳定产出三类附件：

```text
ArchitectureAgent-架构方案.md
ArchitectureAgent-执行交接.md
architecture-trace.json
```

当前已有 `design_report`、`handoff`、`trace`，后续只需要把它们统一写入 artifact store。

## 节点图

第一版节点图：

```text
START
  -> intake_input             local
  -> route_task               LLM
  -> frame_problem            LLM
  -> generate_candidates      LLM
  -> select_architecture      LLM
  -> elaborate_architecture   LLM
  -> review_architecture      LLM
  -> build_outputs            local
  -> quality_gate             local
       pass -> END
       fail -> revise_architecture -> quality_gate
```

后续可扩展边：

```text
quality_gate
  -> if candidate class wrong: generate_candidates
  -> if selected architecture wrong: select_architecture
  -> if boundary/flow incomplete: elaborate_architecture
  -> if taste/review incomplete: review_architecture
  -> if user constraint unclear: decision_point
```

## 节点职责

`intake_input`
- 本地整理 mode、任务、hook 摘要。
- 不调用 LLM。

`route_task`
- 判断任务类型、设计路线、设计深度。
- 不能拒绝设计；进入 ArchitectureAgent 就必须产出 lightweight design。

`frame_problem`
- 界定目标、非目标、核心用户任务、硬约束、软偏好、假设、风险。

`generate_candidates`
- 生成候选架构。
- 候选数量由 mode 控制。

`select_architecture`
- 选择胜出方案。
- 必须解释为什么不是其他候选，不能只说“综合最优”。

`elaborate_architecture`
- 展开运行形态、模块、数据模型、状态流、交互流、错误/空状态、安全和演进路线。

`review_architecture`
- 审稿并解释架构美感。
- 美感不限定具体维度，但必须具体、可辩护，能说明系统秩序、边界、取舍、复杂度位置。

`build_outputs`
- 本地生成或补全 `user_summary`、`handoff`、报告结构。
- 不交给 LLM，避免最后一步把结构写散。

`quality_gate`
- 本地检查 schema、候选数量、模块边界、状态流、验收合同、架构美感说明。

`revise_architecture`
- 按质量门问题返工。
- 第一版返工整份 JSON；未来可按问题路由回具体节点。

## Mode 策略

```text
toy    候选 1，返工 0，允许轻量设计
low    候选 1，返工 1，要求闭合
medium 候选 2，返工 1，要求完整应用架构
high   候选 3，返工 2，严格审查
crazy  候选 4，返工 3，可多轮候选/审稿
```

## 调用次数预算

第一版正常路径：

```text
route_task             1
frame_problem          1
generate_candidates    1
select_architecture    1
elaborate_architecture 1
review_architecture    1
build_outputs          0
quality_gate           0
```

不含 hooks 和返工约 6 次 LLM。返工按 mode 增加 0-3 次。

未来优化：
- `toy/low` 可合并 `route_task + frame_problem`。
- `low` 可合并 `select_architecture + elaborate_architecture`。
- `crazy` 可拆 `generate_candidates` 为多轮候选生成和反方评审。

## 避免重构的边界

内部文件可以继续叫 `design_agent.py`，但外部 registry 主名必须是 `architecture`。

稳定边界：
- `DesignAgent.run(...) -> DesignAgentResult`
- `DesignAgentResult` 字段名
- `trace` 顶层字段
- `handoff` 中的 `Selected Architecture`、`Architecture Contract`、`Architecture Taste`
- SSE phase 使用节点名

可替换边界：
- 当前轻量 runner
- 节点 prompt
- 质量门细则
- 正式 LangGraph 编排引擎

迁移到 LangGraph 包时，每个当前节点函数可直接映射为 LangGraph node；`quality_gate` 的返回值映射为 conditional edge。
