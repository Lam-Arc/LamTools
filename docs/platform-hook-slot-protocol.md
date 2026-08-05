# 平台 Hook + Slot 协议

## 概述

LamTools 的成员差异通过两个协议承载：
- **HookSet**：后端运行时差异（上下文注入、验收、决策、写回）
- **MemberSlotSet**：前端桌面差异（槽位声明、校验、fallback）

两者都是声明式的：成员只声明差异，不重写运行循环或桌面布局。

## HookSet 协议

### 位置
`core/src/lamtools_core/kernel/hooks.py`

### 生命周期节点
1. before_model — 进模型前注入上下文
2. after_tool — 工具执行后处理结果
3. verify — 验收检查
4. writeback — 写回状态、记忆、产物
5. decide_next — 影响下一步决策

### HookResult 字段
| 字段 | 类型 | 说明 |
|------|------|------|
| context_patch | dict | 合并到 PromptContext.metadata，由 Kit 消费 |
| state_patch | dict | 合并到 RuntimeState.metadata |
| events | list[CoreEvent] | 要发射的事件 |
| artifacts | list[dict] | 产物元数据 |
| verification | VerificationResult \| None | 验收结果覆盖 |
| decision_override | LoopDecision \| None | 决策覆盖请求 |
| decision_reason | str | 覆盖原因 |
| drift_detected | bool | 是否检测到漂移 |

### 决策受控规则
- failed / wait 可以覆盖任何决策
- done 不能覆盖 continue
- continue 只能在验证失败、drift 检测、工具需要跟进时覆盖 done

### 现有实现
- NullHookSet：空实现，无差异
- WriterHookSet：`archive/members/writer/backend/app/core/writer/hooks.py`（已归档）
- ArtistHookSet：`archive/members/artist/backend/app/core/artist/hooks.py`（已归档）

## MemberSlotSet 协议

### 位置
`core/ui/src/types.ts`

### 标准 slot 名
sidebar-header, sidebar, sidebar-footer, chat-header, chat, composer-extra, drawer-right, panel, settings-section

### MemberSlotSet 字段
| 字段 | 类型 | 说明 |
|------|------|------|
| memberId | string | 成员 ID |
| declaredSlots | WorkspaceSlotName[] | 声明的 slot 列表 |
| fallbacks | Partial<Record<WorkspaceSlotName, string>> | 可选 fallback 组件名 |

### 校验规则
- declaredSlots 只能包含标准 slot 名
- fallbacks 的 key 只能是标准 slot 名
- 推荐声明 sidebar, chat, composer-extra
- 无效声明报错，缺失推荐 slot 警告

### 现有实现
- WorkspaceShell：`core/ui/src/components/WorkspaceShell.vue`
- Writer WorkbenchView：使用 WorkspaceShell + named slots
- Artist WorkbenchView：使用 WorkspaceShell + named slots

## 禁止事项

- Hook 不能开主循环
- Hook 不能绕过 core 调模型
- Hook 不能绕过 core 执行工具
- context_patch 不能只拼 raw system message
- 成员不能复制整套桌面
- core 中不能出现 Writer / Artist / Artist 专属业务分支

## Hook/Kit 边界规则

### Hook 不能做的事
- 直接执行工具（只能通过 context_patch 建议）
- 直接调用模型（只能通过 context_patch 注入上下文）
- 开自己的主循环（只能通过 decision_override 影响当前循环）
- 返回 tool_calls 或 model_request

### Kit 不能做的事
- 承载成员决策逻辑（decide_next 只返回建议，不覆盖）
- 开自己的主循环（只有 CoreLoopKernel 可以运行循环）
- 绕过 Hook 验证（verify 结果会被 Hook 审查）

### 边界护栏测试
- `core/tests/test_hooks.py::TestHookBoundaryGuardrails` — 5 个测试
- `core/tests/test_kit_boundary.py::TestKitBoundaryGuardrails` — 3 个测试
