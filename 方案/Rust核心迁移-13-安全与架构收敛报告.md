# Rust 核心迁移 13：安全边界与架构收敛报告

日期：2026-11-03
分支：`sunday/m3-isolated-core`
**未合入主干，未切换生产 Core，未删除任何旧实现。**

---

## 结论先说

五项全部完成。三个安全阻断项已修复并有负向测试证明，原生实现从两份收敛为一份，心跳锁换成操作系统锁。Android 现在跑的是**真实 Sunday Vue 应用**，不是第二套前端。

**正式接管仍不批准。** 阻断项在本报告最后一节，其中两项是本轮新发现、且我认为比原计划的"产品完整性"更该先做。

---

## 一、安全边界

### 1.1 默认最小权限

你指出的 `auto_approve: true` 确实存在，性质比"配置不严"更严重：**它是一个全局开关，无法表达"读可以、写要问"**。

替换为 `GrantPolicy`（`sunday-host/src/policy.rs`）：

| 工具类别 | 默认行为 |
|---|---|
| `SideEffect::Pure`（只读） | 自动允许 |
| `SideEffect::Idempotent` / `NonIdempotent` | **询问** |
| `Permission::HardBlock` | 一律拒绝，即使被显式授权 |

规则：

- 没有任何构造方式能默认批准副作用。有一个测试专门守这条（`no_default_construction_approves_a_write`）。
- Android 默认 `granted_tools` 为空，新装应用写文件必须问。
- CLI 的 `--auto-approve` 标志**已删除**，改成 `--grant <tool-id>` 逐个授权。一个"批准一切"的标志无法通过文档变安全。

### 1.2 连接认证

WebSocket 现在必须认证，否则拒绝：

- 每个核心实例生成 32 字节随机令牌，写入数据目录，Unix 下 `0600`
- 首个 `initialize` 必须携带令牌，比对用常数时间
- **认证门放在 `dispatch` 里，不是放在 socket 层**——这样以后新增方法会自动继承，不可能漏掉
- 任何非 `initialize` 方法在认证前一律 `-32001`

未认证时的错误信息不区分"没有令牌"和"令牌错误"，避免给探测者额外信息。

### 1.3 Android 改用 Tauri IPC（不是保留 socket）

你要求"优先评估 IPC"。评估结论：**IPC 明显更好，已采用**。

理由：Android 上任何一个已安装应用都能连另一个应用的 loopback 端口。加令牌能挡住不知道令牌的进程，但令牌文件仍在同一个应用沙箱里；而 IPC 根本不监听端口，攻击面直接消失。

实测证据（`/proc/net/tcp` 与 `tcp6`）：

```
唯一 LISTEN 项：[::]:15B3   ← 0x15B3 = 5555，模拟器 adbd，不是本应用
没有任何 127.0.0.1 监听项
```

上一版的 `ws://127.0.0.1:<随机端口>` 已不存在。

令牌机制保留给 CLI 与桌面，那里跨进程访问是需求本身，socket 无法避免。

### 1.4 负向测试（6 项，全过）

`core/sunday-core/crates/sunday-host/tests/security_negative.rs`

| 测试 | 证明什么 |
|---|---|
| `without_a_token_the_transcript_cannot_be_read` | 知道端口也读不到会话内容 |
| `a_guessed_token_is_refused` | 猜错令牌被拒，且拒绝后连接仍不可用 |
| `no_mutating_method_is_reachable_before_authentication` | 18 个方法逐个试，全部 `-32001` |
| `the_right_token_is_accepted` | 对照项：正确令牌能工作，防止"全都拒绝"也能通过 |
| `the_token_file_is_not_world_readable` | Unix 下 `mode & 0o077 == 0` |
| `the_unauthenticated_constructor_is_clearly_test_only` | 记录 `bind` 与 `bind_authenticated` 的差别是显式的 |

**这些测试是真的**：我临时把认证门改成恒不生效，其中 3 项立刻失败。恢复后全过。

### 1.5 密钥不落明文 JSON

- `core.config.json` 里**没有** api_key 字段
- 密钥走 `sunday_platform::SecretStore` 端口，`HostSecrets` 实现，Unix 下 `0600`
- 有测试 `the_key_is_not_in_the_config_file`：写入密钥后断言配置文件不含它
- 有测试 `the_public_view_never_contains_a_key`：UI 拿到的配置视图里没有 key 字段

