# 验证报告：真实执行内容、未验证项与置信度

本报告回答一个问题：前面四份文档里的结论，哪些是真跑过的，哪些是推断的。

原则：跑过的给命令与输出，没跑过的明确写没跑。不把推断写成事实。

---

## 1. 真实执行的六项

### 1.1 现有 Rust Core 编译状态

命令：`cd core/runtime-rs && cargo check --all-targets`

结果：**失败**。

```
Checking lamtools-runtime v0.1.0 (E:\LamTools\core\runtime-rs)
error: couldn't read `src\../../src/lamtools_core/plugins/bundled/git/plugin.json`: 系统找不到指定的路径。 (os error 3)
  --> src\plugin_catalog.rs:31:9
   |
31 |         include_str!("../../src/lamtools_core/plugins/bundled/git/plugin.json"),
   |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

error: could not compile `lamtools-runtime` (lib) due to 1 previous error
error: could not compile `lamtools-runtime` (lib test) due to 1 previous error
```

含义：当前分支的共享核心不可编译。这不是我的推断，是本次执行的输出。附带影响：`.github/workflows/ci.yml` 里 `mobile-android` job 的 `cargo test --manifest-path core/runtime-rs/Cargo.toml` 必然在同一处失败，所以"双端 CI 全绿"目前不成立。

### 1.2 现有代码的结构度量

脚本：`.tmp/arch-measure.py`，只读，输出到标准输出。

执行结果摘录：

```
module_count: 26

=== 2-cycles ===       2-cycle count: 0
=== 3-cycles ===       3-cycle count: 0

=== fan-out ranking ===
  7  tool_catalog  -> ['fetch_tools', 'image_gen', 'project_tools', 'skills', 'study', 'sub_agent', 'web_search']

=== lines per module, grouped by concern ===
study_domain             7972   25.6%
workflow_domain          6071   19.5%
agent_loop_types         2388    7.7%
model_provider           5344   17.1%
extensions               4797   15.4%
tools                    3024    9.7%
context                   683    2.2%
ops_meta                  901    2.9%

=== external coupling ===
python_source_tree       files=5 occurrences=33
tauri                    files=1 occurrences=1
android_jni              files=0 occurrences=0
```

第二个脚本 `.tmp/arch-coupling.py` 测量每个模块对 crate 根契约的依赖：

```
total lib lines: 31180
lines in modules that touch root contract: 18682 (59.9%)
modules touching root contract: 16 of 26
```

这两个脚本是可复算的。任何人重跑都得到同样数字，因为它们只做文本统计，不依赖我的判断。

### 1.3 隔离参考原型

位置：`.tmp/arch-spike/`，一次性代码，不在 `core/` 内，不进版本库，也不参与任何构建。

规模实测：

```
prod_lines: 793
test_lines: 227
总行数: 1020
直接依赖: rusqlite, serde, serde_json
传递依赖: 32
编译: Finished `test` profile in 8.59s
```

测试执行结果，全部通过：

```
running 10 tests
test tests::queue_serialises_and_cancels_by_run_id ... ok
test tests::cancel_stops_before_any_tool_runs ... ok
test tests::expired_approval_is_not_consent ... ok
test tests::same_tool_call_with_different_args_is_refused ... ok
test tests::idempotent_tool_is_requeued_after_crash ... ok
test tests::seq_is_monotonic_per_thread_and_independent_across_threads ... ok
test tests::duplicate_request_id_produces_one_receipt_and_one_event ... ok
test tests::full_turn_writes_a_replayable_journal ... ok
test tests::approval_is_bound_to_args_and_expiry ... ok
test tests::dispatch_then_crash_marks_non_idempotent_unknown_and_never_replays ... ok

test result: ok. 10 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s
```

每个测试证明什么，逐条对应到 `03` 号文档的不变量：

| 测试 | 证明的不变量 |
|---|---|
| `duplicate_request_id_produces_one_receipt_and_one_event` | I2 幂等：重发只产生一个收据一个事件 |
| `seq_is_monotonic_per_thread_and_independent_across_threads` | I1 seq 单调且 thread 之间独立 |
| `dispatch_then_crash_marks_non_idempotent_unknown_and_never_replays` | I3 前置落盘、I4 未知态不重放 |
| `idempotent_tool_is_requeued_after_crash` | 恢复策略按副作用分类 |
| `approval_is_bound_to_args_and_expiry` | I5 参数绑定、I6 审批一次性 |
| `expired_approval_is_not_consent` | I6 过期不等于同意 |
| `cancel_stops_before_any_tool_runs` | I8 取消后不开始新工具 |
| `queue_serialises_and_cancels_by_run_id` | I7 排队而非拒绝 |
| `full_turn_writes_a_replayable_journal` | I1 与 I9 完整回合产生可重放日志 |
| `same_tool_call_with_different_args_is_refused` | I5 同一调用 ID 换参数被拒 |

### 1.4 故障注入

原型里的故障注入是真实的，不是模拟返回值：

| 注入方式 | 做法 | 观察结果 |
|---|---|---|
| 派发后进程死亡 | `mark_dispatched` 之后不调用 `finish_tool_call`，直接重开连接跑 `recover()` | 阶段被标为 `Unknown`，再次 `prepare_tool_once` 返回"必须人工核对"，工具未被再次执行 |
| 参数被篡改 | 用同一 `approval_id` 提交不同参数 | 返回 `ApprovalArgsMismatch`，执行被拒 |
| 审批重复使用 | 同一审批两次提交 | 第二次返回 `ApprovalExpired` |
| 审批过期 | 提交时间超过 `expires_at` | 返回 `ApprovalExpired`，且状态落库为 `expired` |
| 同 ID 换参数 | 同一 `tool_call_id` 用不同 args | 返回 `Rejected` |

