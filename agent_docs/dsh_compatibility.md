# DSH 插件兼容：分阶段实施与公开契约

user:“我希望每一个地方 sunday 都有等价或者近似接口，能够脚本自动兼容 dsh 插件，分步做，宿主能力补齐和接口完善与文档更新，自动化兼容脚本，脚本不必能处理所有问题，剩下问题交给 agent 来移植”+(先建立完整能力基线，再逐项实现行为兼容，自动化负责确定性迁移，agent 负责剩余语义移植)。

## 目标与边界

仅面向 Sunday 桌面端。每个 DSH 扩展面都应有 Sunday 等价或明确标出差异的近似接口。以调用行为和生命周期验收，不以同名函数、导入替换或空实现判定兼容。

上游基线：`deepseek-ai/deepseek-harness` 的 `f3803c96974ad4a94195fb97e5c637e9c2a3afe3`，2026-10-27。官方来源：

- [服务目录](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/capability-seams.zh.md)。
- [插件作者教程](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/user/develop/basic/index.zh.md)。
- [扩展手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/cookbook/extension-cookbook.zh.md)。
- [Remote 契约](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/api-gateway.zh.md)。

[完整对照表](dsh_compatibility_matrix.md)覆盖官方目录全部 107 个服务键。44 项找到可复用的 Sunday 候选位置，63 项尚无已核实的等价公开契约。这些数字表示调查结果，**不是已兼容数量**。额外收录了核心钩子、四组已核对 Remote 方法和常用 UI 插槽；事件、方法和插槽的穷尽枚举还需在对应阶段按包补充。

`core/src/lamtools_core/plugin_system/dsh_compat/surface.json` 是对照表的机器可读来源，随 Python 包交付。107 项服务状态仍只有 `candidate` 和 `gap`：前者仍需契约、适配和行为验收，后者仍需核实或新增接口。额外的 `hostContracts` 单独记录已验收的 Sunday 基础契约，不计为 DSH 服务已完全兼容。不能在只有候选实现时标记 compatible。升级上游时重新核对服务、方法签名和语义，并记录新提交，不能悄悄跟随 master。

## 阶段与完成条件

| 阶段 | 工作 | 完成条件 | 当前状态 |
| --- | --- | --- | --- |
| 1：基线与迁移准备 | 固定上游、107 项服务对照、能力发现、静态资源迁移、agent 交接 | 新测试验证真实 Sunday 解析器能读取生成资源；未移植源码显式保留待办；不改原插件 | 本次完成，见验收记录 |
| 2：核心宿主契约 | 服务依赖和作用域、注册与撤回、会话/Agent、消息/流、工具/钩子、提示词、存储、配置、凭据、权限和运行能力 | 每项先写验收测试，再接到现有宿主；参数、返回、错误、取消、持久化和卸载均有记录 | 进行中：2a 服务、2b 会话、2c 工具、2d 提示词与 2e 动态命令基础子集已验收，其余待实施 |
| 3：前端与 Remote | 类型化远程调用、访问控制、二进制/双向流、事件名单、Vue UI 扩展与 DSH slot 对照 | 四组已列 Remote 和补充枚举逐项验收；UI 各位置具备注册、撤回和会话隔离 | 待实施 |
| 4：转换与真实插件 | 在已验收契约之上增加 JS/TS 兼容层、自动改写、可选/实验提供方；逐类移植真实插件 | 工具、钩子、MCP/技能、会话、UI 各有真实上游插件；原功能差异和剩余工作可回溯 | 待实施 |

阶段 2 优先顺序：

1. 定义类型化宿主服务及注册的 owner、作用域、依赖、撤回与代际；复用 `PluginSupervisor`，不另建生命周期权威。
2. 公开 Session/Agent 创建、恢复、排队、steer、取消、等待和输出跟随；区分入队回执与完成结果，持久事实与瞬态 token。
3. 工具动态注册、restrict、guard 和执行阶段钩子；保留现有审批链；逐项核对 waterfall 的 next 与 deny/ask 语义。
4. 提示词 section、技能和命令注册；模型/子代理/压缩服务；工作目录、文件、shell、后台任务和终端的公开契约。
5. 存储、配置、凭据、计划、目标、定时任务及可替换提供方。将尚未公开的宿主内部能力提升为版本化契约。

