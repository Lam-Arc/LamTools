# Codex 交接工单：Writer 显示丢失 + run_command Windows 失败修复

## 背景与上下文

你将接手 LamWriter（LamTools monorepo 中的成员产品）的 bug 修复工作。前序会话已完成根因调查并用真实会话日志验证，结论确凿，你无需重新调查，直接按下面的任务清单执行即可。

**仓库**：`E:\LamTools`（Windows，git 仓库，当前分支 `master`）

**Monorepo 结构**（见 `AGENTS.md`）：
- `core/` — 通用协议、运行骨架、共享 UI（**不认产品名**，不得出现 `if product ==` 分支）
- `members/writer/` — Writer 产品完整实现
  - `backend/` — Python FastAPI + SQLite（aiosqlite）
  - `frontend/` — Vue 3 + Pinia + SSE

**架构原则**（必须遵守）：
1. Kernel 管流程（循环/调模型/存状态），Kit 管业务（上下文/工具/验收）。
2. `core/src/lamtools_core/` 中不得出现 Writer/Artist 产品名。
3. 单产品能力留 member，双产品共需才抽 core。

**验证入口**：
- 后端测试：`.\scripts\test.ps1 all`，或进 `members/writer/backend` 跑 `pytest`
- 前端：`members/writer/frontend`，`npm run build` 验证类型
- 手动验证用真实数据库：`C:\Users\Administrator\AppData\Roaming\LamWriter\lamwriter.db`

---

## 调查结论速查（已用 session `7e637ede` 验证）

session `7e637ede` 的任务「开发一个网页来分享我开发的mod，支持网友评论留言」在 Windows 上完整复现了所有问题。数据库 `writer_runtime_events` 表确认：

1. **LLM 5 段回复全文都在 `preview` 字段里**，但 `writer_messages` 表只有最后一段被持久化为 assistant 消息。
2. **`run_command` 连续失败 4 次**（`python -m pip install flask` → `where python` → `py --version` → `cmd /c ver`），全部 `status=failed`，但 `writer_steps.error` 字段**全空**，导致 LLM 盲目重试直到 `Max repair attempts (3) reached`。
3. 回复在前端显示两遍（同一段文字出现两次）。

---

## 修复任务（按优先级执行）

### 🔴 任务 1（最高优先级）：run_command 在 Windows 下失败 + 错误丢失

**现象**：`run_command` 在 Windows 上几乎对任何命令都失败，且失败原因不回传给 LLM，形成「瞎重试→触顶失败」死循环。

**根因证据**：
- `members/writer/backend/app/core/writer/core_kernel_adapter.py:1069` 的 `run_command` 方法用 `shlex.split(command)`（Unix 语义）+ `asyncio.create_subprocess_exec`（不经过 shell）。
  - Windows 上 `python`/`where`/`py` 这类依赖 PATH 查找的可执行、以及 `cmd /c ver` 这种 shell 内置，会触发 `FileNotFoundError` 或 `OSError`。
  - `shlex.split` 用单引号/双引号的 Unix 规则拆 Windows 命令，遇到含空格路径会拆错。
- `members/writer/backend/app/services/writer_service.py:465`（`runtime.tool.finished` 分支）记录 step 时，error 来自 `payload.get("error")`，但 core kernel 上行的事件 payload 里**没有带 ToolResult.error 的原文**——需要确认 core kernel 的 tool.finished 事件是否把 `ToolResult.error` 放进了 payload，如果没有，要在 core 侧补上。
- 对照真实日志：`writer_steps` 表里 4 次 run_command 失败的 `error` 列全是 `"Tool execution error: "`（冒号后空白），证明错误内容在某一层被丢掉了。

**期望行为**：
1. `run_command` 在 Windows 上能正确执行常见命令：PATH 上的可执行（`python`、`node`、`git`）、shell 内置（`dir`、`ver`、`where`）、管道和重定向（`|`、`>`、`&&`）。
2. 任何失败（FileNotFoundError、超时、非零退出码）的**完整错误信息**必须回传给 LLM，写入 `ToolResult.error`，并最终出现在 `writer_steps.error` 和 SSE 的 `writer_part.tool_error` 字段里。
3. 跨平台：Linux/macOS 保持现有 `shlex.split + create_subprocess_exec` 行为不变，只对 Windows 走 shell 路径。

**修复方向**（实现由你决定，但建议）：
- 在 `run_command` 里判断 `sys.platform == 'win32'`，Windows 下用 `asyncio.create_subprocess_shell(command, cwd=work_root, shell=True)`（配合现有的 `_validate_command_paths` 做路径校验，破坏性命令黑名单仍生效）。或者用 `cmd /c <command>` 包一层再 `create_subprocess_exec`。
- 保留并加强 `_validate_command_paths` 与破坏性命令检测（`permission.py` 的 `BLOCKED_COMMANDS`、`guardrail.py` 的 `_is_dangerous_command`）。
- 修复错误回传链路：确保 `ToolResult.error` 的原文一路传到 `writer_steps.error`。检查 `core_kernel_adapter.py` 的 tool 事件构造、`writer_service.py:465` 的 payload 提取、`events.py` 的 `make_step_event`。
- 超时分支（`core_kernel_adapter.py:1142`）已返回 `error=f"Command timed out after {timeout}s"`，确认这条也进了 DB。

