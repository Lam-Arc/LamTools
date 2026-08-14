# 08 CLI 与入口模块 审计报告

## 1. 概况

本区审计 LamTools Core 的 CLI 与根级入口模块，覆盖 7 个文件共 6224 行：

| 文件 | 行数 | 角色 |
|---|---|---|
| `core/src/lamtools_core/cli.py` | 2785 | Core CLI 主入口（argparse 解析、serve/run/run-local/watch/start 等 30+ 子命令、HTTP LLM 客户端、事件脱敏输出） |
| `core/src/lamtools_core/checkpoint.py` | 1520 | 任务级对话/工作区检查点：保存、回滚、undo/derived 节点、fork、主链修剪 |
| `core/src/lamtools_core/context_compaction.py` | 1186 | 模型背书上下文压缩：分段、合并、结构化摘要、预算拟合 |
| `core/src/lamtools_core/composer_commands.py` | 243 | 编辑器斜杠命令目录装载与解析 |
| `core/src/lamtools_core/skills.py` | 257 | SKILL.md 发现/装载、提示词索引、启用状态持久化 |
| `core/src/lamtools_core/tokens.py` | 85 | token 估算工具 |
| `core/src/lamtools_core/agent.py` | 148 | 子代理共享契约（spec/tool schema） |

审计方式：全程只读（grep/read/python AST 解析校验），未运行 pytest、未执行 CLI 本体、未运行任何写操作。部分结论通过 AST 静态检查与跨模块调用点追踪验证（如 `quote` 未导入、`fast=True` 估算器在 kernel 触发路径的使用、`backup_file` 调用点）。

总体印象：模块结构清晰，checkpoint 的懒捕获 + 内容寻址 blob + 主链修剪设计深思熟虑，压缩分段/合并有明确边界保护，CLI 子命令覆盖完整且大部分有参数校验。主要问题集中在：1 个必然崩溃的未导入符号、回滚边界场景的数据一致性、token 估算对 CJK 文本的系统性低估。

## 2. 问题清单

### cli.py

- **[S2] `attachment upload` 子命令必然崩溃：`quote` 未导入（NameError）**
  - 位置：`core/src/lamtools_core/cli.py:1390`（`cmd_attachment_upload` 内 `quote(args.thread_id, safe='')`）
  - 问题：`urllib.parse.quote` 在文件任何位置都未 import（AST 校验确认：无 `from urllib.parse import quote`，无星号导入可引入该名字）。执行 `core attachment upload <thread> <file>` 时在拼 URL 处抛 `NameError: name 'quote' is not defined`，命令 100% 失败。
  - 影响：上传附件功能完全不可用；且 NameError 不在 `main()` 捕获的异常类型内，会输出原始 traceback。
  - 修复建议：顶部补 `from urllib.parse import quote`，并加一条针对该子命令的冒烟测试。

- **[S3] `main()` 异常捕获不完整，网络类异常输出原始 traceback**
  - 位置：`core/src/lamtools_core/cli.py:2588-2595`
  - 问题：`main()` 只捕获 `(ImportError, OSError, RuntimeError, ValueError)`。所有 live 类子命令（run/watch/start/steer/queue/approval/goal/arrange/workflow 等）经 `_invoke_live` 走 `CoreAppServerClient`（httpx），服务器未启动或请求失败时抛 `httpx.ConnectError` / `TimeoutException`；`cmd_attachment_upload` 的 `response.raise_for_status()` 抛 `httpx.HTTPStatusError`——均非上述四类，直接以完整 traceback 崩溃（退出码虽为 1，但输出风格与 `error: ...` 约定不一致，且可能泄露内部路径）。
  - 影响：错误 UX 不一致；对脚本消费者（`--json`）输出被 traceback 污染。
  - 修复建议：捕获 `httpx.HTTPError`（或更宽泛的 `Exception` 统一转 `error: ...` 输出），保持退出码 1。

- **[S3] `goal`/`arrange`/`workflow` 三组子解析器缺 `required=True`，裸调时抛 AttributeError traceback**
  - 位置：`core/src/lamtools_core/cli.py:930`（goal_sub）、`958`（arrange_sub）、`1013`（workflow_sub）
  - 问题：其余全部 `add_subparsers(..., required=True)`（共 18 处），唯独这三处未设置。执行 `core goal`、`core arrange`、`core workflow`（不带子命令）时 argparse 不报 usage 错误，`args.func` 不存在，`main()` 里 `args.func(args)` 抛 `AttributeError` 原始 traceback。
  - 影响：帮助/用法行为与其余子命令不一致；错误信息不可读。
  - 修复建议：与其余子解析器一致补 `required=True`。

