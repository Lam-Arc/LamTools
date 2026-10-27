# qq-bot（QQ 机器人）0.1.0 · LamTools

移植自腾讯官方 DSH 插件 [`@tencent-connect/dsh-qqbot` 0.5.3](https://github.com/tencent-connect/dsh-qqbot/tree/d998f72)，固定提交 `d998f72`。原版是 Node/TypeScript + DSH 宿主；本插件保留其协议行为、命令、审批/问答、富媒体和扫码绑定能力，宿主侧改为 Python + LamTools 子代理运行器。

## 使用

1. 在插件页启用「QQ 机器人」，打开左侧「QQ 机器人」页面。
2. 用手机 QQ 扫码，或手动填写 QQ 开放平台的 AppID / AppSecret。
3. 绑定成功后网关自动连接；在 QQ 私聊或群里 @ 机器人即可对话。
4. 在「设置」里调整访问控制、模型、提示词、富媒体、视觉和附件发送。

数据保存在插件自己的 `data/`：`config.jsonc`、`prefs.json`、`media/`、`logs/qqbot.log`、`gateway-session.json`。升级和默认卸载保留数据。

## 能力

- **QQ 官方 Bot 协议**：访问令牌、WebSocket 网关（identify / resume / 心跳 / 重连）、私聊与群聊消息、按钮交互、C2C 流式消息、主动消息。
- **上游 14 个中间件位置**：回声/去重、访问控制、群历史缓冲、@ 门控、内容清洗、限流（默认关闭，与原版一致）、待答问题截获、并发合并、输入状态、引用解析、附件下载、上下文组装。
- **9 个上游聊天指令 + 4 个增强指令**：`/new`（`/reset` `/clear`）、`/compact`、`/model`、`/preset`、`/stop`、`/bot-ping`、`/bot-version`、`/bot-status`、`/bot-help`；额外提供 `/fork`、`/history`、`/cost`、`/export`。
- **持久会话**：一个私聊/群聊对应一个稳定的子代理会话，历史由宿主状态库保存；闲置回收只释放内存。
- **审批与提问**：宿主 `pending_approval` 自动转成 QQ 按钮；允许后 `resume_approved`，拒绝/超时/取消通过 `resume_question` 清理挂起状态。
- **流式输出**：私聊 `stream_messages`，失败自动降级静态消息；群聊始终静态。
- **富媒体**：图片/视频/文件下载（HTTPS + SSRF + 大小 + 超时）、TTL 清理、扩展名分类发送、5MB 以上分片上传。
- **工具**：`qqbot_send_file`、`qqbot_describe_image`、`qqbot_status`、`qqbot_bind_start`。
- **扫码绑定**：q.qq.com 绑定任务、轮询、AES-256-GCM 解密、二维码 SVG。
- **凭据保护**：AppSecret 存入宿主按插件隔离的密钥库（Windows DPAPI），旧版明文配置在启动时自动迁移并清除；AppID 仍保留在配置里。
- **界面**：导航页面 + 独立窗口 + 右侧区域，复用原版 `imqb-*` / `imqb2-*` 样式类；配置同时提供宿主 schema 表单。

## 代码

```
backend/__init__.py       宿主后端入口（create_plugin）
qqbot/protocol.py         令牌、REST、WebSocket 网关、流式、媒体上传
qqbot/middleware.py       入站中间件与五层消息组装
qqbot/agent_bridge.py     子代理运行器、审批/问答续跑、宿主预设/提示词流水线
qqbot/outbound.py         宿主事件 → QQ 消息、工具结果、交付文件
qqbot/channels.py         审批/问答按钮通道
qqbot/media.py            下载、SSRF、清理、发送
qqbot/binding.py          q.qq.com 扫码绑定
qqbot/runtime.py          生命周期、入站管线、命令、RPC 状态
ops.py / tools.py         操作与模型工具
ui/                       页面、窗口、区域与样式
vendor/qrcode/            二维码渲染（BSD，见 LICENSE）
```

## 验证

- 插件测试 43 项通过：协议、中间件、审批/问答、扫码解密与状态机、网关握手、出站路由、宿主装配、操作、工具、会话分叉与历史、凭据密钥库。
- 宿主新增能力测试 41 项通过：预设组合/来源覆盖、提示词顺序/替换/异步拒绝、运行器应用预设、模型目录、子会话压缩/分叉/历史、通用聊天通道、外部进程插件运行时、插件密钥存储、插件 HTTP 路由、交付物事件。
- 真实 q.qq.com 绑定任务创建成功并渲染二维码 SVG；未扫码，因此没有真实凭据，网关连接和真实收发消息未验证。
- 通过宿主生命周期启动/停止后端：`state=ready`、健康检查通过、扫码状态 `waiting`、停止后任务清理。
- 未验证：真实 QQ 消息收发、真实模型回合、视觉模型调用、分片上传、UI 视觉验收。

详细差异见 [差异表](差异表.md)。

## 许可

本体 MIT（`LICENSE`，Tencent Connect）。协议行为参考 MIT 的 `@tencent-connect/qqbot-nodejs` 1.0.5；扫码连接器 `@tencent-connect/qqbot-connector` 为 UNLICENSED，未复制其源码，仅按公开端点重写。二维码渲染使用 BSD 许可的 `qrcode` 8.2，许可证见 `vendor/qrcode/LICENSE`。完整署名见 [NOTICE.md](NOTICE.md)。
