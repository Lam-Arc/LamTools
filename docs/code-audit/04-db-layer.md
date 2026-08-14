# 04 数据库持久化层 审计报告

- 审计日期：2026-08-13
- 审计区：04 区（数据库与持久化层）
- 仓库根：`E:\LamTools`（Windows + Git Bash，Python 包在 `core/src/lamtools_core`）
- 审计员：LamTools 代码审计员（04 区）

## 1. 概况

### 1.1 范围

核心文件（全部在 `core/src/lamtools_core/`）：

| 文件 | 行数 | 职责 |
|---|---|---|
| `app/core_db.py` | 1455 | SQLAlchemy 模型定义 + 会话/目标/arrange 各 Store + `open_core_app_db` + Schema 迁移 |
| `app/sqlite_write.py` | 91 | `SQLiteWriteCoordinator`（BEGIN IMMEDIATE + 进程内锁 + 退避重试）+ PRAGMA 配置 |
| `app/core_session_store.py` | 246 | 会话资源适配器（读写 thread snapshot JSON） |
| `app/snapshot_store.py` | 728 | 增量快照投影存储（item 行 + 元数据行） |
| `app/event_store.py` | 230 | 事件表追加（seq 分配、去重） |
| `app/persistence_host.py` | 190 | 事件持久化 + 快照投影编排 |
| `app/project_store.py` | 352 | 项目记录 + 初始会话创建/删除 |
| `mem/store.py` | 253 | `SqlAlchemyMemoryStore`（dreaming 短期记忆） |
| `config/migrate_projects.py` | ~240 | 项目目录迁移（work_root 改写） |
| `checkpoint.py`（非 app/，轻扫） | — | 会话工厂/写协调器复用方 |

### 1.2 技术栈与总体结论

- SQLAlchemy 2.0.51 + aiosqlite，`NullPool`（无连接池，每会话新连接），`PRAGMA journal_mode=WAL`、`synchronous=NORMAL`、`busy_timeout=5000ms`（`app/sqlite_write.py:23-32`）。
- **无 SQL 注入**：全库唯一 f-string SQL 是 `PRAGMA busy_timeout={int(busy_timeout_ms)}`（`app/sqlite_write.py:28`，值为类型强转常量），其余全部走 ORM 或常量 `text()` DDL；`mem/store.py` 的 LIKE 匹配使用绑定参数。
- **并发写设计良好**：`SQLiteWriteCoordinator` 以「数据库路径为键的进程内 asyncio.Lock + `BEGIN IMMEDIATE` + 退避重试（0.05/0.15/0.35s）」统一串行化所有写路径；所有 Store（runtime/goal/arrange/project/memory/session/checkpoint）的写操作均经由此协调器，规避了历史 `database is locked` 死锁（代码注释多处证实这是针对实际故障的修复）。
- 乐观并发控制（revision 校验、`RuntimeStateConflictError`、事件 seq 唯一约束 + 重试）覆盖到位；`live_operations.py:2074` 对恢复/取消路径做了 revision 冲突的 load-mutate-save 重试。
- 发现 S2 问题 2 个、S3 问题 7 个、S4 问题 6 个，共 15 个（详见第 2 节）。

## 2. 问题清单

### S2（中等：数据残留/升级路径崩溃）

- **[S2] 迁移无法删除带索引的 `project_id` 列，旧库升级直接失败**
  - 位置：`core/src/lamtools_core/app/core_db.py:1208-1211`（`_migrate_core_app_schema`）
  - 问题：`ALTER TABLE core_arrange_jobs DROP COLUMN project_id` 之前只 `DROP INDEX IF EXISTS ix_core_arrange_jobs_goal_id`，没有删除 `ix_core_arrange_jobs_project_id`。历史提交 `43c08a2` 中 `project_id` 以 `index=True` 定义（`git show 43c08a2:.../core_db.py:105`），该窗口期新建的库由 `create_all` 生成了该索引。SQLite 的 `DROP COLUMN` 明确规定「被删列不得被任何索引引用」，会抛出 `Cannot drop indexed column: project_id`。该迁移在 `engine.begin()` 事务内执行且无 try/except，失败后整个 `open_core_app_db` 抛异常，应用无法启动。
  - 影响：43c08a2 之后、b29f916（删列）之前创建过数据库的用户升级后应用无法启动（无数据损坏，但完全不可用）。
  - 修复建议：在 `DROP COLUMN project_id` 前补 `DROP INDEX IF EXISTS ix_core_arrange_jobs_project_id`；并给整个 `_migrate_core_app_schema` 加 try/except + 可读错误日志（或 `PRAGMA index_list` 动态删除相关索引）。

