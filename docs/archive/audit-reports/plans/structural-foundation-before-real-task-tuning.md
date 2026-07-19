# 结构地基：真实任务测试前的状态

## 状态：结构骨架达成，关键业务能力已迁入新路径，部分高级功能仍需后续迁移

## 单轨运行

CoreLoopKernel 是唯一运行骨架。Writer 和 Artist 的服务/CLI 主入口只走 CoreLoopKernel + 薄 RuntimeKit + HookSet。

- Writer: writer_service.py → run_core_kernel() → CoreLoopKernel + WriterKit
- Artist: artist_service.py → run_core_kernel() → CoreLoopKernel + ArtistKit

旧 WriterRuntime / ArtistRuntime 已删除。架构现在是 100% 单轨：CoreLoopKernel + RuntimeKit + HookSet + Slot。

## Kit/Hook 归一化

RuntimeKit 是薄适配层，只做协议桥接（LLM 适配、工具执行、状态存储、事件转发）。

HookSet 承载成员差异（上下文注入、验收逻辑、决策影响、记忆写回）。

Kit 和 Hook 不能同时做同一类业务。当前分工：
- Kit: LLM 调用适配、工具执行、状态持久化、事件格式化
- Hook: 上下文注入、验收、决策影响、写回

### Kit 进展

- ArtistKit 不再依赖 ArtistRuntime 实例，改用 ArtistGenerationConfig
- WriterKit 保持现有协议桥接实现

### Hook 进展

- WriterHookSet 现有 5 项验证检查（含文件存在性检查）
- WriterHookSet writeback 现在记录 session outcomes
- ArtistHookSet 包含视觉上下文、lineage、generation params

### Hook/Kit 边界护栏

- `core/tests/test_hooks.py::TestHookBoundaryGuardrails` — 5 个测试
- `core/tests/test_kit_boundary.py::TestKitBoundaryGuardrails` — 3 个测试

## HookResult 全字段落地

HookResult 包含：context_patch、state_patch、events、artifacts、verification、decision_override、decision_reason、drift_detected。

context_patch 进入 PromptContext.metadata（统一上下文结构），由 Kit 在 build_model_request 中消费。不允许只拼 raw system message。

## 决策受控规则

apply_decision_override 强制执行：
- failed / wait 可以覆盖任何当前决策
- done 不能覆盖 continue
- continue 只能在验证失败、drift 检测、工具需要跟进时覆盖 done

Hook 不能绕过主循环做决策。

## 前端 Slot 协议

core/ui 提供 WorkspaceShell + MemberSlotSet 声明 + 校验 + fallback。

标准 slot 名：sidebar-header, sidebar, sidebar-footer, chat-header, chat, composer-extra, drawer-right, panel, settings-section。

成员只声明 slot 清单和轻量映射，不复制整套桌面。

无效 slot 声明报错。缺失 slot 走 fallback。

前端共享工具函数已提取到 core/ui：createProductAdapter、createMemberSessionGroup。

## 已删除的旧路径

- Writer 服务不再直接实例化 WriterRuntime
- Artist 服务不再直接调用 ArtistRuntime.handle_turn()
- Artist CLI 不再直接调用 ArtistRuntime.handle_turn()
- LAMWRITER_CORE_KERNEL / LAMARTIST_ARTIST_CORE_KERNEL 环境变量开关已不存在

## 已完成清理

以下文件和目录已彻底删除（不是"不再作为主路径"，而是文件已不存在）：

- `members/writer/backend/app/core/writer/runtime.py` — WriterRuntime 类已删除
- `members/artist/backend/app/core/artist/runtime.py` — ArtistRuntime 类已删除
- `members/writer/frontend/src/views/WorkbenchView.vue` — Writer 旧 WorkbenchView 已删除
- `members/artist/frontend/src/views/WorkbenchView.vue` — Artist 旧 WorkbenchView 已删除
- `core/references/` — 参考文件目录已删除
- Writer 旧 runtime 测试已删除
- Artist 旧 runtime 测试已删除
- Writer compat shims（get_active_runtime、resume_session）已删除
- `run_core_kernel_with_config` 已重命名为 `run_core_kernel`（旧 compat 入口 `runtime: ArtistRuntime` 已移除）
- `ARTIST_RUNTIME_SYSTEM` 现从 `identity.py` 导入（不再从 `runtime.py`）
- `ArtistDeps` 现从 `deps.py` 导入（不再从 `runtime.py`）

## 短期债务

### 不阻塞真实任务测试的债务

- Artist 的 contact_sheet / delegate_agent 未接入 CoreLoopKernel 路径

### 需要关注但不阻塞地基完成的债务

- 流式 token 转发未在 CoreLoopKernel 主循环中实现
- Writer 的 completion_verifier / session_memory 未完全迁入 WriterHookSet
- self_review 需要 kernel 支持二次模型调用（当前 kernel 不支持在 Hook 中发起独立的模型请求）
- LLM-based completion verification 与 self_review 面临相同的边界问题
