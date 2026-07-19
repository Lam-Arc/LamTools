# Core UI 抽调审计

> 目标：回答"所有未抽调项为什么不抽调，最后效果是 core 骨架上只需要稍作填充立马就能做好一个新的成员。"

> **状态注记（2026-06-04）**：5A/5B/5C 已全部完成。下文"当前缺失"和"★ = 5A 阶段新增，当前不存在"属于审计时快照，不再代表当前代码。已完成清单见本文末尾。

## 1. 现状结论

Writer 和 Artist 的 `/core` 路由已经使用 Core UI 组件（WorkspaceShell、SessionSidebar、ChatThread、ComposerBar、RuntimePanel、SettingsShell）。两个产品的 CoreWorkbenchView 结构高度相似——都是对 WorkspaceShell 做插槽填充，区别仅在产品特有的侧边栏内容、附件类型、和后处理面板。

**接近程度**：骨架布局已抽调，但 slot 契约仍然很薄。当前各组件的实际能力：

| 组件 | 当前 props/slot | 缺失的目标能力 |
|------|-----------------|---------------|
| WorkspaceShell | 3 个匿名 slot：`sidebar`、`chat`、`panel` | 缺少具名细分 slot（`sidebar-header`、`drawer-right`、`composer-extra`） |
| SessionSidebar | `sessions` + `activeId` props | 无分组支持（`groups` prop）、无 `group-icon` slot |
| ChatThread | `messages` prop + `message-renderer` slot | 无 `message-product`/`content-product` 细分 slot |
| ComposerBar | `modelValue` + `placeholder` + `disabled` + `extension` slot | 无具名工具 slot（`toolbar-model`/`toolbar-quality`/`toolbar-custom`） |
| RuntimePanel | `events` prop + `action`/`artifact` slot | 无 `step-groups` prop、无 `step-detail` slot |
| SettingsShell | 硬编码 General/Members 段 + `general`/`members` slot | 无 `sections: SettingsSectionDef[]` prop、无动态段注册 |

**结论**：骨架已到位，但 slot 契约不足以让新产品"只填 slot 就能用"。新产品仍需翻看两个产品的 CoreWorkbenchView 实现才能知道该填什么。

---

## 2. 分类表

| 类别 | 项目 |
|------|------|
| **现在必须抽调** | WorkspaceShell slot 契约升级（明确命名 slot）、ComposerBar 工具插槽标准化、RuntimePanel 通用步骤组、Core API client 类型映射层 |
| **验证后再抽调** | 左侧抽屉产品分组适配器、右侧面板 slot 组合机制、设置页产品段注册 |
| **产品自有保留** | Artist 图片编辑面板、Writer git/diff/review 面板、附件/引用图上传行为 |
| **不抽调** | 产品路由守卫、产品品牌样式、产品特有快捷键 |

---

## 3. 未抽调项逐条分析

### 3.1 左侧抽屉 / 会话 / 项目分组

**现状**：SessionSidebar 当前仅接受 `sessions` + `activeId`，不支持分组。Writer 的 CoreWorkbenchView 自行将分组逻辑写在 slot 内容里，Artist 同理。

**未抽调原因**：分组逻辑依赖产品领域模型——Writer 的"项目"是文档集，Artist 的"项目"是图片集。分组键名和排序策略不同。若硬抽一个 `GroupAdapter`，每个产品仍需实现全部方法，等于零收益。

**结论**：当前 slot 透传 `sessions` 数据已足够。下一步 5A 阶段为 SessionSidebar 增加 `groups` prop 和 `group-icon` slot。验证第三产品后再考虑 `ProductSidebarAdapter` 接口。

### 3.2 中央对话 / 聊天渲染

**现状**：ChatThread 已抽调，接收 `messages` 数组，通过 `message-renderer` slot 支持自定义渲染。当前 slot 粒度是"整条消息"。

**未抽调原因**：Writer 消息可能内嵌 diff 高亮，Artist 消息可能内嵌图片对比。这些产品特有的消息内容类型当前靠单一 `message-renderer` slot 解决，粒度不够细。

