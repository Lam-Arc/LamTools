# 插件具名子代理控制

user:“继续”+(通过原监督器与持久邮箱公开可验证的成员控制，不把基础接口冒充DSH Agent/activation协议)。

这是第二阶段2u的桌面Python近似接口。官方基线为固定提交的 [Agent手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/core/agent/README.zh.md)和[Subagent手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/subagent/subagent/README.zh.md)。完整阶段仍按 [71项清单](dsh_phase2_completion.md)推进。

## 调用接口

`context.subagents` 提供以下异步方法：

| 方法 | 参数与结果 |
| --- | --- |
| create | `(parent_session_id, name, kind=..., model=..., reasoning_level=...)`，返回原持久成员状态；创建本身不启动模型 |
| list | `(parent_session_id)`，返回 `{"items": [...]}`，仅含本插件命名空间中的成员 |
| get | `(parent_session_id, name)`，返回一个成员状态，不存在明确报错 |
| message | `(parent_session_id, name, request_id=..., text=...)`，返回原邮箱接收回执；空闲成员启动执行，运行中成员沿用原后续投递机制 |
| close | `(parent_session_id, name)`，关闭并等待这一成员的原生任务收尾，返回持久状态；不是整个父会话的停止 |
| interrupt | `(parent_session_id, name)`，只中断这一成员，保留原提交状态以便后续恢复；不设置父会话共享暂停信号 |
| resume | `(parent_session_id, name)`，仅为已中断成员调度原提交状态的继续执行；返回接纳后的状态，不是执行完成 |

kind使用原consider/execute，model和reasoning_level由原模型记录解析和监督器校验，不新增选择回退或授权。name使用小写字母开头、至多32位字母/数字/下划线；父会话和request_id至多256字符，text为非空UTF-8、最多64KiB。返回值是最多1MiB有限JSON副本，不是实时Agent对象或activation结果Promise。回执accepted表示已接收，不等于执行完成。

## 原权威与作用域

复用原sub_agent.create/list/message/close、SubAgentSupervisor和sub_agents.sqlite3邮箱。每次读取原父会话的可见性，要求父会话仍属于门面绑定的原项目，只接受根会话作为parent。调用方不能覆盖work_root、权限或runtime_snapshot；原生命周期工厂仍负责继承父会话运行设置，不替换已经运行的原监督器。

成员原生名称加入由插件owner与原项目生成的固定前缀，父会话仍是原监督器的键。SDK返回友好name及真实native_name/sub_session_id，原界面和原生事件可能显示带前缀的名称；未修改前端展示。list/get/message/close经本门面不能操作其他插件命名空间的成员。此规则是门面的范围约束，不是可信原生插件的系统隔离，也不是DSH精确在线父子Agent授权协议。

list/get沿用原监督器的构造、恢复与列表行为；冷态访问可能触发原恢复对账，底层列表不是分页数据库查询。因此它不是DSH无激活Session observation目录读取协议。只有本命名空间的有限投影会返回；执行令牌、runtime_owner和内部来源字段不导出。

## 持久化与取消

同名、同配置create沿用原幂等创建/启用行为；已有成员配置不符由原监督器拒绝。message的request_id结合插件、原项目、父会话及成员生成固定原call_id，以原持久邮箱去重；在成员仍接受消息且邮箱记录保留时，同request_id重试文本不同仍返回原回执，不再发送新内容。已关闭/失败等状态会先按原规则拒绝，去重不绕过成员准入。这不代表外部工具副作用恰好执行一次，也不改变原邮箱清理/保留规则。

插件停用撤回旧门面，但已接受的成员仍属于原父会话监督器，继续按原生命周期运行。重新启动同owner/项目的插件可以通过相同name重新发现它。SDK没有在插件停用时擅自清除父会话的工作或删除子会话。关闭成员用close，可恢复中断用interrupt，已中断成员继续用resume；父会话共享暂停、收件箱和应用退出仍由原宿主管理。

