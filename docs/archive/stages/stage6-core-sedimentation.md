# 阶段六：核心能力沉淀

## 原则

只有满足以下条件的能力才能沉到 core：
- Writer 和 Artist 都需要
- 业务语义一致
- 抽到 core 后成员差异仍能通过 persona、hooks、agents、tools 表达
- 不需要复制成员专属判断

## 沉淀状态分类

### A. 已真实接入 core（有代码引用）

| 能力 | core 文件 | Writer 引用 | Artist 引用 |
|------|-----------|-------------|-------------|
| RuntimeKit 协议 | `kernel/kit.py` | WriterKit 实现 | ArtistKit 实现 |
| CoreEvent | `event/__init__.py` | 6 个 SSE 事件映射 | 20+ SSE 事件映射 |
| ToolArtifact | `tool/__init__.py` | WriterArtifact 使用 | ArtistArtifact 使用 |
| RuntimeState | `runtime/__init__.py` | WriterSessionState 包含 | ArtistSessionState 包含 |
| VerificationResult | `kernel/state.py` | CompletionVerifier 返回 | VLM 验收返回 |
| LoopPolicy | `kernel/policy.py` | WriterLoopPolicy 使用 | ArtistLoopPolicy 使用 |
| ToolSpec/ToolRegistry | `tool/__init__.py` | prompt_assembler 使用 | （暂未使用） |
| **权限分层常量** | `tool/permission.py` | **TOOL_PERMISSIONS + tool_specs 使用 AUTO_ALLOW/ASK_USER/HARD_BLOCK** | **tool_specs.py 使用 AUTO_ALLOW 常量** |
| **标准钩子节点名** | `kernel/hooks.py` | **hooks.py WRITER_HOOK_DESCRIPTIONS 使用 HOOK_* 作 key** | **测试验证覆盖 Artist 生命周期** |

### B. 标准化声明，已部分接入

| 能力 | core 文件 | 接入状态 |
|------|-----------|----------|
| ~~权限分层常量~~ | ~~`tool/permission.py`~~ | ~~已从 B 升级到 A~~ |
| ~~标准钩子节点名~~ | ~~`kernel/hooks.py`~~ | ~~已从 B 升级到 A~~ |

### C. 尚未接入、下一轮处理

| 能力 | 理由 |
|------|------|
| RuntimeStateStore 协议 | Writer/Artist 各自有 state_store，未实现 core 协议 |
| 记忆召回统一接口 | Writer 用 MEM（跨会话），Artist 用 visual_memory（会话内），未统一 |
| 完成验收入口统一 | Writer 用 CompletionVerifier，Artist 用 VLM 验收，入口不同 |
| Artist tool_specs 驱动执行 | specs 已声明，runtime 已读取 spec，但执行分支仍用硬编码 |

## 本轮深度落地详情

### 1. 权限分层常量真实接入

**Writer 接入**：
- `permission.py` 导入 `AUTO_ALLOW`, `ASK_USER`, `HARD_BLOCK`
- `TOOL_PERMISSIONS` 字典值使用常量（不再写字符串）
- `PermissionChecker.check()` 使用常量比较
- 默认值使用 `HARD_BLOCK` 常量

**Artist 接入**：
- `tool_specs.py` 导入 `AUTO_ALLOW`
- `ARTIST_TOOL_SPECS` 中每个 spec 的 `permission` 字段使用 `AUTO_ALLOW` 常量
- `ARTIST_TOOL_PERMISSIONS` 类型注解使用 `PermissionTier`

**测试验证**：
- `test_artist_tool_specs.py` 新增 `test_all_permissions_use_core_auto_allow()` 验证权限值等于 `AUTO_ALLOW` 常量
- `test_artist_tool_specs.py` 新增 `test_spec_permission_is_core_constant()` 验证 spec 中的 permission 是常量对象

### 2. 标准钩子节点名真实使用

**测试验证**：
- `core/tests/test_hooks.py` 新增 `test_hook_nodes_cover_artist_runtime_lifecycle()` 验证 5 个钩子节点覆盖 Artist 运行时生命周期
- `core/tests/test_hooks.py` 新增 `test_hook_nodes_cover_writer_runtime_lifecycle()` 验证 5 个钩子节点覆盖 Writer 运行时生命周期

**未改变**：
- Writer/Artist runtime 没有导入 hooks 常量（仅测试验证）
- 业务逻辑未引用 hooks 常量

