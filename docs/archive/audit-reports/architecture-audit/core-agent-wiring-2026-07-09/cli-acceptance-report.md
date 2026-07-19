# Core/Writer CLI 与验收链路审计报告

## 结论

1. Core CLI 是独立 Agent 基础入口。`core.cmd` 只转到 `scripts/core.cmd`，后者直接执行 `lamtools_core.cli`，设置的是 `core/src` 与共享配置库，不经过 `writer.cmd`、`scripts/member_cli.py` 或 `writer_cli`。
2. Core CLI 独立装配 Agent 运行链路：读取共享模型配置，构造 Core 工具箱、插件/Hook、MCP、sub-agent runner、CoreLoopKernel，并把事件写入 Core DB。
3. Writer CLI 复用 Core live client 基础链路。`writer_cli.app_server_client.AppServerClient` 继承 `CoreAppServerClient`，只替换 `/api/app-server` path、client_info，以及 session/project 等 member operation wrapper。
4. Writer 后端仍保留 member overlay，但 Agent 循环已走 Core 下沉后的基础运行骨架。Writer 服务解析 Writer 模型/会话后，把任务交给 CoreLoopKernel 路径，并用 Core runItem 事件回写 CLI/GUI。
5. 两者不是同一个可执行入口：Core CLI 是本地 Core Agent run/session 入口；Writer CLI 是连接 Writer app-server 的 member CLI。它们的基础语义同款：模型/思考/工具/事件/DB 证据都围绕 Core Agent 链路，但返回形态不同。

## 证据文件路径

- `core.cmd`
  - 只调用 `scripts/core.cmd`。
- `scripts/core.cmd`
  - 设置 `PYTHONPATH=%LAMTOOLS_ROOT%\core\src`。
  - 默认共享配置库为 `data/lamtools.db`。
  - 执行 `py -3.14 -m lamtools_core.cli`，无 Writer CLI 路径。
- `core/src/lamtools_core/cli.py`
  - `run_core_cli_task` 独立读取模型配置、构造 Core 工具箱、Hook/MCP/sub-agent runner、CoreLoopKernel，并写入 Core DB。
  - `build_parser` 暴露 `core run`、`core session list/show`、`--core-db`、`--config-db`、`--work-root`、`--shallow-thinking`、`--auto-approve`。
  - `_resolve_core_db` 默认写 `data/core.db`，可用 `--core-db` 或 `LAMTOOLS_CORE_DB` 指向隔离库。
- `core/src/lamtools_core/app/live_client.py`
  - 提供通用 WebSocket JSON-RPC client：initialize、thread/resume、turn.start、approval.respond、turn.cancel、thread.read、command.execute、事件去重。
- `writer.cmd`
  - 只调用 `scripts/writer.cmd`。
- `scripts/writer.cmd`
  - 执行 `scripts/member_cli.py writer ...`。
- `scripts/member_cli.py`
  - Writer member 分发到 `py -3.14 -m writer_cli`。
- `members/writer/backend/writer_cli/app_server_client.py`
  - `AppServerClient(CoreAppServerClient)`。
  - 只换 path 为 `/api/app-server`，并封装 `session.create/list/get/update/delete`、`project.create`、`project.directory.pick` 等 Writer member operation。
- `members/writer/backend/writer_cli/__main__.py`
  - `run/resume/watch` 通过 `AppServerClient` 连接 app-server、调用 `start_turn`、消费 Core runItem 事件。
  - CLI 输出识别 `kind=thinking/message/tool_call/tool_result/status/approval/artifact`。
  - 旧 Writer 私有事件被隐藏，说明展示层已以 Core runItem 为主。
- `members/writer/backend/app/services/writer_service.py`
  - Writer run_turn 解析 session、模型、附件后交给 Core kernel path。
  - model context 中记录 provider/model/thinking/shallow 信息。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py`
  - Writer adapter 使用 CoreLoopKernel。
- `members/writer/backend/app/core/writer/tools.py`
  - Writer 工具箱基于 Core 默认工具箱。
- `docs/plans/core-agent-workbench-foundation-2026-07-09.md`
  - 计划要求 Core live/control 下沉、Writer 成为 adapter、Core DB 与 member DB 分离、真实 Kimi K2.6 验收覆盖 thinking/text/tool/loop/persistence。
- `docs/architecture-audit/core-agent-wiring-2026-07-09/06-final-acceptance.md`
  - 已记录 2026-07-09 的 Core CLI、Writer CLI、Writer GUI 真实验收结果。

## 测试证据

已补跑目标测试：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH='E:\LamTools\core\src;E:\LamTools\members\writer\backend'
py -3.14 -m pytest --import-mode=importlib core/tests/test_core_cli.py core/tests/test_core_live_client.py members/writer/backend/tests/test_writer_cli.py -q
```

