# 第三阶段：Remote后端边界与原HTTP接入

user:“第二阶段结束后 就继续开展第三阶段”+(先核对真实上游调用与权限顺序，再复用Sunday现有认证和操作权威，不能将任意操作目录暴露为Remote)。

## 固定上游依据

本次实际读取deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3：

- [API Gateway手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/api-gateway.zh.md)。
- [Gateway实现](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/gateway/src/index.ts)，prepareInvocation约第793行：检查Peer、解析明确描述符、精确参数集合及codec，再判定非owner的资源权限，之后才解析Context/lookup和调用实时服务。
- [资源读取实现](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/gateway/src/access.ts)：根据显式读取器、lookup和Context声明提取资源身份，拒绝不能确定资源的调用。

上游只开放声明为Remote的方法，撤回后不能降级到较弱推断。Connection拥有RPC关联、信任及取消，Gateway拥有方法描述符、资源判断和业务分发。流方法另有上行codec、半关闭和inbox上限；会话事件/投影不是同一个Remote协议。

## Sunday当前实际可用边界

原/plugin-http/{plugin}/{path}仅分派manifest声明的精确HTTP路由。它复用PluginHost可用性、原操作归属、permission=auto_allow检查及插件私有令牌；ask_user/hard_block不能经HTTP请求自动批准。普通请求不会得到整个操作目录或任意服务方法的执行权限。

认证令牌是原token_urlsafe生成的ASCII值；非ASCII请求令牌明确返回401，X-Plugin-Token及Authorization/Cookie不转交操作负载。此前3项新增验收已记录。

本批加入真实请求体上限：每个原插件HTTP请求最多1MiB。过大的Content-Length在读取前返回413；无长度或分块请求逐块累计，超过上限立即拒绝，不继续取后续块、不派发操作。无效或负数Content-Length返回400。限内JSON及文本仍走原解析规则。上限针对本路由的请求体，不是通用文件上传/二进制流能力；反向代理、ASGI服务本身的接收缓冲不由该应用检查控制。

3项本批新增验收经原FastAPI/ASGI路由与真实OperationCatalog，测试将上限缩小为64字节覆盖边界，生产默认常量为1MiB：声明超限、分块超限、恰好达到上限。超限不调用操作，分块停止读取后续数据，随后合法请求仍正常。仅运行本批新增相关测试。

## 已接通：明确的一元Remote映射

Sunday原HTTP router现在同时挂载POST /api/core/plugin-remote/{plugin}/{namespace}/{method}。原应用已经包含该router，所以无需另启服务；CoreApiAccessMiddleware继续保护该路径。局域网模式必须先通过原Core bearer认证，再通过X-Plugin-Token插件令牌；不能用客户端提供的owner/role字段代替任一认证。

插件在既有http.routes之外显式声明http.remote，例如：

```json
{"http":{"routes":[{"method":"POST","path":"/echo","operation":"demo.echo"}],"remote":[{"namespace":"demo","method":"echo","route":"/echo","argsSchema":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"],"additionalProperties":false}}]}}
```

请求JSON必须恰好为{"args":{"text":"hello"}}。最多64个方法，namespace/method各1–64个普通名称字符；schema最多32KiB、32个扁平原始类型字段，所有字段必填且不允许额外字段。复用原tool_schema实际校验能力，拒绝复杂对象/数组/引用等未实现schema。不是TypeScript生成codec，参数名称及返回值需要agent人工适配。可选resultEncoding为json（缺省）、multipart或ndjson；其他值/类型拒绝。

映射只允许指向本插件已声明、token认证的POST路由，不能指向公共auth:none路由、未声明路径或直接操作名。每次请求读取当前manifest描述，不缓存旧方法；撤回后404，无OperationCatalog兜底。参数错误400，插件停用409，错误令牌401，操作归属或审批拒绝403；其余原操作结果沿原HTTP envelope返回，不改造成DSH wire envelope。原HTTP入口的可用性、令牌、操作归属及permission=auto_allow检查是唯一执行权威。

