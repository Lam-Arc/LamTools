# Sunday 消息加载与分页：审查结论与改造记录

审查对象：快照存储、分页接口、消息投影、滚动与实时更新这一整条链路。
度量台：`core/scripts/message_paging/`（造数与测量脚本），数据来自真实 `append_batch` 写入路径。

## 一、先说清现状：已经做了什么，缺的是什么

任务描述假设前端是「150 条窗口 + 全量快照」，实际代码已经比这进度靠前，所以本次没有重写，只在确认的瓶颈上动刀：

| 机制 | 现状（改造前已存在） |
| --- | --- |
| 条目存储 | `core_thread_snapshot_items` 一条目一行，流式事件只 upsert 被改的条目 |
| 后端分页 | `load_page` 按 `(thread_id, seq)` 倒序读，字节预算封顶；`before_item_id`/`before_seq` 游标；`history_page.has_more/total_items` |
| 前端窗口 | 按「完整轮次」投影（默认 10 轮），`loadMoreHistory` 加宽并后台 `thread.history` 预取 |
| 增量投影 | `messagesById`/`partsByItemId`/`itemsApp` 引用比对缓存，未变的消息复用对象身份 |
| 滚动 | 以可见消息元素 + 视口偏移做锚点，加载历史后回填补偿；`content-visibility: auto` 限制离屏布局 |
| 实时 | `applyAppEvent` 事件合并 + revision/seq 单调校验 + 断线重连 |

缺的是**每次读都要为「整段历史」付一次的固定成本**，以及**若干 O(全部条目) 的读时修补**。下面每一条都是实测出来的，不是猜的。

## 二、测试环境

- 会话：12000 轮，24,000 条逻辑消息，48,000 条 item 行，120,001 条事件
- 元数据行 24.4MB，item 行合计 561MB，全量快照 585MB
- 参照对象：任务要求的是「1 万条逻辑消息 / 10 万条运行条目」，本 fixture 在消息维度是它的 2.4 倍

测量口径：真实 WebSocket JSON-RPC（`ws://127.0.0.1:<port>/api/core/app-server`），含序列化与传输。

## 三、确认的瓶颈（改造前实测）

| 现象 | 数值 | 根因 |
| --- | --- | --- |
| 每次分页 965ms（P50），而响应只有 10~230KB | 941 / 891 / 991 / 988 ms | 见下 4 条 |
| 首屏加载 P95 2008ms | 2008 / 905 / 914 ms | 冷启动多一次全量解码 |
| outline 4.2s、3.2MB | 4759ms | 为取每轮结尾正文，读了全部 561MB item 行 |
| 每个会话 RPC 开头 | 约 +320ms | `session_store.get()` 存在性检查会解析整包 24MB 快照并跑读时修补 |
| 每次读的元数据解码 | 374ms（缓存前的热读） | `load_page`/`_load_metadata` 每次 `db.get` 都重新解码元数据行 |
| 每次读的读时修补 | 约 470ms / 12000 轮 | `reconcile_status` + `_sync_turns_from_core` + `prune_orphan_turns` 各走一遍全表回合 |
| item 读取行数 | 4000 行 / 约 46MB 解码 | 只为给页面 40 条；驱动会取回 LIMIT 允许的全部行再解码 |
| 分页构建里的全量扫描 | 40ms | 倒查条目→回合索引、两个 order 列表的并集与过滤 |

## 四、改造内容

### 后端

1. **元数据解析缓存（有界）** `snapshot_store.py`
   - 只需一次主键探针（`revision`/`snapshot_seq`/`active_turn_id`）就能确认缓存是否新鲜，命中即跳过整包 JSON 解码。
   - 上限 2 个会话（当前会话 + 刚离开的那个）；写入路径 `_persist` 显式失效。
   - 轻量 schema（没有 `revision` 列，测试与外部宿主）自动退回原路径，不缓存。

2. **读时修补门控** `snapshot_store.py` + `core_session_store.py`
   - `active_turn_id` 是写入时派生的索引列，「没有活跃回合 + 状态已终态」就证明修补无事可做。
   - 于是 12000 轮的长会话在空闲读时不再走三趟全表；有活跃回合、状态未settle、或老 schema 时照旧全量修补（行为不变）。

