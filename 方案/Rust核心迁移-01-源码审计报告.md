# Sunday 跨平台 Rust Core 源码审计报告

审计对象：`E:\LamTools`，分支 `codex/plugin-market-0.3.23`，桌面版 0.3.38，手机端 0.1.48。
审计方式：只读源码、数据库结构查询、`cargo check` 实跑。未修改任何正式代码，未改动用户数据。
审计时间：2026-11-02。

本报告只写代码里能证明的事。设计资料里假设的能力，凡是代码中不存在的，一律标为不存在。

---

## 0. 六条结论，先看这里

**结论一：Rust Agent Core 不是从零开始，已经存在 40.7k 行可用实现。**
`core/runtime-rs` 有 33,638 行 Rust，其中 `AgentRuntime` 已实现多轮循环、流式模型调用、工具调用、审批中断与续跑、guidance 插话、hooks、compaction、sub_agent、mcp、skills、provider。`core/mobile/src-tauri` 有 7,123 行，已经在 Android 用 Tauri 2 加 jni 直接跑这个 core，命令包括 `sunday_agent_turn`、`sunday_agent_resume`、`sunday_agent_cancel`、`project_file_*`、`sunday_sub_agent_approval`。

设计资料判断"仓库需要新建 Rust Workspace"，与实际不符。照该判断实施会丢掉 4 万行已验证代码。

**结论二：这个 Rust Core 现在编译不过。**
`cargo check --all-targets` 在 `core/runtime-rs` 直接失败：

```
error: couldn't read `src/../../src/lamtools_core/plugins/bundled/git/plugin.json`: 系统找不到指定的路径
  --> src/plugin_catalog.rs:31:9
```

原因是 `runtime-rs/src/plugin_catalog.rs:31-68` 用 `include_str!` 硬编码引用了 8 个 Python 侧插件文件，而上游提交 `103065a8 refactor(plugin-system): drop the git bundled plugin` 已删除 `git` 插件目录。当前 `core/src/lamtools_core/plugins/bundled/` 只剩 `imagegen / network-exploration / pipeline-checker / plan / study / websearch / workflow`。

这条错误的含义比它本身严重：**所谓共享 Rust Core 在构建期依赖 Python 源码树，且两边已经在漂移**。设计的"双端 CI 全绿"在这一刻不成立。

**结论三：3.6 GB 用户数据库里，1.88 GB 是一张永不清理的同步日志表。**
`data/core.db` 实为 3,676,884,992 字节。按 `dbstat` 实测：

| 表 | 占用 | 行数 |
|---|---|---|
| `core_sync_changes` | 1882.0 MB | 77,396 |
| `core_checkpoint_v2_session_history` | 578.5 MB | 未统计 |
| `core_app_events` | 496.7 MB | 51,621 |
| `core_thread_snapshot_items` | 276.6 MB | 13,144 |
| `core_history_entries` | 110.7 MB | 5,999 |

`core_sync_changes` 表结构是 `seq / change_id / workspace_id / entity_type / event_type / operation / entity_id / thread_id / revision / entity_json / created_at`，`entity_json` 存整份实体快照，平均每行约 24 KB。全仓检索 `core_sync_changes` 的 `delete / prune / trim / cleanup / retain`，零命中，**不存在任何保留策略**。

设计资料写的风险是"55MB 级超长会话快照"。真实量级是单库 3.6 GB、单表 1.88 GB，手机不可能承载，迁移必须先处理这条。

**结论四：`结果未知` 这个状态，Python 和 Rust 两边都没有。**
Python 侧检索 `indeterminate` 全仓零命中，`app/live/recovery.py` 检索 `unknown` 零命中。`app/memory_resume_supervisor.py` 的注释明确写了设计取向："Nothing here guesses. It only resumes a thread whose own recorded state says memory exhaustion"，即不去猜中断状态。

Rust 侧 `AgentRuntime` 的 `TurnProgress` 只有 `Completed` 与 `ApprovalRequired` 两种出口，同样没有未知态。

设计要求的 A07"ToolCall 已发出但回执未知时进入 Unknown，副作用工具不自动重放"，是一条**新增能力**，不是迁移。

**结论五：设计资料说"旧手机版已废弃"，但它在 CI 里是活跃的，而且里面就是 Rust Core。**
`core/mobile` 不是单一技术栈，而是三样东西叠在一起：Capacitor 7 外壳、Tauri 2 宿主 `core/mobile/src-tauri`、以及复用 `core/ui` 的 Workbench 复用层。`.github/workflows/ci.yml` 的 `mobile-android` job 每次推 main 都执行 `tauri android build --apk --debug` 并断言 APK 存在，同时跑 `cargo test --manifest-path core/runtime-rs/Cargo.toml`。

