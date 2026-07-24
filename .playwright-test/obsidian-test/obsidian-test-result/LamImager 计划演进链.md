# LamImager 计划演进链

> 状态：📦 大部分已归档 | 来源：docs/plans/ + docs/plans/archive/
>
> 60+ 篇计划文档的演进关系。按主题分组，标注前后替代关系。

## 一、项目初始设计（2026-05-06）📦

| 文档 | 状态 | 说明 |
|---|---|---|
| `2026-05-06-lamimager-design.md` | 📦 已实现 | 初始设计文档 |
| `2026-05-06-lamimager-design.zh-CN.md` | 📦 已实现 | 中文版 |
| `2026-05-06-lamimager-implementation.md` | 📦 已完成 | 30 个任务全部实现 |
| `2026-05-06-lamimager-implementation.zh-CN.md` | 📦 已完成 | 中文版 |
| `2026-05-06-session-redesign.md` | 📦 已完成 | 会话 UI 重设计 |
| `2026-05-06-session-redesign.zh-CN.md` | 📦 已完成 | 中文版 |

## 二、架构升级 + 桌面应用（2026-05-07）📦

| 文档 | 状态 | 说明 |
|---|---|---|
| `2026-05-07-architecture-upgrade-concurrent-sse-plan-optimize.md` | 📦 | 多会话并发 + SSE 事件中心 + 规划优化 |
| `2026-05-07-architecture-upgrade-implementation.md` | 📦 | 架构升级实施 |
| `2026-05-07-desktop-app-implementation.md` | 📦 | 桌面应用打包实施 |
| `2026-05-07-desktop-app-implementation.zh-CN.md` | 📦 | 中文版 |
| `2026-05-07-desktop-app-packaging.md` | 📦 | 桌面应用打包设计 |
| `2026-05-07-desktop-app-packaging.zh-CN.md` | 📦 | 中文版 |
| `2026-05-07-remove-tasks-merge-into-sessions.md` | 📦 | 移除独立任务，统一到会话 |
| `2026-05-07-remove-tasks-merge-into-sessions.zh-CN.md` | 📦 | 中文版 |

## 三、Agent 系统演进（2026-05-08 ~ 05-13）📦→✅

这是最密集的演进线，从 Agent 工具调用到 LangGraph 统一。

```
Agent 工具调用 (05-08)
  → Agent Phase 2: 输入到生成全流程 (05-08)
    → Agent Phase 3: style_anchor 套图策略 (05-08)
      → 图像感知上下文与迭代精修 (05-08)
        → Agent 意图编配 (05-09)
          → Agent 模式重构 (05-09)
            → Agent 流式输出全栈改造 (05-09)
              → Agent Bug 修复 (05-09)
                → Pre-LangGraph 理想架构 (05-10)
                  → P1 Pre-LangGraph 实施 (05-12) ← 取代 05-10
                    → P2 LangGraph 实施 (05-12)
                      → Agent Graph 统一方案 (05-12) ← 修复 10 个数据流 bug
                        → P2 Task 8: Skill Matcher (05-13)
```

### 归档计划（2026-05-08 ~ 05-09）📦

| 文档 | 说明 |
|---|---|
| `2026-05-08-agent-tool-calling.md` | Agent 工具调用设计 |
| `2026-05-08-agent-tool-calling-implementation.md` | 实施 |
| `2026-05-08-agent-phase2-generate.md` | Phase 2 设计 |
| `2026-05-08-agent-phase2-implementation.md` | 实施 |
| `2026-05-08-agent-phase3-style-anchor.md` | Phase 3 设计 |
| `2026-05-08-agent-phase3-implementation.md` | 实施 |
| `2026-05-08-image-aware-context-and-refinement.md` | 图像感知上下文设计 |
| `2026-05-08-image-aware-context-and-refinement-implementation.md` | 实施 |
| `2026-05-08-billing-token-fixes.md` | 计费 Token 修复 |
| `2026-05-09-agent-intent-orchestration.md` | 意图编配设计 |
| `2026-05-09-agent-intent-orchestration-implementation.md` | 实施 |
| `2026-05-09-agent-refactor.md` | Agent 模式重构 |
| `2026-05-09-agent-streaming-overhaul.md` | 流式输出改造 |
| `2026-05-09-agent-bugfix.md` | Bug 修复 |
| `2026-05-09-image-count-optimization.md` | 图像数量优化设计 |
| `2026-05-09-image-count-implementation.md` | 实施 |
| `2026-05-09-plan-link-test.md` | Plan 链路验证 |

### 活跃计划（2026-05-10 ~ 05-13）⚠️

