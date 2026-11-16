# 插件注册表连通性探测

user:“第二阶段结束后 就继续开展第三阶段”+(先接通可独立验收的Host后端探测，客户端选择界面留待前端阶段)。

固定上游`deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3`：

- [Host源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/ui-plugin-manager/src/index.ts)：`fastest()`只在调用时探测固定的npm官方源与npmmirror `/-/ping`，取先成功的HTTPS响应。并发调用共享探测；胜出后取消并等待另一响应清理；成功和不可用结果按TTL缓存；卸载中止在途请求并等待完成。默认启用、期限1500ms、缓存300000ms。
- [Host行为测试](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/ui-plugin-manager/tests/registry-probe.host.spec.ts)覆盖并发共享、两端失败、超时、卸载及响应体关闭。
- [中文手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/ui-plugin-manager/README.zh.md)将Host探测与浏览器选择、管理页及安装流程分开说明。

Sunday公开`context.plugin_registry_probe.fastest()`，目标地址不可由调用者传入。每个插件启动代共享一个Host HTTP客户端探测，遵循现有网络代理和CA设置，拒绝重定向；仅2xx视为成功，网络/状态失败、两端都不可用或超时均返回`None`。并发调用共享结果，成功及`None`均按TTL缓存。停用会取消在途请求，等待双方HTTP清理；停用后的旧上下文拒绝调用。默认值与上游相同，Host可在创建插件上下文时设`registry_probe_options`的`enabled`、`timeout_ms`、`cache_ttl_ms`；HTTPS目的固定，不支持任意registry URL。

本实现只接通Host可调用的后端依赖；没有迁移浏览器初始选择、UI、安装器配置、Typert Remote路由或全局Profile设置，因此固定20项中的`pluginRegistryProbe`仍未整体完成。探测只在调用`fastest()`时发出两个公开HTTPS GET，不传插件凭据、账户身份或环境数据；未验证下载速度或安装源可用性。

`core/tests/test_plugin_registry_probe.py`的7项用例通过受控HTTPX请求覆盖固定URL、两个registry分别胜出、共享竞速、赢家响应体关闭、失败缓存、期限、重复请求取消、停用清理、禁用配置及迁移提示；不访问公网。