新入口共用1MiB有界请求读取器；只沿原操作调用传播请求task取消，不建立脱管后台任务。协作式回调实际finally结束后请求结束；没有DSH cancel帧、强制终止或已提交副作用回滚。客户端断线是否由ASGI服务转为task取消仍沿原服务行为，不新增断线监控协议。

本批17项新增验收经真实FastAPI/ASGI及OperationCatalog，覆盖允许/未知方法、缺失/额外/错误类型/额外envelope、令牌、审批、外部操作归属、停用、公共路由、复杂schema拒绝、描述符撤回、Core+插件双认证、大小上限与原HTTP读取回归、原操作取消清理，以及迁移包说明。大小上限测试缩小为64字节；原宿主操作是实际测试注册的处理器，不代表已移植真实DSH业务插件。

迁移报告的sundayHostContracts.remoteGateway和PORTING.md公开本契约与文档；脚本不自动生成http.remote、不把上游session/goals等方法盲绑定到原操作。

## 显式原始字节结果：remoteGateway v2

本批读取固定上游[二进制传输记录](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/.agents/notes/implemented/architecture/2026-09-17-workspace-file-binary-transfer.zh.md)、Connection的[http-bridge.ts](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/connection/src/http-bridge.ts)、[rpc.ts](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/connection/src/rpc.ts)和[rpc-host.ts](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/connection/src/rpc-host.ts)。上游使用metadata字段及bytes-N附件，path定位原结果中的字节，投影位置为null；其Connection另有server-response/rpcId信封及生成codec。

Sunday在单个http.remote声明中显式添加"resultEncoding":"multipart"，只允许成功一元结果携带Python bytes（包括空bytes及嵌套列表/字段）。不声明时仍为JSON；JSON方法若返回bytes，明确502 gateway/invalid-result，不能隐式扩大出口。业务失败结果仍为JSON，失败中夹带字节同样拒绝，不能以成功multipart发出。

响应为标准multipart/form-data：metadata部分是原Sunday{name,status,payload}投影及attachments数组；每项包含{path,codec:"bytes",part:"bytes-N"}。path相对于整个Sunday envelope，例如["payload","data"]；该位置投影为null。bytes-N部分为application/octet-stream原始字节，不是base64。Unicode字段名只在JSON正文中，不进入HTTP头；附件名固定、边界随机。没有附件时，即使方法允许multipart，也保持原JSON响应。

这沿用上游按路径关联原始字节的机制，但不是DSH server-response/rpcId、Uint8Array生成codec或原样wire兼容。调用者须显式处理Sunday envelope与附件路径；没有自动安装Client解码器，也不改前端。

结果在任何响应发送前完成投影和限制：原始附件总计≤8MiB，metadata编码后≤1MiB，最多64附件、结果深度32、10000节点。只接受无环有限JSON值和显式bytes；不支持的对象、循环、NaN/Infinity、坏UTF-8或超限返回JSON 502 gateway/invalid-result，不泄露业务值或发送半份multipart。普通JSON结果也使用这些结构/metadata限额。结果整体有界缓冲，不是零复制或流；原业务已经执行，结果编码失败不代表撤销副作用。

18项本批新增验收使用原FastAPI/ASGI与OperationCatalog，覆盖根/嵌套字节、空附件、全部256种字节及CRLF、Unicode路径、JSON对照、各项限额/循环/非有限值/未声明字节拒绝、声明枚举拒绝、失败结果、真实会话文件到HTTP原字节往返及隐藏会话拒绝、迁移契约与不自动opt-in。限额测试缩小内部常量；没有新增后台任务、请求体字节或流帧能力。

## 下一步实现约束

