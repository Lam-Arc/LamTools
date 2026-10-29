# 插件宿主契约：服务注册、依赖引用与资源清理 v1

user:“每一个地方 sunday 都有等价或者近似接口”+(先给 DSH 插件移植提供有所有者、有版本、可撤回并接入真实生命周期的 Python 服务契约)。

## 使用范围

本契约用于进程内 Python 插件，接入原有 `PluginSupervisor` / `PluginRuntimeHandle` 启停流程。它给现有共享服务字典补充注册元数据、调用租约与清理栈，不创建新的插件管理器或 Agent 运行时。

在 `start(context)` / `on_load(context)` 中注册服务和资源。同步 `create_plugin(context)` 工厂只构造运行对象；工厂阶段和 `start_lifecycle=False` 的纯构造模式不支持新的受管注册接口，会抛出明确错误。这样加载工厂失败时不会留下无法异步回收的资源。

## 提供服务

```python
from typing import Protocol, runtime_checkable
from lamtools_core.plugin_system import ServiceKey

@runtime_checkable
class Echo(Protocol):
    def echo(self, text: str) -> str: ...

ECHO = ServiceKey[Echo]("example.echo", version=1, protocol=Echo)

class Runtime:
    async def start(self, context):
        self.context = context
        self.unregister = context.register_service(ECHO, self)
        # 准备资源后立即登记清理；函数可同步或异步。
        context.on_dispose(self.close_resources)

    def echo(self, text: str) -> str:
        return text

    async def close_resources(self):
        pass  # 替换为本插件实际拥有的资源清理。

def create_plugin(context):
    return Runtime()
```

`ServiceKey[T]` 包含名字、正整数版本及可选的运行时 protocol。名字允许字母开头的字母、数字、点、下划线、连字符。版本精确匹配，不自动降级。protocol 应是具体 Python 类或带 `@runtime_checkable` 的 Protocol；Python 的结构检查验证成员存在，不证明参数和返回值完全等价，仍需类型检查和行为测试。

| 接口 | 行为 |
| --- | --- |
| `register_service(key, value)` | 注册非 None 服务，返回可重复调用的撤回函数；也接受字符串名字，默认版本 1 |
| `bind_service(key)` | 绑定一个精确版本的依赖，返回固定提供方和请求方启动代际的 `ServiceRef[T]` |
| `reference.call(method, *args, **kwargs)` | 异步调用公开方法；支持同步或异步实现，透传业务返回值和异常；持有双方的调用租约 |
| `reference.get()` | 校验当前引用后返回原 Python 对象；不持有方法执行租约 |
| `on_dispose(cleanup)` | 登记同步或异步清理函数，按逆序执行 |
| `effect(setup)` | 同步 setup 返回清理函数；异步 setup 应改写为 async start + on_dispose |

服务在启动中暂存，仅该插件及其同代上下文视图可用。启动回调和首次健康检查成功后，先重检依赖与所有名字冲突，再无 await 地提交整批服务。同批任一冲突都不会把其他条目发布出去。健康检查失败、启动失败和停用立即撤回该代服务。ready 后仍可新增/撤回服务，所有权保持属于本次启动。

注册不能覆盖宿主已有条目，即使该条目的值暂时为 None。也不能与本插件自动导出的运行对象或 `plugin.service` 条目重名。`set_service` 不能替换受管服务的不同对象；显式 `remove_service` 会撤回该条注册。直接修改 Python 字典属于旧的受信任逃生口，无法提供同等元数据和所有权保证。

## 消费服务

```python
class Consumer:
    def start(self, context):
        self.echo = context.bind_service(ECHO)

    async def run(self):
        return await self.echo.call("echo", "hello")
```

绑定时缺失依赖、版本不匹配或 protocol 不满足立即失败；启动成功前会重检依赖，提供方在消费者异步初始化期间退出，消费者的服务不会发布。

引用固定提供方和请求方的启动代际。停用、撤回、替换或重启后，旧引用不会转向新对象；即使新旧服务恰好使用同一个 Python 对象也会拒绝。上下文的 `for_work_root()` 视图共享当前注册所有者，同代可注册；旧视图不能在新代重新注册。