- **[S2] `delete_session_records` 删除不完整，会话/项目删除后遗留孤儿数据，已删项目的 arrange 任务仍会继续执行**
  - 位置：`core/src/lamtools_core/app/core_session_store.py:197-202`
  - 问题：删除会话只清理 `core_app_events`、`core_runtime_sessions`、`core_thread_snapshots` 三张表；同属该 `thread_id` 作用域的 `core_history_entries`、`core_thread_snapshot_items`、`core_goals`、`core_arrange_jobs`（及 `core_arrange_occurrences`/`core_arrange_signals`）、`core_attachments`、`core_memories`、`core_checkpoints`/`core_restore_operations` 全部不动。该函数被会话删除（`core_session_store.py:126`）、项目删除（`project_store.py:329`）、项目迁移（`config/migrate_projects.py:209`）三条路径共用。
  - 影响：(a) 数据残留、库体积持续膨胀；(b) 更严重的是 arrange 任务：删除项目只取消会话，`core_arrange_jobs` 中指向已删 `thread_id` 的 job 仍处于 `scheduled`/`waiting`，arrange worker 会照常领取并执行（在已不存在的线程里跑操作）；(c) `core_thread_snapshot_items` 孤儿行会在 thread_id 被复用（概率低）时以陈旧内容复活。
  - 修复建议：按 thread_id 级联删除全部作用域表（或为这些表加 `ON DELETE CASCADE` 外键）；项目删除前把该项目所有 arrange job 置为 `cancelled`。

### S3（轻微：性能/健壮性/边界行为）

- **[S3] Schema 迁移只 `ADD COLUMN` 不建索引，迁移后的库缺少模型声明的索引**
  - 位置：`core/src/lamtools_core/app/core_db.py:1212-1249`（`_migrate_core_app_schema`）
  - 问题：迁移为 `core_arrange_jobs` 添加 `source_thread_id`、`work_root`、`status`（旧表）等列，但模型声明 `index=True`（`core_db.py:146-147`）的索引只能由 `create_all` 在建表时生成；对已存在的旧表 `create_all` 不会补索引，迁移也不建。`SqlAlchemyArrangeStore.list(work_root=...)`（`core_db.py:604-617`）在迁移库上退化为全表扫描。
  - 影响：升级后的库查询性能下降（大量 job 时明显）。
  - 修复建议：迁移末尾对每个 `ADD COLUMN` 的索引列补 `CREATE INDEX IF NOT EXISTS ix_core_arrange_jobs_xxx`。

- **[S3] `append_history` 惰性迁移不清除旧 `history_json` blob，旧 blob 永久残留**
  - 位置：`core/src/lamtools_core/app/core_db.py:385-400`
  - 问题：blob→行迁移只在增量表为空时触发，迁移后不置 `row.history_json = []`（对比 `replace_history` 在 `core_db.py:446-448` 明确清空 blob）。大 blob（历史消息全部内容）会随 `core_runtime_sessions` 行永久保留；且若增量行之后被清空（如未来新增的清理路径），`get_history` 会回退读到陈旧 blob。
  - 影响：存储膨胀 + 潜在陈旧回退读取。
  - 修复建议：迁移成功后同步 `row.history_json = []`（在写事务内）。

