# LamTools 开源 Agent 能力对照与新功能建议

日期：2026-07-08

## 目标

先记录相关开源仓库 README / 简介中已经实现的能力，再结合 LamTools 当前代码和 4 个子 agent 的只读分析，按收益 / 开发难度比分档提出新功能建议。

分档口径：

- 1 档，近期实现：收益 / 开发难度 >= 10。通常是已有 bug、入口缺口，或开发极小但用户感知强。
- 2 档，中期排队：1 <= 收益 / 开发难度 < 10。收益明确，但开发面、验证面或跨模块影响较大。
- 3 档，未来计划：收益 / 开发难度 < 1。方向可能对，但当前成本过高或会扩大复杂度。

## 外部开源能力底表

| 仓库 / 资料 | README / 简介已实现能力 | 对 LamTools 的启发 |
| --- | --- | --- |
| [openai/codex](https://github.com/openai/codex) | 轻量终端 coding agent，CLI 是第一等入口。 | Writer/Artist 的 GUI 能力必须有同接口 CLI；不要只做页面功能。 |
| [openai/openai-agents-python](https://github.com/openai/openai-agents-python) | 多 agent workflow；Agent 由 instructions、tools、guardrails、handoffs 组成；提供 sessions、tracing、human-in-loop、MCP tools。 | Core 应拥有 agent loop、tool、session、handoff/sub-agent、trace/diagnosis、approval/guardrail 骨架；member 只做业务配置。 |
| [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | 官方 reference servers 覆盖 prompts、resources、tools；多语言 SDK。 | 外部工具、资源、prompt 扩展不要自造私有协议，优先按 MCP 形状接入 Core optional capability。 |
| [cline/cline](https://github.com/cline/cline) | IDE / CLI / SDK；跨项目编辑、终端命令、Plan/Act、规则/技能、插件或 MCP；diff 可审查和回退，checkpoint 跟踪改动。 | LamTools 最应补的是计划/执行分离、可审查 diff、回退、规则加载和长命令状态，而不是再堆新页面。 |
| [RooCodeInc/Roo-Code](https://github.com/RooCodeInc/Roo-Code) | 编辑器内 AI agent 团队，多模式协作。 | 子 agent 要表现为“可理解的工作结果和分工”，不是隐藏在日志里的工具调用。 |
| [continuedev/continue](https://github.com/continuedev/continue) | open-source coding agent，覆盖 VS Code、JetBrains、CLI。 | 同一能力多入口是成熟产品常态；LamTools 应先补入口一致性。 |
| [All-Hands-AI/OpenHands](https://github.com/All-Hands-AI/OpenHands) | Agent Server，可接多个 agent server；Docker sandbox / 本机运行两种模式；Agent Canvas。 | 长任务、沙箱、server 健康状态、workspace 权限要成为可诊断的产品状态。 |
| [Aider-AI/aider](https://github.com/Aider-AI/aider) | 终端 pair programming；repo map；Git 自动提交、diff/undo；自动 lint/test。 | Writer 的代码任务应把 repo map、Git 审查、测试验收做成常规闭环。 |
| [block/goose](https://github.com/block/goose) | 可扩展 AI agent，执行、编辑、测试；支持多 provider 和 MCP 扩展。 | Provider/模型配置、MCP 扩展、诊断和执行能力应是平台能力，不应散在 Writer/Artist。 |
| [sst/opencode](https://github.com/sst/opencode) | 内置 build / plan 两类 agent；plan 是只读分析，build 是开发执行；桌面 app beta。 | LamTools 可以保留“规划/执行”模式，但先用权限和入口语义表达，不做复杂角色系统。 |
| [SWE-agent/SWE-agent](https://github.com/SWE-agent/SWE-agent) | 从 issue 自动修复；YAML 配置；重视 benchmark 和研究可复现。 | 高质量自动修复依赖任务规格、验收、配置化和可复现日志；先补验收与诊断，再谈更强自主。 |
| [Claude Code docs](https://docs.anthropic.com/en/docs/claude-code/sub-agents) | subagents、hooks、MCP、checkpointing、commands、skills 是成熟产品面。 | Core 需要生命周期事件、权限、MCP、子 agent、checkpoint 这些通用能力；不要让 Writer 私有实现长期留存。 |

## LamTools 当前可复用基础

| 现有基础 | 证据 | 判断 |
| --- | --- | --- |
| Core 已有 llm / tool / event / prompt / mem / guardrail / runtime / kernel 模块。 | `core/README.md` | 适合继续向“agent 基座”收敛。 |
| 产品目标强调任务状态优先、共享 UI 中立、错误/断连/加载状态一等公民。 | `PRODUCT.md` | 新功能应优先补状态可信度、诊断和入口一致性。 |
| Writer 缺口已经指向计划拆解、强制计划、失败重规划、执行中迷失检测、阶段状态。 | `members/writer/docs/Writer缺口功能表.md` | 计划能力是方向，但应从小闭环开始，不先做大而全 runtime。 |
| CLI/GUI 审查已记录多个 GUI-only 管理能力。 | `docs/cli-gui-entry-audit-2026-06-29.md` | “GUI 必须有同接口 CLI”是近期高收益缺口。 |
| North Star 已明确 Core 是 agent 基座、member 是薄业务包。 | `docs/agent-architecture-north-star-2026-06-30.md` | 新功能不能继续把基础 runtime 加厚到 Writer/Artist。 |
| Core sub-agent MVP 已定义“复用 sub session，不做并行/隔离/分支交付”的小闭环。 | `docs/superpowers/specs/2026-07-07-core-sub-agent-mvp-design.md` | 子 agent 功能应先把结果可见化和可复用做好，不急着扩成团队系统。 |
| 当前结构审计显示 Core UI、Writer Workbench、Settings、operations 是热点。 | `docs/architecture-audit/2026-07-08-structure-organization-plan.md` | 涉及这些热点的功能要特别克制，优先薄 UI + 复用现有接口。 |

## 1 档：近期实现

| 优先级 | 功能建议 | 难度 | 收益 | 比值 | 为什么现在做 | 复用/边界 |
| ---: | --- | ---: | ---: | ---: | --- | --- |
| 1 | 共享操作目录 + CLI/GUI/HTTP 一致性检查 | 0.8 | 9.0 | 11.25 | 直接落实“任何 GUI 能力必须有同接口 CLI”；已有 `OperationCatalog`、`doctor` 和入口审计文档。 | 只做公开操作目录和 doctor 检查，不扫全代码，不新增业务入口。 |
| 2 | Diff / 改动审查卡补齐最小操作：打开、单文件撤销、撤销全部、刷新、增删统计 | 0.8 | 8.5 | 10.63 | Cline/aider/Codex 类工具都把 diff/revert 当核心体验；LamTools 已有右栏审查基础，属于低成本补齐。 | 只接已有 app-server / API；撤销动作必须确认。 |
| 3 | 删除 session/project 时补删 transcript 全链路 | 1.0 | 10.0 | 10.00 | 这是数据一致性 bug，收益不靠新概念；可防止 orphan turn/block/artifact 长期留库。 | 沿用现有删除服务，先加测试确认是否保留审计历史。 |

## 2 档：中期排队

| 优先级 | 功能建议 | 难度 | 收益 | 比值 | 说明 |
| ---: | --- | ---: | ---: | ---: | --- |
| 4 | 启动/刷新时修复“假 running”会话 | 2.0 | 9.0 | 4.50 | 用后端事实和 heartbeat 超时修复 UI 状态漂移；先防止用户误判任务仍在跑。 |
| 5 | Writer/Artist Provider/Model 配置 CLI | 2.5 | 9.0 | 3.60 | GUI-only 缺口明显；统一成“供应商/模型”术语，API key 必须脱敏。 |
| 6 | 子 agent 结果收件箱：运行中、完成结果、查看 diff、合并/放弃入口 | 2.5 | 8.0 | 3.20 | Roo/OpenCode/Claude Code 都把 agent 分工做成可理解界面；先只展示结果和决策，不做自动合并。 |
| 7 | Commit Review 审批卡：摘要、建议提交信息、批准/要求修改/稍后 | 2.5 | 8.0 | 3.20 | 对齐 aider 的 Git 闭环；避免“生成了改动但用户不知道是否该提交”。 |
| 8 | Backend doctor/health 诊断入口，并提供同接口 CLI | 2.0 | 8.0 | 4.00 | 对齐 OpenHands/goose 的诊断与 server 状态；注意隐藏 API key 和敏感路径。 |
| 9 | 审批继续时按 request/block 精确恢复 | 2.0 | 8.0 | 4.00 | 对齐 human-in-loop；减少批准后接错上下文的风险。 |
| 10 | 模板契约测试 / 脚手架 dry-run 检查 | 2.0 | 7.0 | 3.50 | 防止新 member 生成后偏离 Core 规则；独立跑，不污染 core 测试收集。 |
| 11 | 共享事件 envelope 与实时状态标准化 | 2.0 | 7.0 | 3.50 | 只统一 envelope 和常见状态，不抽 Writer/Artist 业务细节。 |
| 12 | Provider/Model 连接预检 | 3.0 | 8.0 | 2.67 | 用户配置后立即知道是否可用；必须轻量、超时、避免默认产生高成本请求。 |
| 13 | 队列/引导体验升级：排队项状态、失败/过期提示、转为本轮或下一轮 | 2.0 | 7.5 | 3.75 | 解决运行中输入是否已进入模型的误解；不要和聊天正文混在一起。 |
| 14 | 运行状态可信条：结束/等待授权/可恢复错误 | 3.0 | 8.0 | 2.67 | 以 snapshot / backend projection 为准，避免前端临时状态放大假象。 |
| 15 | Usage / 上下文预算面板与软警告 | 4.0 | 8.0 | 2.00 | 先做 token、趋势、上下文水位，不做伪精确计费。 |
| 16 | 脚手架自动接入 dev/build/test/ports | 3.0 | 8.0 | 2.67 | 减少新 member 手工注册错误；PowerShell 写 JSON/脚本必须保持 UTF-8。 |
| 17 | 图片/附件输入的 Core 资源适配层 | 4.0 | 8.0 | 2.00 | Artist 可复用 Writer 附件体验；先统一接口，不搬业务存储。 |
| 18 | 统一 `--json` / `--json-lines` 输出 envelope | 2.0 | 8.0 | 4.00 | 方便测试、脚本和外部 agent 调用；流式任务用 JSON Lines。 |
| 19 | 时间线稳定收尾：阶段正文、最终回复边界、减少重排 | 3.5 | 8.0 | 2.29 | 需要新录屏验证收益；不要再造一套前端状态机。 |
| 20 | 设置隐藏区最小解冻：仅权限与 Agent 能力状态 | 4.0 | 6.5 | 1.63 | 根 AGENTS 明确这些区是临时隐藏区；不要恢复整页。 |
| 21 | Core 直跑最小 Agent CLI：`lamtools run --member <id>` | 4.0 | 7.0 | 1.75 | 有助于验证 Core agent 基座，但先用 mock/provider fixture，不碰真实产品流程。 |

## 3 档：未来计划

| 功能方向 | 难度 | 收益 | 比值 | 暂缓原因 |
| --- | ---: | ---: | ---: | --- |
| 并行 sub-agent + worktree/branch 隔离 + 自动合并完整团队系统 | 8.5 | 7.0 | 0.82 | 成熟产品有类似方向，但当前 Core sub-agent MVP 明确不做并行、锁、分支交付；先把可复用 sub session 和结果收件箱做好。 |
| 一次性重写 Core / Writer runtime 到 6,000 行硬目标 | 9.0 | 8.0 | 0.89 | 战略正确，但作为“新功能”会吞掉所有验证预算；应拆成操作目录、事件标准化、toolkit 下沉等小步。 |
| 全量恢复 Writer 设置隐藏区 | 7.0 | 4.0 | 0.57 | 违反当前维护标记；会把已隐藏的临时区重新变成用户承诺。 |
| 完整 MCP marketplace / 任意 server 安装 UI | 8.0 | 6.0 | 0.75 | MCP 是正确方向，但先做 Core adapter 和少量可信 server；不要先做市场化 UI。 |
| Butler/Sage/Creator 跨成员全家桶协作 | 9.0 | 7.0 | 0.78 | 产品愿景成立，但当前 Writer/Artist/Core 入口一致性和状态可信度还未补齐。 |
| Artist MEM/CON/画像全栈一次性重做 | 8.0 | 5.0 | 0.63 | Artist 路线已有长期规划，但现在收益低于修入口、诊断、状态和脚手架。 |

## 主审结论

近期只建议排 3 件：

1. 共享操作目录 + CLI/GUI/HTTP 一致性检查。
2. Diff / 改动审查卡最小补齐。
3. 删除 session/project 时补删 transcript 全链路。

这三件共同特点是：复用已有能力、用户收益直接、不会扩大 runtime 复杂度。

中期按两条线排队：

- 可靠性线：假 running、审批恢复、doctor、状态可信条、队列体验。
- 产品入口线：Provider/Model CLI、JSON 输出、commit review、子 agent 结果收件箱、脚手架接入。

暂不建议做“完整 agent 团队”“完整 MCP 市场”“恢复全部设置页”这类大功能。它们看起来接近成熟产品，但在 LamTools 当前结构下会先扩大复杂度，而不是增强产品闭环。
