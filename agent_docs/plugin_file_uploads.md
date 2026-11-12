# 会话编码文件保存

user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(通过原会话附件宿主保存明确编码的文件，不伪造上游暂存凭证)。

固定上游deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的[file-upload源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/file-upload/src/index.ts)和[中文手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/file-upload/README.zh.md)已核对。上游上传提供流式载体、Agent/Session精确所有权和供prompt事务绑定/消费的暂存凭证；客户端还有进度和取消。

`await context.file_uploads.save_encoded(session_id, filename=..., content_base64=..., mime_type=None)`只接受规范标准base64（无空格/换行、正确填充），解码最多512KiB；空字节允许。复用原session_data/attachments的会话可见性、固定项目、文件名/MIME校验和持久文件存储。返回原附件记录，包含原id/session_id/path等字段；这不是DSH暂存收据，不自动绑定prompt，也没有上传进度、图像归一化、流式输入、DSH Agent恢复或消费/回滚协议。不要将附件ID交给DSH收据消费器。

原作用域、项目根和会话数据宿主在派发前固定并检查。写入一旦派发，沿原finish_on_cancel等待真实写入结算；重复取消调用者也不会截断已接收事务，但调用者收到取消时附件可能已经保存，需要查询原附件状态而不是盲目假定回滚。原服务负责原始文件/数据库一致性；不声称跨资源事务。可由插件原operations处理器明确映射token POST和http.remote；原HTTP JSON请求上限1MiB，512KiB内容的base64及小参数在该范围内。

16项新增验收覆盖实际原附件文件/SQLite、隐藏会话、八种非规范编码、解码限额、重复取消后的真实持久写入、原插件操作→HTTP原字节往返及无效令牌、启动代/根/宿主撤回和迁移交接。没有改用用户真实凭据；没有自动注册路由或安装客户端。

原写入返回后，持有原启动代租约，再经同一原会话附件get复核可见性、项目及附件归属，并在等待前后复核宿主绑定。已保存后发现会话不可见或绑定失效时，Python异常标记`may_have_changed=True`；最终复核等待被取消也可能已保存。显式HTTP通道不保证透传该标记，调用方须先查原会话附件，不能盲目重试。7项新增验收覆盖实际文件已写入后隐藏会话、替换宿主、项目根或启动代、最后复核取消、真实HTTP不回显旧附件ID和正常保存。检查非跨存储原子锁，仍无DSH暂存/绑定/消费收据。

原创建过程先保存内容文件再登记索引，甚至索引已提交后也可能抛错。除原门面明确在调用宿主前拒绝的参数错误外，创建异常脱敏为`file-upload/write-uncertain`并附Python属性`may_have_changed=True`；这也可能保守覆盖写入前失败，普通HTTP不保证透传该属性。4项新增验收实际提交后模拟底层错误、检查参数拒绝及真实HTTP脱敏。

## 有界异步分块接收

`save_chunks(session_id, filename=..., source=..., size=..., mime_type=None)`接收可关闭的异步字节来源，声明总长0–8MiB，单块不超过256KiB、最多4096块；长度不符、来源错误或中途失效均在持久写入前拒绝。接收在宿主内存汇总，完成后复用同一原附件保存及提交后复核；不是直接流式写盘，也不是上游暂存收据。该接口取得有效来源后负责关闭它；参数预检失败前来源仍由调用方持有。

每块和约0.2秒空闲等待期间复核原会话/项目及宿主，启动代撤回主动取消在途读取；取消或撤回等待来源读取及关闭清理，来源不合作可能延迟停用，复核间隔也不是严格时限。接收完成并派发写入后，取消仍等待原提交且可能已保存。24项新增验收覆盖真实临时附件、超512KiB分块、错误/长度/块数限制、隐藏/宿主/根/启动代撤回、重复取消、来源清理、原写入结算、已有编码接口和显式Remote。HTTP验收由插件处理已缓冲JSON再提供分块；现有HTTP不是上游原始流式请求，仍有1MiB请求上限，无进度、图像规整、凭证消费或DSH wire。固定上游[源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/file-upload/src/index.ts)和[手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/file-upload/README.zh.md)的流式载体及凭证生命周期仍待实现。

## 明确声明的原始 HTTP 输入

原始上传声明可选`resource=session`或`resource=workspace`，以唯一的`x-resource-id`头明确当前资源，处理器从body读取相同`resource_id`；原项目/会话准入发生在请求体读取前，分块、空闲及提交后复核。16项新增验收覆盖真实临时附件与项目、非法头、跨项目、撤回和原无声明路径。检查非原子，处理器仍负责它使用的其他资源；详见[Remote资源准入](plugin_phase3_remote.md)。

上述旧 HTTP 缓冲说明适用于普通 JSON 路由；另可按 [原始上传说明](plugin_phase3_remote.md) 显式声明 token POST，直接接收有界网络分块，再交给 `save_chunks`。后者仍在内存中汇总后调用原附件存储，处理器必须验证会话范围；无 DSH 暂存收据、进度、图像规整或精确 wire。43 项新增验收包括实际 HTTP 分块、授权撤回、断连及清理。