"废弃"必须精确到层：该废弃的是 Capacitor 外壳与 Noise 隧道遥控架构，不能连带丢掉 `mobile/src-tauri` 里那份能跑本机 Agent 的 Rust 宿主代码。

**结论六：设计资料认为 `RuntimeTaskRegistry` 负责排队，实际它只负责拒绝。**
`core/src/lamtools_core/runtime/__init__.py:393` 的 `accept_run(thread_id, run_id, turn_id) -> bool` 是准入闸门，返回 False 就拒绝新 run。真正的排队在 app 层另一套：`core/src/lamtools_core/app/live/queue.py` 与 `app/queue_state.py` 的 `QUEUE_TERMINAL_STATUSES`。

Rust 若要"同一 thread 串行、多余请求排队"，需要自己实现排队，不能照抄 `accept_run`。

---

## 1. Python 后端盘点

规模：`core/src/lamtools_core/` 共 149,812 行 Python。

### 1.1 体量分布

| 模块 | 行数 | 职责 |
|---|---|---|
| `kernel/loop.py` | 5,099 | Agent 主循环 |
| `app/default_agent.py` | 4,011 | 默认 agent 装配 |
| `app/core_db.py` | 3,010 | SQLite 与 38 张表 |
| `tool/default_toolbox.py` | 2,625 | 工具清单与 schema |
| `checkpoint.py` | 2,616 | 检查点 |
| `sub_agent_supervisor.py` | 2,591 | 子代理 |
| `app/http_agent_app.py` | 2,471 | HTTP 面 |
| `llm/profiles.py` | 2,363 | Provider 配置矩阵 |
| `app/base_agent.py` | 2,298 | Agent 基类 |
| `tool/workspace_files.py` | 1,723 | 文件工具 |
| `event/runtime_projection.py` | 1,431 | 事件投影 |
| `app/snapshot_store.py` | 1,399 | 快照 |

### 1.2 Agent 主循环

入口 `kernel/loop.py:638 run()` → `:716 _run()`，主 `while True:` 在 `:909`。每轮顺序是：查取消 `:918`、吃插话 `:938`、应用运行期设置 `:941`、必要时重写历史检查点 `:958`、构上下文与请求 `:964` 与 `:967`、存检查点 `:984`、按需压缩 `:999`、调模型 `:1028`、解析输出 `:1113`、写回复 `:1156`、处理工具批 `:1240` 起、收集并应用新一轮插话 `:1573`、判定 done `:1730-1795`。

关键事实：

- **没有最大轮数上限。** 检索 `MAX_`、`max_steps`、`max_rounds` 在 `kernel/loop.py` 全部零命中。实际上限由 `model_retries: int = 100` 与 `model_timeout_seconds: float = 360.0` 相乘间接产生，最坏情况不可预算。
- **工具执行期间不可取消。** `_execute_tool` 在 `:3464`，`_execute_tools_parallel` 在 `:3975`，两者内部都没有检查取消。
- **审批永不超时。** `app/memory_resume_supervisor.py` 的 `_due_question_request_id` 只对 `question` 工具计算超时，且函数内显式排除其他工具。注释原话是 "An approval never expires"。
- 重试策略在 `llm/retry.py`，`complete_with_retry` 与 `stream_with_retry` 由 `kernel/loop.py:78-84` 导入。

### 1.3 Steer 插话

语义是插入当前 run 的下一轮，不新起 run。整个 run 只有一个 while 循环，插话在循环体内被消费。

状态机是三段式，位于 `runtime/__init__.py:313 RuntimeTaskRegistry`：`staged_guidance_ids` 在 `:303`、`offered_guidance_ids` 在 `:304`、消费在 `:614 consume_guidance`。去重有三道闸：kernel 侧 `known_ids` 在 `loop.py:2951-2960`、registry 侧集合过滤在 `runtime/__init__.py:590-591`、轮首初始名单在 `loop.py:2066-2071`。

时序上"先收后放"：`_collect_guidance` 在 `loop.py:2904` 只读不落地，`_apply_guidance` 在 `:2935` 才写历史。这样保证当前工具批写回完整后插话才落地。插话到来时本批工具结果被改写成 skipped，见 `:1583-1595`。

这套语义清晰、可测，适合作为 Rust 的行为基准。

### 1.4 Stop 取消

