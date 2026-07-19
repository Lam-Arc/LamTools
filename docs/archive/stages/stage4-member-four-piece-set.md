<!-- 历史参考，不代表当前架构 -->
# 阶段四：Writer / Artist 四件套定义

## 目的

把 Writer 和 Artist 当前散落在 runtime / service / CLI 中的能力，整理成同一套业务语言。
四件套不是新抽象层，而是对现有能力的结构化描述，方便后续对齐和沉淀。

---

## Writer 四件套

### 1. Persona

| 字段 | 值 | 代码落点 |
|------|-----|---------|
| name | Writer | `members/writer/backend/app/core/persona.py:10` |
| identity | 24岁工匠，精确编码和写作 | `persona.py:11` |
| voice | 极简，两个词代替一句话，无填充 | `persona.py:12` |
| 硬约束 | 不压制类型错误；不留破损代码；验证后才宣布完成；文件操作限 work_root；三层权限 | `persona.py:20-29` |
| 执行纪律 | 工具纪律（先读后改）、Agent 纪律、编辑策略、失败恢复、测试纪律、完成标准 | `prompt_assembler.py:13-22` (`WRITER_EXECUTION_DISCIPLINE_ZH`) |
| 架构决策框架 | 按复杂度选架构；必须含测试/README/构建配置 | `prompt_assembler.py:33-47` |
| 交付要求 | 一句话摘要 + 运行方法 + 前置条件 | `prompt_assembler.py:65-70` |

**状态**：persona 已在代码中完整表达。

### 2. Hooks

| 节点 | 任务 | 代码落点 | 是否已结构化 |
|------|------|---------|------------|
| 进模型前 | 组装 system prompt（persona + 纪律 + 模式 + 项目指令 + 循环位置） | `prompt_assembler.py:560-664` | 是 |
| 进模型前 | 注入任务计划进度 | `runtime.py:452-481` | 散落在 runtime |
| 进模型前 | 注入漂移检测修正 | `runtime.py:485-494` | 散落在 runtime |
| 进模型前 | MEM 上下文召回 | `prompt_assembler.py:545-548` | 是 |
| 进模型前 | 上下文压缩 | `runtime.py:497-513` | 散落在 runtime |
| 工具后 | 权限检查 | `permission.py:78-116` | 是 |
| 工具后 | 结果索引到 session memory | `session_memory.py` | 是 |
| 工具后 | 失败恢复注入 | `runtime.py:938-971` | 散落在 runtime |
| 工具后 | 强制动作检查 | `runtime.py:708-748` | 散落在 runtime |
| 工具后 | 重新规划触发 | `runtime.py:819-847` | 散落在 runtime |
| 最终验收 | CompletionVerifier（编译/导入/API引用/pytest/npm build） | `completion_verifier.py:128-175` | 是 |
| 最终验收 | 步骤验收标准检查 | `runtime.py:870-889` | 散落在 runtime |
| 完成后写回 | Session memory 写回 | `runtime.py:1251-1254` | 散落在 runtime |
| 完成后写回 | Git 上下文刷新 | `runtime.py:1260` | 散落在 runtime |
| 完成后写回 | 状态持久化 | `runtime.py:1257-1259` | 散落在 runtime |
| 完成后写回 | 产物记录 | `runtime.py:1014-1028` | 散落在 runtime |

**风险判断**：Writer hooks 大量散落在 runtime.py（6241行）中，抽成独立 hook 模块风险高，先记录。

### 3. Agents

| Agent | 解决什么问题 | 什么时候用 | 不能做什么 | 代码落点 |
|-------|------------|-----------|-----------|---------|
| architecture | 设计软件架构，返回实施交接 | 复杂任务需要先设计再实施 | 不直接写代码 | `agent_runtime.py:79-88`, `agents/architecture_agent.py` |
| search | 研究当前事实、文档、许可证 | 需要外部信息时 | 不写文件不跑命令 | `agent_runtime.py:89-97` |
| review | 审查计划和代码 | 需要质量把关时 | 不修改代码 | `agent_runtime.py:98-106` |
| test | 设计或运行测试 | 需要验证时 | 不修改生产代码 | `agent_runtime.py:107-115` |
| ui | 创建界面结构 | 涉及前端时 | 不跑后端命令 | `agent_runtime.py:116-124` |
| dependency | 规划依赖和打包策略 | 涉及环境配置时 | 不直接安装 | `agent_runtime.py:125-133` |

**状态**：AgentRegistry 已结构化。architecture agent 有完整图节点和模式控制；旧 design_agent 命名已删除。

### 4. Tools

