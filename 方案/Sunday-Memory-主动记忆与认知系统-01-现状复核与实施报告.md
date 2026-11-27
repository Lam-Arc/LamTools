# Sunday Memory · 主动记忆与认知系统 — 01 现状复核与实施报告

> 对应 PRD：`方案/Sunday-Memory-主动记忆与认知系统-PRD-V1.0.md`
> 设计说明：`方案/Sunday-Memory-主动记忆与认知系统-02-设计说明.md`
> 复核：2026-11-25；实施与两轮补测：同日晚

## 一、现状复核（代码事实）

| PRD 关注点 | 现有实现 | 结论 |
| --- | --- | --- |
| 是否已有 memory.md | 没有。`core/src/lamtools_core/mem/` 只有 `library.py`（目录式记忆库）与 `context.py`（记忆来源快照） | 新建 L1 文档，但长在现有库里 |
| 存储结构与作用域 | `global` = `<core_config_dir>/memory/`；`project` = `<work_root>/.lam/memory/`。均为纯 Markdown 文件目录 | 直接复用；memory.md 放各自档位根目录 |
| INDEX.md 生成与注入 | `library.render_index()` 从目录树生成并原子落盘；`ProjectContextLoader.load()` 以 prompt part 注入 | 复用注入点，在索引前插入核心认知块 |
| 记忆读取工具 | `memory` 工具，路径沙箱在 `resolve_memory_path` | 复用；为 memory.md 增加版本快照、CAS 与写入上限 |
| 历史会话读取 | 会话条目在 snapshot store，`thread_outline.build_thread_outline()` 能产出每轮「用户提示 + 助手答复」 | Dreaming 复用它，不碰工具噪声 |
| 后台任务机制 | `_spawn_live_background`、`MemoryResumeSupervisor`、`session_autotitle` | 复用，未新建调度框架 |
| 旁路模型调用 | `context.host.llm_client` + `resolve_scene_model(SCENE_BACKGROUND)` | Dreaming 复用「后台任务」这一档模型 |
| 设置 | `settings.jsonc` 两级命名空间 | 新增 `core.memory`，缺省开启 |
| 系统提示词冻结与缓存 | `prompt/movable.py`：同一压缩周期内冻结首版文本，变化只追加尾部通知 | 核心认知直接进入这套机制 |

## 二、差距（实施前）

1. 没有 L1 核心认知文档，新会话对用户零认知。
2. 没有后台整理，记忆只能靠用户或模型当场写入。
3. 没有「忘记」的防复活记录。
4. 核心文档没有版本历史；写坏只能靠外部备份。

## 三、设计与取舍（已按评审收敛）

### 3.1 memory.md 是档位根目录里的真实文件

- 全局 `<core_config_dir>/memory/memory.md`；项目 `<work_root>/.lam/memory/memory.md`。
- 纯 Markdown、可直接编辑、随目录备份迁移。
- 从 INDEX.md 与普通条目列表排除（避免重复注入与重复展示），`memory` 工具可直接读写。
- 每次写入先快照旧内容到 `<档位>/.versions/`（保留 20 份），`memory.core.restore` 可回滚。
- 删除语义 = 清空（版本保留）；重命名被拒绝；超过读取上限的写入被拒绝（否则「写得进、读不回」）。

### 3.2 注入

- `ProjectContextLoader` 在索引块之前追加两个 `kind="memory"` 块：全局（priority 14）、项目（priority 19）。
- 正文带层级声明：记忆是辅助背景、不是系统指令；与用户当前表达冲突时以当前表达为准。
- 每档 4000 字符是**异常兜底**（正常体量由整理控制），触发截断时会在正文里说明。
- 关闭开关时不注入；INDEX.md 注入保持不变。

### 3.3 认知允许整篇演进；用户可置顶；版本兜底

评审意见：不能让「保护手写内容」妨碍认知演进，否则手写段与自动段会长期各说各话。

- Dreaming 每次整篇重写 `memory.md`：合并重复、替换过时结论、消解矛盾。
- 用户把内容放进 `<!-- memory:keep:start -->…<!-- memory:keep:end -->`，自动改写原样保留（`merge_core_document`）。
- 每次改写前留版本，记忆页可恢复——被替换掉的内容找得回来。
- 不再有「自动段 / 手写段」两套所有权。

### 3.4 增量与成本