**尚未接 Android Keystore。** `secrets::backend()` 会如实返回 `RestrictedFile` 而不是假装 Keystore。要接需引入 Tauri keychain 插件并重新构建；当前诚实标注为文件存储（权限受限），不声称等价。

---

## 二、消除重复架构

### 2.1 收敛结果

| 之前 | 现在 |
|---|---|
| `sunday-cli/src/serve.rs` 自带一份完整 runner（约 460 行） | 只做装配，154 行 |
| Android `core_service.rs` 复制同一份（约 640 行） | 已删除，改用共享实现 |
| 事件转换、审批、队列、取消各写两遍 | `sunday-host/src/runner.rs` 一份 |

`CoreRunner` 是唯一的 `TurnRunner` 实现。宿主现在只负责：

- 生命周期与启动关闭
- 路径、密钥、平台权限
- 通信接口（CLI 用 socket，Android 用 IPC）
- 组装 store / model / tools / policy

### 2.2 证明双端共用

不是"看起来一样"，是编译期保证：

- 两个宿主都构造 `CoreRunner`，没有任何本地 runner 类型
- 命令行 `serve` 与 Android `run()` 都只调用 `CoreRunner::new`
- 协议分发是同一个 `dispatch`，通过 `FrameSink` 接到不同通道（socket 的 channel / Tauri 的 emit）

一条 `FrameSink` 抽象让"同一个 dispatch 服务两种传输"成立。没有它，第二套传输必然要复制方法表——那正是上一轮漂移的机制。

### 2.3 依赖规则同步收紧

`check-deps.py` 起初**拦住了**这次改动（`sunday-host` 新增了对 tools/platform 的依赖）。这是它该做的。确认理由正当后更新，并写明边界：

- `sunday-host` 可以看 store / agent / tools / platform（组合层要装配工具和路径）
- **仍然看不到 `sunday-llm`**：模型由宿主挑选后传入，runner 保持与供应商无关

---

## 三、单写者锁：换成操作系统锁

### 3.1 为什么必须换

你的判断准确：心跳超时不能证明原进程已死。Android 后台冻结可以持续数分钟，期间写者完全存活且随时可能恢复提交。心跳式回收会在那里制造**两个有效写者**。

### 3.2 现在的机制

`fs2` 的文件锁：

- Unix：`flock(LOCK_EX | LOCK_NB)`
- Windows：`LockFileEx` 独占

两者都由内核在进程死亡时释放，且**不会**因为进程被挂起而释放。这正好是需要的语义。

顺带解决了两件事：

- **回收窗口消失了。** 崩溃的持有者被回收的瞬间锁就没了，重启立即成功，不用等。
- **不能删锁文件。** 删文件会引入 unlink 竞态：A 解锁并删除，而 B 已创建新文件并加锁，A 就把 B 的锁删了。锁文件保留，没人持有时它只是个文件。

「持有者说明」改放 `core.lock.owner`，永不加锁，可随时读。**它只是诊断信息，权威永远是内核锁。**

### 3.3 测试（6 项，全过）

| 测试 | 结果 |
|---|---|
| 第二个写者被拒并报出持有者 | 通过 |
| 释放后立即可以再获取（无等待） | 通过 |
| 遗留描述文件不阻塞新写者 | 通过 |
| 描述文件损坏则重写而非信任 | 通过 |
| **强杀后无需等待即被回收** | 通过 |
| **暂停超过任何心跳阈值仍持有目录** | 通过 |

最后一项是这轮最关键的验证：子进程持锁后被挂起 3 秒，期间试图夺取**必须失败**。旧设计在这里会交出目录。

还有一项并发启动测试通过真实双进程写入验证序号连续、无丢失无重复（沿用上轮的 `append_worker` 夹具）。

### 3.4 需要说明的取舍

`still_owner()` 现在读的是进程内状态，不再读磁盘。原因：Windows 上持有独占锁时，读被锁的字节会失败——这也是把描述信息移出锁文件的原因。语义仍正确：OS 锁不可能被活着的进程抢走。

---

## 四、Android 产品集成

### 4.1 真实 Vue 应用（不是第二套前端）

上一版是简化 HTML。现在是同一个 `LamToolsApp`：

- 新增 `core/ui/src/transport/ipcTransport.ts`，实现既有的 `LamToolsTransport` 接口
- 新增 `src/core-app/main-android.ts` 入口，用 `IpcTransport` 组装同一个 runtime
- 桌面端代码路径未改动；只换了底下那根管子

