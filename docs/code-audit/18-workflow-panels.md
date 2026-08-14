# 18 工作流与运行面板 审计报告

审计时间：2026-08-13　审计区：18（工作流 / 画布 / 运行面板）　方式：静态只读审计
严重度定义：S1=严重缺陷/安全隐患；S2=中等（功能失效/数据丢失/契约断裂）；S3=轻微；S4=建议

## 1. 概况

本区覆盖工作流画布（Vue Flow）、节点编辑卡、Arrange 长期任务管理、Stage 视窗面板、Artifact 面板、运行时控制（执行控制/资源/goal 条）、审批卡、Sub Agent 面板与队列输入盘，以及 workflow/ 与 durable/ 的前后端契约。共审阅 20 个组件/模块，并与后端 `lamtools_core/runtime/workflow.py`、`runtime/arrange.py`、`tool/sub_agent_runner.py`、`app/durable_operations.py` 做了契约核对。

总体印象：代码质量较高，画布同步（签名防抖）、队列输入盘竞态防护、Sub Agent 对话框滚动/焦点管理都有清晰注释与良好设计。但存在 **3 处前后端契约断裂**（once 触发器、command/script 超时字段、AI agent 工具集），其中 once 触发器导致"单次"排期 100% 创建失败；另有审批卡双击重复提交、kind 切换丢编辑等交互级问题。

问题统计：S1=0，S2=6，S3=8，S4=9，共 23 条。

## 2. 问题清单

### 2.1 画布与节点编辑

- **[S2] command/script 节点"超时（秒）"输入框绑定错误，超时配置被静默丢弃**
  位置：`core/ui/src/components/NodeEditCard.vue:108`（command）、`:120`（script）
  问题：两个"超时（秒）"输入框均 `v-model.number="temperature"`，绑定的是 AI 温度 ref 而非超时 ref；`apply()` 的 command/script 分支（`:334-360`）也只写 `command/cwd/script/retries`，从不写 `timeout`。后端 `runtime/workflow.py:1011/1116` 读取 `cfg.get("timeout")`，缺省 60s。
  影响：用户在高级设置里填写的超时对执行毫无作用（实际写入的 temperature 对 command/script 也无意义），节点超时永远 60s；大脚本/慢命令被意外截断或永远不超时，且无任何提示。
  修复建议：新增 `timeout` ref（从 `config.timeout` 初始化），输入框改绑 `timeout`，apply 的 command/script 分支写 `cfg.timeout`。

- **[S2] 编辑卡内切换节点类型（kind）会立即关闭卡片并丢弃所有未提交编辑**
  位置：`core/ui/src/components/NodeEditCard.vue:300-302` + `core/ui/src/components/WorkflowCanvas.vue:416-419`
  问题：`onKind()` 直接 `emit('update', { ...props.node, kind })`，父组件 `onUpdateNode` 收到后更新定义并 `editNode.value = null`（关卡）。标题、指令、端口等本地 ref 中的未提交修改全部丢失（这些只在 `apply()` 才合并）。
  影响：用户在卡片里先改了标题/指令，再点类型下拉想试试其他类型，卡片立刻消失、改动全丢，需重开重填——典型的数据丢失 UX。
  修复建议：kind 切换仅改本地状态（或即时应用但不关卡）；`apply()` 时再一并提交，或改为打开确认。

- **[S2] AI agent 模式"工具集"勾选保存到 `cfg.tools`，后端完全不读取——功能无效**
  位置：`core/ui/src/components/NodeEditCard.vue:322-327`；后端 `runtime/workflow.py:798-830`（`_execute_ai_agent` 仅传 task/agent/model/mode）、`tool/sub_agent_runner.py:175-186`（`run()` 无 tools 参数）
  问题：前端把勾选结果写入 `cfg.tools`（agent 模式）或 `cfg.allow_tools/allowed_tools`（single/loop 模式），但后端 AI 节点执行链中没有任何一处读取这些键；`allowTools` ref 在模板中也从未渲染（`NodeEditCard.vue:252` 死状态）。
  影响：用户勾选/取消工具无任何效果，界面传达"可限制工具集"的承诺与真实行为不符；`cfg.allow_tools` 恒为 false 且永远不写入 `allowed_tools`。
  修复建议：要么后端 `KernelSubAgentRunner.run` 增加 tools/disabled_tools 参数并透传，要么前端移除工具勾选 UI（或标注"暂不生效"）。