- **[S3] 增量投影 `_partial_state` 每次批量投影都全量扫描线程的全部 item 行（id+seq）构建锚点映射**
  - 位置：`core/src/lamtools_core/app/snapshot_store.py:511-523`
  - 问题：`idx_core_snapshot_items_thread_seq` 是 `(thread_id, seq)` 复合索引，不含 `item_id`，`SELECT item_id, seq WHERE thread_id=?` 需对线程的每个 item 行做回表；这是每批事件（含流式 part 事件关闭投影延迟后的每个 turn 边界批量）都要执行的 O(n) 操作，恰好是「55MB 线程」优化要避开的热路径。
  - 影响：大线程上每次投影都产生一次全量 item 扫描，增量设计收益被部分抵消。
  - 修复建议：索引改为 `(thread_id, seq, item_id)` 覆盖索引，或直接维护 `item_order`/锚点于元数据行。

- **[S3] 事件 id 仅 64 位（`uuid4().hex[:16]`），碰撞时第二个事件被静默丢弃**
  - 位置：`core/src/lamtools_core/app/event_store.py:20-21, 88-91`（同 `event/run_item.py:63`）
  - 问题：`_append_once` 对已存在 event_id 直接返回既有 envelope（幂等语义）；64 位 id 全局（跨线程）唯一空间下，事件总量达千万级时碰撞概率约 2.7e-6，一旦碰撞，两个不同事件会被当成同一个，第二个事件静默丢失；快照 `seen_event_ids` 去重与 `find_client_event` 同样依赖该 id 唯一性。
  - 影响：极低概率但静默的数据丢失/事件错配。
  - 修复建议：改用完整 `uuid4().hex`（128 位），或碰撞时追加计数后缀。

- **[S3] 事件 payload 未做 `_json_safe` 序列化清洗，非 JSON 类型导致整个写事务失败**
  - 位置：`core/src/lamtools_core/app/event_store.py:209-222`（`_row_kwargs` 中 `payload_json: dict(event.payload or {})`）
  - 问题：其余所有 JSON 列（runtime_state、arrange payload、snapshot 等）都经 `_json_safe`（`core_db.py:1287-1288`，`default=str` 兜底），唯独事件 payload 直接入库；若事件 payload 携带 `datetime`/`Path`/`bytes` 等对象，SQLAlchemy 默认 `json.dumps` 抛 `TypeError`，导致包含该事件的整批写入失败（协调器只重试 `OperationalError`，此错误直接上抛）。
  - 影响：特定 payload 下流式事件写入整体失败。
  - 修复建议：`_row_kwargs` 中对 payload 也走 `_json_safe`。

- **[S3] `recover_running` 无视租约直接重置所有 running 任务，多 worker 共享库时可能双跑**
  - 位置：`core/src/lamtools_core/app/core_db.py:934-965`
  - 问题：`recover_running` 把 `core_arrange_jobs` 中所有 `running` 行（无论 `lease_owner`、`lease_expires_at`）重置为 `scheduled`。它被 `ArrangeWorker.start()`（`runtime/arrange.py:946`）调用；若 CLI 与 server（默认都指向 `data/core.db`，`cli.py:2726-2733`）各自启动 worker，后启动者会把前者仍在执行的任务复位并重新领取。对比 `claim_due` 只回收「租约已过期」的任务（`core_db.py:670-706`），两者语义不一致。
  - 影响：多进程部署下重复执行 arrange 任务（副作用操作可能重复执行）。
  - 修复建议：`recover_running` 仅回收 `lease_expires_at <= now` 的任务，或仅在确认 owner 已死（如进程启动心跳）时全量回收。

- **[S3] `emit_signal` 对非规范化信号无校验：无 event_id 时以 PK="" 静默去重、缺 `occurred_at` 直接 KeyError**
  - 位置：`core/src/lamtools_core/app/core_db.py:976-987`
  - 问题：`event_id = str(signal.get("event_id") or "")` 为空时也执行 `db.get(CoreArrangeSignal, "")` 并以 `""` 为 PK 落库，后续无 event_id 的信号全部被判定 `created=False` 静默丢弃；`datetime.fromisoformat(str(signal["occurred_at"]))` 缺键时 KeyError 使整个写事务失败。当前所有调用方（`runtime/arrange.py:860-885` 的 `_normalize_signal`、`durable_operations.py:214`、`runtime/observer.py`）都已规范化，此问题仅在绕过校验层直调 store 时暴露。
  - 影响：防御层缺失——错误输入导致信号静默丢失或事务崩溃。
  - 修复建议：store 内对空 event_id 生成占位 id（或抛 ValueError），`occurred_at` 用 `.get()` + 默认当前时间。

