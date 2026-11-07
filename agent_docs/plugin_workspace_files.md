# 会话文件控制器近似接口

user:“第二阶段结束后 就继续开展第三阶段”+(用原会话身份和执行目录读取文件，不能让Remote请求传入授权根；保留清晰的上游差异)。

## 官方固定依据

本批实际读取deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的[包手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-files/README.zh.md)、[index.ts](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-files/src/index.ts)和[types.ts](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-files/src/types.ts)。

上游以workspaceFileScopeId携带Session身份，经lookup从live/header或冷存储取得根，不由Client指定。read按1起算行窗口，readBytes支持完整/范围及baseFile并通过二进制Remote返回Uint8Array；stat/list和changes流另有明确结果与错误。上游允许某些根外文件读取、目录链接及远程提供方，这些不能从Sunday的严格本地文件API自动推导。

## Python公开接口

context.workspace_files绑定当前插件启动代、原working_directory服务和固定项目。每次调用通过原目录服务取得可见会话的当前执行目录，等待前后复核同一宿主和启动代，确认项目归属及目录存在；仅随后构造原PluginFilesystemAPI。没有客户端root参数，不主动激活Agent，不修改会话记录或修订，不新建会话存储或文件权限权威。

| 方法 | 参数与实际结果 |
| --- | --- |
| await stat(session_id, path) | 普通文件；absolute_path/version/bytes |
| await list(session_id, path='.', limit=100) | 原有限目录列举；path/entries/truncated；entries沿原name/kind/size/modified_ns |
| await read(session_id, path, offset=1, limit=100) | offset为1起算正整数，limit为1–5000；返回stat字段及offset/text/lines/eof |
| await read_bytes(session_id, path, offset=None, length=None, base_file=None) | 两者均None时完整文件≤1MiB；否则使用原0起算字节窗口≤1MiB，允许零长度/EOF短读；返回stat字段及offset/data/eof，data为Python bytes；base_file指定同根普通文件，path须相对且从其父目录解析 |
| await changes(session_id, path, interval=0.5) | 返回受管异步迭代器，先ready，再发合并后的change；显式await stream.aclose()关闭 |

read使用原UTF-8增量stream_text，源文件≤64MiB，读取块8KiB；只保留请求页，跳过前缀不积累整行，页UTF-8内容含行间分隔符≤1MiB。空文件返回0行；单空行返回1行但text为空；末尾LF是行终止符，不额外创建空行。页text无最终终止符；窗口后还有实际字符或空行则eof=false。原CR保留，不额外规范化换行。

窗口前缀和当前读取块必须可解码为UTF-8且无NUL，因此块中位于请求页之后的坏数据也可能使本页拒绝。原stream_text的源大小、变更检测及作用域规则仍适用。version仅为stat:size:mtime_ns，不是内容指纹；metadata先于内容读取，不提供原子文件快照。

## 错误、取消与清理

