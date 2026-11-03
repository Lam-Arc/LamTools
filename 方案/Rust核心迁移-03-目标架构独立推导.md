# Sunday Rust Agent Core 目标架构独立推导

本文不参考 `core/runtime-rs` 的现有模块划分。推导只有三个输入：Sunday 的真实需求、Python Core 已被验证的行为、成熟 Agent Harness 的公开实现证据。

结论先行：Sunday 需要的是一个**薄核心加可装卸外围**的结构，核心只负责「回合、状态、授权、持久化」四件事，产品功能一律在外围 crate。核心的行数目标在 1 万行以内，而不是 3 万行。

---

## 1. 推导依据

### 1.1 输入一：Sunday 的真实需求

来自需求本身，不是来自代码：

1. 同一个 Agent 要能在 Windows 与 Android 上本机运行，不依赖 Python、Termux、Linux 镜像。
2. 同一套协议要能同时服务桌面多栏界面与手机单栏界面。
3. 手机要能远程操控电脑上的实例，也要能完全独立工作。
4. 断网、杀进程、Activity 重建后，已确认的状态不能丢，已执行的命令不能重跑。
5. 工具调用有真实副作用，写文件、发消息、下单这类操作不能因为超时而重复。
6. 用户必须能看懂并控制每一次有风险的操作。
7. 插件与扩展要在两个平台上表现一致，不能一边能跑一边不能。
8. 所有 GUI 能力都要有对应的 CLI 入口或明确说明为什么不能有。

### 1.2 输入二：Python Core 已被验证的有效行为

这里只取行为语义，不取实现方式。以下几条在 Python 侧有测试覆盖且语义自洽，值得原样保留：

| 行为 | 语义 | 为什么值得保留 |
|---|---|---|
| 插话三段式 | staged 到 offered 到 consumed，全部按 run 绑定 | 三段式保证插话不会落在半批工具结果中间 |
| 先收后放 | 先收集插话，等本批工具写回完成再落地 | 避免工具结果与用户新指令交错产生歧义 |
| 取消双源汇一 | 事件标志加任务取消，收敛到单一检查点 | 单一收敛点让取消行为可测 |
| 审批不超时 | 超时不等于同意 | 安全语义正确，不能用默认值代替用户决定 |
| 每会话单活跃 run | 准入闸门返回布尔值 | 避免两条 run 同时写同一会话 |
| 工具结果去重 | 连续相同结果达阈值即停 | 防止模型陷入重复调用死循环 |

以下行为在 Python 侧是缺陷，**不能**在 Rust 继承：

| 缺陷 | 证据位置 | Rust 应改成 |
|---|---|---|
| 无最大轮数 | `kernel/policy.py` 只有重试次数，无回合上限 | 显式回合预算加工具预算 |
| 工具执行不可取消 | `kernel/loop.py:3464` 与 `:3975` 无取消检查 | 派发后不中断，但必须在界面上显示收尾状态 |
| 无结果未知态 | 全仓 `indeterminate` 零命中 | 独立状态机阶段加人工核对 |
| 排队靠拒绝 | `runtime/__init__.py:393` 只返回布尔 | 真正的队列加位置反馈 |
| 插件同进程任意代码 | `plugin_system/lifecycle.py:212` importlib | 进程或能力边界隔离 |

### 1.3 输入三：成熟实现的公开证据

两套实现，规模差异很大，正好当上下界。

**OpenAI Codex 的 Rust 工作区**，取自 `codex-rs/Cargo.toml` 的 workspace members，共 169 个 crate。与本议题直接相关的划分：

- `protocol`：只放类型。该 crate 的 README 原文要求 "should have minimal dependencies"，并且 "avoid material business logic in this crate"，业务能力用 `Ext` 风格 trait 在别的 crate 里加。
- `core`：README 原文 "implements the business logic for Codex. It is designed to be used by the various Codex UIs written in Rust"。即核心只服务 UI，不绑死某一个界面。
- `thread-store`：存储是一个 trait 边界，README 说明它 "defines the ThreadStore trait plus local and in-memory implementations. Other storage implementations may live outside this repository"。
- `thread-store` 的职责切法值得照抄：`append_items` 是"原始规范历史追加"，明确"不根据条目内容推断元数据"；`update_thread_metadata` 是唯一的元数据写入口；`LocalThreadStore` 用 **JSONL rollout 文件存历史，用 SQLite 存可查询元数据**。
- 平台能力独立成 crate：`sandboxing`、`linux-sandbox`、`windows-sandbox-rs`、`file-system`、`secrets`、`keyring-store`。`core` 的 README 用整节篇幅讲每个平台各自的沙箱前提，说明平台差异被隔离在核心之外。
- 扩展独立成 crate：`ext/skills`、`ext/mcp`、`ext/web-search`、`ext/image-generation`、`ext/queue`、`ext/goal`、`ext/memories`。
- 进程控制独立成服务：`exec-server` 是一个小的 JSON-RPC 服务，专门负责"启动和控制子进程"，并自带 client 与 protocol crate。工具执行的能力边界因此可以被单独测试和替换。

