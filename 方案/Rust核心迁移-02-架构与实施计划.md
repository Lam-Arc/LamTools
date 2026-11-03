# Sunday 跨平台 Rust Core 架构与实施计划

配套文档：`方案/Rust核心迁移-01-源码审计报告.md`。本文所有结论都以那份报告的代码证据为前提。
状态：待你确认后实施。确认前不改动任何正式代码。

> **本文部分内容已被取代，2026-11-02 更新。**
> 第 1 节的"纠偏一：改造已有的 `core/runtime-rs`"与第 9 节的决策一不再成立。用户指出沉没成本不参与技术决策，改造与重建之间的选择已重新开放。
> 现行结论见 `方案/Rust核心迁移-05-三路线对照与最终推荐.md`，目标架构见 `03`，现有代码质量见 `04`，验证证据见 `06`。
> 本文第 3 到 8 节的存储设计、协议对齐、伪代码、阶段划分与验收门槛仍然有效，可作为实施参考。

---

## 1. 三条纠偏，决定后面全部工作

**纠偏一：不新建 Rust Workspace，改造已有的 `core/runtime-rs`。**
现有 33,638 行 Rust 已实现多轮循环、流式调用、工具、审批中断与续跑、guidance、hooks、compaction、sub_agent、mcp、skills、provider。Android 宿主 `core/mobile/src-tauri` 也已跑通本机 Agent。推倒重建等于把已验证的 4 万行作废。

**纠偏二：先修 CI 红线，再谈迁移。**
`runtime-rs/src/plugin_catalog.rs:31` 的 `include_str!` 指向已删除的 `git` 插件，当前分支 `cargo check` 直接失败。这一步必须先做，否则后面所有"测试通过"都无意义。

**纠偏三：数据风险优先于功能。**
单库 3.6 GB，`core_sync_changes` 独占 1.88 GB 且无任何保留策略。这个不处理，任何迁移、备份、手机同步都是空话。

---

## 2. 目标架构

### 2.1 分层

```
 共享前端 core/ui
 Vue 3 业务组件 · 状态投影 · 主题 token
        │
        │ CoreTransport 接口（已有）
        │
 ┌──────┴──────────────┬─────────────────────┐
 │ LocalTransport      │ RemoteTransport     │
 │ Tauri invoke / WS   │ 金钥认证 + 端到端加密 │
 └──────┬──────────────┴──────────┬──────────┘
        │                          │
 ┌──────▼──────────────────────────▼────────┐
 │ sunday-host  （无 tauri 依赖的装配层）      │
 │ 命令路由 · 事件分发 · 能力注册 · 单写者锁    │
 └──────┬───────────────────────────────────┘
        │
 ┌──────▼───────────────────────────────────┐
 │ sunday-agent   循环 · 队列 · 取消 · 未知态   │
 │ sunday-llm     provider · 流式 · 重试       │
 │ sunday-tools   注册 · 审批 · 幂等 · 文件     │
 │ sunday-store   日志 · 收据 · 快照 · 投影     │
 │ sunday-protocol 类型 · 错误码 · 版本协商     │
 │ sunday-platform trait 层（文件/通知/分享/密钥）│
 └──────┬───────────────────────────────────┘
        │
 ┌──────┴──────────────┬───────────────────┐
 │ Windows Tauri 壳     │ Android Tauri 壳   │
 │ 桌面窗口 · 托盘      │ Kotlin 插件 · 前台服务│
 │ 当前 Python 可回退    │ SAF · 通知 · 分享   │
 └─────────────────────┴───────────────────┘

 sunday-cli 与两个壳共用同一 Core
```

### 2.2 crate 划分与迁移次序

不一次性拆包。`core/runtime-rs` 保持为一个可编译的库，新能力以新 crate 形式加在旁边，然后按模块搬出，旧位置留 `pub use` 转发，保证 Android 宿主不中断。

| crate | 来源 | 首批做什么 |
|---|---|---|
| `sunday-protocol` | 新建 | 类型、错误码、版本协商、TS 类型生成 |
| `sunday-store` | 新建 | 事件日志、命令收据、工具阶段表、快照 |
| `sunday-platform` | 新建 | `FileAccess` `SecretStore` `Notification` `Share` `CommandRunner` trait |
| `sunday-agent` | 从 `runtime-rs/src/lib.rs` 搬 | 循环、队列、取消、未知态 |
| `sunday-llm` | 从 `runtime-rs/src/provider.rs` 搬 | provider、流式、重试 |
| `sunday-tools` | 从 `runtime-rs/src/{project_tools,fetch_tools,web_search,skills,mcp}.rs` 搬 | 注册、审批、文件、网络 |
| `sunday-host` | 新建 | 装配、命令路由、单写者锁 |
| `sunday-cli` | 新建 | 二进制入口，与 GUI 领域对齐 |
| `lamtools-runtime` | 保留 | 空壳门面，`pub use` 全部新 crate，宿主无需改依赖 |

