# Writer 工具标准化审计

日期：2026-06-18

## 目标

把 Writer 的工具体系从“能调用”收敛到“可解释、可维护、可展示”：

- 模型只看到当前运行环境真实可执行的工具
- 每个工具都有严格输入契约、权限等级、失败语义和展示语义
- 前端展示工具事实，不解析任意字符串猜测文件、diff、状态
- Agent、MCP、浏览器、文件读写等能力分层显示，默认不暴露调试遥测

## 对标依据

OpenAI 当前工具方向可以归纳为四条工程约束：

- 工具通过 `tools` 暴露给模型，函数工具使用 JSON Schema 描述参数
- 严格函数工具应启用 `strict`，禁止额外参数，并让 schema 与执行器完全一致
- 工具调用需要可关联的调用 ID，结果应能回到对应调用
- 工具面过大时，应按任务动态选择、延迟加载或通过 Agent/MCP 分层，而不是一次性暴露所有能力

参考资料：

- OpenAI Tools guide: https://developers.openai.com/api/docs/guides/tools
- OpenAI Function calling: https://developers.openai.com/api/docs/guides/function-calling
- OpenAI Tool search: https://developers.openai.com/api/docs/guides/tools-tool-search
- OpenAI MCP/connectors: https://developers.openai.com/api/docs/guides/tools-connectors-mcp
- OpenAI Agents SDK tools: https://openai.github.io/openai-agents-python/tools/

## 当前结论

### 可靠

这些工具与成熟 coding agent 的基础能力一致，边界清晰，默认可继续保留：

| 工具 | 结论 | 说明 |
| --- | --- | --- |
| `read_file` | 可靠 | 限定 `work_root`，有文件元信息和长度保护 |
| `list_dir` | 可靠 | 限定 `work_root`，限制条目数 |
| `search_files` | 可靠 | 标准文件定位工具 |
| `search_content` | 可靠 | 字面文本内容搜索工具，支持文件或目录路径 |
| `write_file` | 可靠 | 有路径边界和长度限制；已返回结构化 `file_change` artifact 和 unified diff |
| `edit_file` | 可靠 | 精确替换、拒绝空匹配和多重匹配；已返回结构化 `file_change` artifact 和 unified diff |
| `git_status` | 可靠 | 只读 git 状态 |
| `git_diff` | 可靠 | 只读 diff，支持路径过滤 |
| `run_command` | 可靠 | 显式前台/后台契约、工作目录约束、秒级超时、非零退出和 readiness 探针失败都会进入 `ToolResult.failed`；结果返回 `command_output` artifact |
| `run_tests` | 可靠 | 独立测试语义，返回 `test_result` artifact、退出码、耗时和 passed/failed 摘要 |
| `inspect_project` | 可靠 | 返回 `project_inspection` artifact 和结构化 metadata，包括 manifests、scripts、test_commands、likely_stack、files_sampled |
| `web_search` | 可靠 | 返回来源 metadata 和 `web_search_result` artifact；实现是轻量搜索 provider，不等同浏览器搜索 |
| `web_fetch` | 可靠 | 返回 URL、状态码、content_type、截断状态和 `web_fetch_content` artifact |
| `browser_check` | 可靠 | HTTP 可达性与文本检查工具；需要真实浏览器时应使用独立浏览器工具，而不是让该工具伪装成 Playwright |

### 存疑

这些能力服务了真实需求，但仍有自研痕迹，需要继续标准化：