**结论**：暂不抽调消息内部渲染器。新产品若只有纯文本消息，直接用默认渲染即可。5A 阶段增加 `message-product`/`content-product` slot 后，产品可以按类型注入渲染逻辑。等两个产品都有富内容消息后再统一 `MessageContentRenderer` 接口。

### 3.3 运行时 / 过程 / 活动流

**现状**：RuntimePanel 当前接受 `events` prop，提供 `action` 和 `artifact` 两个 slot。步骤展示依赖产品自行从事件流中组织。

**未抽调原因**：当前没有 `step-groups` 概念，产品需要自行将事件流转换为步骤视图。Writer 在 slot 中手动渲染"读取→分析→写作→校对"步骤，Artist 渲染"分析→生成→后处理"步骤。步骤间的依赖关系展示（如 Artist 的"生成"步骤带图片预览）也是产品特有的。

**结论**：5A 阶段为 RuntimePanel 增加 `step-groups` prop 和 `step-detail` slot，使步骤结构声明式化。产品特有的步骤详情仍通过 slot 渲染。

### 3.4 底部编辑器工具 / 模型 / 质量控制

**现状**：ComposerBar 当前提供 `extension` slot，无细分。Writer 和 Artist 都将全部工具项塞进同一个 slot。

**未抽调原因**：两个产品的工具项数量和类型完全不同。模型选择看似通用，但 Writer 的模型列表带写作能力标签，Artist 的模型列表带图片能力标签。抽象一个 `ModelSelector` 需要先统一后端的模型能力描述。

**结论**：5A 阶段将 `extension` slot 升级为具名 slot（`toolbar-model`、`toolbar-quality`、`toolbar-custom`），使新产品有明确填充指引。

### 3.5 右侧抽屉 / 状态面板

**现状**：WorkspaceShell 当前有匿名 `panel` slot，Writer 放文档状态 + 字数统计，Artist 放图片元数据 + 分辨率。

**未抽调原因**：面板内容完全不同，无共同结构。强行抽象只会增加理解成本。

**结论**：5A 阶段将 `panel` slot 升级为具名 `drawer-right` slot。新产品自行填充右侧面板。

### 3.6 设置壳 / 供应商 / 计费 / 设置页

**现状**：SettingsShell 当前硬编码 General/Members 两个段，提供 `general` 和 `members` 两个 slot。无 `sections` prop，产品无法动态注册设置段。

**未抽调原因**：产品设置段（Writer 的写作偏好、Artist 的输出格式）差异大，但设置页框架（导航 + 内容区）完全相同。当前硬编码段名导致新产品无法添加自有段。

**结论**：5A 阶段为 SettingsShell 增加 `sections: SettingsSectionDef[]` prop 和动态 `section-slots`，使新产品只需声明段定义即可。

### 3.7 世系 / 图片特有面板

**现状**：Artist 独有，无对应 Writer 实现。

**未抽调原因**：只有一个产品使用，无法判断通用模式。

**结论**：保留 Artist 自有。等第三个产品（如果也是视觉类）出现后再考虑。

### 3.8 Git / Diff / Review 面板

**现状**：Writer 独有，无对应 Artist 实现。

**未抽调原因**：只有一个产品使用。且 git diff 渲染逻辑与文本编辑器深度耦合。

**结论**：保留 Writer 自有。

### 3.9 上传 / 附件 / 引用图

**现状**：ComposerBar 的附件按钮通过 slot 实现。Writer 支持文档上传，Artist 支持图片上传。

**未抽调原因**：上传行为差异大——Writer 上传后作为引用，Artist 上传后作为生成输入。验证逻辑、预览方式、API 端点均不同。

**结论**：保持 slot 透传。若未来出现"引用式上传"的第三产品，再抽调 `AttachmentUploader` 接口。

---

## 4. 目标 Core UI 架构

目标是让新产品只需要：

1. 实现 `ProductAdapter` 接口
2. 填充具名 slot
3. 声明设置段

即可获得完整工作台 UI。

