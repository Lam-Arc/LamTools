# LamImager UI 重新设计方案

## 1. 设计目标

在保持现有功能完整性的基础上，对界面进行现代化升级，提升视觉层次感和交互体验。

## 2. 设计原则

- **极简克制**: 减少视觉噪音，突出内容本身
- **层次分明**: 通过间距、阴影、字重区分信息层级
- **一致性**: 统一的圆角、间距、阴影系统
- **功能性优先**: 每一处设计改动都服务于可用性

## 3. 色彩系统 (微调)

```css
:root {
  /* 背景层级 */
  --bg-base: #F5F5F5;        /* 页面底色，比之前稍深更有质感 */
  --bg-elevated: #FFFFFF;     /* 卡片/面板背景 */
  --bg-hover: #EBEBEB;        /* 悬停状态 */
  --bg-active: #E0E0E0;        /* 激活状态 */

  /* 边框 */
  --border-light: #EEEEEE;    /* 细微分隔线 */
  --border-default: #E0E0E0;  /* 默认边框 */
  --border-strong: #CCCCCC;   /* 强调边框 */

  /* 文字 */
  --text-primary: #1A1A1A;    /* 主文字 */
  --text-secondary: #757575;   /* 次要文字 */
  --text-tertiary: #9E9E9E;   /* 辅助文字 */
  --text-disabled: #BDBDBD;   /* 禁用状态 */

  /* 强调色 */
  --accent: #000000;          /* 主强调色保持黑色 */
  --accent-inverse: #FFFFFF; /* 黑色背景上的文字 */

  /* 功能色 (简化) */
  --success: #2E7D32;
  --warning: #F57C00;
  --danger: #D32F2F;

  /* 阴影系统 */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.08);
  --shadow-lg: 0 8px 24px rgba(0,0,0,0.12);
  --shadow-xl: 0 16px 48px rgba(0,0,0,0.16);

  /* 圆角系统 */
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 16px;
  --radius-xl: 24px;

  /* 间距系统 */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;

  /* 过渡 */
  --transition-fast: 120ms ease;
  --transition-normal: 200ms ease;
  --transition-slow: 300ms ease;
}
```

## 4. 字体系统

```css
--font-sans: "Inter", -apple-system, BlinkMacSystemFont, "PingFang SC", "Noto Sans SC", sans-serif;
--font-mono: "JetBrains Mono", "SF Mono", Consolas, monospace;

/* 字号阶梯 */
--text-xs: 11px;
--text-sm: 12px;
--text-base: 14px;
--text-lg: 16px;
--text-xl: 18px;
--text-2xl: 24px;
--text-3xl: 32px;

/* 行高 */
--leading-tight: 1.25;
--leading-normal: 1.5;
--leading-relaxed: 1.75;
```

## 5. 布局系统

### 5.1 整体布局
- **顶栏高度**: 56px (从 48px 提升)
- **侧边栏宽度**: 220px (从 200px 提升)
- **侧边栏折叠**: 56px (显示图标)
- **圆角**: 统一使用 --radius-md (10px)

### 5.2 页面结构
```
┌─────────────────────────────────────────────────────────┐
│  顶栏 (56px)                                           │
├────────┬────────────────────────────────────────────────┤
│        │                                                │
│ 侧边栏 │  主内容区                                       │
│ (220px)│                                                │
│        │                                                │
│        ├────────────────────────────────────────────────┤
│        │  底部输入区 (可变高度)                          │
└────────┴────────────────────────────────────────────────┘
```

## 6. 组件重构

### 6.1 顶栏 (Topbar)
**现状问题**: 信息密度低，账单展示不够突出

**优化方案**:
- 高度提升到 56px
- 左侧 Logo 区域增加视觉重量
- 右侧账单信息使用圆角胶囊样式，悬停时展开详情
- 增加快捷操作区域(新建会话按钮)

```css
.topbar {
  height: 56px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-light);
  padding: 0 var(--space-6);
  display: flex;
  align-items: center;
  justify-content: space-between;
  backdrop-filter: blur(8px); /* 毛玻璃效果 */
  position: sticky;
  top: 0;
  z-index: 100;
}

.topbar-brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--text-lg);
  font-weight: 700;
  letter-spacing: -0.5px;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.billing-pill {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  background: var(--bg-base);
  border-radius: 20px;
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.billing-pill:hover {
  background: var(--bg-hover);
  transform: translateY(-1px);
}
```

### 6.2 侧边栏 (Sidebar)
**现状问题**: 折叠后信息丢失严重，导航项缺少视觉反馈

