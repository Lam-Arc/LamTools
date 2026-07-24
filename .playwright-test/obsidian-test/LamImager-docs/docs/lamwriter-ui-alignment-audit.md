# LamWriter UI 对齐核查

核查时间：2026-06-02

对照源：`E:\LamWriter\frontend\src`

目标：LamImager 使用 LamWriter 同一套前端骨架、基础样式、页面入口和交互心智；业务能力不同的地方只保留 Artist 必需差异。

## 已逐行一致

| LamImager 文件 | LamWriter 文件 | 结论 |
|---|---|---|
| `frontend/src/main.ts` | `E:\LamWriter\frontend\src\main.ts` | 完全一致。 |
| `frontend/src/App.vue` | `E:\LamWriter\frontend\src\App.vue` | 完全一致。 |
| `frontend/src/router/index.ts` | `E:\LamWriter\frontend\src\router\index.ts` | 完全一致，只有 `/` 和 `/settings` 两个入口。 |
| `frontend/src/styles/variables.css` | `E:\LamWriter\frontend\src\styles\variables.css` | 完全一致。 |
| `frontend/src/styles/base.css` | `E:\LamWriter\frontend\src\styles\base.css` | 完全一致。 |
| `frontend/src/components/UiSelect.vue` | `E:\LamWriter\frontend\src\components\UiSelect.vue` | 完全一致，设置页使用同一选择器。 |

## 基础样式差异

无。

`frontend/src/styles/components.css` 已与 LamWriter 完全一致。之前临时加过抽屉关闭态位移，但用户明确要求以 LamWriter UI 为准后已撤回。

## WorkbenchView 差异

`WorkbenchView.vue` 不能逐行复制 LamWriter，原因是两者业务对象不同：

| LamWriter 段落 | LamImager 对应段落 | 是否继续对齐 | 理由 |
|---|---|---|---|
| 项目 / work root 分组 | 会话列表 | 保留差异 | LamImager 后端没有 Writer 的项目根目录模型；强行复制会制造假入口。 |
| Git 图、diff、撤销改动 | 谱系图、HEAD、图片详情 | 保留差异 | Artist 的核心资产是图片谱系，不是代码仓库。 |
| Writer runtime block / activity flow | Artist 过程卡 + Artist 活动流 | 已对齐骨架 | 已改成 `writer-card process-card`、`processed-row`、`activity-flow-card` 结构，不再使用独立进度面板。 |
| 附件上传 | 参考图上传、粘贴、拖拽 | 保留差异 | Artist 上传对象是图片参考，不是 Writer 文件附件。 |
| Writer 回复附件预览 | 图片详情浮层、下载、设 HEAD、基于生成 | 保留差异 | Artist 需要图片操作面板。 |
| 右侧 Git/Status 面板 | 当前会话、账单、Runtime、最近图片、快捷操作 | 已对齐骨架 | 已改为 `side-section` / `activity-item` 结构；内容换成 Artist 的当前上下文。 |
| 全局快捷键 `Ctrl+Tab` / `Ctrl+E` / `Escape` | 同样保留 | 已对齐 | 两边交互一致。 |
| UI 密度、内容宽度、主题变量 | `lamimager-ui-system` | 已接通 | Workbench 已读取同一类 UI 设置并写入 shell CSS 变量，默认密度改为 compact，贴近当前 LamWriter 显示。 |

### WorkbenchView 逐段核对

