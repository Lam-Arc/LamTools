# DSH 插件兼容：分阶段实施与公开契约

逐项完成状态与后续待办见 [验收清单](dsh_compatibility_checklist.md)。仅经过相关测试与文档核对的子集勾选完成。

user:“我希望每一个地方 sunday 都有等价或者近似接口，能够脚本自动兼容 dsh 插件，分步做，宿主能力补齐和接口完善与文档更新，自动化兼容脚本，脚本不必能处理所有问题，剩下问题交给 agent 来移植”+(先建立完整能力基线，再逐项实现行为兼容，自动化负责确定性迁移，agent 负责剩余语义移植)。

## 目标与边界

仅面向 Sunday 桌面端。每个 DSH 扩展面都应有 Sunday 等价或明确标出差异的近似接口。以调用行为和生命周期验收，不以同名函数、导入替换或空实现判定兼容。

当前完整第二阶段状态见 [71 项完成清单](dsh_phase2_completion.md)，最新新增运行接口见 [2q 接口与限制](plugin_phase2_runtime.md)。后文 2a–2p 记录各自验收时的历史范围，其“尚未提供”以最新清单为准。

后续 2r 已补会话持久执行目录及原生检查点入口，见 [目录与恢复边界](plugin_session_recovery.md)；主代理工具目录和模型通知、完整DSH持久化协议仍未完成。

2s 已接通主代理六种文件工具与run_command的请求目录快照、送审前固定目标及模型尾部通知；其他工具、即时通知及DSH目录事件/持久化协议继续保留差异，详见同文2s章节。

2t已补专用Git固定cwd及工具目录归属表；2u新增[原生具名子代理控制](plugin_subagent_access.md)，复用原监督器和持久邮箱，不视为DSH根Agent/activation协议完成。相关新增及受影响的兼容验收68项通过，前端文件未改动。

2v已补单成员interrupt/resume：复用原监督器与提交历史，拒绝父暂停、live状态和缺少继续能力，并检查实际持有的执行器，避免恢复时退回全新run。新增8项验收，相关54项通过；单成员暂停、启动目录捕获及完整DSH Agent/activation协议仍未完成。

上游基线：`deepseek-ai/deepseek-harness` 的 `f3803c96974ad4a94195fb97e5c637e9c2a3afe3`，2026-10-27。官方来源：

- [服务目录](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/capability-seams.zh.md)。
- [插件作者教程](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/user/develop/basic/index.zh.md)。
- [扩展手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/cookbook/extension-cookbook.zh.md)。
- [Remote 契约](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/api-gateway.zh.md)。

[完整对照表](dsh_compatibility_matrix.md)覆盖官方目录全部 107 个服务键。51 项找到可复用的 Sunday 候选位置，56 项尚无已核实的等价公开契约。这些数字表示调查结果，**不是已兼容数量**。额外收录了核心钩子、四组已核对 Remote 方法和常用 UI 插槽；事件、方法和插槽的穷尽枚举还需在对应阶段按包补充。

`core/src/lamtools_core/plugin_system/dsh_compat/surface.json` 是对照表的机器可读来源，随 Python 包交付。107 项服务状态仍只有 `candidate` 和 `gap`：前者仍需契约、适配和行为验收，后者仍需核实或新增接口。额外的 `hostContracts` 单独记录已验收的 Sunday 基础契约，不计为 DSH 服务已完全兼容。不能在只有候选实现时标记 compatible。升级上游时重新核对服务、方法签名和语义，并记录新提交，不能悄悄跟随 master。

## 阶段与完成条件

| 阶段 | 工作 | 完成条件 | 当前状态 |
| --- | --- | --- | --- |
| 1：基线与迁移准备 | 固定上游、107 项服务对照、能力发现、静态资源迁移、agent 交接 | 新测试验证真实 Sunday 解析器能读取生成资源；未移植源码显式保留待办；不改原插件 | 本次完成，见验收记录 |
| 2：核心宿主契约 | 服务依赖和作用域、注册与撤回、会话/Agent、消息/流、工具/钩子、提示词、存储、配置、凭据、权限和运行能力 | 每项先写验收测试，再接到现有宿主；参数、返回、错误、取消、持久化和卸载均有记录 | 进行中：2a–2p 及 2q–2v 运行、恢复与成员控制子集已验收；完整 71 项仍逐项推进，见完成清单 |
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

