# CLI 与 GUI 功能入口优化方案（2026-06-29）

前置审查见 `docs/cli-gui-entry-audit-2026-06-29.md`。更高层的 Interface 去复杂化判断见 `docs/decomplexity-interface-review-2026-06-29.md`。本文目标不是继续加入口，而是把入口收敛成少数深接口：用户要记的少，后端实现可以多；CLI、GUI、HTTP 不再各自发明同一件事。

## 成熟产品参考

本方案参考 OpenAI Codex CLI 与 Claude Code 的公开做法，但不照搬。参考页：

- OpenAI Codex CLI reference: https://developers.openai.com/codex/cli/reference
- Claude Code CLI reference: https://docs.anthropic.com/en/docs/claude-code/cli-reference
- Claude Code product surface: https://claude.com/product/claude-code

- Codex 把 `exec`、`resume`、`doctor`、`delete`、`completion` 等稳定命令和 experimental/debug 命令分层，说明“诊断、调试、插件、MCP”不应和普通任务入口混在一起。
- Codex 非交互模式支持继续最近 run 或指定 session id，说明 `run/resume` 应成为自动化的一等入口。
- Claude Code CLI 区分交互会话、一次性 print/query、继续最近会话和恢复会话，说明任务入口不应该靠多个近义词堆叠。
- Claude Code 的 `/config` 与 IDE 扩展把设置、历史、计划审查放在 GUI 中，说明 GUI 应承载配置和可视化审查，CLI 应承载自动化和批处理。
- Codex/Claude 都把 hook/权限/设置做成可审查、可分层的配置，不直接散落在普通命令树里。

## 设计目标

1. **一个能力，一个主入口。** CLI 和 GUI 可以同时触达同一能力，但命名、状态、错误语义必须一致。
2. **Core 管通用维护，Member 管产品业务。** Core 不出现 Writer/Artist 业务动词，Member 不重复实现 dev/build/test/scaffold。
3. **普通入口少，开发入口深。** 普通用户只看到 run/resume/session/config/health；debug/tool/agent/hook/adapter 归入 developer 或 doctor。
4. **发送消息不等于启动任务。** `messages` 只表示持久化消息；Writer 任务启动走 app-server turn，Artist 任务启动走 `artist-turn`。
5. **CLI 与 GUI 共享操作目录。** 每个外部能力记录一次：能力名、所属范围、CLI 调用、GUI 位置、底层适配器、是否公开。

## 目标入口模型

### Core CLI：只做仓库与平台维护

推荐新增 `lamtools.cmd` / `lamtools`，作为仓库级入口。保留现有 `scripts/*.ps1`，但文档主推 `lamtools`。

```text
lamtools dev [core|writer|artist|all] [backend|frontend|all] [--open]
lamtools build [core|writer|artist|all] [--desktop]
lamtools test [core|writer|artist|all] [--unit|--contract|--e2e]
lamtools open [core|writer|artist]
lamtools doctor [core|writer|artist|all] [--json]
lamtools members list
lamtools scaffold member <id> --name <name> [--display-name <name>] [--capability <cap>] [--dry-run]
```

设计取舍：

- `lamtools dev/build/test/open/doctor/scaffold` 是 Core 指令，不进入 `writer` 或 `artist`。
- `lamtools open` 负责找到端口、检查后端、打开 GUI；不让用户猜端口。
- `lamtools doctor` 统一检查端口、Python/Node 版本、DB 可写性、后端健康、前端 dev server、配置缺失和旧入口残留。
- `scripts/*.ps1` 作为内部实现或兼容入口保留，不再作为主文档入口。

### Member CLI：只做产品能力

#### Writer

主入口：

```text
writer run <task...> [--work-root <path>] [--title <title>] [--model <model-id>] [--json]
writer resume [--last|<session-id>] <message...> [--json]
writer watch <session-id> [--json]
writer stop <session-id>
writer session list [--limit n] [--json]
writer session new [title] [--work-root <path>] [--json]
writer session show <session-id> [--json]
writer session messages <session-id> [--limit n] [--json]
writer session rename <session-id> <title>
writer session delete <session-id>
writer config providers list|add|edit|delete|test
writer config models list|add|edit|delete
writer config route set|get
writer health [--json]
```

兼容但不主推：

- `writer cancel` 作为 `writer stop` alias。
- `writer chat` 作为 `writer resume` alias。
- `writer quick` 作为 `writer run` alias。
- `writer list/new/status/result/messages` 作为旧形态保留一版，输出 deprecation 提示。

开发者入口：

```text
writer dev agent ...
writer dev tool ...
writer dev debug ...
writer dev app-server ...
```

这些命令默认不出现在普通 `writer --help` 首页，只在 `writer dev --help` 展开。

#### Artist

主入口：

