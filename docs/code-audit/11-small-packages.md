# 11 后端小包合集 审计报告

审计员：第 11 区（后端小包合并审计）
审计日期：2026-08-13
范围：core/src/lamtools_core/ 下的 mem、plugins、mcp、attachment、snapshot、artifact、provider、usage、member、session、prompt、update、project、run_event、skills.py（约 6.1k 行源码，不含 __pycache__）
方式：全程只读，未运行测试、未修改任何代码。

## 1. 概况

按包列出规模与职责（行数为 wc -l 实测，不含空行语义）：

| 包 | 文件 | 行数 | 职责 |
|---|---|---|---|
| mem | `__init__.py`(209)、`store.py`(251)、`memory_file.py`(343)、`dreaming.py`(441) | 1244 | 记忆协议类型、SQLite/内存短期记忆存储、MEMORY.md 长期记忆解析/归并、dreaming 提炼 |
| plugins | `registry.py`(132)、`operations.py`(308)、`engine.py`(272)、`hook_config.py`(155)、`models.py`(119)、`trust.py`(42)、`__init__.py`(52) | 1080 | 插件发现/状态、hook 注册与信任、hook 执行引擎（command/http/mcp/prompt 四类）、插件管理操作目录 |
| mcp | `client.py`(227)、`config.py`(163)、`registry.py`(139)、`schemas.py`(30)、`__init__.py`(15) | 574 | MCP JSON-RPC 子进程客户端（headers/json_lines 双传输）、服务器配置加载、工具注册表 |
| attachment | `service.py`(281)、`files.py`(89)、`http.py`(69)、`store.py`(79)、`__init__.py`(20) | 538 | 附件生命周期服务、文件工具、FastAPI 路由、SQLite 仓库适配 |
| snapshot | `__init__.py`(427) | 427 | 线程快照幂等 reducer（RunItemEvent → 展示态） |
| artifact | `registry.py`(249)、`__init__.py`(19) | 268 | 产物注册表（.lam/artifact/<id>.json，软删除） |
| provider | `__init__.py`(126) | 126 | LLM 提供商配置与注册表 |
| usage | `__init__.py`(110) | 110 | 用量账本协议与内存实现 |
| member | `kit.py`(83)、`manifest.py`(50)、`registry.py`(45)、`__init__.py`(21) | 199 | 成员契约（kit/manifest/注册表） |
| session | `__init__.py`(133) | 133 | 会话/消息存储协议与内存实现 |
| prompt | `__init__.py`(223) | 223 | PromptPart 组装、预算截断 |
| update | `checker.py`(137)、`operations.py`(33)、`__init__.py`(1) | 171 | GitHub Releases 更新检查、版本比较 |
| project | `workflow_store.py`(414)、`__init__.py`(1) | 415 | 文件型工作流存储（目录布局、懒迁移） |
| run_event | `hub.py`(198)、`__init__.py`(109) | 307 | 运行时事件中心（内存日志 + SSE 扇出） |
| skills.py | (257) | 257 | SKILL.md 发现/加载/提示词索引、技能启停状态 |
| **合计** | | **6072** | |

## 2. 问题清单

### S2（中等，4 条）

- **[S2] 附件存储路径未校验 session_id，存在目录逃逸写入；"会话不存在"校验是死代码（attachment）**
  位置：`core/src/lamtools_core/attachment/store.py:17-18`、`service.py:61-67`、`http.py:16-23`、`app/http_agent_app.py:620-627`
  问题：`_CoreAttachmentRepository.session()` 无条件返回 `AttachmentSession(id=session_id, storage_root=data_dir/"attachments"/session_id)`，从不校验会话是否存在（协议签名是 `AttachmentSession | None`，实现永远非 None），因此 `service.create` 中 `raise LookupError("Session not found")` 永远不触发。session_id 直接拼入文件系统路径：实测 `Path(data)/"attachments"/".."` 可上逃一级到 `data/` 根目录；内部调用方（member 应用、CLI，`cli.py:1390` 的 thread_id 经 quote 后原样发送）传入含分隔符的 session_id 时可写入任意目录（`x/../../y` 实测可构造）。文件名本身经 `safe_filename` 消毒，但目录可控。
  影响：未授权/错误会话标识可导致文件写到存储根之外的目录；"会话必须存在"的安全假设不成立。
  修复建议：session_id 使用白名单正则（如 `^[A-Za-z0-9_-]{1,64}$`）校验，拒绝含 `.`、路径分隔符的值；`session()` 应查询数据库确认会话存在后再返回（返回 None 让上层 404）。

