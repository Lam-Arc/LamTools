# 插件持久 JSON 存储 v1

<!-- user:“宿主能力补齐和接口完善与文档更新，自动化兼容脚本，脚本不必能处理所有问题，剩下问题交给 agent 来移植”+(公开稳定数据目录上的 JSON KV 与错误语义，不把基础介质冒充完整 DSH 领域)。 -->

Sunday 桌面进程内 Python 插件可通过 `context.storage` 保存自己拥有的非会话 JSON 状态。它使用现有 `PluginHost.data_path` 对应的稳定目录：`<data_dir>/plugin-data/<plugin>/host-kv.sqlite3`，与插件代码目录分开。更新代码保留数据；卸载时是否保留，继续遵循原插件数据策略。

这是一般应用状态，不是加密凭据库或配置面板的配置文件。凭据继续使用独立 secrets 服务，插件配置继续使用原 config_store。接口不注册模型工具，不注入提示词，也不写入会话事件。

## 使用

```python
class Runtime:
    def start(self, context):
        self.state = context.storage.open("state", version=1)

    def increment(self):
        previous = self.state.get("count")
        return self.state.put(
            "count", (previous.value or 0) + 1,
            expected_revision=previous.revision,
        )

def create_plugin(context):
    return Runtime()
```

在受管 `start/on_load` 中获取门面。所有句柄绑定该插件的启动代和 owner，不接受另一个插件名称。停用、重启和启动失败后旧门面/句柄拒绝使用；新代重新打开相同单元即可读取已持久数据。`for_work_root` 不会改变插件数据身份；需要工作区或会话维度时，插件自己设计单元或记录键。

**持久写入是应用状态，不是启动注册事务的一部分。** 在 start 中成功提交后，即使后续启动失败，已写入状态仍保留；宿主只撤回调用能力，不自动回滚这些业务数据。

## 接口

| 方法 | 结果 |
| --- | --- |
| `context.storage.open(name, *, version=1)` | 打开或初始化命名 JSON 单元，返回 StorageUnit |
| `unit.get(key)` | `StoredValue(found, value, revision)` |
| `unit.put(key, value, *, expected_revision=None)` | 原子写入，返回提交后的 StoredValue |
| `unit.delete(key, *, expected_revision=None)` | 原子删除，返回 found=false 的 StoredValue |
| `unit.keys(*, prefix="", after=None, limit=100)` | `StorageKeyPage(entries, next_after)`；每项仅含 key/revision |
| `unit.close()` | 关闭此句柄，可重复调用；不删除数据 |

单元名匹配 `[a-z][a-z0-9_-]{0,63}`。版本是正整数，范围 1 到 2³¹−1；第一次打开记录版本，之后必须精确相同。没有自动升降级、compatibleVersions 或迁移回调；不要仅修改 version 来假定已迁移数据。

相同单元允许多个句柄，共享数据库中的当前状态，不建立独占内存领域；这与 DSH 的 already-open 规则不同。

键是最多 512 字节的非空 UTF-8 字符串，不含 NUL；它们作为不透明数据库键处理，不构成文件路径。`../outside` 等键不会访问目录外的文件。prefix 可以为空，按字面且区分大小写匹配，不解释 `%/_` 通配符。页上限 1–1000，默认 100；next_after 不为空时继续传给 after。分页不是跨页固定快照，并发修改可能影响后续页。

值仅支持标准 JSON：字符串、有限数字、布尔、null、数组与字符串键对象；拒绝 NaN/Infinity、元组、自定义对象、循环结构及非字符串对象键。编码后每个值最多 1 MiB。读写结果中的可变 JSON 都是独立副本，修改它们不会直接修改已存数据。

## 缺失、版本和并发

未曾存在的键返回 `found=false/value=None/revision=0`；存储 JSON null 则 `found=true/value=None`，两者不混淆。

每次成功 put 增加该键的 revision，即使内容相同。删除已存在键也增加 revision，并保留版本墓碑；再次创建继续递增，避免删除后重建使旧版本误通过检查。删除已缺失的键不再递增。墓碑不参与 keys 列表，本版没有自动清理墓碑或总容量配额。