`runtime-rs` 对 Python 源码树的 8 处 `include_str!` 全部改为 `sunday-protocol` 内的静态清单或 `build.rs` 生成的清单，且允许清单缺失时编译通过只报运行期警告。Rust 从此不再依赖 Python 目录即可编译。

### 2.3 双栈并存期的硬约束

**约束：一个数据库同时只能有一个写入者。**
不是靠约定，靠机制。`sunday-host` 启动时对数据目录取独占文件锁，锁文件写进程标识与后端标识。Python 侧启动时同样取锁，拿不到就明确报错退出，而不是重试或降级。

这一点现在完全没有，`filelock` 全仓零命中，必须新建。

**约束：Rust 只新增表，不改老表结构。**
Rust 写 `journal_events`、`command_receipts`、`tool_call_stages`、`approvals_v2`、`journal_snapshots` 五张新表所在的新库文件，老的 `core.db` 首批只读。这样回滚到 Python 时，老库完全没被 Rust 动过。

这条是回滚方案能成立的根本，写死在设计里。

---

## 3. 存储与协议设计

### 3.1 为什么不能用现有手机端的持久化

手机端当前是整份 JSON 覆写，`local_state` 表结构是 `CREATE TABLE local_state (id INTEGER PRIMARY KEY, state_json TEXT NOT NULL)`。会话变长后每次写入都是 O(n)，且没有 seq 单调序列，无法做断线补拉和去重。

设计要求的事件完整、幂等、恢复，全都依赖 append-only 日志，必须新建。

### 3.2 新库结构

```sql
-- 事件日志：每个 thread 内 seq 单调
CREATE TABLE journal_events (
  workspace_id TEXT NOT NULL,
  thread_id    TEXT NOT NULL,
  seq          INTEGER NOT NULL,
  event_id     TEXT NOT NULL UNIQUE,
  run_id       TEXT,
  turn_id      TEXT,
  kind         TEXT NOT NULL,
  payload      TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  PRIMARY KEY (workspace_id, thread_id, seq)
);

-- 命令收据：request_id 幂等，与事件同事务
CREATE TABLE command_receipts (
  request_id   TEXT PRIMARY KEY,
  command_kind TEXT NOT NULL,
  status       TEXT NOT NULL,   -- rejected|accepted|running|completed|failed|outcome_unknown
  workspace_id TEXT NOT NULL,
  thread_id    TEXT,
  seq          INTEGER,
  revision     INTEGER,
  detail       TEXT,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

-- 工具调用阶段：Prepared 之后才能有副作用
CREATE TABLE tool_call_stages (
  tool_call_id TEXT PRIMARY KEY,
  run_id       TEXT NOT NULL,
  thread_id    TEXT NOT NULL,
  tool_id      TEXT NOT NULL,
  args_digest  TEXT NOT NULL,
  side_effect  TEXT NOT NULL,   -- pure|idempotent|non_idempotent
  stage        TEXT NOT NULL,   -- prepared|approved|dispatched|succeeded|failed|unknown
  result_json  TEXT,
  updated_at   TEXT NOT NULL
);

-- 审批：绑定具体参数摘要，过期即作废
CREATE TABLE approvals_v2 (
  approval_id  TEXT PRIMARY KEY,
  thread_id    TEXT NOT NULL,
  run_id       TEXT NOT NULL,
  tool_call_id TEXT NOT NULL,
  args_digest  TEXT NOT NULL,
  status       TEXT NOT NULL,   -- pending|allowed|denied|cancelled|expired
  expires_at   TEXT NOT NULL,
  created_at   TEXT NOT NULL
);

-- 快照：投影缓存，随时可由事件重建
CREATE TABLE journal_snapshots (
  thread_id   TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  seq         INTEGER NOT NULL,
  revision    INTEGER NOT NULL,
  body        TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
```

数据库配置与现有 Python 保持一致：`WAL`、`synchronous=NORMAL`、`busy_timeout`。理由不重复造轮子，`app/sqlite_write.py:74` 已经记录过 PRAGMA 的实际成本。

### 3.3 协议

`core.app_server.v1` 已存在且被前端 `protocol.ts` 固定，首批**不改版本号、不改字段语义**，只做 Rust 侧对齐。新增能力一律走能力协商，不改老字段。

