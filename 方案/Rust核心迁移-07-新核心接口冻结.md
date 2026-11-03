# 新 Rust Core 接口冻结

状态：冻结草案 v1，2026-11-02。本文件是试迁移与后续实现的唯一契约来源。
修改本文件需要单独评审，因为它同时影响 Windows、Android、CLI 三方。

---

## 0. 冻结范围与兼容策略

**冻结的部分**：类型名、字段语义、错误枚举、端口签名、事件种类、不变量。这些改动会破坏所有实现方。

**可以演进的部分**：
- 新增错误变体，只要不删旧的
- 新增事件种类，消费方必须忽略未知种类
- 新增能力位，不能改已有位的含义
- 工具清单增减

**协议版本**：`sunday.core.v1`。命令与事件的线上形状冻结；版本协商字段 `protocolMin`、`protocolMax`、`capabilities` 允许新增。

**依赖禁令，编译期强制**：
`protocol`、`store`、`agent`、`tools` 四个 crate 不得出现 `tauri`、`jni`、`lamtools_core`、`std::process::Command`。用 `cargo deny` 或 CI 脚本扫描，作为硬门槛。

---

## 1. 模块边界

```
sunday-protocol   只放类型。依赖只允许 serde、serde_json、thiserror。
      ▲
      │
sunday-store      SQLite 与追加日志。依赖 protocol + rusqlite。
      ▲
      │
sunday-agent      回合状态机。依赖 protocol + store。
      ▲
      │
sunday-tools      工具注册与执行。依赖 protocol + store + platform。

sunday-platform   平台 trait，不含实现。依赖 protocol。
      ▲
      │
sunday-llm        模型适配。依赖 protocol。
sunday-extensions Skills/MCP/Hooks/SubAgent。依赖 protocol + tools。
sunday-host       装配与路由。依赖以上全部。
sunday-cli        命令行。依赖 host。
sunday-domain-*   产品域。依赖 protocol + store，禁止依赖 agent。
```

规则：**箭头只能向上**。`protocol` 不知道任何人存在。`domain` 不能依赖 `agent`，这条是关键，防止产品逻辑再次渗回核心。

---

## 2. 基础类型（sunday-protocol）

```rust
pub type DeviceId = String;
pub type WorkspaceId = String;
pub type ThreadId = String;
pub type RunId = String;
pub type TurnId = String;
pub type RequestId = String;

/// 不可透传到 UI 的不透明文件句柄。
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum FileHandle {
    /// 应用私有目录下的相对路径，不含盘符，不允许 `..`
    Workspace { rel: String },
    /// 系统授权目录的不透明引用，不允许当路径解析
    Opaque { grant_id: String, rel: String },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ETag(pub String);

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CommandEnvelope {
    pub protocol_version: String,
    pub request_id: RequestId,
    pub expected_revision: Option<u64>,
    pub thread_id: ThreadId,
    pub payload: Command,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Command {
    TurnStart { input: Vec<InputItem> },
    TurnSteer { guidance_id: String, text: String },
    TurnCancel,
    ApprovalRespond { approval_id: String, decision: Decision, args_digest: String },
    ThreadArchive,
    FileRead { handle: FileHandle },
    FileWrite { handle: FileHandle, bytes_b64: String, expect: Option<ETag> },
}
```

---

## 3. 错误（冻结，11 个变体）

```rust
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "code", rename_all = "snake_case")]
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

每个变体都必须能映射到 CLI 退出码与界面提示。新增变体只能追加。

---

## 4. 模型端口（冻结，流式是一等公民）

```rust
pub struct ModelRequest {
    pub model_id: String,
    pub messages: Vec<Message>,
    pub tools: Vec<ToolDefinition>,
    /// f64, not f32. JSON numbers are f64 and an f32 serialises as
    /// 0.20000000298023224, which providers reject as out of range.
    pub temperature: Option<f64>,
    pub max_output_tokens: Option<u32>,
}

#[derive(Clone, Debug, PartialEq)]
pub enum ModelDelta {
    Text(String),
    Reasoning(String),
    ToolCallDelta { index: usize, id: Option<String>, name: Option<String>, args_fragment: String },
    Usage { input_tokens: u32, output_tokens: u32 },
}

pub struct ModelTurn {
    pub text: Option<String>,
    pub reasoning: Option<String>,
    pub tool_calls: Vec<ToolCall>,
    pub usage: Option<Usage>,
    pub provider_state: Option<String>,
}