- **[S2] 附件上传无大小上限，内存与磁盘可被无界占用（attachment）**
  位置：`core/src/lamtools_core/attachment/http.py:23`（`await file.read()`）、`app/http_agent_app.py:626`、`attachment/service.py:67`（`target.write_bytes(content)`）
  问题：UploadFile 内容被一次性整体读入内存，随后整体写盘；任何环节都没有大小上限（无 Content-Length 校验、无字节数阈值）。
  影响：任意可访问上传接口的调用方可上传超大文件，导致进程内存峰值与磁盘耗尽（DoS）。
  修复建议：在 service.create 入口设最大字节数（如 50MB），HTTP 层校验 Content-Length 并提前拒绝；必要时改为流式写盘（shutil.copyfileobj）而非全量 read。

- **[S2] MEMORY.md 重写会静默丢弃人工编辑的非结构化内容（mem/memory_file）**
  位置：`core/src/lamtools_core/mem/memory_file.py:133-174`（parse 只保留"## 已知五节 + `- ` 开头且匹配 `_ENTRY_RE` 的行"）、`208-225`（write_memory_md 全量重写）
  问题：文件头承诺"可手动编辑；下次 dreaming 以手动内容为基线归并"，但 `write_memory_md` 用解析出的结构化快照做全量重写：人类新增的自定义小节（如 `## Links`）、小节内不匹配条目正则的段落/多行条目/注释行都会在下次 dreaming 写入时被静默删除。此外写入非原子（`Path.write_text` 直接覆盖），崩溃会损坏整份长期记忆。
  影响：长期记忆数据丢失，与"人类编辑是基线"的文档契约直接冲突。
  修复建议：重写时保留未识别的原始行（把快照之外的原文按原样带回）；或改为仅对匹配条目做原地编辑而非全量重写；写入改 tmp+rename 原子替换。

- **[S2] WorkflowStore.delete 跨作用域误删：删除项目工作流可能同时删除同名全局工作流（project）**
  位置：`core/src/lamtools_core/project/workflow_store.py:228-247`（delete 遍历 `_workflow_entries(work_root)` 的全部匹配项）、`51-79`（`_workflow_entries` 无论 work_root 为何都恒包含 home_lam 全局根与 explicit_roots）
  问题：`delete(name, work_root=<项目>)` 的遍历范围是"全局 + 项目"全集，按 `_name_matches` 匹配后把每个位置上的同名工作流全部 `rmtree`。若项目与全局存在同名工作流（`list_grouped` 显示两者可共存），删除项目的一个会连带删除全局的；若项目请求删除的名字只存在于全局，则直接删除全局工作流。
  影响：数据丢失（不可恢复的目录删除）。
  修复建议：delete 仅删除指定 work_root 作用域下的条目（work_root 为 None 时只删全局）；或至少要求调用方显式传 scope 并在返回结果中报告删除的位置。

### S3（轻微，13 条）

- **[S3] 命令型 hook 输出非 JSON 时 JSONDecodeError 未捕获，中断整个工具调用链（plugins/engine）**
  位置：`core/src/lamtools_core/plugins/engine.py:126-133`（`_run_hook` 的 command 分支末尾直接 `self._decision_from_text(text)`）、`202-215`
  问题：http 与 mcp 分支把响应解析包在 try/except 里（`164`、`189`），唯独 command 分支的 `_decision_from_text` 无任何捕获；hook 返回非 JSON stdout 时抛 `json.JSONDecodeError` 一路冒出 `HookEngine.run`。`kernel/loop.py:2223` 等 6 个调用点均未捕获。
  影响：一个输出非 JSON 的可信 hook（常见于手写 shell 脚本）会中断 PreToolUse/PostToolUse 全流程，工具调用直接失败。
  修复建议：command 分支把解析包进 try，失败时按"非 required 则放行并记 audit"处理，与 http/mcp 分支保持一致。

