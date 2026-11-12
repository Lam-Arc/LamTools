# 会话Remote与原记录投影

user:“第二阶段结束后 就继续开展第三阶段”+(复用原会话查询与控制权威，实际请求、原记录和隐藏会话拒绝都经过HTTP验收)。

固定上游deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的packages/api/session-controller/src/index.ts已逐项读取：25个Remote声明覆盖list/search/create、模型、路径、rename/fork/prompt/attachment/updateQueue/cancel、page/events/observeEvent/observeProjections/state/observeState/wait/follow/projections/control。workspace-controller/src/index.ts的11个声明亦已读取；这只是源码范围核对，不是接口可用证明。

当前验收子集通过原插件operations处理器调用原context.bind_service(SESSIONS).call('state'/'events'/'wait', session_id, ...)或context.session_query.query(...)，再返回OperationResult(request.name, value)。显式http.remote映射沿原token POST、操作归属、auto_allow及Core认证；不自动生成路由或直接公开整个会话宿主。

原SessionState、SessionEventPage、SessionWaitResult、SessionQueryPage等dataclass实例现在按字段逐项进入同一Remote结果投影，不先asdict深拷贝；保留循环/深度32/10000节点/1MiB编码上限及显式multipart bytes规则。嵌套记录和元组成为JSON对象/数组；类对象和任意对象仍拒绝。不会重命名为DSH字段或自动处理datetime/Enum等未知对象；原处理器仍负责有意选择公开结果，不能将任意内部对象当作已核验响应。

state/events/wait是原被动读取，不激活Agent或新建存储。list候选是默认50、上限100的有限扫描，保留不透明游标及插件代/筛选绑定，不是DSH完整summary或活动排序。query(title_contains=...)只筛选标题，不能冒充上游消息内容search。events为after_seq正向原持久事件页，不是history address/反向消息对齐页；wait不携带DSH有界assistant输出。follow的原持久事件不包含开场快照、cursorless token或完整DSH重连协议。

实际验收发现原PluginSessionService在可见性/数据库等待期间更换session_store后可发布旧结果，现绑定同一原store/persistence，并在准入、metadata和history等待后复核；关闭也拒绝发布。原已提交写入仍按原提交机制结算，不能将只读失效保护解释为事务回滚或原子资源授权。

本批19项新增验收包含四种真实SQLite原SDK记录经过原插件处理器到HTTP、隐藏会话拒绝与无激活/无记录修改，嵌套dataclass字节附件路径、循环/深度/类对象拒绝，迁移候选，以及两种失效在五个真实等待点的10项验收。完整sessionController、DSH资源lookup/Peer及工作区/模型/附件等全部方法仍未完成。


## 原会话写入的显式HTTP验收

单项新增验收通过插件显式HTTP映射、原SESSIONS与临时真实持久存储验证prompt、队列文字更新/删除及空闲cancel：错误令牌不能入队，相同request_id重试返回原接收回执且只写入一次，更新内容写入原事件，空闲取消及已启动回合的取消请求均不清除待处理队列，活动取消返回cancelling且不声称已经完成。该路径由插件自己明确选择会话和参数；未验证跨项目资源授权、上游附件、恢复或DSH请求/响应协议，也不将其标记为完整sessionController。

经`ServiceRef.call`取得的原follow异步生成器每次读取及发布前复核提供方和请求方代；撤回期间的旧事件不再发布。请求方或受管提供方启动代撤回会取消等待中的读取并等待其清理；非受管宿主替换在读取返回后检查。此项不补DSH开场快照、重连或Peer授权。

原follow缓存页现在逐条复核原宿主绑定与原存储会话可见性；会话隐藏或存储替换后不再发布剩余旧事件，关闭发生在可见性检查中则正常结束。此检查为逐条数据库读取，不能提供跨进程原子权限锁。相关新增文件共8项验收通过。

原SESSIONS会话/请求/队列标识和prompt/队列文本先验证Unicode，非法字符不进入原读写；这不是上游Peer资源授权，其他字段仍沿原校验。

## 当前项目会话只读门面

`context.session_controller.state/events/wait`先经原working_directory读取可见会话项目根，只允许当前插件项目；再调用同一原SESSIONS提供方，结果发布前重新核对可见性、项目、启动代及提供方。两个原服务必须指向同一会话宿主。返回仍是Sunday原dataclass，events为正向游标；不依赖执行目录当前存在。HTTP需插件显式token映射。本只读部分不提供DSH Peer角色/资源授权或跨进程原子锁；会话身份可能在最后检查后变化。7项新增验收覆盖真实数据库、隐藏/跨项目拒绝、读取期间撤回、提供方替换、取消清理、显式HTTP及迁移建议。

