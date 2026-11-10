# 当前插件Remote声明清单

user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(读取当前插件实际声明和原操作归属，不把清单当成Peer授权决策)。

固定上游deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的[remote-access源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/remote-access/src/index.ts)定义Peer principal、action/resource和role binding、失败关闭策略与follow快照。本接口没有实现这些策略。

`context.remote_access.declared_methods()`只读取当前插件的原host及当前manifest：沿用原`read_remote_methods`、原token POST路由、`read_operations`，只返回原OperationCatalog中实际挂载、owner为本插件且permission=auto_allow的namespace/method/result_encoding，按名称排序。无宿主、插件不可用、声明无效或宿主/目录/启动代变化均明确报错；读取期间manifest变化也拒绝发布旧清单。没有读取或返回插件令牌。

这是本插件的方法声明和可用性快照，不判定某个客户端是否持有Core认证/插件令牌，也不判定Session/Workspace等资源是否授权；实际请求仍经过原认证和具体业务处理器的资源检查。插件可通过自己的明确token POST/http.remote处理器返回该清单；不会自动开放路由或提供DSH Peer policy/follow/roles/grants。

13项新增验收覆盖当前声明、撤回、未挂载/外部owner/需审批排除、宿主/目录/启动代/禁用、缺provider与错误声明、读取期间撤回、真实HTTP无令牌泄露及迁移交接。完整remoteAccess仍待实现。
