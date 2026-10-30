# 第二阶段持续补齐：运行接口

user:“继续，把 2 阶段都做完”+(继续落实原 71 项范围，公开真实运行能力，近似接口和未完成项必须分开记录)。

本文新增能力已经过相关行为测试，第二阶段整体仍按 [71 项完成清单](dsh_phase2_completion.md)推进，不能据此宣称整个阶段或 DSH 运行兼容完成。均为受管桌面 Python SDK，未新增 JS/TS 运行桥接，未修改前端样式文件。

## 文件条件修改

```python
fs = context.filesystem
observed = fs.observe("notes.txt")
result = fs.write_text("notes.txt", "新的内容\n", expected_revision=observed.revision)
edited = fs.edit_text("notes.txt", "新的", "修改的", expected_revision=result.revision)
```

observe 读取最多 1 MiB 的普通文件原始字节，返回不可变 FileObservation(path, exists, revision, size)。不存在的最终文件允许观察为 exists=false/revision=None，父目录必须存在。修订号为 sha256 内容摘要，内容恢复后可重复，不是单调版本或文件身份；observe 本身不创建文件或加锁文件。

write_text/edit_text 必须显式给 expected_revision；None 只允许缺失目标的新建，不提供无条件覆盖。内容及现有文件均须为无 NUL 的 UTF-8 文本，原始换行保持，输入/结果最多 1 MiB。edit_text 为非空字面匹配，缺失报 fs/no-match，多处匹配报 fs/ambiguous-edit，只有明确 replace_all=True 才全量替换。

FileWriteResult(path, revision, bytes_written, written, replacements) 不可变。相同内容不重复发布，written=false/bytes_written=0。既有路径、链接拒绝及启动代规则沿用。必须有宿主 data_dir 才能修改：同一 data_dir 下的合作调用按规范路径散列共用有界文件锁，沿用现有 atomic_write_bytes 的临时文件/fsync/原子替换；不新建文件写入状态表。

锁只协调使用本接口且共享 data_dir 的调用，模型文件工具、外部编辑器或其他程序未必参与，不能保证抵御绕过锁的同时写入；路径校验仍存在原有竞争条件。既有 ACL、扩展属性和文件身份不保证原样保留。它是可信原生插件的底层文件能力，不是一次性审批凭证；模型工具仍须走工具审批流程。

新增错误：fs/invalid-revision、conflict、invalid-edit、no-match、ambiguous-edit、busy、unavailable、write-failed。FilesystemError 增加 may_have_changed，发布或回执不确定时为 true；此时先 observe 核对，禁止盲目重试。原始错误不会伪装为“肯定未写入”。

## 本地目标与轮询监听

`resolve(path)` 返回根目录内的 Path；`process_path(target)` 返回绝对字符串，`file_url(target)` 返回本地文件 URI。最终目标可缺失，父目录必须存在；不穿过链接。`contains(parent, child)` 重新校验两个路径，非法/根外子路径返回 false，非法父路径报错。`process_path_from_host_path(absolute)` 返回根内路径或 None，相对输入报 fs/invalid-path。这些是本地近似，不提供 DSH opaque FsTarget、远程挂载或额外授权。

`await context.filesystem.watch(path, callback, interval=0.5)` 返回受管监听句柄；用 `async with handle` 或 `await handle.aclose()` 关闭，`await handle.wait()` 返回 FileWatchResult(reason, changes)。callback 接收 FileWatchEvent(path, kind)，kind 为 created/changed/deleted。目录变化只观察直接条目的元数据，不递归；可能合并或遗漏两次检查之间的变化，也不保证发现内容改变但大小和时间完全相同的文件。

interval 为 0.01–60 秒，每视图最多64监听，目录最多1000条。回调可同步或异步，可关闭自身；回调失败或超过5秒时停止并由 wait 报 fs/watch-callback-failed。scope 停用关闭后台任务，旧门面不能新建或开始等待。回调仍须配合取消；这是元数据轮询近似，不是原生事件流或安全隔离。

## Windows 原生受管进程

```python
handle = await context.processes.spawn(["python", "worker.py"], timeout=30, max_output_bytes=65536)
outcome = await handle.wait()
output = handle.read_output()
# 或 result, output = await context.processes.run([...], timeout=30)
```

