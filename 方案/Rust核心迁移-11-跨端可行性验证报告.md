# Rust 核心迁移 11：跨端可行性验证报告

日期：2026-11-03
分支：`sunday/m3-isolated-core`
远端提交：`608d207a`（代码提交 `022851a6`，父提交 `db75b8bc`）
未合入主干，未切换正式后端。

---

## 一句话结论

新 Rust Core 已经在**真实模型**、**真实前端客户端**、**Android 模拟器**三条链路上真实跑通，单写者锁在两大平台上真实生效。功能数量没有扩张，本轮新增代码几乎全是把已有能力接到真实外部世界所需的端口和适配。

但仍有两处必须诚实标注：**没有 Android 真机**（只有模拟器），**没有接入任何外部云厂商的真实端点**（用的是本机 Ollama 提供的 OpenAI 兼容端点）。

---

## 一、本轮实际验证了什么

### 1.1 真实模型闭环

模型来源：本机 Ollama，`qwen2.5:3b`，走 OpenAI 兼容端点 `http://127.0.0.1:11434/v1`。
这不是脚本模型，每一次都是真实的 HTTP 流式请求。

测试文件：`core/sunday-core/crates/sunday-llm/tests/real_provider.rs`

| 验证点 | 结果 | 实测数字 |
|---|---|---|
| 流式分片 | 通过 | 50 个分片，首个分片 73ms 到达 |
| 真实工具调用解析 | 通过 | 模型自主返回 `write_file`，`{path: "out.txt", content: "hello"}` |
| 多步工具往返 | 通过 | 工具结果 "42" 被模型正确用于回答 |
| 坏模型名快速失败 | 通过 | 1.9ms 失败，未重试 4xx |
| 不可达端点不挂起 | 通过 | 6.8s 内失败返回，未无限重试 |
| 单轮耗时与用量 | 通过 | 80ms，`input_tokens: 35, output_tokens: 2` |
| 取消语义 | 通过（记录限制） | 模型调用本身不可中断，取消只在循环层生效 |

最后一项是本轮主动记录的一个**真实能力缺口**：`LlmClient::stream` 没有取消令牌，一旦发出请求就会读到流结束。这不是被掩盖的问题，测试里明确打印了"the model call completed anyway (363 chars), so cancellation is at the loop level only"。

### 1.2 协议适配：真实前端驱动真实 Core

这是本轮最关键的一步。不是模拟客户端，而是直接 import 桌面端正在使用的 `CoreAppServerClient` 和 `DirectTransport`（`core/ui/src/appServer/client.ts`、`core/ui/src/transport/directTransport.ts`），连到真实的 Rust Core 进程。

测试文件：`core/ui/tests/rust-core-contract.test.ts`

| 验证点 | 结果 |
|---|---|
| initialize 握手与能力声明 | 通过 |
| 真实模型回合，流式事件到达 | 通过 |
| 真实审批卡 + 批准后真实写文件 | 通过，文件内容确认为 `hello` |
| 断线重连后日志重放一致 | 通过，序号完全对齐 |
| 同一数据目录拒绝第二个写者 | 通过，报错含 "another core" |

**过程中发现并修复的真实协议不一致（这些如果只写测试不跑真实前端，会全部漏掉）：**

1. `initialize` 的参数是驼峰 `threadId`，不是 `thread_id`。原实现只读蛇形，重连时会丢掉会话。
2. `approval/respond` 发送的是 `request_id` + `decision`，不是 `approval_id` + `approve`。
   真实取值是 `approve|deny|guide|skip|trust`，还带 `approve_once` / `other_guidance` 等别名。
3. 核心日志里写的是 `approval_id`，而 UI 读的是 `payload.request_id`。
   不补这个映射，审批卡会渲染出来但没有 id，用户点了也没法提交。
4. `turn/accepted` 原先用伪造序号（`1000000 + n`），与真实日志序号冲突，UI 会乱序。
   改为先写入真实日志再读出来发，序号自然单调。

还顺手修掉一个可用性缺陷：回合原先在读取循环里同步执行，导致 `turn/cancel` 会卡在 socket 里，等回合结束才被读到——也就是用户按下"停止"时它已经没用了。改为回合在独立线程运行后，取消能在流式输出期间立即响应，这一点有专门的测试 `a_cancel_is_answered_while_a_slow_turn_is_still_running`。