已有方法别名表必须原样对齐，见审计报告 3.2。特别是 `turn/stop` 与 `turn/terminate` 同义、`turn/pause` 是另一回事，这类细节错一个就会让桌面按钮行为变化。

已有 `thread/gap` 丢帧补偿机制必须复刻。Python 的 `live_router.py` 里 `_record_outbound_drop:456`、`_schedule_outbound_gap:473`、`_publish_outbound_gap:494` 就是完整实现，Rust 照抄语义即可。这不是可选优化，是现有前端已经依赖的行为。

版本协商新增两个可选字段，挂了也不影响老客户端：`protocolMin`、`protocolMax`、`capabilities`。

---

## 4. 关键机制伪代码

### 4.1 命令幂等与收据

```rust
// sunday-host：所有命令的唯一入口
pub async fn execute(db: &Store, cmd: CommandEnvelope) -> CommandReceipt {
    // 1) 先做上下文与能力校验，拒绝不落库
    let ctx = db.check_owner(&cmd.context)?;
    if !ctx.capabilities.allows(cmd.kind()) {
        return CommandReceipt::rejected(cmd.request_id, CoreError::UnsupportedCapability);
    }

    // 2) 收据、事件、投影在同一事务内提交
    db.write_tx(|tx| {
        // 同一 request_id 的重发直接返回原收据，绝不产生第二个执行
        if let Some(existing) = tx.find_receipt(&cmd.request_id)? {
            return Ok(existing);
        }
        tx.compare_revision(&cmd.context.thread_id, cmd.expected_revision)?;
        let receipt = tx.insert_receipt(&cmd.request_id, Status::Accepted)?;
        let seq = tx.next_seq(&cmd.context.thread_id)?;
        tx.append_event(seq, Event::CommandAccepted { kind: cmd.kind() })?;
        tx.touch_snapshot(&cmd.context.thread_id, seq)?;
        Ok(receipt)
    })
}
```

网络层规则单独写，因为这是最容易出错的地方：

```rust
// 客户端拿不到响应时，不代表命令没执行
match transport.send(env).await {
    Ok(receipt) => receipt,
    Err(TransportError::Timeout | TransportError::Disconnected) => {
        // 原 request_id 重发，让服务端用收据告诉你真实状态
        CommandReceipt::unknown(env.request_id)
    }
}
```

**禁止行为：超时后用新 `request_id` 重发。** 那会产生两条命令。

### 4.2 工具调用的未知态

这是设计要求 A07，Python 与 Rust 两栈都没有，属于新建。

```rust
async fn execute_tool_call(call: &ToolCall, tool: &dyn Tool, env: &Env) -> ToolOutcome {
    // 阶段一：在执行之前把意图写死
    let stage = env.store.prepare_tool_once(call, tool.side_effect).await?;
    match stage {
        PreparedState::AlreadySucceeded(out) => return ToolOutcome::Replayed(out),
        PreparedState::UnknownNonIdempotent => {
            // 上次已发出、结果不明、且副作用不可重放
            return ToolOutcome::WaitingForReconciliation;
        }
        PreparedState::Ready => {}
    }

    // 阶段二：标记已派发，这一步必须在真正产生副作用之前
    env.store.mark_dispatched(&call.id).await?;

    // 阶段三：执行。执行结果必须落库才算数
    let outcome = tool.execute(call.args.clone()).await;
    env.store.finish_tool_call(&call.id, &outcome).await?;
    outcome
}

// 崩溃恢复：只在这里区分安全性
async fn recover_after_crash(store: &Store) -> Result<()> {
    for call in store.list_unfinished_tool_calls().await? {
        match (call.stage, call.side_effect) {
            (Prepared, _) => store.requeue(call.id).await?,
            (Dispatched, NonIdempotent) => store.mark_unknown(call.id).await?,
            (Dispatched, Idempotent) => store.reconcile_or_requeue(call.id).await?,
            (Approved, _) => store.restore_pending_approval(call.id).await?,
            _ => {}
        }
    }
    Ok(())
}
```

界面表现：`WaitingForReconciliation` 要作为可见状态呈现给用户，说明哪个工具、什么参数、可能已经发生了什么，让用户手动核对后选择重试或放弃。不能静默跳过，也不能自动重试。

### 4.3 队列与 cancel

现有关键区别：Python 的 `accept_run` 只做准入拒绝，不做排队。Rust 需要真正的排队，否则用户连点两次发送就会看到"拒绝"。

