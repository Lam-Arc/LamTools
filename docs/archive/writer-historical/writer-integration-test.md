# Writer Integration Test: Developer Onboarding Kit

> OpenCode 作为测试者，模拟用户对 Writer 发消息，观察 SSE 事件流，断言 Writer 行为。
> 贯穿 Writer 除 Novel/协作外的所有功能。

## 前置条件

1. 后端已启动：`cd backend && py -3.14 -m uvicorn app.main:app --reload --port 6173`
2. 确认 API 可达：`curl http://localhost:6173/api/sessions` 返回 `[]`
3. OpenCode 有 bash 工具可用

## API 协议速查

| 操作 | 方法 | 路径 | Body |
|------|------|------|------|
| 创建会话 | POST | `/api/sessions` | `{"title": "onboarding-kit-test"}` |
| 发消息 | POST | `/api/sessions/{id}/chat` | `{"message": "..."}` |
| 恢复暂停 | POST | `/api/sessions/{id}/chat` | `{"message": "确认"}` |
| 取消 | POST | `/api/sessions/{id}/cancel` | — |

### SSE 事件（发消息后的 EventSource 流）

当前前后端以 canonical 事件为准。旧事件名只作为兼容别名保留，测试断言不要再依赖旧名。

| 事件名 | 含义 | 关键字段 |
|--------|------|---------|
| `writer_response` | Writer 回复文本 | `data.text`, `data.output_type`, `data.output_meta` |
| `writer_step` | 工具、验证、Part 状态变化 | `data.step.step_type`, `data.step.status`, `data.step.tool_name`, `data.step.tool_args`, `data.session_id` |
| `writer_progress` | 阶段、模式、计划进度、验证、Workflow | `data.phase`, `data.mode`, `data.plan_progress`, `data.verification`, `data.workflow`, `data.session_id` |
| `writer_decision` | 计划确认、暂停、决策点 | `data.decision_type`, `data.title`, `data.options`, `data.context`, `data.session_id` |
| `writer_git` | Git 分支、checkpoint、merge、snapshot | `data.git_type`, `data.data`, `data.session_id` |
| `writer_lifecycle` | 完成、失败、异常、取消、恢复 | `data.lifecycle_type`, `data.reason`, `data.details`, `data.session_id` |
| `ping` | 保活 | — |
| `connected` | SSE 连接建立 | `data.session_id` |

旧名映射：`writer_mode_changed` / `writer_phase_changed` / `writer_progress` 旧 progress 统一看 `writer_progress`；`writer_plan_ready` / `writer_waiting_for_user` 统一看 `writer_decision`；`writer_action_*` / `writer_part_updated` / `writer_criteria_verified` 统一看 `writer_step`；`writer_workflow` 统一看 `writer_progress.workflow`；`writer_done` / `writer_error` / `writer_failed` / `writer_resumed` 统一看 `writer_lifecycle`。

---

## 测试脚本

### 初始化：创建会话

```bash
# Step 0: 创建测试会话
SESSION=$(curl -s -X POST http://localhost:6173/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"title": "onboarding-kit-test"}')
SESSION_ID=$(echo $SESSION | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Session ID: $SESSION_ID"
```

---

### Phase 1: EXECUTE — Planning Gate

**目的**：验证 Writer 收到模糊任务后自动进入 planning、生成 TaskPlan、等用户确认。

**发消息**：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "帮我搭建一个开发者入职包，包括快速启动脚本、架构概览文档、示例API测试、项目结构可视化。项目是LamWriter自身。"}'
```

**断言**（观察 SSE 事件流）：

- [ ] 收到 `writer_progress` → data.mode = "EXECUTE"（或自动切到执行模式）
- [ ] 收到 `writer_decision` → data.decision_type = "plan_ready"，data.context.plan 包含至少 4 个 step
- [ ] plan 中包含 deliverable 列表：quickstart.sh / onboarding-guide.md / test / project-structure
- [ ] 收到 `writer_decision` → data.decision_type 包含 "waiting" 或 "plan_ready"
- [ ] 收到 `writer_response` → data.text 提到计划或步骤概要
- [ ] 如果触发 DesignFSM：收到 `writer_step` → data.step.step_type = "verification"

**恢复**：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "确认计划，开始执行。"}'
```

