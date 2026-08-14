# 21 前端契约测试 审计报告

> 审计日期：2026-08-13 ｜ 范围：`core/ui/tests/` 全部 49 个 Vitest 契约测试文件（约 9.3k 行）+ `tests/setup.ts`、`package.json` 脚本、`vite.config.ts` 的 test 段、`tsconfig.json`/`tsconfig.demo.json`、`.github/workflows/ci.yml`，并交叉核对被测对象 `src/components/ChatThread.vue`、`MessageView.vue`、`appServer/*`（store/selectors/workbenchProjection/workbenchActions/protocol）、`composables/*`。全程只读；抽样运行 5 个代表性测试文件验证 harness 正常（全部通过）。
> 前置阅读：docs/code-audit/16-chatthread-store.md（本区测试应对其 S2/S3/S4 缺陷提供回归保护——第 2 节第 1 条据此判定）。

## 1. 概况

测试资产规模：49 个 `.test.ts` + `setup.ts`，共 9336 行、63 个 describe、321 个用例。按被测对象分布：

- **appServer 状态层**（约 40%）：store 708 行、selectors 410 行、workbenchProjection 554 行、投影缓存 192 行、投影控制器 269 行、投影窗口 114 行、workbenchActions 245 行、sub-agent 流式缓存 174 行、debug-step-by-step 90 行。
- **ChatThread/MessageView**（约 30%）：chat-thread-process 2021 行（45 个用例）、隔离 97 行、rollback 69 行、bench 55 行。
- **composables/组件**（约 30%）：live-composer-controller 401 行、approval-controller 186 行、execution-controls-state 251 行、sub-agent 351 行、settings 186 行、slot-contract 329 行等。

**总体评价：质量高于一般前端仓库。** 无快照测试（0 个 `toMatchSnapshot`）、无 `.only/.skip`、无 `@ts-ignore`；store 测试通过注入 `scheduleFrame` 精确驱动帧回调，确定性极佳；隔离测试用 `vi.mock` 替换 MessageView 直接计数渲染次数，精确锚定 v-memo 隔离契约；回归测试普遍带文档化注释（注明"Regression:"）。**主要问题集中在三处**：① 对 16 区已确认 S2 缺陷（快照前事件丢弃）无回归测试；② MessageView 自动展开/折叠机制（模块级状态 + 1s 定时器）零测试且无卸载清理；③ 相当比例的"源码嗅探"测试（readFileSync 断言 .vue 源文本/CSS 字符串）脆弱，且 update-state/core-settings 以"测试环境无法渲染 SettingsShell"为由退回源码断言，掩盖了真实渲染问题。

CI（ci.yml:49-72）在 ubuntu-latest 上依次跑 `npm run typecheck`（vue-tsc，只覆盖 src）→ `npm run test:contract`（vitest run）→ `npm run build`，链路完整；Windows 本地与 Linux CI 的差异经抽样验证无路径/换行问题（源码嗅探测试均用 `import.meta.dirname`/正则匹配，跨平台稳定）。

## 2. 问题清单

### S2

- **[S2] 16 区已确认缺陷"首个快照落地前流式事件被静默丢弃"没有任何回归测试**
  - 位置：`tests/core-app-server-store.test.ts`（全部 9 个涉及 connect 的用例都先 `await controller.connect(...)` 等到 resume 快照落地后才调用 `onEvent`）；对应缺陷代码 `src/appServer/store.ts:205`（帧回调 `if (!runtime.state) return`）与 `store.ts:186-188`（enqueueEvent 先记 id 再丢事件）。
  - 问题：审计 16 区（16-chatthread-store.md 第 2 节 S2）确认"事件在 `runtime.state` 为 null 时被静默丢弃、turn 内容永久缺块"且 hydrate 跳过判定无法自愈。本区核查发现测试基础设施完全支持该场景（fakeClient 的 `thread/resume` 可改为延迟 resolve），但没有任何用例覆盖"事件先于快照到达"的窗口——所有用例都恰好避开缺陷路径。
  - 影响：该 S2 缺陷在测试套件中不可见：修复后无回归保护，重新引入也不会变红；多窗口并存/断线重连/启动期他人 turn 流式这三种真实场景的"内容缺块"一直是黑盒。
  - 修复建议：新增用例：`connect` 返回延迟 promise（或先手动调用 `enqueueEvent` 再 resolve snapshot），先发 transient delta 事件、断言帧回调后内容未丢；再补"重连后事件与快照竞态"的用例，断言 `shouldHydrateSnapshot` 在 core.items 内容与事件派生状态分歧时强制 hydrate（对应 16 区建议的 b 方案）。

