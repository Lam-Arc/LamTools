# 当前项目工作区重命名

user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(原项目CAS重命名限定当前插件项目，已派发写入按真实提交结算)。

固定上游deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的[workspace命令源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-controller/src/commands.ts)与[workspace注册表手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/workspace/workspace/README.zh.md)已核对：上游rename要求非空且全局唯一标题，并在串行写链上修改原实体。

`await context.workspace_controller.rename(project_id, name, expected_revision=...)`先经原project.get读取并确认与当前context.work_root一致，再通过原project.update/CoreProjectStore.update提交CAS。name为非空字符串、最多256字符；expected_revision须为正整数。原project.update现接受可选expected_revision并传给原CoreProjectStore；未传时保留原调用行为。成功返回原project字典及更新后revision。其他项目与不存在均拒绝；原revision冲突映射workspace/conflict。Sunday原项目存储允许不同项目同名，因此此近似不满足DSH全局标题唯一性。

作用域、项目根和原操作目录在准入后复核。派发前取消不会写入；一旦原写入派发，重复取消仍等待实际结果结算，取消不代表回滚。提交后绑定变化或结果不可信报workspace/host-changed及may_have_changed=True；无法分类的派发后错误报workspace/rejected及may_have_changed=True，原CAS冲突可确认未写。写入异常报workspace/write-failed并保守标记可能已变化。原SQLite事务与同步日志仍为权威，不新增第二套存储。

仅插件自身原处理器明确声明token POST/http.remote后可经HTTP调用；测试验证错误令牌不写、合法调用改变真实SQLite记录。15项新增验收覆盖CAS、跨项目拒绝、非法参数、等待中撤回/取消、重复取消后真实提交、提交后绑定变化及未分类错误、真实HTTP和迁移交接。DSH工作区创建/非破坏删除、全局排序/归档/置顶、Peer权限、实时follow和精确codec仍未完成；原Core项目删除会删除相关Session，不应直接映射到上游非破坏删除。

## 创建或复用当前项目根

`context.workspace_controller.create(path)`仅接受当前插件固定项目根的已有绝对目录；原项目已存在则只读返回，否则调用原`project.create`事务并返回原项目和事务判定的`created`。原事务会确保有一个初始会话，与DSH创建空成员列表不同；准入等待后和派发前复核目录存在，若此后外部并发删除，原宿主仍可能重建目录。路径检查不构成系统级原子隔离。写入派发后取消等待结算，后续绑定或结果失效标记`may_have_changed`；真实HTTP仍要求插件显式映射与原令牌。16项验收覆盖并发事务、临时SQLite、隔离、无效目录、撤回、重复取消、操作重注册、实际HTTP及迁移。上游[命令](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-controller/src/commands.ts)支持任意获授权目录和DSH实体；此接口不提供全局路径权限或完整Peer协议。

重命名与新建会话的原操作注册身份在派发前后复核；写入后若同名操作被替换，拒绝旧结果并保守标记可能已变更。2项新增验收使用真实SQLite提交验证，检查不是跨线程原子锁。

重命名提交后重新读取原项目，并复核原更新操作；记录被删除或后续修改时拒绝发布旧快照，报告可能已变更。8项新增验收覆盖临时SQLite并发更名和删除、正常提交、复核时撤回/取消、真实认证HTTP及迁移交接。提交与复核不是原子锁，复核后仍可能继续变化。

## 当前项目新建会话

`context.workspace_controller.create_session(project_id, title=...)`先核对当前项目，再调用原`project.sessions.create`，由原事务生成ID、持久化会话并绑定项目。调用派发后重复取消等待结算；结果或绑定失效报`workspace/write-uncertain`及`may_have_changed=True`，HTTP不保证透传。11项新增验收包括准入撤回、不确定错误、真实SQLite、跨项目、输入、取消、提交后绑定变化、HTTP及迁移交接。上游[会话手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/README.zh.md)允许复用空白会话、指定ID与preset；此接口只新建，不提供这些行为、Peer授权或精确协议。

新建会话提交后使用原项目存储按会话ID读取，确认记录、项目归属及原可见性，并复核查询和写入操作的注册身份；会话删除、隐藏、转移或改变时不发布旧记录，报告可能已变更。缺少查询提供方时在写入前拒绝。13项新增验收覆盖临时SQLite、跨项目、提供方更换、取消、认证HTTP及迁移；检查非原子，且不扫描整份项目会话列表。

## 当前项目变化流

`context.workspace_controller.follow(interval=0.1)`消费驱动轮询原`project.resolve`，首先返回当前项目或null的`baseline`，变化时返回完整`project`记录或null的`snapshot`；调用方修改已收到的对象不影响后续变化比较。interval为0.01–2秒，撤回、目录替换或取消使正在读取的流结束；没有后台常驻任务。11项新增验收包括真实SQLite重命名/删除、跨项目隔离、状态失效/取消、参数、实际NDJSON断连清理及迁移。轮询可能合并变化，且检查与读取并非原子。

