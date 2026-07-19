# Core-first 接线实施后验收报告（2026-07-09）

## 结论

Core 现在可以作为基础 Agent 使用：有独立 CLI、独立运行库、共享配置读取、默认工具箱、权限策略、插件 Hook 装配、MCP registry、sub-agent runner 和事件落库。Writer 变成 Core 的 member overlay：继续保留 Writer persona、业务投影、专用工具和转录数据，但 Provider / Model / 通用 app_settings / 通用 adapter profile 不再重复放在 Writer 运行库里。

## 已完成接线

1. Core CLI 独立入口：`core.cmd run` 直接装配 Core Kernel、默认工具箱、HookEngine、MCP、sub-agent runner 和 Core DB。
2. Core 默认工具箱：文件读写、搜索、命令、测试、Git、Web、MCP、sub-agent 由 Core 统一生成工具规格、执行器和权限。
3. 权限基础：Core 默认权限表统一管理通用工具；`--auto-approve` 用于验收链路，默认策略仍可要求审批。
4. 插件 / Hook：Core CLI 运行时会扫描插件根，构造 HookEngine，并把 skill roots、MCP files、agent roots 注入运行链路。
5. Hook：`command`、`http`、`prompt`、`mcp` 四类 handler 均进入 Core HookEngine；`http/mcp` 读取同款 JSON 决策，`prompt` 注入额外上下文。
6. Skill：Core 默认工具箱提供通用 `load_skill`，模型请求会带可用 skill 索引；加载后 skill 目录成为可读资源根，命令工具也能解析已加载 skill 的脚本路径。
7. MCP / SubAgent：可运行 registry/client/runner 已下沉 Core；Writer 的 MCP 层改为兼容导入，不再维护完整重复实现。
8. 存储：共享配置库为 `data/lamtools.db`；Core 运行库为 `data/core.db`；Writer 运行库为 `members/writer/data/lamwriter.db` 或显式 `LAMWRITER_DATA_DIR`。
9. Writer overlay：Writer 运行时解析模型走共享配置库；Writer DB 只保留会话、消息、事件、快照、转录、产物等 member 数据。
10. Adapter profile：通用 profile 放到 `core/llm_adapters/`；Writer 只保留 member overlay 和用户/runtime 目录。

## 数据库分类

| 数据库 | 定位 | 本轮验收 |
|---|---|---|
| `data/lamtools.db` | 共享配置库，Provider / Model / 通用 app_settings | 有 Kimi-K2.6 模型记录；不打印 API Key。 |
| `data/core.db` | Core CLI / Core Agent 事件与快照 | Core CLI 真实 run 写入该库。 |
| `members/writer/data/lamwriter.db` | Writer member 运行和业务数据 | 不再要求保存 Provider / Model。 |
| `LAMWRITER_DATA_DIR` 指向的库 | Writer 隔离验收运行库 | fresh DB 中 `llm_providers=0`、`llm_models=0`、`app_settings=0`，但 Writer 真实调用仍完成。 |

## 真实入口验收

Core CLI 真实调用：

- 命令入口：`.\core.cmd run`
- 模型：Kimi-K2.6，model record `906d775ffa9f489e86c74b3d42451631`
- 产物：`.acceptance/core-runtime/core-proof.md`
- 证据：`thinking=True`、`text=True`、`tool=write_file`、`rounds=2`、文档超过 10 行
- 摘要：`.acceptance/core-cli-proof/summary.json`

Writer CLI 真实调用：

- 命令入口：`.\writer.cmd run`
- 数据目录：`.acceptance/writer-data-fresh-20260709-152615`
- 工作目录：`.acceptance/writer-runtime-fresh-20260709-152615`
- 产物：`.acceptance/writer-runtime-fresh-20260709-152615/writer-proof.md`
- fresh Writer DB 配置表：`llm_providers=0`、`llm_models=0`、`app_settings=0`
- 事件证据：会话 `completed`，事件包含 thinking、tool_call、tool_result、write_file
- 模型调用表证据：`model=xopkimik26`，thinking enabled，budget 10000

Writer GUI 真实调用：

- 前端：`http://127.0.0.1:6194`
- 后端：`http://127.0.0.1:6193`
- 数据目录：`.acceptance/gui-data-20260709-161231`
- 工作目录：`.acceptance/gui-work-20260709-161231`
- 会话：`bf5db8884ef547398cec240fda88b3b1`
- 浏览器证据：Chrome + Playwright 打开页面、点击新会话、在输入框提交任务；控制台无 page error。
- 运行证据：session `completed`，事件包含 thinking、tool_call、tool_result、write_file。
- 产物：`.acceptance/gui-work-20260709-161231/gui-proof.md`，13 行。
- 截图：`.acceptance/gui-proof-completed-20260709-161231.png`

## 自动化验证

- `git diff --check`：通过，只有 CRLF 工作区提示。
- `py -3.14 -m pytest core/tests -q`：600 passed。
- `py -3.14 -m pytest members/writer/backend/tests -q`：690 passed，只有 Windows asyncio closed pipe 警告。

## 当前剩余风险

1. GUI 已完成真实浏览器验收，不再是当前不确定点。
2. Hook handler 的 `http/mcp/prompt` 已补最小闭环；后续只需要按具体产品需求扩展高级语义。
3. Writer 仍保留部分展示和业务投影代码，这是 member overlay，不应继续下沉到 Core。

## 下一步建议

下一轮不再重复做 Core-first、DB 拆分、GUI 基础验收；只处理具体产品体验或高级 Hook 语义。
