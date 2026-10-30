# 插件凭据引用 v1

<!-- user:“宿主能力补齐和接口完善与文档更新，自动化兼容脚本，脚本不必能处理所有问题，剩下问题交给 agent 来移植”+(凭据引用与元数据查询分离，保持 owner/代际及原加密存储，不伪造 DSH 授权记录兼容)。 -->

Sunday 桌面进程内 Python 插件通过 `context.credentials` 访问自己拥有的字符串凭据。新门面复用现有 `PluginSecretStore` 和 `<data_dir>/plugin-secrets/secrets.json`；不会将凭据改存到一般 JSON KV 或配置文件，也不建立第二套凭据数据库。

## 使用

```python
class Runtime:
    def start(self, context):
        self.credentials = context.credentials

    def status(self):
        return self.credentials.describe("API_KEY").to_dict()

    def read_when_needed(self):
        hit = self.credentials.resolve("API_KEY")
        return hit.value if hit is not None else None

def create_plugin(context):
    return Runtime()
```

在受管 start/on_load 中获取门面，绑定当前 owner 和启动代。调用方不能提供另一个插件名称。插件停止、重启或启动失败后旧门面拒绝操作；重新启动需取得新门面。已成功保存的值是持久应用状态，不会因后续启动失败而自动回滚。

已经返回给调用方的明文不能追溯撤回；撤回检查限制的是门面之后的读取与修改。

## 方法与返回值

| 方法 | 契约 |
| --- | --- |
| `resolve(name)` | 当前值不存在返回 None；存在则返回 `ResolvedCredential(value, source="plugin-store")` |
| `describe(name)` | `CredentialInfo(configured, source, writable)`；不返回值，也不调用解密 |
| `set(name, value)` | 保存非空白字符串；空值拒绝，不表示删除 |
| `unset(name)` | 删除本插件的引用；不存在时无操作 |

name 使用 `[A-Za-z_][A-Za-z0-9_]{0,127}`，是普通字符串，不是 DSH branded CredentialRef。value 必须为有效 UTF-8 字符串，最多 64 KiB；除拒绝全空白值外，保存原始文本，不裁剪有效值两侧的空白。

CredentialInfo 不可变，其 `to_dict()` 只含 configured/source/writable。source 为 plugin-store 或 None；writable 表示该活动接口支持写入，不保证文件系统权限或磁盘状态。configured 只说明存储中存在条目，不证明密文可解、密钥有效或外部服务可访问。坏密文可以 describe 为已配置，但 resolve 必须明确报错。

ResolvedCredential 不可变，默认 repr 隐藏 value，没有通用 to_dict。**resolve 就是有意读取明文值**；调用方仍须避免把它、`.value` 或自行序列化的结果放入日志、配置或界面。repr 隐藏不是通用的序列化脱敏机制。

引用在当前插件命名空间内生效，跨项目共享同一宿主数据目录里的 owner 数据。没有全局环境变量回退：即使进程环境中存在同名变量，未在该插件存储中保存时仍返回 None。unset 后也不会隐式退回环境值。

## 持久性、轮换和失败

保留原 version=1 JSON 密文格式；Windows 新写入继续由当前登录用户的 DPAPI 保护。旧 b64 编码保留可读兼容性，它只混淆、不加密；非 Windows 原实现的回退规则不变，本批不执行密文格式迁移。

磁盘是唯一状态权威，每次 get/keys/resolve/describe 和修改都重新读取。不同实例不再持有可覆盖新状态的旧内存副本；值轮换在下一次读取时可见。消费方应按操作重新 resolve；本接口不自动改写 LLM 适配器的认证来源或任何已经构建的请求。

合作进程通过同一锁文件串行进行读—改—替换，实例和线程也共享进程内锁。文件锁尝试约 2 秒后失败，返回 credentials/busy，不自动重试业务写入。写入先保存并 flush/fsync 临时密文文件，再原子替换；替换前失败保持原文件，后续读取仍读取磁盘事实，没有失败写入污染内存缓存的问题。外部编辑器若不遵守锁协议，不获得相同并发保证。

损坏 JSON、不支持的版本和格式错误的命名空间/条目均明确拒绝，不当成空库，也不自动覆盖修复。存储对象构造本身不读取文件，故凭据损坏不会单凭服务创建使整个宿主启动失败；实际访问的插件会得到明确错误。部分写入结果不确定时，应重新读取核对，不凭错误文字假定值一定没有改变。

接口同步处理本地文件和 DPAPI，不接受异步修改回调，也不提供 OAuth/远程密钥服务。取消不会中断已经开始的短文件事务。本版不新增异步调用租约或远程请求。

## 错误

新 SDK 的 CredentialError.code 包括：

| code | 含义 |
| --- | --- |
| `credentials/invalid-ref` | 引用名称不符合当前语法 |
| `credentials/invalid-value` | 值为空白、类型或 UTF-8 不合法，或超过上限 |
| `credentials/busy` | 未取得文件锁；本次未修改文件 |
| `credentials/corrupt` | 文档、命名空间或密文条目格式损坏 |
| `credentials/version` | 不支持的文档版本 |
| `credentials/protect` | 加密保护失败，不降级为明文保存 |
| `credentials/decrypt` | 解密失败 |
| `credentials/io` | 文件、锁或保存失败 |

对外错误文字和默认异常堆栈不转发底层异常载荷或凭据值；已停止的门面另沿用 scope-closed。没有宿主凭据能力时获取门面直接报缺失，不能静默改为一般存储。

## 旧接口与 DSH 差异

旧 `context.service("secrets")` 保留同一文件与 owner 数据，原空字符串 set=删除行为不变。它仍具有原来的生命周期行为，不自动获得新门面的撤回检查；新移植优先使用 context.credentials。低层 SecretStoreError 保留为原异常类型，新增 code。旧数据不需要导出明文或重新保存即可读取。

上游固定为 `f3803c96974ad4a94195fb97e5c637e9c2a3afe3` 的[凭据作者手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/credentials/credentials/README.zh.md)。

| DSH 能力 | Sunday 当前对应与差异 |
| --- | --- |
| resolve/describe/set/unset | 同名新门面，同步 Python 方法、普通字符串名、当前插件范围 |
| 全局存储引用优先于环境值 | 未实现全局引用和环境回退；不能直接把 apiKeyEnv 当成当前插件存储引用 |
| credentialRef/credentialKey 品牌与 owner/id 键 | 未提供相同品牌或跨插件键语法 |
| readRecord/describeRecord/listRecords | 未提供凭据或授权记录协议与元数据枚举 |
| modifyRecord/deleteRecord | 未提供异步原子变换或授权 grant 生命周期；不能用字符串 set 冒充 |
| reference-updated/record-updated | 未实现事件通知；界面需显式重新查询 |
| keyring/KMS/远程提供方 | 未实现；继续使用现有本地存储 |

迁移报告新增 credentialMethods，为四个引用方法给出 agent-required 建议；记录和事件保留缺口。脚本不导出真实凭据，不把对象编码成字符串就宣称完成授权记录移植。

验收：`core/tests/test_plugin_credentials.py`。覆盖 Windows 保护格式、值与元数据分离、owner 隔离、无环境回退、启动代撤回、失败后持久状态、轮换、坏文件保留、保存失败、坏密文、旧接口兼容、真实桌面启动，以及两个独立进程并发写入和锁占用失败。