| 工具 | 权限 | 输入边界 | 失败形态 | 恢复建议 | 代码落点 |
|------|------|---------|---------|---------|---------|
| read_file | auto_allow | path (work_root 内) | 文件不存在/越界 | N/A | `prompt_assembler.py:28-41`, `core_kernel_adapter.py:271-470` |
| write_file | ask_user | path + content (≤100k chars) | 越界/无法创建目录 | N/A | `prompt_assembler.py:43-63`, `core_kernel_adapter.py:529-882` |
| edit_file | ask_user | path + old_text + new_text (old_text 唯一) | old_text 不存在/重复 | 用 write_file 重写整个文件 | `prompt_assembler.py:65-88` |
| search_content | auto_allow | pattern + path | 越界 | N/A | `prompt_assembler.py:90-109` |
| search_files | auto_allow | pattern + path | 越界 | N/A | `prompt_assembler.py:111-130` |
| recall_session | auto_allow | 多种检索键 | 无结果 | N/A | `prompt_assembler.py:132-198` |
| load_skill | auto_allow | name | 技能不存在 | N/A | `prompt_assembler.py:200-218` |
| web_search | auto_allow | query + limit | 无结果 | N/A | `prompt_assembler.py:220-238` |
| run_command | ask_user | command + timeout | 超时/退出码≠0 | 检查命令 | `prompt_assembler.py:240-259` |
| git_status | auto_allow | 无 | git 不可用 | N/A | `prompt_assembler.py:261-269` |
| git_diff | auto_allow | path | 无变更 | N/A | `prompt_assembler.py:271-287` |
| list_dir | auto_allow | path | 越界 | N/A | `prompt_assembler.py:289-302` |
| web_fetch | ask_user | url | 网络错误/内容过大 | N/A | `prompt_assembler.py:304-319` |
| run_tests | ask_user | command + timeout | 测试失败 | 阅读失败输出修复代码 | `prompt_assembler.py:321-333` |
| inspect_project | auto_allow | path + max_files | 越界 | N/A | `prompt_assembler.py:335-347` |
| browser_check | auto_allow | url + expect | 不可达 | N/A | `prompt_assembler.py:349-362` |
| decision_point | auto_allow | title + options | 无 | N/A | `prompt_assembler.py:364-383` |
| write_checklist | auto_allow | files + design_summary | 无 | N/A | `prompt_assembler.py:385-405` |
| verify_design | auto_allow | design_path | 验证失败 | 修复不一致 | `prompt_assembler.py:407-421` |
| delegate_to_member | auto_allow | target_member + task | 目标成员不可用 | N/A | `prompt_assembler.py:423-447` |
| `*_agent` | auto_allow | task + mode | Agent 不存在 / 模式无效 | N/A | `tool_specs.py` |

**状态**：工具 schema 在 prompt_assembler.py 定义；权限在 permission.py 定义；执行器在 core_kernel_adapter.py 实现。三层分离，已结构化。

---

## Artist 四件套

### 1. Persona

| 字段 | 值 | 代码落点 |
|------|-----|---------|
| name | Artist (LamArtist) | `identity.py:4` |
| identity | LamArtist 的 Agent 循环运行时；读图→观察→调工具→等结果→再观察 | `identity.py:4` |
| 默认风格 | 遵循 identity_contract 和用户目标 | `identity.py:33-46` |
| 质量标准 | 通过视觉验收（goal_match + task_match + deliverable_match） | `identity.py:62-71`, `visual_review.py` |
| 局部修改规则 | task_card.intent=local_edit 时必须以"修改图X："开头 | `identity.py:23, 29-31` |
| anchor 规则 | 短且开放，只固定核心识别，不追加大画面补充语 | `identity.py:34-41` |
| 品牌系统规则 | 一句话视觉系统，不写"包含"式清单 | `identity.py:41-43` |
| 输出 schema | reply_lines + task_card + observations + batch_review + identity_contract + tool_calls | `identity.py:76-139` |

**状态**：persona 已在 identity.py 完整表达。

### 2. Hooks