## 当前项目会话写入

`context.session_controller.prompt/update_queue/cancel`先检查原会话可见性及当前项目，然后调用原SESSIONS；prompt只接文本，派发前从原会话读取执行目录作为`work_root`快照；目录缺失时拒绝派发。原请求去重、队列回执及取消状态不变；派发后重复取消等待原操作结算，取消不表示回滚。写入后再次核对原作用域和提供方；派发后异常保守报告`session-controller/write-uncertain`及Python属性`may_have_changed=True`，也可能包含写入前参数错误，HTTP不保证透传。检查不是跨进程原子授权锁；没有DSH Peer或精确协议。5项新增验收覆盖原持久队列、跨项目拒绝、已提交失效、重复取消、真实HTTP和迁移建议。

4项新增验收覆盖真实会话子目录、目录缺失不派发、显式HTTP及派发后目录变化：本次请求保留派发前捕获的目录，后续变更不回溯；这不是跨文件系统原子锁或目录恢复。

## 当前项目持久事件跟随

`context.session_controller.follow(session_id, after_seq=0, limit=100, max_bytes=1048576, interval=0.1)`按原events正向游标轮询，间隔0.01–2秒；每次页读取及发布每条前复核原会话可见性和当前项目。消费者停止拉取时不运行后台轮询；取消或关闭释放当前读取。只提供原持久事件，不含DSH开场快照、瞬态token或精确wire；显式ndjson可由插件自行映射，不提供Peer授权或原子锁。10项新增验收覆盖原持久事件、缓冲页项目变化、空闲撤回、取消/关闭、输入错误、实际HTTP和迁移提示。

另3项新增验收通过真实ASGI HTTP长流，确认客户端断连、会话隐藏及项目迁移会结束流并释放原租约与网关容量；后两者返回流错误而非正常结束。

## 会话重命名人工迁移

固定上游[会话命令源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/src/commands.ts)的rename解析Agent后返回标题和持久事件seq。Sunday可人工映射`context.session_title.get/set`：先读取原revision，再以该revision执行当前项目可见会话的CAS修改；返回的是原标题与revision，不是上游事件seq或Agent恢复协议。插件须显式声明token HTTP映射；已派发取消沿原写入结算，不代表回滚。2项新增验收经原SQLite、真实HTTP验证错误令牌、跨项目和过期修订拒绝及迁移建议；原取消结算另见既有会话资料验收。

## 当前项目会话分叉

`context.session_controller.fork(session_id, checkpoint_id=... 或 turn_id=..., new_session_id=..., title=...)`先检查原可见会话和当前项目，再调用原检查点分叉；成功后复核源及新会话项目。沿用原活动会话拒绝、仅对话历史、不回退文件及取消后原提交结算。提交后复核失效的Python错误标记`may_have_changed=True`；取消也可能已创建，HTTP不保证透传该属性。检查不是跨进程原子权限锁。上游支持任意有效事件前缀和迁移预检，此处仅原checkpoint或turn边界，不能声称精确兼容。6项新增验收覆盖真实SQLite分叉、跨项目/错误边界、HTTP、重复取消、提交后项目变化和迁移交接。

`context.session_projections.get/events`返回前再次通过原只读会话核验可见性与绑定项目；等待期间隐藏或迁移时不发布旧摘要/事件。5项新增验收覆盖两种接口、隐藏/迁移及真实Remote；不是原子授权快照。

## 单会话原历史搜索

`context.session_controller.search_archive(session_id, query, limit=10, after_seq=0)`对当前项目可见会话复用原有界历史搜索，最多扫描2000条，支持原序号续读、大小写不敏感的字面查询及最多20条结果。只投影用户/助手文字，排除工具消息与工具调用参数；原历史包含被压缩隐藏的内容，不含尚未持久化的实时尾部。每页读取后及返回前核对原会话/项目和历史提供方；缺提供方明确报错，取消传播。11项新增验收覆盖真实SQLite、工具数据隔离、分页、输入、撤回/取消、真实Remote及迁移。固定上游[搜索源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/src/list.ts)按当前表面搜索全局可见用户/助手消息并按会话去重；此接口必须显式指定单会话，不等价于上游搜索，非Peer策略、实时尾部或原子授权快照。

## 当前项目分页历史搜索

`context.session_controller.search_project(project_id, query, scan_limit=10, cursor=None)`复用原项目可见会话扫描和单会话原历史检索，每次扫描1–20个会话，每会话最多返回一条用户/助手文本命中；各历史最多扫描2000条，内容可能包含压缩隐藏历史。返回的 `next_cursor` 和 `has_more` 描述会话扫描进度，不代表还有匹配；游标绑定插件代/项目/根和精确查询，跨页不是快照。缺原历史提供方明确报错，读取后核对会话、项目和提供方；取消传播。11项行为验收覆盖真实SQLite分页、隐藏/跨项目隔离、撤回/替换/取消、输入和显式Remote。上游按全局可见当前表面搜索并去重排序，本接口非DSH Peer、精确排序或原子授权。

