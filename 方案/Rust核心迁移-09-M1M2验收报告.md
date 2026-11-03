# M1 与 M2 验收报告

路线 C，第一批执行结果。日期 2026-11-02。
M1 与 M2 已完成并通过全部本地闸门。M3 未开始，等批准。

所有数字都是本机实测，可复算。复算方式见第 8 节。

---

## 1. 实际目录与依赖关系

```
core/sunday-core/
  Cargo.toml                        worktree 定义
  README.md                         职责、规则、运行方式、回滚
  docs/behavior-parity.md           与 Python 的行为对照
  scripts/check-deps.py             依赖规则扫描，CI 与本地共用
  crates/
    sunday-protocol/                579 生产行
    sunday-store/                 1,016 生产行
    sunday-platform/                242 生产行
    sunday-llm/                     896 生产行
    sunday-agent/                   548 生产行
    sunday-tools/                   348 生产行
    sunday-cli/                     248 生产行
```

依赖方向，由脚本强制：

```
protocol   (无内部依赖)
   ↑
   ├── store      → protocol, SQLite
   ├── platform   → protocol
   ├── llm        → protocol
   ├── tools      → protocol, platform
   └── agent      → protocol, store
        ↑
      cli → 以上全部
```

直接依赖数：protocol 4、store 6、platform 7、llm 7、agent 8、tools 9、cli 6。

**规则检查结果：`ok 7 crates, edges and tokens clean`。**

不止是文档。我做了负向验证：给 store 加一条指向 agent 的依赖，脚本立即报错退出 1：

```
FAIL sunday-store: depends on ['sunday-agent'] but only ['sunday-protocol'] is allowed
```

恢复后重新通过。所以这条规则真的会拦住人。

禁止项同样可执行：核心 crate 的 `src/` 里不得出现 `tauri`、`jni`、`lamtools_core`、`pyo3`、`std::process::Command`。`tests/` 允许起进程，因为故障注入必须杀掉一个子进程，这条豁免在脚本里写明理由。

---

## 2. 已实现与未实现

### 已实现

| 能力 | 位置 |
|---|---|
| 冻结类型、11 个类型化错误、稳定退出码、事件种类、工具与模型端口 | `sunday-protocol` |
| 事件日志，thread 内 seq 连续 | `sunday-store` |
| 命令收据与幂等，同 id 不同体重发被拒 | `sunday-store` |
| 工具阶段机：prepared → approved → dispatched → succeeded/failed/unknown | `sunday-store` |
| 审批绑定参数摘要、必须过期、只能用一次 | `sunday-store` |
| 续跑状态持久化，审批后不需要重新问模型 | `sunday-store` |
| 投影增量维护与从日志重建 | `sunday-store` |
| 崩溃恢复：非幂等未完成标为 unknown，不自动重放 | `sunday-store` |
| 只读打开，检查命令永不写入 | `sunday-store` |
| schema 版本守卫，新版本库拒绝降级 | `sunday-store` |
| 回合循环：预算、取消、审批移交、工具编排 | `sunday-agent` |
| 每 thread 一条 run，其余排队而不是拒绝 | `sunday-agent` |
| 文件与密钥端口，路径逃逸防护，原子写，比较交换 | `sunday-platform` |
| OpenAI Chat 与 Anthropic Messages 的流式、重试、类型化失败 | `sunday-llm` |
| 三个工具：web_fetch、read_file、write_file | `sunday-tools` |
| CLI：health、db inspect、journal tail、store selftest | `sunday-cli` |

### 未实现，且是有意留空

| 未做 | 原因 |
|---|---|
| 不使用模型的 turn 命令 | M3 才有端到端回合，现在做等于没有验收标准 |
| `core.app_server.v1` 协议适配 | M3，需要与现有前端对齐 |
| 用户插话（guidance）三段式 | M3，需要回合协议一起做 |
| 上下文压缩 | 移植 `context_compaction/`，M3 之后 |
| 子代理、MCP、Skills | M4 |
| 权限层，含敏感路径黑名单 | M3。目前有对照测试把这个缺口钉住 |
| Windows 与 Android 宿主、SAF、通知 | M4 |