## 第二阶段 2f：内存技能注册与调用策略（已完成基础子集）

<!-- user:“宿主能力补齐和接口完善与文档更新”+(内存技能沿原注册表、工具与用户展开路径工作，不新增文件权限)。 -->

[技能扩展 v1](plugin_skill_extensions.md)提供 `context.skills.register`，在受管启动代中登记全局内存文字技能。沿原 SkillRegistry 合并发现，接到模型 `load_skill`、用户技能选择、管理 `skill.list` 与启用/禁用。模型和用户策略四种组合分别验收；旧注册表和工具箱在撤回后不能继续从目录缓存加载。

真实桌面测试发现并修复了子助手未继承技能禁用账本的问题；主助手、子助手、后台入口和子助手克隆共享禁用状态。加载前规范技能名，阻止通过首尾空白绕过禁用。内存项没有文件位置，不扩大资源目录权限；管理界面删除操作明确拒绝。

本批新增 **16 项**技能测试与 **1 项**迁移识别测试，七组本需求新增测试共 **148 项通过**。迁移报告新增 `skillMethods`，登记/列举给出人工映射，外部 provider、scope 层级、snapshot/invalidate、动态目录和 skills/change 保留待办。静态技能目录优先于同名内存项，已交付正文不追溯撤回；未宣称整个 DSH skills 服务完全兼容。

遵照并行工作约束，本批只修改后端、相关测试和文档，未修改前端样式或拆分文件；本批无因此产生的阻塞项。

## 第二阶段 2g：模型目录与场景选择查询（已完成只读子集）

<!-- user:“宿主能力补齐和接口完善与文档更新”+(模型元数据与场景查询先明确契约，不把只读目录冒充 LLM/子代理全部能力)。 -->

[模型访问 v1](plugin_model_access.md)提供 `context.models.list/resolve/select` 和不可变 `ModelDescriptor/ModelSelection`。门面固定当前项目与启动代，读取现有模型配置；区分模型记录 ID 和提供方模型名，精确别名重名时明确拒绝，避免按模糊名称误选。

选择复用原 chat/study/background 场景记忆，不跨场景或回退到全局默认；同场景替换携带提示。显式选择不写入配置，不发送模型请求。目录成员不等于子助手路由授权，查询结果不替代会话或运行档最终选模。

本批新增 **10 项**模型访问测试与 **1 项**迁移识别测试，八组本需求新增测试共 **159 项通过**。真实桌面启动、本地脚本子助手请求与真实文件配置覆盖已验证；无外部模型调用。迁移报告新增 `modelMethods`，stream/prepareCall、适配器、全局写入与子助手路由政策继续保留待办。

本批未修改前端样式或拆分文件；没有因并行前端工作而跳过的阻塞项。

## 第二阶段 2h：插件持久 JSON KV（已完成基础子集）

<!-- user:“宿主能力补齐和接口完善与文档更新”+(存储状态接到既有稳定数据目录，SQLite 原子提交与条件写保护并发修改)。 -->

[存储访问 v1](plugin_storage_access.md)提供 `context.storage.open` 和 get/put/delete/keys/close。状态位于现有插件独立数据目录，绑定 owner 与启动代，区分缺失/null、精确单元版本及记录 revision；条件写防止旧数据覆盖，删除墓碑防止重建后的旧版本误通过。一般状态不混用配置或凭据路径。

损坏文件不静默清空；锁等待失败明确返回；提交确认不确定时隔离旧句柄，重新打开后核对。成功持久写不会因后续插件启动失败自动回滚，这一点已明确测试和记录。实际桌面启动以及替换代码后在新解释器中重启恢复已验证。