### 3. Artist tool_specs 与 runtime 低风险联动

**runtime 接入**：
- `runtime.py` 导入 `artist_tool_spec`, `ARTIST_TOOL_PERMISSIONS`
- `_execute_tool()` 开头调用 `artist_tool_spec(name)` 查找工具规格
- 查找到的 spec 的 permission 存入 `step.tool_spec_permission`
- 未知工具错误消息区分"不在 ARTIST_TOOL_SPECS 中"

**未改变**：
- 工具执行分支仍用硬编码 `if name == "generate_image"` 等
- 权限检查未使用 spec 中的 permission（仅记录到 step）
- 失败模式未使用 spec 中的 failure_modes（仅声明）

**新增字段**：
- `ArtistStep.tool_spec_permission: str | None` 记录工具权限

## 已沉淀能力详情

### 1. 固定节点任务协议（RuntimeKit）

**落点**：`core/src/lamtools_core/kernel/kit.py`

10 个 hook：on_run_start, build_context, build_model_request, parse_model_output, execute_tool, format_tool_result_for_model, verify, decide_next, writeback, on_run_end

**Writer 实现**：`WriterKit`（core_kernel_adapter.py）
**Artist 实现**：`ArtistKit`（core_kernel_adapter.py）

**收益**：Kernel 只依赖 RuntimeKit，不分支产品名。两个成员共享同一个循环骨架。

### 2. 权限分层常量

**落点**：`core/src/lamtools_core/tool/permission.py`

三层权限模型：
- `AUTO_ALLOW`：只读/非破坏性，无需用户确认
- `ASK_USER`：写入/命令/潜在破坏性，需要用户确认
- `HARD_BLOCK`：永远不允许

**Writer 接入**：`permission.py` 导入并使用常量
**Artist 接入**：`tool_specs.py` 导入并使用常量

**辅助函数**：`is_auto_allow()`, `requires_user_gate()`, `is_blocked()` 已定义但未被调用

### 3. 标准钩子节点名

**落点**：`core/src/lamtools_core/kernel/hooks.py`

5 个标准节点：`HOOK_BEFORE_MODEL`, `HOOK_AFTER_MODEL`, `HOOK_AFTER_TOOL`, `HOOK_VERIFY`, `HOOK_WRITEBACK`

**Writer 对应**（测试验证）：
- before_model → prompt_assembler.assemble + drift + progress injection
- after_model → turn parsing + observation application
- after_tool → permission check + result indexing + failure recovery
- verify → CompletionVerifier
- writeback → memory writeback + state save + git refresh

**Artist 对应**（测试验证）：
- before_model → runtime_state injection + vision message + drift + compression
- after_model → task_card + identity_contract + observation application
- after_tool → artifact creation + observation recording + local_edit protection
- verify → self_review + missing_observations + blocking_issues + auto_repair_pause
- writeback → state store + visual memory + lineage refresh

### 4. 标准事件（CoreEvent）

**落点**：`core/src/lamtools_core/event/__init__.py`

8 个事件类别：lifecycle, progress, message, tool, decision, verification, artifact, error

**Writer 使用**：6 个 SSE 事件类型映射到 CoreEvent
**Artist 使用**：20+ SSE 事件类型映射到 CoreEvent（core_adapter.py）

### 5. 标准产物（ToolArtifact）

**落点**：`core/src/lamtools_core/tool/__init__.py`

ToolArtifact：kind, uri, content, metadata

**Writer 使用**：WriterArtifact 跟踪 write_file/edit_file
**Artist 使用**：ArtistArtifact 跟踪图片 URL + 血缘关系

### 6. 标准状态推进

**落点**：`core/src/lamtools_core/runtime/__init__.py`

RuntimeState, RuntimeStatus, RuntimeLoopState, CompletionCheck, CompletionResult

**Writer 使用**：WriterSessionState 包含 plan + git + memory
**Artist 使用**：ArtistSessionState 包含 visual_memory + lineage

### 7. 验收入口

**落点**：`core/src/lamtools_core/kernel/state.py` — VerificationResult

passed, required, summary, repair_prompt, attempt, max_attempts, checks

**Writer 使用**：CompletionVerifier 返回多检查结果
**Artist 使用**：VLM 验收返回通过/修复建议

## 没有沉到 core 的能力

