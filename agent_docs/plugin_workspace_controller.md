# 当前项目工作区重命名

user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(原项目CAS重命名限定当前插件项目，已派发写入按真实提交结算)。

固定上游deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的[workspace命令源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-controller/src/commands.ts)与[workspace注册表手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/workspace/workspace/README.zh.md)已核对：上游rename要求非空且全局唯一标题，并在串行写链上修改原实体。

`await context.workspace_controller.rename(project_id, name, expected_revision=...)`先经原project.get读取并确认与当前context.work_root一致，再通过原project.update/CoreProjectStore.update提交CAS。name为非空字符串、最多256字符；expected_revision须为正整数。原project.update现接受可选expected_revision并传给原CoreProjectStore；未传时保留原调用行为。成功返回原project字典及更新后revision。其他项目与不存在均拒绝；原revision冲突映射workspace/conflict。Sunday原项目存储允许不同项目同名，因此此近似不满足DSH全局标题唯一性。

作用域、项目根和原操作目录在准入后复核。派发前取消不会写入；一旦原写入派发，重复取消仍等待实际结果结算，取消不代表回滚。提交后绑定变化或结果不可信报workspace/host-changed及may_have_changed=True；无法分类的派发后错误报workspace/rejected及may_have_changed=True，原CAS冲突可确认未写。写入异常报workspace/write-failed并保守标记可能已变化。原SQLite事务与同步日志仍为权威，不新增第二套存储。

仅插件自身原处理器明确声明token POST/http.remote后可经HTTP调用；测试验证错误令牌不写、合法调用改变真实SQLite记录。15项新增验收覆盖CAS、跨项目拒绝、非法参数、等待中撤回/取消、重复取消后真实提交、提交后绑定变化及未分类错误、真实HTTP和迁移交接。DSH工作区创建/非破坏删除、全局排序/归档/置顶、Peer权限、实时follow和精确codec仍未完成；原Core项目删除会删除相关Session，不应直接映射到上游非破坏删除。

## 创建或复用当前项目根

`context.workspace_controller.create(path)`仅接受当前插件固定项目根的已有绝对目录；原项目已存在则只读返回，否则调用原`project.create`事务并返回原项目和事务判定的`created`。原事务会确保有一个初始会话，与DSH创建空成员列表不同；准入等待后和派发前复核目录存在，若此后外部并发删除，原宿主仍可能重建目录。路径检查不构成系统级原子隔离。写入派发后取消等待结算，后续绑定或结果失效标记`may_have_changed`；真实HTTP仍要求插件显式映射与原令牌。16项验收覆盖并发事务、临时SQLite、隔离、无效目录、撤回、重复取消、操作重注册、实际HTTP及迁移。上游[命令](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-controller/src/commands.ts)支持任意获授权目录和DSH实体；此接口不提供全局路径权限或完整Peer协议。

重命名与新建会话的原操作注册身份在派发前后复核；写入后若同名操作被替换，拒绝旧结果并保守标记可能已变更。2项新增验收使用真实SQLite提交验证，检查不是跨线程原子锁。

## 当前项目新建会话

`context.workspace_controller.create_session(project_id, title=...)`先核对当前项目，再调用原`project.sessions.create`，由原事务生成ID、持久化会话并绑定项目。调用派发后重复取消等待结算；结果或绑定失效报`workspace/write-uncertain`及`may_have_changed=True`，HTTP不保证透传。11项新增验收包括准入撤回、不确定错误、真实SQLite、跨项目、输入、取消、提交后绑定变化、HTTP及迁移交接。上游[会话手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/README.zh.md)允许复用空白会话、指定ID与preset；此接口只新建，不提供这些行为、Peer授权或精确协议。

## 当前项目变化流

`context.workspace_controller.follow(interval=0.1)`消费驱动轮询原`project.resolve`，首先返回当前项目或null的`baseline`，变化时返回完整`project`记录或null的`snapshot`；调用方修改已收到的对象不影响后续变化比较。interval为0.01–2秒，撤回、目录替换或取消使正在读取的流结束；没有后台常驻任务。11项新增验收包括真实SQLite重命名/删除、跨项目隔离、状态失效/取消、参数、实际NDJSON断连清理及迁移。轮询可能合并变化，且检查与读取并非原子。

固定上游[控制器源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-controller/src/index.ts)和[手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-controller/README.zh.md)的follow是全局持久有序事件流，包含会话归档/置顶及Peer过滤；此接口仅当前项目、只发送全量替换快照，不能冒充其事件协议。