`expected_revision=None` 表示不做条件检查，后提交的值覆盖之前的值；传入非负 64 位 revision 时，检查和写入在同一 SQLite 写事务中完成，不匹配抛出 `storage/conflict`，不覆盖当前值。先读再改的调用方应保留 expected_revision，并在冲突时重新读取后决定是否重试。

SQLite 是唯一持久状态权威，没有另一份内存目录。每次操作独立连接并在结束后关闭，写事务使用 FULL 同步提交；不同连接访问相同文件也通过 SQLite 锁协调。锁等待上限为 2 秒，失败返回 storage/busy，调用方决定重试，不会自动重复业务写入。

接口面向小型本地状态，**同步调用**；DSH 的 await 写入必须人工适配。只能沿宿主同步调用路径使用，不应把门面交给其他线程执行。操作中没有 async 让出点，不承诺取消已经开始的短提交，也不支持任意异步更新回调。本版不新增异步调用租约或后台存储任务。

## 失败与恢复

对外错误使用公开 SDK 的 `StorageError.code`：

| code | 含义与处理 |
| --- | --- |
| `storage/conflict` | revision 不匹配；重新读取并决定是否重试 |
| `storage/version-mismatch` | 单元版本不匹配；保留数据，先设计迁移 |
| `storage/unknown-state` | 提交确认失败，结果可能已持久；停止使用旧句柄，close 后重新 open，读取并核对，不能直接重复副作用 |
| `storage/busy` | 锁等待失败；本次没有取得写事务 |
| `storage/io` | 文件或数据库访问失败；不会当成空数据覆盖 |
| `storage/missing-medium/missing-unit` | 已打开的数据文件或单元被外部移除；显式重新打开处理 |
| `storage/format-version/invalid-record` | 存储格式或已存 JSON 不受支持；不会自动清空或重建 |
| `storage/closed` | 已关闭句柄 |
| `storage/invalid-unit/invalid-version/invalid-key/invalid-value/invalid-revision/invalid-limit` | 输入不符合当前契约 |
| `storage/path/host-changed` | 数据路径被重定向或现有宿主被要求切换根目录 |

提交确认异常会隔离当前句柄，后续读写均拒绝，直到调用方重新打开并核对实际数据。原子提交前的错误会回滚本次事务；损坏文件保持原样，不以空值冒充恢复成功。旧启动代另外沿用受管 scope-closed 错误。

插件是在可信宿主进程内运行的；上述 owner 限定是接口隔离，不是对恶意 Python 代码的操作系统隔离。

## DSH 差异与迁移

上游固定为 `f3803c96974ad4a94195fb97e5c637e9c2a3afe3` 的[存储枢纽说明](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/storage/storage/README.zh.md)和[领域说明](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/storage/storage-domain/README.zh.md)。

| DSH 能力 | 当前 Sunday 对应 |
| --- | --- |
| 持久非会话应用状态 | 插件所有的 JSON KV，可作为人工重构目标 |
| `storage.register/mount` | 未实现后端/数据形式注册 |
| `storageDomain.open(spec)` | 不能直接替换；需人工把领域结构映射为单元和键 |
| defineDomain/schema、tables/global | 未实现类型化领域、表或全局槽位语义 |
| 同步内存读、异步串行写 | Sunday 当前均为同步数据库操作，没有相同内存领域权威 |
| 后端路由、compatibleVersions | 未实现；当前本地 SQLite 和正整数精确版本 |
| update/deleteMany、跨单元事务 | 未实现；当前 get/put/delete 和条件 revision |
| domain/changed | 未实现事件通知；提交不自动产生会话事件 |

迁移报告新增 storageMethods。对于 storageDomain.open，只给出 `candidateContract=context.storage.open` 和人工改造差异，不给出可盲替换的 suggestedContract；其余后端/挂载方法保留待办。脚本不会去除 await、伪造 schema 校验或生成空的存储后端。

验收：`core/tests/test_plugin_storage_access.py`。覆盖插件/单元隔离、真实目录布局、独立宿主读取、缺失与 null、独立 JSON 副本、条件写与删除重建、字面分页、长度/格式限制、损坏保留、锁等待、提交确认丢失、启动失败后的持久状态，以及替换插件代码后在新解释器中重启恢复数据。