### 1.3 单写者锁

测试文件：`core/sunday-core/crates/sunday-host/src/lock.rs`（单元测试）+ 真实前端契约测试中的跨进程用例。

| 验证点 | 结果 |
|---|---|
| 第二个写者被拒并报出持有者 | 通过 |
| 释放后下一个写者能进来 | 通过 |
| 心跳停止后按窗口回收 | 通过 |
| 迟到的 drop 不会误删别人的锁 | 通过 |
| 杀进程后回收（真实子进程 kill） | 通过 |
| 损坏的锁文件被视为占用 | 通过（修复后） |
| Windows 上第二写者被拒 | 通过 |
| **Android 上第二写者被拒** | 通过 |

**修掉的两个真实缺陷：**

1. 无法解析的锁文件曾被当成"过期锁"立刻抢占（`age = u64::MAX`）。这意味着一次写坏的文件就能让两个核心同时写同一个数据库——正是这个锁存在的唯一目的被绕过。改为按文件 mtime 降级判断：活着的心跳会不断改写文件，mtime 就是真实信号。
2. 杀进程测试的子进程过滤名少了模块路径（写成 `lock_child_helper` 而非 `lock::tests::lock_child_helper`），子进程从未真正获取锁，那条测试此前一直"通过"但什么都没验证。修正后补上了"回收窗口内不得抢占"的断言。

### 1.4 Android（模拟器，非真机）

环境：`android-36`、`google_apis`、`x86_64` 系统镜像，NDK `30.0.14904198`，target `x86_64-linux-android`。
启动命令：`emulator -avd sunday_test -no-window -no-audio -no-snapshot -gpu swiftshader_indirect`。

| 验证点 | 结果 | 证据 |
|---|---|---|
| 交叉编译 | 通过 | `target/x86_64-linux-android/debug/sunday`，84MB |
| 二进制在设备上运行 | 通过 | `health` 返回 `ok core=0.1.0 protocol=sunday.core.v1` |
| 本机 SQLite | 通过 | `store selftest` 四项全过（幂等、序号连续、未知不重放、投影重建） |
| 本机文件写入 | 通过 | `ui-check.txt` 内容为 `hello` |
| 网络 | 通过 | 经 `10.0.2.2` 访问宿主机模型，真实回合完成 |
| 单写者锁 | 通过 | 第二写者被拒，退出码 10 |
| 协议端口 | 通过 | `ws://127.0.0.1:18800` 完成 WebSocket 握手（101） |

**实际做到了什么程度：** 用真实前端客户端通过 `adb forward` 连接到运行在模拟器里的 Rust Core，跑完了一整轮真实模型对话和一次真实审批写文件。也就是说"同一个 Rust Core 在 Android 上工作"是被真实执行验证过的，不是交叉编译通过就算。

**明确没有做到的：**
- **没有真机。** `adb devices` 始终只有模拟器。真机上的 ABI、内存压力、后台被杀、真实网络切换全部未验证。
- **没有 Tauri Android 宿主。** 本轮验证的是 Core 本体在 Android 上能跑，不是打包成 APK 的桌面应用能跑。Tauri 壳、SAF 授权模型、Android 生命周期回调都还没接。
- **数据库路径是 `/data/local/tmp`**，这是调试目录，不是应用的私有沙箱目录。权限模型未在真实应用沙箱下验证。

### 1.5 压缩质量

新增 `core/sunday-core/crates/sunday-context/tests/compaction_quality.rs`，用真实模型做摘要器。

实测：23 条消息 → 5 条，约 519 tokens → 约 110 tokens，压缩比约 4.7:1。

**发现一个真实质量缺陷：** 摘要保留了数字约束（"30 seconds"、"500"），但把根因（"splits on every comma"）丢了。也就是说摘要倾向于保留显眼的数字，丢掉解释性的因果。这在长任务里会导致后续步骤不知道"为什么"要改。

这不是实现 bug，是摘要提示词的设计不足。测试把两条保证分开断言（摘要内的事实 vs 被钉住的任务陈述），就是为了不让其中一条掩盖另一条。

### 1.6 容量与写放大

新增 `core/sunday-core/crates/sunday-store/tests/volume.rs`，全部为实测数字。