create/message/close/interrupt/resume一旦进入原操作，调用方取消会等待原操作完成或失败后再传播取消。此时成员/回执可能已提交，先get/list核对再决定重试。close和interrupt等待原任务清理，运行器须配合原取消约定；不以写入终态冒充已经强制终止所有外部资源。成员不能从自身执行任务内close或interrupt等待自己，分别报subagent/self-close和subagent/self-interrupt。

SubagentAccessError含code/details/may_have_changed。错误区分invalid-id/name/message/parent、not-found、project-mismatch、unavailable、host-changed、closed、read-failed、rejected、operation-failed、invalid-result和foreign-member。原拒绝详情保留为有限JSON；修改或回执不确定时may_have_changed为true，禁止盲目重试。

## 单成员中断和提交状态恢复（2v）

user:“继续”+(对自己的单个成员安全中断和继续，不操作兄弟、不清除父会话暂停、不用全新运行假代恢复)。

原监督器新增sub_agent.interrupt_member/resume_member入口，SDK仍按插件/项目命名空间和父会话可见性寻址。单成员中断复用原取消、执行令牌失效和状态落盘，只筛选这一成员；未活动成员返回实际状态及unchanged。缺失成员明确报错，与DSH对不存在目标接受中断信号的行为不同。原会话级interrupt/resume默认仍操作原范围，SDK不将它们冒充单成员操作。

resume只接纳原记录为interrupted、原任务未运行、未被其他进程拥有的成员。父会话共享pause信号已设置，或原运行状态库中父会话已持久暂停时均拒绝，不擅自清除该信号；closed/terminated/failed等状态不能经此入口复活。必须存在真实resume_interrupted提供方、可读的已提交子会话状态和逻辑turn身份，且提交状态不在live集合中。检查在原监督器锁内完成，再调度原驱动器，保持原sub_session_id及历史，不重新发送原任务作为全新run。

实际持有的运行器可能是独立克隆，因此执行前还会检查它的继续能力；不支持时记录失败，不降级到全新run。resume返回的是接纳/调度状态，实际提供方仍可能异步失败，调用方应再次get查询结果。这不是完整DSH根Agent.resume、activation结果或精确重放保证。

中断沿用原任务join和最多3秒的子运行状态收尾观察；独立运行状态的异步写入仍可能稍后收敛。因此resume会再次读取并拒绝仍为live的提交状态，不把中断返回值当作所有外部资源退出证明。底层继续执行沿用原“未记录结果的工具可能存在不确定副作用”规则；无新增跨进程锁或外部工具回滚。

单成员pause仍未开放：原暂停信号为整个父会话共享，不能直接传给一个插件成员。子代理启动目录捕获也仍未接线；没有通过重绑runner.work_root来改变模型配置或权限根。

## 明确未覆盖

没有DSH根Agent注册表/AgentHandle、setup、withInitiator、Agent.model.select、通用resume/dispose或完整inbox操作；根会话仍使用SESSIONS原接口。没有startActivation/result/dispose协议、spawn/fork外部提供方注册、activation树容量、结构化结果收敛、精确在线sender校验、显式Queue/Steer选择、子父双向消息或DSH事件编码。SDK未提供会影响整组成员的terminate/pause/resume或删除接口；新增resume仅为上节的单个已中断成员。

这批成员仍沿用原项目工作目录和运行设置，不自动捕获主代理后来选择的执行目录。原监督器保留自身历史、摘要和通知语义；程序化调用没有伪造活跃父回合、DSH角色或来源链。相关差异必须由agent按真实插件需求处理。

## 验收

test_plugin_subagent_access.py 通过实际SQLite、原操作目录、真实监督器和可控执行器验证创建、原邮箱去重、运行状态、关闭等待、其他插件/隐藏父会话拒绝、重载后发现、非法模型拒绝、自关闭保护，以及取消期间原关闭操作收尾。未请求付费模型或访问外部账号。

test_plugin_subagent_continuation.py 新增8项验收，覆盖实际SQLite历史和逻辑turn保留、兄弟成员保持运行、缺少提供方/状态、父暂停/live状态、关闭成员拒绝恢复、SDK及原生自中断保护、原会话级范围保持、实际持有克隆不支持继续时拒绝全新运行，以及取消期间中断清理收尾。均使用可控执行器，未请求付费模型。
