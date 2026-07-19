# Artist 后端、运行时与桌面

## 一句话结论

Artist 当前主线是清楚的：`HTTP artist-turn -> handle_artist_generate -> artist_orchestrate -> CoreLoopKernel + ArtistKit -> generate_images_core -> SSE/DB 回写`。问题不在主线缺失，而在 member 侧编排层过宽、图片上下文有两套判断、LLM/图片客户端调用分散、桌面打包入口未纳入统一脚本。

## 路径覆盖

- `members/artist/backend/app`
- `members/artist/backend/tests`
- `members/artist/desktop`
- `members/artist/build.py`
- `members/artist/LamArtist.spec`
- 必要调用方：`core/src/lamtools_core/*`、`scripts/dev.ps1`、`scripts/member_cli.py`、`scripts/build.ps1`、`artist.cmd`
- 参考计划：`docs/architecture-audit/2026-07-08-structure-organization-plan.md`

本报告只读分析，未改文件，未运行测试。

## 主要职责和入口

- 后端应用入口：`app.main` 用 Core 工厂创建 FastAPI，但关闭通用 Core routes，再挂 Artist 自己的路由和 `/api/core` 适配层。
- 会话主入口：`/api/sessions/{id}/artist-turn` 设置 `generating`，后台调用生成主线；`/generate` 只是转发；`/messages` 只写消息，不触发生成。
- Core 工作台适配：`/api/core/sessions/*` 直接映射 Artist DB、事件、用量，不使用 Core 自带 in-memory router。
- 生成包装：`handle_generate()` 已收敛为 `handle_artist_generate()`，直达生成不是独立旧路径。
- Artist 业务编排：`handle_artist_generate()` 负责写用户消息、选 provider、构建历史/lineage/workspace、启动任务事件、调用 `artist_orchestrate()`、保存 assistant 消息和刷新 lineage/workspace。
- Kernel 主线：`ArtistKit` 承接业务 prompt、工具、验证、回写；`run_core_kernel()` 实例化 `CoreLoopKernel`。
- 图片生成：`generate_images_core()` 负责 provider 查找、解密、文本生成、图生图、视觉兜底和本地缓存。
- 执行器：`ExecutionEngine` 仍存在计划/步骤执行路径，内部也调用 `generate_images_core()`。
- SSE：Artist 复用 Core 的 `RuntimeEventHub`，member 侧包一层 `TaskEventStream` 和 `stream_session_events()`。
- CLI：`artist.cmd -> scripts/member_cli.py -> python -m app.cli`，CLI 最终也走 `handle_artist_generate()`；另有 `image` 直达图片命令。
- 桌面：`desktop/main.py` 找端口、启动 `ServerManager`、打开 webview；`desktop/server.py` 同样启动 `app.main:app`。

## 可靠

- `CoreLoopKernel + ArtistKit` 是当前主线，符合“Kernel 管流程、Kit 管业务”；测试直接覆盖 Kit 方法、工具执行、VLM adapter、Kernel 运行和事件。
- 会话生命周期已按业务入口落库：启动为 `generating`，完成为 `idle`，失败为 `error`；测试覆盖等待任务结束后再改状态。
- `generate_images_core()` 作为无会话副作用的图片生成内核是有价值的深模块雏形；执行器和 ArtistKit 都可复用它。
- 桌面运行和 dev 后端入口一致，都是 `app.main:app`，数据目录通过 `LAMARTIST_DATA_DIR` 注入。
- `/api/core` 适配层保护了 Artist DB 形状，不把 ORM/密钥暴露给共享工作台；相关测试覆盖 session、message、event、provider、usage。

## 存疑

- `artist_orchestrate()` 约 804 行，接口参数 20 个左右，同时做视觉上下文、LLM 流、执行器桥接、图片生成桥接、事件桥接、Kernel 结果转 Artist 消息。它是主线，但模块深度不够，维护局部性差。
- `handle_artist_generate()` 约 382 行，承担入口、provider、历史、lineage、任务事件、落库、workspace 刷新，已经超过“入口协调”的合理范围。
- 图片上下文存在两套逻辑：`ImageContextResolver` 一套，`artist_service._select_session_images_for_turn()` 又一套；并且源码注释明确 Artist path 跳过 `_apply_image_context_resolution`。
- LLM 客户端调用分散：`LLMClient` 在 provider 测试、Artist 编排、视觉描述、图片上下文 LLM 判断、CLI VLM 中被多处直接构造；adapter 层又包一层 Core LLM 协议。
- `ExecutionEngine` 仍像历史计划执行路径；当前主线是 Kernel/Kit，但 Artist 编排里还保留 `_execution_engine_run()`。需要确认是否仍被模型工具实际调用。
- `test_artist_hook_context_contract.py` 名称仍保留 Hook 语义，内容实际在测 Kit context 注入；命名会误导后续 agent 以为 Hook 层仍是架构资产。

