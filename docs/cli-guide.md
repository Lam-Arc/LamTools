# LamTools CLI 使用指南

本文按当前源码整理 Core 维护命令。所有示例默认在仓库根目录 `E:\LamTools` 执行；如果已把仓库根目录加入 PATH，可省略 `.\`。

> Member 产品（Writer / Sage / Imager）已归档至 `archive/members/`，其 CLI 命令不再维护。以下仅保留 Core 入口。

## 编码与运行前提

- PowerShell 中传递中文长任务时，优先直接作为参数传入；不要用管道或 here-string 传任务正文，避免编码污染。
- 后端未启动时，先用 `.\lamtools.cmd dev core backend` 启动 Core 后端。

## Core 维护命令

### 启动开发服务

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
```

### 打开与诊断

```powershell
.\lamtools.cmd open core
.\lamtools.cmd doctor all
.\lamtools.cmd doctor core --json
```

`open` 读取 `scripts/ports.json`，不要求用户记端口；`doctor` 检查 Python/Node/npm、Core 目录、根 CLI、Core 数据库目录和前端 dev server。

## 推荐命令形态

面向日常使用，优先记住以下入口：

```powershell
.\lamtools.cmd dev core all      # 启动 Core 前后端
.\lamtools.cmd test core         # 运行 Core 测试
.\lamtools.cmd doctor all        # 诊断本地环境
```