本批新增 **14 项**存储测试与 **1 项**迁移识别测试，九组本需求新增测试共 **174 项通过**。迁移报告新增 storageMethods，对 storageDomain.open 只给人工改造候选，不做盲替换。DSH 类型化领域、后端/form 注册、路由、compatibleVersions、异步领域写链及 domain/changed 继续保留缺口；配置与凭据接口完善不在本批范围。

本批未修改前端样式或拆分文件，没有因并行前端工作而跳过的阻塞项。

## 第二阶段 2i：凭据引用与可靠持久化（已完成基础子集）

<!-- user:“宿主能力补齐和接口完善与文档更新”+(凭据元数据与明确读取值分离，沿原格式修复缓存覆盖和坏文件误写，受管门面可撤回)。 -->

[凭据引用 v1](plugin_credentials.md)提供 `context.credentials.resolve/describe/set/unset`。门面固定当前插件 owner 与启动代；describe 不含值、不解密，resolve 才明确返回值。旧 DPAPI 及 version=1 密文格式保持兼容，新接口不提供全局环境回退、授权记录或变更事件。

原凭据库改为按操作重读磁盘，移除实例缓存的状态权威；线程与进程锁串行读改写，唯一临时文件完成原子替换。坏文件或不支持的版本不伪装为空库，替换前失败不污染后续读取，错误文字不转发底层载荷。实际测试验证两个独立进程并发写入无丢失，锁等待有界，旧 scoped secrets 公开行为继续兼容。

本批新增 **15 项**凭据验收与 **1 项**迁移识别测试，十组本需求新增测试共 **190 项通过**。迁移报告新增 credentialMethods，四个引用方法给人工映射，readRecord/modifyRecord 和事件继续保留缺口；配置接口留待后续。

本批仅修改相关后端、测试和文档，没有修改前端样式或拆分文件，也没有因并行工作而跳过的阻塞项。

## 第二阶段 2j：配置快照与条件保存（已完成基础子集）

<!-- user:“宿主能力补齐和接口完善与文档更新”+(配置门面和管理入口共用路径、基础校验及保存函数，明确保存不代表应用)。 -->

[配置访问 v1](plugin_config_access.md)提供 `context.config.read/validate/replace`，绑定实际加载清单、owner 与启动代。快照包含原始配置/schema 的内容修订；SDK 保存强制提交修订号，合作进程检查与写入串行完成。原管理 get/update 及内置旧写入 helper 共用同一文件路径与锁，正常 JSONC 注释和尾逗号可读，坏文档不默认为空或无 schema。

保存返回 applied=false、requires_reload=true，不自动重启或回滚插件。基础校验仅沿用 required、顶层 type/enum，并非完整 Config/JSON Schema。旧管理调用可省略修订号，现有界面尚未接入该字段，仍可能最后写入覆盖；前端接线留待统一处理。本批没有修改并行样式或拆分文件。

本批新增 **15 项**配置验收与 **1 项**迁移识别测试，十一组本需求新增测试共 **206 项通过**。覆盖内置路径、坏 schema、保存失败、启动代、独立进程冲突/锁等待与真实桌面 SDK/管理入口互通。迁移报告新增 configMethods，只给 configEditor.edit 人工改造候选；profile overlay、volatile、secret 投影、热重载失败回滚和注释保留继续保留缺口。

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

## 第二阶段 2k：固定工作目录与只读文件访问（已完成基础子集）

user:“宿主能力补齐和接口完善与文档更新”+(公开可验收的固定目录只读子集，其他文件系统语义继续交给 agent)。

新增 context.filesystem.root/stat/read_bytes/read_text/list_dir，固定当前插件启动代与取得视图时的工作目录。读取要求显式字节上限（最多 1 MiB），列表要求检查 truncated。停用或重启后旧视图失效；目录外路径、已观察到的链接与 Windows junction 被拒绝。路径检查不是原子安全边界，无跨调用快照、取消或 I/O 截止时间。