- **[S2] MessageView 自动展开/折叠机制（autoExpandedPartIds + 1s 定时器）零测试覆盖，且模块级状态无卸载清理**
  - 位置：`src/components/MessageView.vue:1849-1894`（模块级 `autoExpandedPartIds` ref + `partCompletionTimers` Map + `schedulePartAutoCollapse` 1000ms 定时器 + watch 状态转换驱动）；`MessageView.vue:2482-2485`（`onBeforeUnmount` 只清理 `copiedActionTimer`，不清理 partCompletionTimers/autoExpandedPartIds）。
  - 问题：全部 49 个测试文件无一处 `vi.useFakeTimers` 靠近该机制，展开/折叠一律通过外部 `processExpandedIds` prop 驱动；"running→completed 状态转换触发自动展开、1 秒后自动折叠"这一流式核心交互完全无契约。同时该状态是**模块级**：a) 定时器在组件卸载后仍会触发并原地改写共享 ref（若未来测试触发状态转换，真实 1s 定时器会污染同文件后续用例）；b) 生产环境切线程后旧 part id 在集合中残留不清理（同类于 16 区已列的 typingMessageIds 只增不删问题），若新线程 part id 与残留 id 相同会错误展开。
  - 影响：流式 UI 最活跃的交互行为无回归保护；模块级可变状态 + 未清理定时器是测试隔离与生产内存的隐患源。
  - 修复建议：`onBeforeUnmount` 中清除本实例相关的 partCompletionTimers 并摘除 autoExpandedPartIds 条目；新增用例用 `vi.useFakeTimers` 驱动：live 消息 part running→completed 后自动展开、`vi.advanceTimersByTime(1000)` 后自动折叠、期间用户手动展开则取消折叠定时器。

- **[S2] 强制重置运行中 turn（forceResetTurn / forceResetActiveTurn）零测试覆盖**
  - 位置：`src/composables/useCoreLiveTurnController.ts:79-88`（`forceResetActiveTurn`）、`src/composables/useCoreLiveComposerController.ts:239-243`（force 分支）；测试 `tests/core-live-turn-controller.test.ts`（3 用例仅覆盖 connect/start/interrupt）、`tests/core-live-composer-controller.test.ts`（8 用例覆盖 resetForThreadChange、命令清理、目录加载竞态，但无一触及 force 路径）。
  - 问题：`forceResetActiveTurn` 是"绕过 active-turn 守卫强制重置"的独立代码路径（ensureConnected + forceResetTurn + lastError 处理），与普通 interrupt 语义不同（如重置后本地快照 applyResponse 到 post-reset 状态），当前无任何用例断言其调用契约、失败分支（forceResetTurn reject → lastError + 返回 false）与成功分支。
  - 影响：用户侧"强制重置卡死 turn"操作无回归保护；该路径含连接恢复与错误上报逻辑，是组合 bug 高发区。
  - 修复建议：在 core-live-turn-controller.test.ts 补 forceResetActiveTurn 成功/失败/未连接三态用例；在 composer 测试补 force 分支状态文案（forceResetting/forceResetFailed）与 applyResponse 后状态同步的用例。

### S3

