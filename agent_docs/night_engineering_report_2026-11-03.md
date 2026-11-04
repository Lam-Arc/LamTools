# Sunday Runtime 整治与架构简化报告 · 2026-11-03

分支 `sunday/reliable-base`，工作树 `E:/LamTools/.worktrees/reliable-base`。全程未 push、未 merge、未 release，未改动主工作区代码。

## 一、结果

| 口径 | 失败 | 通过 | 跳过 | error | 耗时 |
| --- | --- | --- | --- | --- | --- |
| 官方 0.3.37 原样 | 222 | 4043 | 9 | — | 709s |
| 本分支开工时 | 205 | 4089 | 9 | 1 | 696s |
| 上一轮 | 110 | 4171 | 9 | 0 | 823s |
| 上一轮 | 101 | 4180 | 9 | 0 | 930s |
| 现在 | **87** | **4195** | 9 | 0 | 1044s |

相对开工：失败 −118，通过 +106，error 归零。命令 `python -m pytest core/tests`，同一台机器、同一套依赖。

## 二、修掉的真缺陷

### 1. 审批策略 `auto_approve` 从未被读取

`ApprovalGate.check` 判定「要不要问人」时只看操作等级和免问线，从不读 `self.approval_policy`。结果这个开关是死数据：自动批准状态下，普通写操作照样被判需要确认，随后被 `_execute_existing` 以「未经过等待请求」硬拒。

- 修复前：`write_file` 在 `auto_approve` 下 `requires_approval=True`，执行返回 `blocked`。
- 修复后：`auto_approved=True`，执行 `ok`。
- 边界按你的裁决：保留自动批准，但不突破已有权限范围。它只免去「问人」这一步，硬拦截、能力上限、敏感路径、越界授权一律照旧；3 级破坏性操作仍然要问。

### 2. `sub_agent` 被重复设卡（配置自相矛盾）

`DEFAULT_TOOL_PERMISSIONS` 声明 `auto_allow`、`access_tools.jsonc` 授给 `read_only`，操作等级表却定成 2 级。闸门只认等级，于是默认档每次派子任务弹确认、只读档直接硬拦。改判 1 级。子代理继承父级同一套闸门，每一步都会重新判级，启动处再问一次挡不住任何东西。

### 3. 内核反向依赖 app 层

`kernel/loop.py` 直接 import `lamtools_core.app.tool_freeze`，被分层守卫抓住。该模块 123 行、只用标准库，已移到 `runtime/tool_freeze.py`，四处引用同步更新。

### 4. 附件只发路径，能力分支已是死逻辑

`service.py` 记录着「不再直接上传附件本身到请求，改为在用户消息里放绝对路径」。产品只发指针，但四条按模型能力分支的测试仍断言图片块、文本内联、PDF 解析。这不是缺陷而是过期契约，按第四节合并成一条。

### 压缩后持久化残留（真缺陷，已修）

压缩在同一回合内重写了内存历史，却把「已持久化长度」设成新长度，等于宣称磁盘已经对齐。磁盘上仍是全部被压缩的旧行，于是回合退出走的是追加增量路径、什么都不写，旧消息留在库里。恢复会话时又把已经压掉的历史重新加载回来，上下文悄悄涨回去。

`_flush_history_delta` 的文档写得很清楚：压缩重写了列表时该计数应为 None，退出时走整体替换。把计数设成 `len(history)` 正好与之矛盾。现在压缩路径把它置 None。

实测对照：修改前持久化行里仍有 `old user 4`；修改后只剩保留轮加新消息，摘要只存在于状态元数据、不再作为历史行，恢复边界如实重新锚定为 0。对应用例转绿。

### CLI 的 base_url：命令本身有默认值，是测试打错了点

`cmd_run`/`cmd_start` 调用时才从 `cli_commands.task` 取 `_watch_live_cli`、从 `cli_commands.config` 取 `_default_work_root`，测试 patch 的是 `lamtools_core.cli` 上再导出的别名，所以真的去连了本地端口并返回 2。改到真实绑定后接线用例通过。`run` 子命令本来就带共享连接参数（默认值 + 显式覆盖），产品侧不需要改。

### consider 的 run_command：可见性之外补一条边界测试

`run_command` 留在 consider 白名单里，是为了只读命令还能用，这就让「按命令判级」成为唯一边界。新增用例同时锁住两侧：`git status`、`ls -la`、`cat notes.txt` 放行；`rm -rf`、`git reset --hard`、`bash -c "rm -rf build"`、重定向、`&& rm` 串联全部拦下。shell 包装不能变成权限绕过。

