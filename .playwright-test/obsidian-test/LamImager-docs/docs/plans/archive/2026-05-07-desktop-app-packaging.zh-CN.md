# LamImager 桌面应用打包设计

## 目标

将 LamImager 从 Web 应用打包为 Windows / macOS / Linux 原生桌面应用，提供完整的桌面应用体验。

## 技术方案

**PyInstaller + pywebview + pystray**

- PyInstaller：将 Python 后端打包为可执行文件
- pywebview：原生 WebView 窗口显示前端
- pystray：跨平台系统托盘

## 架构设计

### 应用启动流程

```
用户双击 LamImager.exe
    │
    ▼
desktop/main.py
    │
    ├── 1. 检查单实例锁（已运行？→ 激活已有窗口 → 退出）
    ├── 2. 初始化数据目录（平台标准路径）
    ├── 3. 迁移旧数据（如果 data/ 在程序旁，迁移到新路径）
    ├── 4. 启动 FastAPI 后端（自动寻找可用端口 8000-8100）
    ├── 5. 等待后端就绪（轮询 /api/health，超时 10s 报错）
    ├── 6. 创建系统托盘（pystray，子线程）
    ├── 7. 打开 pywebview 窗口（主线程，加载 http://localhost:PORT）
    │
    ▼
应用运行中
    │
    ├── 关闭窗口 → 最小化到托盘
    ├── 托盘「主程序」→ 显示/隐藏主窗口
    ├── 托盘「助手」→ 在主窗口内激活助手面板 (JS: toggleAssistant())
    ├── 托盘「设置」→ 在主窗口内跳转设置页 (JS: navigateTo('/settings'))
    └── 托盘「退出」→ 停止 uvicorn → 释放锁文件 → 退出
```

### 系统托盘菜单

```
┌─────────────────────┐
│ 主程序              │
│ 助手                │
│ 设置                │
│ ─────────────────── │
│ 退出                │
└─────────────────────┘
```

| 菜单项 | 行为 | 实现方式 |
|--------|------|----------|
| 主程序 | 显示/隐藏主 WebView 窗口 | `webview.windows[0].show()` / `.hide()` |
| 助手 | 在主窗口内激活助手侧边栏 | JS 调用 `window.toggleAssistant()` |
| 设置 | 在主窗口内跳转设置页面 | JS 调用 `window.navigateTo('/settings')` |
| 退出 | 完全退出应用 | `server.stop()` → `release_lock()` → `sys.exit()` |

### 数据目录

打包后程序在临时目录解压，数据目录使用平台标准路径：

| 平台 | 路径 |
|------|------|
| Windows | `%APPDATA%/LamImager/` |
| macOS | `~/Library/Application Support/LamImager/` |
| Linux | `~/.local/share/LamImager/` |

通过环境变量 `LAMIMAGER_DATA_DIR` 传递给 FastAPI 后端。

### 单实例控制

- 启动时在数据目录创建 `.lock` 文件（文件锁）
- 已有实例运行时，通过 HTTP 通知已有实例激活窗口
- 退出时释放文件锁

### 端口策略

- 自动寻找可用端口：8000 → 8100
- 全部占用则弹窗报错
- WebView 加载 `http://localhost:{port}`

### 更新检查

- 应用启动时检查 GitHub Releases API
- 发现新版本弹窗提示
- 用户点击后打开下载页面

## 新增文件结构

```
e:\LamImager\
├── desktop/                    # 桌面应用模块
│   ├── __init__.py
│   ├── main.py                 # 应用入口
│   ├── server.py               # uvicorn 启动管理
│   ├── tray.py                 # 系统托盘
│   ├── updater.py              # 更新检查
│   └── assets/                 # 图标资源
│       ├── icon.ico            # Windows 图标
│       ├── icon.icns           # macOS 图标
│       └── icon.png            # Linux 图标
├── build.py                    # 构建脚本
└── LamImager.spec              # PyInstaller 配置
```

## 核心模块设计

### desktop/main.py

```python
def main():
    lock = acquire_lock()
    if not lock:
        activate_existing_window()
        return

    data_dir = get_platform_data_dir()
    ensure_dirs(data_dir)

    port = find_available_port(8000, 8100)
    server = start_server(port, data_dir)

    wait_for_health(port, timeout=10)

    tray = start_tray(port, data_dir)
    open_webview(port, on_close=minimize_to_tray)

    stop_server(server)
    release_lock(lock)
```

### desktop/server.py

```python
class ServerManager:
    def start(self, port: int, data_dir: Path) -> int
    def stop(self) -> None
    def is_running(self) -> bool
```

- 在子线程中启动 uvicorn
- 通过环境变量 `LAMIMAGER_DATA_DIR` 传递数据目录
- 优雅停止

### desktop/tray.py

```python
class TrayManager:
    def __init__(self, port, data_dir)
    def start(self) -> None
    def show_window(self) -> None
    def stop(self) -> None
```

- 使用 pystray 实现跨平台托盘
- 子线程运行
- 通过线程安全方式与 WebView 通信

### desktop/updater.py

```python
class UpdateChecker:
    def __init__(self, repo: str, current_version: str)
    def check(self) -> UpdateInfo | None
    def prompt_update(self, info: UpdateInfo) -> None
```

- 检查 GitHub Releases API
- 比较版本号
- WebView 内弹窗提示

## 后端适配

修改 `backend/app/config.py`，支持环境变量覆盖数据目录：

```python
class Settings(BaseSettings):
    DATA_DIR: Path = Path(os.environ.get(
        "LAMIMAGER_DATA_DIR",
        str(BASE_DIR / "data")
    ))
```

## 前端适配

暴露 JS API 供桌面应用调用：

```javascript
window.toggleAssistant = function() { ... }
window.navigateTo = function(path) { ... }
```

## 新增依赖

```
pywebview>=5.0        # 原生 WebView 窗口
pystray>=0.19         # 跨平台系统托盘
pyinstaller>=6.0      # 打包工具
```

## 构建与打包

### 构建命令

```bash
python build.py                    # 构建当前平台
python build.py --platform windows # 指定平台
python build.py --clean            # 清理重建
```

### 构建步骤

1. 检查前端是否已构建（frontend/dist/）
2. 如未构建，执行 npm run build
3. 生成 PyInstaller .spec 文件
4. 执行 PyInstaller 构建
5. 输出到 dist/LamImager-{platform}/

### 打包内容

```
├── Python 运行时
├── backend/app/          # FastAPI 后端代码
├── frontend/dist/        # Vue3 构建产物
├── desktop/              # 桌面应用模块
└── desktop/assets/       # 图标资源
```

### 构建产物

| 平台 | 产物 | 大小（预估） |
|------|------|-------------|
| Windows | `dist/LamImager/LamImager.exe` | ~60-80MB |
| macOS | `dist/LamImager.app` | ~70-90MB |
| Linux | `dist/LamImager/LamImager` | ~55-75MB |

## 已知限制

- macOS 需要代码签名和公证（需 Apple Developer 账号）
- Windows 可能被 SmartScreen 拦截（需代码签名）
- Linux 需要系统安装 WebKitGTK
- WebView2 在 Windows 7/8 上可能需要手动安装
- 移动端暂不支持（未来可考虑 Capacitor + 云端后端）
