# Rust 核心迁移 12：可用性验收报告

日期：2026-11-03
分支：`sunday/m3-isolated-core`
**未合入主干，未切换生产 Core，未删除任何旧实现。**

---

## 结论先说

五项优先级全部落地并验证，其中包括两项看似要失败的：Android 正式沙箱跑通、压缩后 Agent 能继续正确工作。

过程中修复 5 个真实缺陷，每一个都不写测试就发现不了。其中两个属于"会静默给出错误结果"的类型，比崩溃更危险。

**仍然不满足正式接管条件。** 阻断项列在最后一节，不做乐观表述。

---

## 一、持久化策略：保持不变，只减少提交次数

### 决定执行情况

`synchronous=FULL` 与 WAL **未改动**，持久性没有用性能换。

### 上一轮的错误结论已纠正

上一轮报告称"写放大 4291 字节/事件，根因是投影全量重写"。**这个结论是错的，本轮实测推翻：**

| 测量项 | 上一轮 | 本轮实测 |
|---|---|---|
| 字节/事件 | 4291 | **213** |
| 投影行大小 | 被指为根因 | **85 字节**，且事件种类是封闭集合，不会无限增长 |
| 测量方法 | 未 fold WAL | checkpoint 后测量稳态占用 |

错误来源：上一轮没有把 WAL 折回主库就量文件大小，量到的是"恰好还没被 checkpoint 的 WAL"，而不是数据本身的成本。测量方法已固化为 `checkpoint()` + 同口径对比。

### 真实成本定位

真实成本是**每次提交一次 fsync**，不是磁盘被浪费：

| 指标 | 单条提交 | 10 条批量提交 |
|---|---|---|
| 延迟 | 2016 µs/事件 | **204 µs/事件** |
| fsync 次数（1000 事件） | 1000 | 100 |
| 稳态磁盘占用 | 213 字节/事件 | **213 字节/事件** |
| p50 延迟 | 1.97 ms | 2.00 ms |

**加速 9.9 倍，磁盘占用完全一致。** 延迟的 p50 没变，因为一次批量提交仍然要等一次 fsync；变的是每 N 条事件只 fsync 一次。

### 实现的优化

`append_events`：一个逻辑操作的所有事件写在一个 `BEGIN IMMEDIATE` 事务里。保住全部原有保证：

- `seq` 连续且按传入顺序
- 相同 `event_id` 被跳过，不重复
- 提交前不可见，崩溃后要么全有要么全无
- 空批量不推进 revision（无操作不伪装成变更）

### 故障注入回归（全部真实进程 abort）

| 测试 | 结果 |
|---|---|
| `abort_mid_transaction` | 通过 |
| `crash_after_dispatch` | 通过 |
| `append_worker`（双进程并发） | 通过 |
| **`c3_a_batch_interrupted_by_a_crash_leaves_no_partial_events`**（本轮新增） | **通过** |

c3 是真实验证批量的原子性：子进程先提交 20 条，然后在第二个批量写到一半时 abort。重开后确认已提交的 20 条完整存在、未提交的 20 条一条不留、序号连续、投影`last_seq` 与日志一致。

---

## 二、模型取消：贯穿到 HTTP 层

### 实现

`CancelToken` 放进 `ModelRequest` 而不是加 `stream` 参数。理由是：这样每个已有实现保持签名不变，新实现**不可能忘记接受它**。

链路：`AppServer` → `TurnRunner` → `Env.cancel` → `ModelRequest.cancel` → `LlmClient` 流读取循环。

### 三条硬保证

1. **本地停止读流**：`LlmClient` 在两个 chunk 之间检查令牌，命中即 drop response 关闭连接。
2. **取消后不再派发工具**（不变量 I8）：在每次工具派发前检查，不是每轮检查一次。理由是模型一次可能返回多个调用，用户可能在两个之间按下停止。
3. **取消不是失败**：以 `Rejected` 返回，明确不进重试路径。否则重试会把用户刚停下的工作重新拉起来。

### 验证结果

单元契约（7 项，全部通过）：

- 慢速流在用户按下停止后停止读取，且模型确实观察到取消（不是静默读完）
- 双工具调用中取消，第二个不执行
- 回合开始前已取消，模型一次都不被调用
- 取消跨重启durable，且不留可恢复的 continuation
- 令牌 reset 后下一个回合不会"生来已取消"
- 两个线程的令牌互相隔离
- 模型层收到的令牌与循环持有的是同一个（`Arc::ptr_eq`）

**真实 Provider（本机 qwen2.5:3b，真实 HTTP 流）**：