**Block 的 Goose**，取自 `crates/` 目录与 workspace 依赖。共 14 个左右 crate：`goose-agent`、`goose-providers`、`goose-provider-types`、`goose-mcp`、`goose-context-management`、`goose-sdk`、`goose-sdk-types`、`goose-roaming`、`goose-local-inference`、`goose-download-manager`、`goose-cli`、`goose-test-support`。

它的取舍和 Codex 不同：agent 与 provider 分开但没有拆到上百个 crate，网络直连单独成 `goose-roaming` 用 iroh 做点对点，本地推理单独成 crate。整体粒度比 Codex 粗一个数量级。

**两套实现共同收敛出的四条：**

1. 类型层与业务层必须分 crate，类型层依赖要少。
2. 持久化是 trait 边界，历史用追加日志，可查询字段才进 SQLite。
3. 平台差异，尤其沙箱与文件系统，独立成 crate 或独立服务。
4. 扩展是独立的 crate，不是核心里的一个大 match。

**两套实现分歧的地方，也就是需要 Sunday 自己判断的地方：**

Codex 的 169 个 crate 对 Sunday 是过度工程。它背后是多家 UI、多平台沙箱、云端后端、企业策略。Sunday 是两个应用、一个核心、两种平台。Goose 的 14 个 crate 更接近 Sunday 的实际规模。所以 Sunday 的目标粒度取**十来个 crate**，不取上百个。

---

## 2. 从需求反推的不变量

架构不是画方块，是先定下必须永远成立的事实。以下 12 条是 Sunday 的架构不变量，每一条都能被测试验证。

| 编号 | 不变量 | 怎么验 |
|---|---|---|
| I1 | 事件在同一 thread 内 seq 单调递增且无空洞 | 追加后读回比对 |
| I2 | 同一 `request_id` 重发任意次，只产生一次已确认执行 | 重放脚本，数执行次数 |
| I3 | 工具在产生副作用之前，意图必须已落盘 | 杀进程后查库 |
| I4 | 已派发且结果未落盘的非幂等工具，重开后进入未知态且不重放 | 故障注入 |
| I5 | 审批绑定具体参数摘要，参数变了审批失效 | 改参数后重放 |
| I6 | 审批过期不等于同意 | 跨过期时间提交 |
| I7 | 同一会话同时只有一条 run 在执行，其余排队而非拒绝 | 并发提交 |
| I8 | 取消后不再开始新的工具调用，已派发的必须收尾并落库 | 取消时序测试 |
| I9 | 投影可以随时从日志完整重建，不依赖增量状态 | 清空投影后重建比对 |
| I10 | 核心不引用任何平台专有 API，平台能力全部走 trait | 编译期依赖检查 |
| I11 | 错误是稳定的枚举而非字符串，CLI 与界面可分支 | 枚举穷尽匹配 |
| I12 | 用户在界面上看到的工具审批对象，就是核心实际执行的那个对象 | 参数摘要比对 |

注意 I7 与 Python 现状相反。Python 的 `accept_run` 是拒绝，Sunday 需要排队，因为手机用户连点两次发送是常态。

---

## 3. 分层

```
┌───────────────────────────────────────────────┐
│ 外壳：Windows Tauri · Android Tauri            │
│ 窗口、托盘、Kotlin 插件、通知、分享              │
└───────────────┬───────────────────────────────┘
                │ 只依赖 host 与 platform
┌───────────────▼───────────────────────────────┐
│ host：命令路由 · 会话装配 · 单写者 · 能力注册     │
│ 把 protocol 的命令翻成 agent 动作，把事件推给传输  │
└───────────────┬───────────────────────────────┘
                │
┌───────────────▼───────────────────────────────┐
│ 核心四件：agent（回合）· store（日志）            │
│           tools（授权与执行）· protocol（类型）    │
└───────────────┬───────────────────────────────┘
                │
┌───────────────▼───────────────────────────────┐
│ 外围：llm · extensions（skills/mcp/hooks）       │
│      · domain（study/workflow 等产品）           │
└───────────────────────────────────────────────┘
                │
        platform：文件 · 密钥 · 通知 · 进程 · 分享
```

