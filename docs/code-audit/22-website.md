# 22 website 官网 审计报告

审计时间：2026-08-13　审计区：22（官网 website/）　方式：静态只读审计（全程未修改任何代码文件，未运行 dev/build）
严重度定义：S1=严重（白屏/构建失败/展示假数据与真实模型不符）；S2=中等（功能失效/契约断裂）；S3=轻微；S4=建议

## 1. 概况

本区为官网（Vue 3.5 + Vite 8 + TS 6 + anime.js v4.5 + lucide-vue-next），共约 2,030 行源码：App.vue / main.ts、7 个页面组件（Hero/Features/Showcase/Architecture/Download/SiteNav/SiteFooter）、composables/useScrollReveal.ts、utils/inView.ts、mock/session-script.ts、styles/sections.css，以及 package.json / vite.config.ts / index.html / tsconfig.json。

总体印象：**Showcase 展示区"真实 UI 直挂"的实现质量很高**——所有 props/slots/类型与 core/ui 真实组件逐项核对一致（WorkspaceShell defineExpose 的 toggleLeftPinned/toggleRightPinned、SessionSidebar 的 ProjectGroup 形状与状态语义、ChatThread 的 v-memo 消息引用依赖、MessageView 的 live/timeline/liveStatus/model_text/processExpandedIds 渲染分支、CoreResourceStats 的 processMetrics 字段名、coreThinkingModeOptions 的 CoreThinkingMode 取值），mock 数据与真实数据模型吻合；commitMsg"新对象提交"约定严格执行（每次变更提交新消息对象、未变 part 保持引用以命中 part 级 v-memo）；`.mock-window .thread` 覆盖样式正确放在全局 sections.css；vue alias 单例配置正确且必要（core/ui/node_modules 中确实存在第二份 vue 实例）。anime.js v4 的 animate/stagger/onScroll/autoplay/revert 用法均正确（已实测）。

主要问题集中在：① 依赖契约不完整（core/ui 依赖链的 marked/dompurify/katex/mermaid 未声明进 package.json，仅靠 core/ui/node_modules 在场才能构建）；② 一处 anime.js v3→v4 API 迁移遗漏（`complete` 回调在 v4 中于动画 setup 阶段即被误调用，已实测确认）；③ 若干演示数据/逻辑的死代码与静默失效（waitVisible 从未调用、active-turn 高亮永不生效、mock/session-script.ts 无人引用）。

问题统计：S1=0，S2=1，S3=5，S4=9，共 15 条。

## 2. 问题清单

- **[S2] website/package.json 未声明 core/ui 依赖链的运行依赖（marked/dompurify/katex/mermaid），全新环境无法按文档流程构建**
  位置：`website/package.json:15-24`（dependencies 仅 animejs/lucide-vue-next/vue）；依赖链入口 `core/ui/src/components/MessageView.vue:1585` → `core/ui/src/components/MarkdownRenderer.vue:11-14`（`marked`/`DOMPurify`/`katex` + `katex/dist/katex.min.css`）、`:58`（函数内 `import('mermaid')` 动态导入，vite build 同样会静态解析）
  问题：这些包只存在于 `core/ui/node_modules`（git 忽略、不随仓库分发）。node 解析从"导入方文件目录"向上查找，`MarkdownRenderer.vue` 的裸导入不会命中 `website/node_modules`；当前能构建纯粹因为本机 core/ui/node_modules 恰好在场（`website/dist/` 上次构建于 08-12 12:23）。全新 clone 后按 AGENTS.md 的 `cd website && npm run dev/build` 流程，vite 将报 "Could not resolve 'marked' / 'dompurify' / 'katex' / 'mermaid'" 直接失败。
  影响：文档化开发/构建流程在干净环境必然断裂（S2）；当前环境只是"侥幸可用"。
  修复建议：把这些依赖显式加入 `website/package.json`（版本与 core/ui/package.json 对齐），或在 README/AGENTS 中写明"先安装 core/ui 依赖"的前置步骤。

