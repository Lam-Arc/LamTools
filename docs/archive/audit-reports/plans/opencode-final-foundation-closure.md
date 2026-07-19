# Opencode 执行说明：结构地基最终收口

## 执行边界

在 `E:\LamTools` 执行。注意编码，中文不要乱码。不要提交 git。不要中途停下等 Codex 分阶段验收，只有全部完成后再汇报。

本次目标不是继续缝补，也不是只让测试通过，而是把 LamTools 打到可以开始 Writer / Artist 真实任务执行测试的地基状态。

## 硬目标

- CoreLoopKernel 是唯一运行骨架。
- RuntimeKit 只能是薄适配层。
- HookSet 承载成员差异。
- Kit 和 Hook 不能同时做同一类业务。
- Hook 不能开主循环。
- Hook 不能绕过 core 调模型。
- Hook 不能绕过 core 执行工具。
- runtime.py 不能再作为主循环或新业务入口。
- core/ui 是统一桌面骨架。
- member 只填 slots 和轻量组件映射。
- core 中不能出现 Writer / Artist / Artist 专属业务分支。
- legacy fallback 只能作为短期回滚点，不允许进入最终结构，不允许新增依赖。
- 新成员目标统一为：persona、hooks、agents、tools、slots。

## 当前验收失败原因

- WriterHookSet / ArtistHookSet 仍是空实现。
- Kit/Hook 没有归一化，成员业务仍留在 runtime.py / core_kernel_adapter.py。
- HookResult 的 next_decision 仍只是 advisory，未通过 core 受控规则影响决策。
- context_patch 被塞进 history system message，不是进入统一上下文结构。
- SlotProtocol 没有驱动真实桌面，CoreWorkbenchView 仍手写布局。
- 文档仍保留 legacy fallback、Phase 1/2、RuntimeKit 做胖等错误方向。

## 后端必须完成

1. WriterHookSet 和 ArtistHookSet 必须迁入低风险真实成员差异，不能全返回空结果。
2. 至少完成 before_model、after_tool、verify、writeback、decide_next 的真实接入。
3. RuntimeKit 中与这些节点重复的成员业务必须迁出或删除，不能重复执行。
4. context_patch 必须进入统一模型上下文结构，不允许只拼 history system message 糊住。
5. verification 必须参与统一验收汇总。
6. next_decision 必须通过 core 的受控决策规则影响最终 decision，并有测试证明不能绕过主循环。
7. runtime.py / core_kernel_adapter.py 中仍保留的业务必须有删除清单；能删就删。
8. hook_set.py 注释不能再写 Phase 1/2 或 “actual runtime logic remains”。
9. 服务和 CLI 主入口只能走 CoreLoopKernel + 薄 Kit + HookSet。
10. 不允许恢复旧开关或实验路径。
11. tool_specs / agents specs 继续作为成员能力清单，不允许工具或专家接管主循环。

## 前端必须完成

1. core/ui 必须真正消费 MemberSlotSet。
2. Writer / Artist CoreWorkbenchView 不能只是校验 slot，必须由 slot/fallback 驱动主要区域。
3. 至少 sidebar-header、sidebar、chat、composer、drawer-right、settings-section 要走 slot 机制。
4. 无 slot 必须走 fallback。
5. 无效 slot 必须清晰报错。
6. Writer / Artist 只能提供槽位清单和轻量映射，不允许复制整套桌面。
7. 删除未使用的 slot 变量，不能留假接入。
8. WorkbenchView.vue 不允许继续成为新 UI 主战场；剩余旧逻辑必须写入删除清单。
9. core/ui 不得写 Writer / Artist / Artist 专属判断。

## 文档必须完成

1. 更新 `docs/plans/structural-foundation-before-real-task-tuning.md`。
2. 删除或改写 `Legacy paths kept as fallback`。
3. 标记或重写 `docs/plans/single-track-runtime.md`，不能继续引导 RuntimeKit 做胖。
4. 更新 `docs/plans/member-runtime-skeleton-design.md`，统一为 persona、hooks、agents、tools、slots。
5. 更新 `docs/platform-hook-slot-protocol.md`，不能继续写 Phase 1/2 半成品状态。
6. 所有文档必须一致：最终单轨，不保留长期 fallback。
7. 如果本轮完成不了真实任务测试门槛，必须明确写“未达到真实任务测试门槛”，不能包装成完成。

## 必须新增或更新测试

1. 后端 contract 测试证明 HookSet 不是空壳。
2. 后端测试证明 HookResult context、state、events、artifacts、verification、decision 不会丢。
3. 后端测试证明空 HookSet 行为不变。
4. 后端测试证明 Hook 决策只能通过 core 受控规则生效。
5. Writer 定向测试覆盖真实 HookSet 接入。
6. Artist 定向测试覆盖真实 HookSet 接入。
7. 前端 contract 测试覆盖 slot 解析、fallback、无效声明报错。
8. E2E smoke 继续硬失败，不能只做 build。

## 必须运行验证

1. `.\scripts\test.ps1 core`
2. Writer hook/core adapter/core kernel/core http/tool executor 相关定向测试。
3. Artist hook/core adapter/tool specs/runtime adapter 相关定向测试。
4. core/ui build。
5. Writer frontend build。
6. Artist frontend build。
7. 实际启动 Writer 和 Artist 前端，用 `npm.cmd` 跑 E2E smoke。
8. 旧双轨扫描。
9. 大文件/旧职责扫描。
10. `git diff --stat`。
11. `git status --short`。

## 最终汇报格式

最终只汇报一次，必须包含：

- 是否达到“可以开始真实任务执行测试”的地基标准。
- 后端单轨完成情况。
- Kit/Hook 归一化完成情况。
- HookResult 全字段落点。
- 前端 Slot/统一桌面完成情况。
- 已删除的旧路径。
- 仍保留的短期债务。
- 全部测试结果。
- `git diff --stat`。
- `git status --short`。

不要提交 git，等待 Codex 验收。
