# 6B Core Member Reuse Audit

> 审计日期: 2026-06-04
> 审计范围: Writer/Artist 的 CoreWorkbenchView.vue + api/core.ts，对照 Core UI types.ts + components
> 目标: 判断 5B/5C 后还有哪些重复代码应抽到 Core，哪些不抽，服务于"新成员只稍作填充即可接入"

---

## 1. 结论摘要

**已双边验证、可进入下一阶段抽调的重复项**:

1. **Core API mapper helpers** -- Writer 和 Artist 各自实现了 snake_case -> camelCase 的 mapSession/mapMessage/mapEvent，逻辑结构完全相同，仅 groupId 硬编码不同。可抽为 Core 提供的泛型 mapper factory。
2. **Loading step-group factory** -- 两边 stepGroups computed 完全一致（loading -> running -> fetch-session-data），可抽为 `createLoadingStepGroup()` helper。
3. **基础 workbench shell CSS** -- sidebar-header/title/subtitle、new-session-btn、empty-state、toolbar-status 六个 CSS 类完全相同，可抽为 Core 提供的 CSS class 包。
4. **Workbench controller 逻辑骨架** -- selectSession/newSession/sendMessage/onMounted 四个函数的结构、错误处理、状态管理模式完全相同，可抽为可选的 `useCoreWorkbenchController` composable。

**留产品侧、暂不抽调的项**:

1. **ProductAdapter 定义** -- id/displayName/supportedFeatures 是产品身份，必须留产品侧。
2. **sessionGroups 定义** -- groupId 和 label 是产品语义，留产品侧。
3. **drawer-right 业务信息** -- Artist 有 drawer-info（status/messages），Writer 没有。仅单边使用，不抽。
4. **ComposerBar toolbar-custom usage 信息** -- 仅 Artist 有 usageTotal/usageCurrency/usageLabel，Writer 没有。仅单边使用，不抽。
5. **Core API 请求层** -- Writer 用 fetch + API_BASE，Artist 用 axios client。HTTP 客户端不同，不抽请求层，只抽 mapper。

---

## 2. 逐项对比表

### 2.1 ProductAdapter 定义

| 字段 | Writer | Artist | 是否相同 | 抽调建议 |
|------|--------|--------|----------|----------|
| id | `'writer'` | `'Artist'` | 不同 | 不抽 -- 产品身份 |
| displayName | `'LamWriter'` | `'lamartist'` | 不同 | 不抽 -- 产品身份 |
| version | `'0.1.0'` | `'0.1.0'` | 相同 | 不抽 -- 产品声明 |
| supportedFeatures | `['chat', 'runtime-events']` | `['chat', 'runtime-events', 'image-generation']` | Artist 多一项 | 不抽 -- 产品能力 |

**结论**: ProductAdapter 是产品身份声明，必须留产品侧。Core 只提供类型定义（已做）。

### 2.2 sessionGroups 定义

| 字段 | Writer | Artist | 是否相同 | 抽调建议 |
|------|--------|--------|----------|----------|
| id | `'writer-sessions'` | `'Artist-sessions'` | 不同 | 不抽 -- 产品语义 |
| label | `'Writer sessions'` | `'Artist sessions'` | 不同 | 不抽 -- 产品语义 |
| description | `'All Writer sessions'` | `'All Artist sessions'` | 不同 | 不抽 -- 产品语义 |

**结论**: sessionGroups 是产品分组语义，留产品侧。Core 只提供 CoreSessionGroup 类型（已做）。

### 2.3 Transient Loading StepGroups

| 字段 | Writer | Artist | 是否相同 |
|------|--------|--------|----------|
| 外层 id | `'loading'` | `'loading'` | 相同 |
| 外层 label | `'Loading'` | `'Loading'` | 相同 |
| 外层 status | `'running'` | `'running'` | 相同 |
| step id | `'fetch-session-data'` | `'fetch-session-data'` | 相同 |
| step title | `'Fetching session data'` | `'Fetching session data'` | 相同 |
| step status | `'running'` | `'running'` | 相同 |
| 条件 | `!loading.value` | `!loading.value` | 相同 |

**结论**: 完全相同。可抽为 `createLoadingStepGroup()` helper，返回 `CoreRuntimeStepGroup[]`。

### 2.4 Workbench Controller 逻辑

#### selectSession

