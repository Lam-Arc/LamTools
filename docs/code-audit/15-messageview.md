# 15 MessageView 渲染核心 审计报告

> 审计日期：2026-08-13 ｜ 审计区：第 15 区（前端渲染核心） ｜ 模式：全程只读
> 参考：`docs/core-ui-streaming-perf.md`（已完成的结构包 / 投影增量 / part 级 v-memo 隔离 / Markdown 增量分段渲染等均为已知设计，本报告不重复列为问题）

## 1. 概况

本区审计对象为消息渲染核心三件套 + 相关 helper：

| 文件 | 行数 | 角色 |
|---|---|---|
| `core/ui/src/components/MessageView.vue` | 4098 | 单消息渲染组件（user/system/assistant 三分支 + part 渲染 + 自递归 sub-line），流式性能优化的主战场 |
| `core/ui/src/components/MarkdownRenderer.vue` | 539 | markdown 渲染器：流式增量分段 DOM 渲染 / 完成态 v-html 全量渲染 / katex / mermaid |
| `core/ui/src/components/TypewriterText.vue` | 53 | 用户消息打字机动画 |
| `core/ui/src/helpers/openUrl.ts` | 45 | 外链协议白名单与系统浏览器转发 |

总体评价：代码质量高——part 级 `v-memo` 隔离（`partMemo` 依赖键齐全）、投影缓存引用稳定性配合、增量分段渲染 O(tail)、XSS 面收得很紧（唯一 v-html 入口在 MarkdownRenderer，流式路径全输入 escapeHtml，完成态经 DOMPurify，链接协议白名单 + 点击拦截）。但发现一处**主链路级的功能缺口**（主线消息从不携带 `metadata.live`，导致 MessageView 的 live 流式渲染路径在主流程整体不生效）与一处**多实例共享模块级可变状态的交叉污染**（mermaid），合计 15 条问题（S1×1 / S2×1 / S3×5 / S4×8）。

## 2. 问题清单

### S1（严重缺陷）

- **[S1] 主线消息从不携带 `metadata.live` → live 流式渲染路径（含 streaming 增量 MarkdownRenderer、part 自动展开/折叠、live 状态条）在主线程流式中整体不生效，主消息实际走 history 分支的「非 streaming 全量 markdown 重解析」路径**
  - 位置：
    - `core/ui/src/appServer/selectors.ts:113-120`（assistant 消息构造，metadata 只含 `processMetrics`）
    - `core/ui/src/appServer/workbenchProjection.ts:200-211`（`buildWorkbenchMessage` 仅透传 `message.metadata?.live`，从不主动打标）
    - `core/ui/src/components/MessageView.vue:2214-2216`（`isLiveMessage` 读 `msg.metadata.live`）
    - `core/ui/src/components/MessageView.vue:1052`（history 分支 `v-if="!isTimelineMessage(msg) && !isLiveMessage(msg)"`）
    - `core/ui/src/components/MessageView.vue:1278-1285`（history 分支 model_text 用 `<MarkdownRenderer :content>` **不带 `:streaming`**）
    - `core/ui/src/components/MessageView.vue:1866-1898`（part 自动展开/折叠 watcher 以 `isLiveMessage(props.msg)` 为门，主消息永不触发）
    - 对照：`core/ui/src/components/MessageView.vue:1958-1962` 与 `core/ui/src/agents/subAgentProjection.ts:184-187` 是**唯一**给真实 assistant 消息打 `live/timeline` 的地方（子代理嵌套消息）。
  - 问题：全仓 grep 证实，主线消息的 `metadata.live` 只有 `selectors.ts:261`（initialWaiting 占位消息）与 `useCoreWorkbenchController.ts:122`（乐观占位）两处赋值，二者均无 parts；一旦真实 parts 到达，占位被替换，此后整个流式期间主消息 `live` 恒为 false（`timeline` 同样从无打标）。于是：
    1. 主消息流式渲染实际走 history 分支（MessageView.vue:1052-1491），model_text 每 tick 全量 `marked.parse` + `DOMPurify.sanitize`（markdownCache 按 content 键控，内容每 tick 变化 → 恒 miss）——正是阶段 3/4 优化要消除的 O(内容长度)/tick 路径；`streaming` 增量分段渲染只对子代理嵌套消息生效。
    2. 自动展开 watcher 失效：流式期间工具卡全部保持折叠，用户看不到工具输入/输出/错误，直到手动点开；完成后 1s 自动折叠同样失效。
    3. live 分支的 `assistant-live-state` spinner、`process-current` 状态条在主线永不出现。
  - 影响：主线程流式渲染的**核心功能与性能优化在默认主流程中未生效**；长回答流式每 tick 全量解析（线性增长卡顿回归）；工具过程流不可见。经 git 比对（`fe15bf9`→`c86d8c5`）确认新旧版本一致，属接线缺口而非本次重构回归。
  - 修复建议：在投影层为「运行中 turn 的最后一条 assistant 消息」主动打 `metadata.live = true`（与 `nextCoreProcessExpandedIds` 同源判定：turn 运行中且含 running part），turn 结束随消息引用更新自然翻转；或让 `isLiveMessage` 退化为「含 running part」判定。修复后需回归 `chat-thread-process.test.ts`（其手工构造 `live: true, timeline: true` 消息的用例恰好覆盖这些分支）。