| 代码段 | LamWriter 作用 | LamImager 当前作用 | 结论 |
|---|---|---|---|
| `<script setup>` imports | 引入 Project/Session/Step/SSE/Config stores、Git 类型、附件类型。 | 引入 Session/Provider/Billing stores、图片谱系、Artist 消息、下载能力。 | 业务依赖不同，保留；页面壳类名继续对齐。 |
| Runtime block 类型定义 | `RuntimeBlock`、`RuntimeGroup`、`DecisionView`、`DiffFileView` 服务 Writer 的代码执行过程。 | 没有复制这些类型，使用 Artist runtime progress 和图片 artifact。 | 保留差异；复制 Writer 类型会产生不可用的假 Git/假 diff。 |
| 左侧栏数据结构 | Project group + project session mode。 | 扁平 session list + 缩略图。 | 保留差异；Artist 没有 project/work root。 |
| `leftOpen/rightOpen/leftPinned/rightPinned` | 左右抽屉开关和固定。 | 同名同义状态。 | 已对齐。 |
| `shellClass/shellStyle` | 写入密度、内容宽度、主题变量。 | 写入密度、内容宽度、同一套主题变量。 | 已对齐。 |
| 模型菜单 | 按 provider 分组选择模型。 | 按供应商分组选择 LLM provider。 | UI 对齐，数据源保留差异。 |
| 质量菜单 | Writer 的执行质量档位。 | Artist 的质量档位入口。 | UI 对齐；后端语义不同。 |
| 左侧栏模板 | 项目组、会话、项目操作。 | 单个 Artist 工作区 + 会话列表 + 会话重命名。 | 已对齐骨架；使用 `project-block` / `conversation-list` / `conversation`，业务上不制造假 project。 |
| 主头部 | 当前 Writer session 标题、运行状态、Git 信息。 | Artist session 标题、消息数、会话编号。 | 保留差异；视觉骨架使用 `thread-header`。 |
| 时间线消息 | 用户气泡、Writer 回复、runtime block、decision、lifecycle、diff review。 | 用户消息、Artist reply、多图批次、Artist 过程卡。 | 保留业务差异；runtime 展示已改为 `writer-card process-card`。 |
| 运行过程折叠 | `processed-row` 折叠多条 Writer 过程。 | Artist SSE 事件被整理为前端轻量活动流，完成后可折叠为 `processed-row`。 | 已对齐骨架；活动数据来源是 Artist runtime 事件。 |
| 右侧栏 | Git、运行状态、活动摘要。 | 当前会话、账单、Runtime、最近图片、谱系入口。 | 已对齐骨架；使用 `side-section` / `activity-item`，内容按 Artist 保留。 |
| 输入区 | 文件附件、模型菜单、质量菜单、发送。 | 参考图片、粘贴/拖拽、模型菜单、质量菜单、发送。 | 骨架对齐，上传对象按 Artist 保留。 |
| 模态层 | 新建项目、新建会话、AGENTS.md、附件预览、diff 审核、撤销确认。 | 图片详情、全屏谱系、谱系抽屉、灯箱、确认框。 | 保留差异；Artist 核心操作是图片和谱系。 |
| 全局键盘 | `G`、`Escape`、`Ctrl+Tab`、`Ctrl+E`。 | 同一套快捷键。 | 已对齐。 |
| 作用域样式 | Writer 业务卡、Git/diff/agent 补充样式。 | Artist 图片批次、谱系、图片详情补充样式。 | 保留差异；基础 shell 样式来自同一 `components.css`。 |

### Workbench 本轮继续对齐

| 原差异 | 处理 | 理由 |
|---|---|---|
| 根节点叠加 `session-page writer-shell` | 改为仅 `writer-shell` | `session-page` 没有样式依赖，会制造旧页面壳残留。 |
| 左右栏叠加 `left-panel/right-panel` | 改为仅 `writer-drawer drawer-left/right` | LamWriter 抽屉骨架已经足够表达结构。 |
| 主区叠加 `chat-area writer-main` | 改为仅 `writer-main` | `chat-area` 没有必要，删掉后更接近 LamWriter。 |
| `details/summary` 折叠过程 | 改回 `processed-row` 按钮 + 展开状态 | LamWriter 是按钮式折叠；浏览器实测 `details` 在当前样式下折叠失败。 |
| 图片占位缩略图使用紫蓝/红蓝渐变 | 改为主题灰阶渐变 | 占位图不是业务语义，不应破坏 LamWriter 的低调配色。 |
| HEAD / generate 使用固定紫色 | 改为 `var(--accent)` / 主题混合色 | 保留状态识别，但不固定旧 LamImager 彩色体系。 |
| 未使用的旧 session 组件 | 删除，仅保留 `Lightbox.vue`、`LineageDrawer.vue` | 当前 Workbench 不再引用旧消息卡、旧输入控件、旧上下文菜单；保留会制造 UI 分叉。 |
| 输入栏开合时瞬间位移 | `input-zone` 的局部 `transition` 补回 LamWriter 的 `left/width .5s` | 原因是同一元素同时挂 `input-zone floating-composer`，局部 transition 覆盖了全局输入栏过渡。 |
| 消息气泡旧视觉 | 用户消息改为 `user-row` + `user-bubble`，Artist 文本改为 `writer-reply-row` + `writer-reply-bubble` | 对齐 LamWriter 的聊天气泡体系；Artist 仍按业务保留多条 reply 分开显示，图片批次继续用图片卡片。 |