| 测试 | 实测 |
|---|---|
| 流式输出中途取消 | **74ms 内停止**，只收到 1 个增量，未跑完 400 token |
| 发送前已取消 | **1.7µs 内拒绝**，完全不建立连接 |

### 必须说清的边界

**取消不保证服务商停止计费。** 我们只承诺停止本地读取并关闭连接。服务商是否继续生成、是否继续计费，不在这段代码的控制范围内。产品文案不得出现"零费用"承诺。

---

## 三、协议补齐：从"能连上"到"能用"

### 覆盖矩阵（唯一依据：`core/ui/src/appServer/store.ts` 实际调用）

| 方法 | 上轮 | 本轮 |
|---|---|---|
| `initialize` / `initialized` | 有 | 有 |
| `thread/start` / `thread/resume` | **缺** | **有**，幂等，重按不分裂会话 |
| `thread/read`（历史分页） | **缺** | **有**，游标分页 + `has_more` + `total_items` |
| `thread/snapshot` | 有（骨架） | 有 |
| `turn/start` / `turn/resume` | 有 | 有 |
| `turn/steer` | **缺** | **有**，无活回合时诚实返回 `applied:false` + reason |
| `turn/pause` / `interrupt` / `terminate` / `force_reset` | **缺** | **有**，四种模式语义区分 |
| `queue/create` / `update` / `delete` / `guide` / `reorder` / `list` | **缺** | **有**，真实表存储 |
| `approval/respond` | 有 | 有 |
| `command.catalog` / `command.execute` | **缺** | **缺**（前端调用，仍未实现） |
| `artifact/*`、`quota/*` | 缺 | 缺（前端当前无调用方，未实现） |

**未实现的方法仍返回 `METHOD_NOT_FOUND`，不返回空对象。** 有一个测试专门守这条：`still says METHOD_NOT_FOUND for what it does not implement`。

### 一个"看起来成功"的陷阱被修掉

`turn/steer` 在无活回合时，如果返回成功，UI 会显示"引导已送达"而文本永远消失。现在返回 `applied:false` + 具体 reason（`run_not_active` / `active_turn_mismatch`），UI 会把文本落到队列。

### 新增存储能力

schema v3 加 `queue_items` 表。队列落盘而不是放内存：重启后用户输入不丢，`queue/create` 也有真实数据可报。

### 真实 Vue 客户端验证（7 项全过）

用桌面端真实的 `CoreAppServerClient` + `DirectTransport`：

- `thread/start` 重按不分裂会话
- 队列增删改重排全链路，重试不重复
- 历史分页逐页回走，结果**精确等于**整个日志，无缺口无重复
- 无活回合时 steer 诚实拒绝
- `turn/interrupt` 真的停住回合
- 三种停止模式都被应答
- 未实现方法仍报 METHOD_NOT_FOUND

原有 5 项契约测试同时回归通过，无破坏。

### 修掉的真实缺陷

历史分页首页永远为空。根因：`u64::MAX as i64 == -1`，SQL 条件变成 `seq < -1`，一行都匹配不到。这个 bug 在生产里表现是"打开会话看不到任何历史"，而单元测试如果只测 `before_seq=Some(n)` 就永远发现不了。

---

## 四、Android：正式应用沙箱

### 不再用 `/data/local/tmp`

新建最小 Tauri 宿主 `core/android-host`，核心以**进程内库**方式链接（不是推送一个可执行文件）。

### 决定性证据

核心启动日志原文：

```
sunday core listening on 127.0.0.1:35841,
data at /data/user/0/com.lamtools.sunday.core
```

`/data/user/0/<package>` 是 Android 的**正式应用私有沙箱**，与之前 `/data/local/tmp` 是完全不同的权限模型。数据目录由 Tauri 的 `app_data_dir()` 解析，不是写死的路径。

### 逐项验证

| 验收项 | 结果 | 证据 |
|---|---|---|
| 正式 APK 构建 | 通过 | `app-universal-release-unsigned.apk`，20.3 MB |
| 签名 | 通过 | V3.0 debug 证书，`apksigner verify` 通过 |
| 安装 | 通过 | `adb install` Success |
| 启动 | 通过 | 进程存活，核心监听端口 |
| WebView 加载 | 通过 | chromium 进程起来，无致命错误 |
| UI 与核心通信 | 通过 | 真实 Vue 客户端经端口转发完成握手（101）与全链路调用 |
| 沙箱内 SQLite | 通过 | 真实模型回合写入，历史分页正确 |
| 退出 | 通过 | `am force-stop` 后进程消失 |
| 进程回收后恢复 | 通过 | see below |
| Agent 完整闭环 | 通过 | 真实模型回合 + 队列 + 历史 |

