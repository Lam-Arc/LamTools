# LamTools CLI and opencode Alignment

日期：2026-06-05

## 结论

当前 LamTools 还没有统一 CLI。根目录只有 `scripts/dev.ps1`、`scripts/build.ps1`、`scripts/test.ps1`、`scripts/scaffold-member.ps1` 四个维护脚本；Writer 有较完整的 `writer_cli`；Artist 仍是产品专用的 `artist` CLI。

建议新增根入口：

```powershell
writer run 任务描述
artist run 任务描述
writer resume <session-id> 继续描述
artist resume <session-id> 继续描述
writer session list
artist session list
lamtools dev writer all
lamtools build Artist
lamtools test core
lamtools scaffold member -Id editor -Name LamEditor
```

其中 `[member] run <task...>` 是主语义，`[member]` 直接替换为 `writer`、`artist` 等成员名。它不替代成员自身业务 CLI，只负责统一入口、路径、参数、输出格式和编码。未来可在其上增加 `lam run <task...>` 智能路由层。

## 现有 LamTools 入口

| 入口 | 现状 | 问题 |
|------|------|------|
| `scripts/dev.ps1` | 支持 `core/writer/Artist/all` 和 `backend/frontend/all` | 是维护脚本，不是统一 CLI |
| `scripts/build.ps1` | 构建三套前端 | 不覆盖后端打包 |
| `scripts/test.ps1` | 跑 core/writer/Artist 测试 | 没有 e2e/pipeline/unit 分层参数 |
| `scripts/scaffold-member.ps1` | 生成新成员骨架 | 生成后还要手动改 dev/build/test |
| `writer_cli` | 有 run/resume/watch/session/agent/tool/debug | 只服务 Writer |
| `artist` | 有 session/image/ct/mock/provider 等 | 参数形态和 Writer 不一致 |

## opencode CLI 清单

| opencode 命令 | 用途 | LamTools 是否吸收 | 改造方式 |
|----------------|------|------------------|----------|
| `opencode [project]` | 进入 TUI | 暂不吸收 | LamTools 目前是产品 Web UI，不做根 TUI |
| `opencode run [message..]` | 一次性任务 | 吸收 | `[member] run <task...>`，例如 `writer run ...` |
| `opencode run --continue` | 继续最近会话 | 吸收 | `[member] resume --last <task...>` |
| `opencode run --session <id>` | 指定会话继续 | 吸收 | `[member] resume <session-id> <task...>` |
| `opencode run --fork` | fork 会话 | 暂缓 | Writer/Artist 需要先统一会话分支语义 |
| `opencode run --share` | 分享会话 | 不吸收 | 本地产品不需要 |
| `opencode run --model` | 指定模型 | 吸收 | 根 CLI 透传为成员标准参数，成员自行解释 |
| `opencode run --agent` | 指定 agent | 部分吸收 | Writer 可用；Artist 暂时映射到 artist 模式或忽略 |
| `opencode run --format json` | 机器可读输出 | 吸收 | 所有 `[member] run` 支持 `--format text/json` |
| `opencode run --file` | 附件 | 吸收 | 统一为 `--file <path>`，Writer/Artist 分别映射附件/参考图 |
| `opencode run --title` | 会话标题 | 吸收 | `--title` |
| `opencode run --dir` | 工作目录 | 吸收 | `--work-root` 和 `--dir` 做同义参数 |
| `opencode run --interactive` | 交互模式 | 暂不吸收 | Writer 不再保留 TUI 旁路；交互走产品 Web GUI，CLI 保持非 TUI |
| `opencode attach <url>` | 连接远端 server | 暂不吸收 | 当前后端固定本地端口，先用 `--base-url` |
| `opencode serve` | 无头服务 | 不吸收 | LamTools 服务由各成员 FastAPI 承担 |
| `opencode web` | 启动 Web | 吸收 | `lamtools open <member>` 或 `lamtools dev <member> all --open` |
| `opencode providers/auth` | Provider 凭据管理 | 部分吸收 | 映射到成员设置接口，先做 `[member] provider list/login` |
| `opencode models` | 模型列表 | 部分吸收 | Artist 已有供应商模型，Writer 需要统一配置后再接 |
| `opencode stats` | token/cost 统计 | 暂缓 | Core 已有 usage 雏形，可后续做 `lamtools usage` |
| `opencode session list/delete` | 会话管理 | 吸收 | `[member] session list/delete` |
| `opencode export/import` | 会话导入导出 | 暂缓 | 两个成员消息结构不同，需要先定义 Core session export schema |
| `opencode agent list/create` | agent 管理 | 部分吸收 | Writer 先支持 `[member] agent list/run`，create 暂缓 |
| `opencode mcp` | MCP 管理 | 暂缓 | Writer 有 MCP 模块，但还不是全成员能力 |
| `opencode completion` | shell 补全 | 暂缓 | CLI 稳定后再做 |
| `opencode debug` | 调试工具 | 部分吸收 | 做 `lamtools doctor`、`[member] health`，不暴露内部 debug 大树 |
| `opencode github/pr` | GitHub agent/PR | 不吸收 | 不属于 LamTools 产品维护入口 |
| `opencode plugin` | 安装插件 | 不吸收 | LamTools 新成员走 scaffold，不走插件 |
| `opencode db` | opencode SQLite 调试 | 不吸收 | 成员数据库各自管理 |
| `opencode upgrade/uninstall` | 管理 opencode 自身 | 不吸收 | LamTools 不是全局安装器 |
| `opencode acp` | Agent Client Protocol | 暂缓 | 后续如果 Core 提供 agent server 再考虑 |

