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