以固定上游 fs 与 workingDirectory 源码/手册核对差异：没有 FsTarget 身份、写入/编辑/监听、流或远程后端，没有会话目录持久化 set/ensure、恢复和模型上下文通知。fs 从 gap 调整为 candidate，全部条目仍不宣称 DSH 运行兼容。迁移报告新增 filesystemMethods，按方法给建议或明确待办，全部 agent-required。

接口、错误、限制与示例见 [只读文件访问](plugin_filesystem_access.md)。验收在 core/tests/test_plugin_filesystem_access.py 与迁移测试中，未改动前端文件。

## 第二阶段 2l：插件手动会话压缩（已完成基础子集）

user:“宿主能力补齐和接口完善与文档更新”+(插件沿用桌面压缩权威，明确实际执行、修订冲突、取消和停用边界)。

新增 context.compaction.compact_now(session_id, expected_revision=...)，固定启动代与工作目录，要求已知 idle/completed 会话及 SESSIONS.state.last_event_seq。通过现有桌面 compact 命令复查修订号、认领运行和写入控制记录，调用实际压缩提供方，保留原始历史。结果区分 compacted/not_needed/cancelled；调用者取消仍传播，失败或取消不代表回滚。停用拒绝新调用并等待已接收调用结束。

已验收实际压缩及数据库重开后的摘要与历史，覆盖并发回合/压缩排他、前后两次修订检查、取消、失败、错误响应和启动代撤回。接口不保证压缩完成时立即唤醒队列；没有 DSH 的持久压缩锁、跨进程互斥、区间/自动触发 API 或检查点协议。compaction 条目保留 candidate，迁移报告新增 compactionMethods，仅 compactNow 给出近似映射，全部 agent-required。

接口与限制见 [手动压缩](plugin_compaction_access.md)。前端文件未修改，自动队列唤醒与持久锁等差异保留为后续统一处理项。

## 第二阶段 2m：权限目录与会话偏好读取（已完成基础子集）

user:“宿主能力补齐和接口完善与文档更新”+(权限读取复用既有会话规则，只展示偏好，不生成授权)。

新增 context.permissions.catalog/read：读取固定 Sunday 预设目录、当前全局默认和指定可见会话的规范化持久偏好。免问等级与会话基础能力上限分开返回，full_access 不提高 read_only 的基础上限；结果不可变，不能当作执行授权。复用 session_runtime_preferences/resolve_permission_preset，未改权限计算或执行策略。

会话存储新增 get_readonly，保持原可见性且不补写旧数据、不更新运行缓存；原 get 的旧数据规范化行为保留。新增验收覆盖旧数据查询不写回、普通 get 仍迁移、全局默认与已有会话隔离、隐藏会话、实际存储更新、错误、取消与停用撤回。

迁移报告新增 permissionMethods，仅 permissionPresets.catalog/current 有人工近似映射。Sunday auto 是免问等级 2，与 DSH Auto review 不同；审批 request/setPolicy、预设 set/registerAuto、sandbox 组合和审计协议仍待补齐，不用只读接口冒充。详见 [权限读侧契约](plugin_permission_access.md)。未修改前端文件。

## 第二阶段 2n：程序解析与环境构造（已完成基础子集）

user:“写好清单，逐项打勾完成，不要出错”+(把进程基础与完整运行分开验收，只勾选已有证据的子集)。

核对固定上游 subprocess 源码/手册后，新增 context.processes.resolve_executable/environment。同步解析宿主绝对程序路径或 PATH 名称，不启动程序；Windows 使用 PATHEXT，忽略相对/空 PATH 项及隐式当前目录搜索，并限制查找项数量。环境按名称启发式过滤凭据及宿主前缀，支持显式字符串覆盖和 None 删除；返回不可变副本，限额为 256 个覆盖项与合并后 1 MiB。

接口绑定插件启动代，停用后旧视图失效；查找不等于授权、运行或目标版本锁定。仍未提供 spawn、终端、标准流、进程取消/终止或整棵受管范围退出证明，不把已有普通运行函数当作这些契约的完成证据。subprocess 从 gap 调整为 candidate，全部服务仍未声明 DSH 运行兼容。