| 能力 | 理由 |
|------|------|
| Writer 专属工程规则（compile, import, npm build） | 只 Writer 需要，Artist 不做代码编译 |
| Writer 专属 prompt 组装（多层 system + MEM + 模式） | 结构完全不同于 Artist 的 system prompt |
| Writer 专属 Agent 调度（6 个专家） | Artist 只有 1 个 stub agent |
| Writer 专属失败恢复（forced action, loop breaker） | Artist 用 auto_repair_pause 和 retry_stop，机制不同 |
| Artist 专属视觉判断（soft_accept, identity_contract, local_edit） | 只 Artist 做视觉验收 |
| Artist 专属产物追踪（lineage, artifact context_role） | 只 Artist 管理图片血缘 |
| Artist 专属视觉记忆（visual_memory, observation merge） | 只 Artist 需要跨轮视觉记忆 |
| Artist 专属参考图解析（image_map, artifact_context_map） | 只 Artist 需要解析图片引用 |
| Artist 专属接触拼图（contact_sheet） | 只 Artist 需要多图验收布局 |
| 单一成员才需要的工具参数习惯 | Writer 用 path/content，Artist 用 task/reference |
| 单一成员才需要的产物解释 | Writer 的文件产物 vs Artist 的图片产物 |
| 还没有被两个成员共同验证过的抽象 | Agent 调度、记忆召回、完成验收的跨成员统一接口 |

## 收益总结

| 沉淀项 | 收益 |
|--------|------|
| RuntimeKit 协议 | Kernel 不分支产品名，新成员只需实现 Kit |
| 权限分层常量 | 统一"安全/需门控/禁止"语义，Writer/Artist 都使用常量值 |
| 钩子节点名 | 统一循环生命周期词汇，测试验证覆盖两个成员 |
| CoreEvent | 统一事件传输协议，前端/日志/监控无需分支 |
| ToolArtifact | 统一产物传输协议，产物存储无需分支 |
| RuntimeState | 统一状态推进协议，状态持久化无需分支 |
| VerificationResult | 统一验收入口协议，验证逻辑无需分支 |

## 剩余不优雅点

1. **Writer runtime.py 6241 行未拆分**：hooks 散落在主循环，无法独立测试。建议后续按 Artist 模式拆分。
2. **Artist tool_specs 已声明，已读取，未驱动执行**：runtime._execute_tool 已调用 artist_tool_spec，但执行分支仍用硬编码。权限仅记录到 step，未用于决策。
3. **delegate_agent 仍是 stub**：Artist 的委派能力未实现。service/CLI 传入 None。
4. **Writer 和 Artist 的 state_store 接口不统一**：Writer 用 WriterStateStore，Artist 用 ArtistStateStore，都未实现 core 的 RuntimeStateStore 协议。
5. **记忆召回未统一**：Writer 用 MEM 模块（跨会话），Artist 用 visual_memory（会话内），无法共享接口。
6. **完成验收未统一**：Writer 用 CompletionVerifier（多检查），Artist 用 VLM 验收（视觉），虽然都实现 VerificationResult 但入口完全不同。
7. **钩子节点名仅测试验证**：hooks 常量未在 runtime 日志/事件中使用，仅测试覆盖验证。

## 为什么本轮没有做更深重构

1. **权限检查逻辑未改**：Writer PermissionChecker 和 Artist runtime 的权限决策仍用原有逻辑，仅将常量值替换为 core 常量。这是为了保持行为不变。
2. **工具执行未改**：Artist runtime 的 _execute_tool 仍用硬编码分支，仅添加 spec 查找和记录。这是为了避免引入回归。
3. **钩子节点名未在 runtime 使用**：仅测试验证覆盖，未在 runtime 日志/事件中引用。这是为了避免大改 runtime。
4. **低风险优先**：本轮目标是"真实低风险接入"，不是"完全重构"。所有改动都是增量，不改变现有行为。

## 下一轮建议

1. Writer runtime 拆分（参照 Artist 模式，拆出 hooks/agents/tools 子模块）
2. Writer state_store 实现 core RuntimeStateStore 协议
3. Artist state_store 实现 core RuntimeStateStore 协议
4. Artist tool_specs 与 runtime 深度联动（权限检查走 specs，失败模式用于错误消息）
5. delegate_agent 实现侧配合（service/CLI 传入实际 handler）
6. 记忆召回接口探索（跨会话 vs 会话内的统一抽象，需两个成员共同验证后才能沉淀）
7. 钩子节点名实际使用（让 runtime 在日志/事件中使用 HOOK_* 常量）