- **[S3] useScrollReveal 使用 anime.js v3 的 `complete` 回调名（v4 不识别），回调在动画 setup 阶段即被误调用，完成清理全部失效**
  位置：`website/src/composables/useScrollReveal.ts:34`（`complete: () => { ... }`），函数体 `:28-40`
  问题：anime.js v4 的参数解析（`dist/modules/animatable/animatable.js` 构造器）把所有非 `globals.defaults` 键当作**动画属性**而非回调：`complete` 被当作名为 complete 的 tween 属性，其函数值被当作 duration 函数。已用 node 桩环境实测 animejs 4.5.0：`complete` 回调在 `animate()` 调用后约 1ms（动画 setup 阶段）即执行，早于 `onBegin@20ms`、`onComplete@726ms`。因此 `useScrollReveal.reveal()` 里"动画完成后加 is-visible、清 inline 样式"的意图完全落空：is-visible 在入场动画开始前就被加上，动画结束后 inline `opacity/transform` 残留、`will-change` 不释放。
  影响：视觉终态仍正确（动画本身照常执行到终值），但清理逻辑整体失效，属于 v3→v4 API 迁移遗漏；后续若有人依赖该回调时机（如在完成时切 class）会得到错误时序。
  修复建议：改为 v4 回调名 `onComplete`（实测 720ms 动画在 726ms 正常触发）。

- **[S3] mock/session-script.ts 为死代码，且与 Showcase.vue 内联常量重复，存在数据漂移风险**
  位置：`website/src/mock/session-script.ts:23-60`（`MOCK_SESSIONS`/`MOCK_SCRIPT` 全仓库无任何 import）；`website/src/components/Showcase.vue:37-50`（侧栏数据）、`:63-68`（USER_TEXT/REASONING_TEXT/README_RESULT/TREE_RESULT/ANSWER_TEXT 内联）
  问题：全仓库 grep 该文件仅出现声明处；Showcase.vue 把脚本内容全部内联重写了一遍（对话脚本、侧栏会话列表、工具结果文本均重复）。文件头注释自称"Showcase.vue 按序渲染并驱动动画"，与事实不符。
  影响：两处数据各自维护，改一处忘另一处即产生演示内容不一致；误导后续维护者以为该文件是播放脚本的数据源。
  修复建议：删除 `mock/session-script.ts`，或让 Showcase.vue 真正 import 消费它（消除内联重复）。

- **[S3] waitVisible/windowInViewport 为死代码：演示循环不等待展示窗口可见，首屏时机不可控且离屏持续渲染**
  位置：`website/src/components/Showcase.vue:82-91`（windowInViewport/waitVisible 定义，从未被调用）、`:285`（`onMounted` 直接 `void playTurn()`）
  问题：`waitVisible` 的设计意图（窗口进入视口才开播，规避本环境 IO 回调不可靠）未接线：playTurn 从挂载即开始。用户滚动到展示区前（首屏 hero 100vh 之后），第一轮约 12s 的播放可能已进行一半甚至进入下一轮；展示区离开视口后循环仍持续执行——typewriter 每 14ms 一次 `replacePart`+`commitMsg`，每次都是新消息对象，消息级 v-memo 失效触发整条消息重渲染（part 级 v-memo 仍隔离）。
  影响：演示新鲜度/节奏不可控 + 离屏持续做无意义渲染（移动端尤甚）。
  修复建议：在 `playTurn()` 开头 `await waitVisible()`（该函数已就绪，仅未接线）。