### S2（中等）

- **[S2] mermaid 渲染共享模块级可变状态（`mermaidBlocks`/`mermaidSeq`/`markdownCache`），多实例同帧渲染时交叉污染——前序消息渲染出最后一条消息的图，或静默缺图**
  - 位置：`core/ui/src/components/MarkdownRenderer.vue:78-83`（模块级 `mermaidBlocks`/`mermaidSeq`/`markdownCache`）、`309-315`（computed 内 `mermaidBlocks.length = 0; push(...)`）、`344-355`（`renderMermaidDiagrams` 在异步 `await ensureMermaid()` 之后才按 `data-mermaid-id` 查 `mermaidBlocks`）。
  - 问题：每条消息的每个 part 一个 MarkdownRenderer 实例。同一 flush 中多个含 mermaid 的实例依次求值 `renderedHtml`，各自把**共享**数组重置为自己的一条记录（且 `mermaidSeq` 每次从 0 起，所有实例的占位 id 都是 `mermaid-0`）。watcher 的异步续体（`await nextTick()` + `await ensureMermaid()`）在 flush 之后执行，此时 `mermaidBlocks` 只剩**最后求值实例**的内容——所有前序实例 `find(b => b.id === id)` 都会命中最后一条消息的块，渲染出别人的图；无匹配时静默跳过。DOM 中还会出现重复的 `mermaid-svg-mermaid-0` id。
  - 影响：一条会话中多个含 mermaid 的消息同时渲染时（挂载即触发，非常常见），除最后一条外全部显示错误内容或缺失；重复 SVG id。
  - 修复建议：把 mermaid 块收集改为实例级（`<script setup>` 顶层即实例级，勿用模块级）；`markdownCache` 可保留模块级（跨实例缓存是收益），但缓存条目内需保存「本实例的 blocks 快照」且 renderMermaidDiagrams 用缓存快照而非共享数组；id 生成建议带实例前缀（如 `mermaid-${uid}-${seq}`）。

### S3（轻微）

- **[S3] 流式增量分段把「含空行的代码块」错误切分：非围栏段按段落渲染，泄漏字面 ``` 并闪变**
  - 位置：`core/ui/src/components/MarkdownRenderer.vue:252-284`（`split(/\n{2,}/)` 切段）+ `200-227`（`renderStreamingBlock` 只认「块首 ```」）。
  - 问题：代码块内出现空行时被切成多段。首段（以 ``` 开头）按代码块渲染；后续段不以 ``` 开头 → 按 `<p>` 段落渲染，行内残留字面 ``` 与代码文本；结束后整体切换为 `<pre><code>` 造成视觉跳变。违背「已闭合段永不回溯变化」的承诺（段内容在闭合围栏到来前后不一致）。
  - 影响：流式中长代码块（多行含空行）中间内容闪变成段落文本，结束时再跳回代码样式；对用户是可见闪变。
  - 修复建议：切段时维护「未闭合围栏」状态——块以 ``` 开头且未闭合时，后续段并入同一代码段直到出现闭合围栏；或在 `renderStreamingIncremental` 中对代码段做跨块合并。

