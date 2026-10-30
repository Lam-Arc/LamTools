# 插件内存技能 v1

<!-- user:“宿主能力补齐和接口完善与文档更新，自动化兼容脚本，脚本不必能处理所有问题，剩下问题交给 agent 来移植”+(内存技能通过原发现、加载和用户选择路径工作，明确与 DSH 提供方协议的差异)。 -->

Sunday 桌面进程内 Python 插件可通过 `context.skills.register` 登记内存中的文字技能。技能进入已有 `SkillRegistry`、模型 `load_skill`、用户技能选择和管理目录。它没有磁盘文件位置，也不新增文件访问权限。

## 登记与撤回

```python
class Runtime:
    def start(self, context):
        self.remove = context.skills.register(
            "example-review",
            "检查项目中的特定规则时使用",
            "先检查规则，再逐项说明发现的问题。",
            model_invocable=True,
            user_invocable=True,
        )

def create_plugin(context):
    return Runtime()
```

签名：`register(name, description, content, *, model_invocable=True, user_invocable=True)`，返回可重复调用的撤销函数。name 为最长 128 字符的小写 kebab-case 名称；description/content 必须为非空字符串，策略必须为布尔值。不接收 provider 回调、文件路径或会话范围参数。

工厂只构造运行对象，在受管 `start/on_load` 中登记。启动和健康检查通过前不公开，失败、停用和更新会撤回该代贡献。旧门面不能继续登记，旧撤销函数不能删除后来同名注册。

所有内存技能当前全局生效。同一宿主内，活动内存注册不能重名，即使来自不同插件；不同宿主独立。与磁盘技能同名时保留原优先级，磁盘技能胜出，内存项被遮蔽；删除磁盘技能后内存项才显现。该规则不同于 DSH 的 rank 与 scope 分层合并，移植时需核对名字冲突。

## 调用策略

| model_invocable | user_invocable | 模型索引及 load_skill | 用户目录及显式技能选择 |
| --- | --- | --- | --- |
| true | true | 允许 | 允许 |
| true | false | 允许 | 拒绝 |
| false | true | 拒绝 | 允许 |
| false | false | 拒绝 | 拒绝 |

管理目录保留四种组合。策略同时作用于发现和实际读取，不能通过直接填写名称绕过。`allow_implicit_invocation` 仍是既有文件技能的索引展示策略，不替代这两个调用开关。

已有技能启用/禁用账本同时作用于模型加载和用户展开。主助手、子助手、后台入口及子助手克隆继承同一账本；技能名在加载前先裁剪首尾空白，避免与禁用检查使用不同名称。

## 宿主路径

| 入口 | 行为 |
| --- | --- |
| 模型技能索引 | 只包含允许模型调用且已启用的技能 |
| `load_skill` | 沿原工具箱与审批链按需返回正文；每次重新检查当前可用性 |
| `command.catalog` 的技能项 | 只包含允许用户调用且已启用的技能 |
| 用户选择技能 | 沿原 composer 输入准备路径展开，检查用户策略与启用状态 |
| `skill.list` | 管理目录，包含 `model_invocable/user_invocable`，内存项 `source="plugin"`、`location=""`、`deletable=false` |
| `skill.enable/disable` | 使用原持久账本；不会停止插件其他能力 |
| `skill.delete` | 内存项只读，拒绝删除文件；由注册方撤销或插件停用清理 |

内存正文沿原长度上限截断，超过上限时明确标注。不会输出虚假的 Base directory，也不会给 `read_file/run_command` 增加资源目录，或因加载内存技能解锁清单中的其他惰性工具。依赖相对路径、脚本或资源文件的技能应继续使用已有静态技能目录，不能仅把 SKILL.md 正文复制到内存注册。

动态贡献每次合并到现有磁盘目录后；已有注册表和长寿命工具箱在停用后不会继续从旧目录缓存加载。已经返回的 Skill 对象、已经展开的输入、已进入历史或发给模型的正文不会追溯删除。这里没有 provider 的异步调用或额外排空租约，登记和内存读取同步完成。

当前前端没有增加动态注册变化订阅。现有模型请求和冻结提示词沿用原生命周期；注册或撤回不保证已打开的技能菜单或正在进行的模型调用立即刷新。

## DSH 对应和剩余缺口

上游依据为固定提交 `f3803c96974ad4a94195fb97e5c637e9c2a3afe3` 的[技能作者说明](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/skill/skill/README.zh.md)。

| DSH 入口/行为 | Sunday 当前对应 |
| --- | --- |
| `skills.register(definition)` | `context.skills.register(name, description, content, ...)`；对象与 camelCase 策略需适配 |
| `skills.list(...)` | 管理 `skill.list` operation；不是 DSH cwd/scope 异步发现协议 |
| 模型消费 | 原 `load_skill`；模型策略与权限链继续生效 |
| 用户消费 | 原技能选择与输入准备路径；用户策略继续生效 |
| `registerProvider` | 未实现外部提供方、异步 list/get 和取消竞速 |
| scope 层级、rank 与冲突裁决 | 当前仅全局内存注册，磁盘优先，内存重名拒绝 |
| `snapshot/invalidate`、不完整发现与 revision 缓存 | 未实现相同公开协议 |
| `skills/change` | 未实现事件通知 |
| 动态文件目录挂载 | 未实现；静态清单目录迁移继续可用 |

迁移报告新增 `skillMethods`，对 register/list 给出人工映射；registerProvider、snapshot 等保留待办，全部标记 `agent-required`。不会自动转换 JS provider，也不会把临时路径当作已实现的目录或文件能力。

验收见 `core/tests/test_plugin_skill_extensions.py`：启动/失败/停用、旧代隔离、宿主隔离、四种调用策略、禁用与空白名称、磁盘优先级、正文长度、无文件授权，以及真实桌面管理目录、主/子助手与克隆、live 用户技能展开路径。