| 步骤 | Writer | Artist | 是否相同 |
|------|--------|--------|----------|
| 设置 activeSessionId | `activeSessionId.value = id` | `activeSessionId.value = id` | 相同 |
| 设置 loading | `loading.value = true` | `loading.value = true` | 相同 |
| 并行获取 | `Promise.all([getCoreMessages, getCoreEvents])` | `Promise.all([getCoreMessages, getCoreEvents])` | 相同 |
| 赋值 messages/events | `messages.value = msgs; events.value = evts` | `messages.value = msgs; events.value = evts` | 相同 |
| catch 清空 | `messages.value = []; events.value = []` | `messages.value = []; events.value = []` | 相同 |
| finally | `loading.value = false` | `loading.value = false` | 相同 |

#### newSession

| 步骤 | Writer | Artist | 是否相同 |
|------|--------|--------|----------|
| createCoreSession | `await createCoreSession()` | `await createCoreSession()` | 相同 |
| unshift | `sessions.value.unshift(session)` | `sessions.value.unshift(session)` | 相同 |
| selectSession | `await selectSession(session.id)` | `await selectSession(session.id)` | 相同 |

#### sendMessage

| 步骤 | Writer | Artist | 是否相同 |
|------|--------|--------|----------|
| trim + guard | `!text \|\| !activeSessionId.value` | `!text \|\| !activeSessionId.value` | 相同 |
| 清空输入 | `composerText.value = ''` | `composerText.value = ''` | 相同 |
| createCoreMessage | `createCoreMessage(id, text, 'user')` | `createCoreMessage(id, text)` (默认 'user') | 等价 |
| 刷新消息 | `messages.value = await getCoreMessages(id)` | `messages.value = await getCoreMessages(id)` | 相同 |

#### onMounted

| 步骤 | Writer | Artist | 是否相同 |
|------|--------|--------|----------|
| 并行获取 | `Promise.all([listCoreSessions, listCoreProviders])` | `Promise.all([listCoreSessions, listCoreProviders, getCoreUsageTotal])` | Artist 多 usage |
| 赋值 sessions | `sessions.value = sessResult` | `sessions.value = sessResult` | 相同 |
| providerCount | `providers.length` | `provRes.data.length` | 差异（见 2.5） |
| usageTotal | 无 | `usageRes.data.total_cost` | Artist 独有 |
| auto-select first | `if (sessions.value.length > 0) await selectSession(...)` | 同 | 相同 |

**结论**: selectSession/newSession/sendMessage 三函数结构完全相同。onMounted 有 Artist 独有的 usage 获取。可抽为 composable，onMounted 的额外获取通过回调或扩展点注入。

### 2.5 Core API Mapping

#### Session Mapper

| 字段映射 | Writer | Artist | 是否相同 |
|----------|--------|--------|----------|
| id | `raw.id` | `s.id` | 相同 |
| title | `raw.title` | `s.title` | 相同 |
| createdAt | `raw.created_at` | `s.created_at ?? ''` | Artist 有 null fallback |
| updatedAt | `raw.updated_at` | `s.updated_at ?? undefined` | Artist 有 null fallback |
| status | `raw.status` | `s.status` | 相同 |
| groupId | `'writer-sessions'` (硬编码) | `'Artist-sessions'` (硬编码) | 不同 -- 产品语义 |

**差异**: Artist 的后端返回 `created_at`/`updated_at` 可为 null，Writer 不可。groupId 是产品硬编码。

#### Message Mapper

| 字段映射 | Writer | Artist | 是否相同 |
|----------|--------|--------|----------|
| id | `raw.id` | `m.id` | 相同 |
| role | `raw.role as ...` | `m.role as ...` | 相同 |
| content | `raw.content` | `m.content` | 相同 |
| timestamp | `raw.created_at` | `m.created_at ?? ''` | Artist 有 null fallback |
| metadata | `raw.metadata` | `m.metadata ?? undefined` | Artist 有 null fallback |

**差异**: Artist 后端字段可为 null，需要 fallback。映射逻辑结构相同。

#### Event Mapper

| 字段映射 | Writer | Artist | 是否相同 |
|----------|--------|--------|----------|
| id | `raw.id` | `e.id ?? 'evt-${i}'` | Artist 有 fallback |
| type | `` `${raw.category}/${raw.name}` `` | `e.type ?? 'info'` | 完全不同 |
| timestamp | `raw.created_at` | `e.created_at ?? new Date().toISOString()` | Artist 有 fallback |
| data | `raw.payload` | `raw` (整个对象) | 不同 |