```rust
pub struct ThreadActor {
    queue: Mutex<VecDeque<QueuedTurn>>,
    running: Mutex<Option<RunHandle>>,
}

impl ThreadActor {
    // 同一 thread 只有一个 run 在跑，其余排队而不是拒绝
    pub async fn submit(&self, turn: QueuedTurn) -> QueuedAck {
        if self.running.lock().await.is_none() {
            self.start(turn).await;
            QueuedAck::Started
        } else {
            self.queue.lock().await.push_back(turn);
            QueuedAck::Queued { position: self.queue.lock().await.len() }
        }
    }

    // 取消只作用于指定 run，不影响排队中的
    pub async fn cancel(&self, run_id: &RunId) {
        if let Some(handle) = self.running.lock().await.as_ref() {
            if &handle.run_id == run_id {
                handle.flag.cancel();
                handle.wake.notify_one();
            }
        }
    }
}
```

取消语义要写清三条边界，因为现有实现有两个盲区：

1. 取消是协作式的，模型流式期间会尽快生效。
2. 工具执行中不可中断。已在 `Dispatched` 阶段的工具调用必须走完并落库，不能半途抛弃。这是正确做法，不是缺陷，但界面必须如实显示"正在收尾"。
3. 取消后排队中的 turn 不自动开始，由用户决定。

### 4.4 Android 文件访问

设计要求明确禁止把 SAF URI 当普通路径。现有 `project_directory_browse` 是普通路径实现，这部分要补。

```rust
pub enum FileHandle {
    Workspace { rel: String },          // 应用私有目录，普通路径
    Saf { uri: String, doc_id: String } // 系统授权目录，不透明句柄
}

#[async_trait]
pub trait FileAccess: Send + Sync {
    async fn list(&self, dir: &FileHandle) -> Result<Vec<FileEntry>, CoreError>;
    async fn read(&self, file: &FileHandle) -> Result<Bytes, CoreError>;
    async fn write(&self, file: &FileHandle, data: Bytes,
                   expect: Option<ETag>) -> Result<ETag, CoreError>;
    async fn delete(&self, file: &FileHandle, expect: Option<ETag>) -> Result<(), CoreError>;
}
```

Kotlin 侧只负责三件事：拿授权、按句柄读写、报告授权是否还有效。规范化与版本校验留在 Rust。

```kotlin
fun grantFolder(): OpaqueHandle {
    val uri = launchPicker(Intent.ACTION_OPEN_DOCUMENT_TREE) ?: throw UserCancelled()
    contentResolver.takePersistableUriPermission(
        uri, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
    )
    return handleStore.save(uri)
}

suspend fun readFile(handle: OpaqueHandle): ByteArray = withContext(Dispatchers.IO) {
    val uri = handleStore.resolveOrThrow(handle)   // 授权被撤销时抛 GrantRevoked
    contentResolver.openInputStream(uri)?.use { it.readBytes() } ?: throw PermissionDenied()
}
```

授权撤销的判定不能只靠缓存的 grant 列表，Android 允许用户在系统设置里撤销，必须在每次真实读写时捕获 `SecurityException` 并映射成 `GrantRevoked`，同时把该句柄标记失效。

写入遇到不支持随机访问的 provider 时，走临时副本加版本校验再写回，写回前比对 `expect` 的哈希，不一致返回 `RevisionConflict` 而不是覆盖。

### 4.5 远程设备认证

现有 `core/remote/relay` 与桌面壳已用 `snow 0.9` 做 Noise 握手，`mdns-sd` 做局域网发现。这部分复用，但要补三件事：

```rust
// 1) 设备身份是长期密钥，不是会话密钥
pub struct DeviceIdentity {
    device_id: DeviceId,        // 公钥指纹
    private_key: Ed25519Secret, // 存 OS 安全存储
}

// 2) 配对只负责建立首次信任，不是长期凭据
pub enum Pairing {
    // 六位码只用于核对两端看到的同一公钥指纹
    SixDigit { code: String, ttl: Duration },
    Qr { payload: String, ttl: Duration },
}

// 3) 会话内再走 Noise，防止中转看到明文
// relay 只做路由与在线状态，绝不持有会话密钥
```

硬性规则，写进代码而不是文档：中转进程永远不解密业务负载；凭据不写入日志、崩溃报告、诊断包；设备撤销后立刻拒绝新会话，而不仅是断开当前连接。

### 4.6 CLI 与 GUI 对齐

设计要求每个 GUI 领域功能都有等价 CLI，现有 45 个命令组里缺主题、桌宠、记忆星图、RAG、检查点回滚、Study、Workflow、QQ 机器人。

补齐方式分两类，明确写清限制而不是假装都能做：

| 类型 | 处理 | 例子 |
|---|---|---|
| 领域操作 | CLI 直接实现 | `sunday checkpoint list` / `sunday checkpoint restore` |
| 必须用户交互 | CLI 返回结构化 `NeedsUserInteraction`，带可复制的动作说明 | `sunday folder grant`（SAF 选择器只能在界面点） |
| 纯桌面表现 | CLI 明确报不支持并给出原因 | 桌宠动画、主题可视化编辑器、多窗拖拽 |