继续按上游逐业务实现工作区/会话/文件等控制器的明确方法映射及参数/资源校验。插件自身令牌不是DSH Peer角色或跨会话资源授权；需要资源身份的控制器必须复用原宿主可见性，在对象解析或激活前拒绝越界。客户端传入资源ID不能作为授权结论。

当前仍未提供DSH Peer role、生成codec、资源lookup/Context、DSH精确二进制wire、二进制参数/事件/流条目、WebSocket多路复用或双向流。固定第三阶段20项继续按dsh_phase3_completion.md，完整typertGateway和webServer尚未勾选；纯前端和样式继续排除。


## 显式服务端JSON流：remoteGateway v3

按同一固定上游http-bridge/rpc/rpc-host与workspace-files changes源核对：上游有RPC标识、生成codec、多路复用和取消控制。Sunday当前明确提供近似HTTP服务端流；不声称DSH wire兼容，也不改前端。

单个http.remote声明显式设定"resultEncoding":"ndjson"；请求地址、精确args和1MiB请求限额不变。目标仍须本插件token POST路由、原操作归属及auto_allow。Python操作处理器须返回OperationResult(request.name, source)，source是返回自身的异步迭代器，且提供aclose；直接返回裸迭代器会被原操作桥包装成result对象，因此明确拒绝，不静默猜测嵌套字段。原进程插件的JSON操作协议尚不提供这种Python对象交接。

成功响应Content-Type为application/x-ndjson，无Content-Length，Cache-Control=no-store、nosniff。每行UTF-8有限JSON：

```json
{"kind":"item","payload":{"kind":"ready"}}
{"kind":"item","payload":{"kind":"change","change":{"absolute_path":"...","version":"...","bytes":10}}}
{"kind":"end"}
```

正常有限源完成发end；源/编码失败发{"kind":"error","code":"gateway/stream-failed"}，不泄露异常文本或源值。已开始响应不能再改HTTP状态。无end或末帧error均不代表完整成功；连接故障可能没有终止帧。每个完整item帧编码后≤1MiB，深度32、10000节点，拒绝循环/NaN/bytes；帧独立有界，无预读队列或全流缓冲。不支持二进制帧、输入流、自动重连/游标、心跳、WebSocket、双向流或DSH stream-cancel信封。

每插件最多32个HTTP活动流（429）；SDK自身32流限额独立适用。send等待期间不拉取下一项，网络背压不累积提供方队列；会话文件SDK自己的最新帧合并规则仍适用。HTTP断连/请求取消取消并等待pull/send退出，再等待source.aclose真实结束，最后释放容量；重复取消仍等待清理。提供方必须配合取消/关闭，不承诺强杀任意Python回调。

每帧发送前及独立0.5秒监控从原host、supervisor generation、当前manifest、操作可用性/归属和现有插件令牌复核；空闲源或阻塞send也会被撤回终止。读取令牌使用原入口的只读模式，不会重新生成已撤销令牌。此检查采用整个manifest精确比较，因此无关清单修改也保守终止旧流。撤回先回收源，再最多0.5秒尝试发gateway/stream-closed终止错误；连接阻塞或断开可截断。Core认证仍由原中间件执行；资源可见性由具体控制器的原宿主处理，不等同DSH Peer角色。

无效/未声明/失败状态下返回迭代器，先真实关闭再502 gateway/invalid-stream；普通非流业务错误仍走JSON。显式映射不自动激活提供方、不扩大原会话/文件根或权限。只有HTTP流端点增加断连监控；原一元入口的取消边界不变。

本批22项新增验收覆盖真实FastAPI/ASGI NDJSON、有限源终止、原Core+插件认证、参数/审批拒绝、坏帧/字节/限额、撤回/换代/停用/令牌撤销、空闲源断连/取消、重复取消等待实际关闭、活动容量和阻塞send无预读、错误/未声明迭代器关闭、原插件处理器及真实会话文件变化到HTTP链路，以及迁移交接。没有将DSH精确wire/双向流或完整第三阶段勾选完成。
