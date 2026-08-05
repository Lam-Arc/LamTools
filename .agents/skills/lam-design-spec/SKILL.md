---
name: lam-design-spec
description: 当在 core/ui 或 member 前端编写/修改 Vue 组件、CSS、scoped style、设计 token，或需要确定 LamTools 配色与设计决策时使用。强制遵循 LamTools 设计语言——主题 area 关联、token、组件配方、配色语义、状态、密度与动效。impeccable 仅在从零的新设计时介入；既有界面的一切设计决策与配色以本 skill 为准。
version: 0.1.0
---

# LamTools 设计语言规范

本 skill 是 LamTools 设计语言的**唯一真源**：管规范、管约束、管配色与设计决策。核心目的是**防止每次写组件都另起一套样式**。`impeccable` skill 仅在"从零的新设计"时介入决定观感；既有界面的一切设计决策、配色、token、组件、状态以本 skill 为准。

不另建 DESIGN.md（避免双源漂移）。

## 核心铁律

1. **优先用 token**，字面量值必须落在标尺上；标尺外值须先提议 token，不得随手硬编码。
2. **每类控件只有一种配方**；禁止新建平行实现（第二个下拉、第二套 `--fb-*` 命名空间）。
3. **hover↔active alpha 增量恒为 +4pp**（`--alpha-hover` 8% → `--alpha-active` 12%）；中性强交互用 `--alpha-*` token，不得再发明 5/6/7/9/10/14%。

## 主题 area 关联（最重要）

4 个 theme area，每个有 `-background`（渐变）/ `-text` / 派生变量。组件须引用**所在 area** 的变量，并在本地 `--text: var(--theme-{area}-text)` 重映射，再用 `color-mix(in srgb, var(--text) X%, transparent)` 派生 hover/边框/次要文字。语义色 `--green/--blue/--orange/--red/--purple` 不随主题变。

| area | 背景变量 | 文字变量 | 派生 | 用于 |
|------|---------|---------|------|------|
| backdrop | `--theme-backdrop-background` | `--theme-backdrop-text` | — | 外壳、侧栏、会话列表、项目菜单 |
| main | `--theme-main-background` | `--theme-main-text` | `-soft-background` / `-subtle-background` / `-border` | 主卡片、内容区、设置页 |
| composer | `--theme-composer-background` | `--theme-composer-text` | `-soft-background` | 底部输入栏、composer 菜单 |
| control | `--theme-control-background` | `--theme-control-text` | `-soft-background` | 按钮、输入框、下拉、select、徽章 |

**最常见错误**：control 控件误用 `--theme-main-text`，或直接用静态 `--panel/--line/--text` 绕过主题——主题切换时该组件不变色。

## Token 真源

来源：`core/ui/src/styles/variables.css`（基色 + 圆角 + 字体）+ 本次新增（间距 / 阴影分级 / 状态 alpha / 行渐隐）。

- **语义色**：`--green #32d17d` · `--blue #79bcff` · `--orange #ff9142` · `--red #f5555d` · `--purple #bd8cff`（不挂 area，不随主题变）
- **圆角**：`--radius-sm 6px`（输入/按钮/item）· `--radius 12px`（卡片/菜单）· `--radius-lg 18px`（大面板）· `--radius-xl 22px`（主应用卡）
- **间距**：`--space-1..6` = 4 / 8 / 12 / 16 / 24 / 32 px
- **阴影**：`--shadow-sm`（悬浮/hover 抬升）· `--shadow-md`（卡片/下拉/popover）· `--shadow-lg`（模态/遮罩）；`--shadow` 旧别名指向 `--shadow-lg`
- **状态 alpha**：`--alpha-hover 8%` · `--alpha-active 12%` · `--alpha-press 16%`
- **行渐隐**：`--row-fade 20%`（选项行左右两侧渐隐宽度，相对行宽）
- **z-index**：`--z-background-info 10` · `--z-stage 15` · `--z-main-surface 20` · `--z-edge-trigger 35` · `--z-composer 40` · `--z-popover 60` · `--z-modal 80` · `--z-toast 90`（来自 layout.css）
- **字体**：`--font-sans`（Inter + CJK 回退栈）· `--font-mono`（JetBrains Mono + 回退栈）· `--font` = `--font-sans`

## 配色语义

- **任务状态**：运行中=spinner 转圈（点色=控件色）；等待=`--orange` 70% + 控件色 30%；失败=`--red` 70% + 控件色 30%；完成=静止纯控件色。状态须有非色觉指示（动画/文字），非仅靠颜色。
- **文字层级**：`--text`（正文）> `color-mix(--text 65%)`（次要说明）> `color-mix(--text 45%)`（占位/禁用辅助）。次要/占位由当前 area 的 `--text` 派生，非静态 muted。
- **面板层级**：`--bg`（最底）< `--panel-2`（输入/凹陷）< `--panel`（卡片）< `--panel-3`（凸起/激活）。
- **暗色唯一**：当前仅暗色主题；不得引入未声明的浅色配色（主题预设中的浅色由 `--theme-*` 控制，非新增配色体系）。

## 设计决策

- **视觉密度**：密集工作台、低视觉噪音；间距取标尺较紧一档，不堆叠大留白。
- **视觉层级**：task state first——运行/等待/失败/完成须一眼可辨。
- **动效**：克制 ease-out；禁止 bounce/elastic；所有动效须有 `prefers-reduced-motion` 回退。动画以后再细化。
- **中性原则**（来自 AGENTS.md/PRODUCT.md）：core 中性，member 差异只走 slot/label，不走分歧样式。
- **工具铁律**（来自 AGENTS.md）：任何 GUI 能力须有对应 CLI。

