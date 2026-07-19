# Core 后端协议与运行骨架

## 一句话结论

Core 后端主线已经成立：它承担通用协议、运行骨架、工具、事件和状态基础能力。当前最大问题不是缺抽象，而是协议层历史并存、模板契约不一致、少量产品名残留，以及几个过宽文件需要减法收口。

## 路径覆盖

- `core/src/lamtools_core`
- `core/templates`
- `core/docs`
- `core/tests`，只作为验证和边界证据
- 根 `README.md`、`AGENTS.md`
- `docs/architecture-audit/2026-07-08-structure-organization-plan.md`

额外发现：

- `core/src/lamtools_core/appserver` 当前只有 `__pycache__`，没有源码文件；结构审计中应视为运行残留，不视为模块。
- `__pycache__` / `.pyc` 不在 `git ls-files` 输出中，属于工作树残留视野噪音。

## 主要职责和入口

- 运行主线：`kernel` 提供共享循环骨架，`RuntimeKit` 是业务注入点，成员只实现上下文、请求构造、模型输出解析、工具执行、验收和下一步决策。
- 协议基础：`llm`、`tool`、`event`、`runtime`、`session`、`provider`、`usage`、`snapshot` 提供通用输入输出、状态、事件、快照和内存实现。
- 模型适配：OpenAI-compatible payload、response、stream helper 是当前成熟主线，`profiles.py` 承担非标准供应商字段映射。
- 应用装配：`app/factory.py` 装 FastAPI 与 member manifest；`http/routes.py` 暴露可选 Core session/event/provider/usage 路由。
- 新成员脚手架：`core/templates/member` 生成薄 member 包，理想上只填产品 prompt、工具、验收和 UI slot。

主入口：

- 运行时主入口：`CoreLoopKernel.run(...)`
- 业务 seam：`RuntimeKit`
- HTTP 装配入口：`create_app(...)`、`create_core_router(...)`
- 轻量 agent app 入口：`AgentApp.run_turn(...)`
- CLI/GUI 统一动作候选：`OperationCatalog`

## 可靠

- `RuntimeKit` seam 清楚，测试限制 Kit 只能有固定生命周期方法，不能启动自己的循环。
- `CoreLoopKernel` 方向正确：Kernel 管流程，Kit 管业务；源码未发现 `if writer/artist` 产品分支。
- OpenAI-compatible LLM helper、stream chunk 归一化、retry policy、provider profile 适合作为 Core 基础能力。
- `RunItemEvent + snapshot reducer` 是产品中性的可恢复展示事实，适合作为长期收敛目标。
- `context_compaction.py` 有明确结构化摘要契约，并保留用户指令、决策、路径、命令和失败信息。
- member manifest、registry、app factory 足够薄，符合“成员注册、Core 装配”的边界。

## 存疑

- `CoreEvent`、`RunItemEvent`、`RuntimeEventRecord`、SSE payload 四套事件形态并存。当前能跑，但协议真相不唯一。
- `AgentApp` 与 `CoreLoopKernel` 是两条 agent 应用路径：前者轻量、后者完整运行骨架。需要确认它是新主线外壳，还是实验层。
- `RuntimeTurnResult`、`RuntimeDriver`、`CompletionGate` 更像早期 runtime 抽象，当前主要被测试覆盖，和 Kernel 主线关系偏弱。
- `command.py`、`command_runner.py`、`command_tools.py` 分层不深，存在私有函数跨文件导入；功能有价值，但模块形状需要收口。
- `llm/profiles.py` 自研 profile DSL 有用，但复杂度会继续涨；进入实现前需要再对照成熟 provider adapter 方案。
- `core/docs` 里大量 Writer/Artist 是历史设计说明，不是源码越界；但需要维护标注，否则容易被后续 agent 当成当前事实。

## 债务

