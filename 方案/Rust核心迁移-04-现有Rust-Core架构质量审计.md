# 现有 Rust Core 架构质量审计

对象：`core/runtime-rs` 与 `core/mobile/src-tauri`。
方法：静态依赖分析、契约耦合度测量、接口语义阅读、测试面核对。全部只读。
口径：`runtime-rs/src` 下 26 个模块文件，库代码 31,180 行，测试 2,458 行，合计 33,638 行。

本文不看功能多少，只看结构是否站得住。

---

## 0. 一句话结论

**代码不是一团乱麻，但它没有分层。** 26 个模块之间零循环依赖，扇出最大只有 7，说明没有意大利面条。问题在另一头：它是把 Agent 循环、四个模型协议、两个产品功能、六种扩展、运维工具全部平铺在一个 crate 里，用一个 2,388 行的 `lib.rs` 当公共契约。

这类结构的问题不在于今天读不懂，而在于**明天改不动**。下面每一条都给出可复核的证据。

---

## 1. 判定一：核心不是核心，45% 是产品功能

`lib.rs` 是 33,638 行里的 2,388 行，占 7.7%。剩下九成以上是别的东西。

按模块行数归组：

| 归组 | 行数 | 占比 |
|---|---|---|
| Study 产品域 | 7,972 | 25.6% |
| Workflow 产品域 | 6,071 | 19.5% |
| 模型 Provider | 5,344 | 17.1% |
| 扩展（skills/mcp/hooks/sub_agent/plugin_catalog/plan） | 4,797 | 15.4% |
| 工具 | 3,024 | 9.7% |
| Agent 循环与类型 | 2,388 | 7.7% |
| 上下文压缩 | 683 | 2.2% |
| 运维元数据 | 901 | 2.9% |

明细：`study.rs` 3,607 行、`study_notes.rs` 2,185、`study_exams.rs` 1,955、`study_skills.rs` 225；`workflow_document.rs` 2,435、`workflow_ops.rs` 1,472、`workflow_store.rs` 774、`workflow_runner.rs` 729、`workflow_data_packet.rs` 661。

**后果：** 任何一次 Agent 循环的改动，都要在有 14,043 行产品逻辑的同一次编译单元里验证。改动 Study 也要重跑 Agent 的测试。这不是"功能多"，是"职责没有分开"。

**这条判定为严重。** 因为它直接决定未来维护成本，而维护成本是本次决策的核心指标。

---

## 2. 判定二：公共契约耦合了 60% 的代码

`lib.rs` 一个文件里同时住着 23 个公共类型和循环本身：`AgentRuntime`、`ToolRuntime`、`ToolDefinition`、`ToolPermission`、`RuntimeError`、`Message`、`ToolCall`、`ModelBackend`、`TurnRequest`、`TurnResult`、`TurnContinuation`、`TurnProgress`、`ApprovalRequest`、`ApprovalResponse`、`ApprovalDecision`、`AgentContext`、`DeviceCapabilities`、`GuidanceSource`、`PermissionPreset`、`ModelTurn`、`ImageInput`、`ToolObserver` 等。

实测每个模块对这套契约的引用：

| 模块 | 行数 | 用到的根类型数 |
|---|---|---|
| `sub_agent.rs` | 1,108 | 18 |
| `study.rs` | 3,607 | 10 |
| `compaction.rs` | 683 | 8 |
| `provider.rs` | 4,493 | 8 |
| 六个工具模块（mcp/skills/fetch/web_search/project/plan） | 4,418 | 各 6 |
| `tool_catalog.rs` | 333 | 5 |
| `plugin_catalog.rs` | 474 | 2 |
| `update_manifest.rs` | 388 | 1 |

合计 **26 个模块中有 16 个**、**18,682 行即 59.9% 的代码**直接依赖这个根的公共契约。

**后果：** 契约不能改。哪怕只是把 `RuntimeError` 从字符串换成枚举，也要同时动 16 个模块。这正是我上一轮审计里"改一处牵连一片"的量化证据。

**这条判定为严重。** 而本次改造的核心恰恰是改契约，所以它不是"能不能改"的问题，是"改的时候要牵动多少"的问题。

---

## 3. 判定三：持久化完全不在核心，且调用方被迫当存储

`AgentRuntime` 本身无状态，这是对的。但回合状态放在 `TurnContinuation` 里，由调用方持有。

`lib.rs:558 run_turn_progress` 的输入是 `request.history`，即**历史由外部传进来**。核心把它拼上系统提示词，跑压缩，跑 hooks，然后进 `continue_turn`。中断时返回 `TurnProgress::ApprovalRequired { continuation }`，`lib.rs:659 resume_turn` 再把 continuation 收回来继续。