| 工具 | 结论 | 需要处理 |
| --- | --- | --- |
| `recall_session` | 存疑 | 属于记忆检索，不应和文件工具平铺展示 |
| `load_skill` | 存疑 | 属于技能加载，不应和普通工具平铺展示 |
| `write_checklist` | 可靠 | 已进入过程层展示，摘要按计划处理，不再伪装成普通工具 |
| `verify_design` | 可靠 | 已进入过程层展示，成功时隐藏“验证通过”等低价值详情 |
| `*_agent` | 可靠 | 已按 Agent-as-tool 暴露为具体工具；结果包含 agent_name、task、substeps、referenced_tools、final_answer，并由 Agent 卡片消费 |
| `call_agent` / `design_architecture` | 已删除债务 | 旧通用路由器和旧专用入口已移除；架构流程统一通过 `architecture_agent` 调用 |
| `delegate_to_member` | 存疑 | 需要明确成员间调用协议和 UI 展示 |
| `decision_point` | 可靠 | 已进入可交互决策卡片，不再计入普通工具；选择会作为用户回复进入正常聊天流程 |

### 债务

这些问题带来负收益，需要优先减法或重构：

| 债务 | 影响 | 当前状态 |
| --- | --- | --- |
| 多个工具注册源并存 | `WRITER_TOOLS`、`tool_specs.py`、执行器仍可能漂移 | 已处理：模型可见 schema 由 `WRITER_TOOL_SPECS` 单一来源生成；旧 `MODEL_TOOL_FUNCTIONS` 双轨源已删除；默认执行器已增加契约测试防漂移 |
| 前端解析工具文本 | 文件名、行数、diff、错误原因容易被摘要格式影响 | 后端 summary 已携带 artifact；前端工具卡片已优先消费 artifact，旧文本解析保留为兜底 |
| 过程控制工具和用户工具混放 | 用户看到“验证通过”“流程推进”等低价值状态 | UI 已收敛；后端分类仍需统一 |
| `run_tests` 复用 `run_command` | 测试语义不清，前端无法稳定渲染测试结果 | 已拆出独立入口、结构化结果和前端专用测试卡片 |
| `tool_specs.py` 声称驱动运行但实际不是唯一来源 | 文档与实现不一致，维护者容易误判 | 已处理：模型 schema、权限、分类、展示与输出契约均从 `tool_specs.py` 派生；执行器映射通过契约测试校验，暂不引入反射式执行器生成 |

## 标准工具契约

后续所有 Writer 工具应落到同一份 ToolSpec，至少包含：

| 字段 | 用途 |
| --- | --- |
| `name` | 稳定工具名 |
| `category` | `file_read`、`file_write`、`command`、`git`、`web`、`browser`、`memory`、`skill`、`agent`、`control` |
| `description` | 给模型看的用途，不写实现细节 |
| `input_schema` | 严格 JSON Schema |
| `permission` | `auto_allow`、`ask_user`、`hard_block` |
| `enabled_when` | 当前运行环境是否可用 |
| `output_schema` | 给前端和模型消费的结构化结果 |
| `display` | 默认卡片类型、是否默认折叠、关键字段 |
| `failure_schema` | 统一失败类型、原因、恢复建议 |

当前 `tool_specs.py` 已经落地：

- `category`
- `display`
- `output_schema`
- `internal_only`
- `permission`
- 模型可见工具由 `WRITER_TOOL_SPECS` 单一事实源生成 `WRITER_TOOLS`
- OpenAI strict schema 递归规范化：对象禁止额外字段，所有属性必填，历史可选字段以 `null` 表示

仍未完全落地：

- Agent 内部子步骤已有稳定 metadata 字段；更细粒度实时子事件仍可继续增强

## 迁移计划

1. 以 `tool_specs.py` 或新注册表作为唯一来源，生成模型 schema、权限表、执行器映射和 UI 元信息
2. 所有默认可见工具必须有真实执行器；Agent/MCP/控制类工具必须显式分类
3. 每个工具结果返回结构化 `metadata` 或 `artifacts`，前端优先渲染结构化字段
4. 文件修改工具输出统一 diff artifact，避免前端从文本摘要里猜行号和内容
5. `run_tests` 从 `run_command` 中拆出测试结果模型：命令、退出码、失败摘要、日志片段、耗时
6. Agent 工具统一进入 Agent 卡片，显示任务、子步骤、引用工具、结论
7. 调试遥测只进调试模式，默认界面保留正文、工具卡片、Agent 卡片和必要错误

## 已完成