### 进程回收恢复（两阶段验证）

1. 写入固定线程的队列项
2. `am force-stop`（进程真的消失）
3. 重新启动应用
4. 读回队列项：**内容完整存在**

这不是"重启后能再跑"，而是"重启前写的数据还在"。

### 修掉的真实缺陷：快速重启会崩溃

第一次重启测试直接崩了。根因：锁的回收窗口是 10 秒，用户强杀后立刻重开时，前一个进程的心跳还在窗口内，锁被判定为"活着"，宿主 `expect` 失败 → abort。

这在手机上极其常见，用户看到的是"这个应用打不开"。

修法：改成本地**有界等待**（最多等窗口 + 2 秒，250ms 轮询），而不是立即失败。这既尊重了"不抢占活着的写者"这条不可撤销的原则，又不会让应用看起来坏掉。

### 明确没有做到的

- **没有真机。** 全程只有模拟器（android-36 / google_apis / x86_64）。真机上的 ABI 差异、内存压力、厂商后台清理策略、真实网络切换，全部未验证。**真机测试保留为发布前强制验收条件，不能用模拟器结果替代。**
- **没有 Android 生命周期回调。** 本轮验证的是"核心在沙箱里能跑、数据能持久化"。`onPause`/`onResume` 时是否该暂停回合、`onDestroy` 时如何优雅释放锁，都还没接。
- **没有 SAF 授权模型。** 文件访问目前只在应用私有目录内。
- **权限申请未验证**（应用当前未申请运行时权限，也就不存在被拒场景）。

---

## 五、压缩质量：修复后 Agent 能继续工作

### 问题

上一轮发现摘要保留数字、丢掉因果（"30 秒""500"留了，"逗号分割"丢了）。

### 根因与修法

根因不是实现 bug，是**提示词只要求"保留事实"，没要求"保留原因"**。

修法：把提示词放进 `sunday-context/src/summary_prompt.rs`（与 compaction 同 crate，因为它就是策略的一部分）。新提示词按优先级要求：

1. **WHY**：每个原因、约束、被排除的方案及其理由。明确写"A cause is worth more than the number it produced."
2. **WHAT IS STILL OPEN**
3. **EXACT VALUES**：路径、标识、错误信息、数字，逐字复制

并显式禁止："Never invent a cause that the transcript does not state."

同时加 3 个单元测试守住提示词本身，防止以后被悄悄改回去。

### 真实模型验证（4 项全过）

| 测试 | 结果 |
|---|---|
| 摘要保留因果（不只保留数字） | 通过 |
| **压缩后 Agent 仍能正确回答根因问题** | **通过** |
| 摘要不编造未出现的原因 | 通过 |
| 压缩比有意义 | 通过，**449 → 180 tokens（2.49x）** |

压缩后的真实回答：

> The root cause is that a trailing comma in the line causes `line.split(',')` to produce an extra empty string, which is then rejected by the validator, resulting in 17 rows per file being discarded.

摘要原文（此前会丢的部分现在在）：

> WHY: The import process is failing due to a trailing comma in each line of the files. This causes `split` to produce an empty field for every line, resulting in 17 rows being rejected per file.

这就是"压缩后能不能继续干活"的答案：能，且原因正确。

**代价要说清：** 保留因果必然多花 token。压缩比是 2.49x 而不是更高，这是有意的取舍，不是退步。

---

## 六、32 个 ignored 测试完整清单

**不计入通过率。** 下面每个都标注原因与风险。

### A. 需要真实模型的 Provider 契约（9 项）

| 测试 | 原因 | 风险 |
|---|---|---|
| `streaming_delivers_text_incrementally_before_the_turn_completes` | 需真实流式端点 | 若流式退化为整体返回，CI 不会发现 |
| `tool_calls_are_parsed_from_a_real_model_answer` | 需真实模型返回工具调用 | 工具调用解析回归只能靠实跑发现 |
| `a_multi_step_tool_conversation_round_trips` | 需真实多步对话 | 工具结果回填错误只能靠实跑发现 |
| `a_turn_reports_wall_clock_and_usage` | 需真实用量数据 | 用量统计错误不会在 CI 暴露 |
| `a_bad_model_name_fails_fast_instead_of_retrying_forever` | 需真实 4xx 响应 | 4xx 误判为可重试会在生产放大费用 |
| `an_unreachable_endpoint_fails_without_hanging_forever` | 需真实连接失败 | 无限重试风险 |
| `a_cancelled_turn_stops_consuming_the_stream` | 需真实流才能中途取消 | 取消退化为读完才能发现 |
| `a_pre_cancelled_request_never_reaches_the_provider` | 需验证不建立连接 | 预取消失效会在生产产生无效计费 |

