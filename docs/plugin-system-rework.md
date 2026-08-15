# 插件系统改造需求（专项会话交付文档）

> 日期：2026-08-14
> 状态：需求已共识，等待专项会话实施（本仓库不实施）
> 目标：把 LamTools Core 插件从"声明式外围"升级为"一等公民"——工具 / 依赖 / UI / CLI 全链路，
> 为 RAG 等重量级原生插件（见 `rag-plugin-design.md`）铺路。
> 前置：本需求落地完成后，再开启 RAG 插件化处理。

---

## 0. 现状基线（改造前的客观事实）

插件系统全部源码位于 `core/src/lamtools_core/plugins/`（`models.py` / `registry.py` / `hook_config.py` /
`engine.py` / `trust.py` / `operations.py`），接线点在 `app/base_agent.py`、`app/default_agent.py`、`kernel/loop.py`。

| 项 | 现状 |
|---|---|
| manifest 字段 | `name / version / description / root / enabled / skill_roots / hook_files / mcp_files / permissions(无消费方) / raw`（`plugins/models.py:32-43`） |
| 插件位置 | 用户级 `APPDATA/LamTools/plugins`（`registry.py:25-30`）、项目级 `{work_root}/.lamtools/plugins`（`:33-34`）、内置 `core_plugins_root()` = `{exe_dir}/.lam/core/plugins`（`config/root.py:114-116`） |
| 发现 | `root.glob("*/plugin.json")` 一层深（`registry.py:82-98`）；路径强制 `./` 开头且不得逃出插件根（`:131-144`） |
| 启用状态 | `{data_dir}/plugins.json` → `PluginStateStore.is_enabled`（`registry.py:37-69`），默认启用 |
| 工具通道 | **只有 MCP**：`mcpServers` → `mcp_files` → `MCPToolRegistry.tool_specs()`（`mcp/registry.py:89-107`）→ 注入 `default_toolbox.py:750-752,776`。无原生 ToolSpec 声明通道 |
| 依赖管理 | **不存在**。无 install / pip / requirements 任何基础设施 |
| hooks | 四级加载（统一配置目录 → 项目 → 旧式用户 → 启用插件的 hook_files，`hook_config.py:44-74`）；逐条 sha256 信任（`trust.py`），未信任不执行（`engine.py:35-37`） |
| skill 联动 | `assemble_core_agent_plugins` 收集 `skill_roots`（`base_agent.py:893-898`）→ `SkillRegistry(explicit_roots=...)`（`default_agent.py:1875-1879`） |
| operation | 14 个：`plugin.list/enable/disable`、`hook.list/trust/untrust/delete/config.get/config.update`、`websearch.config.get/update`、`skill.list/enable/disable`（`operations.py:328-341`） |
| CLI | **无** `plugin` / `hook` / `skill` 子命令（`cli.py` 子命令清单 :679-903） |
| UI | CoreSettings 12 tab，**无"插件"tab**；Skills tab 挂 `CoreSkillsEditor.vue`、Hooks tab 挂 `CoreHooksEditor.vue`（`ui/src/components/CoreSettings.vue:724-734`） |

## 1. 目标与关键约束

**目标**：插件可以声明原生工具（带独立权限）、声明 Python 依赖（可安装）、有完整管理 UI 与 CLI，
插件资产（skills / hooks）统一在插件页管理。

**关键约束（本需求的硬前提）**：插件工具在 core 进程内运行，**依赖必须装入 core 运行环境
（同一 interpreter，当前 `py -3.14`）**——这是 RAG 插件 handler 复用 llm 栈（adapter / 模型重试 /
profiling）的前提，也是"原生工具路线"优于"MCP server 路线"的决定性理由。

**设计原则**：模式全部照抄现成先例（MCP 工具注入 / workflow 动态工具 / hook 四级加载），
不做新架构；改动是定点扩展。

## 2. manifest 扩展（`plugins/models.py:32-43` + `registry.py:100-129`）

新增三个字段，`_paths()` 越界校验（`registry.py:131-144`）同规则适用于新路径字段：