- 游标：`<档位>/.dreaming/state.json` 记录每个会话整理到的回合序号。
- **字数只控制频率**：回合结束触发时，新内容太少就延后（`waiting_for_more`），定时扫描会把短内容补上，不丢。
- 同档位整理间隔 ≥ 15 分钟；单次 ≤ 40 轮 / 12000 字符；一次整理 = 一次后台模型调用。
- 触发：回合结束（分离任务）、每 10 分钟兜底扫描、记忆页「立即整理」。

### 3.5 可靠性

- **并发写**：`write_core_document(..., expected=…)` 比较并交换；冲突时基于最新内容重算（最多 3 次）。
- **进程内单通道**：一次只允许一个整理在跑（不同项目的整理也可能同时写全局档）。
- **档位文件锁**：`.dreaming/lock`（O_EXCL，10 分钟视为陈旧并可回收）。
- **失败不落盘**：解析失败/模型失败只记 `last_error`。
- **关闭即停**：开关在写入前再确认一次，运行中关闭则丢弃结果。
- **敏感信息**：按行丢弃密钥/密码类内容。
- **状态损坏**：`state.json` 坏了回落默认值（丢进度，不丢记忆）。
- **「忘记」**：删除记忆（工具、界面、RPC）都记墓碑，整理提示词禁止恢复；做到合理可靠，不做语义追踪系统。

### 3.6 明确不做

- 不建第二套记忆库、不换存储后端、不引入向量库。
- Dreaming 不删除独立记忆文件。
- 不做专门的导入/导出界面（目录可迁移 + 版本恢复）。
- 不新增整理模型的独立配置（复用「后台任务」）。

### 3.7 与 Prompt Cache 的关系

- 日常记忆更新：头部冻结、只追加一条尾部说明，同一次变化只说一次。
- 只有三种时刻重建头部：新会话、上下文压缩、**开关切换**（评审要求：关闭必须真的生效）。
- 相同内容重复整理是空操作，不写文件、不出版本、不发通知。

## 四、实际改动

### 后端

| 文件 | 改动 |
| --- | --- |
| `core/src/lamtools_core/mem/library.py` | 核心文档常量与 CRUD、版本快照/恢复、置顶段合并（`merge_core_document`/`pinned_blocks`）、注入预算、CAS 写入、写入上限；索引/列表排除 memory.md |
| `core/src/lamtools_core/mem/settings.py`（新） | `core.memory` 开关，缺省开启 |
| `core/src/lamtools_core/mem/dreaming.py`（新） | 状态/游标/墓碑、锁与进程内单通道、回合选择与截断、提示词（整篇重写 + 置顶保留 + 三千字目标）、敏感信息过滤、JSON 解析、按行落盘与冲突重算、回合结束触发与周期扫描、supervisor 生命周期 |
| `core/src/lamtools_core/app/project_context.py` | 两档核心认知注入（预算内、索引之前、非指令声明）；prompt part 支持显式 key 与自定义头部 |
| `core/src/lamtools_core/app/http_agent_app.py` | `memory.core.get/set/clear/versions/restore`、`memory.dream.status/run`；删除记墓碑；启动/停止整理循环 |
| `core/src/lamtools_core/app/base_agent.py` | 开关切换时重建冻结的系统提示词，使关闭/开启实际生效 |
| `core/src/lamtools_core/app/live/runtime_tasks.py` | 回合收尾后分离触发整理 |
| `core/src/lamtools_core/tool/memory_tools.py` | 工具说明补充 memory.md；删除记墓碑 |
| `core/src/lamtools_core/mem/__init__.py` | 导出新 API |

> 评审后删除：`app/dream_supervisor.py`（生命周期并回 `mem/dreaming.py`，少一个模块）。

### 界面

| 文件 | 改动 |
| --- | --- |
| `core/ui/src/components/MemoryView.vue` | 根层固定「核心认知 memory.md」卡片（查看/编辑/立即整理、上次整理时间、历史版本恢复，清空而非删除） |
| `core/ui/src/components/CoreGeneralEditor.vue` | 设置 → 通用新增「主动记忆」开关 |
| `agent_docs/ui_component_catalog.md` | 记忆页条目补充核心认知卡片 |

## 五、验收对照（PRD 第 10 章）