**验收**：在 `members/writer/backend` 跑真实命令测试——新建或扩展 `tests/test_writer_core_kernel_adapter.py`，断言 Windows 下 `run_command("python --version")` 或 `run_command("cmd /c ver")` 返回 `status="ok"`；断言失败时 `ToolResult.error` 非空且包含可读原因。

---

### 🟠 任务 2：回复重复显示两遍

**现象**：每段 LLM 回复在前端出现两次（如「我来帮你开发... 我来帮你开发...」）。

**根因证据**：后端对每轮回复**同时发两条 SSE**：
- `members/writer/backend/app/services/writer_service.py:374`（`runtime.reply_delta` 分支）发 `writer_reply_delta`
- `members/writer/backend/app/services/writer_service.py:389`（`runtime.reply` 分支）发 `final` 标记的 `writer_reply_delta` **外加** `writer_response(output_type="reply")`（`:404`）

前端两条路径都往同一个 `assistantDraft` 追加：
- `members/writer/frontend/src/stores/sse.ts:499`（`writer_reply_delta`）`assistantDraft.value += event.delta`
- `members/writer/frontend/src/stores/sse.ts:266`（`writer_response` reply 分支）`assistantDraft.value += ...replyText`

**期望行为**：每段回复只显示一次。

**修复方向**（二选一，推荐前者）：
- **推荐**：前端 `writer_response` 的 reply 分支改为「仅当 `assistantDraft` 不已包含该文本时才追加」，或者干脆在收到 `final` 后用 `writer_response` 的完整文本**替换**而非追加。注意 `sse.ts:274` 已经按 `output_meta.final` 区分了 append 逻辑，问题是它和 delta 路径同时累加——需要让两者互斥。
- 或：后端不再同时发 `writer_reply_delta(final)` 和 `writer_response(reply)`，二选一。但要小心 CLI/TUI 客户端（`members/writer/backend/writer_tui/`）可能依赖其中一条，改后端前先 grep 确认消费方。

**验收**：手动跑一个任务，确认每段回复只出现一次；`npm run build` 通过。

---

### 🟠 任务 3：中断/结束后内容消失

**现象**：运行结束（哪怕是正常 done）或用户点「停止」后，之前流式显示的回复内容大量消失，只剩截断片段。

**根因证据**：
- `members/writer/frontend/src/stores/sse.ts` 所有终止分支都执行 `assistantDraft.value = ''`：`:382`（lifecycle done）、`:391`（failed）、`:401`（error）、`:409`（cancelled）、`:212`（stopStream）。
- 后端 `writer_turn` 事件里 `model_reply` 被**截断到 500 字符**：`members/writer/backend/app/services/writer_service.py:685` `model_reply=turn_reply[:500]`。
- 前端 `CoreWorkbenchView.vue:340` 用 `turn.model_reply` 作为 turn 消息的 content，所以恢复后只剩 500 字。

**期望行为**：
1. 运行结束后，已生成的回复内容应完整保留（从持久化的 message/turn 恢复），不被清空成空白。
2. `writer_turn` 的 `model_reply` 不再截断，或至少放宽到合理的长度（如 8000）。

**修复方向**：
- 后端：`writer_service.py:685` 去掉 `[:500]` 或改大。同时确认 `runtime.reply`（`:389`）的完整 content 被持久化为 `writer_messages` 的 assistant 消息——当前 session 7e637ede 只有最后一段进了 messages 表，说明中间轮的 reply 没有落库。检查 `send_message` / kernel 结束时是否把每轮 reply 存成 message。
- 前端：`sse.ts` 的终止分支不要无条件清空 `assistantDraft`。改为：在收到 `writer_turn`/`writer_lifecycle done` 后，等持久化消息从 API 刷新回来（`CoreWorkbenchView.vue:663` 的 `getCoreMessages`）再清空 draft。或者保留 draft 作为 fallback 直到刷新完成。

**验收**：跑一个多轮任务，中途点「停止」，确认已显示的回复不消失；任务正常完成后刷新页面，所有轮次回复完整可见。

---

### 🟡 任务 4：plan/thinking 过程不可见

**现象**：LLM 的规划、思考过程（plan、thought、reasoning）在前端完全看不到。

**根因证据**：
- 后端 `writer_service.py` 的 `_publish_live_core_event`（约 `:344` 起）只处理了这些 core 事件：`runtime.started`、`runtime.reply_delta`、`runtime.reply`、`runtime.tool.started`、`runtime.tool.finished`、`runtime.verification`、`runtime.repair`、`runtime.done`、`runtime.failed`、`runtime.waiting`、`runtime.part`。
- **没有** `runtime.thinking` / `runtime.thought` / `runtime.plan` 分支——core kernel 若 emit 这些事件，会落到函数末尾默认分支（只记 DB `writer_runtime_events`，不发 SSE）。
- 前端 `sse.ts:1075` 的 `normalizeReplyText` 把每段回复截到 200 字符、最多 5 段、总 500 字符。`sse.ts:889` 的 `visibleActivityText` 也有 `.slice(0, 240)`。