## 债务

- `artist_service.py` 是最大债务点：入口太宽，不是新增抽象问题，而是需要把已存在职责移回已有模块。
- `generate_service.py` 同时是入口协调、图片生成内核、图片上下文解析、消息落库和 lineage 辅助，服务名和职责不匹配。
- `/api/core` 适配层与 `core/src/lamtools_core/http/routes.py` 有协议重叠；目前因为 Core router 是 in-memory 默认实现，Artist 自建适配合理，但协议字段和事件形状应尽量回收为 Core 可复用 mapper/contract。
- `build.py` 和 `scripts/build.ps1 artist` 不一致：通用脚本只构建前端，桌面包要单独跑 `members/artist/build.py`；这会让“构建 Artist”在团队语义上不唯一。
- `LamArtist.spec` 写死 Python 3.14 dll 路径，属于机器绑定打包债务。

## 重构/优化建议

### P0

- 确认并删除/改名 Hook 语义测试。若测试仍有效，改成 Kit context contract；若覆盖已被 Kit 单测包含，合并到 Kit 测试，避免恢复 Hook 式平行层。
- 收敛图片上下文到一个入口。优先让 Artist 主线也显式使用 `ImageContextResolver` 或把 `_select_session_images_for_turn()` 合并进去；不要保留两套“判断这张/原图/整套”的业务规则。
- 给 `artist_orchestrate()` 做减法拆出已有职责，不新增大框架：LLM 调用桥、图片生成桥、SSE 发布桥、Kernel 结果转 Artist 消息这四块先移到现有 `core/artist/*` 或 `services/*` 小模块。

### P1

- 把 `handle_artist_generate()` 缩回“业务入口协调”：provider 解析、上下文构建、调用编排、保存结果；lineage/workspace 刷新和 assistant metadata 组装独立成已有服务函数。
- 统一 LLM/图片客户端创建路径，至少在 Artist member 内形成一个 provider client resolver；Core adapter 只拿 callable/client，不再关心 base_url/api_key 细节。
- 核对 `ExecutionEngine` 是否仍为活路径。若只剩历史计划执行，删除或降级为测试/实验；若仍活跃，把它挂到 Kit 工具分发下，不放在 `artist_orchestrate()` 内部闭包。

### P2

- 让 `scripts/build.ps1 artist` 能明确选择“前端构建”或“桌面包”，或者在输出中提示桌面包入口；避免两个构建入口各说各话。
- PyInstaller spec 去机器路径，改成从当前 Python/环境解析，或在 build.py 中生成/校验该路径。

## 不建议现在做

- 不建议把 Artist 业务下沉到 Core。Artist 的 persona、图片上下文、lineage、视觉工作区都应留在 member。
- 不建议恢复 Hook 层或新增平行运行时。当前主线已经是 Kernel/Kit。
- 不建议先大拆 CoreLoopKernel。当前更大的风险在 member 侧编排和协议投影重复。
- 不建议现在引入全新 Agent 框架。先把现有 OpenAI-style payload、Core LLM 协议、RuntimeEventHub、Kit 接口用深。

## 需要主线程核对的证据

- `artist_orchestrate`、`handle_artist_generate`、`ImageContextResolver.resolve_image_context` 是当前 Artist 后端的主要复杂度来源。
- `/api/sessions/{id}/messages` 不触发任务，`/artist-turn` 才触发任务；前端/CLI/文档若混用会造成“消息成功但不生成”。
- Artist path 跳过 `_apply_image_context_resolution` 的注释说明上下文解析链路已分叉，需要决定合并方向。
- `scripts/dev.ps1 artist backend` 与桌面都运行 `app.main:app`，运行入口一致；`scripts/build.ps1 artist` 与 `members/artist/build.py` 打包语义不一致。
- `test_artist_execution_engine_e2e.py` 声称 Artist delegates to ExecutionEngine，但当前主线证据显示 Kernel/Kit 是主线；需核对该 E2E 是否仍代表真实架构。
