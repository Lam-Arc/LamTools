# MCP 命令与操作等级

user:“把 MCP 从 toolbox 里面拿出去，通过 command 运行”+(协议连接独立于模型工具列表，查询与执行分开)。
user:“工具权限是改成 123 级，不一棒子按工具类型打死了”+(按本次操作判断，而非按整个工具授权)。

## 查询与执行

模型只看到一个只读的 `mcp` 查询工具：`action=servers/tools/schema`，可带 `server_name`、`tool_name`。服务器工具不会再作为动态模型工具注入。

执行使用现有 `run_command`，例如：

```text
core mcp call --tool mcp__bilibili__search --arguments '{"keyword":"本地模型","days":3}'
```

宿主命令通道直接解析这条命令的参数，不经过 shell 展开；真实 CLI 同样提供 `mcp servers/tools/schema/call`，支持 `--work-root` 和显式 `--config`。协议握手、工具发现和连接回收由 `mcp/command_service.py`、`registry.py`、`client.py` 负责。主聊天、本地 CLI 代理和后台子代理使用相同通路。Hook 仍通过相同服务调用协议。

## 权限判定

先检查硬禁止，再取本次操作的等级，最后比较能力上限与免问线。

| 设置 | 数值 |
| --- | --- |
| ask / auto / full_access 免问线 | 1 / 2 / 3 |
| read_only / limited_edit / full_edit 能力上限 | 1 / 2 / 3 |

同一个 `run_command` 的 `git status` 是 1 级，普通构建是 2 级，删除、重置及无法静态判断的 shell 结构是 3 级。`arrange.list/get` 是 1 级，写动作是 3 级。超过免问线需要确认，超过能力上限直接拒绝；full 不会覆盖只读能力上限或硬禁止。`consider` 模式使用 1 级操作上限，允许只读命令。

等级表在 `tool/operation_levels.py`，数值比较不按具体级别分支。未登记操作默认 3。旧的工具名单、两档命令配置和权限字符串暂留兼容接口，授权以操作等级为准。审批选项“批准并信任”将精确操作的等级永久降低一级，最低为 1；设置页可查看并撤销，CLI 为 `core permissions trust list` 与 `core permissions trust revoke KEY`。信任账全局一份，键包含工作目录、命令原文或绝对目录，命令参数变化不会沿用旧授权；硬禁止不能信任。信任在能力上限比较之前生效。整期计划中其余工具合并不属于本次改动。

## 插件预声明 MCP 等级

新增服务器默认 3 级。插件可在安装的 MCP 配置中声明服务器默认值、单个工具值，或按工具的 `action` 再细分：

```json
{
  "mcpServers": {
    "example": {
      "command": "example-server",
      "level": 3,
      "toolLevels": {
        "search": 1,
        "save": 2,
        "delete": 3,
        "records": {
          "default": 3,
          "actions": { "list": 1, "update": 2, "delete": 3 }
        }
      }
    }
  }
}
```

声明来自安装配置；服务端返回的提示不会自动降低等级。0 表示硬禁止。等级必须是非负整数，不能用布尔值。查询 schema 会显示默认等级；执行时按实际参数重新判断。即使通过命令调用，也不将 MCP 调用误归为普通 shell 命令的 2 级。

## 连接、后台与安装

- 连接按需建立。后台每轮独占服务，不修改 runner 的共享激活集；受限运行档的 `mcpTools` 是精确白名单，command 不能借此执行其他 shell 命令。`skills` 由宿主预载全文。
- 模型用量与工具次数由单轮预算共同管理，耗尽终止循环。模型未返回用量时使用估算值。审批后恢复保留原运行档、已消耗预算、技能全文与 MCP 精确白名单。
- 调度窗口仅在成功后登记；失败有次数与间隔限制，等待确认不自动重试，夜间窗口跨午夜仍使用同一个日期。停止等待旧任务与连接回收。
- MCP 发布模板保持只读；`{{PLUGIN_DIR}}`、`{{PLUGIN_PYTHON}}` 在 JSON 解析后展开，依赖放在插件 `data/venv`，升级不需要重写模板。FastMCP 使用 `json_lines` 传输。

## 本次验收

新增相关后端测试 60 项、界面测试 5 项全部通过，未运行全量测试。覆盖真实 stdio / FastMCP 服务、主聊天命令调用、CLI 与常见启动别名、插件等级声明、模式与能力上限、信任跨聊天持久复用及撤销、子代理审批恢复、模型与工具预算终止、并行工具清理、调度失败恢复与跨午夜窗口，以及 Wiki / 卡片墙 / 转写。另通过 Python 源码检查、修改组件的 Vue 编译检查、卡片脚本语法检查和差异空白检查。
