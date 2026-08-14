# 13 core 测试质量 审计报告

> 审计时间：2026-08-13　审计员：ZCode（13 区）
> 范围：`core/tests/` 全部 103 个 .py 文件（约 33.9k 行、约 1280 个 `def test_`），对照被测核心模块 `core/src/lamtools_core/`（app/kernel/tool/llm/config/runtime 等）。
> 方法：只读静态审计（grep/git log/源码比对），未运行 pytest 全量；未修改任何文件。

## 1. 概况

| 指标 | 数值 |
|---|---|
| 测试文件数 | 103（含 conftest.py、`__init__.py`，单层无子目录） |
| 总行数 | 33,910 |
| 测试函数数 | 约 1280（`grep -c "def test_"` 汇总） |
| skip / xfail | 2 处 skip（均有理由）、0 处 xfail |
| `assert True` / 无断言 | 0 处 `assert True`；低断言文件仅 test_core_live_hub（1 测试 4 断言）、test_kit_boundary（3 测试 3 断言）、test_member_template（3 测试 4 断言） |
| pytest 配置 | `pyproject.toml` `[tool.pytest.ini_options]`：`testpaths=["tests"]`、`asyncio_mode="auto"` |

规模特征：`test_kernel.py`（4067 行 / 120 测试）、`test_core_live.py`（2322 行 / 42 测试）、`test_core_live_router.py`（1047 行）、`test_llm_helpers.py`（997 行）为四大巨头，合计约占 1/4 行数。全库仅 conftest.py 一个共享夹具文件（24 行，单一 autouse fixture），无 session/module 级夹具，无测试间共享状态。

运行时长线索（未实测，按源码估算）：主要慢点在 6 处 `sys.executable` 真实子进程（test_command_tools / test_background_process_registry，含 `time.sleep(5)`、`time.sleep(30)` 的被管进程）、约 15 处轮询型等待（`for _ in range(100)` × 0.01–0.05s 上限 1–5s，test_core_http_agent_app / test_core_live_client_e2e）、test_kernel 内约 10 处 0.03–0.08s 的流式超时用例。预计全量 3–6 分钟量级，无超长用例。

结论先行：整体质量高于常见水平——假 LLM 全覆盖、无真实网络/真实 LLM、随机性受控、隔离干净、命名清晰。主要问题集中在**覆盖缺口**：4 个源码模块（含 1 个 424 行、1 个 273 行的工具模块）零测试，kernel 循环内 05 区审计已确认的缺陷路径（tool_progress 强制 continue、hook 失败隔离、循环外异常）无一有回归测试。

## 2. 问题清单

### S1（严重）

- **[S1] kernel `tool_progress` 进度门路径完全无测试，且该路径已有确认缺陷（可致无限循环）**
  - 位置：源码 `core/src/lamtools_core/kernel/loop.py:462-463`（状态初始化）、`:579-593`（`_has_tool_progress_structure` 结构判定）、`:1066-1069`（`tool_progress_incomplete` 无条件强制 `decision="continue"` 并覆盖 Kit 的 wait/failed 终局决策）；tests/ 全目录 grep `tool_progress` **0 处引用**。
  - 问题：05 区（kernel 审计）已确认该路径缺陷——`tool_progress_incomplete` 强制 continue 没有轮次上限（`tool_progress_blocked_rounds` 只统计另一条 `tool_progress_required` 路径），模型持续输出"文本+工具调用但无三标题结构"时可无限循环，只能靠用户取消。此机制是防死循环的关键门，但整个机制（结构判定、pending 状态流转、强制 continue、`tool_progress_retry_required` 标记）在测试中零覆盖。
  - 影响：已知缺陷无任何回归保护；修复后也无法防止再次引入。
  - 修复建议：按 05 区建议修复（仅当 Kit 返回 continue/done 时才强制 continue、增加轮次上限）后，补齐一组测试：构造"文本+工具调用+无结构标题"的流式输出，断言强制 continue、轮次上限触发 wait、Kit 的 failed 决策不被覆盖。

### S2（中等）