## SettingsView 差异

| LamWriter 段落 | LamImager 对应段落 | 是否继续对齐 | 理由 |
|---|---|---|---|
| `model-api` | `model-api` | 已对齐 | 默认用途 + API 管理统一放在第一入口。 |
| `writer` | `artist` | 保留差异 | 产品对象不同，但位置和心智一致，都是主产品行为设置。 |
| `project` | `workspace` | 保留差异 | Artist 没有 Writer 的 work root/project 后端模型，当前只放图片下载目录。 |
| `agents` | `tools` | 保留差异 | Artist 当前还没有 LogoAgent 等独立 Agent 管理，先展示运行能力。 |
| `ui-system` | `ui-system` | 已对齐 | 已有密度、内容宽度、运行面板开关、主题预览、预设分组、四区域渐变节点、角度、透明度、文字颜色和主题变量写入。 |
| Provider / Model 管理 | `ApiManage.vue` 插槽 | 保留差异 | LamImager 已有供应商和模型管理组件，作为设置页业务插槽更清晰；内联会增加重复。 |

### SettingsView 逐段核对

| 代码段 | LamWriter 作用 | LamImager 当前作用 | 结论 |
|---|---|---|---|
| 页面根 `settings-page` | 挂主题变量 `settingsThemeStyle`。 | 同样挂 `settingsThemeStyle`。 | 已对齐。 |
| 侧栏品牌与返回 | 设置标题、关闭按钮、返回主界面。 | 同样结构。 | 已对齐。 |
| 设置导航 | `模型与 API / Writer / 项目 / Agent / 界面`。 | `模型与 API / Artist 行为 / 工作区 / 工具 / 界面 / 数据管理`。 | 顺序和心智对齐；标签按产品保留。 |
| `model-api` | Provider、Model、用途分配。 | 默认 Runtime / 图像生成 + API 管理。 | 已对齐到同一入口；数据模型不同。 |
| Provider/Model 表单 | LamWriter 内联管理 provider/model/routing rule。 | `ApiManage.vue` 承担供应商、模型、测试、删除。 | 保留组件化差异；UI 卡片语言已对齐。 |
| 产品行为区 | Writer 默认质量档位。 | Artist 默认尺寸、并发。 | 保留差异；属于产品行为设置。 |
| 项目区 | 默认 work root。 | 图片下载目录。 | 保留差异；Artist 无 work root。 |
| Agent/Tool 区 | 展示后端 Agent 和 Tool。 | 展示图像生成、视觉理解、外部调研能力。 | 保留差异；Artist 专用 Agent 尚未后端化。 |
| UI System 区 | 密度、内容宽度、完整主题预设、渐变节点、运行面板。 | 密度、内容宽度、运行面板开关、主题预览、预设分组、四区域渐变节点、主题变量存储。 | 已对齐；只把 Writer 的 Git 图开关换成 Artist 的最近图片开关。 |
| 数据区 | LamWriter 没有同名主区。 | 缓存清理、旧版数据导入。 | 保留差异；这是 LamImager 迁移业务入口。 |
| 本地设置持久化 | Writer 同步后端 app settings + localStorage。 | LamImager 当前使用 localStorage + 既有 settings API。 | 保留差异；后端设置模型不同。 |
| API 测试成功提示 | Writer 使用低调状态文本。 | 已把亮绿色改成主题混合色。 | 已对齐配色节奏。 |

### Settings 业务插槽继续对齐