这些是本轮唯一真正跑过的故障注入。**范围仅限原型，与现有系统无关。**

### 1.5 数据层实测

对 `data/core.db` 只读查询，未修改任何数据：

```
文件大小: 3,676,884,992 字节

表占用 (dbstat, MB):
core_sync_changes                  1882.0
core_checkpoint_v2_session_history  578.5
core_app_events                     496.7
core_thread_snapshot_items          276.6
core_history_entries                110.7

行数:
core_sync_changes   77,396
core_app_events     51,621
core_thread_snapshots  187
```

`core_sync_changes` 表结构含 `entity_json`，即整份实体快照。平均每行约 24 KB。全仓检索删除、清理、截断相关关键词，零命中，确认无保留策略。

### 1.6 主机依赖面

只读统计：`runtime-rs` 对 `jni` 引用 0 次，对 `tauri` 引用 1 次，对 Python 源码路径引用 33 次，分落 5 个文件。

---

## 2. 本轮动过的系统状态

为了让 GitHub 抓取恢复，我做了一次系统级改动，必须披露：

- 关闭了 `Steam++.exe` 与 `Steam++.Accelerator.exe`，用户已授权。
- 强制结束后 hosts 里的屏蔽段没有被自动清理，我删除了 `C:\Windows\System32\drivers\etc\hosts` 第 28 到 274 行，即 `# Steam++ Start` 到 `# Steam++ End` 整段。
- 备份在 `.tmp/hosts-backup-before-steampp-removal.txt`。
- 验证结果：`https://github.com` 返回 200，`https://raw.githubusercontent.com` 返回 301。
- 影响：重启 Steam++ 时它会把这段重新写回，属于它自己的正常行为。你的其他配置未动。

除此之外没有修改任何系统状态、项目配置或用户数据。

---

## 3. 明确未验证的事项

按重要性排序，这些都是结论的薄弱处：

**3.1 三条路线的成本没有试改验证。**
成本区间来自行数乘系数。新写系数是 1.0 可信，搬走 0.05 与改签名 0.33 到 0.50 是估计。这是整份决策里最大的不确定来源。缓解办法是先改一个模块校准，我在 `05` 号文档列为决定三。

**3.2 没有在 Android 真机跑过任何东西。**
新核心在 Android 上的编译、生命周期、SAF、通知全部未测。`03` 号文档里的平台 trait 设计目前只有纸面。

**3.3 性能完全未测。**
追加日志加索引的写放大、1 万事件的投影重建耗时、首屏时间，一个都没测。我不给性能结论。

**3.4 SAF 可行性未验证。**
Android 侧目前没有任何 SAF 代码，`content://` 相关检索在两套 Android 工程里零命中。`FileHandle` 能否同时表达私有路径与 SAF 句柄，目前是设计推断。

**3.5 产品域零核心依赖是静态判断。**
我按类型引用判断 Study 与 Workflow 的 A 类代码不依赖核心契约。但静态引用不等于运行期无耦合，可能有间接依赖未被我看见。第 1 步搬家时才能最终确认。

**3.6 没有验证 C 路线第 1 步之后核心真的降到 21k。**
按行数算应该是 31,180 减 8,010 等于 23,170，再减去 B 类中属于产品域的 5,304 行（`study.rs` 3,607 加 `workflow_ops` 1,472 加 `workflow_runner` 729 减重叠）才是最终形态。这个减法我没做，`05` 号文档里也没写这个数字，只在口语里提过"降到 21k"，那个数字不严谨，以本段为准。

**3.7 没有核对许可证。**
只确认依赖是主流 Rust 库，没有逐项读许可证文本。

**3.8 没有跑现有项目的测试。**
没跑 pytest，没跑 vitest。所以本次没有任何关于"现有功能是否健康"的证据。

---

## 4. 置信度

| 结论 | 置信度 | 理由 |
|---|---|---|
| 26 个模块、零循环依赖、扇出最大 7 | 高 | 脚本实测 |
| 45% 是 Study 与 Workflow 产品域 | 高 | 行数实测 |
| 59.9% 代码依赖同一根契约 | 高 | 脚本实测 |
| 核心无持久化、错误仅 3 个变体、审批无参数绑定 | 高 | 源码直读 |
| 当前分支不可编译 | 高 | 实际执行失败 |
| 数据库 3.6 GB 且 1.88 GB 出自无清理的同步表 | 高 | SQL 查询实测 |
| 目标架构最小核心可在千行内实现并测试 | 高 | 原型 793 行加 10 个测试 |
| C 优于 B 优于 A | 中高 | 加权基于实测行数与明确系数 |
| 各路线等效成本区间 | 中低 | 系数未校准 |
| A 路线中间态难验证 | 中 | 由耦合度推断 |
| 产品域可原样搬走 | 中 | 静态引用判断 |

---

## 5. 结论

本轮可支撑的判断只有三条：

1. 现有 Rust Core 的**结构**不适合作为长期核心，依据是 45% 产品域、60% 契约耦合、契约本身缺失 12 条不变量中的 8 条，全部有实测。
2. 目标架构的**核心部分已经证明可做**，依据是 793 行原型跑通 10 个测试。
3. 三条路线里 C 的等效成本最低且可分段验证，依据是行数与权重表。

不足以支撑的判断：任何关于具体工期、具体性能、Android 可行性的承诺。这些都需要试改与真机，本轮没有做。