### S4（建议）

- **[S4] `CoreAppSnapshotProjector.member_defaults` 是死参数，从未被赋值**
  - 位置：`core/src/lamtools_core/app/snapshot_store.py:30, 45`；`app/core_db.py:1109-1113`
  - 问题：`open_core_app_db` 收到的 `member_defaults` 只存入 `CoreAppDb.member_defaults`（`core_db.py:1132`），构造 `CoreAppSnapshotProjector()` 时未传入（`core_db.py:1112`），`empty()` 里的 `state.update(deepcopy(self.member_defaults))` 永远以空 dict 执行；member 默认值实际由 `_MemberDefaultsHooks`（`http_agent_app.py:138-159`）注入。两套机制并存，投影器侧是死代码。
  - 修复建议：二选一——给投影器传入 member_defaults，或删除该字段与其在 `empty()` 中的分支。

- **[S4] `find_request`（无 thread_id 时）全表全量组装每个快照，且多匹配静默返回 None**
  - 位置：`core/src/lamtools_core/app/snapshot_store.py:612-621`
  - 问题：遍历所有 snapshot 行并逐个 `_assemble`（对 55MB 级线程是灾难性开销）；`matches` 多于 1 个时返回 `None`，调用方无法区分「找不到」与「有歧义」。
  - 修复建议：优先按 thread_id 检索；无 thread_id 时改用 SQL 层 `json_extract` 过滤（同 `find_pending_approval` 的做法，`core_db.py:452-468`）。

- **[S4] 多进程同时打开全新库时 `create_all` 竞态无重试**
  - 位置：`core/src/lamtools_core/app/core_db.py:1100-1102`
  - 问题：`create_all`（checkfirst 探测 + CREATE TABLE）在 CLI 与 server 同时首次打开同一 `data/core.db` 时可能抛出 `table xxx already exists`（该错误不是 `database is locked`，`SQLiteWriteCoordinator` 的重试不覆盖此路径），其中一个进程打开失败。
  - 影响：并发首启时的偶发启动失败。
  - 修复建议：对打开阶段的 `OperationalError`（table exists）做一次重试，或将建表改为 `CREATE TABLE IF NOT EXISTS` 原生 DDL。

- **[S4] `emit_signal` 对 paused 状态的事件触发型 job 仍生成 occurrence，恢复时可能爆发执行**
  - 位置：`core/src/lamtools_core/app/core_db.py:988-990`
  - 问题：job 过滤条件 `status.not_in(("completed","failed","cancelled"))` 未排除 `paused`；暂停期间到达的每个信号都会为 paused job 追加一条 pending occurrence，恢复为 `scheduled` 后这些 occurrence 被 `claim_due` 一次性全部领取，造成任务突发批量执行。
  - 修复建议：过滤条件加入 `paused`（暂停即停止接收事件），或暂停时清空其 pending occurrence。

- **[S4] 会话层写入 `status` 与投影器派生状态互相覆盖**
  - 位置：`core/src/lamtools_core/app/core_session_store.py:69-72, 110-113`
  - 问题：`update`/`patch` 把 `SessionRecord.status` 直接写进快照 JSON 的 `status` 字段，而同一字段也由事件投影器（`snapshot_store.py:358-406`）按事件流重算；两个写入方语义不同（会话管理 vs 事件事实），存在把「运行中」覆盖回「idle」等错位风险，直到下一条事件投影再纠正。
  - 修复建议：会话层只写 `session` 子对象，`status` 一律由投影器维护。

- **[S4] 会话列表无 `updated_at` 索引**
  - 位置：`core/src/lamtools_core/app/core_db.py:1153-1157`（`list_core_sessions`）；同 `core_session_store.py:47-56`
  - 问题：`ORDER BY updated_at DESC` 对 `core_thread_snapshots` 全表扫描排序；会话多时每次列表请求都有排序开销。
  - 修复建议：`CoreThreadSnapshot.updated_at` 加索引（仅对长期存在的大表有意义）。