- **[S3] active-turn 高亮静默失效：mock 消息 id 不符合真实 `assistant:<turn>` 约定，"正在输出"三圆点永不渲染**
  位置：`website/src/components/Showcase.vue:146`（`id: 'mock-turn-'+turnSeq`）、`:387`（`:active-turn-id="running ? \`mock-turn-${turnSeq}\` : null"`）；`core/ui/src/components/MessageView.vue:2222-2229`（isActiveTurnMessage）、`core/ui/src/appServer/selectors.ts:272-277`（assistantSegmentTurnId 仅认 `assistant:` 前缀）
  问题：`assistantSegmentTurnId('mock-turn-1')` 返回 `''`，`'' === 'mock-turn-1'` 恒为 false，`streaming-dots`（MessageView.vue:1517）在 running 期间永不显示。真实 app 的消息 id 形如 `assistant:<session>:turn:<run>`（selectors.ts:116）。
  影响：演示"运行中 turn 底部三圆点"能力实为静默失效，与"真实 UI 直挂"的保真目标相悖。
  修复建议：mock 消息 id 改为 `assistant:mock:<session>:turn:<seq>` 形状，activeTurnId 传对应的 turn 部分。

- **[S3] 右侧栏 pin 状态与 useShellLayout 的 localStorage 持久化冲突：用户点过 pin 后刷新，右栏会被 onMounted 的 toggle 反转为关闭**
  位置：`website/src/components/Showcase.vue:267-270`（onMounted 无条件 `shellRef.value?.toggleRightPinned()`）；`core/ui/src/composables/useShellLayout.ts:34-35`（默认 rightPinned=false）、`:249-266`（storageKey 持久化 pin 状态）
  问题：首次访问（无持久化）时 rightPinned=false → toggle 一次后正确打开；但用户点过 TitleBar pin 后状态写入 localStorage（storage-key="lamtools.site.showcase"），下次加载 shell 初始 rightPinned 即 true，onMounted 的 toggle 又把它翻回 false——右栏"运行状态"意外关闭，而 mock 侧传给 TitleBar 的 rightPinned ref 仍为 true，两者不一致。
  影响：刷新/重访后演示状态错误（资源统计面板消失，TitleBar 却显示已 pin）。
  修复建议：onMounted 改为"确保打开"语义（`if (!shellRef.value?.rightPinned) shellRef.value?.toggleRightPinned()`），或让 mock 使用不可持久化的 storageKey。

- **[S4] 整个 website/ 目录被 .gitignore 排除，源码无版本控制（有意为之但有风险）**
  位置：`E:\LamTools\.gitignore:135-136`（注释 "# Website — not ready, not uploaded" + `/website/`）
  问题：`git log --all -- website/` 无任何提交。注释表明是有意排除，但官网全部源码（含将随发布替换的下载地址等）目前零历史、零回滚能力。
  影响：误删/误改不可恢复；将来"发布"时需一次性入库，无演进记录。
  修复建议：保持现状亦可，但建议在站点进入发布流程时移除该条目并提交（至少 src/、package.json、vite.config.ts）。

- **[S4] Download.vue 模板类名 site-btn-disabled 与 scoped 样式 .btn-disabled 不匹配，cursor 规则永不生效**
  位置：`website/src/components/Download.vue:71`（`class="site-btn site-btn-secondary site-btn-disabled"`）、`:145-147`（`.btn-disabled { cursor: default; }`）
  问题：选择器对不上；且 `aria-disabled` 挂在 span 上无对应 role，语义不完整。`.download-card.disabled` 已降透明度，cursor 未置默认。
  修复建议：样式改为 `.site-btn-disabled { cursor: default; }`（或统一类名）。

- **[S4] 侧栏 active 会话与正在播放的线程内容不一致（mock-s2 高亮但线程播的是 mock-s1 的内容）**
  位置：`website/src/components/Showcase.vue:348`（`:active-session-id="'mock-s2'"`，即"重构 web search 模块"）、`:370-372`（线程标题"梳理 LamTools 仓库结构"= mock-s1）
  问题：侧栏高亮会话与线程播放脚本不属于同一会话，观感矛盾。
  修复建议：active-session-id 改为 'mock-s1'，或让线程脚本/标题与 mock-s2 对齐。

