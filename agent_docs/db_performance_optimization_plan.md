# Sunday 数据库性能优化：现状、设计与实施

基准分支：`sunday/m3-isolated-core`（工作区 HEAD `c105bdde`，用户给定基准 `cbeeba3`）
测量时间：2026-11-16
本文区分三类信息：**实测**（本次真机读取的数字）、**代码事实**（读源码确认的结构）、**估算**（由前两者推导，未压测验证）。

---

## 一、现状基线（实测）

数据目录 `E:\setuptest\constant\.lam\`：

| 项目 | 数值 | 来源 |
|---|---|---|
| core.db | 4.1 GB | 文件系统 |
| core.db-wal | 710 MB | 文件系统 |
| core_app_events | 303,732 行 | SQL count |
| core_thread_snapshot_items | 76,177 行 | SQL count |
| core_history_entries | 56,248 行 | SQL count |
| core_sync_changes | 15,601 行 | SQL count |
| core_checkpoint_v2_session_history | 0 行 | SQL count |
| 全库行数 | 462,071 行 | SQL count |
| 单条历史消息最大 | 0.06 MB | SQL max(length) |
| 同步日志采样 p50 / p95 / p99 / max | 2.9KB / 23KB / 52KB / 430KB | 最近 5000 行 |

连接池现状（代码事实，本轮之前已落地）：

| 池 | 容量 | 超时 | 用途 |
|---|---|---|---|
| 读池 | 8 + 8 = 16 | 8 秒 | 所有普通查询 |
| 写池 | 2 + 2 = 4 | 30 秒 | SQLiteWriteCoordinator |

WAL 维护：每秒一次 PASSIVE checkpoint；未回写页超过 2048 页只告警不处理。

### 与 11-09 那次事故的差异

11-09 的 8.4GB 库里有 2.13GB 的 checkpoint 历史副本（单行最大 109MB）和 3.32GB 同步日志。当前库这两项一个已清空、一个已降到 1.5 万行，说明数据被重建过，**不能把 11-09 的结论直接当现状**。

---

## 二、已确认的问题（按当前数据严重度排序）

### P1 WAL 回写停在中途，文件涨到 710MB（实测 + 代码事实）

日志形态：

```
[{'state': 'ok', 'busy': 0, 'log': 3842, 'checkpointed': 1044, 'pending': 2798}]
```

`busy=0` 表示 checkpoint 没有因锁失败，但 `checkpointed` 长时间停在 1044，`log` 持续增长。这是 SQLite 的读标记被某个长期存在的读快照固定在早期帧的典型表现：PASSIVE checkpoint 只能回写读标记之前的帧。

影响：读操作要在更大的 WAL 上定位帧；checkpoint 每次要扫描的帧更多；磁盘占用 710MB；崩溃恢复时间变长。

现有维护逻辑只报警，不尝试收口，也不会在退出前清零。

### P2 同一份内容存三份（代码事实 + 实测行数）

一条事件写入会落到：

1. `core_app_events.payload_json`（源，事件日志）
2. `core_thread_snapshot_items.item_json`（投影，供 UI 快照）
3. `core_history_entries.message_json`（模型上下文）
4. 历史上还有 `core_sync_changes.entity_json`（同步副本，已通过本轮引用化前的裁剪把行数压到 1.5 万）

4.1GB 基本由前三项按行数摊平构成。这是结构性冗余，不是索引问题。

### P3 读事务持有时间由"查询 + 组装"共同决定（代码事实）

多处读路径在 `async with session_factory() as db:` 内完成查询后立即退出会话，组装放在会话外，这部分已经做对了（`handle_thread_page_around_operation`、`handle_thread_resume_operation`）。

仍需注意：只要组装仍留在会话内，读标记就会被多固定几十毫秒到数秒，直接加剧 P1。

### P4 事件序号分配每事件一次 `SELECT max(seq)`（代码事实）

`SqlAlchemyAppEventStore._append_once` 对每条事件执行一次 `select coalesce(max(seq)) where thread_id=?`。走 `(thread_id, seq)` 唯一索引的反向扫描，单次成本低（估算 10–50 微秒），但 30 万事件累计可观。

### P5 单写通道是并发上限（代码事实，估算）

写入被 `SQLiteWriteCoordinator` 串行化，理论上限 = 1 / 单事务耗时。若单事务 20–50ms，写入通道吞吐约 20–50 次/秒。32 个活跃 Agent 每秒各写 1 次即达 64%–100% 利用率，64 个必然积压。

这是 SQLite 架构的固有边界，不是 bug。要么降低单事务成本（P2、P4），要么在应用层做有界队列与降级（见第五节）。

---

## 三、已实施（本轮之前）

| 改动 | 解决的问题 | 验证 |
|---|---|---|
| 读写分池（8+8 / 2+2） | 读池占满时写拿不到连接，整轮判 failed | `core/tests/test_db_pool_lifecycle.py::test_writes_survive_a_full_booked_read_pool` |
| 池观测（检出点、持有时长、饱和告警、超时点名） | 池耗尽时只能看到无关请求报 30 秒超时 | 同一测试文件的大小与告警断言 |
| 同步日志保留窗口 `SYNC_JOURNAL_MAX_ROWS=20000` | 同步副本无界增长（曾 3.32GB） | `core/tests/test_sync_journal_retention.py` |
| `sub_agent.list` 复用监督器 + 创建串行化 | 每 220ms 轮询都重建 runner、读一次库 | `core/tests/test_sub_agent_list_poll_cost.py` |

---

## 四、本轮实施

### 4.1 WAL 收口（对应 P1）

- `wal_maintenance_once` 增加 `aggressive` 模式，在未回写页超过水位时尝试 `wal_checkpoint(TRUNCATE)`，成功则 WAL 归零，失败（有读者固定）保持原状，不阻断业务。
- 应用启动完成前做一次收口：上次异常退出遗留的巨大 WAL 在没有任何并发连接时最容易截断。
- 应用关闭时做一次收口：不让 710MB 这种体积跨会话累积。
- 维护循环在收口成功/失败时各记一条日志，把"谁在挡"与"是否已收口"变成可查事实。

风险控制：TRUNCATE 使用独立短连接、工作线程、短超时；任何异常只记日志。它不改变读写语义，只影响 WAL 文件大小。

### 4.2 事件序号批量分配（对应 P4）

`AppPersistenceHost.append_batch` 在一批事件开始前取一次当前最大序号，批内顺序分配，省掉每事件一次的查询；单条 `append` 保持原路径不变。冲突仍由唯一约束与重试兜底。

风险控制：仅在批内生效，不改变事件顺序语义；序号冲突时沿用既有的重试分支。

---

## 五、待实施（需测试验证后再动）

| 优先级 | 改动 | 预期收益 | 风险 |
|---|---|---|---|
| 高 | 快照条目只存引用，读时批量回填 | 省 1–1.5GB，单次写少 1 份 | 中：影响快照/分页/搜索三条读路径 |
| 高 | checkpoint 历史副本按条数或字节截断，超出部分标记为可按边界重建 | 避免单次写入 5–109MB | 中：rollback 后重建精度下降 |
| 中 | 写入优先队列：核心事件优先，UI 派生写可延后 | 拥塞时保证回合不失败 | 中：需要统一排队入口 |
| 中 | `core_sync_changes` 超大实体引用化 | 单次写少 1 份大 payload | 低：当前行数已受控，收益随数据增长 |
| 低 | 补齐按方法过滤的索引 | 少量查询从扫描变索引 | 低 |

---

## 六、Rust 切分方案

现状：`core/sunday-core/crates/` 下有 `sunday-store`、`sunday-host` 等独立 crate，**没有 PyO3 桥接**，Python 侧也没有调用入口。因此 Rust 化有两条路径：

1. **独立 sidecar 或子进程**：边界清晰，崩溃隔离，但跨进程传大数据有拷贝成本。
2. **PyO3 扩展**：同进程调用，无需序列化，但要把编译产物打进 PyInstaller，构建链新增一环。

按"收益 ÷ 风险"排序的候选：

| 候选模块 | 为什么值得 | 风险 | 建议 |
|---|---|---|---|
| 事件编解码 + 快照投影（纯 dict 变换） | 热点、纯函数、输入输出明确，可用对照测试逐条比对 | 低（可影子比对） | **首批**，先做影子实现 |
| 历史分页拼装 | 与投影同源 | 低 | 第二批 |
| 写入队列与序号分配 | 减少 Python 与 SQLite 之间的往返 | 中 | 需要与写协调器一并设计 |
| 整库搬 Rust | 彻底绕开 GIL 与 Python 序列化 | 高 | 不作为本阶段目标 |

本阶段不引入 Rust 依赖：构建链尚未包含 PyO3，贸然接入会把"性能优化"变成"打包风险"。建议先完成第五节的中低风险项，用实测确认瓶颈仍在 Python 侧 CPU 后，再按上表顺序切。

---

## 七、验收计划（测试滞后，但必须补）

1. 建立可重复负载脚本：以真实 thread 数据为种子，模拟 4/8/16/32/64 个 Agent 各按 1 次/秒写入，同时保持 UI 轮询与历史分页读。
2. 记录：事务 P50/P95/P99、池等待、峰值占用、超时数、WAL 帧数、库与 WAL 体积、CPU/内存/磁盘。
3. 每项优化前后用同一脚本、同一数据、同一机器对照，结论标注实测。
4. SSD 与 HDD 分开报告。

当前文档中的所有百分比与毫秒预期均为估算，未经验证，不得作为验收结论。

---

## 八、未证实假设

- WAL 710MB 是否由某个具体未关闭的读会话造成：尚未定位到调用点。已加入检出点日志，下一轮可直接确认。
- 快照条目引用化后读放大是否可接受：未测。
- Rust 影子实现的编译与打包成本：未评估。