`NeedsUserInteraction` 作为稳定错误码进 `sunday-protocol`，CLI 退出码单列，便于脚本判断。

---

## 5. 功能覆盖清单

标记：`已有` 表示代码里能用且本次审计看到实现；`部分` 表示有骨架缺关键机制；`未实现` 表示代码中不存在。

### A 共享核心与兼容

| 编号 | 项 | 状态 | 依据 |
|---|---|---|---|
| A01 | Python 行为盘点 | 已有 | 本报告第 1、2 节 |
| A02 | 协议类型与错误码 crate | 部分 | `AgentRuntime` 有类型，无独立 crate，无错误码体系 |
| A03 | 会话事件持久化与投影 | 未实现 | 手机端是整份 JSON 覆写 |
| A04 | 多轮 Loop 与暂停续跑 | 已有 | `lib.rs:549 run_turn`、`run_turn_progress` |
| A05 | 真实 Provider 与流式 | 已有 | `provider.rs` 4,493 行 |
| A06 | 工具注册与执行 | 已有 | `tool_catalog.rs` 与宿主 `sunday_tool_catalog` |
| A07 | 未知态与不重放 | 未实现 | 两栈均无 |
| A08 | Steer 与 Queue | 部分 | 有 guidance，无真正排队 |
| A09 | 事件序号与断线补拉 | 部分 | Python 有 `thread/gap`，Rust 无日志 |
| A10 | 回滚分叉与旧数据安全 | 部分 | `checkpoints.rs` 只标回合边界 |
| A11 | CLI 与 GUI 对齐 | 部分 | 45 命令组，缺口见 4.6 |
| A12 | 模块可脱 Tauri 测试 | 部分 | `runtime-rs` 无 tauri 依赖，符合条件的测试仅 6 个文件 |
| A13 | Windows 兼容 v1 协议 | 未实现 | 桌面仍只跑 Python |
| A14 | 配置与 JSONC 兼容 | 部分 | Rust 侧有 `profiles.rs` 851 行，未见 JSONC 全量兼容 |
| A15 | 单写者与可回滚切换 | 未实现 | 无跨进程锁 |

### B Android 本机能力

| 编号 | 项 | 状态 | 依据 |
|---|---|---|---|
| B01 | 真机签名 APK | 部分 | CI 出 debug APK，未验证签名与真机 |
| B02 | 本机独立 Agent | 已有 | `sunday_agent_turn` 走 `AgentRuntime` |
| B03 | 私有工作区隔离 | 已有 | `native_project_root` |
| B04 | SAF 授权目录 | 未实现 | 只有普通路径 `project_directory_browse` |
| B05 | 文件读写删与确认 | 部分 | 有 `project_file_*`，无审批与版本冲突 |
| B06 | WebFetch 与 WebSearch | 已有 | `fetch_tools.rs`、`web_search.rs` |
| B07 | Checklist | 已有 | `plan_tools.rs:333` 与 `:373`，声明 AutoAllow |
| B08 | 子代理 | 已有 | `sub_agent.rs` 加 `sunday_sub_agent_*` |
| B09 | 模型配置与密钥 | 部分 | 有配置，密钥走 `secure_storage_*` 但 Provider 层未接 |
| B10 | 按需权限 | 部分 | 未见权限矩阵实现 |
| B11 | 系统分享与附件 | 部分 | `attachments.rs` 有，分享入站未见 |
| B12 | 通知 | 未实现 | `notifications.ts` 的 `notifyMobile` 是空实现，注释指向要废弃的 Capacitor 工程 |
| B13 | 后台与进程终止恢复 | 部分 | 有状态持久化，无事件日志，恢复靠整份 JSON |
| B14 | 返回手势与软键盘 | 部分 | 有 `window_insets.rs` 24 行 |
| B15 | 无 Python 依赖 | 已有 | `runtime-rs` 与 `mobile` 均无 Python |

### C 共享 UI

| 编号 | 项 | 状态 |
|---|---|---|
| C01 | 复用消息数据契约 | 部分，`protocol.ts` 与投影可复用，`MessageView.vue` 205.9 KB 强绑桌面 |
| C02 | 单栏自适应 | 未实现，需新建 MobileShell |
| C03 | 会话列表与工作区切换 | 部分，`standalone/` 有客户端 |
| C04 | 流式与工具卡展示 | 部分 |
| C05 | 附件与文件引用 | 部分 |
| C06 | 审批与设备绑定 | 部分，无 args_digest 绑定 |
| C07 | 运行过程折叠 | 部分 |
| C08 | 文件预览与编辑 | 部分 |
| C09 | 主题 token 复用 | 已有，`themeToCSSVars` 纯函数 |
| C10 | 桌面改动触发移动截图回归 | 未实现 |

