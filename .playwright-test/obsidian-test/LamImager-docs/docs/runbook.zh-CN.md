# LamImager 运维手册

## 快速开始

### 开发模式

```bash
# 终端 1: 后端
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 终端 2: 前端
cd frontend
npm install
npm run dev
```

访问地址: http://localhost:5173

### 生产模式

```bash
# 构建前端
cd frontend
npm run build

# 启动服务器
cd ../backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

访问地址: http://localhost:8000

---

## 健康检查

### 后端健康状态
```bash
curl http://localhost:8000/api/health
# 预期: {"status": "ok", "version": "0.4.0-alpha", ...}
```

### 数据库检查
```bash
ls -la data/lamimager.db
# 应存在且可读
```

### 前端构建检查
```bash
ls -la frontend/dist/
# 应包含 index.html 和 assets/
```

---

## 常用操作

### 重置数据库

```bash
# 先停止服务器
rm data/lamimager.db
# 重启服务器 - 表会自动重建
```

### 清理上传文件

```bash
rm -rf data/uploads/*
```

### 导出账单数据

```bash
curl "http://localhost:8000/api/billing/export" -o billing.csv
```

---

## 故障排除

### 后端无法启动

1. 检查 Python 版本: `python --version` (需要 3.14+)
2. 检查依赖: `pip install -r requirements.txt`
3. 检查端口占用: `netstat -an | grep 8000`
4. 查看日志中的错误
5. 某些 Linux 发行版可能没有捆绑 sqlite3 — 通过 `apt install python3.14-sqlite` 安装

### 前端构建失败

1. 检查 Node 版本: `node --version` (需要 18+)
2. 清理 node_modules: `rm -rf node_modules && npm install`
3. 检查 TypeScript 错误: `npx vue-tsc --noEmit`
4. 如果 vue-tsc 失败，尝试: `npx vite build` (跳过类型检查)

### API 调用 CORS 错误

1. 检查 `backend/app/config.py` 中的 `CORS_ORIGINS`
2. 确保前端开发服务器在端口 5173
3. 查看浏览器控制台中的具体 CORS 错误

### 数据库锁定错误

1. 确保只有一个服务器实例在运行
2. 检查僵尸进程: `ps aux | grep uvicorn`
3. 重启服务器

### API 密钥加密失败

1. 加密密钥从文件种子派生（`<DATA_DIR>/.encryption_seed`），首次运行自动创建
2. 迁移到新机器需要同时拷贝 `.encryption_seed` 文件和数据库
3. 查看 `app/utils/crypto.py` 中的密钥派生逻辑

---

## 日志

### 启用调试日志

在 `backend/app/config.py` 中设置:
```python
DEBUG = True
LOG_LEVEL = "DEBUG"
```

### 日志位置

- 默认: 控制台输出
- 可配置: `config.py` 中的 `LOG_FILE`

---

## 备份

### 备份数据库
```bash
cp data/lamimager.db data/lamimager.db.backup
```

### 备份上传文件
```bash
tar -czf uploads-backup.tar.gz data/uploads/
```

---

## 配置

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEBUG` | `true` | 启用调试模式 |
| `DEFAULT_IMAGE_SIZE` | `1024x1024` | 默认图片尺寸 |
| `LAMIMAGER_DATA_DIR` | `<project>/data` | 覆盖运行时数据目录 (DB, 上传文件, 日志) |
| `LAMIMAGER_STATIC_DIR` | `<project>/frontend/dist` | 覆盖静态文件目录 |

### 配置文件

位置: `backend/app/config.py`

关键设置:
- `DATA_DIR`: 运行时数据目录
- `DB_URL`: SQLite 连接字符串
- `CORS_ORIGINS`: 允许的前端来源
- `UPLOAD_DIR`: 文件上传目录

---

## 监控

### 查看月度费用

```bash
curl http://localhost:8000/api/billing/summary
```

### 查看 API 提供商

```bash
curl http://localhost:8000/api/providers
```

---

## 安全配置

### 图片代理 SSRF 防护
`/api/images/proxy` 端点阻止对私有 IP 的请求。如果外部图片 URL 失败:
1. 检查 URL 是否解析到私有 IP (如 `127.0.0.1`、`10.x.x.x`、`192.168.x.x`)
2. 仅允许 `http`/`https` 协议
3. 响应必须是 `image/*` Content-Type

### 下载路径遍历防护
`/api/download/image` 端点严格验证文件名:
1. 文件名仅允许字母数字、中文、点和短横线
2. 解析后的路径必须在配置的下载目录内
3. 如果下载返回 400 错误，检查文件名是否包含特殊字符

### API 密钥加密
1. 密钥使用 AES-256-GCM 基于文件种子加密（`<DATA_DIR>/.encryption_seed`）
2. 迁移到新机器需要同时拷贝 `.encryption_seed` 文件和数据库
3. 解密错误会被记录但不会导致服务器崩溃
4. 查看 `app/utils/crypto.py` 中的密钥派生逻辑