依赖方向只能向下。**核心四件不允许依赖外围**，外围可以依赖核心。

---

## 4. crate 划分

| crate | 职责 | 允许依赖 | 行数目标 |
|---|---|---|---|
| `sunday-protocol` | 命令、事件、错误枚举、版本协商、投影结构 | serde 系 | 1.5k |
| `sunday-store` | 事件日志、命令收据、工具阶段、审批、投影重建 | protocol、SQLite | 2k |
| `sunday-agent` | 回合循环、预算、队列、取消、插话 | protocol、store | 2k |
| `sunday-tools` | 工具注册、授权判定、幂等执行、结果写回 | protocol、store、platform | 2.5k |
| `sunday-platform` | 文件、密钥、通知、进程、分享的 trait 与默认实现 | protocol | 1.5k |
| `sunday-llm` | Provider 适配、流式、重试、用量 | protocol | 3k |
| `sunday-extensions` | Skills、MCP、Hooks 的加载与调用 | protocol、tools | 3k |
| `sunday-host` | 装配、命令路由、单写者锁、能力协商 | 以上全部 | 2k |
| `sunday-cli` | 与 GUI 对齐的领域命令 | host | 1.5k |
| `sunday-domain-study` | Study 产品逻辑 | protocol、store | 8k |
| `sunday-domain-workflow` | Workflow 产品逻辑 | protocol、store | 6k |

合计核心五个 crate 约 9.5k 行，外围合计约 20k。产品域两个 crate 单独立项，不进核心。

**为什么产品域必须独立 crate：** 因为它们是产品，不是 Agent 能力。Study 与 Workflow 都不需要知道回合怎么跑、审批怎么等。把它们放进核心，等于每次动 Study 都要重新验证 Agent 循环。

**为什么 `llm` 不在核心：** 因为核心只需要一个 `Model` 端口。真实 Provider 有重试、限流、多协议差异、流式解析，这些是会持续变化的适配层，不该和回合状态机绑在一起。Codex 把 provider 单独成 crate，Goose 也单独成 crate。

**为什么不学 Codex 拆到上百个 crate：** Sunday 只有两个 UI、两个平台、没有云端策略系统。过度拆分会把每一次跨 crate 改动变成十几次发布协调，对单人维护是净负担。

---

## 5. 状态所有权

这是整个架构最容易搞错的地方，单独说清。

| 状态 | 唯一所有者 | 存在哪 | 谁能改 |
|---|---|---|---|
| 事件日志 | `sunday-store` | 追加日志文件加索引 | 只能追加，不能改 |
| 命令收据 | `sunday-store` | 同一事务内与事件一起写 | 只能由 store 写 |
| 工具阶段 | `sunday-store` | 随收据 | 只能由 tools 通过 store 改 |
| 待审批 | `sunday-store` | 与工具阶段同库 | 只能由 tools 与用户决定共同推进 |
| 会话投影 | `sunday-store` | 可重建的缓存 | 任何时刻可丢弃重建 |
| 当前回合上下文 | `sunday-agent` | 内存，回合结束即释放 | 只有 agent |
| 队列 | `sunday-agent` | 内存加收据 | 只有 agent |
| 模型凭据 | `sunday-platform` | 系统密钥库 | 只有 platform |
| 界面状态 | 外壳 | 前端内存 | 前端 |
| 产品数据 | 产品域 crate | 自己的库 | 自己 |

**关键点：核心不保存"当前会话是什么样"，只保存"发生过什么"。** 界面要的会话视图是投影，投影坏了就重建，不需要修复。

这条直接把需求里的"断网、重建、杀进程后状态可恢复"变成结构性保证，而不是靠补丁。

---

## 6. 关键接口

### 6.1 端口只有一个模型

```rust
pub trait Model {
    /// 流式产出，事件由调用方落库。核心不假设模型是同步还是异步。
    fn stream(&self, req: ModelRequest, sink: &mut dyn FnMut(ModelDelta))
        -> Result<ModelTurn, CoreError>;
}
```