```jsonc
{
  "name": "lamtools-rag",
  "version": "0.1.0",
  "description": "Agent RAG 插件",
  "skills": ["./skills"],                 // 既有
  "hooks": ["./hooks/hooks.json"],        // 既有
  "mcpServers": "./mcp/mcp.json",         // 既有（可选）
  "tools": ["./tools/tools.jsonc"],       // 新增：工具清单
  "dependencies": ["sqlite-vec>=0.1.9"],  // 新增：pip 依赖
  "configSchema": "./config/schema.jsonc" // 新增：插件配置 schema
}
```

`tools.jsonc` 每个工具声明：

```jsonc
{
  "name": "rag_search",
  "description": "在已索引文档中检索（支持 char/context/page 维度）",
  "input_schema": { /* JSON Schema */ },
  "output_schema": { /* JSON Schema */ },
  "permission": "auto_allow",        // PermissionTier: auto_allow | ask_user | hard_block
  "category": "rag",
  "visibility": "on_load",           // on_load=对应 skill 加载后才暴露给模型 | always=常驻（默认）
  "handler": "rag_engine.tools:rag_search"  // 插件内 python 模块:函数入口
}
```

- `permission` 字段需要消费（现状 `PluginManifest.permissions` 是全仓库无消费方的占位符——**决策：新增
  的逐工具 permission 即消费形态，旧的 manifest 级 `permissions` 字段废弃或显式移除**，二者取其一，不可并存）。
- handler 指向插件内 python 模块，**插件 = 可执行代码**：安装时需显式信任提示（与 hook 逐条信任同语义）。

## 3. 工具注册链路（原生 ToolSpec 注入）

四个定点改动，MCP 注入先例照抄：

1. **收集**：`assemble_core_agent_plugins()`（`app/base_agent.py:893-898`）在收集 `skill_roots` 的同一循环
   收集 `tool_specs`（仅 enabled 插件、仅存在的路径）。
2. **装配**：`_build_core_runtime_toolbox()`（`app/default_agent.py:1949-1969`）把 `plugin_tool_specs`
   与 `mcp_tool_specs` 并列传入 `build_core_toolbox()`。
3. **注入**：`CoreToolbox.__init__`（`tool/default_toolbox.py:750-776`）两处合并逻辑与 mcp_tool_specs 相同：
   permission 进 `tool_permissions`、spec 进 `_specs`。
4. **handler 注册**：`_build_handlers`（`tool/default_toolbox.py:777-787`）注册插件 handler
   （动态导入 `rag_engine.tools:rag_search`，按函数名解析；导入失败 = 该工具不可用并在 plugin.list 报状态）。

权限语义（沿用既有三层，skill 工具**无法绕过**）：

- `ApprovalGate.check`（`tool/approval.py:169-258`）：路径边界 / 敏感文件 / 危险命令对插件工具参数照打；
- `access_tools.jsonc` 档位：read_only / limited_edit / full_edit 各配 access 列表，插件工具按档位进出；
- loadtools 模式裁剪（`tool/default_toolbox.py:818-854` `model_tools`）继续生效。

## 4. 惰性暴露（工具可见性跟随 skill 加载）

- `visibility: "on_load"` 的工具在对应 skill 加载前**不进入模型可见工具列表**（MCP 激活过滤同款
  语义，`tool/default_toolbox.py:844-853` 先例），解决"工具集膨胀"问题：加载前零变化，加载后全套生效。
- 状态来源：`load_skill` handler 已有的 `loaded_skill_roots` 追踪（`tool/default_toolbox.py:1046-1050`）。
- 可见性只影响模型侧；权限判定在**执行时**（`prepare_call` → `ApprovalGate`），二者解耦。
- `load_skill` 本身保持 AUTO_ALLOW（加载协议文档不审批），插件工具权限独立声明，不继承。

## 5. 依赖管理（新能力）

- 新增 operation：`plugin.install` / `plugin.uninstall` / `plugin.deps-status`（`plugins/operations.py`）。
- `plugin.install`：读 manifest `dependencies` → pip 子进程安装到 core 运行环境（同一 interpreter，
  满足 §1 硬约束）→ **需审批**（PermissionRequest / ASK_USER 语义，pip 是可执行操作）。