- **[S4] 死代码：`_safe_relative_path` / `_non_empty_line_count` / `_fallback_document`**
  - 位置：`core/src/lamtools_core/cli.py:2768`、`2776`、`2780`
  - 问题：grep 全仓确认三个函数无任何调用点（`_default_run_dir`/`_default_work_root` 有使用）。疑似为早期"proof document"功能残留。
  - 影响：维护负担与误导（`_safe_relative_path` 的路径清洗逻辑易被误认为仍在生效）。
  - 修复建议：删除或恢复其对应功能并接回调用链。

- **[S4] `setup` 子命令 `created` 字段恒为 True**
  - 位置：`core/src/lamtools_core/cli.py:1212-1220`
  - 问题：`ensure_projects_root()` 是幂等 ensure，但输出固定 `"created": true`，即使目录早已存在。
  - 影响：脚本消费者无法据此判断是否新建。
  - 修复建议：由 `ensure_projects_root()` 返回是否实际创建，或改输出 `"exists": true`。

- **[S4] imagegen API key 明文落盘**
  - 位置：`core/src/lamtools_core/cli.py:2244-2247`、`2255-2257`（`cmd_imagegen_config` 写入 `imagegen.jsonc`）
  - 问题：`--api-key` 以明文写入配置文件；help 文本已明示"stored in plaintext"，`cmd_imagegen_show` 也会脱敏显示——属"已知且文档化"的敏感信息入盘，但未提供加密或系统凭据库选项。
  - 影响：本地明文密钥可被任何读取配置目录的进程/备份拿到。
  - 修复建议：至少提示用户文件权限；中长期支持 DPAPI/Keychain 或引用环境变量。

- **[S4] `update check` 在 async 函数内做同步网络调用**
  - 位置：`core/src/lamtools_core/cli.py:2261-2265`（`check_update()` 为同步阻塞调用）
  - 问题：`cmd_update_check` 是 async 函数，`check_update()` 内部发起 GitHub Releases 请求时阻塞事件循环；`asyncio.run` 下虽只有一个任务，但超时控制依赖 `check_update` 内部实现，外部无超时兜底。
  - 影响：网络卡顿时 CLI 无响应时间不可控。
  - 修复建议：`asyncio.to_thread(check_update)` 或为请求设置显式超时。

- **[S4] 默认 `core.db`/`run_dir` 依赖 `_repo_root()`，安装场景路径错误**
  - 位置：`core/src/lamtools_core/cli.py:2726-2732`（`_resolve_core_db`）、`2756-2761`（`_repo_root`/`_default_run_dir`）
  - 问题：`_repo_root()` = `Path(__file__).resolve().parents[3]`，在源码仓库布局下正确（E:\LamTools），但以 wheel/site-packages 安装时指向 site-packages 根，`core.db` 会被写到安装目录（可能无写权限 → OSError，或污染共享安装）。
  - 影响：非仓库环境（pip 安装）下默认 DB/run 目录落点错误。
  - 修复建议：优先 `LAMTOOLS_CORE_DB`/`LAMTOOLS_CORE_DATA` 环境变量与用户配置目录，仓库路径仅作源码模式回退。

- **[S4] `cmd_models_*` 自我导入 `from lamtools_core.cli import _get_model_store`**
  - 位置：`core/src/lamtools_core/cli.py:2104`、`2120`、`2142`、`2175`
  - 问题：模块内部 import 自身，虽能运行（无循环导入错误），但属代码异味，IDE/静态分析易误判。
  - 影响：可维护性。
  - 修复建议：直接调用模块级 `_get_model_store`，删除这四处自导入。

### checkpoint.py