迁移报告新增 processMethods，仅 resolveExecutable 和直接 scrubbedParentEnv 调用有人工近似建议，其他执行/终端方法保留待办。详见 [接口与差异](plugin_process_access.md)和[逐项验收清单](dsh_compatibility_checklist.md)。未改动前端文件。

## 第二阶段 2o：文件字节窗口与最终链接元数据（已完成基础子集）

user:“写好清单，逐项打勾完成，不要出错”+(文件读取按窗口和链接边界单独验收，未完成的写入和监听继续保留待办)。

context.filesystem 新增 read_byte_range(path, offset=..., length=...) 与 lstat(path)。字节窗口最多 1 MiB，直接定位读取，不加载整个文件或前缀；允许零长度、EOF 空读及末尾短读，区间端点限定在有符号 64 位范围。lstat 只观察最终符号链接/Windows 重解析点本身，包括断开链接；根或中间链接仍拒绝，其他读取继续拒绝最终链接。

新增测试确认实际读取调用只有指定定位与长度，覆盖大文件、二进制、参数错误、链接越界/穿透、根被替换为链接及启动代撤回。迁移提示分别记录 readByteRange/lstat 的返回与参数差异；写入、流、监听和远程提供方仍未实现。机器清单 filesystem 升为 v2，保留旧方法，仍不宣称完整 DSH 兼容。

详见 [文件接口](plugin_filesystem_access.md)与[逐项清单](dsh_compatibility_checklist.md)。未修改前端文件。

## 第二阶段 2p：有界文本流读取（已完成基础子集）

user:“继续，列好清单 逐项打勾”+(文本流按解码、总量和资源边界独立验收，完成后更新清单)。

context.filesystem.stream_text 返回同步 Iterator[str]，要求显式 max_bytes（最多 64 MiB），读块最多 64 KiB。UTF-8 增量解码保留跨块字符、BOM 和原始换行，拒绝 NUL/坏编码；初始文件超限在任何前缀返回前拒绝。每块重新打开并定位读取，yield 前关闭句柄，提前停止不遗留打开的文件。

通过身份/长度/修改时间检测普通文件替换或改写，并在耗尽前再次核对；Windows stat/fstat 的 ctime 差异不参与跨接口比较，已添加回归验收。只有正常耗尽才能确认完整文本，后部坏数据、变化或停用可在已返回前缀后报错，不保证原子快照。

filesystem 升为 v3，迁移提示为 streamText 提供有限同步子集建议；写入、编辑、监听和远程后端继续未完成。相关新增测试覆盖解码、限额、资源、普通变更、最终检查及启动代撤回。详见 [文件接口](plugin_filesystem_access.md)和[逐项清单](dsh_compatibility_checklist.md)。未改动前端文件。

## 第二阶段 2q：实际调用、后台工作及文件修改（有界接口已验收）

user:“继续，把 2 阶段都做完”+(从基础读取推进至真实执行，同步显式差异，不以空提供方或基础子集标记整个阶段完成)。

新增文件条件修改、Windows Job受管进程、真实模型请求/流、持久目标与计划、有限会话查询、后端审批审计、插件管理与运行档读取；继续补齐本地路径转换、轮询监听、PowerShell和环境贡献、Python后台作业与长文本保存。各入口均受当前插件启动代管理；持久数据与瞬态资源分别按原宿主语义保留或回收，详见 [运行接口](plugin_phase2_runtime.md)。

自动迁移报告新增实际方法候选，保持 agent-required 和 runtimeVerified=false；没有盲改 JS/TS，也没有标记任何 DSH 服务 compatible。文件监听只轮询、进程存在启动到Job分配窗口，后台回调须配合取消，session标签不构成授权，保存或审计不绕过原工具审批。终端/沙箱/远程/完整日志及会话恢复等仍见未勾选清单。

机器清单 filesystem 升为v5，新增 shell、jobs、spill 等已验收Python契约。此前联合验收383项通过，本批新增及受影响的15个兼容测试模块190项通过（两组重叠，不相加）。未修改前端文件。