- 依赖状态（已装 / 缺失 / 版本不符）进 `plugin.list` 返回，UI 展示安装按钮。
- `plugin.uninstall`：禁用插件 + 可选卸载依赖（默认保留，提示用户）。
- 失败恢复：pip 事务失败返回错误与回滚提示，不置插件为损坏状态。
- 插件启动时依赖探测：缺失 → 插件工具 handler 返回明确错误（附安装命令），不静默降级。

## 6. 插件管理 UI（新增"插件"页）

- 入口：CoreSettings 新增"插件"tab，与现有 tab 并列；**Skills 与 Hooks tab 迁入插件页**
  （作为插件资产视图；系统级 skill / hook 管理入口保留），UI 现有路径需零回归迁移。
- 能力清单：插件列表（来源 / 版本 / 启用状态 / 依赖状态）/ 安装（本地目录 / zip / GitHub Release URL）/
  卸载 / 启用禁用 / 依赖安装按钮 / 插件配置编辑（`configSchema` 驱动的表单）。
- RPC 全接通：现有 `plugin.list/enable/disable` + 新增 `plugin.install/uninstall/deps-status`，
  经 operation catalog 总线（`live_router.py:470-516`，桌面 UI `ui/src/appServer/client.ts` 直通）。

## 7. 已知缺口修补清单

| # | 缺口 | 现状定位 | 要求 |
|---|---|---|---|
| 1 | skill 禁用不生效 | `SkillStateStore.is_enabled` 只在 `skill.list` 显示层使用（`operations.py:296`），`load_skill` / `SkillRegistry` 不查 | `load_skill` 对已禁用 skill 返回不可用 |
| 2 | `permissions` 字段无消费方 | `registry.py:127` 原样读入，全仓无消费 | 与 §2 决策一致：废弃或消费，二选一 |
| 3 | operation catalog 不扫内置插件根 | `default_core_agent_plugin_roots()`（`base_agent.py:918-929`）不含 `core_plugins_root()` | 统一扫描 |
| 4 | 插件无 CLI 子命令 | `cli.py:679-903` 无 plugin/hook/skill | 新增 `plugin list/install/uninstall/enable/disable/deps-status`（遵守"GUI 能力必有 CLI"） |
| 5 | `hook.trust_all` 白名单存在但未注册 | `operation_groups.py:51-65` 白名单含之，`operations.py:166-169` 刻意未注册 | **决策：保持逐条信任**（信任=任意命令执行），UI 提供批量逐条操作，不开放 trust_all |

## 8. 生态兼容性（设计原则 + 待调研）

**原则：标准格式互通，不追求二进制兼容。**

| 社区形态 | 例子 | 状态 |
|---|---|---|
| SKILL.md 技能（Claude Skills 事实标准） | anthropics/skills 生态 | ✅ 已天然兼容（`skills.py` 即此格式） |
| MCP server（工具行业标准） | 大量社区 MCP | ✅ 已天然兼容（插件 `mcpServers` 字段） |
| 私有 manifest / harness 插件 | opencode、DeepSeek harness 等各自格式 | ⏸ 适配器层（翻译到本 manifest），本期不做 |

- 设计上预留：manifest 版本号字段 + 扩展命名空间（`x-*` 键），保证后续加适配器不破坏已装插件。
- **待调研任务（专项会话可并行）**：DeepSeek harness / harness 类社区插件的实际形态
  （manifest 格式、安装方式、运行模型），输出兼容矩阵后再定适配器优先级。不臆测格式。

## 9. 验收与回归

1. 现有 14 operation + Skills/Hooks 两个 UI tab 迁移后**零回归**（RPC 契约与 UI 交互逐项核对）。
2. 新增"测试插件"端到端用例：声明 `tools` + `dependencies` → 安装 → 工具出现在模型列表（惰性暴露按
   visibility 验证）→ 执行 → 权限档位验证（read_only 不可用 / ASK_USER 触发审批）→ 卸载。
3. 插件开发指南文档（manifest 全字段 + tools.jsonc schema + 权限/安全模型）。
4. 新链路测试覆盖：handler 动态导入失败、pip 安装失败、依赖缺失探测三条失败路径。

---

## 附录：RAG 插件（本改造的第一个消费方）依赖本需求的能力清单