对同一个提供方，当前插件 scoped service 优先于共享服务。不同宿主实例拥有独立注册元数据。旧的未版本化服务和 scoped 对象可用默认版本 1 绑定，但这仅是兼容约定，不表示旧实现已通过某个 DSH v1 协议认证。

`get()` 返回的是受信任 Python 对象。若调用方长期保留原对象并直接调用，后续调用不能被撤回或排空；应优先使用 `ServiceRef.call()`。原有 `require_service()` / `service()` 继续返回原对象，保留兼容语义。

## 停用、失败与清理

1. 原生命周期先撤回服务和运行对象，阻止新引用调用与新注册。
2. 等待已有 `ServiceRef.call()` 租约结束，再运行插件原有 stop/on_unload。
3. 不论 stop/on_unload 是否抛错，都尝试执行受管清理栈。
4. 按后注册先清理的顺序执行。单条清理失败不跳过其他条目；成功条目不重复，失败条目留待重试。
5. 沿用生命周期完成条件和 stop deadline。调用方取消不会取消已归属清理任务；后续 stop 可以重新等待。同一代尚未清理完成时不能开启下一代。

从正在执行的服务方法中同步等待自己插件停止，会明确拒绝，避免等待自身租约。应让方法返回后由外部管理入口停用。

正常管理器启动失败会通过既有停止流程回滚；健康监测失败也执行同一清理流程并保留原失败诊断。直接调用底层 `start_plugin_backend()` 的嵌入方仍须负责在失败后调用停止流程，与原有生命周期契约一致。未登记的资源不在自动清理范围。

## 发现与错误

`describe_host()` 对已发布的受管服务增加 `owner`、`version`、`epoch` 元数据，不输出服务对象。epoch 来自该运行句柄的启动尝试号，用于区分注册代际，不替代 supervisor 的代码更新 generation。

`ServiceError` 提供 `code` 和 `service` 字段：

| code | 含义 |
| --- | --- |
| `service/scope-unavailable` | 不在受管启动/运行上下文 |
| `service/scope-closed` | 当前代已撤回 |
| `service/cleanup-required` | 上代尚未清理完成 |
| `service/conflict` | 名字冲突或试图覆盖受管服务 |
| `service/unavailable` | 依赖未就绪/已撤回 |
| `service/version` | 请求版本不匹配 |
| `service/stale` | 提供方已更换或撤回 |
| `service/requester-stopped` | 请求方所属代已退出 |
| `service/method` | 指定公开方法不可调用 |
| `service/self-stop` | 正在持有自己服务调用租约时等待自身停止 |

错误的 ServiceKey 和 protocol 传值使用 ValueError / TypeError。业务方法异常与取消原样传播。管理器仍使用既有 `PluginLifecycleError` 记录启动/健康/停止失败。

## 与 DSH 的对应和剩余差异

对应 Cordis 的服务注册、显式依赖引用、effect 清理和 unload 撤回。这是已验收的 Python 基础契约，尚不表示 DSH 的 JS/TS 插件可以直接运行。

- 没有 Cordis 自动依赖树调度、服务缺失后自动重启消费者、完整 realm/isolate 或配置热替换语义。
- 消费者依赖撤回后，已有依赖引用拒绝调用；不会自动宣称该消费者已被重新组合。加载顺序仍由宿主组合决定，缺失就绪依赖会明确失败。
- 尚未接通动态工具注册、Agent/Session facade、事件瀑布、Remote 或 UI slots。后续使用本契约接入各项宿主能力。
- 仍无 process runtime 反向宿主回调；不能把本契约当成跨进程 RPC。

验收：`core/tests/test_plugin_owned_services.py`，22 项；与第一阶段 17 项共 39 项通过。包含真实模块加载和现有 supervisor 的启停/重启，不依赖界面操作。阶段进度见 [DSH 兼容实施说明](dsh_compatibility.md)。