| 原差异 | 处理 | 验证 |
|---|---|---|
| `ApiManage.vue` 使用未定义的 `drawer-overlay/drawer/drawer-header/form-group` | 改为 LamWriter 已有的 `modal-overlay/modal-card/form-grid/field/modal-actions` | 浏览器实测新增 Provider 弹窗：`modalOverlay=1`、`modalCard=1`、旧抽屉类为 0。 |
| `ConfirmDialog.vue` / `Lightbox.vue` / 数据管理按钮使用未定义 `btn` / `btn-sm` | 改为 `small-btn`、`danger`、`btn-primary` 等已有样式 | 静态扫描已无 `drawer-overlay`、`drawer-header`、`form-group`、`btn-sm` 残留。 |
| 普通 `select` 控件缺少设置页风格 | 在 `ApiManage.vue` scoped 样式中补齐 `.field select` | 构建和类型检查通过。 |

### Settings 本轮继续对齐

| 原差异 | 处理 | 理由 |
|---|---|---|
| `ui-system` 使用 `settings-grid two` 双列布局 | 改为 LamWriter 同款纵向 `settings-panel` | 设置页视觉节奏应和 LamWriter 一致。 |
| 密度选择使用 `segmented` 按钮 | 改为 `UiSelect` | LamWriter 用同一选择器组件；统一控件语言。 |
| Artist 行为和工作区使用 `form-group` | 改为 `field` | 继续复用 LamWriter 表单样式。 |
| 主题卡额外 `ui-theme-card` 类 | 删除 | 没有业务必要，使用普通 `setting-card`。 |

## 文件树差异

| 差异 | 是否问题 | 理由 |
|---|---|---|
| LamImager 保留 `api/apiProvider.ts`、`api/session.ts`、`stores/provider.ts`、`stores/session.ts` 等拆分文件 | 不是问题 | Artist 后端 API 与 Writer 不同，拆分是业务层，不影响 UI 骨架。 |
| LamWriter 有 `stores/project.ts`、`stores/step.ts`、`stores/sse.ts` | 不是问题 | Writer 的工程项目、步骤、SSE 模型不同；LamImager 对应为会话、供应商、图片谱系和 Artist runtime。 |
| LamImager 有 `components/session/*` 图片相关组件 | 不是问题 | 这些是 Artist 图片查看、谱系、灯箱、消息渲染所需。 |
| LamWriter 有 `api/index.ts` 统一出口 | 后续可优化 | LamImager 目前 API 文件较多，可未来抽前端 core SDK 时统一出口，但这不是当前 UI 显示问题。 |

## 当前结论

UI 入口、路由、基础样式、选择器、设置页骨架、完整界面主题编辑器、主工作台 shell、左右抽屉、底部输入区、运行过程卡已经向 LamWriter 对齐。

仍然不逐行一致的部分全部集中在业务层：Writer 是代码项目工作台，Artist 是图片生成工作台。继续强行复制这些业务段落会引入假 Git、假项目、假 Agent 配置，反而增加复杂度。

## 工程外壳对齐

| 项目 | LamWriter | LamImager 当前 | 结论 |
|---|---|---|---|
| dev 端口 | `vite --port 6174` | `vite --port 5174` | 对齐“显式固定端口”的做法；端口按 LamImager 当前访问地址保留。 |
| API 代理 | `VITE_API_TARGET` 可覆盖，默认后端地址 | `VITE_API_TARGET` 可覆盖，默认 `http://127.0.0.1:6171` | 已对齐可配置代理；默认地址按 Artist 后端保留。 |
| 旧 WS 代理 | 无 | 已删除 `/ws -> 8000` | 已对齐；当前前端不使用旧 WebSocket 代理。 |
| build 质量门 | 先类型检查再 Vite 打包 | `vue-tsc --noEmit && vite build` | 已对齐。 |
| Electron 打包 | 有 | 未复制 | 保留差异；LamImager 当前没有对应 Electron 工程和后端打包链。 |
| 依赖版本 | LamWriter 更新 | LamImager 保持现有锁定版本 | 保留差异；升级依赖会扩大风险，不是 UI 骨架对齐的必要条件。 |

类型检查修复：

| 文件 | 修复内容 |
|---|---|
| `useDialog.ts` | `_open` 返回类型允许 prompt/cancel 的 `null`。 |
| `useMarkdown.ts` | 未使用的代码块语言参数改为 `_lang`。 |
| `stores/session.ts` | long task step 元信息使用已有 `total_tokens` 字段。 |
| `ApiManage.vue` | 新增 Provider 按钮改为无参回调。 |
| `WorkbenchView.vue` | 删除未使用的节点分类函数、旧画布事件函数和未使用类型。 |

