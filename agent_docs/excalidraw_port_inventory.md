# Excalidraw 移植：原版能力与宿主边界

用户：“放手去做吧” + 按照此前确定的原版能力不减目标，移植 Obsidian Excalidraw 并用它检验 Sunday 插件架构。

上游：zsviczian/obsidian-excalidraw-plugin，manifest 2.29.0，提交 5e4c83f6370f93d3f794ef7afb9545a6b6208c11。仓库 LICENSE 是 AGPL-3.0，package.json 的 MIT 标记与其冲突；按 AGPL-3.0 对待原插件，保留许可证、版权和对应源码，分发前检查具体义务。上游画布是定制的 @zsviczian/excalidraw 0.18.144，而不是任意版本的通用画布。

| 原版能力 | 原版实现 | 依赖的宿主 | 移植方向 / 待验收 |
| --- | --- | --- | --- |
| 创建、打开、编辑和自动保存画图 | ExcalidrawView、ExcalidrawData、定制画布 | 视图、文件库、事件、存储 | 优先复用原实现；实测创建、关闭、重开及并发保存 |
| Markdown 保存、压缩、文本和元数据 | ExcalidrawData | 文件库及元数据缓存 | 用上游真实文件往返对照，保留额外文本 |
| 绘图工具、图片、字体、笔、导出 | 定制画布、导出与字体管理 | 浏览器、文件、字体、主题 | 用原始组件、样式及资源；验证图片和 PNG/SVG |
| 设置、模板、自动导出 | core/settings、settingsDefaults | 设置、文件库、命令、调度 | 保留原版设置与默认值；验证持久化和导出 |
| 内部链接、拖放、预览和反向链接 | ExcalidrawView、EventManager、MarkdownPostProcessor | 文件库、文档、链接索引、窗口 | 需对应宿主功能；逐项对照原版 |
| 图嵌入 Markdown、文档嵌入画布、块引用 | MarkdownPostProcessor、嵌入处理器 | Markdown 渲染、元数据、文件库 | 双向嵌入及链接变化按原版验收 |
| 画布自动化和脚本库 | ExcalidrawAutomate、Scripts、ea-scripts | 命令、文件库、权限、脚本运行 | 保留接口与本地脚本；逐项验证能力与边界 |
| OCR、LaTeX、SVG、外部集成 | utils、extras、script integrations | 外部服务、其他 Obsidian 插件 | 区分独立能力和原版服务依赖；不得伪造成功 |
| 原生命令行与回执 | ExcalidrawCLI | Obsidian CLI、运行中的视图 | 对照命令、参数、读回与出错回执 |
| 插件启停、多个页面、事件和清理 | core/main、各 manager | 生命周期、workspace、窗口 | 验证重启、关闭、更新和资源释放 |
| 快捷命令及快捷键 | CommandManager | 命令面板、热键、活动视图 | 对照完整注册表；无宿主支持则列缺口 |

此表为实现前清单，不代表任何项目已经移植或验证。分发版本必须同时核实包含的定制画布及第三方依赖许可证。验收限定桌面端和代码方法，不使用 Computer Use。

## 目前进展与验收边界

- 上游在 Node 24.15.0 下通过 `npm ci` 和 `npm run build`（上游构建前自动运行 host contract 测试）。产物 `dist/main.js` SHA-256 `f1fe4f59d7f9847f39d4bee7b87658ac96adced73fd23e6f58c6422525cc0350`，`dist/styles.css` SHA-256 `cabd7e32c71e41dca2cbaff8bb7f4f06b27417901da143d88608d4c7175a8284`；产物是原版 Obsidian 插件，不是 Sunday 插件。
- 原版 PackageManager 解压并动态执行画布；脚本引擎通过 AsyncFunction 运行用户脚本。Sunday 桌面 CSP 当前不允许动态执行。需要设计适当隔离及资源构建，不能单纯放开整个宿主的执行策略，也不能声称脚本引擎已可用。
- 文件库适配 `plugins/excalidraw/vault.py` 已经通过 Sunday 正式插件操作挂载，覆盖原样往返、外部修改冲突、越界路径和创建/删除冲突；检查与替换之间其他进程的极小竞态仍未消除。
- 定制画布与原版场景读取代码已静态打包；开发版通过 Sunday 安装入口，在真实后端完成绘制、保存及重开。普通和压缩 Markdown 支持基础图形、普通文字、HTTP(S) 元素链接以及插件创建的本地图片附件；复杂工作区链接、其他附件形式和无法辨认的索引仍只读，具体限制见 `ui/src/document.mjs`。自动保存和浏览器本地草稿恢复已实测，本地缓存容量受浏览器限制。
- 原版需要 Obsidian 的视图、事件、文件库、元数据与 Markdown 扩展；Sunday 页面接口目前仅有 RPC、样式及生命周期。设置、复杂嵌入、脚本、自动化和完整原版对照验收均尚未完成。不能以基础画布代替完整移植。

<!-- user:“该修就修，不用停下”+(桌面资源策略允许插件字体和画图使用的临时图片，相关浏览器测试验证加载)。 -->
桌面内容策略增加本地后端字体及 blob 图片来源；A9 已重建、安装并确认程序内含新策略。原版的 PNG/SVG 导出及本地中文字体已在代码驱动浏览器中验证。