- **[S2] 工作区外文件的备份以绝对路径写入 manifest，导致该检查点回滚必然失败且留下部分应用状态**
  - 位置：`core/src/lamtools_core/checkpoint.py:262`（`backup_file` 中 `relative = ... if _is_within(...) else file_path.as_posix()`）、`1469-1473`（`_safe_workspace_path` 拒绝绝对路径）
  - 问题：`backup_file` 由 kernel 在 `write_file`/`edit_file` 执行前调用（`kernel/loop.py:2150-2173`），工具路径经 `resolve()` 跟随符号链接。当允许 `allow_access_outside_workdir`（或符号链接指向工作区外）时，manifest 键为绝对路径（如 `C:/secret/file`）。回滚时 `_apply_manifest` → `_safe_workspace_path` 对绝对路径必然抛 `ValueError("Checkpoint path escapes workspace")`，该检查点及之后所有回滚全部失败；且同一会话后续备份都会把外部文件追加进该 manifest，回滚永久损坏。
  - 影响：功能破坏 + 数据一致性（见下一条）。
  - 修复建议：外部文件要么跳过备份（记录跳过标记），要么以"工作区外文件"独立命名空间存储，回滚时明确提示不支持/跳过而非整体失败。

- **[S3] 回滚中途失败时工作区补偿无效，留下部分应用状态**
  - 位置：`core/src/lamtools_core/checkpoint.py:435-465`（`load()` 的 try/except 补偿）
  - 问题：`undo = await self._capture(...)` 产生的是懒捕获检查点，`manifest_hash` 恒为 `""`（`_capture` 第 565 行），因此失败分支的 `await self._apply_manifest(undo_row.manifest_hash)` 恒为 no-op（`_apply_manifest("")` 直接返回 `[]`）。若 `_apply_manifest` 应用到一半抛错（如 blob 缺失、磁盘错误、上述路径逃逸），此前已替换的文件保持新内容，而操作被标记为 `failed`，工作区处于"部分回滚"混合状态且无任何补偿记录。
  - 影响：回滚失败后工作区内容不可预期（部分旧、部分新），用户只能手动核对。
  - 修复建议：回滚前先对所有将应用的文件做一次真正的备份（或复用目标 manifest 本身：失败时按 `applied` 列表反向重放目标 blob——因为目标 blob 内容就是"回滚前"的文件内容，逆向替换即可恢复），保证失败路径可逆。

- **[S3] blob 存储无回收机制，且存在孤儿 blob**
  - 位置：`core/src/lamtools_core/checkpoint.py:279-296`（`backup_file` 先写 blob 再查 `_latest_checkpoint`）、`611-692`（`_prune_mainline` 删除 checkpoint 但从不删 blob/manifest）
  - 问题：(a) `_prune_mainline` 删除节点与 restore 操作后，内容寻址 blob 与 manifest 永不清理，会话长期运行后磁盘占用单调增长；(b) `backup_file` 在 `_latest_checkpoint is None`（首个 checkpoint 建立前）时仍把文件写入 blob，随后在 300-302 行静默 return，产生永远无引用的孤儿 blob。
  - 影响：存储泄漏（大文件场景可达 GB 级）。
  - 修复建议：加引用计数/GC（按 `CoreCheckpointBlob` 被 manifest 引用数清理）；`backup_file` 在无最新检查点时跳过写 blob。

- **[S4] `backup_file` 将整个文件读入内存（上限 200MB）**
  - 位置：`core/src/lamtools_core/checkpoint.py:275`（`data = file_path.read_bytes()`）
  - 问题：接近 200MB 的大文件备份时一次性读入内存 + `sha256` + 再写盘，峰值内存 ~2× 文件大小。
  - 影响：大文件编辑时内存尖峰。
  - 修复建议：分块流式读取并增量喂给 hash 与写盘。

- **[S4] `_remove_empty_directories` 可能删除恢复前就存在的空目录**
  - 位置：`core/src/lamtools_core/checkpoint.py:1484-1505`
  - 问题：恢复后向上清理空目录时，不区分"恢复动作创建的空目录"与"原本就存在的空目录"（`rmdir` 只要求为空）。
  - 影响：极少数情况下回滚会顺带删除用户原有的空目录（如刻意保留的空占位目录）。
  - 修复建议：记录恢复前目录是否存在（staging 阶段建目录前先探测），仅清理本次新建的目录链。

- **[S4] `require_inactive` 检查与恢复执行之间存在竞态**
  - 位置：`core/src/lamtools_core/checkpoint.py:1198-1205`（`_require_inactive_session`）、`414-415`（调用点）
  - 问题：先查 `status` 再执行恢复，两者不在同一事务/锁内；期间若有新 turn 启动（写入 runtime_state），恢复会覆盖其状态。
  - 影响：极端并发下回滚覆盖活跃会话状态。
  - 修复建议：把状态检查并入 `_restore_conversation` 的写事务内，或对 runtime 行加行锁。

