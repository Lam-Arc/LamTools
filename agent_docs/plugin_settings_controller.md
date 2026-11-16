# 设置控制器脱敏读取子集

user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(原插件配置通过明确HTTP处理器时必须保留原脱敏和启动代约束)。

固定上游deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3的[设置控制器源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/settings-controller/src/index.ts)和[中文手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/settings-controller/README.zh.md)已核对。上游describe返回全局命名空间和脱敏schema/层次，其他方法提供写入及本机文档打开。

当前仅将既有`context.settings.public()`作为人工迁移候选：它返回当前插件配置的脱敏values、revision、valid及仅含位置/规则的problems，不返回原始schema或其他插件命名空间。插件须在自身原operations处理器明确调用，再声明token POST/http.remote；迁移脚本不自动生成映射。原配置读取为同步操作，开始后不能异步抢占；插件启动代撤回后不能再读取。

新增2项验收经真实配置持久化、原插件处理器、FastAPI和HTTP验证writeOnly值脱敏、普通值保留、错误令牌和启动代撤回拒绝，以及迁移交接；测试值为临时数据。没有实现上游全局provider、schema/layer投影、跨命名空间写入/打开文档、Peer资源策略或生成codec，不能据此标记完整settingsController。


## 当前插件CAS替换与脱敏返回

`context.settings_controller.describe()`复用原public投影；`replace(values, expected_revision=...)`先调用原PluginSettingsAPI的schema校验及CAS提交，丢弃含明文配置的原ConfigSaveResult，重新读取public脱敏投影。该方法只作用于当前插件，不提供DSH全局namespace或层次合并；HTTP处理器须自行明确扁平参数到配置对象的适配，不能把原始保存对象直接返回。

提交后重新核对原manifest、数据目录和启动代；变化报settings/host-changed，脱敏投影失败报settings/post-commit-unavailable，读取到的投影修订与本次提交不同时报settings/post-commit-changed；这些错误均带may_have_changed=True，且不泄露底层异常/密值。修订包含配置及schema字节，可检测提交和后续投影之间的并发改动；并非跨文件锁的原子投影。同步读写开始后无法异步抢占，成功保存不代表已应用或重载。

7项新增验收覆盖原schema/CAS写入和过期修订拒绝、无效值/撤回不写、真实HTTP密值不回传、提交后manifest替换和投影失败、并发后续配置拒绝发布及迁移交接。测试均使用临时配置；上游全局命名空间、update/mutate、文档打开、Peer和codec仍待移植。

原校验和CAS冲突等明确发生在写入前的错误保留原分类；原写入调用的其他错误可能发生在替换已提交之后，统一脱敏为`settings/write-uncertain`并附`may_have_changed=True`，绑定已变化则报`settings/host-changed`。该标志表示无法断定是否变更，也可能覆盖提交前的其他I/O失败；它是Python异常属性，普通HTTP不保证透传。7项新增验收使用临时配置覆盖实际提交后异常、绑定变化、预检拒绝和真实HTTP脱敏。

数组`contains`和`unevaluatedItems`中的保密标记也参与公开投影；为避免暴露值，将这些分支保守应用于每个元素，可能额外隐藏未命中分支的值。2项新增验收使用真实临时配置保存及控制器读取，确认密值不进入公开结果而原值保留。

## 当前插件CAS补丁

`context.settings_controller.update(patch, expected_revision=...)`先读取原完整配置，在宿主内部递归合并对象、整体替换数组和标量，再通过原schema校验和CAS保存并只返回脱敏投影；未涉及的保密字段保留，修订变化时拒绝覆盖。补丁必须为有限JSON对象，原配置与合并写入不是单独新建的权威，写入异常与提交后复核沿用replace的不确定状态。同步读写无法异步抢占。

固定上游[设置服务源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/settings/settings/src/index.ts)与[控制器手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/settings-controller/README.zh.md)核对其递归对象合并与数组替换；本接口只覆盖当前插件配置，必须携带原修订，不提供DSH无条件写、全局namespace/layer或Peer。9项新增验收使用临时配置覆盖嵌套合并、数组替换、保密字段保留、并发冲突、无效JSON和schema、真实Remote/错误令牌与迁移交接。前文update待办以本节为准，完整DSH update仍未完成。

## 当前插件路径编辑

`context.settings_controller.mutate(ops, expected_revision=...)`在原配置副本按顺序应用1–64条set/unset，路径为1–32个非空字符串；已有对象键可设/删，已有数组下标可设/删，末尾可追加。全部编辑和schema校验成功后才通过原CAS一次提交并返回脱敏投影，未涉及的密值保留。不存在的父路径、无效数组下标或根编辑拒绝；对象缺失的末项unset无操作。

固定上游[源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/settings/settings/src/index.ts)会依据schema默认值构造路径、unset时可能恢复继承层；Sunday本接口不提供这些行为，也不支持全局namespace、Peer或无条件写，需人工移植。13项新增验收覆盖有序操作、数组、保密字段、非法请求、并发CAS、真实Remote及迁移；同步调用不能异步抢占。前文mutate待办以本节为准，完整DSH mutate仍未完成。

## 当前插件设置结构提示

`context.settings_controller.schema_outline()`读取同一原配置快照中的schema和修订，只投影有限类型、属性结构、必填名称、数组items、直接秘密标记及存在引用的提示；上限1024节点、深度16，超限明确拒绝。它不返回设置值、默认值、示例、枚举或说明，也不解析引用、组合分支和完整校验规则；`secret_hint`只代表该节点直接声明秘密，不能据此判断其他节点无秘密，结果标记`partial=true`，不能当作校验schema。同步读取无法异步抢占；调用前后检查原启动代、manifest和数据目录。

5项新增验收覆盖真实临时schema、秘密数据不回传、引用/嵌套/数组、超限、撤回、认证HTTP和迁移提示。上游describe提供多namespace、完整脱敏schema及分层值；此功能仅是当前插件结构提示，非其完整协议或Peer策略。

## 当前插件恢复默认设置

`context.settings_controller.reset(expected_revision=...)`按原`context.settings.reset`默认值规则计算完整替换配置，再经原schema验证、修订CAS及控制器脱敏返回；会整体替换当前插件配置，包括未在默认值中声明的字段。过期修订、schema要求未被默认值满足或提交前撤回时不写入；提交后异常按原控制器的可能已变更规则报告，不返回原始密值。同步调用不能异步抢占。

6项新增验收使用临时配置覆盖原默认值和秘密脱敏、过期修订、无效默认值、撤回、提交后异常、认证HTTP及迁移。上游mutate的unset是单路径编辑并可恢复继承层；此接口恢复整个插件的原默认配置，不是该操作的等价映射，不提供全局namespace或Peer。
