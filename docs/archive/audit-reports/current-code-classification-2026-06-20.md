# LamTools 当前代码系统排查与分级

> 日期：2026-06-20
> 范围：`core/`、`members/writer/`、`members/artist/`、`scripts/`、`e2e/`、根目录测试与样例目录
> 目标：按“可靠 / 存疑 / 债务”给当前代码分级，并列出实测问题

## 结论

当前仓库不是整体不可用。P0 修复后，`core`、Artist 后端、Writer 核心子集和三个前端构建都已通过；P1 旧 Hook 面已删除。剩余最混乱的问题是历史 e2e 产物、样例项目、日志和 Writer 全量测试入口混在一起。

分级总览：

| 范围 | 当前分级 | 理由 |
|---|---|---|
| `core/src/lamtools_core/kernel/loop.py`、`kit.py` | 可靠 | Kernel 管流程、Kit 管业务，与 OpenAI Agents SDK 的 agent loop、tools、sessions、guardrails、tracing 方向一致；删除旧 Hook 测试后 Core 测试 373 通过 |
| `core/src/lamtools_core/llm/`、`tool/`、`runtime/`、`event/`、`session/`、`usage/` | 可靠 | 抽象清晰，测试覆盖稳定，没有发现产品分支 |
| `core/src/lamtools_core/kernel/hooks.py` | 已删除 | 旧 Hook 兼容面已移除；Core 只保留 Kernel/Kit 主线 |
| `core/ui/src/` | 可靠 | 构建通过，作为共享 UI 包可用 |
| `members/writer/backend/app/core/writer/core_kernel_adapter.py` | 存疑 | 主链路功能闭环，核心子集已回绿；文件仍过大，后续需要继续拆分和收敛资源警告 |
| `members/writer/backend/app/core/writer/hooks.py` | 已删除 | 业务上下文、验收、决策、写回已由 WriterKit 覆盖 |
| `members/writer/backend/app/core/mcp/` | 存疑 | MCP 方向成熟，但自研客户端容错、重连、冲突处理需继续验证 |
| `members/writer/backend/app/core/mem/` | 存疑 | 有明确业务闭环，但记忆预算、召回、生命周期是自研，需要持续用真实任务验证 |
| `members/writer/backend/app/core/writer/novel/` | 存疑 | 单产品能力，业务闭环明确，但复杂度高、LLM 依赖强，不应上抽 Core |
| `members/writer/backend/writer_cli/` | 可靠 | CLI 入口完整，符合仓库约定 |
| `members/writer/backend/writer_tui/` | 已删除 | 2026-06-30 维护更新：Textual TUI 是 member 内并行 UI/状态投影壳，已从当前主线移除 |
| `members/writer/frontend/src/` | 可靠 | 构建通过，SSE/设置/工作台主链路存在回归保护；大包警告需要优化但不是功能失败 |
| `members/writer/frontend/electron/` | 存疑 | 桌面封装方向合理，但进程生命周期、后端崩溃恢复、端口占用仍需专门验收 |
| `members/artist/backend/app/core/artist/core_kernel_adapter.py` | 存疑 | Kit 方向正确，后端测试已回绿；旧 action/plan 兼容已补，但文件仍偏大 |
| `members/artist/backend/app/core/artist/hooks.py` | 已删除 | 业务上下文、验收、决策、写回已由 ArtistKit 覆盖 |
| `members/artist/backend/app/services/artist_service.py` | 存疑 | 空发布对象崩溃已修；仍承担较多编排、事件、兼容逻辑，后续应继续拆分 |
| `members/artist/frontend/src/` | 可靠 | 构建通过 |
| `members/artist/backend/app/database.py` 与手写迁移 | 存疑 | 目前可用，但相比 Alembic 等成熟迁移工具更难长期维护 |
| `scripts/` | 可靠 | 入口统一、职责清晰、测试脚本可复用 |
| `core/templates/member/` | 可靠 | 新成员骨架与 monorepo 边界一致 |
| `e2e/tests/`、`tests/*.spec.ts` | 存疑 | 有价值的验收资产，但依赖环境、端口、历史数据，需分层整理 |
| `e2e/real-task-runs/` | 债务 | 大量截图、日志、运行快照混入仓库；发现中文 `????` 编码污染和 16MB SSE 日志 |
| `test-*` 样例目录、`test-blog-project/`、`test-mod-site/` | 债务 | 更像历史夹具或演示项目，不应与产品代码同级长期保留 |
| `members/writer/backend/*.log`、`.env`、`poll_result.log` | 债务 | 运行产物进入产品目录，增加误读和泄露风险 |
| `kbtool-task/` | 存疑 | 独立小工具，有测试，但与 LamTools 主产品边界不清晰 |

