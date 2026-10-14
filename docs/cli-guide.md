# LamTools CLI 使用指南

本文按当前源码整理 Core 维护命令。所有示例默认在仓库根目录执行（即包含 `core/`、`scripts/` 的目录）；如果已把仓库根目录加入 PATH，可省略 `.\`。

> Member 产品（Writer / Sage / Imager）已归档至 `archive/members/`，其 CLI 命令不再维护。以下仅保留 Core 入口。

## 编码与运行前提

- PowerShell 中传递中文长任务时，优先直接作为参数传入；不要用管道或 here-string 传任务正文，避免编码污染。
- 后端未启动时，先用 `.\lamtools.cmd dev core backend` 启动 Core 后端。

## Core 维护命令

### 启动开发服务

Core API 默认只信任回环连接。直接绑定 LAN 地址必须显式启用 `serve --allow-lan`
并配置 `LAMTOOLS_CORE_API_TOKEN`；所有 HTTP/WebSocket 请求均需 Bearer 认证。
桌面远程连接继续使用原有网关。配置、TLS 与信任边界见
[Core API access](../core/docs/core-api-access.md)。

主入口：

```powershell
.\lamtools.cmd dev all
.\lamtools.cmd dev core all
.\lamtools.cmd dev core frontend
.\lamtools.cmd dev core backend
.\lamtools.cmd dev core all --open
```

兼容入口：

```powershell
.\scripts\dev.ps1 all
.\scripts\dev.ps1 core frontend
.\scripts\dev.ps1 core backend
```

端口来自 `scripts/ports.json`：

| 组件 | 后端 | 前端 dev |
|---|---:|---:|
| core | 5172 | 5173 |

### 构建

```powershell
.\lamtools.cmd build all
.\lamtools.cmd build core

.\scripts\build.ps1 all
.\scripts\build.ps1 core
```

### 测试

```powershell
.\lamtools.cmd test all
.\lamtools.cmd test core

.\scripts\test.ps1 all
.\scripts\test.ps1 core
.\scripts\test.ps1 all -Serial
```

默认同时执行完整 Core 后端 pytest 和 Core UI contract 测试；输出带组件前缀，保留所有失败详情，并显示各套件及总耗时。任一套件失败，命令返回非零退出码，另一套件仍完成执行。`-Serial` 执行相同测试，供排查资源竞争或比较耗时。

该入口不包含 CI 的类型检查、构建、移动端/Rust 测试或发布验收；这些检查仍由原有 CI 和发布流程执行。

### 打开与诊断

```powershell
.\lamtools.cmd open core
.\lamtools.cmd doctor all
.\lamtools.cmd doctor core --json
```

`open` 读取 `scripts/ports.json`，不要求用户记端口；`doctor` 检查 Python/Node/npm、Core 目录、根 CLI、Core 数据库目录和前端 dev server。

### 数据维护

一次性维护命令，默认只读预览（dry-run），`--apply` 才写入：

```powershell
cd core
py -3.14 -m lamtools_core.cli maintenance strip-snapshot-images
py -3.14 -m lamtools_core.cli maintenance strip-snapshot-images --apply
```

- 作用：剥离"读取不可见"的历史图片副本——会话元数据行登记表里的图片、以及条目行 / 事件流水 / 同步变更表三处载荷元数据里的同一份图片 base64（新写入早已不再记录；历史行会在会话下次自然写入时惰性瘦身，本命令一次性处理全部）。
- 只允许指向本机开发数据目录（`<repo>/data`）；安装版（绿色/便携或用户级）数据目录一律拒绝（退出码 2），不会写入任何内容。
- `--apply` 先做文件级备份到 `<data>/backups/strip-snapshot-images-<UTC 时间戳>/`（数据库文件 + 记录摘要的 `manifest.json`），再在单个写事务里改写，随后逐会话校验：改写后的行必须只少掉被剥离的死键，且真实读取器组装出的会话状态与剥离前逐字节相同（这些键本就在装载时被丢弃，所以装载结果必须完全一致）。最后打印迁移前后体积。命令可重复执行：已干净时报告 `already_clean`，不会产生第二次备份。
- 只剥离上面这些读取不可见的副本；条目里的渲染副本（`artifacts[].metadata.image_data_url`）与模型可见的历史正文一律不动（剥离会改变读取语义）。结果以单行 JSON 输出，含每会话明细与各表回收字节。被回收的空间先进入数据库空闲页（文件大小不变），除非另行执行 `VACUUM`。

## 推荐命令形态

面向日常使用，优先记住以下入口：

```powershell
.\lamtools.cmd dev core all      # 启动 Core 前后端
.\lamtools.cmd test core         # 运行 Core 测试
.\lamtools.cmd doctor all        # 诊断本地环境
```