## 最新验证

| 验证项 | 结果 |
|---|---|
| `npm run build` | 通过，已包含 `vue-tsc --noEmit` 类型检查。 |
| 基础文件逐行比对 | `main.ts`、`App.vue`、`router/index.ts`、`variables.css`、`base.css`、`components.css`、`UiSelect.vue` 全部一致。 |
| Workbench 左栏 | DOM 中存在 `project-block` / `conversation-list` / `conversation`，旧 `new-session-btn` / `session-item` 不再出现。 |
| Workbench 右栏 | DOM 中存在 5 个 `side-section`，旧 `context-block` 不再出现。 |
| Workbench 主结构 | `thread-header` 是 `HEADER`，消息区是 `SECTION.thread`，输入区是 `FORM.floating-composer`。 |
| Settings UI System | 浏览器实测：“界面”分区存在 `theme-preview`、3 个预设分组、4 个主题区域、9 行渐变节点、4 个添加节点按钮。 |
| Artist 活动流 | 浏览器实测：请求失败时可记录 1 条运行过程；未展开时没有过程明细卡，点击 `processed-row` 后显示过程明细卡、分组和原始错误内容。 |
| 前端代理残留 | `frontend` 目录内未发现 `localhost:8000`、`127.0.0.1:8000`、`port: 5173`、`/ws` 旧代理配置。 |
| 未定义旧类残留 | `frontend/src` 中未发现 `drawer-overlay`、`drawer-header`、`form-group`、`btn-sm`。 |
| 最终浏览器 Workbench 复核 | `writerShell=1`、`writerDrawers=2`、`writerMain=1`、`threadHeader=1`、`floatingComposer=1`、旧壳类全为 0。 |
| 最终浏览器 Settings 复核 | `settingsPage=1`、`settingsSidebar=1`、`settingsMain=1`、`themeGrid=1`、`themeAreas=4`、`segmented=0`、`settingsGrid=0`。 |
| 输入栏过渡复核 | `.floating-composer` 计算样式包含 `left 0.5s cubic-bezier(...)`、`width 0.5s cubic-bezier(...)`。 |
| 消息气泡复核 | `.user-row` 10、`.user-bubble` 10、`.writer-reply-row` 16、`.writer-reply-bubble` 16；旧 `.msg-text` 和 `.artist-reply-line` 均为 0。 |

## 最新代码级计数

| 文件 | LamImager | LamWriter | 结论 |
|---|---:|---:|---|
| `WorkbenchView.vue` 行数 | 2295 | 3222 | 差异来自 Artist 图片业务 vs Writer 代码项目业务；骨架标记已对齐。 |
| `SettingsView.vue` 行数 | 902 | 1875 | 差异来自 Provider/API 管理方式和产品设置项；界面主题编辑器已补齐。 |
| `components.css` 行数 | 4391 | 4391 | 逐字一致。 |

关键骨架标记复核：

| 标记 | LamImager Workbench | LamWriter Workbench | 结论 |
|---|---:|---:|---|
| `writer-shell` | 1 | 1 | 对齐。 |
| `writer-drawer drawer-left` | 1 | 1 | 对齐。 |
| `writer-main` | 1 | 1 | 对齐。 |
| `thread-header` | 1 | 1 | 对齐。 |
| `floating-composer` | 1 | 1 | 对齐。 |
| `project-block` | 1 | 1 | 对齐；LamImager 只有 Artist 工作台一个业务块。 |
| `side-section` | 5 | 2 | 保留差异；Artist 右栏包含会话、账单、Runtime、最近图片、操作。 |
| `processed-row` | 1 | 2 | 保留差异；Writer 还有历史 runtime group，Artist 只需要完成后的过程折叠入口。 |
| `activity-flow-card` | 1 | 1 | 对齐。 |

浏览器复核补充：

| 标记 | 当前 DOM 数量 | 结论 |
|---|---:|---|
| `.session-page` | 0 | 旧壳类已移除。 |
| `.chat-area` | 0 | 旧壳类已移除。 |
| `.left-panel` | 0 | 旧壳类已移除。 |
| `.right-panel` | 0 | 旧壳类已移除。 |
| `.writer-drawer` | 2 | 左右抽屉保留 LamWriter 骨架。 |