| 节点 | 任务 | 代码落点 | 是否已结构化 |
|------|------|---------|------------|
| 进模型前 | 注入 runtime_state（可见图片、谱系、上下文角色） | `runtime.py:822-824` | 是（_inject_runtime_state） |
| 进模型前 | 构建视觉消息（VLM 多模态内容块） | `image_context.py:65-153` | 是 |
| 进模型前 | 接触拼图（>2 待验收时） | `image_context.py:90-133` | 是 |
| 进模型前 | 漂移检测 | `runtime.py:876-887` | 是（_check_drift） |
| 进模型前 | 上下文压缩 | `runtime.py:889-901` | 是（_compress_context_if_needed） |
| 工具后 | 产物创建 + 血缘链接 | `runtime.py:1509-1566` | 是（_create_artifacts） |
| 工具后 | 早期发布 SSE 事件 | `runtime.py:809-823` | 是（_publish_artifacts_ready） |
| 工具后 | 记录待验收观察 | `visual_review.py:171-186` | 是 |
| 工具后 | 应用模型观察结果到视觉记忆 | `visual_review.py:189-248` | 是 |
| 工具后 | 应用 batch_review 到记忆 | `visual_review.py:369-407` | 是 |
| 工具后 | 应用 task_card | `visual_review.py:455-511` | 是 |
| 工具后 | 应用 identity_contract | `visual_review.py:514-554` | 是 |
| 工具后 | 局部修改保护（拒绝扩展 prompt） | `image_prep.py:404-470` | 是 |
| 工具后 | 引用可见性过滤 | `image_prep.py:219-251` | 是 |
| 工具后 | 身份合同冲突检查 | `image_prep.py:365-401` | 是 |
| 最终验收 | 自检（_self_review） | `visual_review.py:14-54` | 是 |
| 最终验收 | 缺失观察阻止完成 | `visual_review.py:62-77` | 是 |
| 最终验收 | 阻塞性问题阻止完成 | `visual_review.py:897-912` | 是 |
| 最终验收 | 自动修复暂停 | `visual_review.py:149-152` | 是 |
| 最终验收 | 重试效果跟踪 | `visual_review.py:839-900` | 是 |
| 最终验收 | 模型超时保底（已出图时） | `runtime.py:100-112` | 是 |
| 完成后写回 | 状态持久化 | `runtime.py:419-431` | 是 |
| 完成后写回 | 视觉记忆写入 | `visual_review.py:57-59` | 是 |
| 完成后写回 | 谱系刷新 | `image_prep.py:106-120` | 是 |

**状态**：Artist hooks 已全部结构化到独立模块（image_context, image_prep, visual_review, artifact_registry）。这是拆分的成果。

### 3. Agents

| Agent | 解决什么问题 | 什么时候用 | 不能做什么 | 代码落点 |
|-------|------------|-----------|-----------|---------|
| delegate_agent | 非图像分析任务（研究、调研、趋势） | 用户只问方向/建议/分析时 | 不能生图 | `identity.py:14`, `runtime.py:1218-1228` |

**状态**：delegate_agent 只有 stub（service 和 CLI 传入 None）。当前没有真正的 Agent 实现。

### 4. Tools

| 工具 | 权限 | 输入边界 | 失败形态 | 恢复建议 | 代码落点 |
|------|------|---------|---------|---------|---------|
| generate_image | 始终允许 | task(必填) + reference[] + note + image_count(1-16) + items[](批量) | 接口不可用/返回空/网络错误 | 标记 retryable | `identity.py:8-13`, `runtime.py:1106-1166` |
| delegate_agent | 有配置时允许 | task + reason | 未配置 | 跳过 | `identity.py:14`, `runtime.py:1218-1228` |
| finish | 始终允许 | reason | N/A | N/A | `identity.py:15`, `runtime.py:1230-1232` |
| ask_user | 始终允许 | question | N/A | N/A | `identity.py:16`, `runtime.py:1234-1236` |

**状态**：工具定义在系统提示词中；执行在 runtime.py 的 _execute_tool 中。无独立工具 schema/权限/注册层。

---

## 对比总结

| 维度 | Writer | Artist |
|------|--------|--------|
| Persona | 已结构化 (persona.py) | 已结构化 (identity.py) |
| Hooks | 散落在 6241 行 runtime.py | 已拆分到独立模块 |
| Agents | 6 个已结构化 (agent_runtime.py) | 1 个 stub |
| Tools | 22 个已结构化 (schema + 权限 + 执行器三层) | 4 个在系统提示词，无 schema/权限层 |
| RuntimeKit | 有 (WriterKit) | 有 (ArtistKit) |

## 低风险可抽取项

| 能力 | 当前落点 | 建议落点 | 风险 |
|------|---------|---------|------|
| Writer hooks 生命周期常量 | runtime.py 内联 | `writer/constants.py` | 低 |
| Writer 工具权限映射 | permission.py | 保持现状 | 无需动 |
| Artist 工具 schema 定义 | identity.py 内嵌 | `artist/tool_specs.py` | 低 |
| Artist 工具权限边界 | 无 | `artist/tool_permissions.py` | 中（新文件，不影响现有行为） |
| Artist delegate_agent 实现 | 无（stub） | 保持 stub | 风险在实现侧，不在定义侧 |

## 高风险暂不动项

| 能力 | 原因 |
|------|------|
| Writer runtime.py 重构为 hooks 模块 | 6241 行，复杂度高，改错代价大 |
| Writer 工具执行器与 runtime 解耦 | 执行器依赖 runtime 状态，循环依赖风险 |
| Artist 工具执行独立于 runtime | 当前 _execute_tool 依赖 self.deps，解耦需重构依赖注入 |