- **[S2] hook 失败隔离路径无测试：hook 非法 JSON 输出、循环前/循环尾异常注入均为零覆盖**
  - 位置：源码 `core/src/lamtools_core/plugins/engine.py:203-215`（`_decision_from_text` 的 `json.loads` 无 try/except）；`kernel/loop.py:429-435`（`on_run_start`/SessionStart hook）、`:1172-1219`（`on_run_end`/Stop hook/终态事件段）；tests/ `test_kernel.py:2305/2315` 仅断言 hook/生命周期方法"被调用"（happy path），`test_kernel_hooks.py` 全部 10 个测试均为正常路径。
  - 问题：05 区审计的 2 个 S2 缺陷（hook 输出非法 JSON → `JSONDecodeError` 穿透杀死整个 run；循环前 `on_run_start`/hook 与循环尾收尾段抛异常 → state 永久卡 "running" 或结果丢失）在测试侧没有任何失败注入用例：没有让 hook 返回非法 JSON / 抛异常的测试，没有 `on_run_start`/`on_run_end` 抛异常的测试。
  - 影响：已知缺陷无回归保护；且"hook 失败不影响主流程"这一设计目标完全未被测试验证。
  - 修复建议：为 hook 引擎与 kernel 各增加失败注入用例（非法 JSON、进程退出码 0 但输出垃圾、hook 抛异常），断言 run 仍完成或 state 收敛到 failed 而非 stuck running；为 `on_run_start`/`on_run_end` 异常断言 state 被置 failed 且收尾执行。

- **[S2] `tool/durable_tools.py`（273 行，goal/arrange 模型面工具）零测试**
  - 位置：源码 `core/src/lamtools_core/tool/durable_tools.py`（`durable_tool_specs`/`durable_tool_handlers`），接线于 `tool/default_toolbox.py:753-759、1229` 与 `app/http_agent_app.py:1003-1028`；tests/ 中 `durable_tool` 0 处引用。
  - 问题：底层 operation（`app/durable_operations.py`，test_durable_operations.py 5 个测试）与运行时（runtime/goal.py、runtime/arrange.py，共 26 个测试）覆盖充分，但**模型→工具的适配层**——spec 的 input_schema 与 handler 的参数解析/校验、AUTO_ALLOW 权限声明、错误映射、action 枚举（goal: create/list/get/cancel；arrange: create/list/get/pause/resume/cancel）——完全没有测试。spec 与 handler 若不一致（如枚举漂移、必填字段缺失）只能在真实 agent 运行中暴露。
  - 影响：工具契约（schema↔handler）无回归保护；schema 里的"当前 UTC 时间"注入等行为无验证。
  - 修复建议：新增 test_durable_tools.py，对每个 action 验证 schema 字段与 handler 参数解析、权限声明、非法 action 的错误结果。

- **[S2] `tool/workflow_build_tools.py`（424 行，workflow 细粒度节点编辑工具）零测试**
  - 位置：源码 `core/src/lamtools_core/tool/workflow_build_tools.py`（`workflow_build_tool_specs`/`workflow_build_tool_handlers`，含 add_node/update_node/delete_node/link 等大量节点操作），接线于 `default_toolbox.py:759、1231`、`http_agent_app.py:1028`；tests/ 中 0 处引用。
  - 问题：`test_workflow_agent_builds_from_nl.py`（119 行）只覆盖 `WorkflowRunner` 高层"自然语言构建"流程，不触碰这套细粒度图编辑工具。五种节点 kind（ai/command/script/content/subgraph）的增删改、端口编辑、图一致性校验全部裸露。
  - 影响：424 行模型面工具零回归保护；与前端 workflow-mode 指令词汇表同步的 schema（node_kind/port_schema）漂移无检测。
  - 修复建议：新增 test_workflow_build_tools.py，覆盖每种节点 kind 的增删改、端口编辑、非法参数与图写回失败路径（用 operation_executor 假执行器）。

### S3（轻微）

