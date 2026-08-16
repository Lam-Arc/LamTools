---
name: plugin-manager
description: 插件 / 技能 / 钩子的统一管理入口——安装、更新、卸载、依赖管理、新建技能（SKILL.md）、安装技能、新建钩子（hooks.json）、安装钩子、创建插件（引用 create-plugin）。Use when the user asks to install, update, remove, enable, disable, or check dependencies of a plugin, to install or create a skill, to install or create a hook, or to manage plugin assets. No settings toggle needed — load this skill and act on demand.
---

# Plugin Manager

统一管理插件 / 技能 / 钩子：安装与新建都从这里按需调取，无任何开关。

## 插件是什么

插件 = 含 `plugin.json` 的目录，是**唯一安装单元**。一个插件可含任意组合：
`skills`（技能）/ `hooks`（钩子）/ `mcpServers`（外部 MCP）/ `tools`（原生工具）/
`dependencies`（pip 依赖）/ `configSchema`（配置）。插件可以只含技能、只含钩子。

## 安装插件

1. 确认用户要什么，从 `plugin_list` 看已装插件，或确认安装来源：
   - **local**：含 plugin.json 的本地目录
   - **zip**：本地 .zip
   - **url**：GitHub Release .zip 资产 URL
   - **cc / codex**：Claude Code / Codex 社区插件（自动翻译）
2. 调 `plugin_install`（source + path/url）——**需用户确认**（pip 可能运行）。
3. 成功回报名称/版本/依赖状态；依赖冲突会拒装并回滚。

## 更新 / 卸载 / 依赖

- **更新**：重装即更新（同 source 再 install 覆盖旧目录）。
- **卸载**：插件页或 CLI（`lamtools plugin uninstall <name>`）；依赖默认保留，共用依赖不卸。
- **启用/禁用**：禁用后工具下一轮即从模型可见列表消失、钩子停止加载。
- **依赖**：`plugin_deps` 查状态（缺失附安装命令）。

## 新建技能

用户要求"新建技能 / 写个技能 / 加个技能"时：

1. 与用户对齐技能用途、`name`、`description`。
2. 用 `write_file` 创建 SKILL.md（Claude Skills 事实标准）：
   - 项目级：`<work_root>/.lam/skills/<name>/SKILL.md`
   - 用户级：`~/.lam/skills/<name>/SKILL.md`
   - 开头 YAML frontmatter（`---` 包裹）：`name`（必填）+ `description`（必填，说明何时使用）
   - 正文：加载后应遵循的完整指引，自包含，相关文件用相对路径
3. 用 `load_skill` 立即验证可加载；告知用户技能已可用。
4. 若用户想分发：把技能包成插件（含 manifest）——见「创建插件」。

## 安装技能

技能随插件分发（插件可只含 skills）：

- 用户给了技能目录 / zip / URL → 按来源调 `plugin_install`，安装后该插件的技能自动进入技能列表（`skill.list` 可见）。
- 用户只想放单个技能文件 → 指导放入技能目录（项目 `.lam/skills/` 或用户级），刷新后可见。
- 验证：`plugin_list` / `skill.list` 确认技能在列且可加载。

## 新建钩子

用户要求"新建钩子 / 加个钩子 / 设置自动响应"时：

1. 确认触发事件与匹配工具。事件：`PreToolUse` / `PostToolUse` / `PostToolUseFailure` /
   `SessionStart` / `Stop` / `UserPromptSubmit` / `PermissionRequest`；matcher = 工具名或 `*`。
2. 用 `write_file` / `edit_file` 写 hooks.json：
   ```json
   {"hooks": {"<事件>": [{"matcher": "<工具名或*>", "hooks": [
     {"type": "command", "command": "...", "timeout": 10, "statusMessage": "..."}
   ]}]}}
   ```
   handler 类型：`command`（shell，stdin 收 JSON、stdout 返回 JSON 决策）、`http`、
   `mcp`、`prompt`（向模型注入附加上下文）。
3. **明确告知**：新建钩子需在钩子页逐条信任后才执行（未信任不执行——信任 = 授予命令执行权）。

## 安装钩子

钩子随插件分发（插件 `hooks` 资产，安装后自动加载，同样需逐条信任）：

- 含 hooks 的插件经 `plugin_install` 安装 → 钩子进入钩子列表 → 用户信任后生效。
- 或直接编辑 hooks.json（`.lam/core/config/hooks.json`）。

## 创建插件（完整插件，含原生工具）

用户要"开发/写一个插件"或带原生工具的插件时：**load `create-plugin` skill**——它提供
manifest 全字段、tools.jsonc schema、handler 契约、权限模型与生成→安装→验证工作流。

## 规则

- 安装 = 显式信任门（pip 可能运行）；**不替用户批准**。
- 新建/安装的钩子未信任不执行——必须明确告知。
- 技能与钩子都是插件的资产形态；安装单元始终是插件（无独立 skill.install / hook.install）。
- 不臆造不存在的插件；能力缺口建议用 `create-plugin` 生成。
