# 署名与来源

本插件是腾讯官方 DSH 插件 `@tencent-connect/dsh-qqbot` 0.5.3 的行为移植，固定上游提交 `d998f72`。

## 上游

- **dsh-qqbot 0.5.3**：MIT License，Copyright (c) 2026 Tencent Connect。
  来源：https://github.com/tencent-connect/dsh-qqbot
- **@tencent-connect/qqbot-nodejs 1.0.5**：MIT License，Copyright (c) 2026 Tencent。
  本插件按其公开协议行为重写了令牌、REST、WebSocket 网关、流式消息和媒体上传；未随包分发 Node 源码。
- **@tencent-connect/qqbot-connector 1.2.0**：包声明为 UNLICENSED。
  本插件未复制其源码；扫码绑定按公开的 q.qq.com 端点与 AES-256-GCM 载荷格式重写。

## 第三方组件

- **qrcode 8.2**：BSD License，Copyright (c) 2011 Lincoln Loop。
  位于 `vendor/qrcode/`，许可证原文见 `vendor/qrcode/LICENSE`。

## 保留的原版资产

- 界面样式类与布局参数来自上游 `src/client/bind-page.ts` 和 `src/client/config-panel.ts`，在 `ui/style.css` 中按 LamTools 主题变量重新映射。
- 命令文案、帮助分组、按钮文案、审批/提问提示语按原版保留。