- **[S3] NodeEditCard 持有定义节点的过期引用，保存会回退编辑期间的拖拽位置**
  位置：`core/ui/src/components/WorkflowCanvas.vue:304-311`（`editNode.value = n` 直接引用 `props.definition.nodes` 中的对象）、`:416-419`
  问题：卡片打开后，任何 `update:definition`（如拖拽节点、连线）都会用新对象替换定义数组，而 `editNode` 仍指向旧对象；点"应用"时 `onUpdateNode` 用旧对象覆盖整节点，旧对象里的 position 是打开卡片时快照。
  影响：卡片开着时拖动该节点 → 点应用 → 节点位置跳回拖拽前；若期间有外部刷新还会回退更多字段。
  修复建议：卡片只存 `id`，`apply()` 时从最新 `props.definition` 取节点再合并。

- **[S3] 全局 document 监听器未随组件卸载清理**
  位置：`core/ui/src/components/WorkflowCanvas.vue:478-481`
  问题：setup 中 `document.addEventListener('pointerdown'/'keydown')` 无对应 removeEventListener。组件由 `v-if="workflowMode"`（demo/App.vue:193）反复挂载/卸载。
  影响：每次进出工作流模式累积监听器（内存泄漏 + 事件重复处理）；卸载后旧实例的 closeMenus 仍在运行。
  修复建议：用 `onMounted/onUnmounted` 配对注册/注销。

- **[S4] 连线类型不兼容时静默拒绝，无任何用户提示**
  位置：`core/ui/src/components/WorkflowCanvas.vue:316-337`（`_typesCompatible` 返回 false 时直接 return）
  影响：用户拖线失败但不知道为什么。
  修复建议：失败时 toast/状态条提示"端口类型不兼容"。

- **[S4] 节点配置浅合并导致已删除键残留**
  位置：`core/ui/src/components/WorkflowCanvas.vue:133-138`（provide `wf-update-node` 用 `{ ...n.config, ...patch.config }`）
  影响：如 AI 节点从 agent 模式切回 single 后 `tools` 键仍残留于 config（后端不读，暂无实际危害），长期累积脏配置。
  修复建议：对 config 做键级替换（patch 时先剔除被删键）或在 apply 时重建 config。

### 2.2 Arrange 管理（CoreArrangeManager）

- **[S2] "单次（once）"触发器前后端契约不匹配，创建/编辑 100% 失败**
  位置：`core/ui/src/components/CoreArrangeManager.vue:206-213`（buildTrigger）；后端 `runtime/arrange.py:786-811`（`_normalize_trigger`）
  问题：前端 once 载荷为 `{ type:'once', local_at, timezone }`；后端只认 `date`/`time`/`timezone`/`run_at`。由于前端恒带 `timezone`（默认 Asia/Shanghai），后端必然进入日期分支，`date.fromisoformat('' /* 前端从不发 date */)` 抛 ValueError → `"one-time date must use YYYY-MM-DD"`。
  影响：表单默认就是"单次"，即"新建安排"默认路径必失败，且报错信息与用户操作对不上；once 排期功能整体不可用。
  修复建议：前端 buildTrigger 的 once 分支改为发送 `{ type:'once', date, time, timezone }`（对齐后端）；或后端兼容 `local_at`。

- **[S3] 编辑既有 once 任务时不回填日期/时间/时区，保存后排期丢失或报错**
  位置：`core/ui/src/components/CoreArrangeManager.vue:162-199`（openEditForm 的 `trigger.type==='once'` 分支只设 formScheduleType）
  问题：formDate/formTime/formTimezone 不被恢复（沿用上次创建表单的残留值），保存时 buildTrigger 生成空/错日期。
  影响：编辑一次即丢失原排期；与上一条叠加，once 任务编辑同样失败。
  修复建议：once 分支从 `trigger.run_at`/`trigger.date/time/timezone` 回填三个字段。

- **[S3] Arrange 任务列表无轮询/推送，状态长期过期**
  位置：`core/ui/src/components/CoreArrangeManager.vue:444`（仅 `onMounted(loadJobs)`）
  问题：scheduled→running→completed 等状态迁移不会自动刷新，只能手动点"刷新"。
  影响：长期任务管理面板展示的状态不可信（任务已跑完仍显示"已安排"）。
  修复建议：加轻量轮询（如 15-30s）或订阅后端事件。

- **[S3] 行内编辑按 Esc 会连带关闭整个安排对话框**
  位置：`core/ui/src/components/CoreArrangeManager.vue:435-453`
  问题：标题/指令行内编辑的 keydown 处理器（`onTitleKeydown`/`onInstructionKeydown`）处理 Esc 时未 `stopPropagation`，事件冒泡到 document 级 `onKeydown`（Esc → closeForm/emit('back')）。
  影响：编辑中按 Esc 想取消编辑，结果整个对话框关闭（或表单被关），编辑内容丢失。
  修复建议：行内处理器对 Esc 调用 `event.stopPropagation()`。