- **[S3] PluginRegistry.discover 单插件损坏即整体失败（plugins/registry）**
  位置：`core/src/lamtools_core/plugins/registry.py:79-86`（discover 无 try）、`88-117`（`_read_manifest` 对 JSON 解析错误与 ValueError 直接抛出）
  问题：任一插件目录的 plugin.json 损坏（JSONDecodeError）或结构非法（ValueError）时，`discover()` 整体抛出；`app/base_agent.py:891` 与 `operations.py:68`（plugin.list）都会因此失败。
  影响：一个坏插件导致全部插件不可见、甚至 agent 组装报错；与 mcp 注册表"单服务器失败不拖垮整体"的隔离设计形成反差。
  修复建议：discover 逐项捕获异常，跳过坏插件并记日志（同 `_load_file` 的文件级容错思路）。

- **[S3] hooks.json 结构错误仍会抛 ValueError，违背"坏文件不拖垮应用"承诺（plugins/hook_config）**
  位置：`core/src/lamtools_core/plugins/hook_config.py:92-105`（`hooks_section` 非 dict、groups 非 list、group 非 dict、handlers 非 list 时 raise）、`139-155`（`float(raw.get("timeout") or 10)` 对非数字 timeout 抛 ValueError）
  问题：`_load_file` 只捕获文件读取层的 OSError/JSONDecodeError，结构层错误全部抛出；`app/base_agent.py:904` 的 `hook_registry.load()` 无保护。一个手误写坏的用户 hooks.json（例如 timeout 写成字符串）会导致 agent 启动失败。
  影响：配置错误引发应用级故障，与注释（"A corrupt or empty hooks file must never take the whole app down"）不一致。
  修复建议：结构校验失败时记 warning 并跳过该事件组/该 handler（或整文件），而非 raise。

- **[S3] JSONC 注释剥离正则误伤字符串内的 `//`（如 URL），合法配置无法保存（plugins/operations）**
  位置：`core/src/lamtools_core/plugins/operations.py:225-228`（`re.sub(r"/\*.*?\*/|//[^\n]*", "", text)`）
  问题：`websearch_config_update` 用该正则做校验；`//` 出现在 JSON 字符串内部（例如 `"url": "https://example.com"`）时会被剥成 `"https:"`，合法 JSONC 校验失败，用户保存配置被拒绝。
  影响：含 URL 的 websearch 配置无法通过 API 保存。
  修复建议：只剥离行首/代码位置的注释（先分词再剥），或改用带注释支持的解析器（如 json5/jsonc 解析库）。

- **[S3] MCPToolRegistry.load 重复调用泄漏旧客户端子进程（mcp/registry）**
  位置：`core/src/lamtools_core/mcp/registry.py:57-73`
  问题：`load()` 对每个 config 新建 `MCPClient` 并 `start()`，直接覆盖 `self._clients[config.name]`；若同一实例上 load() 被再次调用（热重载场景），旧 client 的 MCP 子进程、reader/stderr 任务无人 close，进程泄漏。
  影响：重载场景下 MCP server 子进程累积，资源泄漏。
  修复建议：load 开头先 close 现有 clients（或按 server 名做"已有则跳过/先关后建"）。

- **[S3] MCP read_message 对 Content-Length 无上限，恶意 server 可致内存耗尽（mcp/client）**
  位置：`core/src/lamtools_core/mcp/client.py:193-216`
  问题：headers 传输模式直接 `int(headers.get("content-length"))` 后 `reader.readexactly(length)`，无最大消息长度限制；json_lines 模式对单行长度同样无上限。
  影响：配置的 MCP server（可能指向任意地址）返回超大 Content-Length 或超长行时，进程内存被无界占用。
  修复建议：设置单条消息上限（如 32MB），超限断开并报错。