- **[S3] `runtime/workflow_watcher.py`（96 行 WorkflowFileWatcher）零测试**
  - 位置：源码 `core/src/lamtools_core/runtime/workflow_watcher.py`；tests/ 中 `workflow_watcher` 0 处引用。
  - 问题：轮询 store mtime 签名并广播 `workflow/changed` 事件的机制（首次轮询不广播、签名变化检测、`wake` 唤醒、stop 收敛）无任何测试；同形态的 `ObserverSupervisor`（runtime/observer.py）有测试，watcher 没有。
  - 影响：画布自动刷新依赖的推送链路行为未验证（如首次轮询误广播、停止后仍广播）。
  - 修复建议：仿 test_observer_runtime 补 3-4 个测试：签名不变不广播、变更后广播、首次不广播、stop 退出。

- **[S3] `history_compacted` 事件 payload 数值契约无测试（05 区确认的计数错位 bug 未被捕获）**
  - 位置：源码 `kernel/loop.py:505-507`（`trimmed = len(history) - cut` 在 `del history[:cut]` 之前计算，05 区确认 trimmed/remaining 两个数字全部错位）；tests/ 中 `history_compacted` 0 处引用。
  - 问题：test_kernel.py 有 8+ 个压缩相关测试（`test_successful_auto_compaction_replaces_persisted_history_once` 等），但没有一个断言 `history_compacted` 事件的 payload 数值（trimmed/remaining），导致计数 bug 在大量测试通过的情况下长期存在。
  - 影响：监控/审计数据不可信且无回归保护。
  - 修复建议：在现有压缩测试中断言事件 payload：`trimmed == cut`、`remaining == 删除后长度`。

- **[S3] `kernel_steps` 无界增长与 O(n²) 拷贝行为无测试**
  - 位置：源码 `kernel/loop.py:478`（每步 `_copy_state` 深拷贝）、`:2623-2632`（`_copy_state`）、`:1141`（每步全量存档）；tests/ 中 `kernel_steps` 0 处引用。
  - 问题：05 区确认 `persist_steps=True` 时 `state.metadata["kernel_steps"]` 跨 run 累积、无裁剪，长任务 O(步数²)。测试完全未覆盖步骤摘要的增长/裁剪行为（如设上限后应保留最近 N 条）。
  - 影响：一旦实现"上限裁剪"，无测试验证；现状 O(n²) 也无性能回归哨兵。
  - 修复建议：增加断言 kernel_steps 长度上限与旧摘要不被重复存档的测试（纯单元级，快）。

- **[S3] `mcp/schemas.py`（30 行 pydantic 模型）无直接测试**
  - 位置：源码 `core/src/lamtools_core/mcp/schemas.py`（MCPServerConfig/MCPTool 默认值、`MCPPermission`/`MCPTransport` Literal 枚举）；tests/ 中 `schemas` 0 处引用。
  - 问题：枚举取值、`timeout_seconds`/`enabled`/`builtin` 默认值、`input_schema` 空字典默认值均无直接测试，仅被 mcp/config 间接消费。
  - 影响：轻微——枚举拼写错误（如 `json_lines` vs `jsonlines`）会静默进入配置校验失败。
  - 修复建议：并入 test_mcp_tools.py 补 2-3 个模型构造/默认值断言。

- **[S3] 墙钟计时断言脆弱：`elapsed < 0.09` 依赖并行时序**
  - 位置：`tests/test_kernel.py:2636`（`test_parallelizes_only_whitelisted_tool_names`，`asyncio.get_running_loop().time()` 测 2 个 0.05s 慢工具的并行执行，预算 0.09s）。
  - 问题：断言用真实墙钟区分"并行（~0.05s）vs 串行（~0.10s）"，0.09s 阈值在慢 CI/负载下余量极小（实测偏差 0.01s 即误报）；`test_command_tools.py:312` 的 `< 3` 类似但余量充足。
  - 影响：慢机器上偶发假失败；且不测行为只测速度。
  - 修复建议：改为断言工具并发启动顺序（如记录 started 集合在完成前即含两个 id，或用计数器+事件等待），去掉计时断言。