本控制器错误为WorkspaceFileError(ValueError)，包括workspace-file/invalid-request、host-changed、outside-workspace、not-found、not-regular-file、not-text和too-large。其他fs/*、working-directory/*、session-data/*或service/*沿原宿主错误归属，不能按消息文本判断。隐藏会话在进入文件系统前由原可见性拒绝。

等待会话准入期间可以取消；取消或撤回后不继续文件读取，原租约释放。文件部分为原同步可信插件API，开始后不能承诺异步抢占系统读调用；普通读取没有额外线程、后台任务或长期打开的文件句柄；changes的原受管监听任务另见下节。流分页在finally关闭原迭代器，原stream_text每块yield前已关闭句柄。

所有文件读取和目录列举均限制在选定会话执行目录，拒绝已观察的链接/重解析点。沿用原路径检查的并发竞态限制，不声称OS级隔离、任意文件系统安全快照或网络文件系统支持。

## Remote与迁移

SDK方法可由插件原operations处理器调用，再经明确http.remote扁平参数映射公开；本批真实HTTP/SQLite/文件验收验证read及额外root字段拒绝、隐藏会话拒绝。没有自动公开整个控制器或新的全局文件权限入口。SDK现支持base_file和changes；DSH复杂options/字段投影仍需人工移植，changes可通过显式resultEncoding=ndjson服务端JSON流输出；read_bytes的Python bytes不能直接充当JSON响应，但现在可由显式resultEncoding=multipart的Sunday Remote输出原始字节附件，实际HTTP往返及隐藏会话拒绝已验收。此格式不等于DSH envelope/codec，详见plugin_phase3_remote.md。

迁移报告新增workspaceFileMethods，为read/readBytes/stat/list/changes给出context.workspace_files对应候选及agent-required差异。未知方法无候选；changes候选保留轮询差异，网络流需人工显式ndjson映射；生成PORTING.md保留限制与文档，不生成未经授权的Remote映射，runtimeVerified仍为false。

本批16项新增验收覆盖实际行页/空行/EOF、Unicode、跨块与恰好页限额、跳过长前缀、坏文本、原二进制窗口/完整文件、目录/元数据、选定目录与隐藏会话、宿主替换/撤回/取消、真实HTTP链路及迁移交接。页预算边界测试缩小到16字节；生产默认1MiB。


后续二进制接续：remoteGateway v2本批18项新增验收包含真实会话文件→原操作→HTTP multipart原始字节往返；SDK本身仍返回Python bytes，默认不自动公开或opt-in，路径/限额/会话可见性规则不变。


## SDK变化流与关联文件（workspaceFiles v2）

固定上游[changes.ts](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-files/src/changes.ts)使用共享监听与异步队列；Sunday复用原PluginFilesystemAPI.watch/FileWatch的元数据轮询，不另建监听引擎。SDK示例：

```python
stream = await context.workspace_files.changes(session_id, "notes.txt", interval=0.5)
try:
    async for frame in stream:
        # ready: {"kind": "ready"}
        # change: {"kind": "change", "change": {"absolute_path": ..., "version": ..., "bytes": ...}}
        # absent: change包含absolute_path及absent=True
        await consume(frame)
finally:
    await stream.aclose()
```

首次准入由原可见会话/执行目录权威取得根，后续监听固定该目录；不是自动跟随会话目录切换。可监听缺失末项，但原父目录必须存在。interval须为有限数值0.01–60秒；每个插件启动代最多32活动流、32个不同根，根缓存直至停用。每个流独立保留ready和一个最新change，慢消费者会合并中间变化，不能作为完整事件日志或审计记录。仅允许一个并发消费者，否则workspace-file/concurrent-read；容量错误为workspace-file/watch-limit，原监听参数/文件错误仍沿fs/*。

普通文件版本为stat:size:mtime_ns；目录版本为原有限快照的metadata哈希，可感知已有直属子文件元数据变化；最多1000直属项，不递归，不能保证识别同size/mtime内容变化或两次轮询间短暂变动。没有原生Chokidar、fs-observed标签、DSH opaque版本或远程监听提供方。

显式aclose、等待下一帧时取消、插件停用均等待原监听任务真实退出，不依赖消费方继续拉取；关闭调用者被重复取消仍等待任务退出再传播取消。原目录宿主替换或启动代撤回亦终止监听；没有为整个消费者等待持有插件操作租约。它只提供Python SDK异步迭代，现可通过明确http.remote resultEncoding=ndjson输出服务端JSON流，原operations处理器须返回OperationResult(name, stream)；无WebSocket或DSH server-stream精确协议，不能将流直接放入普通JSON/multipart一元结果。

read_bytes的base_file必须为同根普通文件；path只允许相对路径，拒绝绝对路径、盘符/URL和越界。完整/窗口读取限额及原链接检查不变。不是任意关联文件授权或新的文件根。

本批22项新增验收覆盖真实文件修改/删除/重建、目录子项版本、缺失文件创建、慢消费合并、容量释放、宿主替换、空闲消费者关闭/停用、pull取消、重复取消关闭调用者、无效轮询参数、关联二进制文件/范围及无效路径、迁移交接。没有据此验收网络流。

后续Remote接续：remoteGateway v3新增22项验收，包含原插件operations处理器→原会话文件SDK→HTTP ready/change→断连后真实FileWatch退出；仅显式ndjson，不自动公开方法或安装Client解码器。SDK轮询及目录/根/版本差异不变。
