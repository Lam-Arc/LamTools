# M3 验收报告

路线 C，M3 隔离开发结果。日期 2026-11-02。
本地闸门全绿，远端 CI 四项全绿。M3 未触碰真实用户数据库，未切换正式核心。

---

## 1. 模块边界，按指定落位

| 要求 | 落位 | 证据 |
|---|---|---|
| Steer 放在 sunday-agent，负责生效时机与语义 | `run_turn` 每轮开头调用 `drain_guidance`，把待处理的指令插到本轮模型调用之前 | `crates/sunday-agent/src/lib.rs`，`tests/m3_contract.rs::a_steer_*` |
| 待处理消息由 Store 持久化，Agent 不得另建队列 | 新增 `guidance` 表；Agent 只读 `pending_guidance` 并 `consume_guidance`，内存里没有任何待处理列表 | `crates/sunday-store/src/schema_v2.sql`、`lib.rs` |
| 上下文压缩独立为 sunday-context | 新 crate，只管预算、选择、摘要与压缩策略；Agent 只决定何时触发 | `crates/sunday-context/src/lib.rs`，依赖仅 protocol |
| 压缩不能丢审批状态、工具结果、未处理指令 | 前两者根本不在消息列表里，天然丢不掉；工具结果与它的调用被绑成不可分割的单元 | `units()` 与三个针对性测试 |
| 子代理编排在 sunday-extensions | 创建、权限收窄、预算、生命周期、结果汇总 | `crates/sunday-extensions/src/lib.rs` |
| 子代理必须复用 Agent，禁止第二套循环 | 子代理直接调用 `sunday_agent::run_turn`，本 crate 内没有任何 `for round` 循环 | 全文无循环；`tests/subagent_contract.rs` 断言事件落在子线程且经过同一套事件 |
| 保持与宿主解耦、单向依赖 | 依赖规则脚本强制，9 个 crate 全绿 | `scripts/check-deps.py` |

没有为了拆分而拆分。`sunday-context` 是这次唯一新增的 crate，理由是它的输入输出与 Agent 完全不同：它只回答"模型看到什么"，不回答"什么时候问"。

---

## 2. 功能对照

| M3 要求 | 状态 | 证据 |
|---|---|---|
| 用户消息 → LLM → 工具调用 → 审批 → 执行 → 回答 | 完成 | CLI 实跑，见第 3 节 |
| 执行中 Steer | 完成 | 模型调用进行中写入插话，下一轮生效，只生效一次 |
| 执行中 Stop | 完成 | 取消后不再开始任何工具 |
| 执行中 Queue | 完成 | 同 thread 第二条 run 排队而非报错 |
| 上下文压缩及压缩后继续 | 完成 | 超过预算触发，压缩后同一回合继续跑完 |
| 子代理创建、执行、权限收窄、结果返回 | 完成 | 未授权工具被拒，结果写回记录 |
| 异常中断与重启恢复 | 完成 | 进程被杀、事务中断、孤儿子代理 |
| 真实 SQLite 事件持久化与状态重建 | 完成 | 投影可从日志重建，schema 从 v1 迁移到 v2 |
| 审批与插话并发 | 完成 | 审批挂起期间写入插话，恢复后仍然生效 |
| 子代理取消 | 完成 | 取消后工具一次都没执行 |
| 预算耗尽 | 完成 | 轮数、工具次数、墙钟三种 |
| 非幂等工具结果未知 | 完成 | 未知态不重放，停下等核对 |

### 2.1 端到端实跑记录

命令行，真实 SQLite，真实文件系统：

```
sunday turn --db core.db --workspace ws --thread t1 \
  --prompt "create hello.txt" --script s1.json
→ needs_approval: appr-d9217c11aaafc242:25

sunday approve --db core.db --workspace ws --thread t1 \
  --approval appr-d9217c11aaafc242:25 --script s2.json
→ completed: the file is written

cat ws/hello.txt
→ hello Sunday
```

日志完整且有序，共 11 条：

```
1  run_started       turn-1:t1:started
2  model_started     t1:turn-1:start:0:model
3  model_completed   t1:turn-1:start:0:model_done
4  tool_prepared     t1:c1:prepared
5  approval_requested t1:c1:approval  {"args_digest":"91b90081ea53f179:41"}
6  tool_dispatched   t1:c1:dispatched
7  tool_succeeded    t1:c1:result
8  run_started       t1:turn-1:resumed {"resumed":true}
9  model_started     t1:turn-1:resume:0:model
10 model_completed   t1:turn-1:resume:0:model_done
11 run_completed     t1:turn-1:resume:0:completed
```

审批前工具没执行，审批后只执行一次，续跑没有重新问模型。

---

## 3. 测试结果

### 3.1 本地

| 闸门 | 结果 |
|---|---|
| `cargo fmt --all -- --check` | 通过 |
| `cargo clippy --workspace --all-targets -- -D warnings` | 0 错误 |
| `python scripts/check-deps.py` | 9 个 crate 边界与禁用词全绿 |
| `cargo test --workspace` | 124 个通过，0 失败 |