---

### Phase 2: BRAINSTORM — 中途发散

**目的**：验证 BRAINSTORM 模式切换、发散思考、不停留在执行。

**发消息**：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "入职包还应该包含什么？我没想清楚。"}'
```

**断言**：

- [ ] 收到 `writer_progress` → data.mode = "BRAINSTORM"
- [ ] 收到 `writer_response` → data.text 包含 3+ 个方向建议
- [ ] Writer 不执行任何写操作（无 `writer_step` 的 write_file/edit_file running 步骤）
- [ ] 收到 `writer_decision`（等用户选择）

**恢复**：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "加上常见坑指南和CON术语速查表。继续执行。"}'
```

---

### Phase 3: DECISION — 技术选型

**目的**：验证 DECISION 模式、tradeoff 分析、明确推荐。

**发消息**：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "架构概览用Markdown还是做成交互式Vue页面？"}'
```

**断言**：

- [ ] 收到 `writer_progress` → data.mode = "DECISION"
- [ ] 收到 `writer_response` → data.text 包含至少 2 种方案的对比
- [ ] Writer 给出明确推荐（不是"都可以"）
- [ ] 收到 `writer_decision`

**恢复**：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "用Markdown + Mermaid。继续。"}'
```

---

### Phase 4: EXECUTE — Step 1 quickstart.sh

**目的**：验证 EXECUTE 循环、SelfReview(code)、Memory writeback、TaskPlan 推进。

**观察**（Writer 自主执行，不需要发消息）：

- [ ] 收到 `writer_step` → data.step.tool_name = "read_file"（读 AGENTS.md 等）
- [ ] 收到 `writer_step` → data.step.tool_name = "write_file"，data.step.tool_args 或 content 包含 "quickstart.sh"
- [ ] 收到 `writer_step` → data.step.status 变化：pending → running → completed
- [ ] 收到 `writer_response` → data.text 提到 SelfReview 发现的问题（如缺少 Python 版本检查）
- [ ] 如果 SelfReview 触发修复：收到 `writer_step` → data.step.tool_name = "edit_file"
- [ ] 收到 `writer_progress` → data.plan_progress.completed 推进到 2
- [ ] 文件 `scripts/quickstart.sh` 实际存在于磁盘

---

### Phase 5: TEACH — 知识讲解

**目的**：验证 TEACH 模式、allowed_actions 限制、类比解释。

**发消息**（在 Writer 完成 Step 1 后的等待点，或主动发消息打断）：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "我不懂Writer的CON六层结构。"}'
```

**断言**：

- [ ] 收到 `writer_progress` → data.mode = "TEACH"
- [ ] 收到 `writer_response` → data.text 包含类比解释（如"档案馆"比喻）
- [ ] Writer 不执行任何写操作（无 write_file/edit_file 的 running step）
- [ ] Writer 只使用 read_file/search_content/search_files
- [ ] 收到 `writer_decision`

**恢复**：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "明白了。继续执行。"}'
```

---

### Phase 6: EXECUTE — Step 2 onboarding-guide.md

**目的**：验证 drift detection、SelfReview(prose)、context compaction。

**观察**：

- [ ] 收到多个 `writer_step` → data.step.tool_name = "read_file"（连续读文件）
- [ ] 如果连续读 5+ 次：drift detection 触发，收到 `writer_response` → data.text 提到 nudge 或"开始写"
- [ ] 收到 `writer_step` → data.step.tool_name = "write_file"，data.step.tool_args 或 content 包含 "onboarding-guide.md"
- [ ] 收到 `writer_response` → data.text 提到 SelfReview(prose) 修改建议
- [ ] 如果 token budget 触发 compaction：后续消息中 PER 身份仍然一致（"LamWriter。24岁。匠人。"）
- [ ] 收到 `writer_progress` → data.plan_progress.completed 推进到 3
- [ ] 文件 `docs/onboarding-guide.md` 实际存在