结果：`68 passed in 3.76s`。

覆盖点：

- `core/tests/test_core_cli.py`
  - Core parser 暴露 Agent run/session 参数。
  - Core wrapper 不默认使用 Writer DB。
  - Core run 使用 Core kernel tool loop，包含 thinking、text、write_file、两轮模型循环、Core DB 事件/快照。
  - Core session list/show 读取 Core DB。
- `core/tests/test_core_live_client.py`
  - Core app-server client 初始化、resume、事件去重。
- `members/writer/backend/tests/test_writer_cli.py`
  - Writer CLI client 必须继承 Core live client。
  - Writer session/project/plugin/hook/status/result/messages/open-change-file/compact 均走 app-server operation。
  - Writer CLI 按 Core runItem 格式化 thinking、reply、tool、status、approval。

命令风险：

- 直接运行 `py -3.14 -m pytest core/tests/test_core_cli.py core/tests/test_core_live_client.py members/writer/backend/tests/test_writer_cli.py -q` 在当前仓库会出现 pytest collection 导入冲突，报 `ModuleNotFoundError: No module named 'tests.test_core_cli'`。
- 可信补跑命令应使用上面的 `PYTHONPATH` 和 `--import-mode=importlib`，或按仓库现有全量命令分包运行。

## 真实验收证据

Core CLI 证据：

- `.acceptance/core-cli-proof/summary.json`
  - `ok=true`
  - 模型 `Kimi-K2.6` / `xopkimik26`
  - `steps_count=2`
  - `has_reasoning_block=true`
  - `has_text_block=true`
  - `tool_names=["write_file"]`
  - `response_indexes=[0,1]`
  - 文档 `.acceptance/core-runtime/core-proof.md`，37 行
  - DB 为 `E:\LamTools\data\core.db`
- `.acceptance/core-real-db-20260709-131647/summary.json`
  - 同样为 Kimi-K2.6、thinking/text/write_file、两轮、19 行文档
  - DB 为 `.acceptance/core-real-db-20260709-131647/core.db`
  - 这是更强的隔离 Core DB 证据。

Writer CLI 证据：

- `.acceptance/writer-data-fresh-20260709-152615/lamwriter.db`
  - `llm_providers=0`
  - `llm_models=0`
  - `app_settings=0`
  - `writer_app_events=488`
  - `writer_thread_snapshots=1`
  - `writer_sessions=1`
  - 事件包含 `core/runItem`、thinking、tool_call、tool_result、write_file。
- `.acceptance/writer-runtime-fresh-20260709-152615/writer-proof.md`
  - 真实写入文件，超过 10 行。
- `writer_transcript_model_calls`
  - fresh DB 样本包含 `provider=讯飞 MaaS`、`model=xopkimik26`、`status=completed`。
  - metadata 中有 `model_display_name=Kimi-K2.6`、`thinking_enabled=true`、`thinking_budget=10000`。

Writer GUI 旁证：

- `.acceptance/gui-data-20260709-161231/lamwriter.db`
  - 事件同样包含 `core/runItem`、thinking、tool_call、tool_result、write_file。
- `.acceptance/gui-work-20260709-161231/gui-proof.md`
- `.acceptance/gui-proof-completed-20260709-161231.png`

## 对五个问题的回答

1. Core CLI 是否独立：
   - 是。入口、Python module、运行 DB、模型配置读取、工具箱和 CoreLoopKernel 装配都在 Core 侧完成，不依赖 `writer.cmd run` 或 Writer CLI。

2. Writer CLI 是否复用 Core live client/基础链路：
   - 是。CLI 传输层复用 `CoreAppServerClient`，Writer 只保留 member operation wrapper。
   - 后端执行层也走 CoreLoopKernel path，但仍有 Writer adapter、Writer transcript、Writer projection，这是合理 member overlay。

3. 已有 Kimi K2.6 真实验收是否覆盖指定项：
   - 覆盖 thinking block：覆盖，Core summary 与 Writer DB 事件均可见。
   - 覆盖正文 block：覆盖，Core summary 有 text block，Writer proof 文件和 runItem message/tool 事件可证。
   - 覆盖工具调用：覆盖，Core/Writer 均有 `write_file`。
   - 覆盖至少两轮循环：Core 明确 `response_indexes=[0,1]`、`steps_count=2`；Writer fresh DB 的 model call 样本有 response-0/response-1。
   - 覆盖真实文件写入：覆盖，Core 与 Writer 都有 `.acceptance` 下的真实 md 文件。
   - 覆盖独立 DB：覆盖但要分清证据。Core 的 `.acceptance/core-real-db-20260709-131647/core.db` 是隔离 Core DB；Writer 的 `.acceptance/writer-data-fresh-20260709-152615/lamwriter.db` 是 fresh Writer DB，且配置表为空。