- **[S4] fork 的 `_replace_session_id` 会误改写消息正文中的会话 id 字面量**
  - 位置：`core/src/lamtools_core/checkpoint.py:1378-1396`
  - 问题：对 events/payload 全量递归替换所有等于 `source_session_id` 或以 `source_session_id:` 开头的字符串，包括用户消息/工具结果正文中恰好包含该 id 文本的内容。
  - 影响：fork 后正文被篡改（概率低但真实存在）。
  - 修复建议：限定替换范围到结构化字段（`session_id`/`thread_id`/`turn_id`/`item_id` 等），正文内容不做字符串替换。

### context_compaction.py

- **[S3] `_fit_replacement_to_limit` 无迭代上限，且 `truncate_text_to_tokens` 的字符切片预算对 CJK/emoji 严重失真**
  - 位置：`core/src/lamtools_core/context_compaction.py:420-446`（`_fit_replacement_to_limit`）、`1163-1168`（`truncate_text_to_tokens`）
  - 问题：`truncate_text_to_tokens` 用 `text[:max_tokens*3]` 估算截断量，仅对 ASCII 近似成立：CJK 文本 3×budget 字符 ≈ 2×budget token（估算 1.5 字符/token），emoji ≈ 6×budget，截断后仍大幅超限；而 `_fit_replacement_to_limit` 的 while 循环没有任何迭代次数保护，依赖 `next_tokens >= after_tokens` 分支二次截断收敛，在截断无效（内容短于 3×budget 字符而 token 估算仍超限）的病理输入下理论上可无限循环（同步循环，阻塞事件循环）。当前路径下"摘要必含 9 个编号章节"（780-781 行的 fallback 兜底）使 `compress_structured_compaction_summary` 通常能收敛，实际触发概率低，但循环本身无护栏。
  - 影响：极端输入下压缩挂起或超限后整体失败（`over_limit`）；CJK 摘要压缩质量不稳定。
  - 修复建议：为 while 加最大迭代次数（如 32）与"连续两次未缩减即放弃"的保护；`truncate_text_to_tokens` 改为按估算 token 数二分截断而非固定 3×字符。

- **[S4] 流式压缩失败时宽泛捕获 `AttributeError/NotImplementedError`**
  - 位置：`core/src/lamtools_core/context_compaction.py:753`
  - 问题：`except (AttributeError, NotImplementedError): content = ""` 将"客户端不支持流式"与"客户端内部真实 bug"混为一谈，静默降级为 `complete` 全量调用。
  - 影响：客户端缺陷被掩盖，且多付出一次完整请求成本。
  - 修复建议：仅对明确的 `NotImplementedError`（未实现 stream）降级；`AttributeError` 应记日志并向上抛。

- **[S4] 压缩各阶段的 `estimate_text_tokens` 与 `estimate_message_tokens` 混用**
  - 位置：`core/src/lamtools_core/context_compaction.py:427`（text 估算）、`425/438/444`（message 估算）
  - 问题：同一预算方程里 `summary_tokens` 用纯文本估算、`after_tokens` 用含每条消息 200 token 开销的消息估算，两者刻度不一致，导致预算减法（`next_budget = summary_tokens - (after_tokens - limit) - 64`）的收敛目标存在系统性偏差（消息开销越大偏差越大）。
  - 影响：压缩结果 token 数可偏离 `limit_tokens` 目标（超限时以 `over_limit` 失败收场）。
  - 修复建议：统一用同一估算器（对摘要文本构造单条消息估算），或显式把固定开销从减法中扣除。

### tokens.py

