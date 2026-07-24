# LamImager 源码调研报告

> 状态：✅ 有效 | 来源：learning-report.md
>
> 2026-05-14 调研。Claude Code 2.4.3 / OpenCode 1.14.50 深度源码分析，提炼可借鉴模式。

## 调研对象

| 项目 | 技术栈 | 定位 |
|---|---|---|
| Claude Code 2.4.3 | TypeScript / Node / Ink / Anthropic SDK | Anthropic 官方 CLI 编程助手 |
| OpenCode 1.14.50 | TypeScript / Bun / Effect / SolidJS / Vercel AI SDK | 开源 AI 编程助手 |

## LamImager 当前痛点（调研时）

| 痛点 | 严重度 |
|---|---|
| 三套 Agent 执行逻辑并存 | 🔴 严重 |
| generate_service.py 巨型文件（1230行） | 🔴 严重 |
| 消息模型扁平（content + metadata JSON） | 🟡 中等 |
| AgentState 弱类型（40个可选字段） | 🟡 中等 |
| TaskManager 职责过载 | 🟡 中等 |
| 缺少上下文压缩 | 🟡 中等 |
| 工具执行无权限控制 | 🟡 中等 |
| 缺少测试 | 🔴 严重 |

## Claude Code 核心架构

### 工具系统
- 泛型工具接口 `Tool<Input, Output, P>`（~30个方法）
- 能力声明：`isReadOnly()` / `isDestructive()` / `isConcurrencySafe()`
- Fail-closed 默认值
- 延迟加载（`shouldDefer`）优化 prompt cache

### 成本追踪
- Per-model 使用量追踪
- 90% 完成阈值
- 递减收益检测（连续3次 delta < 500 token）

### Hook 系统
- 12+ Hook 事件（PreToolUse/PostToolUse/SessionStart/Stop...）
- 多源 Hook + 优先级排序
- 异步 Hook 注册表（15秒超时，Promise.allSettled 故障隔离）

### Memory 系统
- MEMORY.md 入口文件（200行/25KB 上限）
- 四类记忆：user / feedback / project / reference
- 陈旧度检测（基于 mtime）

## OpenCode 核心架构

### Part 消息模型 ⭐ P0 借鉴
消息与 Part 分离——消息只存元数据，内容通过 Part 数组承载：
- TextPart / ToolPart（状态机 pending→running→completed/error）/ ReasoningPart / StepPart...

### 上下文压缩
- Head/Tail 分割（head 压缩，tail 保留原文）
- 增量摘要（7段式：Goal/Constraints/Progress/Decisions/Next Steps/Critical Context/Relevant Files）
- 渐进式修剪（从后向前，保留最近 40K token）

### 权限模型
- 三态动作：allow / deny / ask（默认 ask）
- 最后匹配优先（last-match-wins）
- 通配符匹配

### Effect 服务模式
- Context.Service + Tag 全局唯一标识
- Layer 依赖注入
- SyncEvent 事件溯源 + 序列号幂等重放

## 可借鉴模式（按优先级）

| 优先级 | 模式 | 来源 | 对 LamImager 的价值 |
|---|---|---|---|
| P0 | Part 消息模型 | OpenCode | 替代扁平 content+metadata |
| P0 | 上下文压缩 | OpenCode | 解决长会话 token 膨胀 |
| P1 | 工具权限控制 | Claude Code | 防止 LLM 无限调用有成本的工具 |
| P1 | 成本追踪 | Claude Code | 精确预算控制 |
| P2 | Hook 系统 | Claude Code | 扩展点标准化 |
| P2 | Memory 系统 | Claude Code | CON 冷存储参考 |

## 关联

- 竞品研究 → [[LamTools 竞品研究]]
- 架构设计 → [[LamImager 架构设计]]
- 心智模型 → [[LamImager 心智模型]]
- 开发路线 → [[LamImager 开发路线图]]
