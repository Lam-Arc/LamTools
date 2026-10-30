# 插件工作目录与只读文件访问

当前扩展：条件写入/编辑、observe 与回执边界见 [第二阶段运行能力](plugin_phase2_runtime.md#文件条件修改)。本文原只读接口仍按以下规则工作。

user:“宿主能力补齐和接口完善与文档更新”+(公开可验收的文件读取子集，迁移必须保留与 DSH 的差异)。

受管桌面 Python 插件在 start/on_load 中取得 `fs = context.filesystem`。每次取得时固定当前 `context.work_root` 与启动代；旧视图不会随项目切换移动，停用、启动失败清理或重新启动后旧视图失效。它不是会话工作目录服务，不能据此推断另一会话的目录，也不更改进程工作目录。

```python
fs = context.filesystem
root = fs.root  # pathlib.Path；只返回固定目录，不验证它仍存在
info = fs.stat("README.md")
text = fs.read_text("README.md", max_bytes=64_000)
raw = fs.read_bytes("image.png", max_bytes=1_048_576)
window = fs.read_byte_range("large.bin", offset=8_000_000, length=4096)
link_info = fs.lstat("path-to-inspect")  # 可查看最终链接本身，不跟随
for chunk in fs.stream_text("large.txt", max_bytes=8_000_000, chunk_bytes=8192):
    consume(chunk)  # 必须正常耗尽才能确认整份文本有效
listing = fs.list_dir(".", limit=100)
for entry in listing.entries:
    print(entry.name, entry.kind)
if listing.truncated:
    print("目录尚未完整列出；缩小范围后重试")
```

所有方法同步调用。`stat(path=".")` 返回不可变 `FileInfo(name, kind, size, modified_ns)`；kind 为 file/directory/link/other，size 和纳秒修改时间来自操作系统，不是内容版本或一致性凭证。不存在抛 `FilesystemError`，与 DSH stat 返回 undefined 不同。

读取仅接受普通文件，必须显式提供整数 `max_bytes`，范围 1–1,048,576，bool 不算整数。最多读取上限加一字节用于判断；超限抛错，不返回截断成功。文本采用严格 UTF-8，拒绝 NUL，保留 BOM 和原始换行，不做文档提取或图片转换。空文件返回空值。

`read_byte_range(path, *, offset, length)` 读取原始字节窗口 `[offset, offset + length)`：不加载整个文件或前缀。offset/length 必须为非负整数（bool 不算），length 最多 1 MiB，offset 与区间终点不超过 2**63-1。允许 length=0，仍检查目标存在、目录边界与普通文件类型；到达或超过已观察到的 EOF 返回空字节，窗口跨过 EOF 返回剩余字节。二进制、NUL 和非 UTF-8 均可读取，不做文本解码或字符边界修正。并发变化不保证快照。

`lstat(path=".")` 返回同一不可变 FileInfo，但不跟随最后一级链接。它可报告符号链接、Windows junction 或断开链接本身（kind=link），不读取目标或返回链接目标路径。根目录与中间目录仍拒绝链接，不能借此访问链接下的子项；普通 stat/read/list 继续拒绝最终链接。缺失仍抛 fs/not-found，不返回空值。路径检查与实际查询不是原子操作，原有竞争条件限制仍适用。

`stream_text(path, *, max_bytes, chunk_bytes=8192)` 返回同步 `Iterator[str]`。总量 max_bytes 必须为 1–64 MiB 的整数，chunk_bytes 为 1–65,536 的整数，bool 不算整数；创建迭代器时即检查参数、目标和初始大小，超限在输出前报错。只支持普通 UTF-8 文本，增量解码正确处理跨块字符，保留 BOM/原始换行，拒绝 NUL；不产生空字符串块，空文件直接正常结束。

每次继续读取均检查启动代和路径边界，并重新打开同一路径、定位、按块读取，在 yield 前关闭句柄。提前停止甚至不 close 迭代器也不保留文件句柄；迭代器仅保留偏移、元数据和少量解码状态。反复打开/检查有额外开销，这是本同步子集的资源边界，不提供长期打开的流或异步调度。

通过设备/文件标识、大小和修改时间检测普通替换/修改，读前与读后检查打开文件，并在正常耗尽前再次检查路径；检测到变化抛 fs/changed。Windows 路径查询与句柄查询的 ctime 可能语义不同，不用它作跨接口比较。文件删除、链接替换等边界错误保留既有错误码。这仍不是原子快照：保留身份/大小/修改时间的恶意修改等可能无法检测。

流式读取可能先返回合法前缀，再因尾部无效 UTF-8、NUL、文件变化或启动代撤回而失败。**只有迭代器正常耗尽才表示已验证整份文本**；异常或提前停止时不能把前缀当作完整成功，调用方应丢弃部分结果或明确标记未完成。不可通过自动重试拼接不同读取批次。没有 I/O 截止时间或异步取消；每个 next 都是同步操作。

`list_dir(path=".", limit=100)` 的 limit 为整数 1–1000。返回不可变 `DirectoryListing(entries, truncated)`，只列直接子项；最多检查 limit 加一个目录项，不读取子项内容。操作系统原始顺序，没有稳定排序、分页、递归或扫描游标。truncated=true 必须当作不完整结果。单项读取失败使整次调用失败；目录变化可能影响结果。

相对路径以固定目录为基准，也允许目录内绝对路径。拒绝父目录跳转、目录外路径、NUL、NTFS 数据流，以及检查时发现的符号链接和 Windows 重解析点（含 junction）；lstat 只允许查询最后一级链接本身，列表也只报告链接元数据，不跟随。复用现有工作目录解析规则并显式启用范围检查，未改变模型文件工具的权限行为。

这是可信原生插件的便捷接口，不是操作系统隔离边界。路径检查与打开并非原子操作，不能抵御恶意并发替换目录/链接，也不隔离插件自身的 Python 文件访问。无权限申请、后台执行、取消或 I/O 截止时间；数量和字节上限不保证网络磁盘调用时长。跨调用不保证快照，文件读入期间被改写也可能返回混合内容。

从公开 SDK 导入 `FilesystemError`，按 `.code` 分支：`fs/invalid-path`、`fs/link-not-supported`、`fs/invalid-limit`、`fs/invalid-range`、`fs/changed`、`fs/not-found`、`fs/not-file`、`fs/not-directory`、`fs/permission-denied`、`fs/too-large`、`fs/not-text`、`fs/io-error`。启动代撤回仍抛现有 `ServiceError`。错误消息不携带底层系统异常；不要按消息文本判断。

## DSH 移植边界

以 [官方 fs 定义](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/fs/fs/src/index.ts) 和 [workingDirectory 定义](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/session/working-directory/src/index.ts) 为基准。

DSH stat/readBytes/readText/readByteRange/lstat/listDir/streamText 可人工适配到上述方法，但必须改写 FsTarget 参数、异步调用、限额、错误和列表完成性判断。readByteRange 的 range 对象改成 offset/length 关键字；lstat 的缺失结果与链接穿透规则不同；streamText 需改为有限同步迭代，并处理前缀后错误及完整耗尽。未实现稳定目标标识、processPath/fileUrl/contains、远程后端映射、写入/编辑、版本保护、watch、fs/* 策略事件和取消协议。

workingDirectory.get 只能参考固定 root，不等价于按 session 读取当前目录。set/ensure 的会话持久化、恢复原项目、模型上下文通知和既有进程目录边界仍待独立实现。迁移扫描在 `filesystemMethods` 中列出候选，所有方法保留 agent-required，不生成运行桥接。

验收：`core/tests/test_plugin_filesystem_access.py`、`core/tests/test_plugin_filesystem_ranges.py` 与 `core/tests/test_plugin_filesystem_stream.py`；迁移提示：`core/tests/test_dsh_compatibility.py`。机器清单 filesystem v3 在 v2 范围读取/lstat 基础上增加有限文本流，不改旧方法。仅声明 Sunday 子集，不代表通过 DSH 运行兼容验收。