项目搜索在最终项目读取等待完成后复核每条命中的原会话范围；2项新增验收覆盖等待期间隐藏及真实Remote不泄露旧命中。项目与多个会话的复核不是原子快照。

搜索游标复用原宿主的随机令牌、120秒期限及有界缓存，绑定精确搜索词的摘要及原插件代/项目/根；普通会话列表游标不能混用。2项新增验收包含真实HTTP，缓存失效须从头搜索；分页仍不是快照。

## 当前会话状态观察

`context.session_controller.observe_state(session_id, interval=0.1)`按消费节奏轮询原 `state`，首次及状态变化时返回完整原 `SessionState`；每次读取复用当前项目、可见性和原提供方复核。间隔0.01–2秒，取消或关闭不停止会话，没有后台常驻轮询；中间变化可能合并。10项新增验收覆盖真实队列变化、跨项目拒绝、空闲撤回、取消、参数、实际NDJSON断连及迁移。固定上游[实现](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/src/state/controller.ts)和[手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/README.zh.md)使用状态监听器和完整状态替换；此近似是轮询，字段、瞬态输入、事件语义、Peer及codec不同。

## 当前会话后续持久事件观察

`context.session_controller.observe_events(session_id, interval=0.1)`先通过原可见性和项目准入，读取当前持久事件末尾并发送`ready`及`after_seq`，再消费驱动轮询该位置之后的原持久事件；不回放此前事件，准备帧与首次拉取之间新提交的持久事件仍可读取。取消或断连关闭观察，不停止会话。10项新增验收覆盖真实持久事件、准入、撤回、取消、参数、实际NDJSON断连和迁移。固定上游[实现](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/src/history/controller.ts)与[手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/README.zh.md)的observeEvent订阅事件总线，ready不证明会话存在；这里要求先准入，只有持久事件，不含瞬态帧、DSH地址/Peer/codec。

## 当前会话有限投影观察

`context.session_controller.observe_projections(session_id, interval=0.1)`经原会话和项目准入，消费驱动轮询原`session_projections.get`；首次及变化时返回包含标题、修订、状态、队列数及事件序号的完整有限摘要。比较使用副本，调用方修改快照不影响后续；检查原投影提供方并在撤回时拒绝。间隔0.01–2秒，无后台常驻轮询，可能合并中间变化。10项新增验收覆盖真实标题变化、撤回、提供方替换、取消、参数、真实NDJSON断连及迁移。固定上游[源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/src/history/controller.ts)与[手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/README.zh.md)订阅时不读基线，先ready后按键推送稀疏替换；本接口非DSH扩展投影、事件语义、Peer或codec。

事件观察在读取中取消时先取消原来源读取并等待其清理，即使调用者重复取消也不提前结束；来源不配合可延迟结束。2项新增验收覆盖可控异步清理和原真实持久事件。

当前项目`state/events/wait`只读调用在取消时取消实际读取并等待准入/提供方清理，重复取消也不提前释放作用域；不合作的提供方可能延迟完成。5项新增验收覆盖state/wait重复取消、原真实读取、作用域排空和真实Remote取消。

投影观察的在途只读调用被取消时会取消并等待原来源清理，重复取消或NDJSON断连不会提前释放租约；不合作的来源可能延迟结束。4项新增验收覆盖受控来源、真实投影/状态、共享读取帮助函数及实际NDJSON断连。

单会话及项目历史搜索在取消时取消原读取并等待其清理，重复取消不会提前释放作用域；不合作的读取可延迟结束。4项新增验收覆盖真实历史读取、项目搜索、实际Remote取消及正常匹配。

项目搜索在原会话扫描及项目准入阶段也持有可取消的只读任务，重复取消等待其清理；历史读取继续嵌套等待真实退出。4项新增验收覆盖原扫描、嵌套历史读取、正常分页及真实Remote取消；来源不配合可延迟结束。

## 等待与有界持久助手输出

`context.session_controller.wait_with_output(session_id, timeout=30, after_seq=0, max_messages=10)`先复用原等待，捕获停止状态的原事件序号，再从`after_seq`（不含）至停止序号最多扫描2000条原持久事件。只提取`core/runItem`中已完成的`agentMessage`字符串内容，不返回用户消息或工具数据；结果按已扫描范围内序号倒序，1–20条、每条最多4096字符并独立标记截断。`scan_complete=false`及`next_after_seq`表示扫描未到停止位置，`truncated`还表示匹配超出条数。未前进的提供方页会停止并报告不完整。每页及最终返回前复核原会话、项目及提供方；取消等待原读取清理。