spawn 为异步分配，argv 最多 256 个 UTF-8 字符串/32 KiB，仅直接启动解析后的 .exe/.com，不隐式经 shell，不自动执行 .cmd/.bat。cwd 默认固定取得门面时的工作目录，可显式指定其他已存在目录；这是可信插件能力，不提供文件系统隔离或执行授权。环境沿用过滤构造规则。timeout 必须显式、有限且为 (0,3600] 秒；每个视图最多 8 个活跃进程。

成功发布的进程必须取得 Windows Job owner；不提供静默降级为无所有权进程。stdin 关闭，stdout/stderr 各保留 max_output_bytes 指定的字节尾（1–1 MiB）。read_output 的 stdout_after/stderr_after 是独立的非消耗字节游标，落到保留尾部以前时相应 lost=true；输出非文本，UTF-8 解码由调用者决定。无完整溢出文件、原始管道或控制通道。

ProcessOutcome 给出直接进程 exit_code、status（exited/stopped/timed_out）及 quiescent。wait 等待同一拥有范围的处理结果，非零退出正常返回，不冒充基础设施错误。根进程退出会终止 Job 剩余成员；terminate 幂等地停止和等待自身 owner。Job 成员归零且输出读取结束才报告成功；不能证明退出时抛错并保留清理引用，停用可重试回收。

Job 分配发生在原生启动之后，仍有启动至分配之间的竞争窗口；更早逃逸的后代不保证归属 Job，这不是原子进程树分配或安全隔离。OS 创建调用本身没有可抢占截止时间；执行超时及取消在该调用返回后处理。实际 Job 查询/回收已有普通子进程验收，但不据此宣称拥有所有逃逸进程或 PTY 会话。

wait 的调用者取消只取消观察，不自动终止进程；run 的调用者取消会先回收，再传播取消。spawn 分配期间的取消也等待分配/清理完成，不抛下未知原生进程。停用撤回新调用后回收活跃 owner，旧句柄不能读取输出或发起新等待；terminate 保留只停止自身 owner 的清理能力，永不接收外部 PID。完成后输出仍在原启动代内可读。API 不能跨插件拿 PID 接管进程。

当前原生 owner 实现限 Windows 桌面，其他桌面平台抛 process/platform-unavailable。PTY/terminal、stdin、原始标准流、DSH control、持久 shell、远程执行和沙箱模式仍未实现。新增 ProcessOutcome/ProcessOutput 从公开 SDK 导入。

## PowerShell 与环境贡献

依据固定上游的 [Shell 手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/shell/shell/README.zh.md)和[环境手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/shell/shell-env/README.zh.md)，提供桌面近似接口：

```python
context.shell_env.register("region", {"SUNDAY_REGION": "Deployment region"},
                           lambda execution: {"SUNDAY_REGION": "east"})
spec = context.shell.resolve('Write-Output $env:SUNDAY_REGION', timeout=30)
execution = await context.shell.execute(spec)
result = await execution.result()
```

环境贡献在注册插件 ready 后对 collect 可见，name 和变量键均检查冲突；撤回和停用移除贡献。list() 只返回声明，不运行 resolver，不包含内置键。collect(session_id=None) 返回不可变、排序的字符串快照，每次执行重新收集；resolver 可异步，整体最多5秒，失败拒绝执行，取消保留并释放租约，迟到或撤回的结果不发布。最多64贡献者，每个1–64个带描述的 SUNDAY_* 键，合计64KiB；禁止覆盖内置 HOME/SHELL/SESSION_ID/PROFILE/PROFILE_DIR。当前只提供 SUNDAY_HOME（宿主 data_dir）、SUNDAY_SHELL=1 和可选 SUNDAY_SESSION_ID；没有推测 profile 目录。session_id 是调用方标签，不证明会话存在或身份授权。父进程环境永不修改，继承的宿主前缀仍由原进程接口过滤。

resolve(command, timeout=..., cwd=None, env=None, max_output_bytes=65536, session_id=None) 返回不可变 ShellExecutionSpec；必须显式给 (0,3600] 秒，命令最多16KiB。普通 env 禁止 SUNDAY_/DSH_/LAMTOOLS_ 键。execute 只接受同一启动代的 spec，并重新校验，以 pwsh.exe 或找不到时的 powershell.exe 启动无 profile、非交互进程；程序选择沿用受管路径解析，不信任 COMSPEC。超时包括异步环境收集，准备到期抛 shell/preparation-timeout，不返回 DSH 已结算空句柄。原生分配和 Job 竞争窗口仍沿用上节限制。