双通道。主通道是 `asyncio.Event`，`cancel()` 在 `loop.py:595-601` 置位，轮首在 `:918` 检查，外部事件镜像在 `:603 _is_external_cancelled`。辅通道是 `task.cancel()`，见 `:642` 注释。

取消后持久化由 detached 任务继续保持，`_spawn_external_cancel_persist` 在 `:665`，`await_background_persistence` 在 `:708`。这是"turn 任务立即退出但写库继续"的设计。

### 1.5 并发模型

单进程、单 event loop、纯 asyncio。`kernel/loop.py` 内零锁。全仓 `asyncio.Lock` 都在内核之外，主要集中在 `app/sqlite_write.py:42` 的写序列化、`app/session_actor.py:39` 的每会话 actor 锁。

**跨进程锁不存在。** 检索 `filelock` 全仓零命中。跨进程互斥只靠 SQLite 自身。

### 1.6 审批

待审批只有一个真源：`RuntimeState.metadata["pending_approval"]`，写入在 `loop.py:1364`。没有独立审批表。等待机制不是 await，而是本轮直接收敛为 `decision = "wait"` 在 `:1411`，状态映射为 `waiting` 在 `:176`。

恢复靠 guidance 驱动的新 run，`loop.py:807` 注释原话 "The approval resume path is guidance-driven"。

### 1.7 崩溃恢复

入口 `app/live/recovery.py:362 reconcile_terminal_turns`，由 `app/memory_resume_supervisor.py:283` 每 tick 调用。

恢复策略是保守的：只续跑自身记录为内存耗尽的中断，不猜测静默 turn。这解释了为什么"结果未知"这个概念不存在，因为系统选择不重试而不是选择记录未知。

---

## 2. 工具与扩展层

### 2.1 工具清单

注册入口 `tool/default_toolbox.py:400 DEFAULT_TOOL_DEFINITIONS`，schema 生成在 `:391 _schema`，装配在 `:847 default_core_tool_specs`。

权限是三档 `auto_allow / ask_user / hard_block`，定义在 `tool/permission.py:19-21`。数值风险分级在 `tool/operation_levels.py:14 OPERATION_LEVELS`，未登记默认 3 级；能力上限 `CAPABILITY_LEVELS` 与免问阈值 `AUTO_APPROVE_LEVELS` 在 `:10-11`。

**没有 readonly / destructive 布尔字段。** 设计伪代码里的 `SideEffectClass` 需要新建。

实测内置工具与其风险：

| 工具 | 权限 | 等级 |
|---|---|---|
| `read_file` `list_dir` `search_files` `search_content` | auto_allow | L1 |
| `load_skill` `memory` `library` `search_context` `recall_context` | auto_allow | L1 |
| `list_processes` `kill_process` `git_status` `git_diff` `web_search` | auto_allow | L1 |
| `write_file` `edit_file` `web_fetch` `generate_image` | ask_user | L2 |
| `run_command` | ask_user | L1 到 L3 按命令内容判定 |
| `sub_agent` `sub_agent_message` | auto_allow | L2 |
| `write_checklist` `update_checklist` | auto_allow | L1 |
| `question` | ask_user | L1 |
| `goal` | 视 action | L2 / L1 |
| `arrange` | ask_user | L3 / L1 |
| `mcp` | auto_allow，run 时取目标工具等级 | 视目标 |

### 2.2 文件工具

路径校验 `tool/workspace_files.py:699 resolve_read_resource_path`，越界抛错并转成失败码 `path_outside_root`。越界放行由 `allow_outside` 控制，且必须拿到审批给的一次性授权，见 `tool/outside_access.py` 的 contextvar `outside_access_grant`。

写入是原子的，`atomic_write_bytes` 在 `:197`，临时文件建在目标同目录后 `os.replace`，崩溃不留半截文件。并发按路径加 asyncio 锁，`_get_file_lock` 在 `:244`。

**没有写入备份。** 检索 `backup`、`bak`、`.orig` 在该文件零命中。回滚只靠 `edit_file` 的 unified diff 与版本哈希。

敏感路径拦截在 `tool/approval.py:44 DEFAULT_BLOCKED_FILE_PATTERNS`，覆盖 `.env`、`.git/config`、`id_rsa`、`id_ed25519`、`.ssh/`、`credentials`、`.aws/`。

### 2.3 命令执行

进程层在 `tool/command.py`，shell 解析在 `tool/command_runner.py`。Windows 追加 `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`。shell 解析顺序是 pwsh、PowerShell 5.1、WSL、Git Bash、直接 POSIX，见 `:741-768`。

超时默认 120 秒，超时后杀进程树，Windows 走 Job Object，失败回落 `taskkill /T /F`。输出上限 50,000 字符，超出保留头尾。

