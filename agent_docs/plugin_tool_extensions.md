# 插件动态工具与执行钩子 v1

<!-- user:“宿主能力补齐和接口完善与文档更新，自动化兼容脚本，脚本不必能处理所有问题，剩下问题交给 agent 来移植”+(给出真实可调用接口及 DSH 移植边界，不宣称 JS 运行兼容)。 -->

Sunday 桌面进程内 Python 插件通过 `context.tools` 注册动态工具、限制工具集、追加拒绝规则和观察执行。它接入已有主/子代理工具箱、数值等级审批和 kernel 执行链；没有第二套工具执行器。宿主在插件启动前发布该能力。

## 最小插件

```python
from lamtools_core.plugin_system import ToolDecision, ToolPatch
from lamtools_core.tool import ToolSpec, ToolResult

class Runtime:
    def start(self, context):
        self.remove = context.tools.register(
            ToolSpec(
                name="example_echo",
                description="返回输入的文字",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                    "additionalProperties": False,
                },
            ),
            self.echo,
            level=1,
        )

    async def echo(self, invocation):
        return ToolResult(invocation.call_id, invocation.name,
                          content=invocation.arguments["text"])

def create_plugin(context):
    return Runtime()
```

工厂只构造运行对象；贡献在受管 `start/on_load` 中登记。启动及健康检查成功后公开，失败不公开。停用立即隐藏贡献并拒绝新调用，已开始调用排空后才执行资源清理。所有注册返回可重复调用的撤销函数，也随所属启动代自动撤销；旧 `context.tools` 不能在停止后继续注册。

## 接口

| 调用 | 契约 |
| --- | --- |
| `register(spec, handler, *, session_id=None, level=None)` | 注册 `ToolSpec` 与同步或异步 handler，返回撤销函数 |
| `restrict(*, allow=None, deny=(), session_id=None)` | 收窄所有工具的可用集合，包含内置工具；多条规则取交集，deny 优先 |
| `guard(callback, *, session_id=None)` | 执行前追加拒绝规则；返回 `ToolDecision` 或 `None` |
| `on("tools/pre-execute", callback, *, session_id=None)` | 执行前检查；返回 `ToolDecision` 或 `None` |
| `on("tools/post-execute", callback, *, session_id=None)` | 执行后返回 `ToolPatch` 或 `None`；blocked/skipped 不进入此阶段 |
| `on("tools/result", callback, *, session_id=None)` | 观察最终结果，必须返回 `None` |

`session_id=None` 表示所有会话，具体非空会话 ID 表示该会话。名称在宿主范围唯一，即使会话范围不同也不能重名。内置/静态工具保留名及 `mcp__` 前缀不能注册；与旧动态提供方同名时，两个入口均隐藏并拒绝调用。

主助手和子助手沿现有 provider 装配接入。宿主在 run 开始和实际执行时绑定会话，显示与执行使用同一限制规则。工具箱当前列表会刷新；模型调用已经取得的工具快照仍服从现有冻结规则，注册不承诺立即重启正在进行的模型请求。停用后旧快照中的调用也会拒绝。

## 参数与返回值

handler 和 pre/guard 接收不可变 `ToolInvocation`：`call_id`、`name`、`arguments`、`session_id`、`run_id`、`work_root`。参数映射与嵌套集合递归冻结，不提供运行时参数重写。

handler 必须返回同一 `call_id/name` 的 `ToolResult`，状态限于 `ok/failed/blocked/skipped`。不匹配的结果或普通异常变为 `failed`，错误码为 `tool/handler-error`；取消继续传播并释放调用租约，宿主预算耗尽异常继续传给 kernel。

post/result 接收 `ToolOutcome`，包含 `invocation` 和不可变的结果字典 `result`。`ToolPatch(content="...")` 只能改变内容，不能把失败改成成功或修改审批状态。post 异常保留实际结果并在 `metadata.tool_hook_errors` 记录；观察异常写日志，不重试实际工具。kernel 路径在旧 PostToolUse 处理完成后通知 result，一次通知；直接调用工具箱则在该工具箱处理结束后通知。

### 支持的 schema 子集

根必须为 object；支持 `properties`、`required`、布尔 `additionalProperties`、`title/description`。每个属性仅支持 `string/integer/number/boolean/null` 原始类型，以及 `enum/default/title/description`。调用时检查必填项、类型、枚举与额外字段；参数必须是有效 JSON 值，拒绝非字符串键及非有限数字。默认值不自动填充。

暂不接受声明的嵌套 object/array、组合类型、范围/正则约束、引用或非空 `output_schema`；不支持的 schema 显式拒绝，不能静默忽略约束。若允许额外字段，这些值仍可包含有效 JSON 集合，但没有嵌套 schema 校验。注册时复制 spec，修改原对象不会改变已注册契约。

## 审批和执行顺序

`level` 优先于 `spec.metadata["operation_level"]`，均未指定时按 3 处理；仅支持整数 0–3。0 为硬拒绝，1–3 由 Sunday 当前免问线与能力上限决定是否需要用户确认。`permission="unspecified"` 规范为 `ask_user`；`auto_allow/ask_user` 不能代替数值审批。用户显式配置的操作等级优先于插件默认值，硬拒绝、禁用及收窄规则仍不可放宽。

同一个长寿命工具箱内，同名新注册继承更严格的默认权限和等级；放宽需要重建工具箱。每个调用记录注册令牌，旧审批不能进入停用、重启或重新注册后的新 handler。

执行顺序：可用性/注册令牌检查 → pre → 最终 guard → 既有审批与执行 → post → 最终 result。pre 的 allow 不能越过 guard 或既有审批；pre/guard 失败会关闭执行。pre 中新增的 guard 同次生效；guard 集合在检查过程中改变时拒绝本次调用。相同内存调用与未变化参数的 pre 在 kernel/工具箱双入口去重，最终 guard 每次重查；恢复的序列化调用重新检查。

## DSH 对应与剩余差异

| DSH 入口 | Sunday 接法 | 必须适配的差异 |
| --- | --- | --- |
| 动态 tools 注册 | `context.tools.register` | Python handler、扁平 schema、数值等级、同名冲突与所有权 |
| 工具集限制 | `restrict` | 集合交集；只允许收窄 |
| 执行前守卫 | `guard` / pre | 仅 allow/deny；动态 ask 未实现 |
| `tools/pre-execute` | 同名 `on` | 只读参数；不支持参数改写 |
| `tools/post-execute` | 同名 `on` | 仅内容补丁；不是任意结果改写 |
| `tools/result` | 同名 `on` | 最终结果只读观察 |
| `tools/execute` | 尚无对应包装接口 | next/waterfall、重试与接管执行需后续设计 |

没有 Cordis 通用事件总线、JS/TS 原运行环境或外部进程反向调用桥。迁移脚本为上述已验证子集给出 `agent-required` 建议和本页链接，不自动翻译处理函数、参数或事件语义。

验收：`core/tests/test_plugin_tool_extensions.py`。覆盖真实桌面启动、实际主/子工具箱、kernel 边界、审批、会话限制、失败回滚、停用排空、旧令牌、冲突、取消、预算终止及只读结果。