现有实现的 `ModelBackend::complete` 只支持一次性返回，流式是额外挂的闭包，导致核心无法把"流式事件"当成一等公民。新架构把流式放进端口本身。

### 6.2 工具分成描述与执行

```rust
pub struct ToolSpec {
    pub id: String,
    pub input_schema: serde_json::Value,
    pub side_effect: SideEffect,
    pub hosts: HostMask,
    pub permission: Permission,
}

pub trait Tool: Send + Sync {
    fn spec(&self) -> &ToolSpec;
    fn execute(&self, args: Value, ctx: &ToolCtx) -> Result<ToolOutput, CoreError>;
}
```

`side_effect` 不是装饰，它直接决定崩溃恢复策略：纯函数与幂等可以直接重试，非幂等必须人工核对。

### 6.3 平台能力全部是可替换 trait

```rust
pub trait FileAccess: Send + Sync {
    fn list(&self, h: &FileHandle) -> Result<Vec<FileEntry>, CoreError>;
    fn read(&self, h: &FileHandle) -> Result<Vec<u8>, CoreError>;
    fn write(&self, h: &FileHandle, bytes: &[u8], expect: Option<&ETag>) -> Result<ETag, CoreError>;
}

pub trait SecretStore: Send + Sync {
    fn get(&self, key: &str) -> Result<Option<String>, CoreError>;
    fn set(&self, key: &str, value: &str) -> Result<(), CoreError>;
    fn delete(&self, key: &str) -> Result<(), CoreError>;
}
```

`FileHandle` 必须能表示两种东西：应用私有目录下的相对路径，以及系统授权目录的不透明句柄。两个平台各实现一次，核心代码不出现条件编译分支。

### 6.4 错误是枚举

```rust
pub enum CoreError {
    Rejected { reason: String },
    UnsupportedCapability { capability: String },
    PermissionDenied { resource: String },
    RevisionConflict { expected: u64, actual: u64 },
    ProtocolIncompatible { min: u32, max: u32 },
    OutcomeUnknown { tool_call_id: String },
    ApprovalExpired { approval_id: String },
    ApprovalArgsMismatch { approval_id: String },
    InvalidRequest { reason: String },
    Storage { reason: String },
    Model { reason: String },
}
```

这条已在原型里编译通过并测试。现有实现只有三个字符串变体，界面无法区分"权限拒绝"和"存储失败"，这正是要换掉的。

---

## 7. 持久化形态

**历史是追加日志，索引才是数据库。** 这是 Codex `thread-store` 的做法，也是唯一能让 3.6 GB 数据库问题不再出现的结构。

```
工作区/
  sessions/
    <thread>.jsonl     追加写，只增不改，一条一行
  index.db             SQLite：thread 元数据、seq 到行号映射、审批、收据
```

理由：

1. 追加写不需要重写整份会话。现有手机端整份 JSON 覆写是 O(n)，会话越长越慢。
2. 单条损坏最多影响一行，不会毁掉整库。
3. 索引库可以随时删掉重建，因为日志是权威。
4. 远程同步只需要传日志行，天然增量。

工具阶段与审批必须进 SQLite 而不是 JSONL，因为它们需要在事务里做条件更新，这是"只能成功一次"的基础。

---

## 8. 明确不做

防止过度工程，以下内容不放进首批架构：

1. 不做多租户。Sunday 是个人工具。
2. 不做插件热更新的版本协商矩阵，首批只做能力声明与拒绝。
3. 不做跨设备全库同步，只做会话级增量。
4. 不做自研补丁系统，Android 更新走系统安装。
5. 不做沙箱内的代码执行，首批只做受控工具。
6. 不把 Android 后台常驻当假设，长任务必须有检查点。

---

## 9. 这套架构要接受的检验

架构不是说了算，是要能被反驳。以下三条是它最可能出错的地方，必须在实施前验证：

1. **追加日志加索引的写放大** 是否比现有单库方案更省。需要在 1 万事件量级上实测。
2. **核心与产品域的切分** 是否真的让改产品不动核心。需要做一次"新增一个产品功能"的干跑。
3. **两个平台共用一套工具定义** 是否需要对每个工具做平台条件判断。如果每个工具都要写两次分支，说明抽象层错了。

第 3 条我没有验证。原型里没有实现 `hosts` 掩码与按平台过滤，只实现了工具注册表的基本形状。这一条属于待验证项，不能算已证明。