实测 Rusk 核心内没有任何 `CREATE TABLE`，没有事件序号，没有收据，没有工具阶段。`rusqlite` 在 `Cargo.toml` 里，但只被 `sub_agent.rs` 的存储 trait 和 `study`/`workflow` 用。

对照 Android 宿主：`core/mobile/src-tauri/src/lib.rs:4518` 的状态表是

```sql
CREATE TABLE local_state (id INTEGER PRIMARY KEY, state_json TEXT NOT NULL)
```

即整份 JSON 覆写。分作用域版是 `local_state_scopes` 与 `local_state_active`。

**后果：** 需求里的"断网、杀进程后可恢复"没有结构性保证。整份覆写在写一半时崩溃，恢复出来的是上一个完整快照，中间发生的事全丢。会话越长，覆写越慢，丢失窗口越大。

**这条判定为严重。** 因为它是可靠性要求的根，不是可选项。

---

## 4. 判定四：错误模型无法支撑界面与 CLI 分支

`lib.rs:420` 起：

```rust
pub enum RuntimeError {
    #[error("model error: {0}")] Model(String),
    #[error("tool error: {0}")] Tool(String),
    #[error("tool approval required: {0}")] ApprovalRequired(String),
}
```

三个变体，全部是字符串。没有权限拒绝、没有版本冲突、没有能力不支持、没有结果未知、没有协议不兼容。

**后果：**

1. 界面无法区分"工具被拒绝"和"工具执行失败"，只能匹配字符串或统一显示失败。需求要求"未授权访问全部被拒绝"可验证，字符串错误做不到可验证。
2. CLI 无法给出稳定退出码。而需求明确要求 GUI 领域功能有 CLI 对应。
3. 子代理、MCP、工具三层的失败无法归因，全部塌进 `Tool(String)`。

**这条判定为严重。**

---

## 5. 判定五：审批不绑定参数，也不过期

`lib.rs:1128 approval_request`：

```rust
request_id: format!("{turn_id}:approval:{}:{}:{}", continuation.tool_rounds, continuation.next_call_index, call.id)
```

审批对象只有 `request_id`、`tool_call`、`message` 三个字段。没有参数摘要，没有过期时间，没有设备或工作区标识。

`ApprovalDecision` 只有三个选项：`ApproveOnce`、`ApproveForSession`、`Deny`，外加 `OtherGuidance` 携带的自由文本。

**后果：**

1. 用户看到的是"允许执行 write_file"，核心执行的是另一个同名调用，代码无法识别这不是同一个决定。需求要求审批绑定 `args_digest`，这一条不存在。
2. 审批永不过期。手机端这条尤其危险：用户看到的是二十分钟前的审批卡，点下去执行的是二十分钟前的参数。
3. `ApproveForSession` 按工具名放行，不按参数，等于一次点击放行该工具的全部后续调用。

**这条判定为严重。** 属于安全语义缺失。

---

## 6. 判定六：模型端口不支持流式，流式是外挂

`lib.rs:430`：

```rust
pub trait ModelBackend: Send + Sync {
    async fn complete(&self, model_record_id: &str, messages: &[Message],
        tools: &[ToolDefinition], options: &TurnOptions) -> Result<ModelTurn, RuntimeError>;
}
```

签名是一次性返回。流式是另一个入口：`provider.rs:373 with_stream(...)` 接收一个闭包，在实现内部触发。

**后果：**

1. 核心无法把"流式增量"当成一等事件。它只能在闭包里回调，意味着断言流式行为要绕过核心。
2. 事件顺序无法在核心内保证。设计要求的"流式可合并，但审批与工具结果不能丢"需要核心自己按事件类型决定落库顺序，现在这件事发生在闭包里，核心不知道。
3. 任何新的模型后端要实现流式，只能在 `HttpModelBackend` 里加分支，不能作为独立实现替换。

**这条判定为中等偏严重。** 因为它限制了未来换模型的后端自由度。

---

## 7. 判定七：Provider 一文件四协议一传输

`provider.rs` 4,493 行，114 个函数，公开类型只有 3 个。内部同时存在：

- 传输层：`send_until_headers_with_marker`、`classify_send_result`、`AbortSendOnDrop`、超时与连接失败归因
- 重试策略：`RetryPolicy`、`from_config`、`jitter_factor`、`valid_policy_seconds`
- 四种线上协议：OpenAI Chat（`openai_body`）、OpenAI Responses（`responses_body`）、Gemini（`gemini_body`）、Anthropic（`anthropic_body`），配套四个解析器 `parse_openai`、`parse_responses`、`parse_gemini`、`parse_anthropic`
- 两套流读取：`read_openai_stream` 与 `read_native_stream`，加 SSE 帧边界 `sse_frame_boundary`
- 图片编码与尺寸校验：`validate_model_images`、`checked_base64_size`、`openai_image_data_url`
- 推理参数映射：`apply_configured_reasoning`、`enforce_anthropic_thinking_limits`