---

## 3. 测试结果与故障注入

### 3.1 闸门

| 闸门 | 命令 | 结果 |
|---|---|---|
| 格式 | `cargo fmt --all -- --check` | 通过 |
| 静态检查 | `cargo clippy --workspace --all-targets -- -D warnings` | 0 错误 |
| 依赖规则 | `python scripts/check-deps.py` | 通过，且负向验证有效 |
| 测试 | `cargo test --workspace` | 97 个通过，0 失败 |

### 3.2 测试分布

| crate | 测试数 |
|---|---|
| protocol | 5 |
| store | 22 加 3 个被主测试拉起的子进程夹具 |
| platform | 10 |
| llm | 34 |
| agent | 11 |
| tools | 15 |
| 合计 | 97 加 3 |

S1 到 S8 八条全部有对应测试，逐条对应关系写在 `README.md` 的表里。

### 3.3 故障注入记录

全部使用真实 SQLite 文件、真实事务。没有内存 Mock。

| 编号 | 注入方式 | 期望 | 结果 |
|---|---|---|---|
| K1 | 子进程在 `mark_dispatched` 后 `abort()` | 重启后该调用为 unknown，再准备返回必须人工核对 | 通过 |
| K2 | 子进程开 `BEGIN IMMEDIATE`、插入一行、未提交就 `abort()` | 该行不存在；seq 从最后一次提交继续，不跳号 | 通过 |
| K3 | `recover()` 连跑两次 | 第二次是空操作 | 通过 |
| K4 | `accept_command` 后进程死亡 | 收据被标为 failed，进入 abandoned 列表 | 通过 |
| K5 | 只读检查前后比较文件大小 | 文件不增长 | 通过 |
| K6 | 把 schema_version 改成 99 | 拒绝打开，返回 ProtocolIncompatible | 通过 |
| C1 | 期望版本过期 | 返回 RevisionConflict，带实际版本 | 通过 |
| C2 | 两个进程各写 20 条事件 | seq 连续 1 到 40，无丢失无重复 | 通过 |
| S5 | 用另一个参数摘要去花审批 | 拒绝，且审批仍是 pending，没被消耗 | 通过 |
| S6 | 超过过期时间提交 | 拒绝，且状态落库为 expired，重启后仍拒绝 | 通过 |
| S7 | 同一审批用两次 | 第二次拒绝 | 通过 |
| A2 | 取消后再跑回合 | 工具一次都没执行 | 通过 |
| A4 | 上次已派发未完成，这次模型又要求同一调用 | 停下等核对，工具不执行 | 通过 |
| B1 | 续跑时提交被篡改的参数摘要 | 拒绝，工具不执行 | 通过 |

### 3.4 本轮发现的真实缺陷

要求记录真实缺陷、影响范围与结果，这里逐条列。

| 编号 | 缺陷 | 怎么发现的 | 影响范围 | 处理 |
|---|---|---|---|---|
| D1 | `ToolPrepared` 事件从未发出。代码只在审批分支准备了调用，两条路径都没落这个事件 | 契约测试断言完整事件序列时失败 | 1 个函数，`sunday-agent/src/lib.rs` | 两条路径各补一次 emit，12 行 |
| D2 | 审批通过后续跑又弹一次审批，导致循环 | 审批续跑测试报 `approval requested after approval` | 1 个函数加 2 处调用点 | 加 `pre_approved` 参数，共 8 行 |
| D3 | 我自己的契约测试断言写错，把 2 个事件写成 3 个 | S8 测试失败 | 测试文件 1 行 | 改正 |
| D4 | 依赖扫描器把故障注入测试误判为违规 | 首次运行报错 | 扫描器 1 处 | 规则改为只约束 `src/`，并在脚本里写明原因 |
| D5 | 移植模型层时我把字节串转义写坏，mock 服务器认不出请求头结束，整套测试挂住 | 测试运行 900 秒超时 | 测试夹具 1 处 | 改成数值常量 `[0x0d,0x0a,0x0d,0x0a]`，不再依赖转义 |