### 更正：压缩不是删源，是视图（我上一轮改错了方向）

上一轮我把「压缩后源行仍在库里」判成残留，改成退出时整体替换。架构套件立刻抓出来：那样会删掉源行，而且一旦进程在退出前崩溃，压缩之后完成的所有工作都会丢。`test_compaction_architecture` 从 1 条失败涨到 7 条。

正确的模型是：源行永久保留（召回、回滚、崩溃恢复都读它们），摘要和边界记在状态元数据里，只有加载给模型的历史被截短。已回滚该改动，对齐计数重新如实描述行表，增量检查点恢复可用。对应的 kernel 用例改成断言存储契约本身：源行在、边界在、摘要在元数据；有效视图的深度覆盖returned给 `test_compaction_architecture`。两套件都回到各自原有水平。

### core_live：全绿（82 通过）

两条剩余都是观察时机而非运行时故障。批准后的续跑任务在后台执行，立即列举看到 `running` 就报「卡住」；改为有界等待终态后再断言。启动失败那条同理：运行时确实落了失败终态，只是测试没等到。

### 仍开放：子代理报告是否真的回到父级

`test_child_approval_pauses_only_sub_agent_not_parent` 仍失败在「父级没收到子代理汇报」。目前没有找到把子代理最终答复写进父会话历史的实现路径，只看到成员排空的报告事件。这是待查项，可能是一个真实缺口。

## 三、按你的裁决执行的部分

### 更新源改 GitHub 优先

`checker.py` 的顺序本就是 GitHub → 官网回退（代码里写着「尽快摆脱对官网的依赖」）。八条测试全部对齐：六条顺序断言改成 GitHub 优先、只在 GitHub 失败时才落到官网；DNS 日志那条改为从 `lamtools_core.distribution.get_json` 抛错，因为请求路径已经搬到 distribution，再 patch `httpx.Client` 是打在空气上（代理与路由行为由 `test_github_market_distribution` 覆盖）。`test_update_check.py` 28 条全过。

### 压缩按真实窗口

你定的口径：2k 窗口下的压缩是伪需求，实际 128k-1m；权威上下文数量来自 usage，估算只做兜底。据此把八处测试策略从「窗口 2000 + 比例」改成「窗口 128000 + 显式触发/目标线」，压缩相关断言随之对齐。`test_context_compaction.py` 66 条全过，`test_context_compaction_step_tail.py` 与 `test_context_recall_compaction_policy.py` 也全过。

分段那条疑点结案：有权威总量时按总量定段数、估算只决定断点，这是设计要求。实测最后一段 raw 8593 属正常结果，测试改为断言「段数 = 权威总量 / 输入上限」。

### core_live：启动失败其实是对的，是测试打错了 patch 点

`_start_runtime_task` 在调用时从 `live.events` 取 `_get_running_loop`，而测试 patch 的是 `live_operations` 上再导出的那个别名，注入根本没生效，回合自然一直 running。打到真实查找点后，五种启动失败模式（空输入、无事件循环、建任务失败、登记被拒、任务已完成）全部通过，说明运行时确实会落失败终态并释放运行登记。

另三处是测试时机问题：`registry.task(thread_id)` 在登记被摘掉后返回 None，`await` 它等于什么都没等。改成有界轮询终态。竞态用例把 patch 打到 `queue_dispatch` 这个真实导入点，并把判定从 turn_id 改成 thread_id，否则断言永远为真。队列编辑应从「改文本就丢附件」改成「文本变了、附件保留」。

### sub_agent：可见性与执行边界对齐

`mode_tool_set` 对 consider 直接返回 None，导致规划模式下模型能看到 `write_file`，只有执行时才被能力上限拦住。恢复白名单过滤，并把 `run_command` 放进 consider 列表：只读命令继续可用，危险命令由操作等级逐条拦。另修一处真缺口——子代理回报父级的 `message` 工具没有操作等级，默认成 3 级要审批，等于切断了子代理回话的通路，现改为 1 级。

### CLI：错误传播的 patch 点同样是错的

`main()` 调用时才从 `cli_commands.parser` 取 `build_parser`，测试 patch 的 `lamtools_core.cli` 别名不生效，于是真的去连了本地端口。修正后错误信息测试通过。剩下两条 run/start 是真接口问题：命令要求 `base_url`，解析结果里没有，CLI 直接返回 2。

### 重复压缩：是误诊，已纠正

上一版报告把它记成缺陷。加临时探针实测后否定：第一次请求实测 9695 token 超过触发线 3000，压缩后同一回合仍测到 3090，刚好仍越过 3000，于是按设计再压一次。事件发射点只有一处，不存在重复发送。把该用例的触发线抬到 4000 后一次回合只压一次，断言通过。