| 场景 | 实测 |
|---|---|
| 1 万条小事件追加 | 20.24s，约 2024 µs/条 |
| 1 万条全量重放 | 31.8ms |
| 读取尾部 10 条 | 1.12ms（不随总量线性增长，符合预期） |
| 100 条 × 100KB 大事件 | 431ms 写入，57ms 重放 |
| 1 万条分布在 200 个会话 | 单会话 50 条读取 775µs |
| 写放大 | 约 4291 字节/事件（载荷仅 70 字节） |

**这两个数字需要正视：**

- **2024 µs/事件偏慢。** 根因是 `synchronous=FULL`，每条事件一个事务一次 fsync。这是耐久性换性能的取舍，不是缺陷，但在真实交互里意味着每轮对话的日志写入有明显延迟。如果要提速，正确做法是批量提交或降级到 `NORMAL`，代价是崩溃时可能丢最后若干条事件——这是产品决策，我不擅自改。
- **4291 字节/事件是真问题。** 载荷 70 字节却写 4KB+，主要来自每次事件都重写整个投影行（`thread_projection` 存的是完整 JSON）。事件越多投影越复杂，写放大越严重。这是架构级的低效，应当单独修：投影应改为增量更新，或按需重建。

---

## 二、架构变化

新增第 10 个 crate：`sunday-host`（组合层，1011 行）。

职责只有两件，且都明确不属于 agent / store / platform：
1. 单写者锁
2. `core.app_server.v1` 适配器

依赖方向由 `scripts/check-deps.py` 强制，本轮一并修正了该脚本的一个盲区：它原先不区分生产依赖和测试依赖，导致测试用一个下层 crate 就会被判违规。现改为只对 `[dependencies]` 强制，`[dev-dependencies]` 照常打印留痕。

**负向验证：** 把 `sunday-context` 的 `[dev-dependencies]` 改成 `[dependencies]`，脚本立刻报错退出 1；改回后恢复 `ok 10 crates`。闸门没有因为放宽而失效。

### 生产代码行数

| crate | 行数 | 变化 |
|---|---|---|
| sunday-agent | 629 | 无变化（**这是重点：没有因为加协议适配而变胖**） |
| sunday-store | 1304 | 无变化 |
| sunday-protocol | 706 | 无变化 |
| sunday-context | 363 | 无变化 |
| sunday-llm | 1266 | 无变化 |
| sunday-tools | 568 | 无变化 |
| sunday-platform | 541 | 无变化 |
| sunday-extensions | 224 | 无变化 |
| sunday-host | 1011 | **新增** |
| sunday-cli | 1196 | +504（新增 `serve` 命令） |
| 合计 | 7808 | 生产代码 |
| 测试代码 | 4342 | — |

`sunday-agent` 一行没涨，说明"组合层独立"不是口号：协议适配、锁、宿主装配全部落在 agent 之外。

---

## 三、测试与 CI

### 本地闸门（全部真实执行）

```
cargo fmt --all -- --check         干净
cargo clippy --workspace --all-targets -- -D warnings    0 错误
python scripts/check-deps.py       ok 10 crates
cargo test --workspace             149 passed / 0 failed / 19 ignored
```

19 个 ignored 全部是需要真实外部环境的：7 个真实 Provider、4 个压缩质量、4 个容量测量、3 个既有夹具、1 个子进程辅助。它们默认跳过，是因为在 CI 里没有模型服务时空转通过比不测更糟；每个都写了"没有服务就必须失败"的守卫（`require_server`）。

真实环境下这 15 个（7+4+4）都已单独跑过并通过，数字见上文。

### 远端 CI

| 运行 | 提交 | 结果 |
|---|---|---|
| 41596588867 | 022851a6 | **四项全部成功** |

明细（真实 GitHub Actions 结果，非预估）：

| 作业 | 结果 |
|---|---|
| windows build and tests | 成功 |
| linux build and tests | 成功 |
| android target check | 成功 |
| dependency rules | 成功 |

其中 `android target check` 是关键：它证明 Android 目标在干净环境里也能编译，不依赖我这台机器的缓存状态。

### 数据安全

`data/core.db` 全程未被读写。会话前后实测一致：

- 大小 `3676884992` 字节
- mtime `1793633617`（会话开始前）