```text
artist run <prompt...> [--title <title>] [--image-count n] [--image-size size] [--json]
artist resume [--last|<session-id>] <prompt...> [--json]
artist watch <session-id> [--json]
artist stop <session-id>
artist image <prompt...> [--image-count n] [--image-size size] [--json]
artist session list [--json]
artist session new [title] [--json]
artist session show <session-id> [--json]
artist session messages <session-id> [--json]
artist session rename <session-id> <title>
artist session copy <session-id> [--title <title>]
artist session delete <session-id>
artist config providers list|add|edit|delete|test
artist config models list|add|edit|delete
artist config defaults get|set
artist health [--json]
```

必须调整：

- 把 Artist 从位置参数式 CLI 改成 argparse subparser 或同等结构。
- `artist <prompt...>` 可以保留为 `artist run` 快捷，但帮助里只主推 `artist run`。
- `ct <goal>` 从 help 移除，除非补成真实稳定命令。
- `/generate` 标成 legacy，并把 GUI/CLI 全部指向 `/artist-turn`。

## GUI 信息架构

### 全成员通用

每个 member GUI 固定两层：

1. **Workbench `/`**：会话、输入、运行流、结果、验收。
2. **Settings `/settings`**：模型、Provider、默认值、权限、界面。

新增一个共享“命令面板”入口，用于承接 GUI 中不适合常驻显示的操作：

```text
Run task
Resume session
New session
Rename session
Delete session
Open settings
Health check
Open logs
Copy CLI command
```

命令面板不替代页面控件，只提供统一可发现性和“复制对应 CLI 命令”的桥梁。

### Writer GUI

需要补齐或收敛：

- 左侧会话重命名必须接线到持久化；如果不做，先隐藏重命名控件。
- 左侧会话删除补明确入口，并与 `writer session delete` 同语义。
- 右侧“改动审查、验收、分支、检查点”保留 GUI 主入口，CLI 后续补自动化命令。
- Provider/Model/Route 继续放 Settings，但操作名统一为“供应商/模型/用途分配”，避免 Provider 与 Model 混杂。
- `writer agent/tool/debug/message/step` 不进普通 GUI，只在开发者模式或 doctor 里显示。

### Artist GUI

需要补齐或收敛：

- 会话重命名接线；会话删除和复制明确入口。
- Provider/Model 统一叫“供应商/模型”，内部 `vendor` 不暴露给用户。
- 主输入继续走 `artist-turn`；移除对 `/messages` 触发任务的任何误导。
- long-task、lineage、billing、reference、dashboard 若保留，必须各自形成明确 GUI 入口；否则从公开文档中降级为内部/预留能力。
- “清除缓存”改名为“清除本机界面缓存”，避免用户误以为清除后端数据。

## 共享操作目录

新增一个轻量数据模块，不在第一阶段过度工程化：

```text
core/operations/
  catalog.schema.json
  core.json
  writer.json
  artist.json
```

每条记录描述一个能力：

```json
{
  "id": "writer.run",
  "scope": "member",
  "member": "writer",
  "visibility": "public",
  "category": "task",
  "cli": "writer run <task...>",
  "gui": "Workbench composer",
  "backend": "app-server turn/start",
  "status": "stable",
  "aliases": ["writer quick"],
  "deprecated": []
}
```

用途：

- 生成 CLI/GUI 文档表。
- 做入口一致性测试：公开能力必须至少有 CLI 或 GUI；标成 CLI 且 GUI 的能力两边都要存在。
- 为命令面板提供可搜索操作名。
- 为后续精简提供删除清单，避免“代码还在但没人知道入口”。

## 适配器设计

### CLI 适配器

新增统一 Python CLI 内核：

```text
scripts/lamtools_cli.py
scripts/member_cli.py 继续存在，但只做兼容转发
members/writer/backend/writer_cli/commands/
members/artist/backend/artist_cli/commands/
```

接口原则：

- 所有命令支持 `--json` 时返回统一 envelope：`ok/member/session_id/status/result/events/error`。
- 中文任务正文只从 argv 获取，不通过 PowerShell 管道传正文。
- 普通命令只调用产品公开适配器；开发命令才允许碰 debug/tool 内部接口。
- 错误文案统一给出下一步，例如“后端未启动，请运行 `lamtools dev writer backend`”。

### GUI 适配器

保留 `useCoreWorkbenchController`，但把“发送任务”从 `createMessage` 概念里拆出来：

```ts
interface MemberWorkbenchAdapter {
  listSessions()
  createSession()
  renameSession()
  deleteSession()
  listMessages()
  startTurn()
  resumeTurn()
  stopTurn()
  respondDecision()
  listProviders()
}
```

这样 Writer 的 app-server 和 Artist 的 `artist-turn` 都能挂到同一 GUI 工作台，而不会再把 Core message 写入误认为任务启动。

## 分类处理清单