- **[S3] 源码嗅探测试占比高且脆弱；SettingsShell"无法渲染"被固化成源码断言而非修复**
  - 位置：`tests/chat-thread-process.test.ts:133/328/1463/1686/1699`（5 处 readFileSync 匹配 ChatThread.vue 的 CSS 规则文本，含硬编码色值 `#b49a60`、`background: transparent`、`max-height: none` 等）；`tests/update-state.test.ts:89-117` 与 `tests/core-settings.test.ts:116-165`（整段注释承认"SettingsShell 存在 pre-existing recursive-update issue，测试环境无法渲染"，改为断言源文本含某字符串）；另有 `tests/package-boundary-contract.test.ts`、`tests/markdown-renderer-style.test.ts`、`tests/workspace-shell.test.ts:92`、`tests/core-session-rollback-demo.test.ts`、`tests/core-project-components.test.ts:118-127`（`readFileSync(process.cwd(), ...)`）、`tests/core-sub-agent.test.ts:293` 共 9 个文件的同类断言。
  - 问题：a) 正则匹配 CSS 属性书写顺序/具体色值/`@media` 块次序（如 `layoutCss.match(/@media \(max-width: 640px\) \{([\s\S]*?)@media \(max-width: 480px\)/)`），任何样式变量化、换行、规则重排都触发假红；b) 断言的是"源码文本存在"而非"行为正确"——把文本删掉换等价实现测试照样绿或红，无法保护真实行为；c) update-state/core-settings 的规避是**把测试环境缺陷固化为契约**：SettingsShell 渲染问题（recursive-update）才是应当修复的根因。
  - 影响：高频误报消耗维护成本、降低测试可信度；SettingsShell 的真实渲染行为（含"关于与更新"section）长期无行为级验证。
  - 修复建议：先修复 SettingsShell 的 recursive-update 问题并改为真实挂载断言（update-state.test.ts 已注明是"pre-existing issue on this branch"，应提 bug 修复而非接受）；CSS 规则断言收敛为：类名存在性 + 关键属性用 `toContain` 单行匹配（去掉顺序/色值耦合），或引入按计算样式的断言。

- **[S3] messageview-update-bench.test.ts 是无效基准：`expect(true).toBe(true)` 无任何断言**
  - 位置：`tests/messageview-update-bench.test.ts:52-53`（`console.log` 打印 per-tick 毫秒后 `expect(true).toBe(true)`，60s 超时）。
  - 问题：30 轮 × 300-part live 消息更新只输出耗时，不设任何阈值或行为断言；MessageView 渲染性能退化（v-memo/partMemo 回归）时测试依旧全绿；同时在 CI 全量运行中产生噪音输出。
  - 影响：该文件是唯一直接挂载 MessageView 大规模消息的测试，却对"增量渲染"契约零约束——与 16 区 perf 文档强调的每消息 v-memo/partMemo 缓存恰好是同一关注点。
  - 修复建议：a) 给 per-tick 设宽松软阈值（如 < 50ms，仅防数量级回归）；b) 或改为 spy 断言 partMemo 命中（统计 setProps 后未重渲的 part 节点数）；c) 至少将 `expect(true).toBe(true)` 换成有意义的断言（如末轮 content 正确渲染），否则删除该文件。

- **[S3] 测试文件完全不在类型检查链中（vue-tsc 仅覆盖 src，且缺 @types/node）**
  - 位置：`tsconfig.json`/`tsconfig.demo.json` 的 include 均只有 `src/**` 与 `vite-env.d.ts`，无 tests；`.github/workflows/ci.yml:58` 的 `npm run typecheck` 因此不检查任何测试文件；`package.json` devDependencies 无 `@types/node`（`npm ls @types/node` 为空），而 49 个测试文件大量 `node:fs`/`node:path`/`node:timers/promises`/`import.meta.dirname`。
  - 问题：vitest 经 esbuild 转译运行，不做类型检查；测试文件中的类型错误（含 19 处 `as any`/`as never` 逃逸，如 `update-state.test.ts:71`、`markdown-renderer-style.test.ts` 等）全部漏检。测试断言的数据形状若与真实协议字段拼写不一致（如 `waitingResponse` vs `waitingRequest`），只要测试自洽就永远绿。
  - 影响：契约测试自身无类型护栏，"契约"退化为"测试与测试 helper 之间的约定"。
  - 修复建议：加 `@types/node` 到 devDependencies；新建 `tsconfig.test.json`（include tests + src，noEmit）；`typecheck` 脚本追加 `vue-tsc --noEmit -p tsconfig.test.json`（CI 同步）。