- 补齐 `browser_check` 默认执行器，避免模型调用后出现“工具不可用”
- 增加工具契约测试，检查默认运行时不会暴露缺失的普通工具
- 增加严格 schema 测试，确保暴露给模型的函数工具满足 strict schema 要求
- 保留 `call_id` 和参数，便于前端把工具调用与结果稳定关联
- 权限表改为从 `tool_specs.py` 派生，减少一处手写漂移源
- 为所有工具 spec 补齐分类、展示契约、输出契约和 internal-only 标记
- `tool_specs.py` 已生成模型可见 `WRITER_TOOLS`，并用回归测试防止 prompt 入口绕过 spec
- `run_command` 的模型契约改为秒级超时，与执行器真实行为一致
- `run_command` 已移除按命令名猜测后台运行的逻辑；后台服务必须显式 `background=true`，Python `http.server` 成功前会验证当前 `work_root` 探针
- `run_command` 已增加显式 `readiness_url`/`readiness_text`，后台服务可用性必须通过本机 HTTP 探测后才报告 `ok`
- `run_command` 返回 `command_output` artifact，包含 command、exit_code、stdout、stderr、timed_out、background、duration_seconds 和错误类型
- `tool_specs.py` 旧 `MODEL_TOOL_FUNCTIONS` 双轨声明已删除，模型工具 schema 不再通过第二来源覆盖运行时规格
- `read_file` 返回 `file_read` artifact；`write_file` 和 `edit_file` 返回 `file_change` artifact，包含路径、动作、行数变化和 unified diff
- `tool_results_summary` 已传递 `artifacts` 和 `metadata`，Writer 前端历史重建会保留 artifacts
- `ChatThread` 文件工具卡片优先读取 artifact 内容、路径和元信息，旧文本解析只作为兼容兜底
- `run_tests` 已从 `run_command` 别名拆出，返回 `test_result` artifact 和结构化 metadata
- `ChatThread` 已为 `test_result` artifact 增加专用测试卡片，展示通过/失败、命令、退出码、耗时和日志
- `ChatThread` 实时 timeline 已接入同一套工具卡片主体，写文件可在流式过程中展示 diff，测试工具可展示测试结果卡片
- 已用 Playwright 验证历史重建和实时 timeline 两条路径：`file_read`、`file_change`、`test_result` artifact 均能渲染，且未发现卡片溢出
- 默认执行器已增加契约测试：执行器暴露工具必须有 spec，默认模型可见工具必须等于模型工具清单与真实执行器的交集
- `decision_point`、`write_checklist`、`verify_design` 已从普通工具卡片迁到过程/决策层；Playwright 验证控制过程不会产生普通工具卡片
- `call_agent` / `design_architecture` 已删除；新模型直接看到 `architecture_agent`、`search_agent` 等具体 Agent 工具
- `decision_point` 已升级为可点击决策卡片；点击选项会发送一条正常用户回复，不再依赖废弃 resume 接口
- Agent 卡片已补充任务、模式、胜出结论、校验状态、引用工具和结论摘要；历史重建会保留 Agent metadata
- 历史消息中的 `parts.decision` 已能重建为决策卡片，刷新页面后不会退回普通文本
- 默认 Core Kernel 路径已装配 AgentRuntime，避免模型可见 Agent 工具但运行时不可用
- Agent 结果已标准化：`agent_name`、`task`、`substeps`、`referenced_tools`、`final_answer`
- `inspect_project`、`web_search`、`web_fetch` 已补结构化 metadata/artifact
- 默认主界面移除了 composer 旁 provider 数量，避免配置/调试信号占据主任务区

## 下一批优先级

1. 将 `recall_session`、`load_skill` 的展示契约继续从文本摘要迁到结构化 metadata/artifact
2. 为 Agent 实时事件补更细粒度的阶段事件，而不只在最终 ToolResult 中给 `substeps`
3. 处理前端 bundle 大 chunk 警告，降低 Settings/diagram 相关依赖对首屏的影响