71 项服务安排在阶段 2，20 项在阶段 3，16 项在阶段 4；阶段号是实施顺序，不是交付日期。每项落地同步更新契约、对照表和新增验收测试。

## 第二阶段 2a：受管服务基础（已完成）

<!-- user:“继续”+(接续第一阶段，先完成依赖和资源生命周期基础，不把阶段2整体误标完成)。 -->

[服务注册与清理 v1](plugin_owned_services.md)提供 `ServiceKey`、`register_service`、`bind_service`、`ServiceRef.call`、`effect`、`on_dispose`。服务在启动和健康检查通过后才公开；失败、停用撤回；跨插件调用租约先排空再清理；旧引用不会进入新代。直接接入现有 supervisor，未另建插件生命周期权威。

新增 22 项验收测试，合并本需求第一阶段的 17 项后共 **39 passed**。真实加载失败回滚、管理器启停/重启、健康失败清理、重试和取消已验证。迁移报告的 `sundayHostContracts` 与 PORTING.md 同步指向该接口。

2a 本身没有提供会话/工具具体能力，也没有 Cordis 完整依赖树自动重组和 JS/TS 运行兼容。

## 第二阶段 2b：桌面会话基础控制（已完成）

<!-- user:“继续”+(把已验收的注册机制用于真实桌面会话接口，继续保留未实现的 DSH 扩展面)。 -->

[会话控制 v1](plugin_session_control.md)通过公开 SDK 的 `SESSIONS` 提供 create、state、prompt、update_queue、cancel、events、follow、wait。消息和控制复用桌面 live 接收路径，历史读取原有持久事件，回执不冒充完成；queue 与 steer 的去向明确。

会话服务在插件 start 前发布，真实启动验收确认插件能直接绑定该依赖。新建事务拒绝覆盖已有实体，包含 revision=0 的项目空白记录。请求重试从接收事件去重，取消请求不截断已开始的短提交。follow 不包含瞬态 token；创建尚不绑定项目/preset；附件、模型、fork 和 Agent 工厂未覆盖。

本批新增 **31 项**测试。只运行本需求新增的三组相关测试，共 **70 passed**；未运行全量测试，未使用 Computer Use。迁移机器目录、建议映射、作者文档与 PORTING.md 已同步更新。

## 第二阶段 2c：动态工具与执行钩子基础子集（已完成）

<!-- user:“宿主能力补齐和接口完善与文档更新”+(补齐实际工具注册、审批和生命周期契约，明确未覆盖的 DSH 行为)。 -->

[动态工具与钩子 v1](plugin_tool_extensions.md)提供 `context.tools.register/restrict/guard/on`。真实桌面启动在插件 start 前提供能力，主助手和子助手沿原工具箱装配接入，复用数值等级审批。注册随所属启动代撤回，旧调用令牌不能执行重启后的处理函数，同名提供方冲突关闭执行。执行取消释放租约，预算耗尽继续交给 kernel。

pre 支持 allow/deny，最终 guard 不可被 allow 覆盖；post 仅允许内容补丁，result 观察最终只读结果。支持会话范围与扁平原始类型 schema，未实现参数改写、动态 ask、复杂 schema、`tools/execute` 的 next/waterfall 与重试。DSH 服务仍标为候选/缺口，不能据此声称全量兼容。

本阶段新增 **26 项**工具验收测试和 **1 项**迁移建议验收；本需求四组新增测试共 **97 项通过**。迁移脚本为已验证子集提供人工映射并更新 PORTING.md，仍不执行或自动翻译 JS。后续继续补齐其余核心宿主接口，再推进 Remote、前端与提供方能力。

## 第二阶段 2d：提示词段、变量与受管组装（已完成基础子集）

