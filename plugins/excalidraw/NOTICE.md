# 上游来源与许可

- 画布与样式来自 `@zsviczian/excalidraw` 0.18.144 的 `dist/obsidian/excalidraw.production.min.js` 和 `.css`，它是 Obsidian Excalidraw 2.29.0 指定的画布版本。其包标记为 MIT，许可见 `EXCALIDRAW-LICENSE`；源码：https://github.com/zsviczian/excalidraw 。
- Obsidian 插件上游提交 `5e4c83f6370f93d3f794ef7afb9545a6b6208c11`，仓库许可证为 AGPL-3.0（见 `OBSIDIAN-PLUGIN-LICENSE`）；package.json 标记 MIT 与其不一致。当前开发版尚未包含该插件的完整实现，不能视为完整移植或正式分发。
- `ui/page.mjs` 将上游原版画布与 React、ReactDOM 和宿主适配代码静态打包。打包时为画布提供原版需要的 React 词法引用；未修改上游画布运行时代码。运行时代码与依赖的完整许可及对应源码需在分发前核验和附带。

- `vendor/excalidrawMarkdownParsing.ts` 和 `vendor/sceneDataUtils.ts` 为上游提交的原始文件；`ui/src/upstream-markdown.mjs` 由其中的原版解析和压缩函数构建。遵守随附的 AGPL-3.0。
- `vendor/ExcalidrawData.ts`、`vendor/excalidrawSceneUtils.ts` 为上游原始文件；`ui/src/upstream-markdown-writer.mjs` 提取并编译上游 Markdown 写入及元素 ID 更新方法。
- `ui/mermaid.mjs` 静态打包原版 Extras 要求的 `@excalidraw/mermaid-to-excalidraw` 2.2.2；MIT，许可见 `vendor/MermaidToExcalidraw-LICENSE`。其依赖许可证仍须在正式分发前完整核验。
- `vendor/constants.ts` 保留原版源码；原版 Markdown 文件头和压缩写入函数从固定提交提取构建。