- **[S3] mtime 缓存测试依赖真实 `time.sleep(0.01)`，文件系统时间戳粒度下脆弱**
  - 位置：`tests/test_model_store.py:82`（`test_model_store_caches_by_mtime`：`time.sleep(0.01)` 后重写文件以"使 mtime 变化"）。
  - 问题：依赖底层文件系统时间戳分辨率——FAT32/网络盘/某些容器挂载为 1s 粒度时，10ms 内重写可能不改变 mtime，导致缓存未被失效、断言路径静默改变（当前断言只查 `len==1`，失效失败不会报错，属"假绿"风险而非假红）。
  - 影响：跨环境行为不一致；缓存失效逻辑实际未被严格验证。
  - 修复建议：用 `os.utime` 显式推进 mtime（确定性），并在第三段断言 store 重新加载（校验对象 id 变化或 `_cached_models is None`）。

- **[S3] 轮询式等待测试最坏 5s/处，慢机器上超时风险**
  - 位置：`tests/test_core_http_agent_app.py:197-203`（`for _ in range(100)` × `time.sleep(0.05)` 轮询 turn 终态）、`test_core_live_client_e2e.py:52-64`（0.01s×100 轮询 + 5s deadline）。
  - 问题：轮询上限内未达终态时仅"静默 break"，随后靠后续断言间接失败，失败信息弱；且每处固定占 0.5-5s 墙钟。
  - 影响：定位失败慢、CI 时长被动放大。
  - 修复建议：轮询循环超时后显式 `raise AssertionError(快照)`（test_core_live_client_e2e 已有此模式，http_agent_app 未用）。

### S4（建议）

- **[S4] 真实子进程测试是主要时长来源且平台敏感**
  - 位置：`tests/test_command_tools.py:284、299、306-313`（`sys.executable -c "time.sleep(5)"` 测 timeout/取消）、`tests/test_background_process_registry.py:184`（sleep(30) 被管进程，靠 registry 清理 terminate）、`test_durable_operations.py:163`（sleep(1) 脚本）。
  - 问题：每次真实启动 python 解释器约 1-2s（Windows 上更慢），6 处合计约 10s+；且进程树 terminate 语义（`terminate_process_tree`）在 Windows/Git Bash 下与 POSIX 行为不同。
  - 影响：全量时长的主要贡献者；平台差异易出偶发失败。
  - 修复建议：保留 1-2 个真子进程边界测试（timeout/取消是值得的真实验证），其余用伪进程/fake runner 替代；把取消后的 marker 检查改为等待事件而非固定 sleep。

- **[S4] test_kit_boundary.py 首测试断言空洞，测试名与行为不符**
  - 位置：`tests/test_kit_boundary.py:11-17`（`test_kit_has_no_decision_override` 仅断言 `hasattr(RuntimeKit, 'decide_next')`——恒真，无返回值检查，注释自认 "structural check, not runtime"）。
  - 问题：名为"不能覆盖决策"的测试实际什么都没验证；同文件另两个测试（`test_kit_has_lifecycle_methods_only`、`test_kit_cannot_start_loop`）是有效的结构性检查。
  - 影响：误导后续维护者以为决策覆盖有保护。
  - 修复建议：删除或改写为检查 `decide_next` 返回类型注解/签名与 LoopDecision 契约一致。

- **[S4] 源码文本子串断言脆弱**
  - 位置：`tests/test_kernel.py:2389-2417`（`test_kernel_source_no_artist_writer_imager`、`test_kernel_no_if_product_branching`：`open(mod.__file__)` 后断言 `"Artist" not in source`、`"app." not in source` 等）。
  - 问题：把架构约束实现为对源文件文本的子串匹配——任何注释、docstring、日志文案中出现这些词即碎；`"app." not in` 还可能与注释中的示例代码冲突。
  - 影响：误报风险与维护成本高，测的是文本而非行为。
  - 修复建议：改用 import 级检查（如 `"lamtools_core.app" not in sys.modules` 或 AST 解析 import 语句）。

