# 插件权限目录与会话偏好读取

user:“宿主能力补齐和接口完善与文档更新”+(权限读取保持真实来源和只读边界，不把设置当作批准凭证)。

受管桌面 Python 插件通过 `context.permissions` 取得绑定启动代的接口。桌面会话服务将它登记为 `permission_access`；既有 `permission_service` 审批判断器保持原用途。接口没有策略写入、工具执行、信任修改或审批回答能力。

```python
api = context.permissions  # 在受管 start/on_load 中取得
catalog = api.catalog()   # 同步读取当前全局默认值与固定目录
selection = await api.read("existing-session-id")
print(catalog.default_preset, selection.preset)
```

## 目录

`catalog()` 返回不可变 `PermissionCatalog(options, default_preset)`。options 为 `PermissionPresetInfo(name, auto_approve_level)` 元组，沿用现有 PERMISSION_PRESETS 和操作等级表，按以下顺序返回：

| 名称 | 免问等级 | 含义 |
| --- | --- | --- |
| ask | 1 | 免问线为 1 |
| auto | 2 | 免问线为 2 |
| full_access | 3 | 免问线为 3，并按现有解析规则展开目录访问设置 |

免问线始终受到会话基础能力上限、硬阻止、动态工具规则等约束。full_access 不提升 read_only 会话的基础上限。Sunday 的 auto 是等级预设，与 DSH 的 Auto review 集成无对应关系；字符串相似不能直接迁移。

default_preset 每次复用现有全局默认加载器；它使用原有规范化与缺失配置回退行为，不代表某个已有会话的选择。此目录没有展示文案、defaultOptions、自定义预设、sandbox 模式或动态贡献注册。

## 会话读取

`await read(session_id)` 仅接受最多 256 字符的非空字符串，去除首尾空白。它调用桌面会话存储新增的 get_readonly，保留该存储原有可见性判断。不可见与不存在统一报 permissions/not-found，不向插件返回整个会话元数据。

返回不可变 `SessionPermissionView`：

| 字段 | 含义 |
| --- | --- |
| session_id / preset | 会话 ID 与规范化后的预设名 |
| base_tier | 会话基础能力档位 |
| base_available_level | 基础档位对应的能力上限，非动态工具的最终权限 |
| preset_auto_approve_level | 当前预设的免问线 |
| approval_policy | 现有预设解析器展开的 require / auto_approve 值 |
| allow_access_outside_workdir | 现有解析器展开的目录访问设置，非操作系统隔离承诺 |
| preferences_stored | 持久元数据是否已有 runtime_preferences 键，不证明内容完整或合法 |
| basis | 固定为 session-preferences，明确它是偏好读侧 |

字段沿用 `session_runtime_preferences` 和 `resolve_permission_preset`，不另造权限计算。已有偏好不会随全局默认变化而改变；部分或无效偏好仍按既有规范化规则回退。旧会话缺少偏好块时，本次读取按当前全局默认推导并返回 preferences_stored=false，**不将它写回数据库**。在其他普通读取完成旧数据规范化之前，后续读取可能随默认值变化。

新增 get_readonly 不更新权限缓存、不会迁移旧偏好或发布同步事件。原 get 仍保留按需持久化旧偏好和刷新运行缓存的行为。权限查询既不创建会话，也不使用会话事件游标假装提供内容版本；多个调用之间没有一致快照或变更订阅。

## 作用域与错误

查询范围沿用桌面会话存储的可见性，没有新增按请求插件划分的会话授权或工作目录过滤。读侧固定安装时的会话存储对象，检测替换并拒绝旧宿主视图；应用关闭后拒绝新查询。缺少受管启动代抛 ServiceError，未安装宿主接口时抛 LookupError。缺少只读存储能力时抛 permissions/unavailable，不回退到可能写入的 get。

从公开 SDK 导入 `PermissionAccessError`，按 `.code` 判断：permissions/invalid-session、not-found、unavailable、host-changed、closed、read-failed（均使用 permissions/ 前缀）。存储异常不能伪装为默认 ask 或空目录。异步读取占有启动代租约，停用拒绝新调用并等待已接收读取结束；调用者取消仍传播并释放租约。同步目录读取不登记后台任务。

这些结果不是批准凭证、不是实际工具的最终决策。它们不包含运行中的临时授权、插件额外限制、MCP 特定授权或全局精确信任结果。实际执行必须继续走原工具与审批流程，不能因读到 auto/full_access 而跳过检查。

## DSH 移植

依据固定版本的 [permission-presets 官方手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/interaction/permission-presets/README.md)及[源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/interaction/permission-presets/src/index.ts)，catalog/current 可人工近似适配。current 的 Session 对象改为 ID，并从 read 的返回值读取 preset；参数、返回结构、默认值和权限语义均需调整。

[user-approval 手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/interaction/user-approval/README.md)中的 request、setPolicy、回答者组合、一次性授权、取消及 asked/decided 审计对未实现。预设 set/registerAuto/resolve/optionOf、custom、Remote 投影和目录变更事件也不在本子集。不得用只读接口代替这些操作；既有 approval.respond 也不等价于 DSH approval.request。

迁移报告新增 permissionMethods，只为 catalog/current 提供人工映射，所有方法保持 agent-required。验收见 `core/tests/test_plugin_permission_access.py` 及迁移测试。未改前端文件，不代表完整 DSH 权限兼容。