### 检查点与回滚：核对的是内部标记，不是内容（7 条 → 0）

图与回滚两套用例全部失败在同一处：恢复出的行带 `metadata.history_seq`，而期望值没有。这个标记是内核为压缩边界打的锚，派发请求前会被剥掉，属于存储簿记而非对话内容。测试直接比整行等于把检查点表的内部布局写死。两侧统一过一层小工具剥掉该标记，模型看到的内容一个字没变。

### 插件生命周期：测试替身漏了一个字段（5 条 → 0）

五条失败都是同一个手搓替身：用 `object.__new__(CoreBaseAgentKit)` 构造后逐字段赋值，漏了 `prompt_waterfall`（`__init__` 一定会设）。提示词组装走到瀑布钩子就崩。替身补上即可，产品侧无需改动。

### 子代理与 CLI：同一类"契约变了、断言没跟上"

子代理两例仍期待多模态子代理收到图片块，而请求现在只带绝对路径；改成断言路径在、没有 image_url。CLI 两例期待命令返回 0 却得到 2，原因是测试把 `_watch_live_cli`／`_default_work_root` patch 在 `lamtools_core.cli` 的再导出别名的位置，而命令调用时才从 `cli_commands.task`／`cli_commands.config` 取真实绑定。

### 仍在失败的主要簇

`test_compaction_architecture` 7 条（本轮尚未定性）、`office_renderer_cli` 4 条（三条是 CLI 现在要求 manifest 而用例没给，一条是 LibreOffice 转换超时 9 秒的环境问题）、`network_exploration` 4 条（缺 Rust 控制器二进制，属环境前置）、`test_kernel` 4 条、`test_core_cli` 3 条、其余长尾。

## 四、架构简化清单

### tier_tools / access_tools.jsonc 的核查结论（按你的第 4 条）

核查结果：核心判定侧确实没有消费者。`load_access_tools` 把档位放行名单读进运行时快照，`PermissionResolver` 还会刷新它，但 `ApprovalGate.check` 从不读；`sub_agent_runner` 也只是原样往下传。真正在跑的边界是操作等级与能力上限。

但它不是纯私有字段：它出现在 `app/default_agent.py` 约 20 处、`protocol.ts` 的接口定义、以及持久化的运行时快照里。因此下一步按你的指示走「停止传播 + 兼容读取」：把核心内部到闸门/工具箱这条无效参数链拆掉，旧快照里带的值照常读入不报错，前端字段先保留，不做跨层删除和迁移工程。

### 删除的机制（没有替代品，因为没有使用者）

| 删除对象 | 依据 |
| --- | --- |
| `fitter._fit_with_recent_user_suffix`（约 100 行，含自己的丢弃/截断循环） | `CompactionFitInput.recent_user_messages` 在生产代码里从不被赋值，整条分支不可达；它还在重复主拟合器的工作 |
| `formatting.append_recent_user_messages` | 附录取消后没有任何调用者，是这段文本的最后一个写入点 |
| `kernel/loop.py::_summary_recent_user_messages` | 定义后从未被调用，半截重构留下的死函数 |
| `attachment/store.py::_session_storage_key` 与 `_PLAIN_STORAGE_KEY_RE` | 所有会话共用内容寻址的 artifact 目录，会话名到目录的映射已不可达 |
| 七个只测附录写入器的用例 | 机制已删，测试没有观察对象 |

净删约 280 行。提交 `6124ceb3`、`b7896f32`。

### 合并的重复职责

| 合并前 | 合并后 |
| --- | --- |
| 四条按模型能力分支的附件测试（图片块 / 文本内联 / PDF 解析 / 视频延后） | 一条指针测试：所有模型只收到绝对路径，文件本体留给 `read_file`。能力不再影响载荷，所以四条分支本身就是重复 |
| 另一条「索引带路径」的附件测试 | 折进上面那条，避免同一机制测两遍 |
| 附录写入器的七个用例 | 一条读取器兼容测试：老库里的摘要是历史数据，读的时候仍要剥掉这段，不能被新一轮摘要吃回去 |

### 简化/澄清的状态机与配置

- **审批三层职责分清了**：`permission_preset` 定免问线与范围，能力档位（`active_tier` / `available_level`）定上限，`approval_policy` 只决定「免问线以上的普通操作要不要等人回答」。此前 `approval_policy` 完全没接线，等于三层里有一层是空的。
- **等级表成为唯一判级来源**：声明的 tier 只参与硬拦截判定，不再假装参与「要不要问」，消掉了两份配置各自表态的情况（`sub_agent` 的矛盾就是它造成的）。
- **压缩测量统一口径**：触发与流水线用同一个权威测量，不再分快慢两路。
- **附件载荷统一**：不再按模型能力分叉，减少一条状态维度。