- **[S3] history 分支对 `file_diff`/`command_output` part 类型无任何渲染分支 → 这些 part 在完成态消息中完全不可见**
  - 位置：`core/ui/src/components/MessageView.vue:1170-1490`（v-else-if 链覆盖 reasoning/tool/model_text/error/status/decision/sub_line/checklist/plan/todo_update/compaction，**无 file_diff/command_output，也无兜底 else**）；类型来源 `core/ui/src/appServer/messageParts.ts:36-37`（`commandExecution`→`command_output`、`fileChange`→`file_diff`）。
  - 问题：`file_diff`/`command_output` part 在主消息完成态（history 分支，即默认主路径）落入链尾无输出；live 非 timeline 分支（930-1049）同样只覆盖 model_text/reasoning/tool/process-group/retry，error/status/decision/compaction/sub_line/file_diff/command_output/plan/todo_update 在流式期间全部不可见（timeline 分支有 `isHighValueLivePart` 兜底，history 分支没有）。另：live timeline 循环里 `v-if="part.partType === 'text'"`（158 行）为死分支——`groupParts`（3676-3686）先过滤了 text part。
  - 影响：兼容数据/旧快照中的这两类 part 渲染丢失；流式期间错误与审批卡不可见（审批另有 FloatingApprovalCard 兜底）。
  - 修复建议：history 分支补 file_diff/command_output 分支（复用 isFileTool/isCommandTool 的 diff 块/终端样式），并在链尾加兜底 else（与 timeline 分支一致渲染为 process-step--info）。

- **[S3] 子线（sub-line）嵌套渲染无引用稳定性：`agentSubMessages`/`normalizeSubLineChildPart` 每次父重渲重建全新对象，嵌套 part 级 v-memo 恒失效**
  - 位置：`core/ui/src/components/MessageView.vue:1936-1966`（每次调用新建子消息对象）、`3211-3235`（每次调用重建子 part 对象）、`1968-1972`（`agentProcessExpandedIds` 每次返回新 Set）、`782-809`/`1405-1432`（嵌套 MessageView 无缓存）。
  - 问题：父消息任一重渲（msg 引用变化/状态翻转）都会让嵌套子消息与子 part 的**对象引用全部变化**，嵌套 MessageView 内 part 级 v-memo 无从命中，整个 sub-line 子树每次 O(子树) 重建 + 全量重渲；深子代理树（agent 套 agent）下放大为 O(深度×子树)。
  - 影响：子代理消息重渲成本与子树规模线性，深嵌套时明显卡顿（与顶层投影缓存/partMemo 的设计意图不一致）。
  - 修复建议：对 `agentSubMessages`/`normalizeSubLineChildPart` 的结果做按 (parentId, 子项 id) 的实例级缓存（指纹 = 源 item 引用/字段），引用稳定后嵌套 v-memo 才能生效。

- **[S3] TypewriterText：>31 字符的消息总时长突破 500ms 上限（与注释矛盾），且 text 变更后已完成动画不再刷新**
  - 位置：`core/ui/src/components/TypewriterText.vue:29-31`（`intervalMs = Math.max(16, clampedDuration / chars.length)`——长文本时 interval 锁死 16ms，100 字符 ≈ 1.6s、1000 字符 ≈ 16s）；无 text watcher。
  - 问题：docstring 声称「long messages still finish within the upper bound」与实现不符；`displayed` 只在 interval 回调里推进，若 `text` prop 在动画结束后变化（如消息内容更新），展示内容停留在旧文本。叠加已知问题 `typingMessageIds` 只 add 不 delete（`demo/App.vue:2439`），窗口化历史重挂载时同一消息会重放打字动画（最长可达分钟级）。
  - 影响：长用户消息的动画异常冗长；重挂载重放。
  - 修复建议：长文本按 500ms 上限等比分帧（`interval = clampedDuration / chars.length` 不再夹 16ms 下限），或超长文本跳过动画；补 `watch(() => props.text)` 直接同步终态。