result() 返回 ShellExecutionResult(outcome, output)；非零退出与执行超时正常返回，基础设施失败抛 ProcessAccessError。read_output 为非消费、显式双字节游标；kill 终止并等待拥有范围，返回 ProcessOutcome。后台继续执行仍受原 timeout 限制，停止等待不转移所有权，result 取消只停止观察，需要停止时调用 kill。没有 onExpiry:none、stdin、spill、持久终端、沙箱或远程后端；插件停用回收原生 owner。环境变量使用 SUNDAY_*，不自动生成 DSH_* 身份。ShellAccessError 含稳定 code，第三方 resolver 失败消息经过收敛，不返回原始异常内容。

## 通用后台作业

依据固定上游 [Jobs 手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/jobs/jobs/README.zh.md)，新增插件内 Python 回调近似：

```python
async def work(job):
    job.emit("stdout", "working\n")
    job.progress("处理中")
    return {"ok": True}

job = context.jobs.start("worker", "示例", work, session_id="session-label")
view = await context.jobs.wait(job.id, timeout=30)
output = context.jobs.read(job.id, stdout_after=0, stderr_after=0)
```

所有权是当前插件启动代及项目视图；其他视图不能按 id 读取、取消或移除。session_id 只作标签，list 的过滤不构成 DSH 会话 ACL；没有无主共享任务、跨插件接管或控制器机制。最多8个运行任务和128条保留记录，完成后显式 remove 才释放记录；运行中不允许移除。start 预检失败不启动回调，立即 kill 也能结算尚未执行的任务。回调必须异步，emit/progress 只允许自身任务调用。

每流保留1–65536字节尾，每次 emit 最多64KiB，stdout/stderr 为 bytes；read 不消费，返回独立绝对偏移、lost 和 complete，尾部可能从 UTF-8 字符中间开始。result 只允许最多64KiB有限JSON，每个投影复制结果；回调异常只报告 job/execution-failed，不泄露原始异常。get/list/wait 返回 JobView（running/stopping/completed/killed/failed）。wait 必须指定0–60秒，只取消观察；kill 请求 asyncio 取消并等待回调退出，取消后迟到的成功值不作为完成结果发布。不能等待或终止自身；停用取消并 join 所有回调。

回调须配合取消；这里不能强杀任意 Python 代码、原生阻塞或未受管外部进程，外部进程仍用 context.processes。没有日志环、消费游标、结果只交付一次、事件通知、模型工具控制器、持久化或重启恢复。这是可供 agent 移植的后台工作接口，不是完整 DSH Jobs 协议。

## 长文本保存

依据固定上游 [Spill 手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/spill/spill/README.zh.md)，`await context.spill_store.save_text(content, session_id=..., suggested_name="output.txt", source=None)` 保存最多8MiB UTF-8文本，返回不可变 SpillReference(locator, bytes, retrieval_hint)。locator 指向实际持久文件，bytes 精确为UTF-8字节数；内容不改写。插件所有权固定，session 标签散列分目录，文件名只保留安全单段并加随机前缀；不按传入路径写文件。source 仅作有限JSON描述校验，不持久保存或充当授权。

写入使用原 atomic_write_bytes，宿主 data_dir/plugin-data 下持久保存；停用/启动失败不撤回已保存文本。取消等待线程写入结束后传播，文件可能已保存；写入或回执失败用 SpillAccessError(code=spill/write-failed, may_have_changed=True)，不返回虚假定位或自动重试。已知目录重定向拒绝，仍不保证抵御敌对路径替换。没有清理/过期策略、配额总量、远程提供方、自动结果预览或自动 spill。存储目录、session 标签和定位信息不授予读取权限，取回仍走原文件工具的访问规则。

## 普通程序化问答

依据固定上游 [User Questions 手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/interaction/user-questions/README.zh.md)，提供独立于审批的本地回答者接口：

```python
# 回答者在自己的 start/on_load 内注册，ready 后发布；返回可调用撤回对象。
context.questions.answer(lambda request: [
    {"id": question.id, "selected": [], "custom": "用户输入"}
    for question in request.questions
])
# 请求方明确指定等待期限，回答由实际注册的插件取得。
result = await context.questions.ask([
    {"id": "choice", "question": "请选择", "options": ["甲", "乙"], "multiple": False}
], timeout=60)
```