主界面浏览器尺寸对照：

| 指标 | LamImager | LamWriter | 结论 |
|---|---:|---:|---|
| Shell | 1156×664 | 1156×664 | 对齐。 |
| 左侧抽屉 | 322×664 | 322×664 | 对齐。 |
| 右侧抽屉 | 272×664 | 272×664 | 对齐。 |
| 主工作区 | 844×664 | 844×664 | 对齐。 |
| 输入框 | 727×106 | 727×100 | 基本对齐；LamImager 多 6px 来自参考图/图片输入能力预留。 |
| 标题区 | 728×46 | 728×55 | 保留轻微差异；LamImager 标题信息更少。 |

| 标记 | LamImager Settings | LamWriter Settings | 结论 |
|---|---:|---:|---|
| `settings-page` | 1 | 1 | 对齐。 |
| `settings-sidebar` | 1 | 1 | 对齐。 |
| `settings-nav` | 1 | 1 | 对齐。 |
| `theme-settings-grid` | 1 | 1 | 对齐。 |
| `theme-area-card` | 4 | 4 | 对齐。 |
| `setting-card` | 10 | 9 | 保留差异；LamImager 把 API 管理和数据迁移作为业务卡片。 |

浏览器复核补充：

| 标记 | 当前 DOM 数量 | 结论 |
|---|---:|---|
| `.settings-grid` | 0 | 已移除双列分叉。 |
| `.segmented` | 0 | 已改回 `UiSelect`。 |
| `.ui-select` | 1 | UI System 密度选择复用 LamWriter 选择器。 |
| `.setting-card` | 3 | 当前“界面”分区和 LamWriter 一样为界面、主题、运行面板三张卡。 |

设置页浏览器尺寸对照：

| 指标 | LamImager | LamWriter | 结论 |
|---|---:|---:|---|
| 页面 | 1156×664 | 1156×664 | 对齐。 |
| 侧栏 | 300×664 | 300×664 | 对齐。 |
| 主区 | 856×664 | 856×664 | 对齐。 |
| 内容宽度 | 710 | 710 | 对齐。 |
| UI System 卡片数 | 3 | 3 | 对齐。 |
| 主题区域 | 4 | 4 | 对齐。 |
| 预设分组 | 3 | 3 | 对齐。 |

## 未使用组件清理

已删除以下未被当前 Workbench / Settings 引用的旧会话组件：

| 文件 | 处理理由 |
|---|---|
| `ArtistImageMessageCard.vue` | 旧 Artist 图片卡，当前 Workbench 已内联批量图片卡。 |
| `ImageMessageCard.vue` | 旧图片消息卡，当前不再使用。 |
| `TextMessageCard.vue` | 旧文本消息卡，当前不再使用。 |
| `PlanMessageCard.vue` | 旧计划消息卡，当前不再使用。 |
| `OptimizationCard.vue` | 旧优化卡，当前不再使用。 |
| `SystemMessageCard.vue` | 旧系统消息卡，当前不再使用。 |
| `ComposerControls.vue` | 旧输入控制区，当前 Workbench 已使用 LamWriter 浮动输入栏。 |
| `ContextImageStrip.vue` | 旧参考图条，当前 Workbench 已内联参考图预览。 |
| `ContextMenu.vue` | 旧右键菜单，当前不再使用。 |
| `CompareOverlay.vue` | 旧对比层，当前不再使用。 |
| `VideoCoverCard.vue` | 仅被已删除旧图片卡引用。 |

保留：

| 文件 | 保留理由 |
|---|---|
| `Lightbox.vue` | 当前 Workbench 实际引用，用于图片查看。 |
| `LineageDrawer.vue` | 当前 Workbench 实际引用；已把旧高饱和语义色改为低饱和主题色。 |

当前组件目录：

| 文件 | 角色 |
|---|---|
| `ConfirmDialog.vue` | 通用确认框，按钮已改为 LamWriter 样式类。 |
| `ErrorBoundary.vue` | 通用错误边界，按钮已改为 `small-btn`。 |
| `UiSelect.vue` | 与 LamWriter 逐字一致。 |
| `session/Lightbox.vue` | 当前图片查看能力。 |
| `session/LineageDrawer.vue` | 当前图片谱系能力。 |