测试分布：protocol 5、store 23 加 3 个子进程夹具、platform 14、context 7、agent 17、extensions 9、llm 34、tools 15。

### 3.2 远端 CI

第一轮真实 CI 抓到本地测不出的问题，说明这一步必须做。

| 运行 | 结果 |
|---|---|
| 首次推送 `a747aa58` | 依赖规则 成功、Windows 成功、Android 成功、**Linux 失败** |
| 修复后 `7786b8ce` | 四项全部成功 |

失败原因：`refuses_absolute_paths` 测试用 `C:/Windows/win.ini`，在 Linux 上 `Path::is_absolute()` 返回 false，于是这个 Windows 绝对路径被当成一个带冒号的相对名字放行。

这不是测试写错，是真实的跨平台缺陷。Android 内核是 Linux，同样的代码在手机上也会把 `C:/...` 当成普通相对路径。修法是按形状判断：盘符、前导斜杠、UNC 前缀一律拒绝，三个平台行为一致。

第三轮（仅文档改动）在提交后另行确认。

### 3.3 故障注入记录

| 编号 | 注入 | 期望 | 结果 |
|---|---|---|---|
| K1 | 子进程派发后 `abort()` | 重启后未知态，不重放 | 通过 |
| K2 | 进程在未提交事务中 `abort()` | 无残留行，seq 不跳号 | 通过 |
| C2 | 两个进程各写 20 条事件 | seq 连续 1 到 40 | 通过 |
| K3 | `recover()` 连跑两次 | 第二次空操作 | 通过 |
| K4 | 收据挂起时进程死亡 | 恢复时标为 failed | 通过 |
| K5 | 只读检查前后比对 db、-wal、-shm | 三个文件都不变 | 通过 |
| K5b | 存在活动 -wal 时只读打开 | 拒绝，不读移动靶 | 通过 |
| K6 | schema 版本高于当前 | 拒绝打开 | 通过 |
| M1 | 审批挂起时写入插话 | 恢复后插话生效 | 通过 |
| M2 | 同一 guidance id 重发 | 只入队一次 | 通过 |
| M3 | 子代理被取消 | 工具零执行 | 通过 |
| M4 | 子代理未授权工具 | 拒绝，记录标 Failed | 通过 |
| M5 | 子代理运行中进程死亡 | 恢复时报 orphaned | 通过 |
| M6 | 慢模型超过墙钟预算 | 预算耗尽返回 | 通过 |
| S1 | 敏感路径读写 | 拒绝 | 通过 |
| S2 | 符号链接指向工作区外 | 拒绝 | 通过 |
| S3 | 四种绝对路径形态 | 全部拒绝 | 通过 |

---

## 4. 本轮发现的真实缺陷

| 编号 | 缺陷 | 发现方式 | 影响范围 | 处理 |
|---|---|---|---|---|
| D1 | 续跑那一轮的模型事件被当成重复事件吞掉，因为事件 id 复用了轮次号 | 端到端实跑后读日志，发现少了 model_started | 1 个函数加 2 处调用点 | 事件 id 加阶段前缀，`start` / `resume` |
| D2 | 只读打开 WAL 库会创建 `-wal` 与 `-shm`，等于写盘 | 数据安全脚本比对文件，报告 changed | 1 个函数 | 改用 `immutable=1`，有活动 WAL 时直接拒绝 |
| D3 | `C:/...` 在 Linux 与 Android 上不算绝对路径，被放行 | **远端 Linux CI** | 1 个函数加 1 个测试 | 按形状判断，三平台一致 |
| D4 | 压缩切点算法把"保留最新指令"做成了"整段都不压缩" | 压缩测试没触发 | 1 个函数 | 改为固定系统提示与任务陈述，只压缩中间 |
| D5 | `.env.local` 漏过敏感路径规则 | 敏感路径测试失败 | 1 个函数 | 策略拆成目录段、文件名、扩展名、前缀四类 |
| D6 | 子代理把模型建了两次 | 工厂调用次数断言 | 1 个 crate | spawn 时建一次并缓存 |
| D7 | 压缩摘要塞成列表中间的系统消息 | 自己的测试断言不符 | 1 个函数 | 改成用户角色上下文消息，兼容只认顶部 system 的 Provider |

D2 与 D3 是本地永远测不出来的：一个需要比对文件系统副作用，一个需要非 Windows 平台。

---

## 5. 代码复杂度变化

| 项 | M1/M2 | M3 | 变化 |
|---|---|---|---|
| crate 数 | 7 | 9 | +2 |
| 生产代码 | 3,877 | 5,204 | +1,327 |
| 测试代码 | 2,674 | 3,839 | +1,165 |
| 测试数 | 97 | 124 | +27 |
| `sunday-agent` | 548 | 629 | +81 |
| `sunday-store` | 1,016 | 1,304 | +288 |
| `sunday-cli` | 248 | 692 | +444 |

新增的两个 crate：`sunday-context` 189 行，`sunday-extensions` 224 行。

增量归因：