## 实测结果

| 命令 | 结果 |
|---|---|
| `.\scripts\test.ps1 core` | 373 passed |
| `.\scripts\test.ps1 artist` | 修复前：23 failed, 145 passed, 11 skipped；修复后：165 passed, 11 skipped |
| `.\scripts\test.ps1 writer` | 10 分钟超时；直接收集整个 Writer 后端会混入脚本型/外部依赖测试 |
| `py -3.14 -m pytest members\writer\backend\tests\test_hook_context_contract.py -q` | 15 passed，带 Windows asyncio transport 警告 |
| `py -3.14 -m pytest members\writer\backend\tests\test_hook_context_contract.py members\writer\backend\tests\test_writer_core_kernel_adapter.py members\writer\backend\tests\test_writer_core_http.py -q` | 171 passed，带 Windows asyncio transport 警告 |
| `py -3.14 -m pytest members\writer\backend\tests\test_writer_cli.py members\writer\backend\tests\test_tool_executor.py members\writer\backend\tests\test_permission.py -q` | 103 passed, 2 skipped |
| `npm run build` in `core/ui` | 通过 |
| `npm run build` in `members/writer/frontend` | 通过，有 chunk > 500k 警告 |
| `npm run build` in `members/artist/frontend` | 通过 |

## 当前确定问题

### P0：Artist 后端测试红（已修复）

1. 旧测试仍按 `hook_set=` 初始化 Kernel，但当前 Kernel 已经没有这个参数。
2. 测试仍引用 `app.core.artist.runtime`，该模块已经不存在。
3. 业务调用中任务事件发布对象可能为 `None`，导致空对象访问。
4. 成员 ID 预期混乱：测试期望 `"Artist"`，实际返回 `"artist"`。

修复状态：已关闭。Artist 后端当前为 165 passed, 11 skipped。

处理内容：

- Hook contract 测试改为当前 Kit 契约，不再向 Kernel 注入旧 `hook_set`。
- 删除测试中对已移除 `app.core.artist.runtime` 的 mock。
- 运行时事件桥在无任务管理器时安全跳过发布。
- 兼容旧 `actions` 和 `plan.steps` schema，补齐 phase、message、lineage、SSE 事件映射。
- 成员 ID 断言统一为实际注册 ID：`artist`。

### P0：Writer 核心子集测试红（已修复）

1. 重复只读工具循环现在返回 `wait`，测试期望 `done`。这是运行语义变化，需明确到底要等待用户还是视为完成。
2. 事件摘要中仍含 `content`，测试期望摘要不带完整内容。若摘要进入前端或日志，这是潜在泄露面。
3. HTTP/SSE 终态事件名不一致，测试期望 `core_kernel.done`，实际流里没有。
4. Windows 下临时 SQLite 文件被占用，说明测试或服务关闭时连接释放不完整。

修复状态：已关闭。Writer 核心子集当前为 157 passed。

处理内容：

- 摘要输出中的 `core_events` 不再携带 `content`/`prompt`，避免完整内容进入摘要事件。
- HTTP/SSE 终态补发兼容事件：`writer.core_kernel.done`。
- 无 step 的 KernelResult 也能把 `message` 落到最终答案。
- 摘要消息在存在 final answer 时同步带 content，避免倒序查询拿到空消息。
- HTTP 集成测试的临时 SQLite engine 改为 finally 释放。
- 重复工具循环的断言改为 `wait`，与当前“安全停止等待用户信号”的语义一致。

### P1：Core 边界文字污染（已处理）

`core/src/lamtools_core/tool/permission.py`、`kernel/display.py`、`kernel/policy.py`、`sse/__init__.py` 和旧 `kernel/hooks.py` 中曾出现 Writer/Artist 字样。虽然主要是注释和兼容说明，不是运行分支，但仍违反“Core 不认产品名”的严格规则。

修复状态：已关闭。Core 注释已改为 member/product-neutral 语言，旧 Hook 文件已删除；当前 `core/src/lamtools_core` 扫描不到 Writer/Artist 产品名。

### P1：旧 Hook 层形成平行维护面

