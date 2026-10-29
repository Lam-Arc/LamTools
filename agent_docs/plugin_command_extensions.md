# 插件动态斜杠命令 v1

<!-- user:“宿主能力补齐和接口完善与文档更新，自动化兼容脚本，脚本不必能处理所有问题，剩下问题交给 agent 来移植”+(命令沿原目录与动作执行入口扩展，明确文本、作用域、取消和 DSH 差异)。 -->

Sunday 桌面进程内 Python 插件通过 `context.commands.register` 注册文本动作命令。它接入已有 `command.catalog`、`command.execute` 和桌面 live 分派；不创建第二个命令执行器，也不自动把命令及结果提交给模型。

## 注册

```python
from lamtools_core.plugin_system import CommandResult

class Runtime:
    def start(self, context):
        self.remove = context.commands.register(
            "example-echo", self.echo,
            title="回显文字", description="直接显示输入内容",
            accepts_args=True,
        )

    async def echo(self, invocation):
        return CommandResult(text=invocation.arguments)

def create_plugin(context):
    return Runtime()
```

完整签名：`register(name, handler, *, title="", description="", accepts_args=True, session_id=None)`，返回可重复调用的撤销函数。名称必须匹配 `[a-z][a-z0-9_-]{0,63}`，登记时不带 `/`；title 为空时使用名称。handler 可以同步或异步。

工厂只创建运行对象，在受管 `start/on_load` 中登记。启动及健康检查通过前不公开；失败、停用和重启撤回该代全部注册。旧门面不能继续登记，旧撤销函数不能删除新代贡献。

## 输入和结果

handler 接收冻结的 `CommandInvocation`：

| 字段 | 含义 |
| --- | --- |
| `name` | 实际选择的命令名 |
| `session_id` | 接收命令的会话 ID |
| `arguments` | 原执行入口处理后的文字参数，首尾空白会被裁剪 |
| `work_root` | 请求指定的工作目录；未提供则沿用宿主默认目录 |

handler 必须返回 `CommandResult(status="ok", text="...")` 或 `CommandResult(status="error", text="错误原因")`。其他返回类型显式拒绝。错误结果和普通异常进入原动作错误通道；成功响应的 `payload.result` 包含 `plugin_name/status/text`。返回文本交给命令调用方，宿主不自动将其放入模型消息。

不接受附件；命令不会获得 DSH Agent 原对象或通用 UI effects。需要会话控制、工具或权限能力时，应调用对应宿主契约，注册命令本身不会获得模型工具的额外执行权限。

## 查询与执行

插件可以使用已有 operation executor：

```python
execute = context.operation_executor()
catalog = await execute("command.catalog", {"thread_id": "session-1"})
result = await execute("command.execute", {
    "thread_id": "session-1",
    "command": "example-echo",
    "arguments": "hello",
})
```

operation executor 在宿主操作目录装配完成后可用，不应在目录尚未建立的早期启动阶段调用。查询和执行接受 `thread_id/threadId/session_id/sessionId`；省略会话的查询只返回全局命令，执行必须指定会话。`command` 和 `arguments` 分开传入，不解析 DSH 的完整 `/command [input]` 原始行。`find` 可由调用方查询目录后按 name 选择，当前没有独立同名方法。

桌面 live 路径保留已有会话版本检查和动作分派规则。直接调用 operation 属于较低层入口，不替代 live 的版本检查。此接口自身不启动助手轮次；handler 显式请求其他宿主能力所产生的行为由 handler 负责。

## 作用域、冲突和清理

`session_id=None` 为全局命令。指定非空 ID 时，该定义只在该会话遮蔽同一插件的同名全局定义；撤销后恢复全局项。没有 Cordis Agent 上下文自动桥接，也不声明代理名称范围。

同一范围内重名、跨插件重名及已保留的内置/静态命令名会在注册时拒绝。运行中新增静态命令与动态命令发生冲突时，两者在该目录中均隐藏并拒绝执行，避免按加载顺序误选。旧 actions 的同名处理器不能抢占受管命令，也不能成为已撤回命令的回退入口。

每次实际分派固定当前注册令牌并取得所属启动代的调用租约；令牌变化或会话可见性变化会拒绝这次分派。停用立即停止新调用，等待已开始的处理器结束后再清理资源。取消继续传播并释放租约；外部系统已经发生的副作用不自动撤销。handler 应配合异步取消，不能把阻塞工作直接放在事件循环中。

目录的 `metadata.owned_command_token` 是本代注册令牌，不是 DSH 稳定 `definitionId`。当前公开执行请求按命令名称重新选择定义，不要求客户端提交旧目录令牌：用户在旧界面点击同名命令时可能选择当前的新定义。内部已选定调用的隔离不能被理解成客户端旧点击的完整隔离。

## 界面和上游差异

现有桌面界面只查询全局目录，尚未传入当前会话 ID，也没有命令注册变化订阅。因此专属命令的发现及覆盖后的标题/参数信息需要调用方显式带 `thread_id` 查询；动态登记不保证已经打开的命令菜单立即刷新。现有界面仍能通过原执行入口运行全局命令。界面补齐列入前端阶段。

上游依据固定为 `f3803c96974ad4a94195fb97e5c637e9c2a3afe3` 的[命令作者说明](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/interaction/commands/README.zh.md)。

| DSH 能力 | Sunday 当前对应及差异 |
| --- | --- |
| `commands.register({name, description, handler})` | `context.commands.register(name, handler, ...)`；Python handler 与 CommandResult |
| `list(agent)` | `command.catalog`，显式会话 ID |
| `find(agent, name)` | 查询目录后按 name 筛选，无独立 find |
| `execute(agent, line, attachments, signal)` | `command.execute` / live 动作入口；command/arguments 分开、裁剪空白、无附件 |
| agent.ctx 范围 | 显式 session_id；同插件范围覆盖 |
| `input.hint/attachments`、UI 文本渲染契约 | 尚未提供相同契约 |
| `definitionId`、每次执行 commandId | 尚未提供稳定定义 ID 和同格式执行 ID |
| `recordInput` 与 `command/run/done` | 沿用 Sunday 现有执行响应，无 DSH 专用日志格式或配对保证 |
| `commands/change` | 未实现通知订阅 |

迁移脚本新增 `commandMethods`。register/list/execute 给出人工映射，find 和其他方法保留待办；全部标记 `agent-required`，不自动翻译 JS 回调，不将这个基础子集计为整个 DSH commands 服务完全兼容。技能的动态注册不在本批范围，静态技能迁移继续使用原方案。

验收：`core/tests/test_plugin_command_extensions.py`。覆盖启动暂存、失败撤回、会话覆盖、冲突、旧定义、处理器错误、不可变调用、停用排空、取消、真实桌面目录/执行、live 分派及旧 actions 防抢占；未使用外部模型或 Computer Use。
