# Product Analytics 能力缺口

user:“完全不碰前端和样式，纯客户端/UI项保留明确待办”+(保留客户端事件发送边界，不把现有通用遥测误记为完整 Product Analytics)。

固定上游为`deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3`：

- [Host及Remote实现](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/product-analytics/src/index.ts)：提供`enabled()`、可取消的`watchPolicy(signal)`以及`report(event)`。Host在接受事件时遵从动态启用策略，等待有界静态环境采集和原账户身份读取，再提交到原`productTelemetry`；卸载会中止环境查询并等待结束。
- [桌面客户端实现](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/product-analytics/src/client/index.ts)：仅桌面进程挂载，通过认证Remote发送事件，并订阅可重连的策略流；Web客户端不发送产品事件。
- [事件类型](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/product-analytics/src/events.ts)列出产品事件名和逐事件字段，避免任意属性采集。
- [中文手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/product-analytics/README.zh.md)说明数据范围、身份、环境采集与导出策略。

Sunday已公开的`context.otel`基于[`telemetry_access.py`](../core/src/lamtools_core/plugin_system/telemetry_access.py)，默认`sharing="disabled"`，启用时要求插件明确给出HTTP(S)采集端；它提供通用OTLP日志/会话记录器，没有上述产品事件白名单、Host策略Remote、设备/用户身份组合或桌面环境采集。因此不能把它当成等价Product Analytics，也不能为补齐名称而默认开放收集。

本阶段继续把`productAnalytics`保留为`gap`：客户端事件调用受前端排除；独立Host实现需要可验证的Sunday启用策略、身份/环境来源、事件白名单、Remote鉴权、取消和卸载清理契约，再以真实测试接到原遥测提供方。当前未增加未安装的提供方或空壳接口，也未修改前端。
