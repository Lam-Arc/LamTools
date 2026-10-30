# 样式体系说明书

日期：2026-10-29
范围：`core/ui/src` 的全局样式、主题令牌、动效与控件；官网与插件页面不在内。

## 一、分几层，谁管谁

| 层 | 位置 | 职责 |
|---|---|---|
| 令牌 | `styles/variables.css` | 颜色、字阶、间距、圆角、阴影、层级、动效、图标、焦点环 |
| 主题 | `helpers/theme.ts` + `useShellLayout.ts` | 生成四区域底色/文字/玻璃/图片变量，写到根节点 |
| 基础 | `styles/base.css` | 重置、输入框、滚动条、焦点环、减弱动效 |
| 基础件 | `styles/sunday-controls.css` | 按钮、开关、分段、滑块、进度 |
| 外壳 | `styles/workspace-shell.css`、`session-sidebar.css`、`layout.css` | 左栏、主区、输入栏、抽屉 |
| 功能面 | `core-settings-*.css`、`library-surface.css`、`study.css`、`plugin-editor-*.css` | 设置、资料库、学习、插件管理 |
| 消息 | `chat-thread-*.css` | 线程、消息部件、工具行（全局作用域） |

加载顺序：`variables → base → layout（内嵌 optical-glass、workspace-shell、session-sidebar）→ theme-editor → library-surface → sunday-controls`。设置、消息、插件、资料库等分片由各自组件 `src` 引入，顺序即层叠顺序。

## 二、谁控制哪类样式

| 控制点 | 管哪类样式 | 应用位置 |
|---|---|---|
| `themeToCSSVars()` `helpers/theme.ts` | 四区域底色与文字、边框、玻璃滤镜、图片适应方式 | 根节点，全站表面 |
| `useShellLayout.ts` 的 watch | 把主题变量写到根节点，标题栏尺寸 | 外壳 |
| `variables.css` | 字阶 `--type-*`、间距 `--space-*`、圆角、阴影、层级 `--z-*`、动效 `--dur-*`/`--ease-*`、图标 `--icon-*`、焦点环 `--focus-ring-*` | 全站 |
| `base.css` | 元素级重置、输入框配方、滚动条、键盘焦点、减弱动效 | 全站 |
| `sunday-controls.css` 的 `.btn` | 五个角色：`btn--secondary/primary/quiet/ghost/danger` | 全站按钮 |
| `sunday-controls.css` 的 `.sunday-switch/segmented/range/progress` | 控件几何与交互态 | 设置页、更新卡 |
| 局部 `--text` 重绑 | 组件内文字色跟随所在区域 | 五十个文件 |
| `--settings-*` | 设置页表面色，三级回落 | 设置页及主题编辑器 |
| `optical-glass.css` | 浮层玻璃材质 | 侧栏卡片、浮层 |
| `motion/presets.ts` | 入场、弹出、形变、展开、离场参数 | 全站动效 |

## 二点五、主题区域的颜色与玻璃

每个区域（backdrop / main / composer / control）有两个独立节点：

**填充节点**（区域里放什么）：

| 样式 | 存储 | 编译结果 | 可用编辑项 |
|---|---|---|---|
| 纯色 | `<area>Fill = solid` + 首节点颜色 | `rgba(...)`（玻璃开启时换成材质浓度） | 颜色、透明度 |
| 渐变 | `<area>Fill = gradient` + `stops/angle` | `linear-gradient(...)` | 节点、角度、透明度 |
| 图片 | `<area>Fill = image` + `<area>Image/<area>ImageFit` | 首节点颜色垫底 + `--theme-<area>-image` 图片层 | 选图、底色、清除、适应方式 |

**玻璃偏好**（区域表面是什么材质）：

- 存储：`<area>Glass = off | high | low`，默认 `off`；与填充分开，不是一种填充类型。
- 开启后整个区域变成玻璃表面：主表面消费 `--theme-<area>-glass-filter`，填充的颜色/渐变/图片按材质浓度着色（高透 22%、低透 58%，与 `--optical-glass-fallback-tint` / `--optical-glass-low-trans-fallback-tint` 同值），透明度滑杆收起。
- 图片 + 玻璃：图片层上方再盖一层同色薄雾（`linear-gradient(同色, 同色), url(...)`），图片仍是原始 data URL。
- 玻璃关闭时该变量为 `none`，不产生额外合成层。

- 图片按原始 data URL 保存，GIF/WebP/APNG 动图照常播放；格式按文件头识别，单张上限 1.5MB。
- 主表面必须同时消费 `--theme-<area>-image`、`-image-size` 与 `-image-repeat`，否则 `background` 简写会把图片层与适应方式重置掉。

## 三、动效清单与复用等级

| 动画 | 位置 | 参数 | 复用等级 |
|---|---|---|---|
| 从触发点形变长出 | `motion/presets.ts` 的 `enterMorph` | 0.62 秒，`back.out(1.2)`，起点压到触发件大小 | 最高 |
| 原路缩回 | `leaveMorph` | 0.34 秒，`power3.in`，透明度降到 0.3 | 高 |
| 遮罩淡入淡出 | `enterScrim` / `leaveScrim` | 0.26 秒淡入，0.3 秒淡出 | 高 |
| 菜单弹出 | `motion/composerMenu.ts` | 0.32 秒，位移 10 加缩放 0.95；子项 0.22 秒错开 0.045 | 高 |
| 淡入上移 | `enterFade` | 0.22 秒，位移 8，`power2.out` | 高 |
| 面板展开折叠 | `motion/expandPanel.ts` | 展开 0.24 秒，收起 0.2 秒 | 中 |
| 减弱动效退化 | `shouldSkipMotion()` | 全部瞬时切换 | 必用 |

新增浮层一律用 `enterMorph` 或 `enterFade`，不要再写内联 GSAP 参数。减弱动效的判断只走 `shouldSkipMotion()`。

## 四、当前边界

- 消息渲染样式是全局作用域，因为消息体由 HTML 字符串注入，不能改成 scoped。
- 官网 `website/src/styles/sections.css` 是独立体系，不引用任何 `--theme-*`。
- 插件页面是独立文档，只通过 CSS 变量继承外壳主题。
- 空态 46 个类名、卡片 85 个类名、列表行 12 种仍有区域专用布局，未做单一基础件：这三类在不同区域是横排、居中、卡片三种不同意图，合并需要逐屏视觉验收。

## 五、可编辑元素注册表

可视化编辑器不能从任意 DOM 推断可编辑能力，因此每个允许编辑的元素都要先登记。

- 命名：`区域.名称`，例如 `shell.composer`、`chat.message`；全表唯一，格式由测试校验。
- 落点：标识写在组件根节点，形如 `data-ui-id="shell.composer"`，不挂在内部子节点上。
- 清单：`core/ui/src/uiRegistry/registry.ts`，每条记录拥有者组件、父级、可编辑属性与保护级别。
- 级别：`editable` 可改外观与尺寸；`appearance-only` 只改外观；`protected` 不允许改。
- 校验：`core/ui/tests/ui-registry.test.ts` 检查唯一性、父级存在、无环、组件确实挂了标识、保护级别与属性不矛盾。

新增可编辑元素时先改清单，再在组件根节点挂标识，最后跑这条测试。标识一旦发布不要改名，改名属于主题迁移，需要走版本升级。