| 场景 | 现状 |
| --- | --- |
| 初次使用默认开启 | ✅ `core.memory` 缺省即开启 |
| 新会话无需工具掌握核心认知 | ✅ 两档 memory.md 随提示词注入 |
| 新增长期偏好后续可用 | ✅ 整理写进认知；下一请求可见 |
| 修改旧决策不再沿用 | ✅ 整篇重写替换旧结论，不新旧并列 |
| 用户主动要求记忆 | ✅ `memory` 工具可写 memory.md 与独立文件 |
| 用户要求忘记 | ✅ 删除记墓碑，提示词禁止恢复 |
| 用户置顶的内容 | ✅ 每次自动改写原样保留；被替换内容可从版本恢复 |
| 简短但重要的信息 | ✅ 延后整理，不丢弃（扫描补上） |
| 跨项目切换不污染 | ✅ 项目档固定在各自 work_root |
| 长期使用不无限膨胀 | ✅ 提示要求整篇约三千字、细节下沉；截断仅兜底 |
| 并发会话不丢失 | ✅ 文件锁 + 进程内单通道 + CAS（均有测试） |
| 整理失败保留原记忆 | ✅ 失败不落盘 |
| 关闭停止注入与整理 | ✅ 下一次请求头部重建，认知真的消失；运行中关闭丢弃结果 |
| 重新开启恢复 | ✅ 头部重建，认知回来；文件与版本都在 |
| 手动编辑后续生效 | ✅ 下一请求按新内容注入 |
| 备份与恢复 | ⚠️ 目录可迁移 + 版本恢复已做；按评审不做导入导出界面 |
| 性能与成本 | ✅ 注入为文件读取；整理有冷却/上限，不进入主回合路径 |

## 六、缓存与并发证据

`core/tests/test_memory_injection_cache_stability.py`（7 条）用真实 `CoreBaseAgentKit.build_model_request` 证明：

1. **前缀逐字节不变**：同一压缩周期内改 memory.md，第 1 条 system 消息与改动前完全相同；新内容只出现在尾部通知里，且通知是请求最后一条。
2. **一条变化只通知一次**：再发一次请求没有通知。
3. **跨回合沿用**：下一回合恢复快照里的 epoch，前缀仍与首轮相同。
4. **压缩重建是记忆更新的唯一改前缀时机**（开关切换是另一回事，见第 7 条）。
5. **渲染确定**：未变记忆连续加载两次，注入文本完全一致。
6. **相同内容整理是空操作**：不写文件、不多版本，因此不制造通知。
7. **开关切换重建前缀**：关掉后头部里真的没有认知（无需尾部说明），重新打开后认知回来。

并发与容错补测（`core/tests/test_memory_dreaming.py` 新增）：

- 整理读与写之间用户保存了内容 → 从最新内容重算，置顶内容必然保留，未被置顶的旧文可从版本找回；
- 进程内已有整理在跑 → 第二次直接跳过，不调用模型；
- 陈旧锁（超过 10 分钟）可回收；`state.json` 损坏回落默认值；
- 超长核心文档写入被拒绝；
- 短内容：回合结束触发延后（`waiting_for_more`），扫描沿用同一段内容完成整理。

## 七、本次相关测试结果

- 新增四套：`test_memory_core_cognition.py`（18）、`test_memory_dreaming.py`（21）、`test_memory_core_rpc.py`（7）、`test_memory_injection_cache_stability.py`（7）——**合计 53 passed**。
- 既有记忆与提示词回归：`test_movable_system_context`、`test_memory_library`、`test_memory_tool`、`test_memory_context_recall`、`test_command_memory_bounds`、`test_agent_app_contract`、`test_agent_presets_prompt_waterfall` 与新测试一起跑：**119 passed**。
- `vitest run tests/memory-view.test.ts tests/design-system-memory-discard-integration.test.ts`：11 passed。
- `pytest tests/test_core_live.py tests/test_core_runtime_persistence.py tests/test_attachment_only_turn.py`：117 passed / 6 failed。
  已核对：把本次新增的回合收尾触发整段临时移除后，`test_live_queue_guidance_reaches_the_next_model_call` 仍同样失败，
  说明这 6 个失败与本需求无关（同一分支上的既存问题）。
- `test_base_agent_prompt_translation.py` 失败源于 `COMPLETION_RULE` 文案早已改过而断言未同步，与本需求无关。

## 八、评审已定，不再作为待决项

1. 「立即整理」只保留记忆页入口（设置页只放开关）。
2. 不自动删除独立记忆文件。
3. 不做专门的导入/导出功能。
4. 整理复用现有「后台任务」模型配置。

## 九、已知限制

- 缓存命中率未在真实应用里采样；证据是请求头部逐字节不变（命中的必要条件）。
- 整理质量取决于模型；闸门管频率，不管判断。
- 对话进行中的会话也可能被扫到，可能只整理到用户那句话。
- 只做桌面端。
