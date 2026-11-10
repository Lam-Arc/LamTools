# 会话编码文件保存

user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(通过原会话附件宿主保存明确编码的文件，不伪造上游暂存凭证)。

固定上游deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的[file-upload源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/file-upload/src/index.ts)和[中文手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/client/file-upload/README.zh.md)已核对。上游上传提供流式载体、Agent/Session精确所有权和供prompt事务绑定/消费的暂存凭证；客户端还有进度和取消。

`await context.file_uploads.save_encoded(session_id, filename=..., content_base64=..., mime_type=None)`只接受规范标准base64（无空格/换行、正确填充），解码最多512KiB；空字节允许。复用原session_data/attachments的会话可见性、固定项目、文件名/MIME校验和持久文件存储。返回原附件记录，包含原id/session_id/path等字段；这不是DSH暂存收据，不自动绑定prompt，也没有上传进度、图像归一化、流式输入、DSH Agent恢复或消费/回滚协议。不要将附件ID交给DSH收据消费器。

原作用域、项目根和会话数据宿主在派发前固定并检查。写入一旦派发，沿原finish_on_cancel等待真实写入结算；重复取消调用者也不会截断已接收事务，但调用者收到取消时附件可能已经保存，需要查询原附件状态而不是盲目假定回滚。原服务负责原始文件/数据库一致性；不声称跨资源事务。可由插件原operations处理器明确映射token POST和http.remote；原HTTP JSON请求上限1MiB，512KiB内容的base64及小参数在该范围内。

16项新增验收覆盖实际原附件文件/SQLite、隐藏会话、八种非规范编码、解码限额、重复取消后的真实持久写入、原插件操作→HTTP原字节往返及无效令牌、启动代/根/宿主撤回和迁移交接。没有改用用户真实凭据；没有自动注册路由或安装客户端。

原写入返回后，持有原启动代租约，再经同一原会话附件get复核可见性、项目及附件归属，并在等待前后复核宿主绑定。已保存后发现会话不可见或绑定失效时，Python异常标记`may_have_changed=True`；最终复核等待被取消也可能已保存。显式HTTP通道不保证透传该标记，调用方须先查原会话附件，不能盲目重试。7项新增验收覆盖实际文件已写入后隐藏会话、替换宿主、项目根或启动代、最后复核取消、真实HTTP不回显旧附件ID和正常保存。检查非跨存储原子锁，仍无DSH暂存/绑定/消费收据。

原创建过程先保存内容文件再登记索引，甚至索引已提交后也可能抛错。除原门面明确在调用宿主前拒绝的参数错误外，创建异常脱敏为`file-upload/write-uncertain`并附Python属性`may_have_changed=True`；这也可能保守覆盖写入前失败，普通HTTP不保证透传该属性。4项新增验收实际提交后模拟底层错误、检查参数拒绝及真实HTTP脱敏。