| 原因 | 大致增量 |
|---|---|
| 插话持久化与消费语义（表、方法、Agent 侧排空） | 约 210 |
| 压缩 crate 与 Agent 触发点 | 约 260 |
| 子代理编排与记录 | 约 224 |
| schema v2 迁移、只读加固、子代理与插话表 | 约 180 |
| 安全边界：敏感路径、符号链接、绝对路径形状 | 约 130 |
| CLI 端到端命令与脚本模型 | 约 444 |
| 其余（事件阶段、预算、测试支持） | 约 100 |

`basis` 仍是估计，总行数是实测。**没有出现职责混乱导致的重构**：Agent 只加了"何时排空插话""何时压缩"两个判断，循环结构没变。

一个需要盯住的信号：`sunday-agent` 从 548 涨到 629，涨幅 15%，主要来自插话排空与压缩触发。如果 M4 再把 MCP 与 Skills 塞进来，它会重新变成胖模块。建议 M4 一开始就定：MCP 与 Skills 各自独立 crate，Agent 只保留端口调用。

---

## 6. 遗留风险

| 风险 | 现状 | 缓解 |
|---|---|---|
| 未跑真实模型 | CLI 用脚本模型；适配层只对本地 HTTP 服务器测过 | 拿一个真实 Key 跑同一条命令即可验证，代码路径相同 |
| 未上真机 | Android 只做了交叉编译 | M4 的首要动作 |
| 无协议适配 | 现有前端连不上新核心 | 下一阶段第一项 |
| 压缩质量未评估 | 只测了边界与不丢信息，没测摘要是否好用 | 接真实模型后对比压缩前后的回答质量 |
| 子代理并发未压测 | 只测了上限拒绝与取消 | 并发 8 个子代理的压力测试留给 M4 |
| 事件表增长未被限制 | 日志只增不减，没有归档策略 | 与 `core_sync_changes` 那次教训合在一起处理，属数据治理阶段 |
| 单写者锁未实现 | 现在靠"新核心不碰真实库"保证 | 接管 Windows 前必须做 |

---

## 7. Windows 接管方案

不切换，先并行验证。

1. **协议适配层**：把 `sunday.core.v1` 命令与事件映射到 `core.app_server.v1` 的方法与通知，先覆盖 `thread/*`、`turn/*`、`approval/respond`、`session/*`。现有前端不改一行。
2. **单写者锁**：数据目录级的独占文件锁，写进程标识与后端类型。拿不到锁就明确失败，不重试。这是接管的前置条件，没它不能切。
3. **影子读**：新核心以只读方式打开用户库的一份拷贝，跑真实会话来验证投影与事件重建，不写任何东西。
4. **后端选择开关**：桌面配置加一个 `core_backend`，默认仍是 Python。用同一个前端分别连两套后端，跑同一组操作，比对事件与投影。
5. **翻转**：确认等价后，先停 Python，再取锁，再启 Rust。失败立刻切回，因为老表一行没动。
6. **数据**：新核心里程碑内只新增自己的表，不改老表结构；这样回滚就是改回配置。

顺序不能颠倒：先锁，再影子读，再协议，最后翻转。

---

## 8. 数据安全证明

| 证明 | 证据 |
|---|---|
| 用户库未被打开 | `data/core.db` 3676884992 字节，mtime 仍是 2026-11-02 03:33 |
| 只读检查零写入 | 脚本比对 db、-wal、-shm 三个文件的 sha256 与大小，前后一致 |
| 只读为何能零写入 | `immutable=1`；有活动 WAL 时拒绝打开而不是读移动靶 |
| 备份可用 | db + wal + shm 三文件复制后，只读打开并通过表计数检查 |
| 测试不碰真实库 | 所有测试用 `tempfile::tempdir()`，进程退出即销毁 |
| 旧核心未动 | `core/runtime-rs` 无改动 |

复算命令：`python .tmp/data-safety.py`。

---

## 9. 关于 C 路线是否需要重新评估

按约定的停止条件自查：

1. 没有为了迁就旧代码改新架构。这次只搬了纯函数与已定型类型。
2. 产品逻辑没进核心。Study 与 Workflow 一行都没进。
3. 每个 crate 职责独立、测试独立，依赖规则可执行且做过负向验证。
4. 核心对 tauri、jni、Python、子进程的引用为 0。
5. 复杂度增量有归因，主要来自新能力而非抽象。

没有触发停止条件。但第 5 节末尾那个信号要写进 M4 的开工条件。

---

## 10. 复算方式

```
cd core/sunday-core
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
python scripts/check-deps.py
cargo test --workspace
```

端到端：

```
D=/tmp/m3 && mkdir -p $D/ws
echo '[{"text":"go","tool_calls":[{"id":"c1","name":"write_file","args":{"path":"hello.txt","content":"hello Sunday"}}]}]' > $D/s1.json
echo '[{"text":"done","tool_calls":[]}]' > $D/s2.json
sunday turn --db $D/core.db --workspace $D/ws --thread t1 --prompt "create hello.txt" --script $D/s1.json
sunday approve --db $D/core.db --workspace $D/ws --thread t1 --approval <上一步打印的 id> --script $D/s2.json
sunday journal tail --db $D/core.db --thread t1
```

远端 CI：分支 `sunday/m3-isolated-core`，运行 41582929011 四项全绿。