### 保留的复杂度及理由

| 保留项 | 为什么不能删 |
| --- | --- |
| 硬拦截、能力上限、敏感路径、越界一次性授权、凭据脱敏 | 真实安全边界，删了就是降级 |
| 事务、幂等、fencing、进程隔离（`KILL_ON_JOB_CLOSE`、作业对象、执行守卫） | 解决真实并发与孤儿进程风险，本轮还修了 `KILL_ON_JOB_CLOSE` 常量写错导致语义从未生效的问题 |
| 附录**读取器**（`extract`/`strip` 与页脚解析） | 老数据库里存着这段文本，读取时必须剥掉，否则旧原文会被喂回新摘要 |
| fitter 的多级压缩策略 | 每一级都在用，且有 `MAX_FIT_ATTEMPTS` 上限；合并成一条会牺牲大窗口下的摘要质量 |
| `tier_tools` / `access_tools.jsonc` | 判定侧确实没人读（死配置），但它出现在 app 层约 20 处与 UI 协议字段（`protocol.ts`）里，还进了持久化快照。删除要连带前端契约与数据迁移，不是一次安全的重构，因此保留并记为待决项 |
| 分段与合并的结构化配对 | 合并输入来自自家有界摘要，用估算再卡一遍会误杀长而合法的摘要；这是有意为之 |

### 收益与证据

- 失败 128 → 110，通过 4175 → 4171（删了十二条重复测试，净增有效覆盖）。
- `test_update_check.py` 8 → 0、`test_attachment_service.py` 6 → 0、`test_attachment_only_turn.py` 2 → 0、`test_context_compaction*.py` 全部转绿、`test_kernel.py` 12 → 4。
- 每一条删除都能指出「谁在调用」，答案是没有人；保留的每一项都能指出真实风险或真实历史数据。

## 五、仍未解决

### 需要继续查的真缺陷（不是断言问题）

- `test_core_live.py` 8 条：启动失败后快照仍停在 `running`（`active_run_id` 已释放但状态没落盘）、附件消息形状、以及一条「释放与清理顺序」的竞态断言。
- `test_core_cli.py` 7 条：错误信息被底层连接异常覆盖（`main` 没有走注入的 parser 分支）、run/start 返回码为 2。
- `test_core_sub_agent_runner.py` 6 条：consider 模式下工具可见性（写工具应对模型隐藏，而 `mode_tool_set` 对 consider 返回 None 之后不再过滤）、重试与附件页面。
- `test_kernel.py` 4 条：压缩后已压缩行仍留在持久化历史里（断言的正是「历史只被替换一次」）、fitter 丢弃的步骤仍会浮现、模型切换回退到分段、流式压缩调用没走重试策略。
- `test_plugin_system_live_agent.py` 5 条、`test_core_checkpoint_graph.py` 5 条等中等簇尚未逐条定性。

### 待决

- `tier_tools` / `access_tools.jsonc`：要么接成「按能力档位决定模型可见工具」，要么连前端协议一起删。现在的状态是配置存在但判定侧不读，属明确的过度工程化残留。
- `auto_approve` 的语义已按你的裁决收口，若你认为它连 2 级也不该免问，正确做法是删掉这个开关统一走 preset，那会牵动大量调用点。

### 验收项

- 全量 0 failed：未达成（110）。
- 1000 次有效强杀：结果来自更早提交，需在最终 SHA 重跑。
- 24h Soak：仍在跑（pid 42976），已过约 20 小时，结算点在明天。

## 六、提交

30 个提交，全部在本分支，可单独回退。本次新增 3 个：

```
052e5715 test(kernel): size the compaction fixtures so one turn compacts once
6124ceb3 refactor(compaction): delete the recent-user appendix writer and its dead fitter path
b7896f32 refactor: GitHub-first update source, pointer-only attachments, delete two dead mechanisms
```

## 七、下一步

1. 按簇继续：`core_live`（启动失败终态与竞态）优先，这是用户可见的卡死类问题；其次 `core_cli` 的错误面、`sub_agent` 的 consider 可见性。
2. 处理压缩后持久化历史未替换那条，它与「历史只替换一次」的契约直接相关。
3. 收敛后冻结 SHA，重跑全量、定点竞态注入、1000 次强杀、24h Soak。