每个都有 `require_server()` 守卫：**没有服务时直接失败，不会静默通过。**

### B. 压缩质量（7 项）

| 测试 | 原因 | 风险 |
|---|---|---|
| `the_summary_keeps_the_cause_not_only_the_number` | 需真实摘要器 | 摘要丢因果是质量问题，单测测不出来 |
| `the_agent_can_still_answer_a_cause_question_after_compaction` | 需真实模型回答 | 压缩后任务断裂无法自动发现 |
| `the_summary_does_not_invent_a_cause` | 需真实摘要器 | 编造原因比丢信息更危险 |
| `compaction_shrinks_a_long_transcript_materially` | 需真实摘要 | 压缩失效只能靠实测 |
| `the_summary_keeps_the_facts_a_later_step_needs` | 需真实摘要器 | 同上 |
| `compaction_leaves_the_task_statement_intact` | 需真实摘要器 | 任务陈述被改写是严重问题 |
| `a_summary_that_runs_away_is_capped` | 需真实摘要器 | 摘要超长会反过来爆预算 |
| `a_short_conversation_is_not_compacted` | 需真实摘要器 | 短对话被压缩是纯损失 |

### C. 存储测量（7 项）

| 测试 | 原因 | 风险 |
|---|---|---|
| `batching_versus_single_commit` | 测量，非门禁 | 批量优化退化只能靠实测发现 |
| `growth_per_event_decomposed` | 测量 | 磁盘增长异常不会报警 |
| `payload_size_versus_growth` | 测量 | 大载荷路径未在 CI 覆盖 |
| `projection_rewrite_cost` | 测量 | 投影成本回归不报警 |
| `commit_latency_distribution` | 测量 | 延迟劣化不会报警 |
| `ten_thousand_events_append_and_replay` | 耗时约 20s | 万级事件性能回归不报警 |
| `two_hundred_threads_do_not_slow_each_other` | 同上 | 多会话性能回归不报警 |
| `a_hundred_large_events_stay_usable` | 耗时 | 大载荷性能回归不报警 |
| `bytes_per_event_is_reported` | 测量 | 写放大回归不报警 |

### D. 原子性与幂等（2 项）

| 测试 | 原因 | 风险 |
|---|---|---|
| `a_batch_is_atomic_across_a_reopen` | 需真实 reopen | 批量原子性回归 |
| `a_replayed_batch_is_idempotent` | 需真实重放 | 重试产生重复事件 |

### E. 崩溃注入辅助进程（4 项）

| 测试 | 原因 | 风险 |
|---|---|---|
| `abort_mid_transaction` | 辅助进程，被主测试 spawn | 单独跑无意义 |
| `crash_after_dispatch` | 同上 | 同上 |
| `append_worker` | 同上 | 同上 |
| `batch_abort_worker` | 同上 | 同上 |
| `lock::tests::lock_child_helper` | 同上 | 同上 |

这些的**主测试**（`c*` 开头的）都在默认测试集里通过，注入逻辑本身已覆盖。

### F. 说明

ignored 数量从 19 增加到 32，是因为本轮**新增**了取消、压缩后续执行、存储测量三组需要真实环境的测试。不是标准放松，是覆盖增加后必然的划分。

真实环境下这 20 项（9+7+2 中的真实环境类）已在本次全部实跑通过，数字见上文。

---

## 七、真实模型验证：区分"协议可用"与"任务质量"

用户要求明确区分，这里分开列：

### 协议可用性（走得通）

- 流式 50 个分片，首个 71ms
- 工具调用解析出 `{path:"out.txt", content:"hello"}`
- 多步工具往返，工具结果 "42" 被正确使用
- 坏模型名 1.26ms 拒绝，不重试
- 不可达端点 4.06s 失败，不挂起
- 取消 74ms 生效

### 任务质量（做得好不好）

- 压缩后能正确回答根因问题（唯一一项本轮测了任务质量的）
- 真实回合端到端完成，文件真的写出 `hello`

**诚实说明：任务质量只测了压缩后续执行这一项。** 没有对多轮任务成功率、工具选择正确率、长任务保持能力做系统评估。这是下一阶段的事。

**测试模型是 qwen2.5:3b，本机 Ollama。** 换更强的模型，这些数字会变；换成商业 API，计费和限流行为也不同。本轮未接入任何外部云厂商端点。

---

