# 数据库与 Provider 适配分类口径

维护标注：本文只整理当前拆分口径，不改变现有调用逻辑。现有讯飞 MaaS / Xfyun Coding Plan 链路先保持可用。

## 目标

把三类东西分开：

1. 共享配置：谁可调用、用哪个模型、用哪个 provider profile。
2. 运行数据：Core 和 Writer 各自的 session、事件、快照、转录、产物。
3. Provider 适配规则：怎么拼请求体、怎么解析响应、哪些字段不支持。

## SQLite 文件分类

### `data/lamtools.db`

定位：共享配置库。

应保留：

- `llm_providers`：服务商、接口类型、Base URL、API Key、默认标记、`extra.adapter_profile_id`。
- `llm_models`：模型 ID、显示名、上下文、最大输出、thinking 能力、默认参数。
- 通用 `app_settings`：跨 Core / member 共用的模型路由、基础运行控制、共享默认值。

不应存：

- Core session / 事件 / 快照。
- Writer session / 消息 / 转录 / 产物。
- 大段 provider 请求体规则。

### `data/core.db`

定位：Core 自己的运行库。

应保留：

- `core_app_events`：Core CLI / Core Agent 的事件流水。
- `core_thread_snapshots`：Core thread 快照。

不应存：

- Provider API Key。
- Writer 业务数据。
- Writer UI / 项目 / 转录。

### `members/writer/data/lamwriter.db`

定位：Writer member 运行库。

应保留：

- `writer_sessions`
- `writer_messages`
- `writer_steps`
- `writer_projects`
- `writer_attachments`
- `writer_queued_inputs`
- `writer_runtime_events`
- `writer_app_events`
- `writer_app_events_archive`
- `writer_thread_snapshots`
- `writer_app_requests`
- `writer_artifacts`
- `writer_transcript_turns`
- `writer_transcript_model_calls`
- `writer_transcript_blocks`
- `writer_transcript_artifacts`
- `writer_active_producers`

应迁出或停止重复写入：

- `llm_providers`
- `llm_models`
- 可共享的 `app_settings`

Writer 专属设置可以继续留在 Writer 库，例如纯 UI 偏好、Writer 特有工具展示、Writer 项目默认项。

### 旧 AppData Writer 库

路径：`C:/Users/Administrator/AppData/Roaming/LamWriter/lamwriter.db`

定位：旧迁移来源，不作为新运行默认库。

## `app_settings` 分类

当前实际有三类命名空间：

- `lamwriter.modelRouting`
- `lamwriter.runtimeControls`
- `lamwriter.ui`

拆分口径：

- 模型路由如果是 Core / 多 member 共用默认策略，迁到共享库并改通用命名，例如 `lamtools.modelRouting`。
- 运行控制如果是工具权限、基础工具开关、通用 agent 运行控制，迁到共享库或 Core 配置命名。
- Writer UI 偏好留 Writer 库，例如主题、密度、内容宽度、运行区显示。
- Writer 专属 agent / Writer 专属工具策略留 Writer 库，不下沉为 Core 语义。

## Provider 适配文件分类

Provider 适配规则不是运行数据，不拆进 SQLite。它们属于 JSONC profile。

当前讯飞适配规则在：

- `core/llm_adapters/xfyun-coding-plan.jsonc`
- `members/writer/backend/app/llm_adapters/xfyun-coding-plan.jsonc`

当前数据库只保存引用：

```json
{"adapter_profile_id": "xfyun-coding-plan"}
```

这个含义是：该 provider 使用 `xfyun-coding-plan` 这套请求/响应适配规则。

## 讯飞 thinking 开关口径

讯飞 MaaS 的 thinking 开关不需要拆成两个 profile。

原因：

- 开启 thinking 时只是请求体多一个字段：`enable_thinking: true`。
- 关闭 thinking 时不发送这个字段。
- endpoint、鉴权方式、响应字段路径、流式字段路径没有变。

所以当前应该保留为同一个 profile：

```jsonc
{
  "id": "xfyun-coding-plan",
  "request": {
    "thinking": {
      "when_enabled": {
        "enable_thinking": true
      }
    },
    "unsupported_fields": [
      "thinking",
      "reasoning_effort"
    ]
  }
}
```