**后果：** 增加第五个 Provider 要改这个 4,493 行的文件，改动风险与四种协议共享。测试面虽然有 41 个内联测试，但都在同一个编译单元里，一个协议改坏很难靠测试切分定位。

**这条判定为中等。** 它是有价值的资产，但形态不适合长期扩展。

---

## 8. 判定八：扩展机制靠单点扇出，子代理直连具体实现

`tool_catalog.rs` 是全仓扇出最高的模块，7 条边，指向 `fetch_tools`、`image_gen`、`project_tools`、`skills`、`study`、`sub_agent`、`web_search`。新增一个工具就要改这个汇总点，而且它会连带把 Study 拉进来。

`sub_agent.rs:455` 直接构造具体实现：

```rust
let model: Arc<dyn ModelBackend> = Arc::new(
    HttpModelBackend::new(model_entry.provider).map_err(|error| error.to_string())?,
);
...
let runtime = AgentRuntime::new(model, tools).with_guidance_source(...)
```

**后果：**

1. 子代理无法用假模型测试。要测子代理编排，必须构造 `HttpModelBackend`，只能靠打桩 HTTP。
2. 换模型后端时子代理不同步，因为它是硬编码的。
3. 扩展是"核心里的一个 static 列表"，不是"外围注册进来的能力"。这与目标架构里"扩展独立 crate"的方向相反。

**这条判定为中等偏严重。**

---

## 9. 判定九：跨平台隔离基本做到了，但有一处漏和一处渗

好的部分：`runtime-rs` 对 `jni` 的引用为 0，`tauri` 只出现 1 次（`update_manifest.rs`），绝对 Windows 路径为 0。这说明核心大体上真的与平台解耦，这是它最值得肯定的一点。

坏的部分：**Python 源码树渗入 5 个文件共 33 处**。

| 文件 | 次数 |
|---|---|
| `study_skills.rs` | 19 |
| `plugin_catalog.rs` | 8 |
| `study.rs` | 3 |
| `skills.rs` | 2 |
| 其余 | 1 |

`plugin_catalog.rs:31-68` 用 `include_str!` 硬编码 8 个 Python 插件文件路径。上游提交 `103065a8` 删除 `git` 插件后，`cargo check` 直接失败：

```
error: couldn't read `src\../../src/lamtools_core/plugins/bundled/git/plugin.json`
  --> src\plugin_catalog.rs:31:9
```

**后果：** 这不是一个可以顺手修的小 bug，它是结构信号。共享核心在构建期依赖另一门语言的源码树，说明"共享"是名义上的，两边没有独立演化能力。任何一侧删文件都会打断另一侧的构建。

**这条判定为严重。** 因为它证明当前结构无法支撑"长期双端独立演进"。

---

## 10. 判定十：测试面看着不小，但没有一条覆盖关键语义

实测测试数量：

| 位置 | 数量 |
|---|---|
| 各模块内联 `#[test]` / `#[tokio::test]` | 191 |
| `tests/` 集成测试 | 55 |
| 合计 | 246 |

分布很集中：`provider` 41、`study` 域集成 45、其余多在 4 到 9 之间。

关键语义的覆盖情况：

| 关键语义 | 是否有测试 | 说明 |
|---|---|---|
| 命令幂等 | 无 | 因为没有收据概念 |
| 事件序号单调 | 无 | 因为没有事件日志 |
| 工具结果未知态 | 无 | 因为状态机没有该阶段 |
| 审批参数绑定 | 无 | 因为不存参数摘要 |
| 审批过期 | 无 | 因为没有过期字段 |
| 同会话排队 | 无 | 因为只有拒绝没有队列 |
| 崩溃恢复 | 无 | 恢复逻辑不在核心 |
| 模型后端可替换 | 无 | 子代理直连 `HttpModelBackend` |

**后果：** 246 个测试证明的是"已经实现的行为没坏"，不能证明"可靠性要求成立"。这两件事必须分开看，否则会把测试数量当成可靠性证据。

**这条判定为严重。** 因为本次验收标准里最硬的那几条，恰好全在无覆盖区。

---

## 11. 判定十一：Android 宿主是另一个巨型单文件

