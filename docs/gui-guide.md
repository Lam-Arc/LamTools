# LamTools GUI 使用指南

本文按当前源码整理 Core GUI 入口。GUI 指用户可见页面或桌面窗口；后端已有但未在页面暴露的 HTTP 能力不算 GUI 入口。

> Member 产品（Writer / Sage / Imager）已归档至 `archive/members/`，其 GUI 入口不再维护。以下仅保留 Core。

## Core GUI

Core 的前端工作台即产品入口。

```powershell
.\lamtools.cmd dev core all --open
```

打开：

```text
http://127.0.0.1:5173
```

后端默认地址：

```text
http://127.0.0.1:5172
```

用途：Core 工作台基于 `@lamtools/ui` 的 WorkspaceShell、SessionSidebar、ChatThread、ComposerBar、RuntimePanel 组装，是当前唯一活跃的产品界面。

## 使用建议

- 配置模型和 Provider 优先用工作台设置页。
- 批量、自动化、诊断任务优先用 CLI。
- 不要把 `/api/core/*/messages` 当成"启动任务"入口；它只是 Core 形状的消息写入/读取接口。