## 推荐命令形态

### 根命令

```text
lamtools
  dev [core|writer|Artist|all] [backend|frontend|all]
  build [core|writer|Artist|all]
  test [core|writer|Artist|all] [--unit|--pipeline|--e2e]
  open [writer|Artist]
  doctor
  scaffold member ...
  member ...
```

### 成员命令

```text
writer run <task...> [--title] [--file] [--model] [--agent] [--format text|json] [--work-root]
writer resume <session-id> <message...>
writer watch <session-id>
writer session list
writer session new
writer health

artist run <task...> [--title] [--reference-image] [--image-count] [--compact]
artist resume <session-id> <message...>
artist session list
artist session new
artist image <prompt...>
artist ct <goal...>
artist health
```

### 成员映射

| 统一命令 | Writer 映射 | Artist 映射 |
|----------|-------------|-------------|
| `writer run 任务` | `py -3.14 -m writer_cli run 任务` | 不适用 |
| `artist run 任务` | 不适用 | `py -3.14 artist.py 任务` |
| `writer resume <sid> 消息` | `writer_cli resume <sid> 消息` | 不适用 |
| `artist resume <sid> 消息` | 不适用 | `artist.py session <sid> 消息` |
| `writer watch <sid>` | `writer_cli watch <sid>` | 暂无等价 |
| `writer session list` | `writer_cli list` | 不适用 |
| `artist session list` | 不适用 | `artist.py session ls` |
| `writer health` | `writer_cli health` 或 `/api/health` | 不适用 |
| `artist health` | 不适用 | `/api/health` |

## 实施顺序

1. 新增根 CLI 薄封装，先用 PowerShell 或 Python 均可。推荐 Python，因为要处理参数、JSON 输出、路径和编码。
2. 第一版只做 `dev/build/test/open/doctor` 和 `[member] run/resume/session list/health`。
3. 把 Writer 和 Artist 的运行差异留在 adapter 层，不改成员业务 CLI。
4. `[member] run` 默认文本输出；`--format json` 只输出统一 envelope：`member/session_id/status/events/result`。
5. 验证 Windows 中文任务描述：不要求用户加引号；CLI 内部用 argv join，并以 UTF-8 调子进程。
6. 第二版再补 `--file/--model/--agent/provider/models/usage/export/import`。

## 不建议做的事

- 不要把 opencode 的所有命令一比一搬进 LamTools。
- 不要继续新增散落的 `writer.ps1`、`artist.ps1`。
- 不要让用户进入 `members/writer` 或 `members/artist` 才能执行日常任务。
- 不要把 `[member] run` 直接绑死到 opencode；opencode 是外部工程助手，LamTools member 是产品运行入口。