- **[S3] 协议契约无锚定：测试全部手工重造事件/快照对象，protocol.ts 漂移不可见**
  - 位置：`src/appServer/protocol.ts`（`CORE_APP_SERVER_PROTOCOL_VERSION`、`CoreAppEvent`/`CoreAppSnapshot` 形状）仅被 `client.ts` 以 type 引用；测试端 `tests/core-app-server-store.test.ts` 的 `runItemEvent`/`snapshot`/`runUsageEvent` helper 与 `tests/core-workbench-projection-cache.test.ts` 的 `baseSnapshot` 等全部手工构造字面量对象，无一处 `satisfies CoreAppEvent` 类锚定。
  - 问题：store/投影按字符串键鸭子读取，测试构造的字段与 protocol.ts 接口不同步时测试照常通过；后端字段改名（如 approval_request 形状调整）前端静默错乱，测试无法预警。`CORE_APP_SERVER_PROTOCOL_VERSION` 导出但从不发送/校验（16 区已列 S4），测试亦无版本协商用例。
  - 影响：协议演进无护栏；契约测试测的是"自己构造的协议"，不是"代码声明的协议"。
  - 修复建议：测试 helper 的返回类型标注为 `CoreAppEvent`/`CoreAppSnapshot` 并用 `satisfies` 断言（缺失字段立即编译错）；为 client.ts 的 handleMessage 加真实 JSON 帧解析测试（含畸形帧，对应 16 区 client.ts:133 JSON.parse 无 try/catch 的 S4）。

- **[S3] todo_update part 类型零测试覆盖**
  - 位置：`src/components/MessageView.vue:1454`（`v-else-if="group.part.partType === 'plan' || group.part.partType === 'todo_update'"` 独立渲染分支）与 `MessageView.vue:2539`（label 映射 `todo_update: '更新任务'`）；全测试套件 grep `todo_update` 零命中（`plan` 也仅 chat-thread-process.test.ts:1076 的 checklist 用例 1 处）。
  - 问题：write_checklist 工具产生的任务更新流式卡片是用户可见 UI（'更新任务' 过程步），其渲染契约（label/status/内容回退）完全无测试。
  - 影响：该分支的任何回归（如 label 丢失、status 类名错误）直接漏检。
  - 修复建议：在 chat-thread-process.test.ts 补 1-2 个用例：挂载带 todo_update part 的 live 消息，断言 `.process-step--todo_update` 渲染 label 与 detail 回退逻辑。

### S4

- **[S4] FloatingApprovalCard.vue 是死代码：全仓库零引用、零测试，"审批卡超时"审计点在 UI 层不存在**
  - 位置：`src/components/FloatingApprovalCard.vue`（409 行）；`git grep FloatingApprovalCard` 全仓库（src/demo、core-app、tests）零命中；`src/composables/useCoreApprovalController.ts` 也无任何 setTimeout/expiresAt 逻辑。
  - 问题：审计点"审批卡超时"实际在 UI 层不存在——等待状态完全由服务端 `waitingRequest` 驱动（approval 的提交/解析/降级路径已有 core-approval-controller.test.ts 良好覆盖）；悬浮审批卡组件既未接线也无测试，是维护负担。
  - 修复建议：删除该组件，或在接入审批流时补行为测试；审批等待超时若确为产品需求，应在 useCoreApprovalController 层设计并测试（当前无超时语义）。

- **[S4] navigator.clipboard / window.matchMedia 的测试内覆盖未还原，依赖同文件用例顺序**
  - 位置：`tests/chat-thread-rollback.test.ts:60-62`（`Object.defineProperty(navigator, 'clipboard', ...)` 无 afterEach 还原）；`tests/slot-contract.test.ts:113-127`（测试内整体替换 `window.matchMedia`，afterEach 只还原 innerWidth 不还原 matchMedia——setup.ts 的 mock 被永久覆盖）。
  - 问题：当前因两处覆盖均发生在各自文件的最后一个用例而恰好无害；一旦同文件后续新增用例，navigator.clipboard 的 writeText 桩与 matchMedia 的行为会泄漏（vitest 默认按文件隔离，跨文件无泄漏）。
  - 修复建议：`afterEach` 中恢复 `navigator.clipboard`（delete property）与 `window.matchMedia`（重新赋回 setup mock）；workspace-shell.test.ts 的 `vi.unstubAllGlobals()` 是正确范式。