- **[S4] Download.vue 版本占位 0.2.1 已过期（仓库当前版本 0.2.3）**
  位置：`website/src/components/Download.vue:5`（`VERSION = '0.2.1'`）；`core/src/lamtools_core/__init__.py:3`（0.2.3）
  问题：虽标注为占位，但展示给用户看的安装包名/大小是过期版本号，若站点先行上线会展示错误版本。
  修复建议：发布前替换真实版本与下载地址；若保留占位建议同步为当前版本。

- **[S4] index.html 的 title/description 文案未按约定标注 TODO(文案)**
  位置：`website/index.html:12-15`
  问题：AGENTS.md 约定"全部文案是占位，标 TODO(文案)"，各组件均遵守，但 index.html 的站点标题与 description 未标。
  修复建议：补 `<!-- TODO(文案) -->` 标记或确认其为正式文案。

- **[S4] SiteFooter 的 .site-footer-faint 与 Hero 的 .reveal-in 为无样式死类**
  位置：`website/src/components/SiteFooter.vue:61`（`<span class="site-footer-faint">保留所有权利</span>`）、`website/src/components/Hero.vue:71`（`class="hero-eyebrow reveal-in"`）
  问题：全站无任何选择器定义这两个类（scoped/全局均无），属遗留类名（reveal-in 暗示曾计划做入场动效）。
  修复建议：删除或补样式。

- **[S4] playTurn 卸载后的异步尾巴缺少 disposed 检查（onUnmounted 只能清到当前 pending 的 sleep）**
  位置：`website/src/components/Showcase.vue:131-142`（首个 sleep 后无 `if (disposed) return`）、`:288-292`（onUnmounted 仅 `clearTimeout(timer)`）
  问题：组件卸载时若处于任意 await 间隙，playTurn 会继续执行若干次 ref 写入与一次 `messages.value = [userMsg]` 重置（typewriter 循环内已检查 disposed，递归尾部也已检查，实际无渲染副作用、无泄漏）。
  影响：纯健壮性问题，当前单页站点不会触发；未来若展示区可卸载需补全。
  修复建议：每个 `await sleep(...)` 后补 `if (disposed) return`。

- **[S4] 入场动效按元素注册 scroll/resize 监听（每个 .reveal 一套监听器）**
  位置：`website/src/utils/inView.ts:45-46`（每元素 addEventListener）、`website/src/composables/useScrollReveal.ts:60-65`（watchAll 遍历全部 .reveal）
  问题：约 20 个 .reveal 元素 → 20 组 scroll/resize 监听，每个 scroll 事件触发 20 次 getBoundingClientRect。当前规模 passive 且数量小，无实际性能压力。
  修复建议：可选优化——单一共享监听 + 元素集合批量检查（rAF 合并已在单元素内做了，全局合并收益有限）。

- **[S4] TitleBar Tauri shim 的 reject 未捕获：点击窗口控制按钮产生 Unhandled promise rejection**
  位置：`website/src/components/Showcase.vue:19-21`（shim `invoke: () => Promise.reject(...)`）；`core/ui/src/components/TitleBar.vue:87-89`（onMinimize/onMaximize/onClose 直接调用不 catch）
  问题：注释已知晓"仅点击才触发"，但点击最小化/最大化/关闭按钮会在控制台抛 Unhandled rejection。
  修复建议：shim 改为 `Promise.resolve()`（无副作用且消除报错），或 TitleBar 侧 catch。

- **[S4] website/node_modules 中 vue-tsc（3.3.9）未声明在 package.json**
  位置：`website/package.json:20-24`（devDependencies 无 vue-tsc），`website/node_modules/vue-tsc` 实际存在
  问题：与 AGENTS.md"未挂 vue-tsc"的描述一致（脚本未使用），但残留的未声明包会造成依赖清单与安装产物不一致的假象。
  修复建议：`npm uninstall vue-tsc` 或补进 devDependencies。

## 3. 该区 Top 3 问题