- **[S2] fast 估算模式对 CJK 文本系统性低估 ~2.1 倍，且被用于上下文窗口触发检查**
  - 位置：`core/src/lamtools_core/tokens.py:18-19`（`fast` 分支 `ceil(len(text)/3.2)`）
  - 问题：fast 模式按 `len/3.2` 估算，而本模块自己的非 fast 校准为 CJK `1.5 字符/token`（第 26-34 行）。对中文为主的消息，fast 低估 3.2/1.5 ≈ 2.13 倍（对"1 中文字 ≈ 1 token"的常见事实则低估 3.2 倍），与 docstring 声称的"±20% acceptable"严重不符。`kernel/loop.py:2673-2682` 的 `_estimate_request_tokens`（`fast=True`）正是用它做 compaction 触发与上下文窗口超限检查。
  - 影响：中文会话中压缩触发阈值实际放大 2 倍以上——上下文已接近窗口时触发检查仍不报警，可能直接向供应商发送超窗请求（400/context-length 错误），或压缩过晚导致质量下降。这是对中文用户（LamTools 主市场）最实际的偏差。
  - 修复建议：fast 模式对 CJK/emoji 单独计权（如 `len` 换成 `ascii*1 + cjk*2.2 + emoji*4` 后再除系数），或直接移除 fast 分支；至少修正 docstring 并给 kernel 触发检查补一个 CJK 权重。

- **[S4] `estimate_message_tokens` 图片 token 硬编码 85**
  - 位置：`core/src/lamtools_core/tokens.py:40`（`image_tokens: int = 85`）
  - 问题：所有图片一律按 85 token 计，与真实多模态 token 数（依分辨率/提供商可从数百到数千）无关。
  - 影响：含图消息的预算估算失真（在触发检查场景与上面的 CJK 偏差叠加）。
  - 修复建议：按图片尺寸/提供商配置传入，或至少把默认值提到真实下限附近并在文档中标注为占位。

### composer_commands.py

- **[S4] 被禁用的 core 命令名进入 reserved_names，同名 skill 被静默丢弃**
  - 位置：`core/src/lamtools_core/composer_commands.py:89-91`（`reserved_names.update(load_disabled_core_commands(member_roots))`）
  - 问题：禁用的 core 命令已从 `commands` 列表过滤（第 70 行），但名字仍占着 reserved 名额，导致同名 skill（或成员命令）被跳过且无任何提示。
  - 影响：用户禁用一个 core 命令后，同名 skill 突然"消失"。
  - 修复建议：reserved 集合只应包含实际生效的 core 命令名，不应包含被禁用者。

- **[S4] 损坏的 command JSON 被静默跳过**
  - 位置：`core/src/lamtools_core/composer_commands.py:204-211`（`_load_definitions`）、`218-221`（`_read_definition`）
  - 问题：JSON 解析失败/字段非法一律 `continue`，用户配置出错时命令目录静默少项，无日志无提示。
  - 影响：排障困难（`command catalog` 少一条命令不知原因）。
  - 修复建议：对存在但解析失败的文件打 warning 日志（含文件名）。

### skills.py

- **[S3] `SkillStateStore` 对损坏状态文件无异常处理，且写入非原子**
  - 位置：`core/src/lamtools_core/skills.py:226-234`（`_load`/`_save`）
  - 问题：`_load` 直接 `json.loads(path.read_text(...))`，无 try/except——`skill_state.json` 被截断/手改损坏时 `JSONDecodeError` 直接向上传播（该 store 在 prompt 装配/插件装配路径上被调用，可导致整个 turn 失败）；`_save` 直接 `write_text`，中途崩溃会留下半个 JSON。对比同文件 `load_disabled_core_commands`（composer_commands.py:182-185）有完整异常保护。
  - 影响：一次异常写入即可让启用状态系统持续崩溃。
  - 修复建议：`_load` 捕获 `(OSError, json.JSONDecodeError)` 回退 `{"skills": {}}`；`_save` 先写临时文件再 `os.replace`。

- **[S4] 技能发现对工作区全树递归扫描**
  - 位置：`core/src/lamtools_core/skills.py:164-169`（`lam_dir.rglob("SKILL.md")`）
  - 问题：`{work_root}/.lam/**` 的 `rglob` 是整棵项目树遍历；`available()`/`signature()` 每次变更都重扫，大型工作区（node_modules 等被排除目录外的海量文件）会拖慢 prompt 装配。
  - 影响：性能。
  - 修复建议：扫描时剪枝常见噪音目录（如 `.git`、`node_modules`），并限制扫描深度。

### agent.py