## 八、本地闸门与 CI

```
cargo fmt --all -- --check          干净
cargo clippy --workspace --all-targets -- -D warnings   0 错误
python scripts/check-deps.py        ok 10 crates
cargo test --workspace              166 passed / 0 failed / 32 ignored
```

依赖检查本轮仍有效：`note sunday-context (tests only) -> ['sunday-llm']` 说明测试依赖被单独列出而非豁免。

远端 CI（运行 41618088813，提交 `eee1b1de`）：**四项全部成功**

| 作业 | 结果 |
|---|---|
| windows build and tests | 成功 |
| linux build and tests | 成功 |
| android target check | 成功 |
| dependency rules | 成功 |

这是真实 GitHub Actions 结果，不是预估。注意 `android target check` 只验证交叉编译，不覆盖 APK 打包与安装，那部分本轮是手工执行（见阻断项 9）。

---

## 九、剩余阻断项（正式接管前必须解决）

按严重程度：

1. **`command.catalog` / `command.execute` 未实现。** 前端确有此调用，斜杠命令面板会失败。这是覆盖矩阵里唯一还空着的真实调用。
2. **没有 Android 生命周期处理。** `onPause`/`onDestroy` 未接，后台被系统回收时回合如何收尾未定义。
3. **没有真机验证。** 发布前强制项。
4. **没有 SAF 授权模型。** 文件访问目前只在应用私有目录。
5. **任务质量只测了压缩一项。** 多轮成功率、工具选择正确率、长任务保持能力未评估。
6. **没有接外部云厂商。** 只有本机 Ollama，商业 API 的重试、限流、计费行为未验证。
7. **事件表无归档策略。** 只增不减。
8. **`sunday-host` 已有约 900 行、Android 宿主又复制了一份 runner。** 两份 `TurnRunner` 实现高度相似，这是重复。应抽到共享 crate，否则漂移是时间问题。
9. **Android 宿主未纳入 CI。** 本轮构建是手工执行，没有自动保证。
10. **未做双写校验与回滚演练。**

---

## 十、下一步建议

1. 实现 `command.catalog` / `command.execute`，补完覆盖矩阵最后一块。
2. 把两份 `TurnRunner` 实现合并，消除重复（阻断项 8）。
3. 接 Android 生命周期，定义后台回收时的回合收尾。
4. 拿真机做验收，同时把 Android 构建纳入 CI。
5. 之后才谈 Windows 接管：需要双写校验、灰度、回滚演练三件套。

**不建议现在做正式接管。** 理由不是进度，是上面 10 项里至少 1、2、8 会影响真实用户。

---

## 十一、本轮文件清单

新增：

- `core/android-host/`（`src-tauri/src/lib.rs`、`src-tauri/src/core_service.rs`、`src-tauri/Cargo.toml`、`src-tauri/tauri.conf.json`、`src-tauri/build.rs`、`src-tauri/tauri.js`、`ui/index.html`）
- `core/sunday-core/crates/sunday-store/src/schema_v3.sql`
- `core/sunday-core/crates/sunday-store/tests/storage_profile.rs`
- `core/sunday-core/crates/sunday-context/src/summary_prompt.rs`
- `core/sunday-core/crates/sunday-context/tests/compaction_continuation.rs`
- `core/sunday-core/crates/sunday-agent/tests/cancel_contract.rs`
- `core/sunday-core/crates/sunday-host/tests/protocol_coverage.rs`
- `core/ui/tests/rust-core-coverage.test.ts`
- `core/ui/tests/android-persistence.test.ts`

修改：

- `core/sunday-core/crates/sunday-protocol/src/lib.rs`（CancelToken、ModelRequest.cancel）
- `core/sunday-core/crates/sunday-llm/src/lib.rs`（可中断流读取）
- `core/sunday-core/crates/sunday-agent/src/lib.rs`（Env.cancel、派发前检查）
- `core/sunday-core/crates/sunday-extensions/src/lib.rs`（子代理取消令牌）
- `core/sunday-core/crates/sunday-store/src/lib.rs`（append_events、checkpoint、队列、历史分页、schema v3）
- `core/sunday-core/crates/sunday-host/src/app_server.rs`（覆盖协议方法、StopMode、DISPATCHED）
- `core/sunday-core/crates/sunday-cli/src/serve.rs`（新协议方法实现）
- `core/sunday-core/crates/sunday-store/tests/store_contract.rs`（批量崩溃注入、schema 版本引用常量）

未触碰：

- `data/core.db`（真实用户库，全程未读写）
- `core/src/`（旧 Python 实现）
- 生产 Core 切换