**差异**: Writer 后端 event 有 category+name 结构，Artist 后端 event 有 type 字段。这是后端 schema 差异，不是前端可统一的。

#### Provider

| 字段 | Writer | Artist | 是否相同 |
|------|--------|--------|----------|
| 返回类型 | `CoreProviderRaw[]` (直接返回) | `AxiosResponse<CoreProvider[]>` (包装在 res) | 不同 |
| 字段 | id/kind/name/base_url/api_key_ref/default_model/models/metadata/enabled | id/kind/name/base_url/default_model/enabled/billing_type/unit_price/currency/vendor/api_key_ref | Artist 多 billing 字段 |

**差异**: HTTP 客户端不同（fetch vs axios），返回结构不同（裸数据 vs axios response），Artist 有 billing 扩展字段。

#### Usage

| 端点 | Writer | Artist |
|------|--------|--------|
| getCoreUsageTotal | 无 | 有，返回 `{ total_cost, currency }` |

**差异**: 仅 Artist 有 usage 端点。

**结论**: Session/Message mapper 结构相同，可抽为泛型 factory，接受 groupId 参数和可选的 null-fallback 策略。Event mapper 因后端 schema 差异大，不适合统一。Provider/Usage 是产品差异，不抽。

### 2.6 基础 CSS 类

| CSS 类 | Writer | Artist | 是否相同 | 抽调建议 |
|--------|--------|--------|----------|----------|
| `.core-sidebar-header` | flex/align-center/gap-8px/padding-10px-12px | 完全相同 | 相同 | 现在应抽 |
| `.core-sidebar-title` | font-weight-600/font-size-md | 完全相同 | 相同 | 现在应抽 |
| `.core-sidebar-subtitle` | font-size-0.75rem/color-text-secondary | 完全相同 | 相同 | 现在应抽 |
| `.core-new-session-btn` | block/width-calc/margin-8px/padding-6px-12px/border/border-radius/background/color/font-size/cursor/text-align | 完全相同 | 相同 | 现在应抽 |
| `.core-new-session-btn:hover` | background-bg-tertiary | 完全相同 | 相同 | 现在应抽 |
| `.core-empty-state` | flex/align-center/justify-center/flex-1/color-text-secondary/font-size-md | 完全相同 | 相同 | 现在应抽 |
| `.core-toolbar-status` | font-size-0.7rem/color-text-secondary/white-space-nowrap | 完全相同 | 相同 | 现在应抽 |

**结论**: 7 个 CSS 类完全相同。可抽为 Core 提供的 `workbench-shell.css` 或 CSS module。

### 2.7 Drawer-right 业务信息

| 内容 | Writer | Artist | 是否相同 | 抽调建议 |
|------|--------|--------|----------|----------|
| RuntimePanel | 有 | 有 | 相同 | 已在 Core |
| drawer-info (status/messages) | 无 | 有 | Artist 独有 | 不抽 -- 仅单边 |
| `.core-drawer-info` CSS | 无 | 有 | Artist 独有 | 不抽 |

**结论**: drawer-info 仅 Artist 使用，不抽。如果未来第三个产品也需要 key-value 信息展示，再考虑抽为 `DrawerInfoList` 组件。

### 2.8 ComposerBar toolbar-custom 信息

| 内容 | Writer | Artist | 是否相同 | 抽调建议 |
|------|--------|--------|----------|----------|
| provider count 显示 | 有 | 有 | 相同 | 验证后再抽 -- 可做 `ProviderCountBadge` |
| usage total 显示 | 无 | 有 | Artist 独有 | 不抽 -- 仅单边 |
| usage currency | 无 | 有 | Artist 独有 | 不抽 |

**结论**: provider count 两边都有，但实现极简（一个 span），抽组件收益低。usage 仅 Artist。暂不抽，等第三边验证。

---

## 3. 抽调建议分级

### 3.1 现在应抽