| 文档 | 状态 | 说明 |
|---|---|---|
| `2026-05-10-pre-langgraph-ideal-architecture.md` | ⚠️ 被 05-12 取代 | 理想架构设计 |
| `2026-05-10-pre-langgraph-implementation.md` | ⚠️ 被 05-12 取代 | 实施（被 P1 取代） |
| `2026-05-10-agent-pipeline.md` | ⚠️ | 语义解析→策略匹配→执行最小闭环 |
| `2026-05-10-priority-sorted-unfinished-tasks.md` | ⚠️ | 未完成事项优先级排序 |
| `2026-05-11-future-roadmap-skill-context-plan.md` | ⚠️ | 未来路线图 + Skill/Context/Plan 分工 |
| `2026-05-12-p1-pre-langgraph.md` | ✅ 已完成 | P1 施工文档（取代 05-10） |
| `2026-05-12-p2-langgraph-implementation.md` | ✅ 已完成 | P2 LangGraph 实施 |
| `2026-05-12-agent-graph-unification.md` | ✅ 已完成 | Agent Graph 统一（10 bug 修复） |
| `2026-05-12-sessions-vue-split.md` | ✅ 已完成 | Sessions.vue 拆分 |
| `2026-05-13-agent-content-visibility.md` | ✅ | 节点内容可见性与持久化 |
| `2026-05-13-agent-logging-billing.md` | ✅ | 全链路日志与计费 |
| `2026-05-13-agent-node-visibility.md` | ✅ | 节点进度可见性 |
| `2026-05-13-p2-task8-skill-matcher.md` | ✅ | Agent 自主 Skill 选择 |
| `2026-05-13-ui-redesign.md` | ⚠️ | UI 重新设计（已被 LamWriter 对齐取代） |

## 四、Artist 演进（2026-05-14 ~ 05-29）✅

```
Artist Mode 设计 (05-14)
  → ImageContextResolver (05-16)
    → Artist P3B-10 实施 (05-17)
      → Artist Before P4 (05-18)
        → Image Lineage & Reference Resolution (05-18)
          → Lineage DAG 设计 + 实施 (05-19)
            → Artist Realism Architecture (05-19)
              → Cross-Turn Image Context (05-22)
                → Artist 统一对话生图 (05-25)
                  → ExecutionEngine 委派重构 (05-27)
                    → Long Task Orchestration (05-29)
```

| 文档 | 状态 | 说明 |
|---|---|---|
| `2026-05-14-artist-mode-design.md` | ✅ | Artist Mode 聊天式交互设计 |
| `2026-05-14-canvas-directions-analysis.md` | ❓ | 画布方向分析（未排期） |
| `2026-05-14-checkpoint-sse-fix.md` | ✅ | Checkpoint SSE 修复 |
| `2026-05-14-unified-execution-engine.md` | ✅ | 统一执行引擎 |
| `2026-05-14-agent-per-node-model-config.md` | ❓ | 节点分模型配置（未实现） |
| `2026-05-15-checkpoint-state-persistence.md` | ✅ | Checkpoint 状态持久化 |
| `2026-05-16-agent-inline-progressive-display.md` | ✅ | Agent 内联渐进式显示 |
| `2026-05-16-image-context-resolver.md` | ✅ | ImageContextResolver |
| `2026-05-17-artist-p3b10-implementation.md` | ✅ | Artist P3B-10 实施 |
| `2026-05-18-artist-before-p4-completion.md` | ✅ | Artist P4 前完成 |
| `2026-05-18-artist-image-lineage-and-reference-resolution.md` | ✅ | 图像谱系与参考解析 |
| `2026-05-19-artist-lineage-dag-design.md` | ✅ | Lineage DAG 设计 |
| `2026-05-19-artist-lineage-dag-impl.md` | ✅ | Lineage DAG 实施 |
| `2026-05-19-artist-realism-architecture.md` | ✅ | Artist 真人感架构 |
| `2026-05-19-wechat-adapter.md` | ❓ | 企业微信适配器 |
| `2026-05-20-lineage-upload-nodes.md` | ✅ | 谱系树包含上传参考图 |
| `2026-05-20-writer-architecture.md` | ✅ | → [[LamTools 成员架构设计]] |
| `2026-05-21-mate-architecture.md` | ✅ | → [[LamTools 成员架构设计]] |
| `2026-05-21-sage-architecture.md` | ✅ | → [[LamTools 成员架构设计]] |
| `2026-05-21-video-branch-design.md` | ❓ | 视频分支设计 |
| `2026-05-22-artist-cross-turn-image-context.md` | ✅ | 跨轮次图片上下文 |
| `2026-05-22-butler-detailed-design.md` | ✅ | → [[LamTools 成员架构设计]] |
| `2026-05-24-lineage-e2e-test-plan.md` | ✅ | → [[LamImager E2E 测试]] |
| `2026-05-25-artist-unify-conversation.md` | ✅ | 统一对话生图 |
| `2026-05-25-lineage-tree-system-message.md` | ✅ | 谱系图改造 + 系统消息气泡化 |
| `2026-05-27-artist-execution-engine-delegation.md` | ✅ | ExecutionEngine 委派重构 |
| `2026-05-29-artist-long-task-orchestration-plan.md` | ✅ | 长任务编排计划 |
| `2026-05-29-artist-long-task-orchestration.md` | ✅ | 长任务编排技术设计 |

## 五、生态规划（2026-05-09）⚠️

| 文档 | 状态 | 说明 |
|---|---|---|
| `2026-05-09-lamtools-ecosystem.md` | ⚠️ | LamTools 生态架构演进计划 |
| `2026-05-09-plan-system-gaps.md` | ⚠️ | 规划系统 30+ 问题修复 |

## 关联

- 开发路线 → [[LamImager 开发路线图]]
- 进度日志 → [[LamImager 进度日志]]
- Artist Runtime → [[LamImager Artist Runtime]]