以上回答者仅示范返回形态；宿主不自动生成用户答案。每批1–10题，每题唯一id≤128字符、问题≤4000字符、最多10个互不相同的选项（各≤256字符）；无选项时可自由输入。输入最多64KiB有限JSON，拒绝额外呈现/审批intent字段。QuestionRequest 含随机请求id、请求插件名及不可变 UserQuestion 元组，不携带凭据、Agent实例或授权。

answer 注册到原受管服务表，同一宿主只能有一个终端回答者；返回值必须逐题恰好一答，每条含id、selected选项列表和可选custom（最多16000字符）。单选的custom覆盖选项，多选的custom补充选项；空选择且无custom表示跳过，不表示任何默认许可。结果为不可变 QuestionResult/UserAnswer，不提供 allowed 或工具授权令牌。

ask 必须显式给 (0,300] 秒，每视图最多8个待答批次。缺少或未ready的回答者报 question/unavailable；无效答案、回答者失败、撤回、超时分别明确报错。请求方取消保持取消，回答者协作退出后释放双方租约；超时或撤回后的迟到答案丢弃。回调须配合取消；这不是可强杀的外部代码。

范围仅为无Agent身份的程序化后端问答。没有waterfall、askTimed、客户端接手、持久投影、继续回复、根/子Agent身份校验、审批intent或Web表单接线；不能代替现有工具审批或模拟“用户已经同意”。前端接线留待并行样式工作结束后统一处理。验收见 test_plugin_question_access.py。

## 实际模型调用与结构化流

```python
from lamtools_core.llm import LLMRequest, ChatMessage
request = LLMRequest(messages=[ChatMessage(role="user", content="问题")], timeout=30)
response = await context.llm.complete(request, scene="chat", ref="exact-model-record-id")
async with context.llm.stream(request, scene="chat", ref="exact-model-record-id") as events:
    async for event in events:
        consume(event)
estimate = context.llm.estimate(request)
```

复用原 LLMRequest/LLMResponse/LLMStreamEvent、模型目录/场景解析和实际宿主 client。选择固定工作目录、模型记录 ID；同名引用歧义、缺供应商和冲突 model/ref 在调用前拒绝。配置路由 client 显式携带 work_root，不修改进程全局配置，底层仍转换到上游 model_id。直接 client 仅允许宿主明确绑定的模型，不能借它路由到另一个提供方。

输入为至多 1 MiB 的有限 JSON 协议，复制后调用，返回响应也复制并移除 raw 字段；不承诺任意 provider metadata 的通用脱敏。timeout 为 (0,300] 秒，默认 60；max_tokens 若提供须为 1–65536 且不超过配置上限。返回 usage 是提供方实际用量（若有），estimate 返回 TokenEstimate(exact=false)，只复用 Sunday 估算，不冒充精确 tokenizer 或 DSH replay-aware tokenMeter。

流必须 async with 管理，一个流只允许一个未完成读取，最多 8 个开放流/视图；总协议输出最多 8 MiB。截止时间包括消费者停顿；耗尽没有 finish/done 时明确报 llm/incomplete-stream。provider 错误、超时、坏响应均不能伪装完整成功。部分 token/事件可能已返回，调用方必须保留未完成语义。

complete 和正在读取的流占有启动代租约；停用等待已接收调用，沿用原生命周期等待/重试。流暂停在事件之间时不占调用租约，停用会关闭它；上下文提前退出及调用者取消也关闭底层流。清理失败保留重试引用。未提供 DSH adapter registry/prepareCall、全量消息品牌类型或子代理模型授权策略。

## 持久目标与计划

context.goals/context.schedule 复用现有 goal.* / arrange.* 目录、数据库与 Runner，固定插件/项目命名空间。create 必须有 thread_id/request_id：相同身份重试返回原记录，后续修改使用 update。数据保持有限 JSON，不允许调用者指定记录 ID 或其他项目。原生插件仍可信；该命名空间约束不是操作系统或对任意内部 API 的安全隔离。

goals.create(objective, completion_criteria, metadata) 使用 Sunday 的 active/blocked/archived 目标；get/list/update 不等价于 DSH 单会话目标投影、goal rounds、revision/CAS 或进程续跑激活。list 要求 thread_id，返回 items/has_more/next_after，以 ID 分页；输出有限但底层原目录查询不是有界数据库游标。