D1 与 D2 是真正的产品缺陷，都是靠“断言事件序列”和“断言续跑行为”发现的，不是靠编译。D5 说明一件事：**测试夹具本身也会挂，超时阈值是必要的护栏**。

---

## 4. 相比原型增加的复杂度及原因

原型是 `.tmp/migration-trial` 里的参考实现：793 行生产代码，10 个测试，覆盖协议、存储、循环三件事，全在一个文件里。

现在这三件事分别是 579 加 1,016 加 548，共 2,143 行，41 个测试。加 1,350 行，约 170%。

多出来的部分，按原因归：

| 原因 | 大致增量 | 说明 |
|---|---|---|
| 续跑状态与审批后恢复 | 约 270 | 原型只做到“返回需要审批”，没有续跑。要保证不重新问模型，必须持久化消息与待执行的调用 |
| 投影增量维护与重建 | 约 150 | 原型没有投影。S8 要求从日志重建并与增量一致 |
| schema 版本、迁移守卫、只读打开 | 约 90 | 原型直接用 `open`，没有版本概念，也没有“检查不得写入”的约束 |
| 主机过滤的工具可见性与权限字段 | 约 90 | 原型工具没有 hosts 与 permission |
| 错误集扩到 11 个加退出码映射 | 约 60 | 原型有 11 个变体但没有退出码与可重试判定 |
| 分轮事件、工具批处理、预算拆分 | 约 150 | 原型只按轮数记事件，没有工具调用预算 |
| 其余（Debug、校验、格式化） | 约 50 | |

这些增量是估计，总行数是实测。**加得最多的是“续跑”和“投影”这两件原型压根没做的事**，而不是抽象膨胀。

整个工作区 3,877 行生产代码里，还有 896 行模型层、348 行工具、242 行平台、248 行 CLI，这些在原型里没有对应物。

### 4.1 顺手得到的一个实测数据

把模型层从试迁移目录搬到正式工作区，896 行生产代码，只改了 3 处 clippy 风格问题，逻辑零改动，一次编译通过，34 个测试直接沿用。

这验证了成本模型里“搬走已验证代码系数约 0.05”这条估计。之前是猜的，现在有一个真实样本。

---

## 5. 与 Python Core 的行为差异

完整表格在 `core/sunday-core/docs/behavior-parity.md`，分三类。

**一致的，带测试**：路径不能逃逸工作区、写入不会留半截文件、文件被改过就不覆盖、HTML 提取正文并丢弃脚本样式、非绝对 URL 先拒绝、截断会告知模型。

**有意做得不同**：

| 项 | Python | 新核心 | 理由 |
|---|---|---|---|
| 最大轮数 | 无上限 | 预算 16 轮 | 无上限不可预算 |
| 审批过期 | 永不超时 | 必须设 TTL，0 被拒 | 手机上的审批卡可能挂几小时，同意必须绑定当时的判断 |
| 审批范围 | 按工具名，会话级放行 | 绑定参数摘要，只能用一次 | 用户同意的是具体参数 |
| 同 thread 并发 | 拒绝第二个 | 第二个排队 | 手机连点两次不该报错 |
| 错误 | 3 个字符串变体 | 11 个类型化变体加退出码 | 界面与 CLI 都要能分支 |

**已知缺口，写进文档而不是藏起来**：敏感路径（`.env`、`.ssh/`、`id_rsa`）目前没拦；插话、压缩、子代理、MCP、Skills 未实现；协议兼容未做。敏感路径这条有一个测试**故意断言缺口存在**，等权限层补上时再翻转断言，这样它不会被忘掉。

---

## 6. 下一阶段接入方案

M3 的目标是“端到端回合跑通”，不碰用户数据，不切换生产核心。

1. **协议适配层**：把 `sunday.core.v1` 命令与事件映射到 `core.app_server.v1` 的方法与通知，先覆盖 `thread/*`、`turn/*`、`approval/respond`、`session/*`。这是让现有前端不改一行就能连上新核心的唯一途径。
2. **模型接入**：`sunday-llm` 已经就位，只差把配置里的 Provider 映射成 `ProviderConfig`，密钥走 `SecretStore`。
3. **回合命令**：`sunday-cli turn --workspace <p> --prompt <text>`，在隔离 Profile 里跑真实模型加文件工具加审批。
4. **权限层**：补敏感路径黑名单、host 过滤、能力上限，把第 5 节那个缺口关掉。
5. **验收**：命令行跑通一轮真实任务；杀掉进程重启后状态正确、不重复执行；现有前端能连上并看到流式输出。

