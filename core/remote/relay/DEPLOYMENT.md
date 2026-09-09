# LamTools Relay 部署与数据运维

Relay 只保存控制面数据：账号、Node、Workspace、授权、短期会话和
Connection Ticket。项目、会话正文、消息、文件和 Agent 内容仍在
Workspace Host 的本地 Core，不会进入 Relay 数据库。

## Docker 部署

准备一个已经解析到服务器公网 IP 的域名，并确保安全组和防火墙开放
TCP `80`、`443`。在 `core/` 目录执行：

```bash
export LAMTOOLS_DOMAIN=relay.example.com
docker compose up -d --build
curl -fsS "https://${LAMTOOLS_DOMAIN}/healthz"
```

`caddy` 负责自动申请和续期 HTTPS 证书；反向代理会原样支持 WebSocket
升级，因此客户端使用 `wss://relay.example.com/v1/relay/connect`。Relay
容器只在 Docker 网络中暴露 `8787`，公网入口是 Caddy 的 `443`。

Compose 默认使用固定的 `lamtools/server:0.1.0` 和 `caddy:2.10.2-alpine`
标签，不要在生产环境改成 `latest`。`lamtools-server` 以 UID/GID
`10001` 的非 root 用户运行，数据写入 `lamtools_data` 的 `/data`。

首次创建账号时可暂时保持 `REGISTRATION_MODE=open`。完成初始账号创建后，
设置 `REGISTRATION_MODE=closed` 并重建服务：

```bash
export REGISTRATION_MODE=closed
docker compose up -d
```

注册关闭只影响新用户，已有账号的登录、刷新和已注册设备不受影响。

## 一致性备份与校验

Relay 数据库使用 SQLite WAL。不要在服务运行期间直接复制
`lamtools.db`，因为已提交事务可能仍在 `lamtools.db-wal` 中。镜像内置
SQLite online backup API 命令，从运行中的数据库读取一致性快照，并同时
写出只包含校验元数据的 `manifest.json`：

```bash
docker compose exec lamtools-server \
  /usr/local/bin/lamtools-relay backup \
  --database /data/lamtools.db \
  --output /data/backups/$(date +%Y%m%d-%H%M%S)

docker compose exec lamtools-server \
  /usr/local/bin/lamtools-relay verify \
  --backup /data/backups/20260909-120000
```

备份目录包括：

```text
lamtools.db       # 控制面数据及数据库内的 server identity
manifest.json     # server_id、schema_version、大小和 SHA-256
```

备份数据库包含用于保持 `server_id` 不变的服务端私钥，因此必须按生产
凭据保护。`manifest.json` 不写入密码、Access/Refresh Token 或私钥；
账号密码只以哈希存在数据库中。`backup` 默认不覆盖已有目录，确认替换
时才使用 `--force`。

也可以只校验当前数据库：

```bash
docker compose exec lamtools-server \
  /usr/local/bin/lamtools-relay verify \
  --database /data/lamtools.db
```

## 恢复与迁移

恢复必须先停止 Relay，避免运行中的连接继续写入数据库。使用 Compose
默认命名卷时，先停止服务，再用一次性 root 容器替换数据库；下面的卷名
来自本文件顶层 `name: lamtools`：

```bash
docker compose stop caddy lamtools-server

docker run --rm \
  -v lamtools_data:/data \
  -v "$PWD/backup/20260909-120000":/restore:ro \
  debian:12.11-slim \
  sh -c 'cp /restore/lamtools.db /data/lamtools.db && rm -f /data/lamtools.db-wal /data/lamtools.db-shm && chown 10001:10001 /data/lamtools.db'

docker compose run --rm lamtools-server \
  /usr/local/bin/lamtools-relay verify --database /data/lamtools.db
docker compose up -d
```

迁移到另一台机器时，迁移整个 `/data` 内容（或先用上面的在线备份），
不要只迁移某一个 WAL 文件：

1. 在旧机生成并校验备份。
2. 停止旧机 Compose，保存原有 `lamtools_data` 和 Caddy 数据卷。
3. 在新机使用相同的 `DATABASE_PATH=/data/lamtools.db` 恢复数据库。
4. 启动新机并校验 `/healthz`、账号登录和设备连接。
5. 确认 `server_id` 与旧机一致后，再把 DNS 切换到新机。

`server_id`、服务端密钥、账号、Node、Workspace 和授权关系都由
`lamtools.db` 的 `server_config` 等表持久化；只要恢复同一个数据库，
设备不需要因为换机器而重新建立服务端身份。Caddy 的证书数据在
`lamtools_caddy_data`，可一并迁移，也可以让 Caddy 在新机重新签发。

## 升级与回滚

当前数据库 schema version 为 `1`，对应 `lamtools/server:0.1.0`。以后
每个需要改表的版本必须增加版本化 migration，并同步提升镜像版本；
启动时 migration 失败应保持服务未 ready，不能带着半完成 schema 对外
提供 Relay。

升级流程：

1. 用 `backup` 生成并校验一个带时间戳的备份目录。
2. 修改 Compose 中的固定镜像标签，先构建/拉取新镜像。
3. `docker compose up -d`，等待 `lamtools-server` healthcheck 通过。
4. 检查日志、`/readyz`、账号登录和一条 Relay 长连接。

如果 migration 失败或新版本行为异常：

1. 停止新版本容器。
2. 将镜像标签改回旧版本。
3. 若新版本已经写入不可逆 schema，先按“恢复与迁移”恢复升级前备份。
4. 用 `verify --database` 校验后再启动旧版本。

不要只回滚镜像而保留一个旧版本无法读取的新 schema；数据库恢复和镜像
回滚必须使用同一份经过验证的版本配对。