schedule.create 支持原 Arrange 的 operation/payload/trigger/kind/title/session_strategy/model_id/max_runs，固定 work_root；operation 必须已注册，实际由原 Runner 执行。get/list/update 和 control(id, pause/resume/cancel) 继续走原业务目录，正在运行任务的停止沿用原取消回调，不另造状态机。Sunday 触发器与 DSH reminders/cron/投递历史不同，不自动转换语义。

写入和提交回执不构成跨存储事务；DurableAccessError.may_have_changed 为 true 时先读取记录核对。update 沿用现有管理器的修改语义，没有新增调用方 expected_revision 协议。目标和计划是持久意图，插件停用后不自动删除；旧视图撤回，原 Runner 与存储生命周期不归门面所有。若没有对应宿主 operation，明确报 durable/unavailable。

## 验收与剩余范围

审批后端增加 context.approvals.request(session_id, tool_name=..., call_id=..., reason="", timeout=15) 与 answer(callback)。回答者经原 RegistrationScope 的服务注册/就绪发布/撤回，只允许一个终端回答者，不另造全局生命周期。请求须位于已有活动回合，默认无回答者为 unavailable；仅 allowed-once 为允许本次请求，其余 rejected/cancelled/unavailable 都不允许。

请求和决定通过原持久库记录 plugin/approvalAsked 与 plugin/approvalDecided，返回不可变 ApprovalResult（含两个序号）。缺少活动回合不写审计。回调异常或非法结果归 unavailable；请求方取消、任一启动代撤回、超时或迟到回答都不能放行。已开始的 asked 提交在调用者取消后仍收尾并写取消结果，决定审计失败抛 approval/audit-failed，不能使用未落盘决定。最多 128 个待决请求，回答期限最多 30 秒；回调须协作取消，不协作时仍由原服务租约/停用等待处理，不伪装清理完成。

这些审计事件不是 DSH 的原事件编码；回合结束后撤销决定可能落在原回合结束之后，不提供 DSH 严格 turn-enclosed 重放协议。没有前端审批卡、回答者 waterfall 或持久 setPolicy；不把此结果自动注入数字等级审批或作为通用工具绕过授权。模型面对的工具仍须沿用原审批执行流程。验收见 test_plugin_approval_access.py，包含 asked 已提交后的取消竞争、撤回答者迟到 allow、非法回答和决定审计失败。

会话查询已增加 context.session_query.query(limit=50, cursor=None, title_contains="")，每次最多扫描 1000 行、返回 1–100 条可见摘要；不调用可能迁移旧数据的 get/list。摘要只含会话 ID、标题、状态，标题超过 1024 字符带 title_truncated 标记。扫描预算用尽可以返回空 items 但 has_more=true，调用方必须继续分页，不能把它当作没有匹配会话。

游标为宿主内存中的随机引用，不公开隐藏会话 ID；绑定插件 owner/epoch 和标题条件，最多 128 个、有效期 120 秒，不保证数据库快照或持久恢复。过期/跨插件/改变筛选条件均明确拒绝。会话可见性沿用原存储，不新增按项目或插件划分的完整会话 ACL。应用关闭、存储替换或启动代撤回后旧查询不可用。验收包括真实隐藏行扫描超过预算后的继续分页，见 test_plugin_session_query.py。

新增验收在 test_plugin_filesystem_mutations.py、test_plugin_owned_processes.py、test_plugin_llm_access.py、test_plugin_durable_access.py、test_dsh_phase2_runtime.py。包含实际进程/普通后代回收、真实配置路由、原数据库目标与原 Runner 执行；模型网络传输使用可控测试提供方，未调用付费模型或外部账号。

迁移器保留 agent-required 和 runtimeVerified=false，只给有行为证据的近似建议。第二阶段剩余 71 项审计、审批/隔离/终端、工作目录、投影、外部提供方和其他差异仍见完成清单，不提前勾选。

插件管理增加 context.plugins.list/enable/disable/reload，运行档读取增加 context.profiles.list/resolve，均经原 operation catalog 和管理器处理；没有独立状态权威，返回原 payload 副本。宿主拒绝或需要确认时抛 HostOperationError，保留 status/details，不能吞成成功。自己的活跃调用内禁止 disable/reload 自身以避免自停死锁。profiles 是原宿主运行档声明，非 Cordis profile Context 组合或安装隔离；没有自动模块图热替换。相关验收为 test_plugin_management_access.py，包括真实启停账本和真实运行档清单解析。