3. **按需真正解码 item 行** `snapshot_store.py`
   - 两段式：先读 `(seq, item_id, length(item_json))` 决定预算边界（不解码 JSON），再只取边界内的行。
   - 读预算从 3× 页上限降到 1.5×（`thread_history._page_item_byte_budget`）。

4. **分页构建去掉全量扫描** `thread_history.py`
   - 条目→回合反向索引改为惰性：只有真的遇到没有 `turn_id` 的条目才建。
   - 有 seq 的常规情形直接按已加载条目建时间线，不再遍历整条线程的 order 列表。
   - `total_items` 用存储层给的 COUNT + 顶层用户条目数（两者构造上不相交），不再做两个全量 id 集合的并集。
   - `turns` 只保留本页可见回合（外加活跃回合），按成员判断而不是逐回合扫描。
   - `item_order` 由本页已有条目按 seq 生成。

5. **按消息直接定位** `snapshot_store.load_page_around` + `thread.pageAround`
   - `resolve_item_seq` 同时覆盖 item 行与元数据里的顶层用户条目。
   - 一次有界读返回「以目标条目结尾」的窗口，附 `anchor_item_id/anchor_seq/page_min_seq/page_max_seq`。

6. **会话存在性检查** `core_session_store.exists`
   - 默认可见性规则只看 `owner_plugin`，用 SQLite 的 JSON 提取在 SQL 里回答，不物化整包快照。
   - 宿主自带可见性解析器时保留完整读取（只有它知道要看什么）。
   - `session_record_from_snapshot` 同样接入修补门控，会话列表不再为每行跑全表修补。

7. **会话列表按项目过滤下沉到 SQL** `project_store._project_sessions`
   - 项目归属在会话元数据里，之前是「读出所有项目的所有会话，再在 Python 里过滤」。
   - 改成 `json_extract(... '$.session.metadata.work_root')` 精确匹配，只物化本项目自己的行。
   - 新增 `limit/offset` 与 `count_sessions()`（未加载数量），默认行为不变。

8. **outline 只读正文** `load_items_by_kind` + `thread.outline`
   - 只为取每轮结尾的助手正文，用 `LIKE '%"agentMessage"%'` 在 SQLite C 层过滤，不再解码 95% 的工具输出。

### 前端

9. **投影缓存上界** `workbenchProjection.ts`
   - `partsByItemId` 4000 / `messagesById` 2000 / `itemsApp` 8000 / 子代理 500 / 浅思考 1000，每次投影后丢最旧项。
   - 丢掉的项只是下次重建，语义不变；`selectCoreWorkbenchMessages` 的输出不变。

10. **搜索跳转直接用定位接口** `createWorkbench.loadHistoryAround` + `LamToolsApp.locateMessage`
    - 先问后端目标消息在哪个窗口（一次请求），命中即滚动+高亮。
    - 跳转窗口与当前最新窗口之间若还有未加载的一段，如实提示「上滑可继续加载」，不把两段历史悄悄拼接。
    - 后端不可用或未命中时，退回原来的逐页加载。

## 五、改造前后对比

同一 DB、同一脚本、同一口径。

| 指标 | 改造前 | 改造后 | 变化 |
| --- | --- | --- | --- |
| 首屏加载 P50 | 914ms | 311ms | −66% |
| 首屏加载 P95 | 2008ms | 531ms | −74% |
| 向上分页 P50 | 965ms | 306ms | −68% |
| 向上分页 P95 | 991ms | 343ms | −65% |
| 历史定位 P95 | 不存在（逐页翻） | 305ms | 新增 |
| 历史定位 P95（旧路径等价成本） | 约 965ms × 页数 | — | — |
| outline | 4759ms | 1619ms | −66% |
| 首屏传输量 | 457KB | 457KB | 不变 |
| 全量快照传输量 | 585MB | — | — |
| 首屏相对全量 | — | 减少 99.92% | 目标 ≥90% ✔ |
| 热读分页（进程内） | 374ms | 110ms | −71% |
| 冷读分页（进程内） | 544ms | 272ms | −50% |

进程内冷读拆解（改造后）：元数据解码 176ms + item 读取 94ms + 分页构建 25ms。