1. **[S2] 依赖契约断裂**：marked/dompurify/katex/mermaid 未声明进 `website/package.json`，仅依赖 `core/ui/node_modules` 在场才能构建（`package.json:15-24`）。干净环境按文档流程必然构建失败。
2. **[S3] anime.js v4 回调名迁移遗漏**：`useScrollReveal.ts:34` 的 `complete` 在 v4 中被当作动画属性，实测于 setup 阶段（~1ms）被误调用而非动画完成时，清理逻辑整体失效，终态靠 inline 样式残留维持。
3. **[S3] 演示保真度静默失效**：`waitVisible` 死代码导致离屏持续渲染、首屏节奏不可控（Showcase.vue:82-91/285）；mock 消息 id 不合 `assistant:` 约定导致"正在输出"三圆点永不显示（Showcase.vue:146/387）。

## 4. 亮点

- **真实 UI 直挂执行彻底**：Showcase 直接复用 core/ui 真实组件（TitleBar/WorkspaceShell/SessionSidebar/ChatThread/CoreExecutionControls/CoreResourceStats/CoreSessionTitleEditor）与真实样式，props/slots/defineExpose/类型逐项核对全部匹配；`transform: translateZ(0)` 把 position:fixed 的 shell 装进窗口卡片的方案简洁有效。
- **数据模型对齐严格**：mock 消息严格按 CoreMessage/MessagePart 形状构造；metadata.live/timeline/liveStatus、model_text part + msg.content 全文、processMetrics 字段名（estimated_prompt_tokens/context_window_tokens/llm_calls/input_tokens/output_tokens/cache_hit_rate）与 MessageView/buildCoreResourceSummary 实际读取一致；context-window 1074176 与资源统计数字自洽（8.8k/1049k·1%）。
- **commitMsg 约定与 v-memo 协同**：每次变更提交新消息对象、未变 part 保持引用，与 ChatThread.vue:12 消息级 v-memo + part 级 v-memo 的机制完全匹配，演示即真实性能路径。
- **动效基础设施正确**：inView.ts 的 scroll+rAF 一次性检测（含清理与首屏立即触发）不依赖 IntersectionObserver，符合 AGENTS 的 headless 环境约束；Architecture/Hero/Showcase 的 onScroll 滚动联动与 stagger 均为 v4 正确用法；prefers-reduced-motion 全路径降级。
- **全局覆盖规则遵守**：`.mock-window .thread { align-content: end }` 放全局 sections.css（scoped 属性选择器匹配不到 WorkspaceShell 渲染节点），并明确注释真实 app 仍是顶对齐。
- **构建配置正确**：vue alias 单例（含子路径前缀匹配）解决第二份 vue 白屏；fs.allow 覆盖 core/ui；strictPort 5199 不与 5172/5173 冲突。

## 5. 审计范围与方法

范围：`website/` 全部源码（App.vue、main.ts、components/ 7 个组件、composables/useScrollReveal.ts、utils/inView.ts、mock/session-script.ts、styles/sections.css、package.json、vite.config.ts、index.html、tsconfig.json），以及为验证真实性对照的 `core/ui/src`（types.ts、ChatThread/MessageView/WorkspaceShell/SessionSidebar/CoreExecutionControls/CoreResourceStats/CoreSessionTitleEditor/TitleBar/MarkdownRenderer、appServer/selectors.ts、runtime/resources.ts、composables/useShellLayout.ts、styles/variables.css/layout.css、demo/App.vue、index.ts）。

方法：静态逐文件阅读 + 交叉比对真实类型/组件契约（props、slots、defineExpose、v-memo 依赖、渲染分支、localStorage 持久化语义）+ 依赖解析链验证（node 解析规则、node_modules 实际内容、git 跟踪状态）+ 对 animejs 4.5.0 的 `complete`/`onComplete` 回调时序做了 node 桩环境实测（结果：complete 于 setup ~1ms 触发、onComplete 于 726ms 触发）。全程只读，未运行 npm run dev/build，未修改任何代码文件。
