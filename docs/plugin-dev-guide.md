# LamTools 插件开发指南

> 配套：`docs/plugin-system-rework.md`（需求）· `docs/plugin-compat-matrix.md`（社区兼容）
> 会话内引导：加载 `create-plugin` skill 生成骨架；加载 `plugin-manager` skill 管理安装。

## 1. 插件是什么

插件 = 一个含 `plugin.json` 的目录，是**唯一安装单元**。一个插件可含任意组合：

| 资产 | manifest 字段 | 说明 |
|---|---|---|
| 技能 | `skills` | SKILL.md 目录（Claude Skills 事实标准） |
| Hooks | `hooks` | 事件钩子（command/http/mcp/prompt 四类） |
| MCP | `mcpServers` | 外部 MCP server 配置 |
| **原生工具** | `tools` | **进程内 Python handler**（本系统一等公民） |
| 依赖 | `dependencies` | pip 包（装入 core 运行环境，同一 interpreter） |
| 配置 | `configSchema` | 驱动插件配置表单的 JSONC schema |

插件可以只含技能、只含 Hooks、只含 MCP——不必有工具。

## 2. manifest 全字段

```jsonc
{
  "name": "my-plugin",              // 必填：唯一名（目录名约定）
  "version": "0.1.0",               // 必填：语义化版本
  "description": "一句话描述",
  "manifest_version": "1",          // 缺省 1；未知版本拒绝加载（`x-*` 键透传保留）
  "skills": ["./skills"],           // ./ 相对路径，不得逃出插件根
  "hooks": ["./hooks/hooks.json"],
  "mcpServers": ["./mcp/mcp.json"], // 可选
  "tools": ["./tools/tools.jsonc"], // 可选：原生工具清单
  "dependencies": ["sqlite-vec>=0.1.9"], // 可选：pip 依赖（PEP 508）
  "configSchema": "./config/schema.jsonc" // 可选：配置 schema
}
```

所有 `./` 路径强制以 `./` 开头且解析后必须仍在插件根内（越界拒绝加载）。

## 3. tools.jsonc（原生工具）

```jsonc
{
  "tools": [
    {
      "name": "rag_search",                 // 全局唯一（与 core/MCP/其他插件冲突 → 不可用）
      "description": "在已索引文档中检索",
      "input_schema": {                     // JSON Schema（object）
        "type": "object",
        "properties": { "query": { "type": "string" } },
        "required": ["query"]
      },
      "output_schema": {},                  // 可选
      "permission": "auto_allow",           // auto_allow | ask_user | hard_block（缺省 ask_user）
      "category": "rag",                    // 可选（缺省 plugin）
      "visibility": "on_load",              // always | on_load（缺省 always）
      "skill": "rag-for-agent",             // visibility=on_load 必填：随该 skill 加载暴露
      "handler": "rag_engine.tools:rag_search", // 必填：module:function 动态导入入口
      "timeout": 30                         // 可选：执行超时（秒）；不声明 = 不限
    }
  ]
}
```

### handler 契约

```python
# 插件内模块（core 运行环境可导入；必要时把插件目录加入 sys.path）
async def rag_search(call) -> ToolResult:
    # call.id / call.name / call.arguments（dict）
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="ok",          # ok | failed | blocked | skipped
        content="结果文本（回喂模型）",
        error="",             # failed 时必填可读错误
        metadata={},
    )
```

- 预期失败返回 `status="failed"` + 清晰 `error`——模型看到错误可自纠。
- handler 导入失败 = 工具不可用（执行返回 Unknown tool），装配期错误记录在 `_plugin_handler_errors`。
- 声明了 `dependencies` 但缺失时：工具注册**占位 handler**，返回明确错误附安装命令（不静默降级）。

### 权限模型（三层，skill 工具无法绕过）

1. **逐工具 PermissionTier**：`auto_allow` 免审 / `ask_user` 每次确认（安全默认）/ `hard_block` 不注入。
2. **access_tools.jsonc 档位**：`read_only` / `limited_edit` / `full_edit` 各配 access 列表——插件工具按档位进出（列表内有→免审，无→需审批）。
3. **ApprovalGate 硬规则**：路径边界 / 敏感文件 / 危险命令对插件工具参数照打。

用户可在权限设置中**升降级覆盖**插件工具的 permission（`{data_dir}/tool_permissions.jsonc`，覆盖优先于 manifest；显式禁用的工具不可被覆盖解禁）。

## 4. 安全模型

- **插件 = 可执行代码**：handler 在 core 进程内运行，可读写本机文件与配置（含明文 `providers/*.jsonc` API key）。**安装即永信**——安装动作 = 显式信任门，插件更新自动跟随；只从可信来源安装。
- 插件声明的 **hooks 保持逐条 sha256 信任**（与工具"安装即永信"两条线并存；`hook.trust_all` 不开放）。
- pip 依赖装入 core 运行环境（`sys.executable -m pip`）：安装前 dry-run 冲突检测（覆盖已装包即拒装并回滚），安装清单记录，卸载按清单回滚（多插件共用依赖保留）。

## 5. 生命周期

| 操作 | 入口 | 说明 |
|---|---|---|
| 安装 | UI 插件页 / `plugin.install` / `cli plugin install` | 本地目录 / zip / GitHub Release URL / CC / Codex 适配；复制到插件根（默认用户级）|
| 更新 | 重装即更新 | 对已存在插件 install = 覆盖旧目录 |
| 启用/禁用 | `plugin.enable/disable` | **即时生效**（下一轮模型可见列表即变） |
| 卸载 | `plugin.uninstall` | 删目录 + 可选清依赖（默认保留）；清理该插件 hook 信任与配置 |
| 依赖 | `plugin.deps-status` / `plugin_install`（模型工具） | 已装/缺失/版本不符 + 安装命令提示 |
| 配置 | `plugin.config.get/update` / `cli plugin config` | `{data_dir}/plugins/<name>.jsonc`，configSchema 校验 |

内置插件（git / websearch / imagegen）：包内只读资源，**可禁用、不可卸载**；声明外移为插件，
handler 由 core 显式装配（半声明式 tools.jsonc 引用 core 常量按名补全）。

## 6. 模型侧引导

- **plugin-manager skill**：会话内自然语言安装/管理插件（模型调 `plugin_install` 工具，安装需用户审批）。
- **create-plugin skill**：按描述生成插件骨架（manifest/tools.jsonc/handler）+ 本地安装验证。
- CLI 直通：`cli plugin list/install/uninstall/enable/disable/deps-status/config get|set`（GUI 能力必有 CLI）。

## 7. 内置插件开发（半声明式）

内置插件 tools.jsonc 只声明 `name` + `handler`，`description`/`input_schema`/`category`/
`failure_modes`/`recovery` 从 core 常量（`default_toolbox.bundled_core_tool_specs`）按名补全；
handler 由 core 显式装配（`_bundled_plugin_handler` 按工具名查表），不走动态导入。

## 8. 测试

`core/tests/test_plugin_*.py` 覆盖：声明解析 / spec 补全 / 注入与执行 / 惰性暴露 /
冲突 / timeout / 导入失败 / 依赖缺失占位 / 权限档位 / 安装卸载配置全链 / 适配器翻译。
新插件建议自测：安装 → `plugin.list` 确认工具 → 按 visibility 验证可见性 → 执行 → 卸载。