- manifest `tools` 字段 + 工具注入链路（§2、§3）
- **插件声明 operations（G 组，2026-08-15 增量需求）——`rag.sessions.search`（全局搜索 UI 直调）**
- 惰性暴露 visibility=on_load（§4）——rag-indexer / rag-for-agent 两类 skill 各自暴露自己的工具
- `dependencies` + `plugin.install`（§5）——sqlite-vec / fastembed 可选安装
- 插件 UI 页（§6）——安装 / 依赖状态 / 配置（embeddingSource / autoRoots）
- 缺口修补 #1（§7）——rag skill 可禁用

详细规格见 `docs/rag-plugin-design.md`。

---

## 共识决策（2026-08-14 专项会话增补，A-F 六组 39 项）

> 本需求经专项会话（2026-08-14）逐项探讨后达成共识，并已实现于 `core/`。
> 原文 §1-§9 不变；以下决策为对原文的增量/修正，实现以本清单为准。

### A 组 · 文档原文共识（9 项，逐条核验采纳）

A1 manifest 新增 `tools / dependencies / configSchema` 三字段
A2 tools.jsonc 工具声明（name/description/input_schema/output_schema/permission/category/visibility/handler，另增 `skill`/`timeout` 可选字段）
A3 工具注入 4 定点改动照抄 MCP 注入先例
A4 权限三层（PermissionTier + access_tools 档位 + ApprovalGate 硬规则），skill 工具无法绕过
A5 惰性暴露 visibility=on_load 跟随 skill 加载；load_skill 保持 AUTO_ALLOW
A6 依赖管理三 operation（install 需审批 / uninstall / deps-status）；依赖缺失 handler 报错附安装命令，不静默降级
A7 缺口 #1 load_skill 查禁用 / #3 catalog 统一扫内置根 / #4 新增 CLI / #5 hook.trust_all 不开
A8 生态兼容原则：标准格式互通（SKILL.md / MCP 天然兼容）
A9 验收四条（测试插件 e2e / 开发指南 / 三条失败路径 / 零回归）

### B 组 · 增量决策（11 项）

B1 补 `plugin.config.get/update`（RPC + CLI `plugin config get|set`），配置存 `{data_dir}/plugins/<name>.jsonc` 全局一份
B2 manifest 级 `permissions` 字段**显式移除**（models/registry 删除，全仓无消费方）
B3 pip 冲突保护：安装前 dry-run 冲突检测（覆盖已装包即拒装并回滚）、安装清单记录、卸载按清单回滚（多插件共用依赖保留）
B4 插件工具信任 = **安装即永信**（安装动作 = 信任门，更新自动跟随）；插件 hooks 保持现状逐条 sha256 信任（两套并存，trust_all 立场不变）
B5 卸载 = 删插件目录 + 可选按清单清依赖（默认保留）；禁用 = 只写状态
B6 UI：**插件与设置同级 + 插件/技能/钩子导航内页**（用户共识修正：插件独立于设置体系）——新建 PluginsShell 全屏页（与 CoreSettings 同骨架/同入口层级，入口在侧边栏「插件」按钮），侧边栏三内页：插件（CorePluginsEditor：列表/安装/详情资产/配置表单）、技能（CoreSkillsEditor：系统级 + 插件技能，按来源分组）、钩子（CoreHooksEditor：逐条信任）；设置内不再保留 Skills/Hooks tab（全部迁入插件页）
B7 安装 = 复制到插件根（默认用户级，可选项目级）+ GitHub 资产 sha256 校验（无校验和提示风险）+ zip 解压路径逃逸检查（is_relative_to + 条目/体积限额）
B8 工具名全局唯一：与已注入工具同名 → 不可用；插件间同名 → 先声明者保留、后者报冲突（plugin.list 标注）
B9 插件更新 = 重装即更新（覆盖旧目录）
B10 `plugin.list` 全量返回：来源/版本/启用/依赖状态（随 list 探测）/工具状态（含清单解析错误）/configSchema/已存配置
B11 `manifest_version` 本期加字段（缺省 1，未知版本解析报错）+ `x-*` 键透传

### C 组 · 生态与配套（2 项）