- **[S3] `imageSrc` 本地文件路径拼接未净化 `..`：`workRoot + artifact.uri` 可能越过 work_root 读取任意本地文件**
  - 位置：`core/ui/src/components/MessageView.vue:2865-2876`（`abs = ${workRoot}\\${path.replace(/\//g, '\\')}` → `__LAMTOOLS_FILE_SRC__`（`core/desktop/src/main.ts:25-32` 的 `convertFileSrc` asset 协议））。
  - 问题：`artifact.uri` 来自工具结果的 artifacts（模型输出可控），若含 `..\..\` 前缀，拼接后绝对路径可指向 work_root 之外；是否真正越权取决于 Tauri asset 协议 scope 的 Rust 侧校验（本审计未及 Rust 配置）。
  - 影响：潜在本地文件越权读取并展示（图片外泄给模型/用户可见）；风险中等、依赖外层防线。
  - 修复建议：拼接前规范化并校验 `abs` 位于 `workRoot` 之下（`path.resolve` + `startsWith` 检查）；或拒绝含 `..` 段的 uri。

### S4（建议）

- **[S4] `markdownCache` 驱逐策略是 FIFO 而非文档所称 LRU，且永不清除**
  - 位置：`core/ui/src/components/MarkdownRenderer.vue:331-334`（`map.keys().next()` 删最早插入键）；`docs/core-ui-streaming-perf.md` E4 称「LRU 100 条」。
  - 影响：常被命中的旧条目会被新条目挤出（扩容/折叠反复切换同一大内容时缓存命中率下降）；100 条大 HTML 常驻内存（有界，可接受）。
  - 修复建议：命中时 `delete` + 重新 `set` 实现真 LRU；或改文档措辞。

- **[S4] 超大 diff/工具输出无行数上限：`diffDisplayLines` 全量生成 DOM 行**
  - 位置：`core/ui/src/components/MessageView.vue:2159-2163` + 模板 `276-279` 等 v-for。
  - 影响：read_file 巨文件（数万行）展开时创建数万 diff-line 节点，主线程卡死级白屏风险。
  - 修复建议：限制渲染行数（如 2000 行 + 「已截断」提示），或虚拟滚动。

- **[S4] 工具输出文本被重复解析：`splitToolOutput` 每渲染被调用多次**
  - 位置：`core/ui/src/components/MessageView.vue:2824-2839`（`toolOutputContent`/`toolMetaText`/`commandDisplayText`/`commandOutputText` 各自重新 split 同一字符串）。
  - 影响：大输出下 O(n) 冗余扫描；修复建议：单次解析并缓存。

- **[S4] `partCompletionTimers` 未在 `onBeforeUnmount` 清理**
  - 位置：`core/ui/src/components/MessageView.vue:1851、2482-2484`（unmount 只清了 `copiedActionTimer`）。
  - 影响：卸载后最多 1s 的悬空 setTimeout（仅写 ref，无实际危害）；修复建议：unmount 时遍历清理。

- **[S4] ChatThread 的 v-memo 键含整个 `checkpointTurnIds` Set 引用（未每消息布尔化）**
  - 位置：`core/ui/src/components/ChatThread.vue:12`。
  - 影响：checkpoint 集合更新（turn 边界）时整线 v-memo 缓存一次失效、全量重渲；频率低但与该文件 `processExpandedIds.has(msg.id)` 的既有模式不一致。
  - 修复建议：改为 `checkpointTurnIds.has(msg.id)`（注意 Set 内部 `has` 在引用变化后的求值时机）。

- **[S4] `restoreMath` 的 token 替换会命中用户文本中的字面 token；`$` 行内数学正则对价格类文本误判**
  - 位置：`core/ui/src/components/MarkdownRenderer.vue:166-168`（`replaceAll('@@LAM_MATH_0@@')`）、`161`（`(^|[^\\$])\$([^\n$]+?)\$` 对 `$5 and $10` 类文本整体匹配）。
  - 影响：极端输入下文本被数学化（katex 自带转义，无安全风险，仅样式/内容失真）；修复建议：token 加随机盐 + 限制 `$` 前后须为空白/行首。

- **[S4] `splitFencedCode` 不识别未闭合围栏：` ``` ` 之后未闭合的数学公式仍会被替换**
  - 位置：`core/ui/src/components/MarkdownRenderer.vue:133-145`。
  - 影响：未闭合代码块内 `$$...$$` 被当公式处理；修复建议：围栏配对后处理尾部未闭合段。

