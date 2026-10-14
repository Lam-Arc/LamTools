# LamTools Relay

Relay 的应用数据通道转发 Noise 加密后的隧道帧，不保存项目、会话、消息、文件或
Agent 内容。控制面并非端到端加密：兼容六位数字 WAN 查找会把配对码、
设备公钥、网关地址和到期时间发送给 Relay，存放在进程内存中直到清理或到期。
因此 Relay 是配对目录的信任方，不能声称它不知道配对码或设备元数据。
生产模式使用现有账号认证和一次性 Connection Ticket，不使用部署级共享 Token。

环境变量：

- `DATABASE_PATH`：SQLite 数据库路径，默认 `data/lamtools.db`。
- `LAMTOOLS_RELAY_BIND`：监听地址，默认 `0.0.0.0:8787`。
- `REGISTRATION_MODE`：`open` 或 `closed`，默认 `open`。
- `LAMTOOLS_RELAY_TLS_CERT` 与 `LAMTOOLS_RELAY_TLS_KEY`：同时设置时直接启用 TLS；也可以在反向代理终止 TLS。

运行：

```text
cargo run --manifest-path core/remote/relay/Cargo.toml
```

移动端流程：

1. `POST /v1/auth/register` 或 `POST /v1/auth/login` 获取账号会话。
2. `POST /v1/nodes/register` 注册当前移动 Node，并获得设备绑定的会话。
3. `GET /v1/workspaces` 选择 Workspace。
4. `POST /v1/workspaces/{id}/connect-ticket` 获取一次性短期 Ticket。
5. 连接 `WSS /v1/relay/connect`，携带 `role=mobile`、`device_id`、`target` 和 `ticket`。

桌面 Host 使用账号绑定的 Access Token 建立长期 Relay presence，不能使用未绑定设备的账号会话。
桌面端的六位数字配对可通过 LAN、VPN 或手动网关完成，不要求账号。
现有 WAN 查找使用账号绑定的 Node 会话和短期一次性 Ticket；本次加固未新增账号系统。
详细信任边界、尝试限制、兼容性和残余风险见
[配对安全说明](../../docs/pairing-security.md)。

健康检查、指标和 presence：`/health`、`/metrics`、`/v1/presence/:device_id`。

Push 默认关闭。启用实现只能接收 `device_id`、`event_type` 和 `opaque_event_id`，不得携带对话正文。

Docker、HTTPS/WSS、在线一致性备份、恢复、迁移和升级回滚流程见
[`DEPLOYMENT.md`](DEPLOYMENT.md)。