- `core/src/lamtools_core/kernel/loop.py` 过宽：主循环、流式事件、工具执行、审批等待、压缩事件、展示事件都在一个文件里。
- `event/runtime_projection.py` 过宽：运行事件到快照事实的映射、工具参数预览、artifact、usage、status 都堆在同一文件。
- `tool/workspace_files.py` 过宽：读、列、搜、写、编辑、diff 全在一起；外部接口可以不变，内部应拆。
- `core/templates/member/frontend/src/api/core.ts` 与 `http/routes.py` 契约不一致：模板创建 session 只传 `title`，但后端要求 `id/member_id/title/status`；创建 message 只传 `role/content`，但后端要求 `id`。
- `kernel/loop.py` 仍识别 `writer_message_id`，这是 Core 源码中的产品名残留。即使是兼容字段，也应迁移为中性 `message_id`。
- `sse.format_thinking_chunk` 已标 deprecated，仍保留非标准 reasoning delta 输出，属于旧兼容层。
- `core/src/lamtools_core/appserver` 只有缓存目录，没有源码，应清理出结构视野。

## 重构/优化建议

### P0

- 修正 member 模板与 Core HTTP 路由契约，补测试覆盖“生成模板后能创建 session/message”。这是脚手架会复制的问题。
- 清理 `core/src/lamtools_core/appserver` 和缓存残留，避免审计、统计、agent 搜索误判模块边界。
- 把 `writer_message_id` 兼容逻辑移到成员侧或投影适配层；Core 内部统一只认 `message_id` / `id`。

### P1

- 事件协议收口：明确 `RunItemEvent` 是快照/展示事实，`CoreEvent` 是 Kernel 内部运行事件，`RuntimeEventRecord` 只是持久化 DTO；删除或降级重复转换入口。
- 保持 `CoreLoopKernel` 外部接口不变，把内部拆成私有模块：模型流事件、工具执行计划、压缩控制、运行事件发射。
- 合并命令工具层级：减少 `command_tools.py` 对 `command_runner.py` 私有函数的依赖，形成一个清楚的“命令执行器 + 工具 handler”结构。
- 对 `RuntimeTurnResult`、`RuntimeDriver`、`CompletionGate` 做全仓调用核对；无真实成员依赖就删除或标注为 legacy。

### P2

- 给 `core/docs` 历史计划加维护标注，区分“历史抽取方案”和“当前源码事实”。
- 拆 `workspace_files.py` 内部实现为 read/search/write/edit 四块，但保持工具名和 `ToolResult` 契约不变。
- 为模板增加端到端 scaffold smoke：后端启动、前端 API body、Core routes 基本可用。
- `profiles.py` 后续按 provider family 拆内部文件，但不要新增公开抽象。

## 不建议现在做

- 不新增 Hook 层；当前 Kernel/Kit seam 已够清楚。
- 不把 Writer/Artist 的 persona、业务路由、专用工具抽进 Core。
- 不一次性重写 Kernel；先拆内部文件，保持接口和测试面稳定。
- 不把 `AgentApp` 直接宣布为新主线；先核对实际调用方。
- 本轮不做 OpenAI/Claude 外部方案调研，因为这是只读结构审计，不是实现阶段。

## 需要主线程核对的证据

- `core/templates/member/frontend/src/api/core.ts` 的 POST body 与 `core/src/lamtools_core/http/routes.py` 请求模型不匹配，确认脚手架是否当前仍被使用。
- `RuntimeTurnResult`、`RuntimeDriver`、`CompletionGate` 是否有 scope 外成员依赖；若没有，建议进删除清单。
- `CoreEvent`、`RunItemEvent`、`RuntimeEventRecord` 哪个作为长期协议真相，需要统一口径。
- `writer_message_id` 是否仍有历史数据必须兼容；如必须兼容，应放在 member/adapter 层，不留在 Kernel。
- `core/src/lamtools_core/appserver` 是否可直接清理；当前看不到源码，只是缓存残留。
- `AgentApp` 是否计划承接 CLI/GUI/HTTP 统一操作；若不是，应避免继续扩张。
