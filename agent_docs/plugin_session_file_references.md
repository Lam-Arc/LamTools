# 会话执行目录的文件引用

user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(按真实可见会话的当前执行目录扫描，复用原文件候选与取消清理)。

固定上游deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的[Session Controller手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/README.zh.md)和[file-references.ts](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/src/file-references.ts)已核对。上游`fileReferences.list`由Session资源解析Agent，查询该Agent工作目录，调用取消信号，并可能恢复普通Session。

`await context.session_file_references.list(session_id, query='', limit=100)`先调用原working_directory会话可见性和执行目录宿主，确保所属项目等于上下文固定项目且目录存在，再复用原`PluginFileReferencesAPI.list`扫描。仅执行目录及其子目录参与扫描，不返回其他项目或隐藏会话内容；不主动恢复或启动Agent。返回`{items:[{path,kind}], truncated, scanned}`，path相对该执行目录，kind为file/directory；不是上游生成FileReferenceCandidate对象或Peer资源解析。

query须为至多512字符且不含NUL的字符串，limit须是1–1000的整数，参数错误在原宿主准入前拒绝。复用原扫描最多5000条、目录深度64、排序、排除链接/重解析点和依赖目录，以及截断标志；并非原子文件快照。每次目录准入及扫描后复核原宿主、项目根和启动代。取消时原线程扫描收到停止标志，调用等待线程实际退出后释放作用域租约；正处于系统调用时不能强制抢占。

插件可在自身operations处理器显式调用，再经已声明token POST及http.remote方法返回。原SQLite会话→原目录→实际文件扫描→HTTP已验收，隐藏会话被拒绝；没有自动开放整个控制器或伪造DSH wire。原普通project.file_references与此会话执行目录入口各自保留；不同项目会话返回workspace-file/outside-workspace。

13项新增验收覆盖选定目录及隐藏/跨项目会话、五种错误参数先拒绝、原目录宿主/启动代/项目根撤回及取消时实际线程退出、真实HTTP及迁移交接。完整DSH Agent lookup/自动恢复、精确候选字段及客户端传输尚待移植。

扫描完成后重新调用原会话执行目录准入；会话隐藏、删除或执行目录变化时丢弃旧目录候选。新的5项验收覆盖扫描中隐藏/更换目录、正常结果、末次会话读取期间取消及真实HTTP隐藏拒绝。原目录授权与扫描之间仍无原子锁；扫描本身是有界线程，不是文件系统快照。
