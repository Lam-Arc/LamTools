# 夜间工程报告 · 2026-11-03

分支 `sunday/reliable-base`，工作树 `E:/LamTools/.worktrees/reliable-base`。全程未 push、未 merge、未 release，未改动主工作区代码。

## 一、结果

| 口径 | 失败 | 通过 | 跳过 | error | 耗时 |
| --- | --- | --- | --- | --- | --- |
| 官方 0.3.37 原样（pristine） | 222 | 4043 | 9 | — | 709s |
| 本分支开工时 | 205 | 4089 | 9 | 1 | 696s |
| 现在 | **134** | **4169** | 9 | 0 | 684s |

失败数 −71，通过数 +80，error 归零。两次全量都是同一台机器同一套依赖，命令 `python -m pytest core/tests`。

## 二、这一轮修掉的东西（每条都有失败复现和修复后通过）

### 1. 审批策略 `auto_approve` 从未被读取（真实产品缺陷）

`ApprovalGate.check` 判定「要不要问人」时只看操作等级和免问线，完全没有读 `self.approval_policy`。结果 `auto_approve` 和 `require` 两种策略给出逐字相同的判定：会话处于自动批准状态时，任何 2 级操作仍被判「需要确认」，随后被 `CoreToolbox._execute_existing` 以「未经过等待请求」硬拒。

- 修复前：`write_file` 在 `auto_approve` 下判定 `requires_approval=True`，执行返回 `blocked`。
- 修复后：`auto_approved=True`，执行返回 `ok`。
- 边界：自动批准只覆盖到 `auto` 档的免问线（2 级），3 级破坏性操作仍然要问。这一条是回归测试逼出来的——我第一版写成「策略是 auto_approve 就一律批准」，立刻打挂了 `test_full_access_command_approval` 里 5 条，说明 3 级不能放过。

### 2. `sub_agent` 被重复设卡（配置自相矛盾）

`DEFAULT_TOOL_PERMISSIONS` 声明 `sub_agent` / `sub_agent_message` 是 `auto_allow`，`access_tools.jsonc` 也把它授给 `read_only` 档，但操作等级表把它定成 2 级。闸门里等级表说话，于是：默认「ask」档下每次派子任务都弹确认，`read_only` 会话里直接硬拦——那条授权等于废纸。

改判为 1 级。这不是放宽：子代理是用父级的 `approval_policy`、`permission_preset`、`active_tier` 造出来的（`sub_agent_runner._build_toolbox`），它真正要做的每一步都在自己的闸门里重新判级，启动处再问一次挡不住任何东西。

### 3. 内核反向依赖 app 层（分层违规）

`kernel/loop.py` 直接 `from lamtools_core.app.tool_freeze import ...`，被 `test_kernel` 的分层守卫抓住。`tool_freeze.py` 只有 123 行、只用标准库，已移到 `runtime/tool_freeze.py`（内核本来就用 `runtime.execution_guard`），四处引用一并更新。

### 4. 过期契约对齐（产品侧有明确决定，测试没跟上）

- **MCP 迁移**：`mcp_tool` / `mcp_activate` 已随「把 MCP 从 toolbox 里拿出去、通过 command 运行」下线，入口只剩 `mcp`（action=run）。`test_default_toolbox` 里 5 条还在断言旧网关。
- **consider 模式边界改机制**：只读边界改成「操作一级上限」而不是按工具名删，所以报错文案是能力上限而不是模式提示；同时补了一条「只读命令在同模式下仍可用」的断言，比原来只断言被拦更严格。
- **常驻原话附录取消**：`controller.py` 里写着「用户消息那个也许可以取消？——取消最多 50 条原话的常驻附录，当前请求保留原角色，历史原文由召回工具按需读取」。测试仍在找 `## Recent user messages`。
- **最新用户消息改为原角色保留**：`planner` 的文档写明「the latest user request remains a user message」。测试仍在断言它被折成编号条目、`retained_count == 0`。
- **压缩测量统一口径**：代码注明「压缩的数值只应该使用一种权威值」，触发不再分快慢两路，短请求的测量也是 exact。
- **无收益压缩改报 `not_needed`**：原来报 `compacted` 却一条都没压，现在如实报。
- **更新源改 GitHub 优先**：`checker.py` 注明「尽快摆脱对官网的依赖」，官网降为兼容回退。
- **插件打包边界**：排除清单从 1 个长到 4 个、必需的 `git` 插件已删除，测试还钉着旧字面量。现在改为解析清单，并交叉校验本地脚本与 CI 完全一致，另加「不能既必需又排除」的判定。

## 三、测试数