- **[S4] DOMPurify 使用全默认配置（未收紧 `style`/`iframe` 等）**
  - 位置：`core/ui/src/components/MarkdownRenderer.vue:326`。
  - 影响：内联 style 与空 iframe 可通过（无脚本执行风险，但存在 UI 覆盖式钓鱼/布局破坏的可能）；修复建议：显式 `FORBID_TAGS: ['style','iframe','form','input']` 等并按需收紧。

## 3. 该区 Top 3 问题

1. **主线消息无 `metadata.live` 打标 → live 流式渲染路径（增量 streaming markdown、part 自动展开、live 状态条）在主流程整体不生效**（S1）：主消息流式实际走 history 分支的非 streaming 全量重解析路径，阶段 3/4 的核心优化在默认主路径上形同虚设，长文本流式卡顿与工具过程不可见并存。证据链完整（selectors/workbenchProjection/MessageView 三处对照 + git 历史确认非新回归），建议尽快接线验证。
2. **mermaid 模块级共享状态跨实例污染**（S2）：多消息同帧含 mermaid 时渲染错图/缺图，重复 SVG id，属渲染正确性缺陷。
3. **history 分支无 file_diff/command_output 渲染分支**（S3）：完成态消息中这两类 part 静默丢失；live 分支同样存在 error/decision 等流式期间不可见缺口。

## 4. 亮点

- **part 级 v-memo 隔离设计完整**：`partMemo`（MessageView.vue:1769-1778）依赖键覆盖 part 引用 + 全部展开/折叠状态 + 决策草稿，与投影缓存（阶段 1）的引用稳定性严格配套；`nextCoreProcessExpandedIds` 内容稳定返回同一 Set 引用（workbenchProjection.ts:388-405），从根上避免整线重渲。
- **流式增量分段渲染**（MarkdownRenderer.vue:252-284）：仅重建尾部开放段、已闭合段 DOM 节点跨 tick 复用，O(tail)/tick；等价性验证方法（随机流 textContent + 块结构对比）与 `normalizeMarkdownLineBreaks` 4-pass 正确性论证（" \n " 重叠空白）都是严谨工程。
- **XSS 面收束干净**：全库唯一 v-html 入口在 MarkdownRenderer；streaming 路径所有用户输入先 escapeHtml（单 pass 字符映射，字节等价验证），输出仅 p/ul/ol/pre/code/strong/span 且属性仅 escapeHtml 后的 language-*；katex 自带转义；mermaid 用 `securityLevel: 'sandbox'`；完成态 DOMPurify 兜底；链接协议白名单 `isExternalUrl` 仅 http(s) + 点击拦截 + `afterSanitizeAttributes` 统一 `target=_blank`/`rel=noopener noreferrer`。
- **资源清理总体到位**：`copiedActionTimer`、v-beam 的 rAF/flowEls 增删、MarkdownRenderer 的 click 监听与 `clearStreamedSegments`、TypewriterText 的 interval 均有成对清理；`streaming→false` 切换时 DOM 交还 v-html 分支的处理正确。

## 5. 审计范围与方法

- 范围：`core/ui/src/components/MessageView.vue`（4098 行全文）、`MarkdownRenderer.vue`（539 行全文）、`TypewriterText.vue`（全文）、`helpers/openUrl.ts`；为验证「live 打标来源 / part 类型产出 / 嵌套子线引用」追溯至 `appServer/selectors.ts`、`appServer/workbenchProjection.ts`、`appServer/messageParts.ts`、`composables/useCoreWorkbenchProjectionController.ts`、`agents/subAgentProjection.ts`、`components/ChatThread.vue`、`demo/App.vue`、`core/desktop/src/main.ts`（均为只读）。
- 方法：逐行阅读 + grep 全仓交叉验证（`metadata.live`/`timeline` 赋值点、`partType` 覆盖矩阵、v-memo 键、定时器/监听器成对性）+ git log/git show 比对历史版本（确认 live 缺口非本次重构引入）+ 以 `docs/core-ui-streaming-perf.md` 为已知设计基线排除误报。
- 限制：全程只读，未运行测试/dev server；「live 缺口」与 mermaid 污染为静态代码推理，建议以一次真实长流式会话（多 mermaid 消息）人工复核为准。