**优化方案**:
- 折叠后显示为 56px 图标模式
- 导航项使用圆角背景替代下划线
- 当前页使用左侧色块指示条
- 增加悬停动画效果

```css
.sidebar {
  width: 220px;
  background: var(--bg-elevated);
  border-right: 1px solid var(--border-light);
  display: flex;
  flex-direction: column;
  transition: width var(--transition-normal);
}

.sidebar.collapsed {
  width: 56px;
}

.sidebar-nav {
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-size: var(--text-base);
  transition: all var(--transition-fast);
  position: relative;
}

.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.nav-item--active {
  background: var(--bg-base);
  color: var(--text-primary);
  font-weight: 500;
}

.nav-item--active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 20px;
  background: var(--accent);
  border-radius: 0 2px 2px 0;
}
```

### 6.3 会话列表 (Session List)
**现状问题**: 视觉平淡，状态区分度低

**优化方案**:
- 卡片式设计，增加圆角和阴影
- 悬停时卡片微微上浮
- 状态徽章使用更柔和的色调
- 元信息使用更小的字号和次要色

```css
.session-list {
  width: 280px;
  background: var(--bg-elevated);
  border-right: 1px solid var(--border-light);
  display: flex;
  flex-direction: column;
}

.session-item {
  padding: var(--space-4);
  margin: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
  border: 1px solid transparent;
}

.session-item:hover {
  background: var(--bg-base);
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}

.session-item.active {
  background: var(--bg-base);
  border-color: var(--border-default);
  box-shadow: var(--shadow-sm);
}

.session-title {
  font-size: var(--text-base);
  font-weight: 500;
  margin-bottom: var(--space-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-meta {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: var(--text-xs);
  font-weight: 500;
}

.status-badge.generating {
  background: rgba(0,0,0,0.06);
  color: var(--text-primary);
}

.status-badge.optimizing,
.status-badge.planning {
  background: rgba(0,0,0,0.04);
  color: var(--text-secondary);
}

.status-badge.error {
  background: rgba(211,47,47,0.1);
  color: var(--danger);
}
```

### 6.4 消息区域 (Message Area)
**现状问题**: 消息气泡缺乏层次感

**优化方案**:
- 用户消息右对齐，使用强调色背景
- 助手消息使用卡片样式，带阴影
- 消息之间保持合适间距
- 消息时间戳使用更柔和的样式

```css
.message.user {
  align-self: flex-end;
  max-width: 75%;
}

.message.user .message-content {
  background: var(--accent);
  color: var(--accent-inverse);
  border-radius: var(--radius-lg) var(--radius-lg) var(--radius-sm) var(--radius-lg);
  padding: var(--space-4) var(--space-5);
  box-shadow: var(--shadow-md);
}

.message.assistant {
  align-self: flex-start;
  max-width: 75%;
}

.message.assistant .message-content {
  background: var(--bg-elevated);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg) var(--radius-lg) var(--radius-lg) var(--radius-sm);
  padding: var(--space-4) var(--space-5);
  box-shadow: var(--shadow-sm);
}
```

### 6.5 输入区域 (Input Area)
**现状问题**: 输入框与操作按钮视觉分离

**优化方案**:
- 输入区域使用深色背景增强聚焦感
- 圆角更大的输入框
- 发送按钮使用填充样式
- 增加打字时的微交互动效

```css
.input-area {
  background: var(--bg-elevated);
  border-top: 1px solid var(--border-light);
  padding: var(--space-4) var(--space-6);
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  box-shadow: 0 -4px 20px rgba(0,0,0,0.04);
}

.input-main {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  max-width: 800px;
  margin: 0 auto;
}

.input-area textarea {
  width: 100%;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: var(--space-4) var(--space-5);
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  resize: none;
  transition: all var(--transition-fast);
  background: var(--bg-base);
}

.input-area textarea:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(0,0,0,0.06);
  background: var(--bg-elevated);
}

.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: var(--space-2);
}

.btn-send {
  padding: var(--space-3) var(--space-6);
  background: var(--accent);
  color: var(--accent-inverse);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.btn-send:hover {
  opacity: 0.9;
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

.btn-send:active {
  transform: translateY(0);
}
```

### 6.6 助手侧边栏 (Assistant Sidebar)
**现状问题**: Tab 切换不够流畅，内容区域拥挤

**优化方案**:
- Tab 使用更大胆的选中样式
- 各功能面板增加标题和分组
- 对话区域使用更宽松的间距
- 优化设置面板的展开/收起动画