M3 不许碰 `data/core.db`，只在隔离目录里跑。

---

## 7. 回滚方案与数据安全证明

**回滚**：删掉 `core/sunday-core/` 与 `.github/workflows/sunday-core.yml` 即恢复到之前状态。仓库里没有任何其他代码引用它们。

**数据安全证据**：

| 证明 | 证据 |
|---|---|
| 没有打开过用户数据库 | `data/core.db` 修改时间是 2026-11-02 03:33，早于本会话核心工作开始时间；本次未写入 |
| 测试只用临时数据库 | 每个测试用 `tempfile::tempdir()`，进程退出即销毁 |
| 检查命令只读 | `Store::open_read_only` 用 SQLITE_OPEN_READ_ONLY，且有测试比较前后文件大小 |
| 旧核心未改动 | `core/runtime-rs` 无改动，仍是唯一写真实库的实现 |
| 新核心不猜路径 | `Store::open` 必须显式传路径，没有任何默认值指向 `data/` |
| 新版本库拒绝降级 | K6 测试覆盖 |

**不会出现双写**：新核心目前没有任何命令能写真实库，M3 之前也不会有。真要切换时，单写者锁是 M3 的前置条件，届时先做。

---

## 8. 复算方式

```
cd core/sunday-core
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
python scripts/check-deps.py
cargo test --workspace
cargo run -p sunday-cli -- health
cargo run -p sunday-cli -- store selftest --db /tmp/s.db
cargo run -p sunday-cli -- db inspect --db /tmp/s.db
```

Android arm64 交叉编译，本机用 NDK 30 实测通过，含 SQLite：

```
CC_aarch64_linux_android=<ndk>/bin/aarch64-linux-android21-clang.cmd \
AR_aarch64_linux_android=<ndk>/bin/llvm-ar.exe \
cargo build --target aarch64-linux-android \
  -p sunday-protocol -p sunday-store -p sunday-platform -p sunday-agent
```

规模统计脚本：`.tmp/core-measure.py`。

---

## 9. 置信度与未验证

| 结论 | 置信度 | 依据 |
|---|---|---|
| 7 个 crate 的边界与依赖规则成立 | 高 | 脚本可复算，且做过负向验证 |
| S1 到 S8 与 A1 到 A5 成立 | 高 | 97 个测试，真文件真事务 |
| 崩溃与并发行为正确 | 中高 | 子进程真杀真写；未做长时间压力与断电模拟 |
| Android 可编译 | 高 | 本机交叉编译通过，含 rusqlite |
| Android 可运行 | 未验证 | 没上真机，没跑模拟器 |
| 性能 | 未验证 | 未测 1 万事件、未测写放大 |
| 与现有前端兼容 | 未验证 | 协议适配层还没写 |

**未验证项明确列出**：真机、模拟器、性能、协议兼容、SAF、长时间稳定性、断电。

---

## 10. 关于 C 路线是否需要重新评估

要求里写“如果发现 C 路线产生新的严重结构性问题，立即停止并重新评估”。我检查了一遍，没有触发条件：

1. 没有为了迁就旧代码改动新架构。旧代码只搬了纯函数与已定型类型。
2. 没有把产品逻辑塞进核心。Study 与 Workflow 一行都没进。
3. 每个 crate 有独立职责与独立测试边界，依赖规则可执行。
4. 核心对 tauri、jni、Python、子进程的引用为 0。
5. 复杂度增量有明确归因，主要来自原型本就没做的两件事，不是抽象膨胀。

一个需要留意的地方：`sunday-agent` 现在 548 行，如果 M3 把插话、压缩、子代理都放进来，会重新变成一个胖模块。届时应该新增 crate，而不是继续加，这一点要在 M3 的设计评审里先定。
