# 当前项目只读查询

user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(按依赖提供真实项目只读入口，复用原数据库与操作目录，并固定当前插件项目)。

固定上游deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的[workspace注册表源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/workspace/workspace/src/index.ts)、[中文手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/workspace/workspace/README.zh.md)与[控制器命令](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-controller/src/commands.ts)均已核对。上游get为按WorkspaceId查找实体；其全局有序列表、创建/删除、session成员、归档/置顶和故障恢复不由本接口冒充。

`await context.workspace_registry.get(project_id)`调用原OperationCatalog的`project.get`，读取原CoreProjectStore/SQLite。project_id须为非空字符串且至多128字符；返回与当前context.work_root规范路径一致的原project字典。其他项目及不存在项目均返回None，不暴露其他项目字段或路径；没有可由请求指定的授权根。原项目字段为id/name/work_root/icon_key/color_key/workspace_id/revision及时间字符串，不是DSH Workspace实体或生成codec。项目ID由调用方提供，接口不枚举全局项目，也不自动激活Agent。

接口绑定当前插件启动代、项目根和原操作目录；等待后再次核对，期间目录替换/项目根变化/撤回则拒绝发布旧结果，取消传播给原读取并释放作用域租约。不存在通过原project.get明确的not-found结果映射为None；其他原错误归类为workspace-registry/rejected，操作缺失为workspace-registry/unavailable，绑定变化为workspace-registry/host-changed。仅是读取前后检查，并非跨数据库和授权的原子事务或OS级目录隔离。

插件可在自身operations处理器中显式调用，再将该处理器声明为已有token POST路由和http.remote方法。实际SQLite→原project.get→插件处理器→HTTP验收覆盖当前项目、其他项目不可见和无效令牌；默认不公开路由。数据库关闭再打开后同一原项目ID/名称仍可查。

本批13项新增验收覆盖真实读取/隔离、五种非法ID先拒绝、等待期间目录/启动代/根变化及取消、真实HTTP、数据库重开与迁移交接。上游移除注册不删除Session，而当前Core project.delete会删除关联会话；不能直接将上游删除映射为该原操作。创建、排序、会话成员及归档/置顶、Workspace follow/Peer授权均仍须各自实现与验收；纯客户端/UI不在当前工作范围。


## 从当前目录解析项目编号

`await context.workspace_registry.resolve_by_path(path)`接受1–4096字符的绝对路径，仅当规范路径等于调用上下文固定项目根时进入原project.resolve；其他路径不访问项目数据库并返回None。原CoreProjectStore.resolve_by_path使用原规范路径和SQLite精确读取，未登记返回None，不创建目录或项目；成功返回同一原project字典。不是DSH跨工作区全局resolveByPath。等待期间根、原操作目录或插件启动代变化时拒绝结果；取消传播并释放作用域租约。`project.resolve`为原Core操作目录的只读操作，HTTP仍需插件显式映射。

新增14项验收覆盖原SQLite精确解析、其他项目派发前拒绝、五种非法参数、四种等待后失效/取消、缺失根不创建、原插件操作到HTTP和迁移交接；与本轮前13项一起仅运行这两个新增测试文件，27项通过。不是完整workspaceRegistry或Workspace follow。


## 当前项目的可见会话

`context.workspace_registry.sessions(project_id, limit=50, cursor=None)`先验证当前项目，再复用原session_query的可见会话扫描：每次最多扫描1000条原记录，按原会话metadata中的绝对工作根过滤，重新只读核对可见性和根，返回SessionSummary分页；发布前重新验证项目仍存在和宿主绑定。limit为1–100，游标绑定插件代、项目ID及固定项目根，120秒过期，最多保留128个；游标不能与全局session_query互换。空页仍可能有下一游标，因隐藏或其他项目记录也会消耗扫描预算。

这是依照当前原会话work_root推导的只读近似，按会话ID扫描；不是DSH持久成员账本、新到旧顺序、归档/置顶或恢复语义。各页不是数据库快照，读取与权限检查之间没有跨进程原子锁。缺session_query提供方报错。14项新增验收覆盖真实SQLite、隐藏及其他项目、游标隔离、无效参数、原项目删除/会话隐藏与等待中失效、取消、真实HTTP及迁移。

扫描完页面后再次只读核对已选记录并更新摘要，过滤扫描后隐藏或迁移的会话；过滤可能产生短页，游标仍按已扫描位置推进。这些逐项读取和随后的项目核对不是原子快照，后续并发变化仍可能发生。2项新增验收覆盖早先选中会话在后续读取中隐藏，以及相同场景经真实HTTP返回。

项目ID查询和根目录解析完成后还复核原操作注册身份；同名重新注册或失效则拒绝发布旧结果。2项新增验收覆盖原SQLite读取期间的两种同名替换，检查不是跨线程原子锁。