**Shell 注入面存在且被代码承认。** `tool/operation_levels.py:44` 原话是 "This is an ordered classification table, not a shell security boundary"。缓解手段是审批加等级上限，不是隔离。

### 2.4 审批策略

总入口 `tool/approval.py:248 ApprovalGate.check`，顺序是硬拦截、操作等级、能力上限、免问阈值。

"总是允许"不是布尔白名单，而是逐级降级。`tool/operation_trust.py OperationTrustStore` 写 `.lam/core/config/config/operation-trust.json`，每次 `lower()` 把等级降 1 且不允许降到 0，跨进程文件锁加 `os.replace` 原子写。

### 2.5 SubAgent

并发上限 `SUB_AGENT_MAX_CONCURRENT_RUNS = 8`，`sub_agent_supervisor.py:40`，配 `asyncio.Semaphore` 在 `:321`。

**工作区不隔离。** `project = Path(self.runner.work_root).resolve()` 在 `:521`、`:578`，子 agent 共享父工作区。

子代理用独立 SQLite，注释在 `:1981` 明确原话 "a core.db lock can never freeze sub-agent lifecycle work"。

### 2.6 MCP

客户端只有 stdio，`mcp/client.py` 用 `asyncio.create_subprocess_exec` 拉起子进程，JSON-RPC 2.0，支持 `Content-Length` 与 `json_lines` 两种帧。检索 `sse`、`streamable_http`、`https` 在该目录零命中，**没有 HTTP 传输**。

配置来源 `mcp/config.py` 的顺序是 `.lam/core/config/mcp.json`、环境变量、调用方路径、插件清单。工作区 `.mcp.json` 被刻意禁用，理由写在 `_config_paths` docstring：否则打开一个仓库即可执行任意命令。

失败处理不重放请求，下次调用重建连接。

### 2.7 插件系统

清单 `plugin.json` 强制字段只有 `name` 与 `version`，其余字段原样保留在 `raw`。

**没有 OS 级沙箱。** `plugin_system/lifecycle.py:212 _load_module` 用 importlib 在同进程加载任意 Python。这是设计现状，不是待修漏洞。

### 2.8 模型配置

Provider 抽象在 `llm/adapter.py`，`LLMAdapter` 协议加 `OpenAICompatibleAdapter`。Provider 定义每 provider 一个 jsonc，优先级是项目 `.lam/config/providers/`、统一 `.lam/core/config/providers/`、遗留 `~/.lam/config/providers/`、内置 `core/config/resources/providers/`。

**API Key 明文写在 jsonc 里。** `api_key` 直接落在 provider 文件，展示时用 `MASKED_API_KEY` 遮盖。检索 `keyring`、`encrypt`、`dpapi` 在该文件零命中。

### 2.9 CLI 覆盖度

`cli_commands/parser.py` 注册 45 个命令组。GUI 有而 CLI 没有的缺口，按检索零命中确认：主题与可视化编辑器、桌宠覆盖层、记忆星图、RAG 索引、检查点回滚、Study 与 Workflow 域操作、QQ 机器人。

---

## 3. 协议与数据层

### 3.1 协议标识

`app/live_protocol.py:9` 定义 `PROTOCOL_VERSION = "core.app_server.v1"`。文件只 111 行，内容是 JSON-RPC 信封：`JsonRpcRequest`、`JsonRpcResponse`、`JsonRpcError`、`InitializeParams`，加三个工厂 `rpc_result`、`rpc_error`、`event_notification`、`snapshot_notification`。

真正的连接状态机在 `app/live_router.py`，1,222 行。

### 3.2 方法面

对外可收方法，按 `app/live_router.py:991 _normalize_method` 的别名表：`thread/resume`、`thread/read`、`thread/history`、`thread/outline`、`turn/start`、`turn/resume`、`turn/pause`、`turn/cancel`、`turn/interrupt`、`turn/terminate`、`turn/stop`、`turn/force_reset`、`turn/steer`、`approval/respond`、`session/permissions/set`、`session/composer/set`、`queue/create`、`queue/update`、`queue/delete`、`queue/guide`。

别名映射值得注意：`turn/stop` 与 `turn/terminate` 同义，`turn/interrupt` 与 `turn/cancel` 同义，而 `turn/pause` 是另一回事。桌面的单击发 `turn/pause`，长按确认发 `turn/terminate`。