- 新增 2 条：`DEFAULT_TOOL_PERMISSIONS` 与 `OPERATION_LEVELS` 的一致性不变式（能抓住第 2 类缺陷）、`sub_agent` 启动不需要审批（含 read_only 档）。
- 改写到当前契约：`test_default_toolbox` 12 处、`test_tool_approval` 5 处、`test_plugin_packaging_boundary` 3 处、`test_context_compaction` 11 处、`test_kernel` 5 处。
- 没有删除任何测试；断言强度只升不降（例如把「英文文案包含某句」改成对 `allowed / requires_approval / permission_tier / level / auto_approved` 的结构化断言）。

## 四、新发现的架构问题

1. **闸门只看等级，声明权限成了死数据**。`tool_permissions` 里除 `HARD_BLOCK` 之外的值（`auto_allow` / `ask_user`）在 `check()` 里从不参与判定；`access_tools.jsonc` 的档位放行名单被一路透传到闸门却从没被读过。两份配置对同一件事各自表态，实现只认第三份（等级表）。这次 `sub_agent` 的矛盾就是它的直接产物。
2. **`kernel/loop.py` 的 `_summary_recent_user_messages` 是死代码**。半截重构：近期用户原话塞进了消息 metadata，但没有任何调用点把它渲染回请求。
3. **压缩 fitter 拿「整请求」估算去比「消息」预算**。`_estimate_tokens` 含工具数组等固定开销，目标值却是消息口径。实测：`context_window=2000`、`compaction_limit_ratio=0.6` 时目标 1200，而策略全部穷尽后仍停在 1520，整轮直接 `failed`。
4. **小窗口会话会整轮失败**。压缩指令本身就有 1278 校准 token（实测），目标低于这个数时压缩必然失败，而失败会连带整轮 `failed`——不是降级，是不可用。

## 五、没做完的，以及为什么

### 阻塞项：需要你拍板

- **压缩上限口径**（影响 `test_context_compaction` 2 条 + `test_kernel` 9 条）。要么让 fitter 的预算扣掉工具固定开销，要么让小窗口会话降级而不是整轮失败，要么认定这类窗口不支持。三条路都改产品语义，我不替你选。
- **分段请求超过声明的输入上限**（`test_compact_context_segments_oversized_history_within_model_input_limit`）。实测 `input_limit_tokens=1200` 时实际发出 1491 与 2961 token 的请求。代码注释的理由是「本地估算只决定断点、不决定段数」，我没找到判断谁对的确证。
- **更新源优先级**（`test_update_check` 8 条）。产品已改为 GitHub 优先，测试还断言官网优先且「不许联系 GitHub」。是重写这 8 条到新契约，还是把产品改回官网优先，需要你定。

### 待办：没阻塞，只是还没轮到

`test_core_live`(8)、`test_core_sub_agent_runner`(7)、`test_core_cli`(7)、`test_attachment_service`(6)、`test_plugin_system_live_agent`(5)、`test_core_checkpoint_graph`(5)、`test_office_renderer_cli`(4)、`test_network_exploration`(4)、`test_bundled_plugins`(3)、`test_context_compaction_step_tail`(3)、`test_goal_dispatch_queue_boundaries`(3)、`test_review_runtime_contracts`(3)，以及各自 1–2 条的长尾。这些这一轮只做了文件名分组，还没逐条定性。

### 验收项状态

- 全量 0 failed：**未达成**（134）。
- 1000 次有效强杀：已跑完（1000/1000 有效、0 孤儿、0 超时、全程无降级 `taskkill /F`、恢复中位数 1.27s），但那是更早的提交，**不覆盖现在的代码**，需要在最终 SHA 上重跑。
- 24h Soak：仍在跑（pid 42976，`.lam/soak24.log`），未到结算点。
- fail-closed、副作用专项、资源主动释放：未开工。

## 六、提交

23 个提交，全部在本分支，都可单独回退。本轮新增 6 个：

```
b4ae8271 test(kernel): align compaction assertions with the appendix-free, retain-latest design
6dac4edc refactor(kernel): move tool_freeze out of the app layer
9b0354cb test(compaction): align context-compaction expectations with the current design
87dc3897 test(packaging): parse the plugin boundary lists instead of pinning loop text
dcda6fcb test(approval): assert decision fields instead of localized reason text
ddfab61d fix(tool): decline-to-ask policy was never read, and sub_agent was double-gated
```

工作树里还有非我产生的改动（`.agents/skills/impeccable/*` 等），全程没有纳入提交。

## 七、下一步

1. 你拍板上面三个阻塞项，我按其中一条推进并把对应测试改到新契约。
2. 继续逐簇清理待办里那批（`test_core_live`、`test_core_sub_agent_runner`、`test_core_cli` 优先，都是 7–8 条）。
3. 全部收敛后冻结 SHA，依次重跑：全量、定点竞态注入、1000 次强杀、24h Soak，并把结果写进验收表。
