# Sunday Runtime 整治：覆盖清单与有序执行计划

> 分支 `sunday/reliable-base`。本文是 6.1 要求的计划文档：按依赖、风险和共同根因排序，
> 不按文件逐个改。
> 数据来源：`agent_docs/superagent_orphan_fix_status.md` 第 8-10 节，原始日志
> `.lam/baseline_pristine.log` / `.lam/baseline_branch.log`。

## 0. 当前事实基线

| 指标 | pristine HEAD | 本分支 |
|---|---|---|
| passed | 4043 | 4089 |
| failed | 222 | 205 |
| skipped | 9 | 9 |
| 共有失败 | — | 203 |
| 分支新增失败 | — | 2（全量特有，独立 5/5、负载 4/4 均通过） |
| 分支修好 | — | 19 |

## 1. 失败聚类（按共同根因，不按文件）

### 1.1 已确认的共同根因（本分支已修）

| 簇 | 规模 | 根因 | 状态 |
|---|---|---|---|
| 事件循环归属 | 6+ | 插件 `startup_task` 跨循环复用；`await_plugin_backends` 用新循环 gather 旧 Task | 已修（`89b89caf`），新增 7 例回归 |
| Job 隔离失效 | — | `KILL_ON_JOB_CLOSE` 常量写成 `0x200`（应为 `0x2000`）、`LimitFlags` 偏移 40（应为 16） | 已修（`ff101f7d`），1000 次强杀 0 孤儿 |
| 目录权威判定 | 2 | 无项目会话被误判为 `invalid-state`，与"缺席≠非法"契约冲突 | 已修（`06ee3849`） |
| 测试夹具缺件 | 1（阻塞全量收集） | `.agents/` 被 gitignore，工作树缺失 | 已修（`b7c88fa5`），自动准备 |

### 1.2 待处理的簇（按杠杆排序）

| 优先级 | 簇 | 规模 | 证据 | 初步判断 |
|---|---|---|---|---|
| P1 | `test_default_toolbox.py` 全部失败 | 27 | 其中 `'blocked' == 'ok'` 12 项、`True is False` 5 项、`'blocked' == 'failed'` 4 项；**原始 HEAD 上 27 项完全相同** | 工具审批/权限分级的契约整体位移，最可能是**一个**根因 |
| P2 | `test_context_compaction.py` | 16 | 压缩预算与段合并断言 | 待聚类 |
| P3 | `test_kernel.py` | 12 | 内核回合状态机 | 待聚类 |
| P4 | `test_core_cli.py` / `test_core_sub_agent_runner.py` | 各 10 | CLI 输出与子 Agent 运行器 | 待聚类 |
| P5 | 环境类 | ≈22 | 缺 Rust 控制器、连接被拒、DNS | 提供自动化准备方式即可消除 |
| P6 | 其余断言/异常 | ≈100 | 未逐项定性 | 待聚类 |

### 1.3 结论

203 项**不是**一个根因；但按上表，P1 单簇占 13%，且有高度一致的症状
（工具应当放行却被判 blocked），先啃它最划算。**在完成 P1 的根因定位前，
不应逐文件修补其余簇。**

## 2. 功能覆盖清单（审查维度，不是功能清单）

| 维度 | 审查要点 | 现有证据 | 缺口 |
|---|---|---|---|
| Agent Loop | 回合状态机、取消/封板、引导注入 | 跨循环 7 例；`turn_ending` 契约 | 状态机竞态未系统覆盖 |
| 工具系统 | 白名单、审批分级、路径固化、执行目录 | `test_default_toolbox` 27 项失败未定性 | **P1 待办** |
| 权限审批 | 闸门优先级、续跑路径、硬阻断 | 第 8 项双场景已验 | 权限绕过未专项 |
| Sub-agent | 运行器、恢复、接管 | `test_core_sub_agent_runner` 10 项失败 | 待聚类 |
| 插件 | 生命周期、跨循环、依赖占位、打包边界 | 已修跨循环与依赖占位 | 打包边界 2 项契约过期 |
| 调度 | 并发闸门、租约、代际隔离 | 1000 次强杀、100 次崩溃恢复 | 24h soak 未做 |
| 持久化 | 事务、CAS、迁移幂等 | `_LATE_COLUMNS`、CAS 已验 | 事件投递语义待补 |
| 并发/进程 | Job 隔离、进程树、句柄 | 1000 次强杀 0 孤儿 | 句柄泄漏计数未做 |
| 会话生命周期 | 工作目录、重启恢复 | 目录权威已修 | 长会话未压测 |
| 跨端通信 | WebSocket RPC、重置 | 3 项已恢复 | 未专项压测 |
| 资源回收 | Task/Future/Lock/连接 | 跨循环 7 例 | `fail-closed` 未做 |

## 3. 有序执行计划

按依赖与杠杆排序；每步都必须先有失败复现。

