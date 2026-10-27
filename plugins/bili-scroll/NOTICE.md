# 第三方代码与署名说明

本插件（`dsh-bili-scroll` / 刷B站）本体以 **MIT** 协议发布，正文见仓库根目录的 `LICENSE`。

## 内含第三方代码

- 目录：`vendor/bilibili-mcp/`
- 项目：**bilibili-mcp**
- 许可证：**MIT**，Copyright (c) 2026 AGI_Ananas
- 完整许可见该目录下的 `LICENSE`

## 关于版权署名

`LICENSE` 第一行写的是 `Copyright (c) 2026 c1overzz`。
如果你要基于本仓库做二次分发，保留这一行和 MIT 正文即可，不必另行取得授权（MIT 本身就允许改、再发、商用）。

---
*本文件只是说明，不构成额外限制。*

## 原版前端与浏览器依赖

- `vendor/dsh-client.js`：DSH bili-scroll 2.2.2 原版前端，提交 `4af98392ee078e02f50a7fd0bf0491033f4675ed`，MIT，c1overzz。文件保留原样；`ui/src/original-adapter.mjs` 仅适配宿主注册、请求、主题别名与生命周期。
- `ui/page.mjs` 静态打包 React 18.3.1、ReactDOM 18.3.1 和 Scheduler；MIT 许可分别保存在 `vendor/React-LICENSE`、`ReactDOM-LICENSE`、`Scheduler-LICENSE`。运行时不需要另装 Node 或访问 CDN。
- `vendor/dsh-mcp.mjs`：DSH bili-scroll 2.2.2 的 `lib/mcp.mjs` 原版客户端，提交 `4af98392ee078e02f50a7fd0bf0491033f4675ed`，MIT，c1overzz；文件与上游一致。