### D 远程设备

| 编号 | 项 | 状态 |
|---|---|---|
| D01 | 设备身份与撤销 | 部分，有 Noise 与配对，无长期身份与撤销 |
| D02 | 局域网配对 | 已有，`lan_discovery_discover` 加 `pairing/` |
| D03 | 设备列表与工作区选择 | 部分，`ConnectionManager` |
| D04 | 远端流式与审批 | 部分 |
| D05 | 远程文件浏览下载 | 未实现 |
| D06 | 命令去重与并发冲突 | 未实现 |
| D07 | E2EE Relay 与轮换 | 部分，`remote/relay` 有 `pairing_abuse.rs`、`push.rs` |
| D08 | 条件写入 | 未实现 |
| D09 | 离线排队 | 未实现 |

### E 插件与高级

| 编号 | 项 | 状态 |
|---|---|---|
| E01 | 能力清单 | 部分，`plugin_catalog.rs` 474 行 |
| E02 | Skills 跨端 | 已有，`skills.rs` 811 行 |
| E03 | MCP | 部分，`mcp.rs` 796 行，Android 只能连 HTTP 型服务 |
| E04 | Hooks | 已有，`hooks.rs` 923 行 |
| E05 | 声明式 UI | 未实现 |
| E06 | Python 插件标记仅桌面 | 未实现 |
| E07 | 自动化与后台约束 | 部分，`StandaloneArrangeStore` |
| E08 | Study 与 Workflow | 部分，`study.rs` 3,607 行、`workflow_*` 约 7k 行 |
| E09 | 语音与生图 | 部分，`image_gen.rs` 565 行，语音未实现 |
| E10 | 无障碍读屏 | 未实现，明确不在首批 |

### F 发布与安全

| 编号 | 项 | 状态 |
|---|---|---|
| F01 | 双端 CI | 部分，job 在，`cargo` 现在失败 |
| F02 | 单一版本源 | 部分，release 断言 5 处 |
| F03 | 固定签名与升级 | 未实现，CI 只出 debug |
| F04 | 隔离 Profile | 部分，`LAMTOOLS_HOME` 等环境变量可隔离 |
| F05 | 增量升级与断电模拟 | 未实现 |
| F06 | 远程鉴权与 E2EE | 部分 |
| F07 | 权限与注入测试 | 未实现 |
| F08 | 后台限制复核 | 未实现 |
| F09 | CI 证据留存 | 部分 |
| F10 | 文档 | 部分 |

---

## 6. 按依赖排序的实施计划

每个阶段都有明确退出条件。退出条件不满足不进下一阶段。

### 阶段 0：红线修复与基线固化

依赖：无。
做什么：

1. 修 `runtime-rs/src/plugin_catalog.rs` 的 8 处 `include_str!`，改为 Rust 自有清单，Python 目录缺失也能编译。
2. 用隔离 Profile 跑一遍 `cargo test`、pytest 关键子集、vitest 契约测试，把当前真实通过率记成基线数字，写进 `方案/` 下的基线文件。
3. 给 `core_sync_changes` 加统计脚本与只读诊断命令，先不改数据。

退出条件：`cargo check --all-targets` 与 `cargo test` 在 `core/runtime-rs` 全绿；基线数字有据可查。

### 阶段 1：协议与存储骨架

依赖：阶段 0。
做什么：

1. 建 `sunday-protocol`，把 `AgentRuntime` 现有类型迁入，加稳定错误码与版本协商。
2. 建 `sunday-store`，落 3.2 的五张表，实现 `append_event`、`find_receipt`、`prepare_tool_once`、`mark_dispatched`、`finish_tool_call`。
3. 建 `sunday-cli`，只做 `health`、`db inspect`、`journal tail` 三个只读命令。

退出条件：`cargo test -p sunday-store` 覆盖幂等、seq 单调、崩溃恢复三分支；`sunday-cli db inspect` 能对一个 Python 库的克隆做只读统计且不修改文件，用文件哈希前后比对证明。

### 阶段 2：最小可运行闭环

依赖：阶段 1。
做什么：把 `AgentRuntime` 接到 `sunday-store`，实现真实 LLM 到工具到审批到落库，加队列与未知态。

目标闭环，这是设计的"最早可验证"：