14项新增验收包括真实持久事件、停止游标、数量/长度/扫描预算、授权撤回、重复取消、真实Remote和迁移；其中一次早期异常页测试因同步假提供方无限循环，只终止本次测试进程并改为可取消的失败验收后修复。固定上游[源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/src/state/controller.ts)与[类型](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/src/types.ts)返回停止游标之前的最新DSH assistant history records；本项只识别Sunday字符串事件，不含多模态/瞬态输出或DSH Peer/codec，扫描不完整时不能声称全区间最新，旧版未对同一item多次完成去重，现以本节后续说明为准。

单次扫描范围内，相同非空原`item_id`的完成事件保留最新一条，数量截断按去重后结果计算；缺少ID的事件各自保留，跨续页不去重。3项新增验收覆盖真实持久事件重复、缺ID及真实Remote。

## 会话模型目录迁移候选

`context.models.list()`可由插件显式Remote处理器返回当前项目原模型配置的安全元数据；真实临时配置与原令牌HTTP验收覆盖配置变更及缺失的提供方。目录只表明存在配置，不代表提供方已安装、连接或模型可用，也不返回密钥或地址。上游[目录源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/src/catalog.ts)按实时提供方分组并携带默认项和失败信息；本候选不提供这些内容或自动生成Remote。4项新增验收涵盖真实配置/HTTP、迁移说明和读取及选择期间启动代撤回。

## 当前项目会话选模

`context.session_controller.select_model(session_id, model_id, expected_revision=...)`先复用原会话可见性与项目准入，要求精确模型记录ID和原会话修订；由原模型目录检查启用状态、提供方配置及URL，再调用原会话输入参数写入事务。只更改该会话后续回合的模型，不更新全局默认或当前运行回合，也不放行现有审批。写入派发后取消等待结算，出错或绑定失效保守报告`may_have_changed`；返回记录ID与新修订。检查仅证明本地配置有效，不证明提供方在线或密钥有效，非跨线程原子锁；HTTP须插件显式映射。17项新增验收覆盖实际临时模型及提供方配置、原SQLite、缺提供方、无效参数、跨项目、撤回、CAS、重复取消、认证HTTP、原审批行为及迁移。上游[选模源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/src/commands.ts)选择Agent模型并异步保存全局默认；本项不提供相同实时Agent、默认项、reasoning参数或Peer协议。

## 当前会话托管图片读取

`context.session_controller.attachment(session_id, attachment_id)`只读当前项目可见会话的原附件索引及托管目录，允许PNG/JPEG/GIF/WebP、最多512KiB和1600万像素。读取实际文件后核对原SHA-256指纹、长度和图片格式，返回id、MIME及base64，不返回本机路径；无Pillow时明确不可用。非托管外部引用、其他会话附件、无效图片和不在原托管目录的记录均拒绝。读取后复核附件记录、会话和宿主；重复取消等待原读取清理，检查不是跨线程原子锁。14项新增验收覆盖原临时附件与SQLite、错误图片、上限、跨项目、撤回、取消、真实认证HTTP和迁移。固定上游[源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/src/commands.ts)读取DSH持久图片引用，本项不支持任意引用、外部文件或Peer策略。

## 单次会话投影读取

上游`session.projections`可人工迁移至已有`context.session_projections.get(session_id)`，返回当前项目可见会话的原有限标题、状态、修订与事件序号；原插件必须显式声明认证Remote映射。2项新增验收覆盖真实SQLite、隐藏会话拒绝、令牌及迁移建议；不是上游扩展投影、迁移缓存或Peer过滤。

## 原桌面历史分页

`context.session_controller.history_page(session_id, before_seq=None, turn_limit=10, max_bytes=262144)`复用原桌面持久快照分页，首次读取最近条目，后续用返回的`next_before_seq`向前翻页；回合限1–50，输出限64–512KiB。只返回原历史条目、顺序和分页信息，不返回完整会话快照；原分页可能按条目切开回合，单个条目超过输出上限时明确报错。缺有界原提供方时不退化为全量读取。读取和组装后复核可见会话、项目及宿主，重复取消等待原读取清理；跨进程并发不是原子快照。14项新增验收覆盖真实持久回合、向前翻页、参数及超限、缺提供方、撤回、取消、认证HTTP和迁移。上游[手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/README.zh.md)的page/events为持久事件记录及地址和固定截断；本项是Sunday条目快照，不是其事件wire、DSH地址、完整实时follow或Peer策略。