前端的“Max 思考 / 无思考”是运行时选项，不是 provider profile 分类。它最终只决定本次请求是否启用 thinking；profile 再把这个选项翻译成讯飞需要的 `enable_thinking` 字段。

## 什么时候拆多个 JSONC profile

需要拆 profile 的情况：

- endpoint 不同。
- 协议不同，例如 OpenAI Chat Completions 和 Anthropic Messages。
- 鉴权 header 不同。
- 请求体固定字段长期不同，不只是开关字段。
- 响应解析路径不同。
- 流式 chunk 字段路径不同。
- 同一 provider 下有互斥能力，放在一个 profile 会让规则变复杂。

不需要拆 profile 的情况：

- 只是 thinking 开 / 关。
- 只是 thinking budget 不同。
- 只是模型上下文、最大输出、temperature 不同。
- 只是 UI 档位不同，例如 low / high / max。

## 推荐文件归属

Core 内置 profile：

- 放通用 provider / 协议 profile。
- 作为默认可用规则。
- 例如 `openai-chat.jsonc`、`xfyun-coding-plan.jsonc`。

Member profile：

- 只放该 member 独有的 provider 规则或临时覆盖。
- Writer 不应长期复制 Core 已有通用 profile。

用户 profile：

- 放用户自定义 provider profile。
- 不放 API Key。
- API Key 继续存在共享配置库或环境变量。

## 后续执行顺序

1. 先保留现有调用逻辑。
2. 把共享配置读写统一到 `data/lamtools.db`。
3. Writer 停止把 `llm_providers`、`llm_models`、共享 `app_settings` 当作自己的运行数据。
4. Core 继续只写 `data/core.db`。
5. Writer 继续只写 `members/writer/data/lamwriter.db`。
6. 适配规则继续走 JSONC profile；只有满足拆分条件时才新增 profile 文件。

## 当前判断

SQLite 需要拆：

- 共享配置库：`data/lamtools.db`
- Core 运行库：`data/core.db`
- Writer 运行库：`members/writer/data/lamwriter.db`

讯飞 JSONC profile 暂时不需要按 thinking 开关拆。

如果后续出现真正不同的讯飞产品线，例如不同 endpoint、不同响应结构、不同鉴权方式，再新增独立 profile。当前“开不开启思考”只是同一个 profile 内的可选请求字段。

## 三项落地方案

### 1. `app_settings` 拆分方案

不按旧 namespace 一刀切，按字段归属拆。

新口径：

- Core / 基础设施配置进共享配置库 `data/lamtools.db`。
- Writer 专属配置进 Writer 库 `members/writer/data/lamwriter.db`。
- 旧 `lamwriter.*` namespace 只作为迁移来源，不作为新设计继续扩张。

目标 namespace：

- `core.modelRouting`：Core 默认模型、Core 子 agent 模型、通用 agent mode 的模型路由。
- `core.runtimeControls`：基础工具开关、命令策略、Core agent 运行控制。
- `core.permissions`：Core 权限基底。
- `writer.modelRouting`：Writer mode、Writer 专属 agent、Writer 专属子流程的模型覆盖。
- `writer.runtimeControls`：Writer 专属工具、Writer 专属 agent 开关。
- `writer.permissions`：Writer 对 Core 权限的增量覆盖。
- `writer.ui`：Writer UI 偏好。

当前三类旧设置的迁移判断：

- `lamwriter.modelRouting`
  - `writer` 路由迁到 `writer.modelRouting`。
  - `architecture_agent`、`sub_agent` 先按是否能脱离 Writer 运行来拆；能作为 Core 通用 agent 的进 `core.modelRouting`，只服务 Writer 的留 `writer.modelRouting`。
- `lamwriter.runtimeControls`
  - `tools` 默认迁入 `core.runtimeControls` / `core.permissions`。
  - 只有依赖 Writer 专属业务状态、Writer 专属 UI、Writer 专属产物语义的工具留在 `writer.runtimeControls`。
  - `agents.sub` 如果是 Core 子 agent 能力，迁入 Core；如果是 Writer 专属子 agent persona，留 Writer overlay。
  - `command_policies` 迁入 `core.permissions`，Writer 只做覆盖。