所有测试使用 `tempfile` 临时目录或 `core/sunday-core/.tmp/`（已被 `.gitignore` 排除）。

---

## 四、当前架构缺陷（如实列出）

按严重程度排序：

1. **投影全量重写导致写放大（4291 字节/事件）。** 每条事件都把整个 `thread_projection` JSON 读出来、改一个计数、再写回去。事件越多越慢。这是真实的架构低效，应改为增量更新。

2. **摘要丢因果、留数字。** 压缩摘要倾向于保留显眼数字，丢掉解释性原因。根因是摘要提示词只说了"保留事实"，没说"保留为什么"。

3. **模型调用不可中断。** `LlmClient::stream` 没有取消令牌，取消只在循环层检查。用户按停止后，网络请求仍会读到流结束并计费。

4. **事件表只增不减。** 没有归档、没有分片、没有保留策略。长期使用会无限增长。

5. **Android 只在调试目录验证过。** `/data/local/tmp` 不是应用沙箱，SAF 授权模型完全没接。

6. **单写者锁是心跳式，不是操作系统咨询锁。** 崩溃后有回收窗口，且"接管一个还活着但卡死的写者"是不可撤销的操作。这个取舍已写进代码注释，但在真实产品里需要一个更明确的用户决策点（比如"检测到另一个核心，是否强制接管"）。

7. **`sunday-host` 已有 1011 行。** 目前职责清晰（锁 + 协议），但如果把 Iroh P2P、MCP、Skills 都往这里塞，会重演 `sunday-agent` 变胖的老问题。建议：MCP 独立 crate，Iroh 独立 crate，host 只做装配。

---

## 五、剩余迁移成本

只算硬骨头，不算机械搬运：

| 项目 | 说明 |
|---|---|
| 协议覆盖面 | 目前只实现 UI 打开会话、跑回合、审批、取消。配额、产物、队列、历史分页、命令目录、辅助对话全部返回 METHOD_NOT_FOUND。这是最大的一块。 |
| 产品域迁移 | Study、Workflow、插件系统全部未动。 |
| Tauri Android 宿主 | 完全没有。壳、SAF、生命周期、后台策略。 |
| Iroh P2P | 按用户要求只做规划，不开发。 |
| 真机验证 | 无设备。 |
| 压缩与检索 | 摘要质量、长期记忆、检索召回都未评估。 |
| Windows 接管 | 双写校验、灰度、回滚演练全部未做。 |

---

## 六、下一步建议

1. **先修写放大**，因为它是唯一一个会随使用时间恶化的架构问题，且修它不需要改产品行为。
2. **补协议覆盖面**，让真实 UI 能完整使用，否则"能连上"和"能用"之间还有很大距离。
3. **模型调用加取消令牌**，这是用户体验和成本的直接问题。
4. **拿到真机后再谈 Android 接管**，模拟器只能证明代码能跑。
5. **MCP 与 Skills 严格按用户要求分 crate**，不要塞进 host 或 agent。

不建议现在做 Windows 正式接管。理由：协议覆盖不到一半，接管后用户会发现大量功能不可用。

---

## 七、本轮文件清单

新增：
- `core/sunday-core/crates/sunday-host/`（`Cargo.toml`、`src/lib.rs`、`src/lock.rs`、`src/app_server.rs`、`tests/app_server_contract.rs`）
- `core/sunday-core/crates/sunday-cli/src/serve.rs`
- `core/sunday-core/crates/sunday-llm/tests/real_provider.rs`
- `core/sunday-core/crates/sunday-context/tests/compaction_quality.rs`
- `core/sunday-core/crates/sunday-store/tests/volume.rs`
- `core/ui/tests/rust-core-contract.test.ts`

修改：
- `core/sunday-core/Cargo.toml`（注册第 10 个 crate）
- `core/sunday-core/crates/sunday-cli/Cargo.toml`、`src/main.rs`（新增 `serve`）
- `core/sunday-core/crates/sunday-context/Cargo.toml`（测试依赖）
- `core/sunday-core/scripts/check-deps.py`（区分生产/测试依赖）

未触碰：
- `data/core.db`（真实用户库，本轮全程未读未写）
- `core/src/`（旧 Python 实现）
- 正式后端切换