**模拟器实际 UI 验收**：截图确认渲染出正式 Sunday 启动页（"Sunday 先选"），不是空白页也不是测试页。

过程中遇到并修复两个真实问题：

1. **黑屏**：`window.__TAURI__` 不存在（未开 `withGlobalTauri`）。改为从 `@tauri-apps/api` 模块导入。期间还发现并修掉我自己的一个 bug：`mount()` 会覆盖失败提示，导致症状退化成"黑屏无说明"。
2. **`plugin:event|listen not allowed by ACL`**：Tauri 2 的权限系统拦住了事件监听。补 `capabilities/core-ipc.json`，只授予 `core:default` + 事件监听，**不授予文件系统和 shell**。

第 2 条值得单独说：ACL 报错其实是一次安全机制正常工作。我没有为了让它跑通去放宽权限，而是只加必需的两项。

### 4.2 生命周期

`src/lifecycle.rs`：

- 进后台**不取消**运行中的回合。取消会静默截断用户走开前启动的工作。
- 记录当时有回合在跑的线程，写入 `lifecycle.json`
- 回前台报告中断，且**只报一次**
- 明确返回 `turn_continues_in_background: false`，防止 UI 文案漂移成"后台继续跑"
- `auto_resumed_turns: false`：非幂等工具结果未知，绝不自动重放（不变量 I4）

### 4.3 未完成

- **没有真机。** 全程模拟器。真机是发布前强制项。
- Android 生命周期回调只接到 IPC 命令，**没有接系统 `onPause`/`onResume`**。目前需要前端主动调用；`MainActivity` 的接线未做。
- **APK 构建未进 CI。** 仍为手工执行。
- 未接 Keystore（见 1.5）。

---

## 五、剩余能力

### 5.1 `command.catalog` / `command.execute`

已实现，语义是诚实的：

- 目录只列核心真能做的事：`clear`、`tools`，加上真实的工具名
- `expand_command` 展开为 prompt，未知命令返回明确错误
- **拒绝返回空字符串**：那会让 UI 以为成功启动了一个空回合
- `command.execute` 走与普通回合完全相同的路径（journal、审批、取消）

### 5.2 ignored 测试分类（修正）

上一轮我写的分类数字与清单不符，这次逐项核对。

**总数 32，分五类，相加等于 32：**

| 类别 | 数量 | 计不计入通过率 |
|---|---|---|
| A. 真实 Provider（需要模型端点） | 8 | 不计 |
| B. 压缩质量（需要真实摘要器） | 8 | 不计 |
| C. 存储测量（耗时或纯测量） | 9 | 不计 |
| D. 原子性/幂等（需真实 reopen/重放） | 2 | 不计 |
| E. 崩溃注入辅助进程（被主测试 spawn） | 5 | 不计 |

逐项对应：

**A. 真实 Provider（8）**
`streaming_delivers_text_incrementally_before_the_turn_completes`、
`tool_calls_are_parsed_from_a_real_model_answer`、
`a_multi_step_tool_conversation_round_trips`、
`a_turn_reports_wall_clock_and_usage`、
`a_bad_model_name_fails_fast_instead_of_retrying_forever`、
`an_unreachable_endpoint_fails_without_hanging_forever`、
`a_cancelled_turn_stops_consuming_the_stream`、
`a_pre_cancelled_request_never_reaches_the_provider`

**B. 压缩质量（8）**
`the_summary_keeps_the_cause_not_only_the_number`、
`the_agent_can_still_answer_a_cause_question_after_compaction`、
`the_summary_does_not_invent_a_cause`、
`compaction_shrinks_a_long_transcript_materially`、
`the_summary_keeps_the_facts_a_later_step_needs`、
`compaction_leaves_the_task_statement_intact`、
`a_summary_that_runs_away_is_capped`、
`a_short_conversation_is_not_compacted`

**C. 存储测量（9）**
`batching_versus_single_commit`、`growth_per_event_decomposed`、
`payload_size_versus_growth`、`projection_rewrite_cost`、
`commit_latency_distribution`、`bytes_per_event_is_reported`、
`ten_thousand_events_append_and_replay`、
`two_hundred_threads_do_not_slow_each_other`、
`a_hundred_large_events_stay_usable`