- **[S4] 历史"读取中…"分支是死代码**
  位置：`core/ui/src/components/CoreArrangeManager.vue:375-390` 与 `:713`
  问题：`toggleHistory` 先置 `occurrences[jobId]=[]` 再异步拉取，模板 `v-if="!occurrences[job.id]"` 的"读取中"永不显示；加载期间误显示"暂无运行记录"。
  修复建议：置 null 表示加载中，或给 occurrence 加 loading 标记。

- **[S4] 编辑表单不回填且无法修改 max_runs**
  位置：`core/ui/src/components/CoreArrangeManager.vue:162-199`（openEditForm 未读 `job.max_runs`）、`:262-269`（editArrangeJobApi 无 max_runs 字段）
  影响：有上限的任务在编辑表单里显示"留空不限"，且保存无法修改上限，误导用户。
  修复建议：回填并在 edit 请求中携带 max_runs。

### 2.3 Stage / Artifact 面板

- **[S2] StageBrowser 把"所有跨域页面"误报为"该站点不允许内嵌预览"**
  位置：`core/ui/src/components/StageBrowser.vue:87-99`（onLoad）
  问题：`contentDocument === null` 对**任何加载成功的跨域 iframe** 都成立（跨域时该属性即返回 null，并不抛异常）；只有被 X-Frame-Options/iframe 限制拒绝时才触发 error 事件而非 load。
  影响：预览绝大多数外部站点（Google、Bing 等）时都盖上"该站点不允许内嵌预览"黑罩，实际页面已加载成功，功能被误判成不可用；`catch` 分支实际是死代码。
  修复建议：用 `@error` 事件 + 加载超时（如 8s 未 load 判定 blocked）代替 contentDocument 探测。

- **[S3] StagePane 的 dirty 标志是单例，切换标签后"保存"按钮错位**
  位置：`core/ui/src/components/StagePane.vue:150`（`codeDirty` 单一布尔）、`:115`（保存按钮条件）
  问题：编辑 tab A（dirty=true）后切换到 tab B，B 的状态栏仍显示"保存"按钮；点击保存的是 B 的内容（A 的未保存修改被掩盖）。markdown 标签则永远不显示保存按钮（条件只认 kind==='code'）。
  修复建议：dirty 按 tab id 维护（Map），保存按钮与 dirty 一并按当前标签判定；markdown 也纳入保存按钮条件。

- **[S3] 媒体预览加载失败无任何提示（error 状态永为 false）**
  位置：`core/ui/src/components/StageMediaPreview.vue:19` 与模板 `:5-8`
  问题：`error` ref 声明后从未被赋值，video/audio 元素没有 `@error` 监听。
  影响：媒体 404/解码失败时显示空白或浏览器原生错误图标，模板里的错误提示是死代码。
  修复建议：给 video/audio 加 `@error` 置 error=true。

- **[S4] HTML 预览 iframe sandbox 含 allow-same-origin，不可信内容可触达父页面**
  位置：`core/ui/src/components/StagePane.vue:40-45`（srcdoc）、`core/ui/src/components/StageBrowser.vue:19-25`
  问题：`sandbox="allow-scripts allow-same-origin ..."`：srcdoc 文档与父页面同源，工作区内（可能由 Agent 生成的）HTML 中的脚本可访问父窗口 DOM/存储。
  影响：预览不可信 HTML 时存在同源逃逸面（低概率但属安全边界问题）。
  修复建议：预览 srcdoc 去掉 `allow-same-origin`（纯展示足够）；浏览器标签页保持现状（跨域场景无同源风险）。

- **[S4] 代码编辑器对 props.content 整体替换无 dirty 保护**
  位置：`core/ui/src/components/StageCodeEditor.vue:149-157`
  影响：当前链路（update:content 与父级内容同步）风险低，但若未来父级推送服务端内容会直接覆盖未保存编辑。
  修复建议：替换前判断 dirty 并确认/跳过。

- **[S4] Artifact 预览无加载失败处理，PDF iframe 无 sandbox**
  位置：`core/ui/src/components/ArtifactPanel.vue:66-93`
  影响：图片/视频加载失败显示破图；PDF iframe 无 sandbox 属性（同源内容可执行脚本，虽 PDF 渲染器通常无脚本，但建议加 sandbox 兜底）。
  修复建议：img/video/audio 加 @error；iframe 加 `sandbox`（如 `sandbox="allow-same-origin"` 或留空）。

### 2.4 审批卡与运行时

- **[S2] 审批卡批准/拒绝无防重入，快速双击会重复提交决策**
  位置：`core/ui/src/components/FloatingApprovalCard.vue:167-193`（handleApprove/handleDeny）
  问题：两个按钮无 disabled/进行中状态；`dismissedIds` 更新虽同步，但连续两次点击（或批准+拒绝快速连点）可发出两条 `decision-select`，父级/后端若无幂等去重会重复处理同一审批。
  影响：对同一请求重复执行/重复拒绝，可能造成工具重复调用。
  修复建议：提交后立即置 in-flight 状态禁用按钮，直到 pendingDecisions 更新或加防抖。

