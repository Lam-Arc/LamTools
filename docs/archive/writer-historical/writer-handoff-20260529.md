<!-- 历史参考，不代表当前架构 -->
# Writer 修复交接文档

**日期**: 2026-05-29
**状态**: 核心修复完成，3 个 bug 待修

---

## 一、已完成的改动

### 1. 废除强制 DesignFSM，改为 LLM 自主调用工具

**问题**: DesignFSM 激活时将 `tools=None`，LLM 只能纯文本输出。GLM5.1 的 thinking 模式下推理内容在 `<think>` 块中，正则 `_extract_json_block` 无法提取 → 死循环。

**修复**: 
- `runtime.py` 不再强制激活 DesignFSM
- 始终将 `self._current_tools` 传给 LLM（`runtime.py:L305`）
- 模糊任务注入 planning prompt 引导 LLM 用 `write_checklist`（`runtime.py:L1091-1117`）
- 移除 `_extract_deliverables` 正则提取，让 LLM 自主决定交付物（`runtime.py:L175-176`）

### 2. DesignFSM 封装为 `design_architecture` 工具

**位置**:
| 文件 | 行号 | 内容 |
|------|------|------|
| `prompt_assembler.py` | L262-290 | 工具定义 (name=`design_architecture`, params=`task_description`, `mode`) |
| `runtime.py` | L1587-1684 | `_run_design_pipeline()` — handler |
| `runtime.py` | L1689-1713 | `_try_parse_json()` — 多策略 JSON 解析 |
| `runtime.py` | L1936-1940 | `_run_tool` 中注册 `elif atype == "design_architecture"` |
| `schemas.py` | L28 | WriterActionType 新增 `"design_architecture"` |
| `permission.py` | L34 | TOOL_PERMISSIONS 新增映射 |

**逻辑**: LLM 检测到复杂任务 → 调用 `design_architecture(task_description=...)` → handler 内部运行 7 轮 DesignFSM（`intent→comparable→candidates→walkthrough→revision→evaluation→adversarial`）→ 返回 winner + handoff → LLM 基于结果调用 `write_checklist`

**mode**: 默认 `"max"`（LLM 可选 `low`/`high` 但需在 task_description 中说明原因）（`runtime.py:L1598`）

**进度事件**: 每轮开始时发出 `writer_thought` 事件（中文标签如 `🧭 意图分析`）（`runtime.py:L1628-L1631`）

### 3. Self-review 解析修复

**位置**: `self_review.py:L364-400`

**问题**: `json.loads(raw)` 直接解析 LLM 输出，包含 think 块/markdown → 永远失败。

**修复**: 多策略 — 直接 JSON → ` ```json ``` ` 代码块 → 正则 `{...}` 提取 → 都失败则返回空结果。

### 4. SSE 断开不取消 runtime

**位置**:
| 文件 | 行号 | 改动 |
|------|------|------|
| `task_manager.py` | L48-54 | `unsubscribe()` 不再 cancel running task |
| `task_manager.py` | L126-137 | `register_running_task()` 不覆盖已有 task |
| `session.py` | L302-303 | `event_generator()` 中 CancelledError 不传播 cancel |
| `session.py` | L366-367 | 同上（正常路径） |

### 5. work_root 默认值

**位置**: `config.py:L67-69`