```
sunday-cli workspace create demo
sunday-cli turn --workspace demo --prompt "创建 hello.txt 并写入 hello Sunday"
  → 真实模型返回 tool call
  → CLI 提示审批
  → 用户确认
  → 文件写入，事件入 journal，收据入 receipts
sunday-cli journal tail --thread <id>      # 看到完整 seq 序列
kill 进程；重新执行
sunday-cli turn --thread <id> --prompt "继续"
  → 从 journal 恢复上下文，不重复写文件
```

退出条件：上述命令在隔离 Profile 下真实跑通，附终端输出；故意在工具已派发后杀进程，重启显示 `OutcomeUnknown` 且不重放。

### 阶段 3：Windows 接管

依赖：阶段 2。
做什么：`sunday-host` 实现 `core.app_server.v1` 的 WS 协议子集，先覆盖桌面真实用到的 `thread/*`、`turn/*`、`approval/respond`、`session/*`、`queue/*`。桌面 `tauri.conf.json` 加后端选择，Python 仍是默认。

退出条件：同一份 `core/ui` 前端，分别接 Python 与 Rust 后端，跑同一组操作，事件与投影结果一致；用前端现有 262 个测试中的契约子集做对照。

### 阶段 4：Android 收口

依赖：阶段 2。
做什么：明确 Capacitor 外壳退役范围；把 `mobile/src-tauri` 接入 `sunday-store`，替换整份 JSON 覆写；补 SAF、通知、分享入站、权限按需。

退出条件：真机断网、断电脑、关闭中转，跑通一轮真实模型加文件工具加审批；进程被杀后恢复；SAF 授权撤销后工具返回 `GrantRevoked` 且不崩溃。

### 阶段 5：远程与多设备

依赖：阶段 3 与 4。
做什么：设备长期身份、撤销、命令去重、断线补拉、远程文件浏览下载。

退出条件：100 次断线重连不丢已确认事件、不重复执行已确认命令，有脚本与日志。

### 阶段 6：生态与治理

依赖：阶段 3、4、5。
做什么：MCP 传输补 HTTP、插件能力清单、双端 CI 硬化、签名与升级、Python 逐步退役。

退出条件：CI 双端全绿且有产物与哈希留存；3 次跨版本升级保留用户数据。

### 阶段 7：数据治理

依赖：阶段 1。可与阶段 2 并行。
做什么：`core_sync_changes` 保留策略、历史归档、3.6 GB 库的在线整理方案。

退出条件：克隆库上实测整理后体积下降，且内容校验一致，10 套代表性样本全部通过。

---

## 7. 验收标准

所有测试用隔离 Profile，环境变量 `SUNDAY_PROFILE_ROOT` 指向临时目录，绝不触碰真实 `.lam` 与 `data/core.db`。

| 维度 | 门槛 | 怎么验 | 现在能不能达成 |
|---|---|---|---|
| 核心编译 | `cargo check --all-targets` 与 `cargo test` 双端通过 | CI 命令 | 不能，`plugin_catalog` 编译失败 |
| 核心无 Python | APK 内无 Python、Termux、Linux 环境；Rust Core 独立跑 | 产物扫描加运行探针 | 部分，代码已无 Python 依赖 |
| 本机独立 | 关电脑、关中转，手机跑通真实模型加工具加审批加文件 | 真机，记录机型与系统版本 | 不能，缺事件日志与审批落库 |
| 契约等价 | Python 与 Rust 事件与投影一致率 100% | 同一输入双跑对照 | 不能，Rust 未接协议 |
| 幂等 | 同一 `request_id` 重发 100 次只产生一次已确认执行 | 脚本重放 | 不能，无收据表 |
| 未知副作用 | 注入崩溃后进 `OutcomeUnknown`，不自动重放 | 故障注入 | 不能，无未知态 |
| 事件完整 | 100 次断线重连不丢已提交事件、不重复应用 | 网络注入加 seq 审计 | 不能 |
| 故障恢复 | 100 次杀进程、重建界面、断网，已持久化状态可恢复 | 自动化注入 | 不能，整份 JSON 覆写 |
| 权限安全 | 未授权目录与设备操作 100% 拒绝 | 权限矩阵 | 不能，无 SAF |
| 迁移一致 | 10 套代表性数据库迁移前后关键内容一致 | 备份加校验和加只读投影 | 不能，未开始 |
| 升级 | 同签名 APK 3 次跨版本升级保留数据 | 真机覆盖安装 | 不能，只有 debug APK |
| 屏幕 | 360、393、600、840dp 与横屏无遮挡无横溢 | 截图加交互 | 不能 |
| 性能 | 首屏可交互不超过 3 秒；本机事件 UI 更新 P95 不超过 250ms | 冷启动与 1 万事件基准 | 未测，先测基线再锁阈值 |
| CI | Rust 加 TS 加 Android 加 Windows 全绿才可合并 | 分支保护 | 不能，现为红 |