| 项 | 分类 | 处理 |
|---|---|---|
| `writer run/resume/watch/stop` | 可靠 | 保留为 Writer CLI 主干，补 `--json` 和 `--last`。 |
| Writer app-server `turn/*` | 可靠 | 作为 Writer 任务真实后端接口。 |
| Artist `/artist-turn` | 可靠 | 作为 Artist 任务真实后端接口。 |
| Core `/messages` | 可靠但易误用 | 明确只用于消息读写，不作为任务入口。 |
| `writer quick/chat/cancel` | 存疑 | 保留 alias，不主推；下一阶段输出 deprecation 提示。 |
| Artist 位置参数式 CLI | 债务 | 改为子命令式；保留 `artist <prompt>` 快捷。 |
| Artist `/generate` | 债务 | 标 legacy，收敛到 `/artist-turn`。 |
| GUI session rename 未接线 | 已处理 | Writer/Artist Workbench 已接线到持久化重命名。 |
| Provider/Model/Vendor 混名 | 债务 | 用户层统一“供应商/模型”。 |
| Writer Electron + Tauri 双桌面线 | 存疑 | 选主线，另一条标 experimental 或删除候选。 |
| 未形成入口的 attachment/novel/reference/billing/dashboard/long-task | 存疑 | 每项决定“公开并补入口”或“内部化/删除”。 |

## 分阶段实施

### Phase 0：入口止血（0.5 天）

- 保持已修复的 Artist 根 CLI 分发。
- 文档主入口只保留当前真实可用命令。
- `rg` 检查旧文档里不存在的 `artist.py`、`writer sse`、`--one-loop`。

验收：

- `writer --help`、`artist --help` 能跑。
- `docs/cli-guide.md` 与实际 help 无明显冲突。

### Phase 1：最小统一（1-2 天，主干已落地）

- 新增 `lamtools` 根命令：`dev/build/test/open/doctor/members/scaffold`。已落地 `scripts/lamtools_cli.py` 与 `lamtools.cmd`。
- 给 `writer` 与 `artist` 增加 `--json` envelope。未完成，保留到下一阶段。
- Artist CLI 改为子命令式，同时保留旧快捷。已先在根转发层提供子命令 help 和稳定映射。
- GUI session rename 接线或隐藏。已接线 Writer/Artist 会话重命名。

验收：

- `lamtools doctor writer --json` 能检查后端、前端、DB、版本、端口。
- `artist session list` 和 `artist run` 由真实 subparser 提供帮助。
- Writer/Artist 左侧重命名刷新后仍保留。

### Phase 2：产品能力补齐（2-4 天）

- 补 `session delete/rename/show/messages/status` 两成员一致性。
- 补 `config providers/models/defaults/routes` CLI。
- Writer `stop` 成为主命令，`cancel` 降为 alias。
- Artist `/generate` 标 legacy，GUI/CLI 不再调用。
- Settings 文案统一供应商/模型。

验收：

- 审查表中所有“仅 GUI 但适合自动化”的能力至少有 CLI 方案。
- 审查表中所有“看似 GUI 但未接线”的能力清零。

### Phase 3：操作目录与文档生成（2-3 天）

- 新增 `core/operations/*.json`。
- CLI help、GUI 命令面板、文档表从同一操作目录读取或校验。
- 增加测试：公开操作必须有 owner、visibility、CLI/GUI/HTTP 映射、稳定性标记。

验收：

- `docs/cli-guide.md` 和 `docs/gui-guide.md` 可以由操作目录校验。
- 新增 member 时必须补操作目录，否则测试失败。

### Phase 4：减法清理（持续）

- 移除或隐藏未公开的旧入口。
- 选择 Writer 桌面主线。
- 对 attachment/novel/reference/billing/dashboard/long-task 做逐项公开/删除决策。
- 旧命令 alias 进入一版提示期后删除。

验收：

- `rg "@router\\.|add_parser|function .*Api"` 发现的新入口必须在操作目录里出现。
- 普通用户文档不再出现 developer/debug 命令。

## 验收标准

1. 任一外部能力都能回答四个问题：谁用、从哪里进、底层调哪里、失败怎么反馈。
2. Core 文档里不出现 Writer/Artist 业务动作。
3. Member 文档里不要求用户进入成员目录。
4. Writer 与 Artist 至少共享 `run/resume/session/config/health` 的外部语义。
5. GUI 中所有可点入口都能持久化或给出明确失败提示。
6. Debug/内部接口不会出现在普通用户主帮助和主设置页。
7. 文档、CLI help、GUI 命令面板的能力命名一致。

## 建议立刻做的三个任务

1. **先做 `lamtools doctor/open`。** 这是用户最容易遇到的启动与端口问题，也能支撑后续验收。
2. **修 GUI 会话重命名。** 当前属于明确债务：控件存在但未接线。
3. **改 Artist CLI 子命令。** 这是 member 指令统一的最大阻塞点。