- **[S4] 审批忽略状态在"非空新列表"下不重置**
  位置：`core/ui/src/components/FloatingApprovalCard.vue:128-138`
  影响：同一 part.id 若在未经过空列表的新一轮 pending 中再次出现（agent 复用消息 part），会一直保持"已忽略"。低概率。
  修复建议：以"part.id 集合变化"而非"变空"作为重置条件。

## 3. 该区 Top 3 问题

1. **once 触发器契约断裂（S2）**——前端发 `local_at`，后端要 `date/time`，且前端恒带 timezone 使后端必然进入解析分支报错；"单次"排期（含默认新建路径）创建与编辑 100% 失败。位置：`CoreArrangeManager.vue:206-213` vs `runtime/arrange.py:786-811`。
2. **command/script 超时输入绑定错误（S2）**——"超时（秒）"输入框绑 `temperature`，apply 从不写 `cfg.timeout`，用户设置静默丢失、节点永远 60s 默认超时。位置：`NodeEditCard.vue:108/120` vs `runtime/workflow.py:1011`。
3. **AI agent 工具集勾选无效（S2）**——前端保存 `cfg.tools/allowed_tools`，后端 `_execute_ai_agent`/`KernelSubAgentRunner.run` 从不读取，界面功能承诺与真实行为不符。位置：`NodeEditCard.vue:322-327` vs `runtime/workflow.py:798-830`。

## 4. 亮点

- **WorkflowCanvas 的"签名防抖同步"设计**（`WorkflowCanvas.vue:147-183`）：位置刻意排除在签名之外、config 键排序后再序列化，避免拖拽中因父级重写定义导致的抖动/回跳，注释完整解释了设计权衡——同类组件中少见的高质量处理。
- **队列输入盘竞态防护完备**（`useCoreQueuedInputController.ts:47-66`）：Enter/blur/Esc 可能触发的重复 save/cancel 用 `editingId` 守卫 + `submittingItemIds` 双保险，实测路径（Enter→blur、Esc→blur）均安全。
- **Sub Agent 对话框的滚动与焦点管理**（`CoreSubAgentDialog.vue:163-210`）：ResizeObserver 单通道滚动、focus 恢复带可见性校验、dialog fallback（showModal/setAttribute），处理细致。
- **StagePane 保存失败可重试设计**（`StagePane.vue:170-181` + demo/App.vue:790-804）：`onSaved`/`resetSaving` 分离，失败保持 dirty 并复位 saving。
- **arrange/durable API 共享持久连接**（`durable/api.ts:11-41`）：避免每次 RPC 新建 WebSocket 的抖动，注释说明了历史教训。
- **WorkflowNode 内联编辑与画布状态分离**：节点状态（state）更新不触碰结构/位置（`WorkflowCanvas.vue:189-197`），运行时高亮与拖拽互不干扰。

## 5. 审计范围与方法

### 范围（全部只读）
- 画布/节点：`components/WorkflowCanvas.vue`、`NodeEditCard.vue`、`WfSelect.vue`、`WorkflowControlBar.vue`、`WorkflowNode.vue`
- Arrange：`components/CoreArrangeManager.vue`、`durable/api.ts`、`durable/types.ts`
- Stage/Artifact/Runtime：`components/StagePane.vue`、`StageBrowser.vue`、`StageCodeEditor.vue`、`StageImagePreview.vue`、`StageMediaPreview.vue`、`ArtifactPanel.vue`、`RuntimePanel.vue`
- 运行时控制：`components/CoreExecutionControls.vue`、`CoreResourceStats.vue`、`CoreGoalStrip.vue`、`CoreQueuedInputTray.vue`、`FloatingApprovalCard.vue`、`CoreSubAgentDialog.vue`、`CoreSubAgentPanel.vue`
- 工作流 API/类型：`workflow/api.ts`、`workflow/types.ts`、`composables/useCoreQueuedInputController.ts`、`composables/useCoreGoals.ts`
- 使用方与后端契约核对：`demo/App.vue`（WorkflowCanvas/StagePane/队列盘宿主）、`lamtools_core/runtime/workflow.py`、`runtime/arrange.py`、`tool/sub_agent_runner.py`、`app/durable_operations.py`

### 方法
逐文件通读 + 交叉核对：前端 emit/状态流 → 宿主（demo/App.vue）接线 → 后端 RPC/运行时对配置键的读取，逐条验证"前端写入的键 == 后端读取的键"；对定时器/监听器/ref 生命周期做泄漏与竞态检查；对模板中声明但从未赋值/引用的状态做死代码检查。所有结论均可在标注的 file:line 复现。