- **[S3] dreaming 无 LLM 分支：compaction 摘要候选永不沉淀，且存在死代码与注释不符（mem/dreaming）**
  位置：`core/src/lamtools_core/mem/dreaming.py:146-153`（注释宣称"仍可将 compaction summary 沉淀为低置信度 fact"）、`171-179`
  问题：无 LLM 时生成的候选 `confidence=0.4`，随后的 `min_confidence=0.5` 过滤必然将其剔除；即便提高阈值放行，沉淀到 MEMORY.md 的门槛是 0.6，也永远不会写入。`line 153` 的 `result = DreamResult(...)` 是死赋值（后续 return 新建对象）。注释描述的"可以沉淀"实际从未发生。
  影响：无 LLM 配置的部署下，会话压缩摘要永远不会进入长期记忆；注释误导后续维护者。
  修复建议：要么删除该分支并更新注释，要么把摘要候选按 0.6 置信度直接沉淀到 MEMORY.md（不进短期 store）。

- **[S3] dreaming 去重时 metadata["sessions"] 列表无界增长（mem/dreaming）**
  位置：`core/src/lamtools_core/mem/dreaming.py:203`
  问题：`hit.entry.metadata.setdefault("sessions", []).append(session_id)` 每次 re-dream 命中同一记忆就追加一个会话 id，永不清除、无上限，随 JSON 列持久化。
  影响：高频会话下单条记忆的 metadata 持续膨胀，DB 行体积无界增长。
  修复建议：限制列表长度（如保留最近 20 个）或改用 set 去重 + 上限。

- **[S3] mem/store.search 注释与实现不符：注释称 AND 语义，实现是 OR（mem/store）**
  位置：`core/src/lamtools_core/mem/store.py:132-139`
  问题：注释写"split the query into whitespace terms and **AND** them with LIKE %term%"，实现是 `or_(*conditions)`（任一 term 命中即返回）；`InMemoryMemoryStore`（`__init__.py:215-218` 的 `any(...)`）也是 OR。
  影响：dreaming 去重召回过宽，命中更多相似记忆、更易误判"已存在"；注释与行为不一致影响维护。
  修复建议：统一语义（若要 AND 则改用 `and_`），或修正注释。

- **[S3] update.check 同步 HTTP 阻塞事件循环最长 10 秒（update）**
  位置：`core/src/lamtools_core/update/checker.py:62-76`（同步 `httpx.Client`）、`operations.py:24-27`（async handler 内直接调用）
  问题：`check_update` 是同步阻塞调用，`update.check` 操作与 `cli.py:2263` 的异步命令都直接调用；网络慢/超时期间事件循环被占满最多 10s。
  影响：GUI RPC 场景下阻塞期间所有异步请求（含 SSE、心跳）卡顿。
  修复建议：用 `httpx.AsyncClient` + `await`，或 `asyncio.to_thread` 包裹。

- **[S3] RuntimeEventHub 订阅队列仅靠显式 unsubscribe 清理，无 TTL/断连检测（run_event）**
  位置：`core/src/lamtools_core/run_event/hub.py:83-115`
  问题：`subscribe` 把队列注册进 `_queue_registry`/`_session_queues`，只有调用方记得 `unsubscribe` 才会移除；订阅者异常断开（连接中断、未走清理路径）时队列永久滞留，每次 publish 都会向僵尸队列 put（`_try_put` 直到 QueueFull 才停）。
  影响：长期运行下队列对象与内存泄漏，无效 fan-out 持续消耗 CPU。
  修复建议：队列注册附带最后活跃时间戳，提供定期清理；或对 put 失败/满队列的订阅做自动注销。

- **[S3] 事件被 trim 后按 last_event_id 重放静默返回空，客户端丢事件无感知（run_event）**
  位置：`core/src/lamtools_core/run_event/hub.py:166-181`（`_replay_records`）、`183-191`（`_trim_events` 上限 2000）
  问题：客户端带着旧 `last_event_id` 重连时，若该 id 已被 trim 出存储，`_replay_records` 返回空列表，客户端以为"没有新事件"而永久错过中间事件（无 204/错误信号）。
  影响：重连客户端 UI 状态缺失且无任何提示。
  修复建议：last_event_id 未命中时返回一个明确的 gap 标记（如特殊 event 或让上层报错重拉全量）。

- **[S3] 工作流名称 slug 归一化碰撞可致误删/误取（project/workflow_store）**
  位置：`core/src/lamtools_core/project/workflow_store.py:379-405`（`_safe_filename`、`_ascii_slug`、`_name_matches`）
  问题：`_name_matches` 先精确匹配、再 ASCII slug 兜底；非 ASCII 名称全部折叠成下划线（如"lam的小实验"与"lam____"slug 相同），删除/获取时可能命中非预期的同名 slug 工作流。
  影响：多语言命名环境下误删/误取风险。
  修复建议：slug 兜底仅用于 get 的显示侧查找，delete 要求精确名称匹配（或至少返回命中列表让调用方确认）。