## 3. 该区 Top 3 问题

1. **迁移 DROP COLUMN 未删索引（S2）**——旧库升级路径上应用直接无法启动，且迁移无任何错误处理。修复成本极低（补一行 `DROP INDEX IF EXISTS`），应优先处理。
2. **`delete_session_records` 删除不完整（S2）**——三处删除入口共用，造成孤儿数据持续累积，且已删除项目的 arrange 任务仍会执行（可能造成对已删除工作区的副作用操作）。应改为按 thread_id 级联清理并取消相关任务。
3. **增量投影热路径的全量 item 扫描（S3）**——`_partial_state` 的锚点映射构建 O(n) 回表查询，与「增量投影」设计目标直接冲突，大线程（55MB）上会放大每次投影的耗时；覆盖索引即可解决。

## 4. 亮点

- **统一写协调器**：`SQLiteWriteCoordinator`（`app/sqlite_write.py:44-78`）以「数据库路径 → 进程内 asyncio.Lock」+ `BEGIN IMMEDIATE` + 退避重试，从根上解决了历史 `database is locked` 死锁；`WeakValueDictionary` 保证同库多引擎共享一把锁，且 `database_identity` 归一化路径大小写。
- **事务边界清晰**：所有写路径（事件、快照、runtime 状态、goal、arrange、项目、记忆、checkpoint）统一走协调器；`AppPersistenceHost.append_batch` 用 savepoint 保证「事件 + 投影」原子提交；异常路径统一 `rollback` 后重试，无事务残留。
- **乐观并发控制完善**：runtime 状态 revision 校验 + `RuntimeStateConflictError`；事件 `(thread_id, seq)` 唯一约束 + 分配重试；arrange 任务 lease（owner/expires_at）+ claim 条件更新，多 worker 安全领取；revision 冲突在恢复/取消路径有 load-mutate-save 重试（`live_operations.py:2074`）。
- **迁移幂等设计**：`PRAGMA table_info` 探测 + 条件 ALTER，全部在单个事务内执行，失败自动回滚；`create_all` 与迁移分离，兼容旧库。
- **增量快照架构**：item 行级 upsert（`snapshot_store.py:666-722`）配合 `flag_modified` 忠实写回，避免 55MB 线程全量重写；`_item_seq_map` 锚点保证部分装配下 `item_order` 与生产顺序一致。
- **JSON 边界处理**：`_json_safe`（`default=str`）在多数列统一兜底，读写两侧对称。

## 5. 审计范围与方法

- **范围**：`app/core_db.py`、`app/sqlite_write.py`、`app/core_session_store.py`、`app/snapshot_store.py`、`app/event_store.py`、`app/persistence_host.py`、`app/project_store.py`、`mem/store.py`、`config/migrate_projects.py`、`checkpoint.py`（仅其协调器/会话工厂复用面）；`app/queue_state.py` 经确认不涉及 DB，未列入。
- **方法**：逐文件通读（core_db.py 1455 行全文、snapshot_store.py 728 行全文等）；`grep` 定位引擎/会话工厂创建点、`commit`/`rollback`/`begin_nested` 使用点、原始 SQL 与 f-string SQL；`git log`/`git show` 核查历史模型（`project_id` 索引史、迁移演进）；交叉核对写路径调用方（`live_operations.py`、`http_agent_app.py`、`cli.py`、`runtime/arrange.py`）是否全部经由写协调器；验证信号规范化链路（`_normalize_signal`）、事件 seq 语义（`snapshot/__init__.py` 锚点逻辑）。
- **约束遵守**：全程只读，未修改任何代码文件，未打开/触碰 `data/core.db`，未运行测试或服务；唯一写入文件为本报告。
- **排除项**：未对 `core.db` 实际数据做验证（只读纪律）；未评估 `checkpoint.py` 的工作区文件捕获逻辑（属文件系统层）。
