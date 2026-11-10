# 凭据控制器只读元数据

user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(批量描述真实凭据状态，密值不作为Remote结果)。

固定上游deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的[凭据控制器](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/settings-controller/src/credentials.ts)及[中文手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/settings-controller/README.zh.md)已核对：上游describe最多64引用，输出严格投影configured/source/writable，控制器无返回密值的方法。

`context.credential_controller.describe(refs)`同步接收至多64个POSIX标识符（单项最多128字符）；整个参数先校验，错误不会读取存储。原`context.credentials.describe_many(refs)`从当前插件owner的原PluginSecretStore一次读取键名快照并构造CredentialInfo；控制器逐字段投影configured/source/writable，不调用get，也不返回值。未配置source为None，已配置为plugin-store；上游缺省source可能省略，字段和引用语法须人工适配。空列表返回空字典，重复引用合并为一个键。

只访问当前插件私有命名空间，不查询其他插件或环境变量；原存储缺失明确报错。启动代和同一存储在快照前后复核，替换或撤回拒绝结果。存储调用同步，开始后不能异步抢占，也不承诺与外部修改的跨调用原子事务。插件原处理器可显式映射token POST与http.remote；当前Remote参数仍为扁平原始类型，批量参数必须由处理器自行明确适配，不自动注册路由。原context.credentials.set/unset仍是本地SDK能力；控制器现提供当前插件set/unset单向写入，不提供resolve，详见下节。

11项新增验收使用临时原PluginSecretStore/加密测试凭据，覆盖owner隔离、无值与不调用get、全批非法先拒绝、一次键快照、存储替换/撤回、真实HTTP和迁移交接。上游全局provider、Remote set/unset、Peer策略和精确codec仍未完成；没有读取或修改用户真实密钥。


## 当前插件单向写入

`context.credential_controller.set(ref, value)`及`unset(ref)`同步调用原PluginCredentials/PluginSecretStore的当前插件私有加密存储，成功返回None，不返回密值。原标识符规则及非空白/UTF-8至多64KiB值限制不变，比上游非空约束更严格。调用开始前检查原启动代和存储；原写入成功后再检查绑定，若绑定变化返回`credentials/host-changed`且`may_have_changed=True`，调用方须重新查询状态，不能假定回滚。同步写入开始后不能异步抢占，未提供跨调用事务。

插件自身可按原token POST/http.remote明确声明单向写入处理器，迁移脚本只给人工候选，不自动公开。10项新增验收只使用临时PluginSecretStore/临时密值，覆盖写入/清除和跨owner隔离、四种非法参数先拒绝、set/unset提交后存储替换标记、已撤回启动代、真实HTTP错误令牌与不回传密值、迁移交接。没有修改用户真实密钥。仍无DSH全局provider/Peer角色授权或自动注册策略。

当前控制器在调用原set/unset前复用同一原标识符和值校验；校验失败维持原参数错误且不进入存储。通过校验后若原存储抛错，不能假定没有提交：绑定仍有效时返回脱敏`credentials/write-uncertain`，绑定改变时返回`credentials/host-changed`，均标记`may_have_changed=True`。显式HTTP不保证透传该标志，调用方须先查询状态。7项新增验收仅用临时加密存储与临时密值，模拟真实写入/删除后报错、绑定替换、原参数拒绝及真实HTTP不回显密值；没有访问用户真实密钥。
