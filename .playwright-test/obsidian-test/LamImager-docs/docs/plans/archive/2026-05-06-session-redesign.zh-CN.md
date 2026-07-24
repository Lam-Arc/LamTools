# LamImager 会话 UI 重设计

> **状态: 已完成** (2026-05-07)

## 目标
将 LamImager 从基于表单的任务管理器重新设计为基于对话的交互模型，包含会话窗口、LLM 助手侧边栏，以及集成的技能/规则/优化/规划功能。

## 关键设计决策

1. **基于对话的会话** 替代基于表单的任务创建
2. **侧边栏 + 聊天区域** 布局 (类似 ChatGPT)
3. **LLM 助手侧边栏** 包含 4 个标签页: 对话、优化、规划、技能
4. **上下文共享开关** 在对话标签页 (共享上下文 vs 仅当前输入)
5. **多选优化方向** + 支持自定义指令
6. **默认模型选择器** 在 API 管理页面
7. **默认中文界面**

## 新数据模型

### sessions
- id (UUID PK), title, created_at, updated_at

### messages
- id (UUID PK), session_id (FK), role (user/assistant/system)
- content (TEXT), message_type (text/image/plan/optimization/skill)
- metadata (JSON), created_at

### app_settings
- id (UUID PK), key (VARCHAR), value (JSON), updated_at
  - default_optimize_provider_id
  - default_image_provider_id
  - default_plan_provider_id

## UI 结构

### 会话页面 (/sessions, 默认首页)
- 左侧: 会话列表 (220px) 显示标题、进度条、费用/token
- 中间: 聊天区域，消息流 + 输入区
- 右侧: LLM 助手侧边栏 (360px，可折叠)，包含 4 个标签页

### API 管理页面 (/api-manage)
- 顶部: 默认模型配置 (3 个选择器)
- 底部: 提供商表格 (保持原有设计)

### 其他页面
- 技能、规则、参考图、设置 - 保持现有设计，翻译为中文

## 技能/规则调用链

1. 用户输入 → 技能应用 (可选，手动选择)
2. → 规则应用 (自动，全局，按优先级)
3. → 提示词优化 (可选，手动触发)
4. → 任务规划 (可选，手动触发)
5. → 图像生成 (并行 API 调用)
6. → 自动账单记录

## 导航 (中文)
- 概览, 会话, API管理, 技能, 规则, 参考图, 设置
