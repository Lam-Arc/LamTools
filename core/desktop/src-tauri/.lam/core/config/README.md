# LamCore 配置说明

安装后在 LamCore.exe 同目录下出现 `.lam/core/config/` 文件夹。
修改这里的文件即可自定义 Agent 行为，无需重新打包。

## 配置文件

| 文件 | 用途 |
|------|------|
| `loadtools.jsonc` | 控制各模式下 Agent 可用哪些工具 |
| `access_tools.jsonc` | 控制工具权限审批规则 |
| `hooks.json` | 事件钩子（工具前后执行自定义操作） |
| `mcp.json` | MCP 服务器配置（扩展工具） |

## 使用方法

1. 打开要修改的配置文件
2. 参考文件内的注释修改
3. 保存后重启 LamCore 即可生效

## 自定义技能

在 `.lam/core/skills/` 下创建子目录，放入 `SKILL.md` 文件。
Agent 会自动发现并使用。

示例：
```
.lam/core/skills/translator/SKILL.md   → 翻译技能
.lam/core/skills/reviewer/SKILL.md     → 代码审查技能
```

## 自定义插件

将插件文件夹放入 `.lam/core/plugins/`，包含 `plugin.json` 清单文件。