对外推送通知：`turn/accepted`、`turn/started`、`turn/steered`、`turn/paused`、`turn/interrupted`、`thread/snapshot`、`thread/gap`、`approval/request`、`approval/busy`、`session/created`、`session/updated`、`session/closed`、`session/rollback`、`tools/result`、`tools/call`、`tools/list`、`subagent/closed`、`subagent/rejected`、`subagent/unavailable`、`model/unavailable`、`model/ambiguous`、`config/schema`、`config/io`、`config/busy`、`config/corrupt`、`config/conflict`、`config/unavailable`、`tool/denied`、`tool/restricted`、`tool/unavailable`、`core/event`。

### 3.3 丢帧补偿

`live_protocol.py:15` 定义 `THREAD_GAP_METHOD = "thread/gap"`。它是可靠控制通道上发的一条通知，告知客户端该 thread 的 runItem 帧在丢帧通道被丢弃，客户端应从自己的 revision 恢复，而不是等下一个全量快照。

`live_router.py` 里的实现点：丢帧记录 `_record_outbound_drop:456`、调度 `_schedule_outbound_gap:473`、发布 `_publish_outbound_gap:494`、双通道判定 `_is_control_outbound:1138`。

这套"有损事件通道加可靠控制通道"是本仓库真实存在且成熟的设计，Rust 侧必须原样复刻，不能简化为单一 WebSocket。

### 3.4 数据库

`app/core_db.py:83 CORE_SCHEMA_VERSION = 3`。版本存在 `core_db_metadata` 表的 `schema_version` 键，读取在 `:2348`，写入在 `:2358`。

实测 `data/core.db` 有 38 张表。核心表：`core_app_events`、`core_thread_snapshots`、`core_thread_snapshot_items`、`core_runtime_sessions`、`core_turn_control`、`core_turn_runs`、`core_turn_interactions`、`core_turn_intents`、`core_turn_jobs`、`core_agent_runs`、`core_history_entries`、`core_checkpoints`、`core_checkpoints_v2`、`core_sync_changes`、`core_projects`、`core_attachments`、`core_artifacts`。

迁移方式不是数据库级迁移脚本，而是"补列幂等"，见 `:2373` 注释与 `:2412` 的 `PRAGMA table_info` 循环。特点是每次打开都兜一遍补列，代价只是一次 PRAGMA。

写序列化在 `app/sqlite_write.py:42`。PRAGMA 设置：`busy_timeout`、`journal_mode=WAL`、`synchronous=NORMAL`。注释里记录了实测成本：一次 `PRAGMA synchronous` 在 I/O 压力下要 0.4 到 1.4 秒，见 `:74`。

### 3.5 数据风险分级

| 级别 | 风险 | 证据 | 后果 |
|---|---|---|---|
| P0 | `core_sync_changes` 无保留策略，已 1.88 GB | 表结构含 `entity_json` 全量快照，全仓检索无 prune | 持续增长，手机无法承载，迁移时复制成本不可控 |
| P0 | 3.6 GB 单库文件 | `ls -la data/core.db` | 备份、校验、迁移都需要数分钟级 I/O，测试必须用克隆而非原地 |
| P1 | 无跨进程写锁 | 检索 `filelock` 零命中 | 新旧后端若同时启动会互相覆盖，切换必须硬性保证单写者 |
| P1 | 无"结果未知"状态 | `indeterminate` 零命中 | 非幂等工具崩溃后会被重新执行 |
| P1 | API Key 明文 | `config/provider_store.py` 读 `data.get("api_key")` | 手机与远程场景下密钥传播风险，设计明确禁止 |
| P2 | 迁移靠补列而非版本脚本 | `core_db.py:2373`、`:2412` | 回滚到旧版时新列残留，需验证旧版能容忍 |
| P2 | 事件与检查点无事务绑定 | `loop.py:1159` 与 `:1185` 各自独立 | 崩溃可能产生事件与历史不一致 |

---

## 4. 前端与宿主

### 4.1 前端技术栈

`core/ui` 是 Vue 3.5 加 Vite 8 加 TypeScript 6，无第三方 UI 框架，样式是自研 CSS 变量 token。`pinia` 只在 `core/desktop`，`core/ui` 里没有。

状态中枢是 `core/ui/src/appServer/store.ts`，90.8 KB；投影在 `workbenchProjection.ts`，26.7 KB；选择器 `selectors.ts`，44.7 KB；决策池 `pendingDecisions.ts`，25.3 KB。

协议类型唯一来源是 `core/ui/src/appServer/protocol.ts`，278 行，`CORE_APP_SERVER_PROTOCOL_VERSION = 'core.app_server.v1'` 在首行。

组件 126 个 Vue 文件，`MessageView.vue` 205.9 KB 为最大单体。