- `lamwriter.ui`
  - 整体迁为 `writer.ui`，留 Writer 库。

判定规则：

- Core 独立 Agent 要用到的配置，进 Core。
- 任意 member 都可能复用的配置，进 Core。
- 只要不是 Writer 独有，先按 Core 处理。
- 只有确认依赖 Writer persona、Writer 页面、Writer 项目语义、Writer 专属产物时，才留 Writer。

### 2. 权限 overlay 方案

权限不再由 member 各自实现一套。权限分两层：

1. Core 权限基底。
2. Member 增量覆盖。

Core 权限基底放在共享配置库：

```jsonc
{
  "version": 1,
  "tools": {
    "read_file": { "enabled": true, "approval_policy": "auto_allow" },
    "write_file": { "enabled": true, "approval_policy": "ask_user" },
    "run_command": { "enabled": true, "approval_policy": "ask_user" }
  },
  "command_policies": {
    "regular": "auto_allow",
    "dangerous": "ask_user"
  },
  "mcp": {},
  "hooks": {}
}
```

Writer 权限覆盖放在 Writer 库：

```jsonc
{
  "version": 1,
  "extends": "core.permissions",
  "tools": {
    "writer_specific_tool": { "enabled": true, "approval_policy": "ask_user" },
    "run_command": { "approval_policy": "ask_user" }
  },
  "command_policies": {
    "dangerous": "ask_user"
  }
}
```

合成顺序：

1. Core 默认权限。
2. Core 用户配置。
3. Member 默认 overlay。
4. Member 用户配置。
5. 本次运行临时参数。

冲突规则：

- `hard_block` 优先级最高。
- member 可以收紧 Core 权限。
- member 可以新增 member 专属工具权限。
- member 不应该复制 Core 工具定义，只写差异。
- member 如果要放宽高风险权限，必须显式配置，不能靠默认继承。

实现原则：

- Core 提供权限合成和判定入口。
- Writer 只提供 overlay 数据。
- Writer 不再直接解释完整权限体系。

### 3. JSONC profile 去重与打包方案

内置 provider profile 以 Core 为唯一默认源。

目标加载顺序：

1. Core 内置 profile：`core/llm_adapters/*.jsonc`
2. 打包后的 Core runtime profile：`runtime/core/llm_adapters/*.jsonc`
3. Member profile：`members/{id}/llm_adapters/*.jsonc`
4. Member 打包资源 profile：`runtime/members/{id}/llm_adapters/*.jsonc`
5. 用户自定义 profile：环境变量目录、用户 AppData 目录

覆盖规则：

- 后加载的同 ID profile 覆盖前面的 profile。
- Core 内置 profile 提供默认能力。
- Member profile 只用于 member 专属 provider 或 member 专属覆盖。
- 用户 profile 只用于本机自定义，不放 API Key。

当前讯飞处理：

- `xfyun-coding-plan` 作为通用讯飞 MaaS profile，归 Core。
- Writer 目录里的同名 `xfyun-coding-plan.jsonc` 是重复内置资源，最终应删除。
- 删除前必须确认开发态和打包态都能从 Core profile 加载。

迁移顺序：

1. 先让 Writer profile loader 读取 Core profile 目录。
2. 确认开发态 `adapter_profiles.list` 能看到 `xfyun-coding-plan`。
3. 确认打包态 runtime 包含 `runtime/core/llm_adapters/xfyun-coding-plan.jsonc`。
4. 确认 Writer CLI / GUI 仍能发出 `enable_thinking: true`。
5. 删除 Writer 目录里的重复 `xfyun-coding-plan.jsonc` 和 `openai-chat.jsonc`。
6. Writer 目录只保留 Writer 专属 profile 或 README。

## 需要询问的点

当前没有必须询问的点。

如果后续实现时发现某个工具依赖 Writer 专属业务状态，我会把它列为 Writer overlay；否则默认归 Core。