验收口径对照：

| 要求 | 结果 |
| --- | --- |
| 首次历史加载 P95 ≤500ms | 531ms（fixture 为要求规模的 2.4 倍）；进程内 272ms |
| 首次历史数据 ≤50 条逻辑消息 | 10 轮 = 10 条用户 + 10 段助手；`item_count` 50（wire 条目） |
| 初次传输量减少 ≥90% | 99.92% |
| 历史消息定位 P95 ≤500ms | 305ms |
| 向上分页无重复、无遗漏 | 游标遍历测试覆盖（`test_thread_page_load.py`） |
| 内存有界 | 元数据缓存 2 个会话、item 读取按字节封顶、前端投影缓存全部有上界 |
| 会话切换/重连不串数据 | 既有 revision/seq 单调校验与合并逻辑未改，相关测试通过 |

## 六、没做完的部分（如实列出）

1. **元数据行仍随条目数线性增长**（12000 轮 → 24.4MB）。`core.item_order` 与每轮的 `items` 列表都在这份 JSON 里，冷读 176ms 的解码就是它。要彻底解决得把 order 移出 JSON，并补「未投影事件回放」以避免崩溃窗口丢数据——这是带迁移的存储改造，本次没做。
2. **前端流式更新仍是「每帧全量选消息」**。`selectChatMessages` 在快照身份变化时重扫已加载的全部条目；`parts`/`message` 有增量缓存，但选择阶段没有。历史上限靠「只加载一页」压住，翻得越多这步越贵。
3. **没有真正的条目级虚拟列表**。现状是 `content-visibility: auto` + `contain-intrinsic-size`，离屏消息不布局不绘制，但 Vue 组件与 DOM 节点仍在。要上 `@tanstack/vue-virtual` 得先解决动态高度与工具过程展开的测量，风险与工作量都不小。
4. **会话列表分页只做了一半**：后端已能按项目在 SQL 里过滤、支持 `limit/offset` 与总数，但侧边栏仍请求整表，没有「加载更多」和「还有 N 个」。
5. **outline 仍是整份返回**（12000 轮 → 3.2MB）。耗时降了 66%，payload 没有分页。
6. **冷读首屏 531ms 略超 500ms 目标**（要求规模的 2.4 倍数据），差距来自第 1 条的元数据解码。

## 七、测试与回归

- 新增后端：`core/tests/test_thread_page_around.py`（5 项，通过）
- 新增前端：`core/ui/tests/core-workbench-projection-cache-bounds.test.ts`（4 项，通过）
- 回归通过：`test_thread_page_load.py`、`test_thread_outline.py`、`test_core_agent_snapshot_store.py`（49 项通过）、`test_run_item_snapshot.py`、`test_app_persistence_host.py` 等
- 前端 13 个相关测试文件、131 项通过（投影缓存、窗口、滚动、控制器、运行时、发送集成）
- 全量代码库存在**与本次无关**的既有失败，已用改造前的文件复核确认：
  - `test_projector_owns_all_generic_app_events`、`test_thread_outline.py::test_session_outline_cli_parser_and_human_output`
  - `LLMConfig.__init__() missing 1 required positional argument: 'provider_id'`（共 4 项，含后端启动占位配置路径）

## 八、复现方式

```bash
# 造 12000 轮 / 4.8 万条目行的长会话（约 30 分钟，库约 1.5GB）
python core/scripts/message_paging/seed_long.py --home E:/LamTools/tmp/perf-message-paging --turns 12000

# 起后端（模型 ID 只为避开无关的 LLMConfig 占位分支）
SUNDAY_CORE_PORT=5919 LAMTOOLS_CORE_MODEL_ID=<模型> \
LAMTOOLS_HOME=<home> LAMTOOLS_CORE_DATA_DIR=<home> \
LAMTOOLS_CORE_DB=<home>/core.db LAMTOOLS_CORE_WORK_ROOT=E:/LamTools \
python core/desktop_backend.py

# 量首屏、分页、定位
python core/scripts/message_paging/bench_history.py --port 5919 \
  --db <home>/core.db --thread perf-long --rounds 5 --pages 5 \
  --locate-item-id perf-long:perf-long:turn:000500:call_00_tool
```