### 4.2 传输

不是 HTTP 轮询。`core/ui/src/transport/directTransport.ts` 用 `new WebSocket` 走 JSON-RPC，同时组合 `DirectHttpTransport` 处理二进制与上传。默认地址从 `defaultAppServerWsUrl(apiBase, token)` 推出，token 走 `Authorization: Bearer`。

`appServer/client.ts` 只依赖 `LamToolsTransport` 接口，所以传输层可替换。这一点对手机端关键。

### 4.3 Tauri 桌面宿主

`core/desktop/src-tauri` 2,572 行。`main()` 在 `main.rs:794`，`start_backend` 在 `:1066`，`wait_for_health` 在 `:1368` 手写 HTTP 探测，超时 90 秒。

后端是外部进程，三种来源：dev 走 `dev_python_executable()`，`:1147`；另一种走 `Command::new("py")`，`:1191`；打包态走 `Command::new(&backend_exe)`，`:1240`。端口由 `TcpListener::bind("127.0.0.1:0")` 在 `:1364` 动态取空闲端口。

**没有 sidecar 机制。** `Cargo.toml` 无 `tauri-plugin-shell`，`tauri.conf.json` 无 `externalBin`。后端靠 `"resources": { "../../dist/SundayCore": "sunday-backend" }` 随包投递再手动 spawn。

**没有进程内重启后端的能力。** 全文件只有一条相关注释，在 `:1155`，说 `core.db` 被锁时 Tauri dev 重启是全量重启。

Windows 安装包不走 Tauri NSIS，走自有 Inno Setup，见 `.github/workflows/release.yml` 调 `core/desktop/installer/build-installer.ps1`。

### 4.4 测试

| 层 | 规模 | 位置 |
|---|---|---|
| Python pytest | 350 个文件 | `core/tests/` |
| 前端 vitest | 262 个文件 | `core/ui/tests/` |
| Rust 集成测试 | 6 个文件 | `core/runtime-rs/tests/` |
| 桌面 node 测试 | 6 个 `.mjs` | `core/desktop/tests/` |

最有价值的黄金基准是这四组，因为它们不碰 Python 内部实现：

1. `core/ui/tests/core-app-server-store.test.ts` 83.7 KB，事件到状态的归约
2. `core/ui/tests/core-app-server-workbench-projection.test.ts` 37.3 KB 加 cache 与 window 两个附带测试
3. `core/ui/tests/core-app-server-selectors.test.ts` 37.2 KB
4. `core/tests/test_core_http_agent_app.py` 59.4 KB 与 `test_core_agent_snapshot_store.py` 50.2 KB

不宜作基准的：`test_core_live.py` 164 KB、`test_backend_module_split.py`、`test_backend_deep_split.py`、`test_architecture_review_fixes.py`。这些测的是 Python 内部结构，Rust 化后天然失效。

`test_core_live_client_e2e.py` 是唯一真实 WebSocket 端到端，但 `ci.yml` 注释承认缺 server extra 时会被静默跳过。

### 4.5 CI

`.github/workflows/` 两个文件。

`ci.yml` 四个 job：`backend` 跑 pytest、`frontend` 跑 typecheck 加 test:contract 加 build、`mobile-android` 跑 `cargo test` 加 `tauri android build --apk --debug` 并断言 APK 存在、`desktop-linux` 跑 `package-linux.sh`。

`release.yml` 21.4 KB，tag 触发。它的版本一致性断言覆盖 5 处：`lamtools_core/__init__.py`、`tauri.conf.json`、`Cargo.toml`、`core/desktop/package.json`、`core/pyproject.toml`。

存在问题：`mobile-android` job 的 `cargo test` 在当前分支会因 `include_str!` 缺失直接失败。也就是说"共享核心改动都触发 CI"这条，机制在，但状态是红的。

---

## 5. 已有 Rust 资产实测

### 5.1 结构

`core/runtime-rs` 33,638 行，`Cargo.toml` 声明包名 `lamtools-runtime`，描述 "Shared Sunday Agent runtime for desktop and mobile hosts"。依赖含 `rusqlite bundled`、`tokio`、`reqwest rustls`、`async-trait`、`regex-lite`，**没有 tauri 依赖**，这一点符合"Core 独立于 Tauri"的要求。

模块：`provider.rs` 4,493 行、`study.rs` 3,607、`workflow_document.rs` 2,435、`lib.rs` 2,388、`study_notes.rs` 2,185、`study_exams.rs` 1,955、`workflow_ops.rs` 1,472、`sub_agent.rs` 1,108、`hooks.rs` 923、`web_search.rs` 897、`project_tools.rs` 852、`profiles.rs` 851、`skills.rs` 811、`mcp.rs` 796、`compaction.rs` 683、`image_gen.rs` 565、`plugin_catalog.rs` 474。