| 项 | 抽调形式 | 理由 | 风险 |
|----|----------|------|------|
| Core API mapper helpers | `ui/src/helpers/createSessionMapper(groupId, options?)` / `createMessageMapper(options?)` | 两边 mapSession/mapMessage 结构相同，仅 groupId 和 null-fallback 不同。泛型 factory 可消除重复。 | 低 -- 纯函数，无副作用 |
| Loading step-group factory | `ui/src/helpers/createLoadingStepGroup()` | 两边 stepGroups computed 完全一致 | 极低 -- 纯函数，返回常量结构 |
| 基础 workbench shell CSS | `ui/src/styles/workbench-shell.css` | 7 个 CSS 类完全相同，新成员必然需要 | 低 -- CSS 不影响逻辑 |
| 可选的 useCoreWorkbenchController composable | `ui/src/composables/useCoreWorkbenchController.ts` | selectSession/newSession/sendMessage/onMounted 骨架完全相同，新成员复制粘贴成本高 | 中 -- 需要设计好扩展点，避免把产品状态锁进 Core |

**关于 useCoreWorkbenchController 的设计要点**:
- 接受 `api` 参数对象（产品注入自己的 API 函数），不硬编码 HTTP 客户端
- 接受 `onMountedExtra?` 回调（Artist 注入 usage 获取，Writer 不传）
- 返回 `{ sessions, activeSessionId, messages, events, composerText, loading, providerCount, stepGroups, selectSession, newSession, sendMessage }`
- 不包含 usageTotal/usageCurrency/activeSession 等产品特有状态

### 3.2 验证后再抽

| 项 | 抽调形式 | 理由 | 暂不抽原因 |
|----|----------|------|------------|
| Provider/usage toolbar summary | `ProviderCountBadge` / `UsageSummaryBadge` 组件 | Writer 和 Artist 都显示 provider count，但实现极简 | 仅两行模板代码，抽组件收益低。等第三边验证后再决定 |
| Drawer info key-value list | `DrawerInfoList` 组件 | Artist 有 status/messages 展示，未来产品可能也需要 | 仅 Artist 单边使用，过早抽会假设所有产品都需要此展示形式 |

### 3.3 不抽

| 项 | 原因 |
|----|------|
| ProductAdapter 定义 | 产品身份声明，id/displayName/features 必须由产品定义 |
| sessionGroups 定义 | 产品分组语义，groupId/label/description 是产品领域概念 |
| Event mapper | Writer 后端 event 有 category+name，Artist 有 type，schema 差异大，强行统一会掩盖后端不一致 |
| Provider 返回结构 | Writer 用 fetch 返回裸数组，Artist 用 axios 返回 AxiosResponse，HTTP 客户端不同 |
| Usage 端点 | 仅 Artist 有，是产品特有功能 |
| drawer-right 业务信息 | Artist 独有的 status/messages 展示，是产品业务状态 |
| ComposerBar toolbar-custom usage | Artist 独有的 usageTotal/usageCurrency/usageLabel，是产品业务数据 |
| 产品 persona | 业务身份，如 Writer 人格、Artist 人格 |
| 业务工具 | 业务能力，如生图工具、文件工具、Git 工具 |
| 图片/Git/Diff/Usage 语义 | 产品领域概念，不属于 Core |

---

## 4. 6C 最小实现边界

6C 阶段的目标：在 Core UI 增加小 helper 和可选 composable，Writer/Artist 仍能构建，不迁主 Workbench。

### 6C 包含

1. **`ui/src/helpers/createSessionMapper.ts`**
   - 导出 `createSessionMapper(groupId: string, options?: { nullFallback?: boolean })`
   - 返回 `(raw: CoreSessionRaw) => CoreSessionListItem`
   - Writer 调用: `createSessionMapper('writer-sessions')`
   - Artist 调用: `createSessionMapper('Artist-sessions', { nullFallback: true })`

2. **`ui/src/helpers/createMessageMapper.ts`**
   - 导出 `createMessageMapper(options?: { nullFallback?: boolean })`
   - 返回 `(raw: CoreMessageRaw) => CoreMessage`

3. **`ui/src/helpers/createLoadingStepGroup.ts`**
   - 导出 `createLoadingStepGroup(): CoreRuntimeStepGroup[]`
   - 返回固定的 loading step-group 结构

4. **`ui/src/styles/workbench-shell.css`**
   - 包含 7 个 `.core-*` CSS 类
   - 产品通过 `@import '@lamtools/ui/styles/workbench-shell.css'` 引入
   - 或在组件库入口自动导出

