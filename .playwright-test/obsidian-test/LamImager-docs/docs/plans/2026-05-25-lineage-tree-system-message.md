# 谱系图树状图改造 + 系统消息气泡化 实施计划

> **For agentic workers:** Use executing-plans to implement this plan task-by-task.

**Goal:** 将谱系图从垂直列表抽屉改为可缩放拖拽的树状图面板，系统消息改为居中气泡样式。

**Architecture:** 纯 Canvas 绘制树状图（不引入 Vue Flow），自上而下 DAG 布局算法，支持缩放/平移/点击选中/详情面板。系统消息新增 SystemMessageCard.vue 组件。不引入新 npm 依赖。

**Tech Stack:** Vue3 / Canvas / TypeScript / 现有 CSS 变量体系（黑白灰）

---

## Task 1: 系统消息气泡化

**Files:**
- `frontend/src/components/session/SystemMessageCard.vue` (新建)
- `frontend/src/components/session/MessageList.vue` (修改)

**Steps:**
- [ ] 创建 `SystemMessageCard.vue`：居中气泡、小字号、浅灰背景、药丸圆角、无复制按钮
- [ ] 在 `MessageList.vue` 的 v-for 循环中，在 `TextMessageCard` 分支前插入 `msg.role === 'system'` 的判断，使用 `SystemMessageCard`
- [ ] 在 `MessageList.vue` CSS 中添加 `.message.system` 样式：`align-self: center; max-width: 60%`

**Verification:**
- [ ] 创建新会话后，欢迎语消息显示为居中淡灰小气泡
- [ ] assistant/user 消息样式不受影响

**Commit:** `feat: system message centered bubble style`

---

## Task 2: 重写 LineageDrawer 为 LineageTreeGraph

**Files:**
- `frontend/src/components/session/LineageDrawer.vue` (重写)
- `frontend/src/components/session/LineageDrawer.vue` → 重命名概念为树状图（文件名保持不变，内部重写）

**Steps:**
- [ ] 将 LineageDrawer.vue 从垂直列表改为 Canvas 绘制的树状图
- [ ] 实现 DAG 布局算法：根节点在顶部，子节点向下展开，DFS 水平排序
- [ ] 实现视图状态管理：viewX, viewY, viewZoom, selectedNode, hoveredNode
- [ ] 实现 Canvas 绘制：节点卡片（缩略图 + 模式色标 + 标签 + 时间 + HEAD标记）、贝塞尔曲线连线
- [ ] 实现交互：Ctrl+拖拽平移、滚轮缩放（鼠标中心）、点击选中（路径高亮+详情）、hover 高亮
- [ ] 实现 fitToView 自动适应画布
- [ ] 保留现有功能：fetchTree、分支选择（改为底部下拉）、分支重命名、loading/error/empty 状态
- [ ] 保留现有 emit 接口：close, select-image

**Verification:**
- [ ] 打开谱系图，树状图正确渲染所有节点和连线
- [ ] Ctrl+拖拽可平移，滚轮可缩放（以鼠标为中心）
- [ ] 点击节点选中，路径高亮，再次点击打开详情
- [ ] HEAD 路径默认彩色高亮
- [ ] 分支切换、重命名仍可用
- [ ] loading/error/empty 状态正常显示

**Commit:** `feat: lineage tree graph with zoom/pan/select`

---

## Task 3: 详情面板

**Files:**
- `frontend/src/components/session/LineageDrawer.vue` (在 Task 2 基础上增加)

**Steps:**
- [ ] 在 LineageDrawer.vue 中添加详情 overlay 遮罩 + 详情卡片
- [ ] 详情卡片展示：图片预览区 + 模式 badge + prompt 全文 + 时间 + 参考图缩略图 + HEAD 标记
- [ ] 点击节点一次选中（路径高亮），再次点击弹出详情
- [ ] ESC / 点空白 / 关闭按钮 关闭详情并取消选中
- [ ] 非选中节点和连线淡化至 25%

**Verification:**
- [ ] 选中节点后详情面板正确显示所有信息
- [ ] 参考图（source_image_urls）以缩略图形式展示
- [ ] 关闭详情后恢复全亮状态

**Commit:** `feat: lineage node detail panel with prompt and refs`

---

## Task 4: 底部控制栏

**Files:**
- `frontend/src/components/session/LineageDrawer.vue` (在 Task 2/3 基础上增加)

**Steps:**
- [ ] 添加底部栏：分支下拉选择器 + 缩放按钮 (+/−/适应) + 缩放百分比
- [ ] 分支选择器替代原来的垂直分支列表（改为 compact 下拉）
- [ ] 模式色标 legend（generate/variation/refine）

**Verification:**
- [ ] 分支切换正常工作
- [ ] 缩放按钮点击生效
- [ ] 适应按钮一键复位视图

**Commit:** `feat: lineage bottom controls bar`

---

## Task 5: 清理 demo 文件 + 验证

**Files:**
- `lineage-tree-demo.html` (删除)
- `lineage-wheel-demo.html` (删除)
- `lineage-wheel-demo-v2.html` (删除)

**Steps:**
- [ ] 删除所有临时 demo HTML 文件
- [ ] 启动前端 dev server，实际测试谱系图和系统消息
- [ ] 检查 LSP diagnostics 无错误

**Verification:**
- [ ] 前端无编译错误
- [ ] demo 文件已删除
- [ ] 谱系图和系统消息在实际应用中正常工作

**Commit:** `chore: cleanup demo files and verify`