<!-- user:“宿主能力补齐和接口完善与文档更新”+(提示词沿用原组装链，增加所有权与范围，错误时真实回退而非保留半成品)。 -->

[提示词扩展 v1](plugin_prompt_extensions.md)提供 `context.prompts.section/variable/on_assemble`。贡献受启动代管理，支持同步动态文本、变量插值、显式会话/agent_id 范围、覆盖恢复、插件内部排序和自动撤回；主助手与子助手沿用原组装入口。原流水线改为副本上组装，回调失败或结果结构损坏时，桌面助手可以恢复未被污染的内置提示词。

已重新核对固定上游的 system-prompt 源码和作者说明。Sunday 追加段只在插件之间排序，不重排内置提示词；错误时按原策略回退，而 DSH 严格拒绝组装。完整替换、独立动态上下文/刷新/抑制、集中顺序表、change 事件和工具 schema 组装尚未实现。现有模型请求与冻结上下文不追溯更新。

本批新增 **20 项**提示词测试与 **1 项**迁移识别测试，五组本需求新增测试共 **118 项通过**；未运行全量测试，未使用 Computer Use。迁移报告新增 `promptMethods`，将已支持方法与未覆盖方法分开交给 agent，保留 JS 原码和 `runtimeVerified=false`。技能/命令动态注册、模型/压缩、运行能力和其余阶段 2 服务继续按清单推进。

## 第二阶段 2e：动态斜杠命令（已完成基础子集）

<!-- user:“宿主能力补齐和接口完善与文档更新”+(动态命令接入原目录与执行通道，不创建第二套运行权威)。 -->

[命令扩展 v1](plugin_command_extensions.md)提供 `context.commands.register`、`CommandInvocation` 与 `CommandResult`，接入原 `command.catalog/execute` 和桌面 live 路径。注册按启动代暂存、公开与撤回，支持同插件会话覆盖、处理器调用排空和取消。实际 live 测试确认受管命令不会被旧 actions 同名处理器抢占，停止后也不会回退调用旧处理器。

本批新增 **12 项**命令验收与 **1 项**迁移识别测试，六组本需求新增测试共 **131 项通过**。迁移报告新增 `commandMethods`，同步作者说明、逐项对照和 PORTING.md；仍不自动翻译 JS handler。

已核对固定上游的命令作者说明。当前只支持文本，Sunday 裁剪输入空白；附件、完整行解析、稳定定义 ID、commands/change 和 DSH command/run/done 日志仍有差异。现有界面仅查询全局目录，会话专属目录与菜单自动刷新留到前端阶段。动态技能注册不包含在本批，静态技能登记仍可使用迁移脚本。

## 第一阶段新增的宿主接口

Python 插件直接使用传入的 `PluginContext`：

```python
description = context.describe_host()
models = context.require_service("model_catalog")
execute = context.operation_executor()
result = await execute(operation_name, payload, metadata)
```

`describe_host()` 返回 JSON 可表示的描述：

```json
{
  "contractVersion": 1,
  "services": [
    {"name": "model_catalog", "available": true, "scope": "host"},
    {"name": "secrets", "available": true, "scope": "plugin"}
  ],
  "operations": ["当前目录中实际可用的操作名"],
  "externalProcessHostCallbacks": false
}
```

- 每次查询读取当前状态，不缓存可用性；仅列服务名字、是否存在和来源作用域，不序列化对象、配置或凭据值。
- 当前插件的 scoped service 优先于共享 service；值为 None 表示不可用。`require_service()` 在缺失时抛出包含名字的 LookupError。
- 操作目录通过现有 parent 链解析，支持目录在插件初始化之后才挂载；列表与执行均保留原 availability 判断。
- `operation_executor()` 是已有接口，本次验证了其元数据透传和不可用操作拒绝。调用者仍须使用宿主实际提供的操作目录；能力发现不是新的授权。
- 查询适用于进程内 Python 插件。现有 process runtime 暂不提供反向宿主回调，也没有 DSH Context 的自动代理。
- 本次没有把候选服务包装成 DSH 同名空方法，没有新增另一套 Agent、工具执行或权限状态。