---

### Phase 7: PROTOTYPE — 快速原型

**发消息**：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "快速出一个项目结构可视化的原型，不求完美。"}'
```

**断言**：

- [ ] 收到 `writer_progress` → data.mode = "PROTOTYPE"
- [ ] 收到 `writer_step` → data.step.tool_name = "write_file"，data.step.tool_args 或 content 包含 "project-structure.md"
- [ ] Writer 不跑测试（无 data.step.tool_name = "run_command" 且 data.step.content 包含 "pytest"）
- [ ] 快速交付，不多轮修改
- [ ] 文件 `docs/project-structure.md` 实际存在
- [ ] 内容包含 Mermaid 图

---

### Phase 8: EXECUTE — Step 3 test_onboarding_demo.py

**目的**：验证 run_command、SelfReview 修复循环、error_pattern writeback。

**发消息**（让 Writer 回到执行计划）：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "继续执行计划，写示例API测试。"}'
```

**观察**：

- [ ] 收到 `writer_step` → data.step.tool_name = "write_file"，data.step.tool_args 或 content 包含 "test_onboarding_demo.py"
- [ ] 收到 `writer_step` → data.step.tool_name = "run_command"，data.step.content 或 tool_args 包含 "pytest"
- [ ] 如果测试失败：Writer 自主修复（edit_file）→ 重新 run_command
- [ ] Memory writeback：如果出现 error_pattern，后续可查询
- [ ] 最终收到 `writer_progress` → data.plan_progress.completed 推进到 4
- [ ] 文件 `backend/tests/test_onboarding_demo.py` 实际存在
- [ ] 测试内容无 mock（项目铁律）

---

### Phase 9: EXECUTE — Step 4 邮件 + Workflow

**目的**：验证 Workflow 5 phase 流转、email domain recall、SelfReview(email)。

**发消息**：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "给团队发邮件，入职包已完成，附链接，语气客气点。"}'
```

**断言**：

- [ ] 收到 `writer_progress` → data.workflow.phase = "ideation"
- [ ] 收到 `writer_progress` → data.workflow.phase = "outlining"
- [ ] 收到 `writer_progress` → data.workflow.phase = "drafting"
- [ ] 收到 `writer_progress` → data.workflow.phase = "revising"
- [ ] 收到 `writer_progress` → data.workflow.phase = "polishing"
- [ ] 收到 `writer_response` → data.text 包含邮件草稿（Subject / To / Body）
- [ ] 收到 `writer_decision` → data.title 或 context 包含 "email" 或 "confirm"
- [ ] SelfReview(domain=email) 触发（在 revising 或 polishing 阶段）

**恢复**：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "确认邮件内容，发送。"}'
```

---

### Phase 10: REVIEW — 最终审查

**发消息**：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "帮我审一下这个入职包的整体质量。"}'
```

**断言**：

- [ ] 收到 `writer_progress` → data.mode = "REVIEW"
- [ ] Writer 只使用 read_file / search_content / search_files（无 write/edit）
- [ ] 收到 `writer_response` → data.text 包含每个产出的审查意见
- [ ] 给出评级（A/B/C）
- [ ] 列出具体缺失项
- [ ] 收到 `writer_decision`

---

### Phase 11: COMFORT — 挫折处理

**发消息**：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "quickstart.sh在Windows上跑不通，修了两天了。"}'
```

**断言**：