```css
.assistant-sidebar {
  width: 320px;
  background: var(--bg-elevated);
  border-left: 1px solid var(--border-light);
  display: flex;
  flex-direction: column;
  box-shadow: -4px 0 20px rgba(0,0,0,0.03);
}

.assistant-tabs {
  display: flex;
  padding: var(--space-3);
  gap: var(--space-1);
  border-bottom: 1px solid var(--border-light);
}

.tab-btn {
  flex: 1;
  padding: var(--space-3);
  border: none;
  background: transparent;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);
}

.tab-btn.active {
  background: var(--bg-base);
  color: var(--text-primary);
  font-weight: 600;
}

.assistant-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-5);
}

.tab-panel {
  animation: fadeIn var(--transition-normal);
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
```

### 6.7 管理页面表格 (Management Tables)
**现状问题**: 表格行与行之间区分度不足

**优化方案**:
- 表头使用更浅的背景
- 行悬停时高亮背景
- 斑马条纹可选
- 操作按钮组使用图标化

```css
table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  background: var(--bg-elevated);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

th {
  background: var(--bg-base);
  font-size: var(--text-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-secondary);
  padding: var(--space-4) var(--space-5);
  text-align: left;
  border-bottom: 1px solid var(--border-light);
}

td {
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--border-light);
  font-size: var(--text-base);
}

tr:hover td {
  background: var(--bg-base);
}

tr:last-child td {
  border-bottom: none;
}

.badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: var(--text-xs);
  font-weight: 500;
}

.badge-active {
  background: rgba(46,125,50,0.1);
  color: var(--success);
}

.badge-inactive {
  background: var(--bg-base);
  color: var(--text-tertiary);
}
```

### 6.8 按钮系统 (Buttons)
**现状问题**: 按钮样式过于简单

**优化方案**:
- 主按钮使用填充样式和微阴影
- 次按钮使用描边样式
- 图标按钮使用圆形
- 悬停和点击有明确的视觉反馈

```css
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-5);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--bg-elevated);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.btn:hover {
  background: var(--bg-hover);
  border-color: var(--border-strong);
  transform: translateY(-1px);
}

.btn:active {
  transform: translateY(0);
  background: var(--bg-active);
}

.btn-primary {
  background: var(--accent);
  color: var(--accent-inverse);
  border-color: var(--accent);
}

.btn-primary:hover {
  opacity: 0.9;
  background: var(--accent);
  box-shadow: var(--shadow-md);
}

.btn-danger {
  color: var(--danger);
  border-color: var(--danger);
}

.btn-danger:hover {
  background: var(--danger);
  color: var(--accent-inverse);
}

.btn-sm {
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-xs);
}

.btn-icon {
  width: 32px;
  height: 32px;
  padding: 0;
  border-radius: 50%;
}

.btn-icon:hover {
  background: var(--bg-base);
}
```

## 7. 动效设计

### 7.1 微交互
- 按钮悬停: scale(1.02) + shadow
- 卡片悬停: translateY(-2px) + shadow
- 输入框聚焦: 边框高亮 + 微光晕
- 侧边栏折叠: width 过渡 + 内容淡入淡出

### 7.2 页面过渡
- 路由切换: 淡入淡出 (200ms)
- 抽屉滑入: translateX + opacity (300ms)
- 模态框: scale + opacity (200ms)

### 7.3 加载状态
- 骨架屏 (Skeleton) 替代 spinner
- 脉冲动画用于流式输出
- 进度条使用渐变色

## 8. 响应式策略

考虑到这是桌面应用，主要针对 1280px+ 的屏幕优化，但保留以下断点:

- **≥1440px**: 侧边栏默认展开
- **1280-1439px**: 侧边栏可折叠
- **1024-1279px**: 助手侧边栏默认为收起状态

## 9. 可访问性 (Accessibility)

- 所有交互元素有清晰的焦点状态
- 颜色对比度符合 WCAG AA 标准
- 语义化 HTML 结构
- 支持键盘导航

## 10. 实现优先级

### Phase 1: 基础系统
1. CSS 变量重构 (global.css)
2. 字体系统引入
3. 按钮/表单基础组件重制

### Phase 2: 布局优化
4. 顶栏重构
5. 侧边栏重构
6. 会话列表卡片化

### Phase 3: 交互优化
7. 消息区域优化
8. 输入区域重构
9. 助手侧边栏优化

### Phase 4: 管理页面
10. 表格样式统一
11. 表单抽屉优化

---

*本方案为设计指导，实际实现可根据反馈调整*