`core/mobile/src-tauri/src/lib.rs` 4,990 行，56 个 Tauri 命令，命令体内合计 4,525 行。按首段分组：

| 组 | 行数 |
|---|---|
| `sunday_skill_*` | 1,338 |
| `sunday_agent_*` | 684 |
| `sunday_study_*` | 428 |
| `sunday_update_*` | 395 |
| `sunday_open_*` | 289 |
| `sunday_sub_*` | 198 |
| `local_state_*` | 182 |
| `project_file_*` | 143 |
| `sunday_attachment_*` | 123 |
| `sunday_artifact_*` | 112 |
| `secure_storage_*` | 112 |
| `project_directory_*` | 77 |

**后果：** 真正的 Agent 入口只占 684 行，而 Skills 编辑占 1,338 行。这说明宿主层也没有分层：产品功能、平台适配、Agent 调用、更新器全在一个文件里。任何一条路线都必须重写这层，但好消息是 Agent 命令面很小，重写代价低。

**这条判定为中等。** 因为它的替换成本低于核心。

---

## 12. 度量汇总

| 指标 | 实测值 | 判断 |
|---|---|---|
| 模块数 | 26 | 尚可 |
| 循环依赖 | 2 环 0 个，3 环 0 个 | 合格 |
| 最大扇出 | 7（`tool_catalog`） | 尚可，但它是扩展瓶颈 |
| 最大扇入 | 3（`workflow_document`） | 合格 |
| 根契约耦合 | 16/26 模块，18,682 行，59.9% | 不合格 |
| 产品域占比 | 14,043 行，45.0% | 不合格 |
| 核心自身占比 | 2,388 行，7.7% | 不合格 |
| 外部语言耦合 | 33 处 Python 路径 | 不合格 |
| 平台耦合 | jni 0，tauri 1 | 合格 |
| 错误模型 | 3 个字符串变体 | 不合格 |
| 持久化 | 核心内无 | 不合格 |
| 关键语义测试 | 8 项全部无覆盖 | 不合格 |

---

## 13. 结论：哪些是可抢救的零件

> **本节的行数口径已更正，见 `方案/Rust核心迁移-08-第一批验证报告.md` 第 1.5 节。**
> 本节用的是含内联测试的行数，分类比例失真。按生产代码重算的结果是：A 类 9,296 行占 38.2%，B 类 12,902 行占 53.1%，C 类 2,116 行占 8.7%。
> 三个类别的归属与理由不变，只是行数与占比要用 08 号报告的数字。

按"脱离这份契约后还能不能用"分类，三类：

**A 类，可原样搬走（10,297 行，33.0%）。** 完全不引用根契约，或只引用领域内类型。搬走不需要改。

`hooks.rs` 923、`profiles.rs` 851、`forensics.rs` 513、`study_exams.rs` 1,955、`study_notes.rs` 2,185、`workflow_document.rs` 2,435、`workflow_store.rs` 774、`workflow_data_packet.rs` 661。

其中只有 `hooks`、`profiles`、`forensics` 共 2,287 行属于核心外围，其余 8,010 行是产品域，本来就不该住在核心。

**B 类，改契约后可复用（17,300 行，55.5%）。** 逻辑有价值，但要按新契约改签名。

`provider.rs` 4,493、`study.rs` 3,607、`workflow_ops.rs` 1,472、`sub_agent.rs` 1,108、`web_search.rs` 897、`project_tools.rs` 852、`skills.rs` 811、`mcp.rs` 796、`workflow_runner.rs` 729、`plan_tools.rs` 685、`compaction.rs` 683、`image_gen.rs` 565、`fetch_tools.rs` 377、`study_skills.rs` 225。

**C 类，必须重写（3,583 行，11.5%）。** 结构本身就不对，留着只会拖累新结构。

`lib.rs` 2,388（契约加循环，必须换）、`plugin_catalog.rs` 474（Python 路径硬编码）、`update_manifest.rs` 388（平台渗入）、`tool_catalog.rs` 333（单点扇出）。

三类合计 10,297 加 17,300 加 3,583 等于 31,180，与库代码总量一致，无重复计入。

`sub_agent.rs` 需要特别说明：它在逻辑上属于 B 类，值得保留编排逻辑，但它 `sub_agent.rs:455` 硬编码了 `HttpModelBackend`，属于必须动手术的地方。改造时它要改成接收注入的模型工厂，而不是自己造模型。

**这个分类是后面路线对比的基础。** 注意 B 类的 17,300 行不等于"省下 17,300 行的工作量"，改动签名本身有成本，只是比从零写省。按经验，改签名的成本约为重写的三分之一到二分之一。这个系数没有实测，属于估计，置信度标注为中等。