**期望行为**：LLM 的思考/规划过程能实时显示在前端（可折叠的「思考」区域，参考 `display.py` 的 fold policy：think 类默认折叠、verbose 时展开）。

**修复方向**：
- 后端：在 `writer_service.py` 的 `_publish_live_core_event` 加 `runtime.thinking` 分支，发 `writer_response(output_type="thought", text=...)`（前端 `sse.ts:282` 已有 thought 分支处理）。确认 core kernel 确实会 emit `runtime.thinking`——若不会，需在 `core/src/lamtools_core/kernel/` 的 loop/adapter 里补 emit。
- 前端：放宽或去掉 `normalizeReplyText`（`sse.ts:1075`）和 `visibleActivityText`（`:889`）的截断，改为「显示完整内容 + CSS 折叠」。`display.py` 已有完整的 fold policy 设计（think=done 折叠、reply=live 显示），可作为参考。

**验收**：跑任务时能看到 LLM 的思考过程（折叠态），展开可见完整文本。

---

### 🟡 任务 5：scope_guard 对常见 Web 栈误杀

**现象**：任务文本含「网页/网站/app」等词时，`scope_guard` 强制走「零依赖」模式，写 `.py` 文件 import flask/fastapi 等会被 `WRITE REJECTED`，逼 LLM 走它不擅长的纯标准库路线，增加失败概率。

**根因证据**：`members/writer/backend/app/core/writer/scope_guard.py`
- `:340` `looks_like_software_creation_task` 关键词包含「网站/网页/应用/前端」等，命中范围过宽。
- `:191` `content_scope_rejection` 在写 `.py` 文件时，若 import 了 flask/fastapi/django/sqlalchemy 等（`:247` blocked 集合），直接拒绝。
- `:120` `plan_scope_rejection` 对含 heavy_markers 的计划整体拒绝。

**期望行为**：
1. 用户没明确要求「零依赖/离线/无安装」时，不应默认拦截常见 Web 栈。scope_guard 的零依赖策略应作为**提示**而非**硬阻断**，或仅当用户任务隐含离线约束时才启用。
2. 至少不要因为 scope_guard 拦截写文件，导致 LLM 转而用 run_command 装依赖时又触发任务 1 的失败链。

**修复方向**：
- 收紧 `looks_like_software_creation_task` 的触发条件，或给 scope_guard 加一个「显式离线/零依赖」标志位，默认关闭硬拦截。
- 把 `content_scope_rejection` 对 flask 等常见栈的拦截改为「返回警告 hint 但允许写入」，让 LLM 自己决定。
- 注意：这个任务的优先级低于任务 1，且改动涉及 Writer 的安全哲学（避免 LLM 引入重依赖）。改动前先读 `scope_guard.py` 顶部的注释和 `members/writer/AGENTS.md` 理解设计意图，不要破坏离线/零依赖的验收能力。

**验收**：跑「开发一个带评论的 mod 分享网页」这类任务，LLM 能正常用 flask/fastapi 完成而不被 WRITE REJECTED；现有的「零依赖」测试（若 `tests/` 里有）仍通过。

---

## 执行顺序与建议

1. **先做任务 1**——这是 Writer 在 Windows 上「基本不可用」的根本原因，其他任务的价值都依赖它能跑起来。
2. 任务 2、3 一起做（都涉及 SSE 回复链路，改一处可同时解决）。
3. 任务 4 次之（体验优化）。
4. 任务 5 最后，且要谨慎（涉及安全策略）。

每完成一个任务，跑一次相关测试再继续。改 `core/` 前确认不影响 Artist（`members/artist/`）。

## 需要你额外探索确认的点

- core kernel（`core/src/lamtools_core/kernel/loop.py`、`llm/adapter.py`）是否真的 emit `runtime.thinking` 事件？若不发，任务 4 需要 core 侧补 emit。
- `ToolResult.error` 在 core kernel 的 tool.finished 事件 payload 里到底叫什么字段？任务 1 的错误回传修复依赖这个。在 `core/src/lamtools_core/kernel/` 里 grep `tool.finished` / `ToolResult` 确认。
- CLI/TUI（`members/writer/backend/writer_tui/`）消费哪些 SSE 事件？改后端事件前 grep 确认不破坏 CLI。

## 不要做的事

- 不要进旧的 `E:\LamToolsCore`、`E:\LamWriter`、`E:\LamArtist` 改东西（已废弃，见 `AGENTS.md`）。
- 不要为了修显示问题去删 SSE 事件类型——保持 7 个 canonical 事件不变，只调整内容/时机。
- 不要在 `core/src/lamtools_core/` 里写 Writer 产品名或 `if product ==` 分支。
- commit 前确认 `git status`，只提交相关改动，不要把 `test-*` 目录、截图、`nul` 文件等杂物一起提交（当前 working tree 已有很多未跟踪的测试产物）。