5. **`ui/src/composables/useCoreWorkbenchController.ts`** (可选)
   - 接受参数: `{ api: { listSessions, createSession, getMessages, createMessage, getEvents, listProviders }, onMountedExtra?: (ctx) => Promise<void> }`
   - 返回: sessions, activeSessionId, messages, events, composerText, loading, providerCount, stepGroups, selectSession, newSession, sendMessage
   - 产品可选择性使用，也可继续手写

### 6C 不包含

- 不迁移 Writer/Artist 的 CoreWorkbenchView.vue 到 Core
- 不创建统一的 Workbench 组件
- 不统一 Event mapper
- 不统一 HTTP 客户端
- 不抽 Provider/Usage 组件
- 不抽 DrawerInfoList 组件

### 6C 验收标准

- Core UI `npm run build` 通过
- Writer 前端 `npm run build` 通过（可选择使用新 helper 或保持原样）
- Artist 前端 `npm run build` 通过（可选择使用新 helper 或保持原样）
- 新 helper/composable 有类型导出
- 不破坏现有 CoreWorkbenchView.vue 的功能

---

## 5. 风险

### 5.1 过早抽成大 Workbench 组件

**风险**: 如果 6C 阶段把 CoreWorkbenchView 整体迁入 Core 作为"默认 Workbench"，会导致:
- 产品差异被压缩到 slot 级别，无法表达更复杂的布局变化
- 新产品如果需要不同的三栏结构（如双面板、无侧边栏），必须覆盖整个组件
- Core 组件的 props/slots 会膨胀以适配所有产品，变成"万能组件"反模式

**缓解**: 6C 只做 helper 和 composable，不做 Workbench 组件。产品仍拥有自己的 CoreWorkbenchView.vue，只是内部调用 Core 提供的 helper 减少重复。

### 5.2 把产品业务状态放进 Core

**风险**: 如果 useCoreWorkbenchController 包含 usageTotal/usageCurrency/activeSession 等产品特有状态:
- Core composable 变成产品状态的集合，新成员接入时需要理解不相关的状态
- 产品差异被隐式编码在 composable 的可选参数中，增加认知负担

**缓解**: composable 只包含双边验证通过的通用状态（sessions/messages/events/loading/providerCount）。产品特有状态由产品自己在 View 中管理。

### 5.3 Mapper factory 的 null-fallback 策略

**风险**: Writer 后端返回的 created_at/updated_at 不可为 null，Artist 可为 null。如果 factory 默认行为不正确:
- Writer 侧可能引入不必要的 null 检查
- Artist 侧可能缺少 null fallback 导致运行时错误

**缓解**: factory 的 options.nullFallback 默认为 false（匹配 Writer 的严格模式），Artist 显式传入 `{ nullFallback: true }`。类型层面，CoreSessionRaw 的字段类型保持 `string | null`，由 factory 统一处理。

### 5.4 CSS 类名冲突

**风险**: `.core-*` CSS 类名在产品 scoped style 中定义，如果 Core 也导出同名类:
- 产品可能同时有两份定义（scoped + Core 导出），导致样式优先级问题

**缓解**: Core 导出的 CSS 使用 BEM 前缀 `ltw-`（lamtools-workbench），如 `.ltw-sidebar-header`。产品迁移时替换类名，删除 scoped 中的重复定义。6C 阶段产品可选择不迁移，继续使用 scoped `.core-*`。

---

## 6. 对照源文件索引

| 文件 | 路径 | 用途 |
|------|------|------|
| Writer View | `E:\LamTools\members\writer\frontend\src\views\CoreWorkbenchView.vue` | Writer 工作台实现 |
| Writer API | `E:\LamTools\members\writer\frontend\src\api\core.ts` | Writer Core API 映射 |
| Artist View | `E:\LamTools\members\Artist\frontend\src\views\CoreWorkbenchView.vue` | Artist 工作台实现 |
| Artist API | `E:\LamTools\members\Artist\frontend\src\api\core.ts` | Artist Core API 映射 |
| Core types | `E:\LamTools\core\ui\src\types.ts` | Core UI 类型定义 |
| Core components | `E:\LamTools\core\ui\src\components\*.vue` | Core UI 组件 |
| 接入指南 | `E:\LamTools\core\docs\new-member-core-onboarding.md` | 新成员接入文档 |
