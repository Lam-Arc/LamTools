# Writer 前端大文件梳理

## WorkbenchView.vue（3461 行）

职责：
1. 主工作台布局编排：左/中/右三面板，响应式 CSS custom properties
2. Session 和 Project CRUD：创建、选择、删除、切换
3. SSE 流式聊天编排：发送消息、SSE streaming、本地/持久化消息对齐
4. Runtime Block 渲染和分组：computed runtimeBlocks、displayTranscriptItems、activityGroupViews
5. Decision/lifecycle/attachment/diff 渲染

最适合下一轮拆：
- **P0** 主题/渐变/颜色工具函数（7 个纯函数，零 store 依赖，已与 SettingsView 重复）→ `core/shared/utils/theme.ts`
- **P0** defaultTheme + presets 数据 → `core/shared/data/theme-presets.ts`
- **P1** 文本/i18n/格式化工具函数（businessText 等，纯函数）→ `core/shared/utils/format.ts`
- **P2** Diff 解析器（parseUnifiedDiff，纯 parser）→ `core/shared/utils/diff.ts`

## SettingsView.vue（1875 行）

职责：
1. Provider CRUD（name、api_type、base_url、api_key）
2. Model CRUD（model_id、context_window、max_output_tokens、thinking）
3. Routing rules（task_type → provider+model）
4. Writer behavior defaults（quality mode）
5. UI 主题编辑器（渐变角度、透明度、文字颜色、11 个预设）

最适合下一轮拆：
- **P0** 主题工具函数（与 WorkbenchView 完全重复）→ `core/shared/utils/theme.ts`
- **P0** themePresets 数据 → `core/shared/data/theme-presets.ts`
- **P1** Settings 持久化逻辑 → composable

## sse.ts（870 行）

职责：
1. SSE stream 生命周期（startStream、AbortController、cancel）
2. 背景 session event watching
3. SSE event 路由（15+ 事件类型 → store mutations）
4. Activity feed 管理（9 类别、去重、上限 500）
5. Assistant draft 积累
6. Lifecycle alert 记录

最适合下一轮拆：
- **P1** Status text 映射函数（phaseStatusText 等 7 个纯函数）→ `core/shared/utils/sse-labels.ts`
- **P1** Activity 分类函数（stepActivityGroup 等 8 个纯函数）→ `core/shared/utils/activity.ts`
- **P1** Reply text normalization（normalizeReplyText、extractReplyAttachments）→ `core/shared/utils/reply.ts`

## components.css（4463 行）

职责：
- 100% UI/presentation code，无逻辑、无状态
- 包含：app-shell 布局、sidebar、project/session 列表、message/composer、settings 页面、主题编辑器、agent/tool 配置、reply attachments、modal、activity/metric/git、diff viewer、floating composer、density variants、git timeline、响应式断点

最适合下一轮拆：
- **P1** Settings CSS（440-1310 行）→ `core/shared/styles/settings.css`
- **P1** Modal CSS → `core/shared/styles/modal.css`
- **P2** Diff viewer CSS → `core/shared/styles/diff.css`
- **P2** Git timeline CSS → `core/shared/styles/git.css`

## 跨文件重复

| 重复概念 | 文件 | 风险 |
|-----------|------|------|
| normalizeColor、gradientFromStops 等 7 函数 | WorkbenchView + SettingsView | 主题 bug |
| defaultTheme 对象 | WorkbenchView + SettingsView | 预设不一致 |
| businessText / businessStatusText | WorkbenchView + sse.ts | 状态标签不一致 |