## 自动化脚本

在仓库根目录运行，仅分析本地目录，不下载、安装依赖或执行插件代码：

```powershell
python scripts/dsh_compat.py E:/sources/dsh-example
python scripts/dsh_compat.py E:/sources/dsh-example --output E:/ports/sunday-example
python scripts/dsh_compat.py --matrix
```

安装了 core 包时也可使用：

```powershell
python -m lamtools_core.plugin_system.dsh_compat E:/sources/dsh-example
```

默认只向标准输出写 JSON 报告。`--output` 才创建迁移目录，拒绝覆盖已有目录，也拒绝源与目标相互包含。输出通过暂存、真实宿主解析和最终重命名发布；验证失败不留下半成品迁移目录。

目录包含：

| 文件 | 内容 |
| --- | --- |
| `plugin.json` | Sunday 名称/版本、已迁移静态资源、迁移状态；默认停用 |
| `upstream/` | 原插件源码、包信息、许可证和资源，保留原相对结构 |
| `migration-report.json` | 固定基线、服务使用位置、事件、Remote、slot、未解决问题与分析范围 |
| `PORTING.md` | 给 agent 的逐项待办及验收要求 |

当前自动处理：npm scoped 名称转单段 Sunday 名称，登记可识别的静态技能目录，登记根目录 `mcp.json` / `.mcp.json`，保留其资源。使用 Sunday 真正的 manifest/capability 解析器验证，并检查技能没有因重名等原因丢失。MCP 仅转换声明；路径、依赖、变量和外部服务必须在目标运行环境核验。

当前只分析并交给 agent：JS/TS 后端、Cordis 生命周期、动态工具/服务注册、钩子、YAML 组合、React 界面、Remote、动态 Context 属性、未知服务和嵌套包。不会自动把 `@deepseek-ai/*` 替换成一个未经实现的 Sunday 包，也不会自动声明原 JS 工具已经可执行。

扫描默认限 4000 文件、32 MiB。跳过 `.git`、`node_modules`、`.venv`、`__pycache__`、`.env` 等已声明排除项；拒绝符号链接和 Windows junction。未知本地代码仍保留给 agent。它是保守静态扫描，不是完整 TypeScript 分析器：注释/字符串可能误报，计算属性、复杂别名和跨函数 Context 传递可能漏检。`runtimeVerified` 始终为 false。

退出码：0 表示只发现可登记的静态资源，**仍未运行验证**；2 表示报告/目录已生成，但需 agent 移植；1 表示输入、限额或导出验证失败。所有生成插件都默认停用，不安装到正在运行的 Sunday。

## agent 接续规则

先读生成的 PORTING.md、原 README 与许可证，再按服务、事件、Remote 和 UI 逐项移植。每个接口记录：参数/返回类型、同步或异步、作用域/所有权、权限、取消、错误、持久状态、停用和更新清理。近似接口必须写差异，不能吞异常或返回伪成功。

优先接到 Sunday 已有权威。需要下沉 Rust 的共享能力先确定跨语言协议和验收，渐进迁移；不为清单和静态扫描再造 Rust 状态表。进程后端继续走已有 supervisor 和 JSON-RPC 协议，UI 继续走桌面插件生命周期。具体已有契约见 [插件生命周期](../core/docs/plugin-lifecycle.md)和[宿主重建](plugin_host_rebuild.md)。

## 本次验收

先新增测试并验证缺少兼容模块时失败，再实现。只运行本次新增的 `core/tests/test_dsh_compatibility.py`，未运行全量测试，未使用 Computer Use。记录包括完整目录与文档一致性、实际静态资源读取、源码保留、明确待办、命令行状态、覆盖保护、限额、链接拒绝、技能冲突、服务隔离和操作可用性。

测试结果及当前范围见 [第一阶段验收](dsh_compatibility_acceptance.md)。真实第三方 DSH 插件的 JS/TS 执行兼容、UI 对等与全量移植尚未验收，继续按阶段 2–4 推进。