/// 只能在 io 边界异步。核心逻辑不要求 async 运行时。
#[async_trait]
pub trait Model: Send + Sync {
    /// 增量通过 sink 同步交付，落库由调用方决定。
    /// 返回 Err 时，已经交付的增量视为部分结果，调用方必须决定是否保留。
    async fn stream(
        &self,
        request: ModelRequest,
        sink: &mut (dyn FnMut(ModelDelta) + Send),
    ) -> Result<ModelTurn, CoreError>;
}
```

**约定**：`stream` 返回 `Ok` 时，`sink` 收到的增量与 `ModelTurn` 必须一致，不一致视为实现缺陷，由一致性测试捕获。

**重试规则，试迁移实测后补入冻结：**
一旦有任何 `ModelDelta` 已交给 `sink`，本次调用不得重试。原因是重试会让调用方看到重复文本，而调用方无法撤回已经写入的事件流。

**截断检测，试迁移实测后补入冻结：**
只有当响应使用分块传输编码或声明了 `Content-Length` 时，流中断才能被发现。没有这两种标识的响应，TCP 关闭与正常结束在协议上无法区分。实现必须在文档与诊断里标注"该响应无法验证完整性"，不能假装成功就是完整。

---

## 5. 工具端口（冻结）

```rust
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum SideEffect { Pure, Idempotent, NonIdempotent }

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum HostKind { Windows, Android, Server }

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ToolSpec {
    pub id: String,
    pub description: String,
    pub input_schema: serde_json::Value,
    pub side_effect: SideEffect,
    pub hosts: Vec<HostKind>,
    pub permission: Permission,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Permission { AutoAllow, AskUser, HardBlock }

#[async_trait]
pub trait Tool: Send + Sync {
    fn spec(&self) -> &ToolSpec;
    async fn execute(&self, args: serde_json::Value, ctx: &ToolCtx) -> Result<ToolOutput, CoreError>;
}
```

**约定**：`spec().hosts` 不含当前宿主时，工具不会出现在模型可见清单，也不会被调用。这是唯一允许的平台分支点，工具实现内部不允许再判平台。

---

## 6. 存储接口（冻结，含必须成立的条件）

```rust
pub trait Store: Send + Sync {
    /// 收据与事件在同一事务内提交。重复 request_id 返回原收据。
    fn accept_command(&mut self, env: &CommandEnvelope) -> Result<CommandReceipt, CoreError>;

    /// 声明的副作用发生之前调用。返回 Ready 才允许执行。
    fn prepare_tool_once(&mut self, call: &ToolCall, side: SideEffect, thread: &ThreadId)
        -> Result<Prepared, CoreError>;

    fn mark_dispatched(&mut self, call_id: &str) -> Result<(), CoreError>;
    fn finish_tool_call(&mut self, call_id: &str, result: &serde_json::Value) -> Result<(), CoreError>;

    fn request_approval(&mut self, thread: &ThreadId, call: &ToolCall, ttl: Duration)
        -> Result<ApprovalRequest, CoreError>;
    fn respond_approval(&mut self, approval_id: &str, args_digest: &str, now: u64)
        -> Result<Decision, CoreError>;

    fn append_event(&mut self, thread: &ThreadId, kind: EventKind, payload: serde_json::Value)
        -> Result<u64, CoreError>;
    fn events(&self, thread: &ThreadId, after: u64) -> Result<Vec<Event>, CoreError>;
    fn snapshot(&self, thread: &ThreadId) -> Result<Projection, CoreError>;
    fn rebuild_projection(&mut self, thread: &ThreadId) -> Result<Projection, CoreError>;

    fn recover(&mut self) -> Result<RecoveryPlan, CoreError>;
}
```

**必须成立的条件**（每条对应一个测试）：
- S1 同一 `request_id` 任意次调用只产生一个收据、一个事件
- S2 `events` 的 seq 在同一 thread 内严格递增且连续
- S3 `prepare_tool_once` 在副作用前持久化
- S4 `mark_dispatched` 之后未 `finish` 的 `NonIdempotent` 调用，`recover` 必须标为 unknown
- S5 `respond_approval` 参数摘要不符返回 `ApprovalArgsMismatch`
- S6 `respond_approval` 超时返回 `ApprovalExpired` 且状态落库
- S7 同一审批只能用一次
- S8 `rebuild_projection` 结果与增量投影一致

---

## 7. 事件种类（冻结，允许追加）

```rust
pub enum EventKind {
    CommandAccepted,
    RunStarted,
    ModelStarted,
    ModelDelta,
    ModelCompleted,
    ToolProposed,
    ToolPrepared,
    ApprovalRequested,
    ApprovalResolved,
    ToolDispatched,
    ToolSucceeded,
    ToolFailed,
    ToolOutcomeUnknown,
    ToolReplayed,
    GuidanceReceived,
    RunPaused,
    RunResumed,
    RunCancelled,
    RunCompleted,
    RunWaitingForReconciliation,
}
```

消费方必须忽略未知种类，这条写进协议说明，不依赖实现自觉。

---

## 8. Agent 循环契约（冻结）

```rust
pub struct RunBudget {
    pub max_rounds: u32,        // 默认 16，必须显式，不允许"无上限"
    pub max_tool_calls: u32,    // 默认 64
    pub wall_clock: Duration,   // 默认 30 分钟
}

pub enum RunOutcome {
    Completed { text: String },
    Cancelled,
    WaitingForReconciliation { tool_call_id: String, hint: String },
    NeedsApproval { approval_id: String },
    BudgetExhausted { reason: BudgetReason },
}

pub async fn run_turn(env: &Env<'_>, thread: &ThreadId, budget: RunBudget)
    -> Result<RunOutcome, CoreError>;
```

**必须成立的条件**：
- A1 预算用尽返回 `BudgetExhausted`，不静默继续
- A2 取消后不再开始新的工具调用
- A3 已 `Dispatched` 的工具必须执行完并落库，不能中途丢弃
- A4 `WaitingForReconciliation` 状态下不自动重试，必须等人工
- A5 同一 thread 同时只有一个 run 在执行，其余排队

---

## 9. 平台端口（冻结）

```rust
#[async_trait]
pub trait FileAccess: Send + Sync {
    async fn list(&self, handle: &FileHandle) -> Result<Vec<FileEntry>, CoreError>;
    async fn read(&self, handle: &FileHandle) -> Result<Vec<u8>, CoreError>;
    async fn write(&self, handle: &FileHandle, bytes: &[u8], expect: Option<&ETag>)
        -> Result<ETag, CoreError>;
    async fn delete(&self, handle: &FileHandle, expect: Option<&ETag>) -> Result<(), CoreError>;
}

pub trait SecretStore: Send + Sync {
    fn get(&self, key: &str) -> Result<Option<String>, CoreError>;
    fn set(&self, key: &str, value: &str) -> Result<(), CoreError>;
    fn delete(&self, key: &str) -> Result<(), CoreError>;
}

pub trait Notification: Send + Sync {
    fn notify(&self, kind: NotificationKind, thread: &ThreadId, body: &str);
}

pub trait CommandRunner: Send + Sync {
    /// 不可用返回 UnsupportedCapability，而不是假装成功。
    fn available(&self) -> bool;
    fn run(&self, argv: &[String], timeout: Duration) -> Result<CommandOutput, CoreError>;
}
```

`CommandRunner` 可为 `None`。为 `None` 时相关工具不出现在清单里，而不是存在但报错。

---

## 10. 不变量总表

12 条不变量按本文编号落到具体条件，实现与测试必须逐条对应：

| 不变量 | 落在哪 | 测试条件 |
|---|---|---|
| I1 seq 单调无空洞 | store | S2 |
| I2 命令幂等 | store | S1 |
| I3 副作用前落盘 | store | S3 |
| I4 未知态不重放 | store + agent | S4、A4 |
| I5 审批绑定参数 | store | S5 |
| I6 审批过期不等于同意 | store | S6 |
| I7 同会话排队 | agent | A5 |
| I8 取消边界 | agent | A2、A3 |
| I9 投影可重建 | store | S8 |
| I10 核心不依赖平台 | 构建 | CI 依赖扫描 |
| I11 错误是枚举 | protocol | 编译期穷尽匹配 |
| I12 审批对象一致 | store + tools | S5 |

---

## 11. 这份冻结的风险

1. `Model::stream` 用同步 `sink` 而非 `Stream`，因为核心不需要异步运行时。代价是背压只能靠调用方缓冲。若后续需要背压，需要改签名，属于破坏性变更。
2. `FileHandle::Opaque` 的 `grant_id` 语义未在 Android 上验证，SAF 的持久化授权能否稳定映射到 `grant_id` 未知。
3. `EventKind` 的粒度偏细，可能在高频流式场景产生大量行。是否把 `ModelDelta` 合并落库，留给实现决定，本冻结只要求"确认、审批、工具结果、终态不可合并"。

## 12. 试迁移后的修订记录

冻结草案共两处被实测推翻，已在上文改正：

| 项 | 原写法 | 改正 | 原因 |
|---|---|---|---|
| `ModelRequest.temperature` | `Option<f32>` | `Option<f64>` | f32 序列化成 `0.20000000298023224`，部分 Provider 拒绝 |
| 流式重试 | 未规定 | 已交付增量后禁止重试 | 否则调用方事件流里会出现重复文本 |

一处新增，属于协议性质而非实现缺陷：没有分块编码或 `Content-Length` 时无法检测截断，实现必须如实标注。
