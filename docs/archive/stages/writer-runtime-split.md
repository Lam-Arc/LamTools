<!-- 历史参考，不代表当前架构 -->
# Writer runtime 低风险拆分（阶段六延续）

## 目标

降低 Writer runtime.py 的复杂度，向 Artist 当前结构靠拢。本轮只做低风险拆分，不重写主循环，不改变业务行为。这不是原路线"阶段七：脚手架"，而是阶段六的 Writer 复杂度治理延续。

## 原则

- 拆而不变：业务行为不变，测试不弱化
- 只拆纯业务辅助能力，不动最复杂主循环
- 新模块先作为声明和测试，不强行改 runtime 主循环
- delegation pattern：保留旧签名，委托到新模块
- 不做空声明导入：runtime.py 只导入实际使用的模块

## 本轮拆出什么

### 1. Writer hooks/lifecycle 模块

**新文件**：`members/writer/backend/app/core/writer/hooks.py`

内容：
- `WRITER_HOOK_DESCRIPTIONS`：5 个钩子节点的 Writer 专属描述（复用 core HOOK_* 常量作为 key）
- `WRITER_LOOP_POSITIONS`：4 个循环位置（plan/execute/verify/idle）
- `WRITER_WORKFLOW_PHASES`：5 个写作流程阶段（ideation→outlining→drafting→revising→polishing）
- `validate_writer_hooks_cover_core()`：验证 Writer hooks 覆盖所有 core 节点
- `writer_hook_description(node)`：按节点名查描述

**接入状态**：声明 + 测试验证。runtime.py **未导入**此模块。仅测试和文档引用。

### 2. Writer tool_specs 模块

**新文件**：`members/writer/backend/app/core/writer/tool_specs.py`

内容：
- `WRITER_TOOL_SPECS`：26 个工具的完整声明（name, description, input_schema, permission, failure_modes, recovery）
- `WRITER_TOOL_PERMISSIONS`：从 specs 派生的权限映射（复用 core AUTO_ALLOW/ASK_USER/HARD_BLOCK）
- `writer_tool_spec(name)`：按名称查找 spec

**接入状态**：
- 权限值与 permission.py 的 TOOL_PERMISSIONS 完全一致（测试验证）
- runtime.py **未导入**此模块
- 已声明，未驱动执行

### 3. Writer verification_specs 模块

**新文件**：`members/writer/backend/app/core/writer/verification_specs.py`

内容：
- `VERIFICATION_CRITERIA`：6 项验收标准
- `VERIFICATION_REPAIR_CONSTANTS`：修复循环常量（MAX_COMPLETION_REPAIR_ATTEMPTS=5, COMPLETION_REPAIR_READ_ONLY_LIMIT=2, REPAIR_READ_ONLY_ACTIONS）
- `VERIFICATION_FAILURE_MARKERS`：验收失败标记（中英文）
- `is_completion_repair_request(user_message)`：检测验收修复请求

**接入状态**：runtime.py 的 `_is_completion_repair_request` 已委托到此模块。

### 4. Writer failure_specs 模块

**新文件**：`members/writer/backend/app/core/writer/failure_specs.py`

内容：
- `LOOP_BREAKER_CONSTANTS`：7 个循环断路器阈值
- `FAILURE_PREFIXES`：12 个失败前缀模式
- `RECOVERABLE_FAILURE_PATTERNS`：可恢复失败模式映射
- `RECOVERY_STRATEGIES`：6 种恢复策略（中文）
- `is_recoverable_tool_failure(action_type, output)`：判断是否可恢复
- `failure_recovery_instruction(action_failures)`：生成恢复指令
- `is_test_or_command_failure(action_failures)`：判断是否测试/命令失败

**接入状态**：runtime.py 的三个方法已委托到此模块：
- `_is_recoverable_tool_failure` → `_failure_specs.is_recoverable_tool_failure`
- `_failure_recovery_instruction` → `_failure_specs.failure_recovery_instruction`
- `_is_test_or_command_failure` → `_failure_specs.is_test_or_command_failure`
- `_tool_output_is_failure` 使用 `_failure_specs.FAILURE_PREFIXES`

## runtime.py 行数变化

| 指标 | 值 |
|------|-----|
| 拆分前 | 6241 行 |
| 拆分后 | ~6170 行 |
| 减少量 | ~71 行（4 个方法/常量委托 + 移除未使用导入） |

行数减少不多，因为本轮重点是声明和测试，不是大规模代码搬迁。价值在于：
- 4 个新模块为后续深度拆分提供了目标文件
- 测试验证了 specs 与 runtime 行为一致
- runtime 已有 4 个方法委托到 failure_specs + verification_specs，建立了拆分路径
- hooks / tool_specs 仍是声明+测试，未接 runtime

## 哪些只是声明，哪些已被代码引用