### S4（建议，9 条）

- **[S4] compare_versions 数字提取式比较对段数不同的版本误判（update/checker）**
  位置：`core/src/lamtools_core/update/checker.py:44-59`
  问题：`re.findall(r"\d+")` 提取后按段比较，段数不等时短者判旧：实测 `compare_versions("1.0","1.0.0") == -1`、`"0.2.3" < "0.2.3.1"`。当前 `__version__="0.2.3"` 与仓库 `v0.x.y` 标签格式一致故无实际影响，但 tag 格式一旦变化（如 `v1.0`）会误报更新。
  修复建议：改用 `packaging.version.Version` 或补齐段数后比较。

- **[S4] read_text_preview 先全量 read_bytes 再截断（attachment/files）**
  位置：`core/src/lamtools_core/attachment/files.py:67-77`
  问题：`path.read_bytes()[:limit]` 把整个文件读入内存后才取前 200KB，超大文件（GB 级）时造成不必要的内存尖峰。
  修复建议：用 `open()` + `read(limit)` 或 seek 后部分读取。

- **[S4] 附件无删除/清理接口，孤儿文件与 DB 记录只增不减（attachment）**
  位置：`core/src/lamtools_core/attachment/service.py:43-119`（仅 create/list/get/preview/open，无 delete）
  问题：上传文件与 `core_attachments` 行没有删除路径，长期使用磁盘与 DB 无界增长。
  修复建议：补充软/硬删除并联动清理文件。

- **[S4] snapshot seen_event_ids 达到 2000 上限驱逐后，重放旧事件会被重复应用（snapshot）**
  位置：`core/src/lamtools_core/snapshot/__init__.py:52-54`（上限 2000）、`40-42`（去重依据）
  问题：事件 id 列表被截断后，若通过重放（`reduce_run_item_events`/尾部 replay）再次送入已被驱逐的流式 delta 事件，去重失效，`item["deltas"]` 与 content 会重复拼接。
  影响：长时间会话 + 重放场景下文本重复。概率低，建议去重键改用"每 item 最大 seq"而非仅事件 id。

- **[S4] ArtifactRegistry.resolve_artifact_id 用 endswith 松散匹配 attachment id（artifact）**
  位置：`core/src/lamtools_core/artifact/registry.py:181`
  问题：`record.path.endswith(target_id)` 使 `attachment://xabc` 引用 id `abc` 时也可能命中；短 id 易误匹配。
  修复建议：改为精确匹配 `attachment://<id>` 的完整后缀段（`path == f"attachment://{target_id}"`）。

- **[S4] InMemoryUsageLedger 无上限累积（usage）**
  位置：`core/src/lamtools_core/usage/__init__.py:72-103`
  问题：内存账本 `_records` 只增不减，长跑进程内存无界增长。
  修复建议：环形/上限裁剪或说明该实现仅用于测试与短生命周期场景。

- **[S4] 全局 skill 静默遮蔽同名项目 skill（skills）**
  位置：`core/src/lamtools_core/skills.py:42-51`（`if skill.name not in skills` first-wins）、`132-171`（扫描顺序：全局 → 显式根 → 项目）
  问题：同名技能按扫描顺序后者被丢弃，项目内技能被全局技能静默遮蔽，无任何提示；与 workflow 的 `list_grouped` 分组展示策略不一致。
  修复建议：按来源分组或在冲突时记录 warning。

- **[S4] hook_delete 的 hook_id 冒号分段解析在 source_name 含冒号时失效（plugins/operations）**
  位置：`core/src/lamtools_core/plugins/operations.py:161-171`
  问题：hook_id 格式 `source:source_name:event:group:handler:hash`，`parts[2]` 取 event；若插件名/source_name 含 `:`，event 下标错位，删除操作定位到错误位置或报"invalid hook id format"。
  修复建议：用 `split(":", 4)` 限定分段数量，或直接按 hash 段定位。

