# 当前项目工作区重命名

user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(原项目CAS重命名限定当前插件项目，已派发写入按真实提交结算)。

固定上游deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的[workspace命令源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-controller/src/commands.ts)与[workspace注册表手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/workspace/workspace/README.zh.md)已核对：上游rename要求非空且全局唯一标题，并在串行写链上修改原实体。

`await context.workspace_controller.rename(project_id, name, expected_revision=...)`先经原project.get读取并确认与当前context.work_root一致，再通过原project.update/CoreProjectStore.update提交CAS。name为非空字符串、最多256字符；expected_revision须为正整数。原project.update现接受可选expected_revision并传给原CoreProjectStore；未传时保留原调用行为。成功返回原project字典及更新后revision。其他项目与不存在均拒绝；原revision冲突映射workspace/conflict。Sunday原项目存储允许不同项目同名，因此此近似不满足DSH全局标题唯一性。

作用域、项目根和原操作目录在准入后复核。派发前取消不会写入；一旦原写入派发，重复取消仍等待实际结果结算，取消不代表回滚。提交后绑定变化或结果不可信报workspace/host-changed及may_have_changed=True；无法分类的派发后错误报workspace/rejected及may_have_changed=True，原CAS冲突可确认未写。写入异常报workspace/write-failed并保守标记可能已变化。原SQLite事务与同步日志仍为权威，不新增第二套存储。

仅插件自身原处理器明确声明token POST/http.remote后可经HTTP调用；测试验证错误令牌不写、合法调用改变真实SQLite记录。15项新增验收覆盖CAS、跨项目拒绝、非法参数、等待中撤回/取消、重复取消后真实提交、提交后绑定变化及未分类错误、真实HTTP和迁移交接。DSH工作区创建/非破坏删除、全局排序/归档/置顶、Peer权限、实时follow和精确codec仍未完成；原Core项目删除会删除相关Session，不应直接映射到上游非破坏删除。
