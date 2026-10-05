# 归档：视窗（Stage pane / 文件编辑器）

2026-10 归档。这一组组件曾是主界面右侧的「视窗」面板：文件树 + 代码编辑 +
Markdown/图片/音视频/PDF 预览 + 网址浏览。产品里每条打开路径都有了更直接的
去处之后，它不再有任何入口：

- 成果与文件 → 系统默认应用打开（`artifact.open` / 附件打开通道）；
- 图片 → 聊天消息内预览；Markdown → 聊天与资料库阅读页渲染；
- 文档编辑 → 资料库方案/记忆编辑器。

## 状态

- 组件保留在此目录，不再被任何活跃代码引用，也不参与打包（无入口即不进产物）。
- 类型随迁：`StageKind` / `StageResource` 在本目录 `types.ts`，已从共享
  `src/types.ts` 移除。
- 不维护、不修复；不要在新代码里 import 这里的任何文件。

## 若要复活

从归档恢复时需要：把组件移回 `src/components/`、类型移回 `src/types.ts`、
恢复 `src/index.ts` 的导出，并在 `WorkspaceShell`（外壳舞台区域）、
`useShellLayout`（开合与高度状态）、`LamToolsApp`（挂载与打开入口）、
`styles/layout.css` + `styles/workspace-shell.css`（几何与 reveal 变量）
里把当时移除的接线重新接上。git 历史里有完整的原实现。
