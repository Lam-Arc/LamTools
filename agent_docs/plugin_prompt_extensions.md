# 插件提示词扩展 v1

<!-- user:“宿主能力补齐和接口完善与文档更新，自动化兼容脚本，脚本不必能处理所有问题，剩下问题交给 agent 来移植”+(公开能实际调用的提示词契约，记录上游差异和移植待办)。 -->

Sunday 桌面进程内 Python 插件通过 `context.prompts` 贡献提示词段、变量和同步组装钩子。该门面复用 `system_prompt_waterfall`，在插件启动前可用，主助手和子助手使用同一条组装链。无需另建模型请求或插件生命周期。

## 最小插件

```python
class Runtime:
    def start(self, context):
        context.prompts.variable("response_language", lambda ctx: "Chinese")
        self.remove = context.prompts.section(
            "language",
            "Respond in {{response_language}}.",
            order=100,
        )

def create_plugin(context):
    return Runtime()
```

工厂只构造对象，贡献在受管 `start/on_load` 中登记。启动和健康检查成功前不可见；启动失败、停用或更新会撤回。所有方法返回可重复调用的撤销函数，并自动登记清理；旧门面不能在停止或重启后登记新贡献，旧撤销函数不能删除新一代的贡献。

提示词组装及 provider 均同步执行，不能等待异步操作，也不支持跨线程修改。已开始的同步组装不会让出执行权；宿主不为它另设异步调用租约。

## 方法

| 方法 | 参数与结果 |
| --- | --- |
| `section(name, text, *, order=100, session_id=None, agent_id=None, interpolate=True)` | `text` 为字符串或同步 `provider(PromptContext) -> str \| None`；返回撤销函数 |
| `variable(name, provider, *, session_id=None, agent_id=None)` | 同步 `provider(PromptContext) -> str \| None`；返回撤销函数 |
| `on_assemble(callback, *, order=100, session_id=None, agent_id=None)` | 同步 `callback(PromptContext, PromptAssembly) -> PromptAssembly \| None`；可原地修改本次组装副本；返回撤销函数 |

`None` 文本和空白段不输出。变量名使用 `[a-z][a-z0-9_]*`，段名为最长 128 字符的 ASCII 名称，允许字母、数字、下划线、点、冒号和连字符，首字符为字母或下划线。`order` 接受有限整数或小数，不接受布尔值和非有限数。

`PromptContext` 包含 `session_id`、`agent_id`、`agent_name`、`work_root`、`active_mode`、`actor_kind` 和 `metadata`。每次回调取得独立副本，修改其嵌套 metadata 不会修改运行状态或下一个回调的输入。`agent_id` 精确匹配组装上下文中的 ID，不等同于展示名称 `agent_name`，也不自动转译 DSH Agent 对象；不确定代理 ID 时优先使用明确的 `session_id`。

`PromptAssembly` 包含 `text` 和 `sections`；每个 `PromptSection` 包含 `name/order/text/metadata`。钩子可调用已有 `append_section/replace_section/get_section`，或返回新的 `PromptAssembly`。自定义钩子负责保证 `text` 与 `sections` 内容一致，宿主不尝试推断任意字符串改写对应的结构。类型损坏或异步返回均显式报错。

## 范围、命名和顺序

`session_id=None` 与 `agent_id=None` 表示不限制该维度，具体 ID 必须为非空字符串。同一插件同名 section/variable 按以下优先级选一个：

1. 同时指定会话与代理。
2. 只指定会话。
3. 只指定代理。
4. 全局默认。

撤销覆盖项后，下次组装恢复默认。同一插件在完全相同范围内重复登记同名段或变量会报冲突。不同插件段名独立，输出名自动加 `<plugin>:` 前缀，例如 `example:language`。变量名由一个插件拥有，不同插件不能用同名变量互相覆盖，即使它们声明不同范围；这是与 DSH 通用作用域遮蔽的差异。

组装次序：已有内置段 → 当前可见的受管段 → 旧式及受管 assemble 钩子。受管段按 `order` 再按带插件前缀的完整名称排序，**仅在插件贡献之间排序，不重排内置段**。assemble 钩子按 `order` 再按登记顺序执行；同一范围内的多个钩子全部执行，不参与同名覆盖。

宿主每次构建提示词时读取当前贡献；现有模型请求和冻结的上下文不会被追溯修改。停用后的新组装不再包含这些贡献，但已经发给模型或写入历史的文本不会自动删除。

## 变量与失败处理

每次组装重新求值当前可见变量和段落。只在本门面贡献的段落中插值 `{{variable_name}}`；不会扫描或插值内置提示词和任意 assemble 钩子的输出，也不递归解释变量值里的模板。

未知变量、被引用但返回 `None` 的变量和格式错误的完整引用会报错。与固定上游实现一致，没有后续 `}}` 的不完整 `{{` 保留为普通文字。`interpolate=False` 原样保留整段花括号，适用于代码与模板文本。

所有变换在输入的深副本上进行，成功返回也与插件保留的对象分离。任一 provider、旧式钩子或受管钩子抛错，以及结果结构无效时，waterfall 抛出错误，原输入保持不变。桌面助手沿用现有策略：记录错误并使用未被修改的内置提示词；本次其他插件贡献也一并回退。**这与 DSH 阻止该次提示词组装的严格失败规则不同**。依赖提示词执行访问控制的插件必须另用真实工具/权限守卫，不能把提示词当成授权。

已有 `context.service("system_prompt_waterfall").register(...)` 保留兼容，但仍需调用者自行撤销，不能获得本门面的启动代和范围保证。新插件优先使用 `context.prompts`。

## DSH 对应和后续缺口

上游依据固定为 `f3803c96974ad4a94195fb97e5c637e9c2a3afe3`：
[官方源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/core/system-prompt/src/index.ts)和[作者说明](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/core/system-prompt/README.zh.md)。

| DSH 入口 | Sunday 对应或差异 |
| --- | --- |
| `systemPrompt.section({name, order, text, interpolate})` | `prompts.section(name, text, ...)`；参数结构、插件前缀和内置段排序不同 |
| `systemPrompt.variable(name, provider)` | `prompts.variable`；同步回调，变量所有权及范围需适配 |
| `system-prompt/assemble` | `prompts.on_assemble`；Python context/assembly 结构不同 |
| agent.ctx 的作用域覆盖 | 显式 `session_id/agent_id`；没有 Cordis 上下文自动桥接 |
| `complete` | 未实现精确完整提示词替换和冲突规则 |
| `context/refreshContext/suppressRuntimeContext` | 未实现独立 user 角色上下文、刷新和必需项规则 |
| `getSectionOrder/getContextOrder` | 未实现 DSH 第一方集中顺序表 |
| 工具 schema provider、toolOrder、modelSelection/toolSet | 继续由 Sunday 工具箱与模型请求管理，未实现相同组装字段 |
| `system-prompt/change` | 未提供注册变更事件 |

迁移报告包含 `promptMethods`，逐项给出 section/variable 建议与未覆盖方法；assemble 事件给出 `on_assemble` 建议。全部仍标记 `agent-required`，不自动运行或改写 JS，不声称整个 systemPrompt 服务完全兼容。

验收见 `core/tests/test_plugin_prompt_extensions.py`：受管启停、失败回滚、旧代隔离、覆盖恢复、变量与字面模板、排序、回调错误、实际桌面启动、主助手组装与子助手真实请求路径。子助手使用本地脚本模型，不访问外部模型服务。