C1 本期实现 **Claude Code + Codex 适配器**（`plugins/adapters.py`，翻译产物走既有安装流程）+ 兼容矩阵调研报告（`docs/plugin-compat-matrix.md`，Harness 实测计划不臆测）+ opencode/OpenClaw MCP 化建议
C2 补缺口 #6：接通 hook `additional_context` 消费链（`format_tool_result_for_model` 拼接工具事件注入 + UserPromptSubmit 注入随历史持久化；原写入 `call.metadata` 后无人读）

### D 组 · 内置工具插件化（6 项）

D1 基础工具集定界 15 个：读(4)/写(2)/run_command/web_fetch/question/sub_agent/load_skill/checklist(2)/mcp_tool+mcp_activate
D2 三个内置插件 git（git_status/git_diff）、websearch（web_search）、imagegen（generate_image）：声明外移为包内插件（`plugins/bundled/`），handler 留 core 按名显式装配（半声明式：spec 从 `bundled_core_tool_specs` 常量按名补全）
D3 内置插件：包内只读资源（frozen 经 force-include 到 resources），默认启用、可禁用、**不可卸载**（uninstall 拒绝）
D4 浏览器自动化 = 既有 MCP 通道（playwright 等外部 server），已是插件形态，无独立 browser 工具
D5 websearch/imagegen 配置迁入插件 configSchema（`{data_dir}/plugins/<name>.jsonc`）：旧位置（`.lam/core/config/websearch.jsonc` / `imagegen.jsonc`）首次访问自动迁移（读旧写新，不删旧）；`websearch.config.get/update` 保留名称转发（RPC 契约零回归）；imagegen 的 settings namespace `core.imagegen` 经 `data_dir` 参数路由到插件配置；原 imagegen/websearch tab 并入插件页
D6 验收：默认装配可见工具 = 基础 15 + 内置插件 4；禁用内置插件 → 工具消失且调用返回不可用

### E 组 · 补充（7 项）

E1 插件启停**即时生效**（每轮 toolbox 重建 + assemble 按 enabled 过滤；执行侧 Unknown/Disabled 语义兜底，无需重启）
E2 tools.jsonc 可选 `timeout` 字段（执行侧 `asyncio.wait_for` 约束；不声明 = 长任务不限）
E3 插件工具权限默认 manifest 声明，用户可升降级覆盖（`{data_dir}/tool_permissions.jsonc`，覆盖优先；显式 disabled 不可被覆盖解禁）
E4 卸载清理该插件来源的 hook 信任记录与插件配置数据
E5 `plugin.config.update` 按 configSchema 校验值（轻量手写校验器，不引 jsonschema 依赖）
E6 manifest 损坏/解析失败在 `plugin.list` 报状态（discover_errors 收集，继续不阻断其他插件）
E7 插件工具调用进现有 audit/会话记录（execute 链路自然覆盖，S6 核对）

### F 组 · 持久化与模型侧引导（4 项）

F1 插件注册表统一 jsonc：`{data_dir}/plugins.json` → **`plugins.jsonc`**（load_jsonc + atomic_write_text，旧 json 兼容读 + 自动迁移写新，不删旧）；注册表条目含安装记录与依赖清单
F2 新增系统级 skill「**plugin-manager**」（`core/skills/plugin-manager/SKILL.md`）：插件形态/安装来源/规则；`plugin_install`（ASK_USER）/`plugin_deps`/`plugin_list` 三个模型可调工具（`plugins/manager_tools.py`，照抄 durable 骨架，审批走 ApprovalGate→loop 等待门→approval.respond 全链路）
F3 新增系统级 skill「**create-plugin**」（`core/skills/create-plugin/SKILL.md`）：manifest 全字段 + tools.jsonc schema + handler 契约 + 权限模型 + 生成→安装→验证工作流
F4 **插件 = 唯一安装单元**（manifest 可只含 skills / 只含 hooks / 只含 mcp / 组合），不单列 skill.install / hook.install

### 非本期演进方向（记录不实施）

插件间依赖（插件 A 依赖插件 B）、create-plugin 代码生成服务化、opencode/OpenClaw 源码翻译、Harness 适配器（实测后定）。

### 实现状态（2026-08-14）