**D. 原子性/幂等（2）**
`a_batch_is_atomic_across_a_reopen`、`a_replayed_batch_is_idempotent`

**E. 崩溃注入辅助进程（5）**
`abort_mid_transaction`、`crash_after_dispatch`、`append_worker`、
`batch_abort_worker`、`lock::tests::lock_child_helper`

每类的风险：A/B 类若回归，CI 不会发现（需要真实环境）；C 类只报数字不当门禁；D/E 的主测试都在默认集内通过。

### 5.3 未做的

- 真实 Agent 任务质量测试：仍只有压缩后续执行一项
- 长时间运行/数据库增长/恢复测试：未建立

---

## 六、验证与闸门

```
cargo fmt --all -- --check                            干净
python scripts/check-deps.py                          ok 10 crates
cargo test --workspace                               见下
```

测试总数（默认集 + ignored）：

- 默认集：全部通过，无失败
- ignored：32（分类见 5.2）

安全负向测试 6 项、锁测试 6 项、策略测试 6 项均在默认集内。

**数据安全**：`data/core.db` 全程未读写，大小与 mtime 未变。

---

## 七、正式接管阻断项

按我认为的处理顺序：

1. **`sunday-llm` 的 HTTP 客户端没有校验 TLS 根证书来源之外的任何东西，也没有对 `base_url` 做协议与主机检查。** 一个被篡改的配置文件可以把 api_key 发到任意主机。这是本轮新发现，严重度高于产品完整性。
2. **Android 生命周期没有接系统回调。** 目前依赖前端主动调用，`onPause`/`onDestroy` 未接。系统回收时状态是持久的，但"进后台"这一事件可能漏掉。
3. **Keystore 未接**，密钥在权限受限的文件里。
4. **没有真机验证。** 发布前强制项。
5. **APK 构建未进 CI。**
6. **任务质量只测了压缩一项。**
7. **没有接外部云厂商**，只有本机 Ollama。
8. **事件表仍无归档策略。**
9. **Rust store 没有后台 WAL 检查点。** 项目记忆里记着 Python 生产核踩过这个坑（`wal_autocheckpoint` 默认 1000 页导致提交线程同步回写、发送延迟尖峰），修法是后台 PASSIVE 检查点。Rust 侧目前同样没有，会重现同类尖峰。
10. **未做双写校验与回滚演练。**

第 9 条是读项目记忆时发现的跨核共性问题，不是本轮引入，但接管前必须解决。

**不建议现在接管。** 第 1、2、9 条会直接影响真实用户或泄露密钥。

---

## 八、本轮文件清单

新增：

- `core/sunday-core/crates/sunday-host/src/policy.rs`
- `core/sunday-core/crates/sunday-host/src/token.rs`
- `core/sunday-core/crates/sunday-host/src/runner.rs`
- `core/sunday-core/crates/sunday-host/tests/security_negative.rs`
- `core/android-host/src-tauri/src/config.rs`
- `core/android-host/src-tauri/src/secrets.rs`
- `core/android-host/src-tauri/src/lifecycle.rs`
- `core/android-host/src-tauri/capabilities/core-ipc.json`
- `core/ui/src/transport/ipcTransport.ts`
- `core/ui/src/core-app/main-android.ts`
- `core/ui/index-android.html`
- `core/ui/vite.config.android-app.ts`

重写：

- `core/sunday-core/crates/sunday-host/src/lock.rs`（心跳锁 → 操作系统锁）
- `core/sunday-core/crates/sunday-cli/src/serve.rs`（runner → 纯装配）
- `core/android-host/src-tauri/src/lib.rs`（socket → IPC）
- `core/android-host/ui/index.html`（删除，改用真实 Vue 构建产物）

修改：

- `core/sunday-core/crates/sunday-host/src/app_server.rs`（认证门、`FrameSink`、`Session`、`command.*`）
- `core/sunday-core/crates/sunday-host/Cargo.toml`、`core/sunday-core/scripts/check-deps.py`
- `core/sunday-core/crates/sunday-cli/src/main.rs`（删除 `--auto-approve`）
- `core/sunday-core/crates/sunday-agent/src/lib.rs`（`Approval` 加 `Debug`/`PartialEq`）
- `core/android-host/src-tauri/tauri.conf.json`、`core/ui/package.json`

未触碰：`data/core.db`、`core/src/`（旧 Python 实现）、生产 Core 切换。