| 步 | 内容 | 前置 | 验收 |
|---|---|---|---|
| 0 | ✅ 全量基线 + 粗分类 + 夹具自动化 | — | 已完成 |
| 1 | **P1：`test_default_toolbox` 27 项单一根因定位** | 0 | 一份根因说明 + 最小复现；判定是产品缺陷还是契约过期 |
| 2 | 按 1 的结论修复（产品缺陷）或更新契约（附产品正确性证明） | 1 | 27 项转绿，且不降低断言 |
| 3 | P2/P3 聚类（压缩、内核） | 1 的方法论 | 每簇给出根因或明确排除 |
| 4 | 环境类 22 项：Rust 控制器/网络的自动化准备 | 0 | 一条命令可复现，不再依赖人工 |
| 5 | 无人值守 fail-closed（原子 Job 失败即拒启） | 0 | 成功/失败/降级三路径测试 |
| 6 | 副作用专项：文件、网络、外部命令，覆盖取消/超时/租约失效/落库前崩溃 | 5 | 区分"可终止"与"需幂等或补偿" |
| 7 | 资源生命周期：应用关闭主动释放，不依赖 `Task.cancel()` | 0 | 句柄/连接/进程计数归零 |
| 8 | 冻结提交 | 1-7 | 记录最终 SHA |
| 9 | 最终验收：全量回归、竞态、定点注入、1000 次强杀、24h Soak | 8 | 全部针对最终 SHA |

## 4. 方法约束

- 审查 → 复现 → 根因 → 方案比较 → 修复 → 反向验证 → 回归 → 记录。
- 不为全绿降断言、跳测试、吞异常或改安全语义。
- 无法解决时记录证据、影响与阻断关系，继续不依赖它的工作。
- 外部依赖无法消除时明确标注，不伪装通过。

## 5. 已知限制（当前）

1. 203 项仅有粗分类，未逐项定性。
2. 2 项新增失败只在全量进程内复现，尚未定性。
3. `test_plugin_packaging_boundary` 2 项把 PowerShell 字面量当契约，属过期断言，未修。
4. 24 小时 Soak 与 1000 次强杀均针对更早提交，需在冻结后重跑。

## 6. P1 根因定位结论（27 项 test_default_toolbox）

### 6.1 现象

27 项失败跨工具规格、审批标记、路径放行、MCP 调用、子 Agent、模式拦截、生图，
但错误签名高度集中：

- `操作等级 2 超过免问线 1，需要确认` ×12（断言 `'blocked' == 'ok'`）
- `'blocked' == 'failed'` ×4
- `True is False` ×5（放行/拦截布尔断言）

### 6.2 机制

`ApprovalGate.check()`（`core/src/lamtools_core/tool/approval.py:247-294`）：

```python
threshold = self.auto_approve_level
if threshold is None:
    threshold = AUTO_APPROVE_LEVELS.get(preset, 1)   # preset 默认 "ask" → 1
...
ask = not blocked and not approved_mcp and level > threshold
```

而 `AUTO_APPROVE_LEVELS = {"ask": 1, "auto": 2, "full_access": 3}`
（`tool/operation_levels.py:8`），`ApprovalGate.__init__` 的 `permission_preset` 默认是
`"ask"`（`approval.py:175`）。

用例统一用 `build_core_toolbox(approval_policy="auto_approve")` 构造，指望 tier-2 的写操作被放行；
但 `approval_policy` 与 `permission_preset` 是**两个正交维度**：

| 维度 | 取值 | 作用 |
|---|---|---|
| `approval_policy` | `require` / `auto_approve` | 谁来回答审批（人 / 自动） |
| `permission_preset` | `ask`(1) / `auto`(2) / `full_access`(3) | 免问线在哪一级 |

所以 `auto_approve` 只代表"不必等人回答"，不代表"放宽到第 2 级"。当前产品行为是自洽的。

### 6.3 判定：测试契约过期，不是产品缺陷

- `default_toolbox.py:1125` 的 docstring 写着 `auto_approve bypasses the gate`，这句是过时注释，
  与现在的两维模型冲突，需要同步修正文案（不是改逻辑）。
- 若反过来让 `auto_approve` 隐含 `permission_preset="auto"`，等于**把免问线从 1 抬到 2**，
  属于放宽安全语义 —— 按约束（不得为测试通过改安全语义）**不予采纳**。

### 6.4 修复方案（未执行，仅记录）

1. 逐个用例判断真实意图：
   - 意图是"自动回答审批、但仍受档位限制" → 保留 `approval_policy`，断言改为期望 blocked/requires_approval；
   - 意图是"验证 tier-2 可放行" → 显式加 `permission_preset="auto"`。
2. 27 项必须逐项判断，不能批量 sed，否则会把"应该拦截"的用例也放开。
3. 同步修正 `default_toolbox.py:1125` 的过时 docstring。

**这一步没做**：需要逐项读用例语义，属于下一轮的第一件事。