## 组件配方

每类组件只有一种配方。改组件前先查本表。

### 卡片 / 面板（main area）
`--radius` · `--space-3` 内边距 · `1px solid var(--theme-main-border)` · `--shadow-md` · 背景 `--theme-main-background`。内部层级用派生 `--theme-main-soft-background` / `-subtle-background` 表达，**禁止嵌套实色卡**。

### 输入框 — 三类
1. **标题输入**（main area）：无边框纯文字。`border:0` / `outline:0` / `background:transparent`，focus 也保持无边框（光标闪动即聚焦指示）。重字重（760）、极小内边距（`2px 0`）。取自 `CoreSessionTitleEditor.vue`。
2. **小字输入**（control area）：2 行行高起步，随输入增高到最高 5 行，超出 5 行后 `overflow:auto` 滚动；`resize:none`（不可拖拽）；`width:100%`（不横向拓宽）；`white-space:pre-wrap` 自动换行。背景 `color-mix(--theme-control-background 70%)`，文字 `--theme-control-text`，边框 `control-text 12%`。
3. **常规输入框**（control area）：单行表单控件，同小字输入的背景/文字/边框配方。

**输入框不做聚焦态**：光标闪动即聚焦指示，不加边框/outline（覆盖全局 `:focus-visible`）。

### 下拉 / select / popover（control area）
单一配方：触发器 `--radius-sm`、菜单 `--radius`、item `--radius-sm`、`--z-popover`、`--shadow-md`。`UiSelect` 为唯一可复用原语，`WfSelect`/composer-menu 须收敛至此。

**选项行高亮 = 行式**：无圆角遮罩（`border-radius:0`），hover/active 背景层用 `::before` 伪元素 + `mask` 左右渐隐（`--row-fade`，两端 alpha 0.2），行间 `gap: var(--space-1)` 留间距。只有 hover/active 的背景层渐隐，文字始终完整。

### 按钮（control area）
统一变体 primary / secondary / ghost / danger × sm / md。`--radius-sm` · disabled `opacity:.45`。hover 机制：中性变体（secondary/ghost）用 `--alpha-*`；彩色填充按钮（primary/danger）用 `filter: brightness(.94)`，不混用。
- **primary**：填充 `--theme-control-background`、文字 `--theme-control-text`（跟主题联动，不用 `--blue`）。
- **danger**：`--red` 语义色（固定）。

### 悬停 / 选中态
统一规则 + `--alpha-*` token，hover → active 恒 +4pp。部分组件（settings-nav）当前把 hover 与 active 合并为同值——规范后须区分。

### 滚动条
复用 `base.css` 全局样式，不另做：`*::-webkit-scrollbar` 8px、透明轨道、thumb `color-mix(--theme-main-text 18%)` + `border-radius:999px` + `background-clip:content-box`、hover 加深到 34%。

## 硬禁令

- 禁止 control 控件误用 `--theme-main-text` 而非 `--theme-control-text`
- 禁止直接用静态 `--panel/--line/--text` 绕过主题层
- 禁止 hardcode 主题色值（如 `#2c2c2b`）而非引用 `--theme-*-background`
- 禁止新建本地命名空间（如 `--fb-*` / `--xxx-radius`）平行于主题层
- 禁止语义色挂到 theme area（应保持固定）
- 禁止 off-scale 圆角（5/7/9/10/11/14px），必须用 `--radius-*`
- 禁止硬编码 z-index（180/200/100 等），必须用 `--z-*`
- 禁止第二个下拉 / button 原语
- 禁止覆盖输入框 focus 为 outline:none 之外的聚焦态（输入框无聚焦态，光标即可）
- 禁止动效无 `prefers-reduced-motion` 回退

## 审计

审计存量碎片化：运行 `node .agents/skills/lam-design-spec/scripts/audit.mjs`。脚本扫描 `core/ui/src/styles/*.css` 与 `core/ui/src/components/*.vue`，报告 off-scale 值与违例。**不自动改代码**，供手动逐项收敛。

### 最严重存量违例（优先收敛）
- `FolderBrowserDialog.vue` 的 `--fb-*` 本地命名空间（平行主题层）+ `z-index: calc(var(--z-modal-backdrop,80)+3)`
- `UiSelect.vue` 与 `WfSelect.vue` 双下拉原语（须收敛为单一配方）
- `FloatingApprovalCard.vue` 的 bespoke shadow + `z-index:200`（忽略 z 标尺）
- `archive/members/writer/frontend/src/styles/components.css` 孤儿文件（引用不存在的子目录，且未被 import；member 已归档，此项不再需要收敛）

### 值→token 映射（收敛时参考）
- `6px` → `var(--radius-sm)` · `12px` → `var(--radius)` · `18px` → `var(--radius-lg)` · `22px` → `var(--radius-xl)`
- `8px` hover → `var(--alpha-hover)` · `12%` active → `var(--alpha-active)`
- `z-index:180` → `var(--z-popover)` · `z-index:200` → `var(--z-modal)` 或 `--z-toast`
- bespoke shadow → `var(--shadow-sm/md/lg)` 按场景选

## 与 impeccable 分工

- `impeccable` = 通用的"如何设计/审计/打磨"引擎，动作导向（craft/shape/audit/polish），读 `PRODUCT.md`。仅在从零的新设计时介入。
- `lam-design-spec` = LamTools 设计语言的唯一真源（what，非 how），约束导向。
- 二者可同时触发：新组件设计时 impeccable 定方向，本 skill 约束落在 token 与配方内。