- **[S4] `SUB_AGENT_TOOL_SPEC` 的 `required` 与 `nullable` 自相矛盾**
  - 位置：`core/src/lamtools_core/agent.py:84-133`（`input_schema`）
  - 问题：`required: ["task", "agent"]`，但 `agent` 的 `type` 为 `["string", "null"]` 且描述明确写着"leave null to use the default sub session"——要求必填却允许空值，schema 语义混乱；`model`/`mode`/`attachments` 同为 nullable 但未列入 required，更凸显矛盾。
  - 影响：消费方（模型/校验器）可能困惑；严格 schema 校验的实现会拒绝 null。
  - 修复建议：`agent` 移出 required（或要求非空 string），与描述一致。

## 3. 该区 Top 3 问题

1. **`core attachment upload` 必然崩溃（NameError: quote 未导入）** — cli.py:1390。一个已发布子命令 100% 失败且输出原始 traceback，属确定性功能缺陷，修复成本一行。
2. **checkpoint 对外部路径文件的备份以绝对路径入 manifest，回滚必然失败且无法补偿** — checkpoint.py:262 与 1469-1473、435-465。凡工具改过工作区外文件（`--allow-outside-workdir` 或符号链接场景）的会话，其回滚功能整体失效，且中途失败会留下"部分回滚"的工作区混合状态，数据一致性风险最高。
3. **token 估算 fast 模式对中文低估 2 倍以上并用于压缩触发检查** — tokens.py:18-19 + kernel/loop.py:2673。对中文用户，上下文压缩/超窗保护的实际阈值被放大 2 倍，可能导致超窗请求失败，属于"估算与真实偏差"中影响面最大的一项。

## 4. 亮点

- **checkpoint 懒捕获设计**：`backup_file` 按需快照 + 内容寻址 blob 去重 + `_safe_workspace_path` 严格逃逸校验（`resolve()` + `relative_to` 双重防护），避免了对巨型工作区的全量扫描，路径穿越防护到位（唯一缺口是外部文件键的处理，见问题清单）。
- **回滚图结构**：undo/derived 节点挂到目标节点之下、主链修剪只计 main turn、`nearest_surviving_ancestor` 重链，注释详尽地解释了"修剪不会减少可回滚目标池"的不变量，设计推理完整。
- **压缩分段与合并**：语义分组（assistant+tool 单元保持完整）、12 轮合并上限、单轮超限即明确报错、本地 fallback 摘要"宁缺毋滥"（不编造事实），边界保护意识强。
- **CLI 参数校验**：`--compact-trigger/limit-tokens` 的正值及大小关系校验在 `CoreCliRunOptions.__post_init__`、`cmd_run`、`cmd_run_local` 三处一致实现；`_positive_timeout_or_none`、`_resolve_thread_id` 等辅助函数干净。
- **敏感信息处理意识**：`events-redacted.json` 对 reasoning 内容做哈希替换、`_mask_api_key` 脱敏显示、`_redact_event` 剥离 raw 字段。
- **tokens.py 非 fast 估算**：按字符类别（ASCII/CJK/emoji/其他）分权计，方向正确，慢路径本身可用。

## 5. 审计范围与方法

- **范围**：`core/src/lamtools_core/cli.py`（2785 行）、`checkpoint.py`（1520）、`context_compaction.py`（1186）、`composer_commands.py`（243）、`skills.py`（257）、`tokens.py`（85）、`agent.py`（148），合计 6224 行，全部逐行阅读。
- **方法**：逐文件通读 + 关键结论交叉验证：
  - AST 静态分析确认 `quote` 未导入（cli.py:1390 为 NameError）；
  - grep 确认 `_safe_relative_path`/`_non_empty_line_count`/`_fallback_document` 无调用点、确认 18 处 `add_subparsers` 中 3 处缺 `required=True`；
  - 追踪 `fast=True` 估算器的调用链（kernel/loop.py:2673-2682 上下文触发检查）、`backup_file` 调用链（kernel/loop.py:2150-2173 write_file/edit_file 前置备份）、`default_core_resource_roots` 调用链（default_agent.py/base_agent.py，验证 `module_root.parents[1]` 在仓库布局下正确指向 `core/`，非问题项）；
  - 校验 `ChatMessage` 为可变 dataclass（`_fit_replacement_to_limit` 的原地赋值合法）；
  - 逐条推演 `_fit_replacement_to_limit` 终止性（正常路径收敛，病理输入存在无护栏风险，定为 S3）。
- **限制**：未运行 pytest/CLI 本体（纪律要求只读），行为类结论基于静态推演；`app/`、`kernel/`、`llm/` 等相邻区域的实现仅作调用点参考，未纳入本区问题清单。