```
当前 WorkspaceShell slot 布局（匿名，契约薄）:
┌─────────────────────────────────────────────────┐
│  WorkspaceShell                                  │
│  ┌──────┬────────────────────┬──────────┐       │
│  │sidebar│       chat        │  panel   │       │
│  │(anon) │     (anon)        │ (anon)   │       │
│  └──────┴────────────────────┴──────────┘       │
└─────────────────────────────────────────────────┘

目标 WorkspaceShell slot 布局（具名，指引明确）:
┌─────────────────────────────────────────────────┐
│  WorkspaceShell                                  │
│  ┌──────┬────────────────────┬──────────┐       │
│  │ Left │     Center         │  Right   │       │
│  │      │                    │          │       │
│  │ Sess │  ChatThread        │ Product  │       │
│  │ ionS │   ├─ message-      │ Status   │       │
│  │ ideb │   │  renderer      │ Panel    │       │
│  │ ar   │   ├─ message-      │          │       │
│  │      │   │  product ★     │ (slot:   │       │
│  │(adap │   └─ content-     │  drawer- │       │
│  │ ter) │     product ★     │  right)  │       │
│  │      │                    │          │       │
│  ├──────┼────────────────────┼──────────┤       │
│  │      │  ComposerBar       │          │       │
│  │      │  ├─ toolbar-model │          │       │
│  │      │  ├─ toolbar-      │          │       │
│  │      │  │  quality ★     │          │       │
│  │      │  └─ toolbar-      │          │       │
│  │      │     custom ★      │          │       │
│  └──────┴────────────────────┴──────────┘       │
│                                                  │
│  RuntimePanel (step-groups ★ + step-detail ★)   │
│  SettingsShell (sections ★ + section-slots ★)   │
└─────────────────────────────────────────────────┘

★ = 5A 阶段新增，当前不存在
```

### 核心抽象

| 抽象 | 当前实现 | 目标契约 |
|------|----------|----------|
| **ProductAdapter** | 不存在 | `id`, `displayName`, `sessionGroups`, `supportedFeatures` — 产品身份与能力声明 |
| **WorkspaceShell** | 3 个匿名 slot：`sidebar`、`chat`、`panel` | 具名 slot：`sidebar-header`、`drawer-right`、`composer-extra` |
| **SessionSidebar** | `sessions` + `activeId` props | 增加 `groups` prop + `group-icon` slot |
| **ChatThread** | `messages` prop + `message-renderer` slot | 增加 `message-product`/`content-product` 细分 slot |
| **ComposerBar** | `modelValue` + `extension` slot | 具名 slot：`toolbar-model`、`toolbar-quality`、`toolbar-custom`（替代 `extension`） |
| **RuntimePanel** | `events` prop + `action`/`artifact` slot | 增加 `step-groups` prop + `step-detail` slot |
| **SettingsShell** | 硬编码 General/Members 段 + `general`/`members` slot | `sections: SettingsSectionDef[]` prop + 动态 `section-slots` |
| **CoreApiMapper** | 不存在 | 将 Core API 类型映射为组件 props 类型，产品可扩展 |

### 新产品接入流程

```
1. 实现 ProductAdapter（声明产品 ID、会话分组、支持特性）
2. 填充 WorkspaceShell 具名 slot（侧边栏头、右侧面板、编辑器工具）
3. 声明 SettingsShell sections（产品设置段定义）
4. 可选：扩展 CoreApiMapper（产品特有 API 类型）
→ 完成接入
```

---

## 5. 下一实施阶段

### 阶段 5A：Core UI slot 契约升级

| 任务 | 文件 | 内容 |
|------|------|------|
| 5A-1 | `ui/src/types.ts` | 新增 `ProductAdapter`、`SettingsSectionDef`、`StepGroup` 类型定义 |
| 5A-2 | `ui/src/components/WorkspaceShell.vue` | 将匿名 slot `sidebar`/`chat`/`panel` 升级为具名：`sidebar-header`、`drawer-right`、`composer-extra` |
| 5A-3 | `ui/src/components/ComposerBar.vue` | 将 `extension` slot 拆分为具名：`toolbar-model`、`toolbar-quality`、`toolbar-custom` |
| 5A-4 | `ui/src/components/ChatThread.vue` | 在 `message-renderer` 基础上新增 `message-product`、`content-product` slot |
| 5A-5 | `ui/src/components/SessionSidebar.vue` | 新增 `groups` prop + `group-icon` slot |
| 5A-6 | `ui/src/components/RuntimePanel.vue` | 新增 `step-groups` prop + `step-detail` slot（保留 `events`/`action`/`artifact` 向后兼容） |
| 5A-7 | `ui/src/components/SettingsShell.vue` | 将硬编码段改为 `sections: SettingsSectionDef[]` prop + 动态 `section-slots` |
| 5A-8 | `ui/src/index.ts` | 导出新增类型 |