- **[S4] 等待模式与路径依赖：setTimeout(0) 代替 flushPromises、process.cwd() 代替 import.meta.dirname**
  - 位置：`tests/core-execution-controls-state.test.ts:188/245`（及 155 行用例内，共 3 处 `await new Promise((resolve) => setTimeout(resolve, 0))`）；`tests/update-state.test.ts:90`、`tests/core-settings.test.ts:119/129/145`、`tests/core-project-components.test.ts:120`、`tests/core-session-rollback-demo.test.ts:4` 使用 `resolve(process.cwd(), 'src/...')`（其余文件已用 `import.meta.dirname`）。
  - 问题：setTimeout(0) 比 `flushPromises()`/`vi.waitFor` 慢且语义不精确（等待的是宏任务而非微任务队列）；`process.cwd()` 依赖 vitest 运行目录（CI 从 core/ui 运行所以当前不炸，但任何从仓库根/其他目录的调用即失败），是已修复模式（import.meta.dirname）的残留。
  - 修复建议：统一改用 `flushPromises`；`process.cwd()` 全部替换为 `import.meta.dirname` 组合路径。

## 3. 该区 Top 3 问题

1. **快照前事件丢弃（16 区 S2）无回归测试**——已知缺陷在测试套件中完全不可见，是"有缺陷无保护"的最典型形态；测试基础设施支持该场景（延迟 resume 即可），缺的只是用例。
2. **MessageView 自动展开/折叠零测试 + 模块级定时器状态无卸载清理**——流式 UI 最活跃交互无契约，且模块级可变状态是测试隔离与生产内存的双重隐患（与 16 区 typingMessageIds 只增不删同类）。
3. **源码嗅探测试群（含 SettingsShell 渲染问题被固化为源码断言）**——9 个文件的 CSS/源文本正则断言脆弱易假红，且以"测试环境无法渲染"为由规避真实 bug，侵蚀测试可信度。

## 4. 亮点

- **隔离契约测试设计精良**：`chat-thread-messageview-isolation.test.ts` 用 `vi.mock` 替换 MessageView 并计数渲染次数，直接断言"新消息到达时历史消息零重渲"，精确对应 16 区 perf 文档的每消息 v-memo 契约；`markdown-streaming-incremental.test.ts` 用 DOM 节点身份（`after[i] === before[i]`）验证闭段节点复用，锚定 O(tail)/帧的渲染保证。
- **store 测试确定性极高**：注入 `scheduleFrame` 手动控制帧回调，无真实 rAF；`seq=0` 瞬态锚定、usage 聚合跳过 replace 项、turn/runItem 交错、`last_seen_seq` 续传等协议细节均有精确断言。
- **回归测试文档化**：多处注释写明 "Regression:" 与根因（handleScroll 双向、sub-agent 投影缓存冻结、cache 0% 假数据、compaction 摘要截断、DeepSeek prompt_cache_hit_tokens 归一化），后续维护者可读性极佳。
- **决策契约有覆盖**：approve_once/approve_for_session/deny/other_guidance 归一化（workbench-actions、approval-controller 嵌套审批、store 的 approval/respond 调用）三处交叉验证。
- **纪律干净**：零快照测试、零 .only/.skip、零 @ts-ignore；auto-follow-scroll-directive 对 ResizeObserver 的 fake/restore 完备（含 afterEach 清理）；setup.ts 的 matchMedia mock 有据可查。
- **CI 全链**：ci.yml 中 typecheck → test:contract → build 顺序执行，前端后端双 job。

## 5. 审计范围与方法

- 范围：`core/ui/tests/` 49 个测试文件 + setup.ts 全文通读/抽样精读（chat-thread-process 2021 行全文；store/selectors/projection/controllers/composables 全文；其余按文件头注释 + 用例清单 + 关键段抽查）；`vite.config.ts` test 段、`package.json` scripts/devDependencies、两个 tsconfig、`ci.yml` 逐一核对；与 `src/components/MessageView.vue`、`ChatThread.vue`、`appServer/*`、`composables/*` 逐点对照。
- 方法：只读；覆盖缺口用"src 分支枚举 vs 测试 grep"双向比对（partType 枚举、setTimeout 枚举、导出函数枚举）；已知缺陷回归保护用 16 区报告逐条反查；隔离/速度维度统计 fake timers、flushPromises、共享模块级状态、mock 还原点。
- 验证：按纪律运行 `npx vitest run` 单文件 5 个（composer-syntax、core-runtime-checklist、update-state、chat-thread-messageview-isolation、core-approval-controller，共 26 用例）全部通过，确认 harness 与报告引用的行号/行为无出入。
- 限制：未运行全量套件（纪律禁止）；未验证 ubuntu CI 上的实际执行（Windows 本地抽样通过，源码嗅探测试均为平台无关正则/路径拼接）。