4. 还需要补跑哪些命令才能让最终验收可信：
   - 如果最终验收接受 2026-07-09 证据，不必补跑真实 LLM，只需保存本报告和目标测试结果。
   - 如果最终验收要求当前时点可信，建议补跑一组新的 Core + Writer Kimi K2.6 实际任务，使用新 `.acceptance` 时间戳目录，不复用 `data/core.db` 或旧 Writer DB。
   - 必补测试命令：
     ```powershell
     $env:PYTHONUTF8='1'
     $env:PYTHONIOENCODING='utf-8'
     $env:PYTHONPATH='E:\LamTools\core\src;E:\LamTools\members\writer\backend'
     py -3.14 -m pytest --import-mode=importlib core/tests/test_core_cli.py core/tests/test_core_live_client.py members/writer/backend/tests/test_writer_cli.py -q
     ```
   - 建议补跑真实 Core：
     ```powershell
     $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
     $env:PYTHONUTF8='1'
     $env:PYTHONIOENCODING='utf-8'
     .\core.cmd run --model-id xopkimik26 --core-db ".acceptance\core-cli-final-$stamp\core.db" --run-dir ".acceptance\core-cli-final-$stamp" --work-root ".acceptance\core-cli-work-$stamp" --auto-approve --raw "请创建一个超过10行的Markdown文件，必须实际写入磁盘。"
     ```
   - 建议补跑真实 Writer：先用隔离 `LAMWRITER_DATA_DIR` 启动 Writer backend，再执行 `.\writer.cmd run --model-id xopkimik26 --work-root <isolated-work-root> --raw ...`，最后查询 fresh `lamwriter.db` 的配置表计数、`writer_app_events`、`writer_transcript_model_calls`。

5. CLI 入口/返回结果/实现逻辑是否与 Writer 同款：
   - 入口不同：Core 是 `core run/session`，Writer 是 `writer run/resume/watch/session/project/plugin/hook`。
   - 实现逻辑同款的部分：模型配置、thinking 参数、工具调用、CoreLoopKernel、Core runItem 事件、session/read/resume/cancel/approval/command 语义。
   - 返回结果不完全同款：Core non-raw 输出 summary/proof/file；Writer non-raw 输出 live stream 行。raw 模式下 Core 输出 run summary JSON，Writer 输出 app-server event JSON stream。两者不是 byte-for-byte 一致，但验收指标和事件语义一致。

## 缺口清单

1. `core/src/lamtools_core/app/live_client.py` 已提供 Core live client，但 Core CLI `core run` 当前是本地 run summary，不是 app-server live CLI。因此“Core live CLI 与 Writer CLI 同款 app-server 返回”不能由 `core.cmd run` 单独证明。
2. 旧 `06-final-acceptance.md` 写“模型调用表证据”，实际表名是 `writer_transcript_model_calls`，不是通用 `model_invocations`。
3. Writer GUI 验收 DB `.acceptance/gui-data-20260709-161231/lamwriter.db` 不是 fresh config DB，里面有历史模型配置；它只能作为 GUI 旁证，不能证明 fresh Writer DB 配置拆分。
4. 现有真实验收是 2026-07-09 产物；若交付口径要求“当前最新运行仍可用”，需要按新时间戳补跑。
5. 当前目标测试需要 `--import-mode=importlib` 或分包方式运行；裸目标路径命令存在 collection 冲突。

## 建议动作

1. 最终验收报告主引用这四个证据：
   - `.acceptance/core-real-db-20260709-131647/summary.json`
   - `.acceptance/core-real-db-20260709-131647/core.db`
   - `.acceptance/writer-data-fresh-20260709-152615/lamwriter.db`
   - `.acceptance/writer-runtime-fresh-20260709-152615/writer-proof.md`
2. 把 `06-final-acceptance.md` 中“模型调用表证据”改成明确表名 `writer_transcript_model_calls`，避免后续审计误查。
3. 新增或保留一条标准验收脚本，固定做三件事：Core isolated DB run、Writer fresh DB run、SQLite 证据摘要导出。
4. 如果后续要证明“Core live CLI 与 Writer live CLI 完全同款”，需要新增 Core app-server CLI 命令或让 `core run --live` 走 `CoreAppServerClient`。

## 没把握的点

1. 没有重跑真实 Kimi K2.6 任务；本报告复核的是已有 `.acceptance` 证据，加上当前目标测试。
2. 没有启动 Writer backend 做新的 live command 验收；Writer live 可用性依据是 2026-07-09 真实 DB/日志/文件证据。
3. 没有全量运行 `core/tests` 和 `members/writer/backend/tests`；本次只跑了用户点名的三个测试文件。
4. 没有检查所有 frontend Core/Writer workbench 共享模块；本报告范围聚焦 CLI、live client、后端验收链路。