### 阶段 5B：Writer /core 使用升级 slot

| 任务 | 文件 | 内容 |
|------|------|------|
| 5B-1 | Writer `CoreWorkbenchView.vue` | 迁移至具名 slot，删除旧 slot 用法 |
| 5B-2 | Writer `core.ts` | 确保类型与 CoreApiMapper 对齐 |

### 阶段 5C：Artist /core 使用升级 slot

| 任务 | 文件 | 内容 |
|------|------|------|
| 5C-1 | Artist `CoreWorkbenchView.vue` | 迁移至具名 slot，删除旧 slot 用法 |
| 5C-2 | Artist `core.ts` | 确保类型与 CoreApiMapper 对齐 |

### 阶段 5D：替换主 WorkbenchView（后续阶段，不在本次范围）

仅在 5A-5C 全部通过后，逐步将主 WorkbenchView 迁移到 Core UI 组件。

---

## 6. 验收标准

| 标准 | 验证方式 |
|------|----------|
| Core UI 构建通过 | `npm run build` in `E:\LamTools\core\ui` |
| Writer 前端构建通过 | `npm run build` in `E:\LamTools\members\writer\frontend` |
| Artist 前端构建通过 | `npm run build` in `E:\LamTools\members\Artist\frontend` |
| /core 路由调用真实 API | 手动检查 CoreWorkbenchView 中无 mock 数据 |
| 主 WorkbenchView 不变 | git diff 确认 Writer/Artist 主工作台无变更 |

---

## 7. 风险与护栏

| 风险 | 护栏 |
|------|------|
| 过早抽象产品语义 | 只在两个产品都有对应实现后才抽调；单一产品独有的永远留产品侧 |
| 削弱 TS 类型检查 | 所有新增接口必须有完整类型定义，禁止 `any`；slot prop 必须有类型声明 |
| 主工作台视觉回归 | 5A-5C 阶段只改 /core 路由，不动主 WorkbenchView；每次变更后构建验证 |
| 使用假数据演示 | /core 路由必须调用 `/api/core` 真实接口，禁止 mock 数据 |

---

## 8. 已完成清单

> 以下阶段已全部完成，原审计中的"当前缺失"描述已过时。

### 5A：Core UI slot 契约升级 [done]

| 任务 | 状态 |
|------|------|
| 5A-1 `ui/src/types.ts` 新增 ProductAdapter、SettingsSectionDef、CoreRuntimeStepGroup 等类型 | [done] |
| 5A-2 WorkspaceShell 具名 slot（sidebar-header、drawer-right、composer-extra） | [done] |
| 5A-3 ComposerBar 具名 slot（toolbar-model、toolbar-quality、toolbar-custom） | [done] |
| 5A-4 ChatThread 新增 message-product、content-product slot | [done] |
| 5A-5 SessionSidebar 新增 groups prop + group-icon slot | [done] |
| 5A-6 RuntimePanel 新增 step-groups prop + step-detail slot | [done] |
| 5A-7 SettingsShell 新增 sections prop + section slot | [done] |
| 5A-8 `ui/src/index.ts` 导出新增类型 | [done] |

### 5B：Writer /core 使用升级 slot [done]

| 任务 | 状态 |
|------|------|
| 5B-1 Writer CoreWorkbenchView 迁移至具名 slot | [done] |
| 5B-2 Writer core.ts 类型与 CoreApiMapper 对齐 | [done] |

### 5C：Artist /core 使用升级 slot [done]

| 任务 | 状态 |
|------|------|
| 5C-1 Artist CoreWorkbenchView 迁移至具名 slot | [done] |
| 5C-2 Artist core.ts 类型与 CoreApiMapper 对齐 | [done] |

**验证结论**：Writer 和 Artist 均已用 `/core` 真实 API 验证同一骨架，差异仅在 slot 填充和 API 映射。新成员接入指南见 `docs/new-member-core-onboarding.md`。