**修复前**: `Path.home()` → `C:\Users\Administrator\`
**修复后**: `Path(data_dir) / "workspace"` → `%APPDATA%/LamWriter/workspace/`

### 6. 多轮对话上下文延续

**位置**: `runtime.py:L178-196`

**修复**: 检测到 `state.task_plan.user_confirmed == True` 时跳过 `_assess_task_complexity`，设置 `loop_position = "execute"`，避免已确认计划后重新 planning。

---

## 二、待修复 Bug（3 个）

### B1: 并发请求导致多个 runtime 同时运行

**严重度**: 🔴 高

**症状**: T1 FSM 还在执行时 T2 请求到达 → 创建了第二个 `WriterRuntime.run()` → 两个 runtime 同时操作同一 session → 状态互相覆盖

**根因**: `writer_service.py:L189-192` 中 `send_message()` 只检查 `runtime.is_paused`，不检查 "runtime 是否正在执行工具（busy）"。FSM 工具执行期间 runtime 不算 paused。

**修复思路**:
1. 在 `runtime.py` 中加 `_is_busy` 标志，执行工具时设为 True
2. `writer_service.py` 的 `send_message()` 中检查 runtime 是否 busy，如果是则将消息入队等待

### B2: 中文计划确认消息未被识别

**严重度**: 🔴 高

**症状**: 用户发 `"确认计划，开始执行。"` → Writer 显示 "user requested plan changes" → 重新 planning → 死循环

**根因**: `runtime.py:L1129-1148` 中 `_is_plan_confirmation()` 对超过 30 字符的消息只做 `startswith` 匹配，`"确认计划，开始执行。"` 长度 36 字符。`"确认"` 在 `confirmation_keywords` 元组中但只在 `if len(lower) <= 30` 短消息分支中做包含匹配。

**修复思路**: 对超过 30 字符的消息也做包含匹配（`"确认" in lower` 等），或改为始终做包含匹配，不按长度分分支。

### B3: FSM 工具过慢 + API 波动阻塞

**严重度**: 🟡 中

**症状**: candidates 轮生成 20K+ 字符耗时 5-10 分钟。API 500 重试时整体 7 轮需要 20+ 分钟。SSE 连接超时后 runtime 被误判为完成。

**修复点**: `runtime.py:L1605-1608` — 给 `chat_full()` 加 `asyncio.wait_for(..., timeout=120)` 超时保护，超时走 degraded continue。

---

## 三、关键文件索引

| 文件 | 关键行 | 作用 |
|------|--------|------|
| `app/core/writer/runtime.py` | L154-238 | `run()` 主循环入口 |
| `app/core/writer/runtime.py` | L178-196 | 上下文延续逻辑 |
| `app/core/writer/runtime.py` | L303-305 | LLM 调用（tools 传递） |
| `app/core/writer/runtime.py` | L344-372 | 响应解析分支 |
| `app/core/writer/runtime.py` | L540-695 | Planning Gate（plan 确认/自动确认） |
| `app/core/writer/runtime.py` | L1091-1117 | `_build_planning_prompt()` |
| `app/core/writer/runtime.py` | L1129-1148 | `_is_plan_confirmation()` ← B2 位置 |
| `app/core/writer/runtime.py` | L1587-1713 | `_run_design_pipeline()` + `_try_parse_json()` |
| `app/core/writer/runtime.py` | L1719-1940 | `_run_tool()` 各工具处理 |
| `app/core/writer/design_fsm.py` | 全文 | 7 轮 FSM（未经修改） |
| `app/core/prompt_assembler.py` | L262-290 | `design_architecture` 工具定义 |
| `app/core/prompt_assembler.py` | L419-422 | `get_tools()` |
| `app/services/writer_service.py` | L180-252 | `send_message()` ← B1 位置 |
| `app/services/task_manager.py` | L48-54 | `unsubscribe()` |
| `app/routers/session.py` | L240-372 | SSE chat 路由 |
| `app/config.py` | L67-69 | work_root 默认值 |

---

## 四、验证方法

### 快速验证（5 分钟）
```powershell
# 启动后端
cd e:\LamTools\members\writer\backend
py -3.14 -m uvicorn app.main:app --reload --port 6173

# 另一端测试
$sid = (iwr -Uri http://localhost:6173/api/sessions -Method POST -ContentType 'application/json' -Body '{"title":"test"}' -UseBasicParsing | ConvertFrom-Json).id
# 发送消息，用 curl 或 Postman 连 SSE
```

### 完整回归测试（B1+B2 修复后）
```powershell
cd e:\LamTools\members\writer\backend
powershell -ExecutionPolicy Bypass -File regression_suite.ps1
```

期望：T1-T5 全部 PASS，FSM 进度事件可见，文件交付物 ≥ 4 个在 `%APPDATA%/LamWriter/workspace/poll-system/` 下。

### 验证清单
- [ ] 模糊任务：Writer 调用 `design_architecture` → FSM 7 轮 → `write_checklist`
- [ ] 简单任务：Writer 跳过 FSM 直接 `write_checklist`
- [ ] Plan 确认：中文 "确认" 触发执行
- [ ] 多轮对话：后续消息不重新 planning
- [ ] 文件创建：文件写入 `workspace/` 下正确路径
- [ ] SSE 断开重连：paused runtime 存活，resume 正常

---

## 五、已知限制

1. **FSM 全量跑需要 10-20 分钟**（取决于 API 速度）。B3 修复后单轮上限 120s，总上限约 14 分钟。
2. **`acceptance_criteria` 仍为空**。`write_checklist` 的参数只有 `files` 和 `design_summary`，没有 criteria 字段。需要拓展工具定义或在 planning prompt 中要求 LLM 将 criteria 写入 design_summary。
3. **Git 分支/提交功能未实现**。只有 `git_status` 和 `git_diff` 只读工具。
4. **Permission 系统为 MVP 模式**：所有 `ask_user` tier 操作自动批准（`permission.py:L102-103`）。

---

## 六、测试脚本位置

| 脚本 | 路径 | 用途 |
|------|------|------|
| 完整回归测试 | `regression_suite.ps1` | T1-T5 8 项断言 |
| FSM 单次测试 | `test_design_tool.ps1` | 只测 design_architecture 工具 |
| B1+B2 快速修补后验证 | `quick_verify.ps1` | 两轮对话测上下文延续 |
| SSE 事件采集 | `run_all_phases_v3.ps1` | 13 阶段全量事件采集 |
| 日志 | `%APPDATA%/LamWriter/lamwriter.log` | LLM 调用链、错误 |
| 状态文件 | `%APPDATA%/LamWriter/states/{session_id}.json` | 会话状态快照 |