- 后端全链落地：`plugins/`（models/registry/tools/deps/install/config_store/manager_tools/adapters/_jsonc/operations）+ `app/`（base_agent/default_agent）+ `tool/`（default_toolbox 注入/惰性暴露/占位 handler）+ `kernel/loop.py`（C2）+ `config/`（imagegen 迁移）+ CLI plugin 子命令 + UI 插件页（PluginsShell 与设置同级，插件/技能/钩子三导航内页；设置内不再保留 Skills/Hooks tab）。
- 测试：`tests/test_plugin_tools.py`（17）/ `test_plugin_lifecycle.py`（18）/ `test_bundled_plugins.py`（9）/ `test_plugin_adapters.py`（6）/ CLI 插件命令（2）——全量 1458+ 通过。
- 文档：`docs/plugin-dev-guide.md`（开发指南）· `docs/plugin-compat-matrix.md`（兼容矩阵）。

---

## 增量需求（2026-08-15，RAG 设计会话提出）：插件声明 operations（RPC 面）

**背景**：RAG 插件选定"全局搜索对话框（Ctrl+K，UI 直搜不经 agent）"作为会话历史搜索入口
（`docs/rag-plugin-design.md` §8.4）。**UI 不能直接调工具**（工具执行走 kernel/toolbox）——UI 直调
必须走 operation 通道。已实现插件系统（A-F 组）覆盖 tools/dependencies/configSchema，**无插件声明
operations 的能力——本项为新缺口**（G 组）。

### G 组 · 增量需求（4 项）

G1 manifest 新增 `operations` 字段（指向 `operations.jsonc` 或 python 模块:函数入口），解析/越界校验
规则与 `tools` 相同（`_paths()` 同套校验）。
G2 注册链路：`build_plugin_operation_catalog()`（`plugins/operations.py:88-342`）扩展——收集插件
operations → 注册进 operation catalog → UI 经现成 JSON-RPC 总线直调（`live_router.py:470-516`，
桌面 `ui/src/appServer/client.ts` 已通）；权限按工具同套 PermissionTier。
G3 信任语义同工具 handler（安装即永信，B4）；CLI 补 `plugin operations list`（"GUI 能力必有 CLI"）。
G4 消费方：RAG 插件 `rag.sessions.search`——与工具 `rag_search_sessions` 共用同一检索内核
（双出口单内核，`retriever.query(source="session_history")`）。

**验收补充**：测试插件声明 `operations` → JSON-RPC 直调 → 权限档位验证 → 卸载清理（与 §9 第 2 条合并执行）。

**优先级**：RAG 插件开发前必须（会话历史搜索入口依赖此通道）。

---

## 增量需求（2026-08-16，实测暴露）：安装-扫描不一致（H 组）

H1 **现象**：`plugin.install` 默认安装到**用户级根**（B7），但默认扫描链（`default_core_agent_plugin_roots`，
`include_user_plugins=False`）**不含用户级根**——UI 安装插件后 `plugin.list` 看不见、装配不加载。
实测：Tauri 后端插件页只显示 3 个内置插件，用户级安装的 `lamtools-rag` 不可见。
H2 **根因**：① `include_user_plugins` 默认 False；② Tauri 后端（`http_agent_app.py:178,319`）
`plugin_roots` 默认**空元组 `()`**（非 None）——`assemble`/`build_core_plugin_operation_catalog` 的
`plugin_roots is not None` 把空元组当"显式传空"，兜底只补内置根 + bundled，**项目级/用户级根全被排除**。
H3 **影响**：用户级/项目级安装的插件默认不可见（安装即消失）；dev 期规避 = 复制到内置根
`core_plugins_root()`（`core/.lam/core/plugins`，扫描链兜底保证存在）——lamtools-rag 已如此放置。
H4 **建议修复（专项会话）**：① 空 `plugin_roots` 回退默认根集合（`if plugin_roots` 而非 `is not None`）；
② 或装配默认 `include_user_plugins=True`（与 B7"默认用户级安装"对齐）；③ 修复后回归：安装→可见→可用
端到端用例补进验收清单；④ 明确"用户级插件默认启用"的隐私/安全语义（多项目共享 = 全局信任面扩大）。