| 模块 | 声明 | runtime 引用 | 测试验证 |
|------|------|-------------|---------|
| hooks.py | WRITER_HOOK_DESCRIPTIONS, LOOP_POSITIONS, WORKFLOW_PHASES | 未导入 | 是（11 个测试） |
| tool_specs.py | WRITER_TOOL_SPECS, WRITER_TOOL_PERMISSIONS | 未导入 | 是（11 个测试，含与 permission.py 一致性验证） |
| verification_specs.py | VERIFICATION_CRITERIA, REPAIR_CONSTANTS, FAILURE_MARKERS | `_is_completion_repair_request` 委托 | 是（10 个测试，含 runtime 委托验证） |
| failure_specs.py | LOOP_BREAKER_CONSTANTS, FAILURE_PREFIXES, RECOVERY_STRATEGIES | 3 个方法委托 + FAILURE_PREFIXES 引用 | 是（14 个测试，含 runtime 委托验证） |

## 已知既有测试失败（非本轮回归）

以下 3 个 test_runtime.py 测试在拆分前就失败，与本轮改动无关：

| 测试 | 失败原因 |
|------|---------|
| `test_forced_next_action_rejects_read_before_edit` | 期望 forced action 机制阻止 read_file 并产生 error 事件，但 runtime 实际未阻止，直接达到 max_turns 退出。这是 forced action 机制的既有问题。 |
| `test_completion_repair_request_forces_edit_after_read_only_turn` | 期望 completion repair 触发 forced action，但 runtime 未触发，直接达到 max_turns 退出。这是 completion repair 与 forced action 交互的既有问题。 |
| `test_simple_text_response` | 期望 runtime 收到纯文本回复后发出 `writer_done` 事件，但 runtime 实际只发出 `writer_response`，未发出 `writer_done`。这是 runtime 完成检测的既有问题。 |

**证据**：git stash 回到拆分前版本，3 个测试仍然失败，输出与拆分后完全相同。

## 全量 Writer tests 目录不能直接 pytest 运行的原因

`members\writer\backend\tests` 目录包含以下脚本式/依赖服务的文件：

| 文件 | 问题 |
|------|------|
| `test_original_task.py` | 导入即执行，依赖本地数据库和服务 |
| `test_tool.py` | 导入即执行，依赖本地服务 |
| `test_tui_e2e.py` | E2E 测试，依赖前端服务和浏览器 |
| `test_e2e_w1_w11.py` | E2E 测试，依赖完整 Writer 服务栈 |
| `test_writer_service.py` | 依赖数据库和完整服务栈 |

这些文件不应该和单元测试一起用 `pytest members\writer\backend\tests -q` 运行。
单元测试应单独指定，或通过 pytest markers/markers 排除脚本式文件。

本轮相关测试全部通过：
- `test_writer_core_kernel_adapter` + `test_writer_core_http`（147/147）
- `test_writer_hooks`（11/11）
- `test_writer_tool_specs`（11/11）
- `test_writer_verification_specs`（10/10）
- `test_writer_failure_specs`（14/14）
- 上述 3 个既有失败是预存在问题，与本轮无关

## Writer runtime 还剩哪些不优雅点

1. **主循环 ~6170 行未拆分**：run() 方法本身约 1500 行，包含所有生命周期逻辑
2. **工具执行器未拆分**：_run_tool 约 370 行，20+ 工具实现仍是 @staticmethod
3. **Git 管理未拆分**：10+ 个 _git_* 方法约 400 行
4. **上下文管理未拆分**：token 估算、压缩、strip 约 400 行
5. **架构 Agent 调度未拆分**：架构预处理、决策点、商业安全约 400 行
6. **范围拒绝/零安装约束未拆分**：_plan_scope_rejection、_content_scope_rejection 约 300 行
7. **hooks 常量未在 runtime 中使用**
8. **tool_specs 未驱动工具执行**
9. **3 个既有测试失败**（forced action、completion repair、simple text done）

## 下一轮如果继续拆，应优先拆什么

1. **工具执行器**（_run_tool + 20+ @staticmethod）→ 独立 tool_executor.py，风险中等
2. **Git 管理**（10+ _git_* 方法）→ 独立 git_context.py，风险低（已有 WriterGitManager）
3. **上下文管理**（token/compress/strip）→ 独立 context_manager.py，风险中等
4. **架构 Agent 调度**（invoke/decision/commercial）→ 独立 architecture_agent.py，风险低
5. **范围拒绝/零安装**（scope_rejection/zero_install）→ 独立 scope_guard.py，风险低
6. **hooks 常量实际使用**（runtime 日志/事件引用 HOOK_* 常量）
7. **tool_specs 驱动执行**（权限检查走 specs 而非硬编码）
8. **修复 3 个既有测试失败**（forced action、completion repair、simple text done）
