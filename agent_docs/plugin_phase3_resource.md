# 显式插件资源 GET/HEAD

user:“第二阶段结束后 就继续开展第三阶段”+(资源访问复用现有插件令牌与操作归属，不冒充全局WebServer)。

插件在 `plugin.json` 的 `http.resources` 中明确声明，例如 `[{"kind":"exact","path":"/image","route":"/resource"},{"kind":"prefix","path":"/docs","route":"/resource"},{"kind":"fallback","route":"/resource"}]`。每项 `route` 必须指向本插件已声明的 token POST 操作，操作实际挂载、归属本插件且 `auto_allow`，仅进程内 Python 处理器可用；不自动生成声明。插件内部按精确路径优先、最长前缀、唯一回退选择，前缀按路径段匹配。请求 `GET` 或 `HEAD /api/core/plugin-resource/{plugin}/{path}`，使用已有插件令牌；其他方法405且不读请求体。

原操作收到 `request.payload["body"]` 中的 `path`、`method`，查询参数仍在 `query`，认证头不传给处理器。处理器返回恰含 `content` 字节和 `mime_type` 的对象；最多8 MiB，MIME是无参数的类型/子类型。HEAD执行同一处理器、保留字节长度但不发内容。资源路径最多2048字符，查询串最多8192字节；路径限制比上游更严格。返回含`nosniff`、沙箱CSP及`no-store`。读取的是处理器实际提供的字节；会话/项目等业务资源权限必须由该处理器复用原宿主判断。

派发前、空闲期间、处理器结算后及实际发送前复核原宿主、令牌、声明和操作注册身份；撤回或断连取消并等待真实操作清理，重复取消等待清理；不合作的处理器可延迟结束。处理器可能已产生副作用，撤回错误标记`may_have_changed`。每插件与Remote流共享32个处理槽，覆盖处理器和异常来源清理，缓冲响应开始网络发送前释放，不限制慢客户端尚未收完的响应数量。GET/HEAD处理期间监视断连，收到的请求体超过1 MiB会中止；快速完成的处理器不保证验证整个请求体，且请求体不传处理器。检查非跨线程或跨进程原子锁。

30项新增验收覆盖真实插件文件和ASGI GET/HEAD、路由顺序、令牌、归属/审批、大小/类型、未知声明、进程后端拒绝、撤回/取消/断连、未声明异步来源回收、槽位及迁移说明。固定上游[源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/host/webserver/src/index.ts)与[手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/host/webserver/README.zh.md)提供全局注册、可流式资源、进程内readResource/Peer、upgrade及监听/TLS生命周期；本项仅插件隔离的近似，未实现全局路由、任意Peer读取或监听/upgrade等能力，不能标记整个第三阶段完成。

HEAD错误响应也不发送实体内容，保留对应响应头；新增ASGI验收直接检查错误认证时的底层响应帧。

## 显式原始字节流

资源声明可显式添加 `"encoding":"stream"`；处理器的 `content` 必须是自身拥有、可`aclose`的异步字节迭代器，默认`buffered`仍只接受字节。每块≤256 KiB，总量≤8 MiB、最多4096块；消费遵循发送背压，不预取下一块。流式HEAD调用处理器后关闭来源、不拉取内容且不返回Content-Length。认证、路由、来源类型与MIME沿原规则，未声明的嵌套异步来源先关闭再拒绝。

流发送期间维持共享槽位，逐块及空闲时复核原授权；断连、撤回、发送失败和取消均等待在途读取及来源清理后释放槽位。响应头发出后遇到非法块、超过限额或授权撤回将中止响应，不能再改HTTP状态；调用方应视不完整连接为失败。来源清理不合作可延迟结束，发送前检查不是跨线程原子锁；缓冲资源仍在发送前释放处理槽。14项新增验收覆盖真实ASGI字节流、背压、HEAD、超限、撤回、断连、重复取消、未声明来源清理、缓冲对照和迁移。固定上游[源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/host/webserver/src/index.ts)与[手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/host/webserver/README.zh.md)支持资源流、背压、HEAD取消及断连；本项仍非DSH Peer、全局路由、任意Fetch Response、压缩或任意Peer进程内读取。

## 当前插件进程内读取

`await context.plugin_resources.read(path, method="GET", query=None)`固定调用当前插件、原宿主和原显式资源路由，复用同一令牌/归属/审批及路径匹配；只支持GET或HEAD，不接受其他插件或任意URL。可选query为字符串键值字典，经URL编码后最多8192字节，不能表达重复键；非法参数派发前拒绝。仅读取已有插件令牌，不生成密钥或向处理器/结果暴露令牌；缺令牌返回401，缺原宿主明确报错。返回`status`、有限安全响应头和`body`字节；流式资源在进程内完整缓冲，最多8 MiB，失败不返回部分内容。HEAD不返回内容，已知长度沿原规则返回。

作用域撤回、取消及在途来源清理沿原资源通道；调用会执行插件资源处理器，处理器自己的资源授权仍由它负责，检查非原子。18项新增验收覆盖原实际GET/HEAD、缓冲/流、路径、缺令牌/宿主、令牌隔离、撤回/重复取消、部分流失败及迁移；另8项覆盖查询编码、HEAD、空查询和非法参数。固定上游[源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/host/webserver/src/index.ts)的`readResource`由调用方先准入任意Peer，接受Fetch Request并返回Response；本项仅当前插件、已有令牌、有界查询且完整缓冲，非上游Peer策略或原样流式读取。