### 5.2 AgentRuntime 真实能力

`lib.rs:498 AgentRuntime<M, T>`，泛型于 `ModelBackend` 与 `ToolRuntime`。装配器：`with_hook_executor`、`with_guidance_source`、`with_progress`、`with_tool_observer`。

出口 `run_turn` 在 `:549`，`run_turn_progress` 在 `:558`。返回 `TurnProgress`，只有 `Completed` 与 `ApprovalRequired`。

已有类型：`TurnRequest`、`TurnResult`、`TurnContinuation`、`ApprovalRequest`、`ApprovalResponse`、`ApprovalDecision`、`AgentContext`、`DeviceCapabilities`、`TurnOptions`、`Message`、`ToolCall`、`ToolDefinition`、`ToolPermission`、`ImageInput`。

`TurnContinuation` 含 `tool_rounds`、`identical_tool_results`、`hook_audit_events`、`runtime_warnings`、`compaction`。这说明防止工具结果重复的机制已经在 Rust 侧存在，字段带 `identical_tool_result_window` 注释。

### 5.3 Android 宿主真实能力

`core/mobile/src-tauri` 依赖 `lamtools-runtime` 加 `jni 0.22` 加 `rusqlite bundled` 加 `tauri 2` 加 `rustls-platform-verifier`。`lib.rs` 4,990 行。

已注册的 Tauri 命令覆盖：`sunday_agent_turn`、`sunday_agent_resume`、`sunday_agent_cancel`、`sunday_sub_agent_approval`、`sunday_sub_agent_list`、`project_file_list`、`project_directory_browse`、`project_file_read`、`project_file_read_raw`、`project_file_write`、`project_file_delete`、`project_directory_create`、`project_directory_delete`、`sunday_attachment_*`、`sunday_artifact_*`、`sunday_checkpoint_*`、`sunday_goal_*`、`sunday_skill_*`、`sunday_hook_list`、`sunday_model_reasoning_declaration`、`sunday_tool_catalog`、`sunday_plugin_*`、`secure_storage_*`、`sunday_update_*`、`lan_discovery_discover`、`local_state_read`、`local_state_write`、`mobile_diagnostics_share`。

`cancellation.rs` 实现了按 turn_id 的取消登记，带 60 秒 latched 取消与 256 条上限，注释解释了"注册与取消持同一把锁，所以取消要么看到活跃 turn 并唤醒它，要么留下 latch 给尚未注册的命令"。

### 5.4 Android 原生层：两套工程并存

`core/mobile` 下有两套完全独立的 Android 工程，这是收口的关键事实。

第一套是 Capacitor，在 `core/mobile/android/`，`capacitor.config.ts` 里 `appId: 'com.lamtools.mobile'`，另有 `core/mobile/ios/`。

第二套是 Tauri，在 `core/mobile/src-tauri/gen/android/`，包含 6 个自有 Kotlin 插件：

| Kotlin 文件 | 职责 |
|---|---|
| `LamToolsSecureStoragePlugin.kt` | 安全存储，`secure_storage_*` 命令的落点 |
| `LamToolsAttachmentOpenPlugin.kt` | 用系统应用打开附件 |
| `LamToolsDiagnosticsSharePlugin.kt` | 诊断包分享 |
| `LamToolsLanDiscoveryPlugin.kt` | 局域网发现 |
| `LamToolsShellPlugin.kt` | 外壳能力 |
| `LamToolsWindowInsetsPlugin.kt` | 软键盘与系统栏内边距 |

Rust 侧通过 `run_mobile_plugin` 调用，`MobileSecureStorage` 包装 `PluginHandle` 在 `lib.rs:247`。

**没有 SAF 插件。** 检索 `OpenDocumentTree`、`takePersistableUriPermission`、`content://` 在 `core/mobile/src` 与两套 Android 工程里全部零命中。设计要求 B04 未开始。

**没有通知插件。** `core/mobile/src/native/notifications.ts` 的 `notifyMobile` 是空实现，函数体只有一条注释："APNs/FCM adapters are added in the Capacitor native projects"。而 Capacitor 工程正是要废弃的那一套，所以 Tauri 路径上通知实际不可用。

**Checklist 在 Rust 侧已有。** `runtime-rs/src/plan_tools.rs:333` 定义 `write_checklist`，`:373` 定义 `update_checklist`，`:452` 声明为 `ToolPermission::AutoAllow`。文件头注释说明它与桌面 `tool/default_toolbox.py` 的语义对齐。