固定上游[控制器源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-controller/src/index.ts)和[手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-controller/README.zh.md)的follow是全局持久有序事件流，包含会话归档/置顶及Peer过滤；此接口仅当前项目、只发送全量替换快照，不能冒充其事件协议。

## 当前项目会话置顶近似

`context.workspace_controller.pin_session(session_id)`与`unpin_session(session_id)`复用Sunday原`CoreThreadSnapshot`会话行新增的置顶序号列，在原SQLite写协调器内更新；列表只返回固定当前项目根下仍对插件可见的会话，最近置顶优先。重复置顶不重新排序，重复取消幂等。旧库打开时由原数据库补列流程幂等补齐。

置顶/取消先解析当前项目并要求原项目会话操作；提交后使用原`project.sessions.pinned`重读，复核操作注册身份与项目仍存在。派发后取消等待写入结算；结果不确定时报告可能已变更。只有HTTP显式映射并使用插件原令牌才可调用。固定上游`workspace-controller/src/commands.ts`的`pinSession`/`unpinSession`位于全局Peer列表与有序状态协议中；此Sunday实现仅覆盖当前项目的可见子集，不提供Peer授权、全局顺序事件、插入顺序、归档或精确上游错误协议，因此机器清单整项仍为gap、服务仍为candidate。

6项新增验收覆盖最近置顶顺序/重复置顶、取消幂等、跨项目隔离、真实认证HTTP、SQLite重开持久性、旧库补列及迁移差异。仅运行`core/tests/test_plugin_workspace_controller_pins.py`。

固定上游[workspace controller命令](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-controller/src/commands.ts)与[注册表手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/workspace/workspace/README.zh.md)已核实：全局置顶集合最近置顶优先，重复置顶不重排，取消重复调用幂等；原方法要求已知、未归档的会话。Sunday近似仍限当前项目/可见会话，且原宿主没有归档状态，因此不会模拟全局授权、排序或归档拒绝。

## 当前项目会话手动顺序

固定上游[命令源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-controller/src/commands.ts)的`insertSessionBefore`移动已登记会话，可省略锚点追加；目标或锚点不存在时拒绝，移动到自身之前不改变顺序。Sunday新增`context.workspace_controller.insert_session_before(session_id, before_session_id=None)`，通过原`project.sessions.insert_before`写入`CoreThreadSnapshot.workspace_session_order`，再通过原`project.sessions.list`复核顺序；只允许当前项目内原可见会话。重排时只替换可见会话对应的行槽，隐藏会话仍留在原位置。省略锚点将目标追加到列表末尾。

原SQLite写协调器负责持久提交，旧库由原Core列补齐流程添加排序列。目标/锚点缺失、跨项目或隐藏会话映射为`workspace/move-invalid`；提交后列表或操作绑定变化报`workspace/host-changed`及`may_have_changed=True`。派发后取消等待写入实际结算；只有插件显式声明token POST及`http.remote`后，才能经真实认证Remote调用。

新增9项验收覆盖相对顺序、追加、自身锚点、跨项目/隐藏拒绝、隐藏行槽位、SQLite重开、旧库补列、真实认证Remote及取消结算，并验证迁移建议范围。此近似没有DSH全局Peer权限、会话归档、全局顺序事件或原精确错误协议；workspace服务继续保持candidate，固定服务仍为gap。

## 其他上游方法的后端边界

固定上游`WorkspaceRegistry.initializeDefault`要求全局workspace注册表、归档集合、live sessions和持久会话历史均为空，使用Documents目录策略并且不创建Session；Sunday的`CoreProjectStore.create`以固定项目根创建并确保初始会话，既没有相同的全局首次使用判定，也不能伪装成此方法。

上游`insertBefore`修改全局Workspace登记顺序；插件当前只绑定一个项目根，不能安全读取或重排其他项目。上游`delete`只移除Workspace注册表记录，不删除会话持久化；Sunday原`project.delete`会删除该项目关联的会话记录，不能直接映射或替代。上游archive/unarchive使用Registry全局归档集合，并可组合`workspace/session-activity`和`workspace/session-stop`提供方；Sunday没有同一全局状态/活动组合器。follow还包含跨Workspace有序事件与RemoteAccess过滤，现有接口只是当前项目快照轮询。

这些方法保留待办，不通过插件私有影子表、硬删除或扩大项目读取权限模拟。机器契约保持candidate，固定workspace Remote仍为gap。

当前项目查询和路径解析在重复取消时等待原项目读取清理，再释放作用域；控制器的创建/重命名准入与follow复用同一边界，准入取消不会派发后续写入。新增验收覆盖两种查询、创建/重命名准入、follow、真实认证Remote、停用等待及正常项目隔离；不合作的原读取可能延迟结束。