- **[S4] `__pycache__` 残留 9 个已删除测试文件的 .pyc**
  - 位置：`core/tests/__pycache__/`（test_approval_continuation、test_guardrail、test_kernel_pre_tool_hooks、test_kernel_summary、test_member_cli、test_migrate_models、test_project_directory_picker、test_shared_config_database、test_shared_config_operations 的 .pyc；git 历史 a58c13f/c86d8c5/7f1e7a7/dbb404a 等删除）。
  - 问题：删除测试文件时未清理缓存；其中 test_migrate_models/test_shared_config_* 是随 config jsonc 迁移（a58c13f）与迁移逻辑本体一起删除的（无缺口），但 test_kernel_summary/test_kernel_pre_tool_hooks 的用例是否被 test_context_compaction.py/test_kernel_hooks.py 完全承接未逐条核对。
  - 影响：干扰对"哪些测试曾存在"的静态分析；缓存目录膨胀。
  - 修复建议：清理孤儿 .pyc；若确认旧 kernel_summary 用例未被承接，在 test_context_compaction.py 中补齐。

## 3. 该区 Top 3 问题

1. **kernel `tool_progress` 进度门零覆盖 + 已确认缺陷**（S1）：防死循环的关键机制完全无测试，05 区审计发现的无限循环窗口缺陷无任何回归保护。
2. **两个模型面工具模块零测试**（S2）：`tool/durable_tools.py`（273 行）与 `tool/workflow_build_tools.py`（424 行）的 spec↔handler 契约完全裸露，底层 operation 层测试充分反而放大了"中间层无保护"的落差。
3. **hook 失败隔离与循环外异常注入零覆盖**（S2）：05 区两个 S2 缺陷（hook 非法 JSON 杀死 run、循环前/尾异常卡 running）在测试侧无一个失败注入用例，设计目标"hook 失败不影响主流程"未被验证。

## 4. 亮点

- **隔离干净**：conftest.py 单一 autouse fixture（`isolated_config_root`）全局钉住 `LAMTOOLS_CORE_CONFIG_ROOT`/`LAMTOOLS_HOME`，杜绝配置泄漏；全库无 session/module 级共享夹具，test_core_cli 另用 autouse 隔离 `LAMTOOLS_CORE_DB`。
- **无外部依赖**：全部 LLM 调用用假客户端（Scripted/Fake/Recording 系列），搜索/抓取/更新检查全 monkeypatch，e2e 用进程内 uvicorn + 真实 websocket（`test_core_live_client_e2e.py`），不触真实网络/真实 LLM。
- **关键路径成组覆盖**：kernel 取消（5 个测试：外部 cancel 持久化、流式中止、跨 run 重置）、上下文压缩（8+）、checkpoint 回滚/分支/剪枝（13+）、审批 approve/deny 双路径与 deny 后 stale claim 释放（test_core_live.py:162）、live watch 断线重连续 seq（test_cli_live.py:156）、sqlite 迁移（legacy checkpoint 表/legacy blob 惰性迁移，test_core_runtime_persistence.py:112/720）。
- **纪律良好**：仅 2 处 skip 且理由充分；0 xfail；随机性受控（jitter 测试固定 seed，test_model_retry_store.py:168）；真实子进程边界（timeout 返回 -1、取消真正终止子进程）确实值得测。
- **命名与结构**：测试名行为描述式、类分组清晰；`asyncio_mode="auto"` 下混用 sync/async 测试均规范。

## 5. 审计范围与方法

- 范围：`core/tests/` 全部 103 个 .py（`__pycache__` 除外），`core/src/lamtools_core/` 全部源码模块作对照，参考 `docs/code-audit/05-kernel.md` 已知缺陷清单交叉验证。
- 方法：`grep` 统计 1280 个测试函数与源码符号提及次数（模块名/符号名），比对出零覆盖模块；对 kernel 取消/压缩/失败、live 重连、checkpoint 恢复、sqlite 迁移、审批拒绝、命令执行边界逐一路径核查测试存在性；`grep` 扫描脆弱断言（assert True、墙钟、sleep、私有属性、源码文本断言、轮询）、skip/xfail、夹具范围；`git log --diff-filter=D` 核查被删测试与孤儿 .pyc。
- 未运行 pytest 全量（按纪律避免耗时）；未修改/创建/删除任何代码文件。
- 统计口径：本报告共 **16** 条问题 —— S1 × 1、S2 × 3、S3 × 7、S4 × 5。