### 5.5 持久化真相

手机端状态**不是事件溯源**，而是整份 JSON 覆写。`local_state` 表结构是 `CREATE TABLE local_state (id INTEGER PRIMARY KEY, state_json TEXT NOT NULL)`，见 `lib.rs:4518`。分作用域版本是 `local_state_scopes` 与 `local_state_active`，见 `:3301` 与 `:3306`。

`mobile/src/storage/Database.ts` 顶部注释原话："Tauri owns durable mobile state. Keeping the SQLite connection and writes in Rust avoids WebView-origin changes or renderer failures silently moving projects and sessions into volatile browser storage."

真正用 rusqlite 的只有四个文件：`artifacts.rs`、`checkpoints.rs`、`goals.rs`、`lib.rs`。`checkpoints.rs` 顶部注释说明检查点只标回合边界，永不回退文件。

对话历史是每轮由前端作为 `payload.history` 传入 Rust，Rust 无会话日志表。这意味着：

- 没有 append-only 事件日志
- 没有 seq 单调序列的服务端权威
- 没有命令收据与幂等键
- 整份状态覆写在会话变长后是 O(n) 写放大

设计要求 A03、A07、A09 全部落在这里。这是移动端最需要补的一块。

### 5.6 前端与 Rust 的接线

`core/mobile/src/native/rustAgent.ts` 里 `invoke('sunday_agent_turn')` 在 `:479`，`invoke('sunday_agent_resume')` 在 `:543`。流式走 `listen('sunday-agent-stream')` 事件，阶段走 `emit_agent_stage`。

`core/mobile/src/standalone/` 有 15 个文件，说明本机独立模式已经成型：`StandaloneTransport`、`StandaloneConfigStore`、`StandaloneProjectClient`、`StandaloneArtifacts`、`StandaloneCheckpoints`、`StandaloneGoals`、`StandaloneExtensionsStore`、`StandaloneArrangeStore`、`StandaloneWorkspaceSearch`、`StandaloneSessionExport`、`StandaloneStateStorage`、`StandaloneUpdate`、`planLibraryScan`、`pluginSchema`。

同时 `core/mobile/src/connection/` 有 `NoiseSecureWire`、`TunnelProtocol`、`TunnelTransport`、`RemoteTransport`、`LanDiscovery`、`ConnectionManager`，说明遥控模式也在。

**两种模式并存，这就是需要收口的地方。**

---

## 6. 设计资料与实际代码的差异清单

| 设计资料的判断 | 实际代码 | 处理建议 |
|---|---|---|
| 需要新建 Rust Workspace | 已有 33.6k 行 runtime-rs 加 7.1k 行 Android 宿主 | 改造现有，不重建 |
| `runtime/` 有 RuntimeTaskRegistry 负责取消、Steer、活动执行 | 存在，但只做准入拒绝不做排队 | Rust 需补排队 |
| 旧手机版已废弃 | 三层混装，CI 仍在构建，内含本机 Agent | 只废弃 Capacitor 外壳与隧道架构 |
| 现有快照 55MB 级 | 单库 3.6 GB，单表 1.88 GB | 迁移前必须先解决 sync_changes 增长 |
| 工具状态设计为 Prepared 到 Unknown | 两栈都没有 Unknown | 新建能力 |
| 事件 seq 单调、可断线补拉 | Python 有 `thread/gap` 加双通道，Rust 无事件日志 | Rust 照抄 Python 的 gap 机制 |
| 插件可声明式跨端 | Python 插件是同进程任意代码，无沙箱 | 跨端插件必须重新定义边界 |
| API Key 存 OS 安全存储 | 目前明文 jsonc | 移动端必须先做密钥库 |

---

## 7. 审计边界与未验证项

以下是本次没有验证、不得当成已通过的部分：

- 未在 Android 真机运行任何构建产物。`mobile-android` 的历史构建结果不构成本次证据。
- 未跑 pytest 与 vitest 全量。当前分支 `cargo check` 已失败，不能声称 CI 绿。
- 未测 100 次断线重连、100 次进程终止，这些是设计目标不是实测结果。
- 未核对 Android SAF 支持情况，代码中未见 SAF 授权目录实现，`project_directory_browse` 是基于普通路径的。
- 未检查 `core/remote/relay` 的公网部署状态与密钥管理，仅确认目录存在与文件清单。
- 未验证许可证合规，仅确认 `runtime-rs/Cargo.toml` 依赖为 MIT 或 Apache 系主流库。