性能阈值在阶段 0 测出基线后锁定具体数字，不用感觉代替结果。

---

## 8. 回滚方案

**前提保证：阶段 1 到 3 期间，Rust 不修改 `core.db` 的任何老表，只新增独立表或独立库文件。**

| 场景 | 回滚动作 | 数据影响 |
|---|---|---|
| Rust 核心出新版本崩溃 | 桌面后端配置切回 Python，重启应用 | 老表未动，会话历史完好；Rust 新增表被忽略 |
| Rust 写入数据后需回退 | 直接在 Profile 里把后端标识切回 python，启动时校验锁已释放 | 已写入的 Rust 表保留不删，便于事后取证 |
| 数据治理出问题 | 保留整理前的完整备份，按备份路径还原 | 需独占写锁，还原后校验 `integrity_check` |
| Android 升级失败 | 保留上一版 APK 与库备份，同签名覆盖安装旧版 | 新表保留，旧版不读 |
| 协议不兼容 | 前端不动，后端回退；Rust 新增能力靠能力协商，老客户端不下发 | 无 |

三条硬规则：

1. 迁移前必须备份，且备份要有独立校验和，并在隔离环境试还原一次。
2. 切换写者必须持有独占锁，拿不到锁就明确失败，不重试、不降级。
3. 任何阶段都不允许为了"通过测试"删除现有测试或现有功能。

---

## 9. 需要你确认的六个决策

**决策一：改造还是重建 Rust Core。**
我建议改造现有 `core/runtime-rs`，保留 33.6k 行已验证实现，按 crate 逐步搬出。重建会丢掉 Android 上已经跑通的 Agent。

**决策二：`core/mobile` 的废弃边界。**
先说清现状，因为它比设计资料复杂。`core/mobile` 下有两套独立 Android 工程：Capacitor 在 `core/mobile/android/` 与 `core/mobile/ios/`，Tauri 在 `core/mobile/src-tauri/gen/android/`。Tauri 那套已经有 6 个自有 Kotlin 插件：安全存储、附件打开、诊断分享、局域网发现、外壳能力、软键盘内边距。

我建议废弃 Capacitor 两套工程与 Noise 隧道遥控架构，保留 `mobile/src-tauri` 的本机宿主代码、那 6 个 Kotlin 插件、以及 `standalone/` 客户端。理由是这些正是设计要求的能力。同时 `ci.yml` 的 `mobile-android` job 需要相应调整，否则会长期红。`notifications.ts` 的空实现挂靠在 Capacitor 上，也要重做到 Tauri 路径。

**决策三：Windows 接管先做协议还是先做数据。**
我建议先做协议兼容，让 Rust 后端能顶替 Python 的 WS 接口，前端一行不改。数据接管放在协议跑通之后，风险更低。

**决策四：1.88 GB 的 `core_sync_changes` 什么时候处理。**
我建议在阶段 7 单独处理，但阶段 0 就加只读诊断。不要和功能迁移混在一起做，否则出问题分不清是谁的责任。如果你希望先瘦身再迁移，那阶段 7 要提到阶段 1 之前。

**决策五：移动端密钥存哪。**
现状是 Tauri 侧已有 `LamToolsSecureStoragePlugin.kt` 与 Rust 侧的 `MobileSecureStorage` 包装，`secure_storage_*` 三个命令已经在用系统能力。所以我建议不引新依赖，直接把这条现有通道收敛成 `SecretStore` trait，Windows 侧用已有的 `keyring` 依赖实现同一个 trait。这样两端各自用系统能力，代码只维护一个抽象，改动面最小。

`tauri-plugin-stronghold` 的代价是引入新依赖、新存储格式、以及一次密钥迁移，收益不明显。

**决策六：CI 红线怎么处理。**
现在 `mobile-android` job 会失败。我建议阶段 0 直接修好，而不是把它降级成 `cargo check`，因为降级等于把"共享核心改动必须过 CI"这条要求作废。

---

## 10. 我打算先做的第一批动作

等你确认后，第一批只做这几件事，都是低风险且可验证：

1. 修 `plugin_catalog.rs` 的编译断裂，让 Rust 不再依赖 Python 目录。
2. 加 `sunday-protocol` 与 `sunday-store` 两个空 crate 加五张表的建表与测试。
3. 加 `sunday-cli` 的 `db inspect` 只读命令，对克隆库跑一次，输出表与行数统计。
4. 写基线文件，记录当前真实通过率数字。

这四步做完你会拿到可运行结果和真实数字，再决定阶段 2 的范围。