- **[S4] 状态文件写入非原子且无并发保护（plugins/registry、plugins/trust、skills）**
  位置：`core/src/lamtools_core/plugins/registry.py:44-46`（`_save`）、`plugins/trust.py:18-20`、`skills.py:232-234`
  问题：`write_text` 直接覆盖 JSON 状态文件；并发读写（多进程/多请求）可能产生截断文件或丢更新。同类小文件存储均未用 tmp+rename。
  修复建议：统一改为原子写（tmp + replace）并考虑进程级文件锁。

## 3. 该区 Top 3 问题

1. **附件路径逃逸写入 + 无大小上限（attachment，S2×2）**：session_id 未校验直接拼入存储路径（实测 `..` 与绝对路径段均可逃逸），且"会话不存在"校验为死代码；同时上传无任何大小限制。两者叠加使附件接口成为本地文件系统写入与资源耗尽的敞口。
2. **MEMORY.md 重写数据丢失（mem/memory_file，S2）**：以"人类编辑为基线"的文件，在下一次 dreaming 全量重写时静默删除所有未识别行/自定义小节，长期记忆不可恢复。
3. **WorkflowStore.delete 跨作用域误删（project，S2）**：项目工作流的删除会连带删除全局同名工作流（目录级 rmtree），且无作用域参数与结果反馈。

## 4. 亮点

- **路径穿越防护意识较好**：plugins/registry `_paths`（`registry.py:119-132`）强制 `./` 前缀 + `resolve()` 后 `is_relative_to` 双重校验；artifact `resolve_artifact_id`（`artifact/registry.py:185-199`）对绝对路径做 `relative_to(base)` 边界检查；attachment `safe_filename` 消毒完整（Windows 非法字符全覆盖）。
- **原子写实践**：artifact `_write`（`artifact/registry.py:233-240`）与 workflow `_write_text_atomic`（`project/workflow_store.py:368-372`）均采用 tmp+rename。
- **失败隔离与优雅降级**：MCP 注册表逐服务器 try/except 隔离（`mcp/registry.py:64-70`）；update 检查所有网络/解析失败收敛为 `check_failed` 不抛异常（`update/checker.py:103-109`）；dreaming 对 LLM 与 MEMORY.md 写入失败均返回状态而非 raise（`mem/dreaming.py:163-168, 228-237`）。
- **hook 安全模型清晰**：定义哈希（sha256）+ 信任存储 + pending_review/trusted 状态机（`plugins/hook_config.py:117-134`、`trust.py`）；HTTP hook 对 loopback 与外部环境变量代理做了区分（`engine.py:143-151`）。
- **MCP 客户端生命周期细节**：reader/stderr 独立任务、pending future 在断连时统一置异常、close 有 3s 宽限后 kill（`mcp/client.py:64-79, 144-175`）。
- **快照 reducer 幂等设计**：`seen_event_ids` 去重 + seq 有序插入 + 终端状态不可回退（`snapshot/__init__.py:34-171`），是全区少见的严谨状态机。
- **工作流存储隔离**：节点单文件存储，单个损坏节点不拖垮整个工作流（`project/workflow_store.py:284-296`）；懒迁移失败不破坏原文件。

## 5. 审计范围与方法

- 范围：`core/src/lamtools_core/` 下 mem、plugins、mcp、attachment、snapshot、artifact、provider、usage、member、session、prompt、update、project、run_event 共 14 个包全部源码（含 `__init__.py`）与 `skills.py`，合计 6072 行；不含 `__pycache__`、测试目录与其它区包。
- 方法：逐包 `find/ls` 清点文件 → 逐文件通读（Read）→ 对关键发现用 `grep` 交叉验证调用方（`kernel/loop.py` hook 调用点、`app/base_agent.py` 插件/hook 组装、`app/http_agent_app.py` 附件路由、`cli.py` 更新检查）→ 用只读 `python -c` 实测 pathlib 路径拼接与版本比较边界行为。
- 约束：全程只读；未运行 pytest、未启动任何服务、未修改或创建代码文件；本报告是唯一写入产物。
- 严重度口径：S1=严重缺陷/安全隐患；S2=中等（数据丢失/资源耗尽/越界写）；S3=轻微（异常传播、注释不符、泄漏隐患）；S4=建议。