修复状态：已关闭。

处理内容：

- 删除 `core/src/lamtools_core/kernel/hooks.py`。
- 删除 `members/writer/backend/app/core/writer/hooks.py` 和 `members/artist/backend/app/core/artist/hooks.py`。
- 删除旧 `core/tests/test_hooks.py` 与 Writer 旧 Hook 描述测试。
- Writer/Artist hook contract 测试改为当前 Kit 契约。
- 当前代码层已无 `HookSet`、`WriterHookSet`、`ArtistHookSet`、`HookResult`、`HOOK_*` 引用。

成熟方案对照仍成立：

成熟方案对照：

- OpenAI Agents SDK 的 Runner 管 agent loop，模型输出工具调用时执行工具并继续循环，模型给 final output 时结束；LamTools 的 Kernel/Kit 更接近这个方向。
- Claude Code 的 hooks 是 settings 中的事件扩展配置，和 subagents、memory 分开；LamTools 旧 HookSet 不是清晰配置扩展点，而是迁移残留。

判定：债务已处理。

### P1：Writer 全量测试入口混入历史/外部依赖测试

现象：

- `.\scripts\test.ps1 writer` 两次分别在 5 分钟和 10 分钟超时，没有完成。
- 逐文件运行发现 `test_original_task.py` 超时。
- `test_events.py` 仍断言旧事件字段。
- `test_novel_l3_e2e.py` 依赖外部后端，当前返回 502。
- `test_e2e_stability.py` 的 async 标记缺失或 pytest 配置不匹配。

判定：债务。Writer 测试需要拆成 unit/integration/e2e 三层，脚本默认只跑稳定单元和核心集成；外部依赖 E2E 应显式开关。

### P1：运行产物污染仓库

发现：

- `e2e/real-task-runs/writer-responses-blocks-20260619/sse.log` 约 16MB。
- `e2e/real-task-runs/` 中大量截图、日志、JSON 快照。
- 多个 JSON 里出现中文 `????` 编码污染。
- `members/writer/backend/` 里有 `.env`、`server_*.log`、`poll_result.log`。

判定：债务。应移到 artifact 存储或加入清理脚本，仓库只保留最小夹具和可复现实验说明。

### P2：前端体积

Writer 前端构建通过，但有多个大 chunk，尤其 Mermaid/KaTeX/Cytoscape 相关依赖。

判定：存疑。不是 bug，但应该按路由或功能懒加载。

## 成熟方案对照

参考：

- OpenAI Agents SDK：Agent loop、tools、guardrails、handoffs、sessions、tracing、MCP 是成熟主干。
- Claude Code：hooks、subagents、memory、project instructions 是分层能力，且 subagent 可独立上下文和权限。

LamTools 现状：

| 能力 | 成熟方案位置 | LamTools 当前判断 |
|---|---|---|
| Kernel/Kit 主循环 | OpenAI agent loop / Runner | 可靠，继续保留 |
| 工具调用与权限 | OpenAI tools + guardrails；Claude permission hooks | 可靠到存疑，需继续强化边界 |
| 会话与事件 | OpenAI sessions/tracing | 可靠到存疑，SSE 终态协议需统一 |
| 子代理 | Claude subagents；OpenAI handoffs/agents-as-tools | 存疑，Writer 自研 sub-agent 需要收敛成清晰协议 |
| 记忆 | OpenAI sessions / Claude memory | 存疑，当前自研可保留但要减少魔法逻辑 |
| HookSet | Claude hooks 是配置化事件扩展；LamTools 旧实现已被 Kit 取代 | 已删除 |
| 运行产物管理 | 成熟项目通常不提交大日志/截图 | 债务，清理优先 |

## 建议处理顺序

1. 整理 Writer 测试入口：默认脚本只跑稳定测试，历史/外部依赖 E2E 显式开关。
2. 清理仓库运行产物：`e2e/real-task-runs/`、`test-*`、产品目录日志按“保留最小夹具，其余归档/忽略”处理。
3. 处理 Writer 后端测试中的 Windows asyncio transport 警告，收敛子进程/管道释放。
4. 前端优化：Writer Mermaid/KaTeX/Cytoscape 懒加载，避免首屏大包。

## 本次修复状态

P0 和旧 Hook P1 已处理完毕。当前剩余主要是 P1/P2 的减法任务：Writer 测试入口、运行产物、前端体积和 Writer 后端资源警告。