- [ ] 收到 `writer_progress` → data.mode = "COMFORT"
- [ ] 收到 `writer_response` → data.text 帮拆解问题，不强行鼓励
- [ ] Writer 不执行任何工具操作（allowed_actions = []）
- [ ] 自然过渡：如果用户说"帮我看看"→ Writer 切回 EXECUTE 并诊断

**恢复**：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "帮我看看具体报错。"}'
```

**断言**（COMFORT → EXECUTE 过渡）：

- [ ] 收到 `writer_progress` → data.mode = "EXECUTE"
- [ ] Writer 执行 run_command 诊断
- [ ] 发现问题并修复

---

### Phase 12: DISCUSS + 周报

**发消息**：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "做完了。帮我生成这周的入职包开发周报。"}'
```

**断言**：

- [ ] 收到 `writer_response` → data.text 包含周报格式（完成项 / 修改记录 / 发现问题 / 下一步）
- [ ] 内容从 git log + todowrite + conversation 提取（不是凭空编造）
- [ ] SelfReview(domain=prose) 或 domain=general 触发
- [ ] Memory writeback 更新产出索引

---

### Phase 13: PAIR — 结对模式

**发消息**：

```bash
curl -s -X POST http://localhost:6173/api/sessions/$SESSION_ID/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "我们一起来写一个CONTRIBUTING.md吧，一人一句。"}'
```

**断言**：

- [ ] 收到 `writer_progress` → data.mode = "PAIR"
- [ ] 收到 `writer_response` → data.text 建议下一步
- [ ] 收到 `writer_decision` → 等用户确认才执行
- [ ] Writer 不一次性写完整个文件

---

## 最终验证

测试完成后，检查以下文件和状态：

### 文件存在性

```bash
test -f scripts/quickstart.sh && echo "PASS: quickstart.sh" || echo "FAIL: quickstart.sh"
test -f docs/onboarding-guide.md && echo "PASS: onboarding-guide.md" || echo "FAIL: onboarding-guide.md"
test -f docs/project-structure.md && echo "PASS: project-structure.md" || echo "FAIL: project-structure.md"
test -f backend/tests/test_onboarding_demo.py && echo "PASS: test_onboarding_demo.py" || echo "FAIL: test_onboarding_demo.py"
```

### 测试可运行

```bash
cd backend && py -3.14 -m pytest tests/test_onboarding_demo.py -v
```

### 无 mock

```bash
grep -r "mock\|Mock\|patch\|Monkeypatch" backend/tests/test_onboarding_demo.py && echo "FAIL: found mock" || echo "PASS: no mock"
```

### Git 分支

```bash
git branch --list "writer/*" | grep -q . && echo "PASS: writer branch exists" || echo "FAIL: no writer branch"
```

---

## 覆盖率总结

| 类别 | 覆盖项 | Phase |
|------|--------|-------|
| 交互模式 (9/9) | EXECUTE(1,4,6,8,9) BRAINSTORM(2) DECISION(3) TEACH(5) DISCUSS(12) REVIEW(10) PAIR(13) COMFORT(11) PROTOTYPE(7) | 全部 |
| SelfReview domain (5/5) | code(4,8) prose(6,12) email(9) general(10) plan(1) | 全部 |
| Workflow phases (5/5) | ideation→outlining→drafting→revising→polishing | 9 |
| 架构功能 | TaskPlan(1) DesignFSM(1) Drift(6) SelfReview(4,6,8,9,10) Permission(4,5,8,9) Memory writeback(4,6,8,9,12) Compaction(6) Part-based(4,8) Git(12) Loop breaker(6) Mode auto-switch(1,4,6) | 全部 |
| 工具 (13/16) | read_file write_file edit_file search_content search_files list_dir run_command git_status git_diff git_branch git_commit web_fetch self_critique | 4-13 |
| 输出类型 (5/5) | code(4,8) document(6,7) email(9) report(12) text(2,3,5,10,11) | 全部 |

**未覆盖（按设计排除）**：delegate_to_member / request_image / query_sage / Novel 相关 / git push
