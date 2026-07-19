# 最终形态审计 -- LamTools Core 收尾

> 审计日期: 2026-06-04
> 目标: 记录 Core 收尾后的最终状态、不抽项清单和新成员最小接入步骤

---

## 1. Core 最终形态

### 1.1 后端 SDK (`lamtools_core`)

| 层 | 提供内容 |
|----|----------|
| 协议层 | LLM、Tool、Event、Prompt、MEM、Guardrail、Runtime 协议定义 |
| 内核层 | Core Loop Kernel（共享主循环骨架） |
| HTTP 层 | `/api/core` 通用路由（session、event、provider、usage） |
| 应用层 | `create_app` 工厂、`MemberManifest` 成员声明 |

### 1.2 前端 UI Core (`@lamtools/ui`)

**组件**：

| 组件 | 用途 |
|------|------|
| WorkspaceShell | 三栏骨架 |
| SessionSidebar | 会话列表（支持分组） |
| ChatThread | 消息流 |
| ComposerBar | 输入栏（具名工具插槽） |
| RuntimePanel | 运行时面板（步骤组） |
| SettingsShell | 设置面板（动态段） |

**Helpers**：

| Helper | 用途 |
|--------|------|
| `createSessionMapper(groupId)` | 创建 session snake_case -> camelCase 映射器 |
| `createMessageMapper()` | 创建 message 映射器 |
| `createLoadingStepGroup()` | 创建 loading 状态步骤组 |

**Composable**：

| Composable | 用途 |
|------------|------|
| `useCoreWorkbenchController({ api, onMountedExtra? })` | 通用工作台状态和控制逻辑 |

**CSS**：

| 类名 | 用途 |
|------|------|
| `ltw-sidebar-header` | 侧边栏头部容器 |
| `ltw-sidebar-title` | 侧边栏标题 |
| `ltw-sidebar-subtitle` | 侧边栏副标题 |
| `ltw-new-session-btn` | 新建会话按钮 |
| `ltw-empty-state` | 空状态占位 |
| `ltw-toolbar-status` | 工具栏状态文字 |

### 1.3 Writer/Artist 验证状态

Writer /core 和 Artist /core 均已使用 Core helper/controller，骨架完全相同：

- 均使用 `createSessionMapper('writer-sessions')` / `createSessionMapper('Artist-sessions')`
- 均使用 `createMessageMapper()`
- 均使用 `useCoreWorkbenchController({ api })`
- 均使用 `ltw-*` CSS 类
- 均保留 `ProductAdapter`、`sessionGroups` 在产品侧
- 均保留各自的 event mapper 在产品侧
- 均保留各自的 HTTP 客户端

---

## 2. 仍不抽调项及原因

| 项 | 不抽原因 |
|----|----------|
| Persona / System Prompt | 业务身份，产品人格不可共享 |
| 业务工具 | 业务能力（生图、文件读写、Git），仅单产品使用 |
| Event schema | Writer 用 category/name，Artist 用 type，后端 schema 不一致，强行统一会掩盖差异 |
| Provider/Usage 语义 | Artist 有 billing/unit_price/currency/vendor，Writer 没有，字段差异大 |
| Drawer info | 仅 Artist 有 status/messages 展示，单边使用 |
| 图片/Git/Diff 专有 UI | 产品领域展示，不属于 Core |
| fetch/axios HTTP 客户端 | 产品已有各自的 HTTP 层，统一增加耦合，收益低 |
| ProductAdapter 定义 | 产品身份声明，id/displayName/features 必须由产品定义 |
| sessionGroups 定义 | 产品分组语义，groupId/label/description 是产品领域概念 |

判断标准：如果只有单一产品使用，或两个产品的实现完全不同，则留产品侧。

---

## 3. 新成员最小接入步骤

### 3.1 后端

1. 声明 `MemberManifest`（id、name、version、capabilities）
2. 调用 `create_app` 注册成员，设置 `enable_core_routes=True`
3. 或手动映射 `/api/core` 路由到 Core 路由器
4. 实现 `RuntimeKit`（如使用 Core Loop Kernel）
5. 产品路由挂载到 `/api/{member_id}`

### 3.2 前端

1. 配置 `@lamtools/ui` 路径别名（tsconfig + vite.config）
2. 实现 `ProductAdapter`（id、displayName、version、supportedFeatures）
3. 定义 `sessionGroups`（使用产品 groupId，如 `'writer-sessions'`）
4. 在 `api/core.ts` 中使用 Core mapper：
   - `createSessionMapper('{member}-sessions')`
   - `createMessageMapper()`
   - 保留产品侧 event mapper
   - 保留产品侧 HTTP 客户端
5. 在 `CoreWorkbenchView.vue` 中使用 `useCoreWorkbenchController`：
   - 注入 `api` 对象（产品 API 函数）
   - 可选 `onMountedExtra` 回调（产品特有初始化）
   - `onMounted` 调用 `loadInitialData()`
6. 填充 `WorkspaceShell` slots（sidebar-header、sidebar、sidebar-footer、chat、drawer-right）
7. 使用 Core `ltw-*` CSS 类替代产品侧重复样式
8. 产品独有 CSS 保留在产品 scoped style 中
9. 产品特有状态（usage、drawer info 等）保留在产品 View 内

### 3.3 接入后产品侧只保留

- 产品身份（ProductAdapter、sessionGroups）
- API 请求层（HTTP 客户端 + 端点路径）
- Event mapper（产品 event schema 差异）
- 业务状态（usage、drawer info 等）
- 业务 UI（图片编辑器、Diff 查看器等）
- Slot 差异（toolbar-custom、step-detail 等）

---

## 4. 对照源文件索引

| 文件 | 状态 |
|------|------|
| `E:\LamTools\members\writer\frontend\src\api\core.ts` | 已使用 Core mapper |
| `E:\LamTools\members\writer\frontend\src\views\CoreWorkbenchView.vue` | 已使用 Core controller + ltw-* CSS |
| `E:\LamTools\members\Artist\frontend\src\api\core.ts` | 已使用 Core mapper，保留 event fallback 和 usage |
| `E:\LamTools\members\Artist\frontend\src\views\CoreWorkbenchView.vue` | 已使用 Core controller + ltw-* CSS，保留 usage/drawer info |
| `E:\LamTools\members\Artist\frontend\src\lamtools-ui.d.ts` | 已同步 Core helpers/composables 声明 |
| `E:\LamTools\core\ui\src\helpers\` | Core mapper + loading step group |
| `E:\LamTools\core\ui\src\composables\` | Core workbench controller |
| `E:\LamTools\core\ui\src\styles\workbench-shell.css` | Core ltw-* CSS |
