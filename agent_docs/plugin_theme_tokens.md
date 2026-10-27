# 插件 UI 主题接入的架构问题（一类问题）

日期：2026-10-25
范围：`core/ui` 主题输出、插件页面装载器、`network-exploration` 自绘页面。

## 结论

插件页面和宿主在同一个文档里，**CSS 变量可以直接继承**，不需要额外的主题桥接层。网络插件现在直接读取：

- `--theme-main-background` / `--theme-main-text`
- `--theme-main-border`
- `--theme-main-soft-background` / `--theme-main-subtle-background` / `--theme-main-sunken-background`
- `--theme-composer-*` / `--theme-control-*`
- `--font-sans`
- `--space-*` / `--radius-*` / `--dur-*` / `--ease-*`

所以亮色、暗色和换主题时，插件的页面底色、文字、边框、字体、间距都能跟着宿主走。

## 缺口一：没有语义强调色 token

宿主主题只导出“表面/文字/边框”，没有导出“强调色”：

- 有：`--green`、`--blue`、`--orange`、`--purple`、`--red`，但它们是固定的全局色，不随主题变化。
- 没有：`--theme-accent`、`--theme-accent-ink`、`--theme-success`、`--theme-danger`、`--theme-warning`。

影响：插件可以把背景和文字接到主题上，但“开启/加速/选中”的强调色只能固定用 `--green`。换一个强调色不是绿色的主题时，插件表面跟随了，强调色仍然绿。

建议：宿主补一组稳定的语义 token，作为插件 UI 契约的一部分：

```css
--theme-accent: ...
--theme-accent-ink: ...
--theme-success: ...
--theme-warning: ...
--theme-danger: ...
--theme-info: ...
```

## 缺口二：插件样式只注入主文档

`plugin.system.ui` 的 `styles` 由宿主注入 `<link>`，但这只发生在主窗口文档。插件页面还可能挂在分屏/插件宿主文档里，那个文档拿不到宿主的 `<link>`，页面就会变成裸 HTML。

当前 workaround：插件把 `style.css?inline` 打进 `page.mjs`，在 `mount()` 时注入实际文档。这个方式可靠，但属于每个插件都要自己处理的事情。

建议：二选一写进插件契约：

1. 宿主在所有可能挂载插件页面的文档里都注入 `ui.styles`；或
2. 明确要求插件页面自注入样式，并提供 `?inline` 的构建约定。

## 当前网络插件的处理

- `--nx-*` 颜色全部由宿主 `--theme-*` 派生；`--nx-accent` 暂用 `var(--green)`。
- 页面样式由 `page.mjs` 自带并注入实际文档。
- 接管主区时给 `.workspace-main` 加 `nx-plugin-full`，隐藏宿主标题条/插件工具栏和内边距。
- 首页、加速、代理、下载四个入口，首页只做总览与快捷入口。

在宿主补出 `--theme-accent` 之前，这是能做到的“最接近主题”的接法。
