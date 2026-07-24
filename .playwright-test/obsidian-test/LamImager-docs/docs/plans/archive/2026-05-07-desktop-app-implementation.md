# LamImager 桌面应用打包实施计划

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 LamImager Web 应用打包为 Windows / macOS / Linux 原生桌面应用，提供系统托盘、单实例控制和更新检查功能。

**Architecture:** 使用 PyInstaller 将 Python 后端（FastAPI + uvicorn）打包为可执行文件，内嵌前端构建产物。pywebview 提供原生 WebView 窗口，pystray 提供跨平台系统托盘。桌面应用模块独立于现有后端代码，通过环境变量与后端通信。

**Tech Stack:** PyInstaller 6.x / pywebview 5.x / pystray 0.19+ / Pillow（已有）

---

## Task 1: 修改后端配置支持环境变量数据目录

**Files:**
- `e:\LamImager\backend\app\config.py`

**Steps:**
- [ ] 修改 `Settings.DATA_DIR`，优先从环境变量 `LAMIMAGER_DATA_DIR` 读取，回退到默认的 `BASE_DIR / "data"`
- [ ] 新增 `Settings.STATIC_DIR`，优先从环境变量 `LAMIMAGER_STATIC_DIR` 读取，回退到默认的 `BASE_DIR / "frontend" / "dist"`（PyInstaller 打包后前端文件在 `sys._MEIPASS` 临时目录中，需要通过环境变量传递）
- [ ] 修改 `Settings.CORS_ORIGINS`，添加 `http://localhost` 和 `http://127.0.0.1`（不带端口），支持动态端口场景
- [ ] 修改 `backend/app/main.py` 中的 `static_dir` 变量，从 `settings.STATIC_DIR` 读取，替代硬编码的 `Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"`
- [ ] 确保 `model_post_init` 中所有依赖 `DATA_DIR` 的路径（`UPLOAD_DIR`, `DB_PATH`, `LOG_FILE`）自动跟随 `DATA_DIR` 环境变量更新

**Verification:**
- [ ] 设置环境变量 `LAMIMAGER_DATA_DIR=/tmp/test_data` 后启动后端，确认数据目录为 `/tmp/test_data`
- [ ] 不设置环境变量时，确认数据目录仍为 `BASE_DIR / "data"`

**Commit:** `feat: support LAMIMAGER_DATA_DIR env var for desktop packaging`

---

## Task 2: 创建 desktop 模块目录和 __init__.py

**Files:**
- `e:\LamImager\desktop\__init__.py`
- `e:\LamImager\desktop\assets\` (目录)

**Steps:**
- [ ] 创建 `desktop/` 目录
- [ ] 创建 `desktop/__init__.py`，内容为 `__version__ = "0.1.0"`
- [ ] 创建 `desktop/assets/` 目录（存放图标资源）

**Verification:**
- [ ] `python -c "import desktop; print(desktop.__version__)"` 输出 `0.1.0`

**Commit:** `chore: create desktop module directory structure`

---

## Task 3: 实现 desktop/server.py — 后端启动管理

**Files:**
- `e:\LamImager\desktop\server.py`

**Steps:**
- [ ] 实现 `find_available_port(start, end)` 函数，扫描 start 到 end 范围内的可用端口
- [ ] 实现 `ServerManager` 类：
  - `__init__(self)`: 初始化线程和事件对象
  - `start(self, port: int, data_dir: Path, static_dir: Path = None) -> None`: 在子线程中启动 uvicorn，设置 `LAMIMAGER_DATA_DIR` 和 `LAMIMAGER_STATIC_DIR` 环境变量
  - `stop(self) -> None`: 优雅停止 uvicorn 服务器
  - `is_running(self) -> bool`: 检查服务器是否运行中
- [ ] uvicorn 启动时禁用 access log（减少控制台输出），设置 `log_level="warning"`
- [ ] 使用 `uvicorn.Config` 和 `uvicorn.Server` 在子线程中运行，支持优雅关闭

**Verification:**
- [ ] 在 Python 中 `from desktop.server import ServerManager; sm = ServerManager(); sm.start(8000, Path("/tmp/test")); import time; time.sleep(2); print(sm.is_running()); sm.stop()` 确认服务器启动和停止正常

**Commit:** `feat: implement ServerManager for desktop app backend`

---

## Task 4: 实现 desktop/tray.py — 系统托盘

**Files:**
- `e:\LamImager\desktop\tray.py`

**Steps:**
- [ ] 实现 `TrayManager` 类：
  - `__init__(self, on_show, on_assistant, on_settings, on_quit)`: 接收回调函数
  - `start(self) -> None`: 在子线程中启动 pystray 托盘图标
  - `stop(self) -> None`: 停止托盘
  - `update_icon(self, icon_path: str) -> None`: 更新托盘图标
- [ ] 使用 `pystray.Icon` 创建托盘图标，菜单项为：主程序、助手、设置、分隔线、退出
- [ ] 使用 `Pillow.Image` 生成默认托盘图标（纯色圆形 + 首字母 "L"），无需外部图标文件即可运行
- [ ] 托盘左键点击行为等同于「主程序」菜单项（显示窗口）

**Verification:**
- [ ] 运行 `python -c "from desktop.tray import TrayManager; tm = TrayManager(lambda: print('show'), lambda: print('assistant'), lambda: print('settings'), lambda: print('quit')); tm.start()"` 确认托盘图标出现且菜单可点击

**Commit:** `feat: implement TrayManager with pystray`

---

## Task 5: 实现 desktop/updater.py — 更新检查

**Files:**
- `e:\LamImager\desktop\updater.py`

**Steps:**
- [ ] 实现 `UpdateInfo` dataclass：`version: str`, `download_url: str`, `release_notes: str`
- [ ] 实现 `UpdateChecker` 类：
  - `__init__(self, repo: str, current_version: str)`: repo 格式为 `"owner/repo"`
  - `check(self) -> UpdateInfo | None`: 调用 GitHub API `https://api.github.com/repos/{repo}/releases/latest`，比较版本号，有新版本返回 UpdateInfo，否则返回 None
  - `get_download_url(self, release: dict, platform: str) -> str`: 根据平台从 release assets 中找到对应的下载链接
- [ ] 版本比较使用 `packaging.version.parse`，如未安装则使用简单的字符串分割比较
- [ ] 网络请求使用 `urllib.request`（标准库，无需额外依赖），设置 5 秒超时
- [ ] 异常处理：网络错误、API 限流、JSON 解析失败均返回 None（静默失败）

**Verification:**
- [ ] `python -c "from desktop.updater import UpdateChecker; uc = UpdateChecker('test/test', '0.0.1'); print(uc.check())"` 确认能正确调用 API（可能返回 None 因为 repo 不存在）

**Commit:** `feat: implement UpdateChecker for GitHub Releases`

---

## Task 6: 实现 desktop/main.py — 应用入口

**Files:**
- `e:\LamImager\desktop\main.py`

**Steps:**
- [ ] 实现 `get_platform_data_dir() -> Path`：根据平台返回标准数据目录
  - Windows: `%APPDATA%/LamImager`
  - macOS: `~/Library/Application Support/LamImager`
  - Linux: `~/.local/share/LamImager`
- [ ] 实现 `get_static_dir() -> Path`：检测是否在 PyInstaller 打包环境中运行（`getattr(sys, 'frozen', False)`），是则返回 `Path(sys._MEIPASS) / "frontend" / "dist"`，否则返回项目根目录下的 `frontend/dist`
- [ ] 实现 `acquire_lock(data_dir: Path) -> FileLock | None`：使用 `filelock` 库实现跨平台单实例控制（`pip install filelock`），锁文件路径为 `data_dir / ".lock"`
- [ ] 实现 `activate_existing_window(port: int)`：向已运行实例的 `/api/health` 发送请求，触发窗口激活
- [ ] 实现 `wait_for_health(port: int, timeout: int = 10)`：轮询 `/api/health` 直到后端就绪
- [ ] 实现 `main()` 函数：按启动流程串联所有模块
  1. 单实例检测
  2. 数据目录初始化
  3. 启动后端（ServerManager），传递 `static_dir`（PyInstaller 打包后使用 `sys._MEIPASS / "frontend/dist"`）
  4. 等待后端就绪
  5. 启动托盘（TrayManager）
  6. 打开 WebView 窗口
  7. 启动时异步检查更新
  8. 退出清理
- [ ] WebView 窗口配置：
  - 标题：`LamImager`
  - 尺寸：1200×800
  - 最小尺寸：800×600
  - 关闭时最小化到托盘（`on_close` 回调中调用 `window.hide()`）
- [ ] 托盘回调实现：
  - 主程序：`webview.windows[0].show()`
  - 助手：`webview.windows[0].evaluate_js('window.toggleAssistant && window.toggleAssistant()')`
  - 设置：`webview.windows[0].evaluate_js('window.navigateTo && window.navigateTo("/settings")')`
  - 退出：设置退出标志 → 停止服务器 → 停止托盘 → `window.destroy()`
- [ ] 添加 `if __name__ == "__main__": main()` 入口

**Verification:**
- [ ] `python desktop/main.py` 启动桌面应用，确认窗口打开、托盘图标出现、菜单功能正常

**Commit:** `feat: implement desktop app entry point with pywebview`

---

## Task 7: 前端暴露 JS API 供桌面应用调用

**Files:**
- `e:\LamImager\frontend\src\App.vue`

**Steps:**
- [ ] 在 `App.vue` 的 `<script setup>` 中添加 `onMounted` 钩子，将函数挂载到 `window` 对象：
  - `window.toggleAssistant = () => { router.push('/') }` — 助手功能跳转到会话页面（会话页面包含助手对话）
  - `window.navigateTo = (path: string) => { router.push(path) }` — 通用路由跳转
- [ ] 在 `onUnmounted` 中清理 `window` 上挂载的函数

**Verification:**
- [ ] 在浏览器控制台执行 `window.navigateTo('/settings')`，确认页面跳转到设置页
- [ ] 在浏览器控制台执行 `window.toggleAssistant()`，确认页面跳转到会话页

**Commit:** `feat: expose JS API for desktop app tray integration`

---

## Task 8: 创建应用图标资源

**Files:**
- `e:\LamImager\desktop\assets\icon.ico`
- `e:\LamImager\desktop\assets\icon.icns`
- `e:\LamImager\desktop\assets\icon.png`

**Steps:**
- [ ] 使用 Pillow 生成一个简单的应用图标（256x256 PNG）：深灰背景 + 白色 "L" 字母
- [ ] 将 PNG 保存为 `icon.png`（Linux 和 pystray 使用）
- [ ] 使用 Pillow 将 PNG 转换为 ICO 格式（包含 16x16, 32x32, 48x48, 256x256 多尺寸），保存为 `icon.ico`
- [ ] macOS 的 ICNS 格式暂用 PNG 代替（ICNS 转换需要系统工具，可在 macOS 上构建时生成）

**Verification:**
- [ ] 图标文件存在于 `desktop/assets/` 目录
- [ ] `icon.ico` 可被 Windows 资源管理器正确显示

**Commit:** `chore: add application icon resources`

---

## Task 9: 创建 PyInstaller 配置文件

**Files:**
- `e:\LamImager\LamImager.spec`

**Steps:**
- [ ] 创建 PyInstaller spec 文件，配置以下内容：
  - `name='LamImager'`
  - `onefile=False`（使用目录模式，启动更快）
  - 入口脚本：`desktop/main.py`
  - hiddenimports：`uvicorn.logging`, `uvicorn.loops`, `uvicorn.loops.auto`, `uvicorn.protocols`, `uvicorn.protocols.http`, `uvicorn.protocols.http.auto`, `uvicorn.protocols.websockets`, `uvicorn.protocols.websockets.auto`, `uvicorn.lifespan`, `uvicorn.lifespan.on`, `aiosqlite`
  - datas：`('frontend/dist', 'frontend/dist')`, `('desktop/assets', 'desktop/assets')`
  - exclude：`tkinter`, `test`, `unittest`
  - Windows 特定：`icon='desktop/assets/icon.ico'`, `console=False`
  - macOS 特定：`icon='desktop/assets/icon.png'`
- [ ] 添加 UPX 压缩选项（如果可用）

**Verification:**
- [ ] `pyinstaller LamImager.spec` 能成功生成构建产物（可能需要先安装依赖）

**Commit:** `chore: add PyInstaller spec configuration`

---

## Task 10: 创建构建脚本 build.py

**Files:**
- `e:\LamImager\build.py`

**Steps:**
- [ ] 实现 `build.py` 命令行脚本，支持以下参数：
  - `--platform`: 指定目标平台（windows/macos/linux），默认当前平台
  - `--clean`: 清理构建缓存后重新构建
  - `--skip-frontend`: 跳过前端构建步骤
- [ ] 构建流程：
  1. 检查 Python 环境（版本 >= 3.14）
  2. 检查依赖是否安装（pyinstaller, pywebview, pystray），未安装则提示
  3. 检查 `frontend/dist/` 是否存在，不存在则执行 `cd frontend && npm run build`
  4. 如果 `--clean`，删除 `build/` 和 `dist/` 目录
  5. 执行 `pyinstaller LamImager.spec`
  6. 输出构建结果路径
- [ ] 使用 `subprocess` 执行外部命令，捕获输出和错误
- [ ] 构建成功后打印产物路径和大小

**Verification:**
- [ ] `python build.py --skip-frontend` 能成功构建（前提是 frontend/dist/ 已存在）

**Commit:** `feat: add build script for desktop app packaging`

---

## Task 11: 更新 requirements.txt 添加桌面应用依赖

**Files:**
- `e:\LamImager\backend\requirements.txt`

**Steps:**
- [ ] 在 `requirements.txt` 末尾添加：
  ```
  pywebview>=5.0
  pystray>=0.19
  pyinstaller>=6.0
  filelock>=3.13
  ```
- [ ] 这些依赖仅在桌面打包时需要，Web 模式运行不需要安装

**Verification:**
- [ ] `pip install -r backend/requirements.txt` 能成功安装所有依赖

**Commit:** `chore: add desktop app dependencies to requirements.txt`

---

## Task 12: 端到端测试 — Windows 桌面应用

**Files:** 无新文件

**Steps:**
- [ ] 执行 `python build.py` 构建 Windows 桌面应用
- [ ] 运行 `dist/LamImager/LamImager.exe`，验证：
  - 应用窗口正常打开
  - 系统托盘图标出现
  - 托盘菜单功能正常（主程序、助手、设置、退出）
  - 关闭窗口后应用最小化到托盘
  - 托盘退出后应用完全关闭
  - 数据目录在 `%APPDATA%/LamImager/` 下正确创建
  - 数据库和上传目录正常工作
  - 前端页面正常加载和交互
- [ ] 双击启动第二个实例，验证单实例控制生效（激活已有窗口而非启动新实例）

**Verification:**
- [ ] 以上所有测试项通过

**Commit:** `test: end-to-end verification of Windows desktop app`

---

## 依赖关系图

```
Task 1 (config.py) ─────┐
                         │
Task 2 (目录结构) ───────┤
                         │
Task 3 (server.py) ──────┤
                         ├──→ Task 6 (main.py) ──→ Task 12 (端到端测试)
Task 4 (tray.py) ────────┤
                         │
Task 5 (updater.py) ─────┤
                         │
Task 7 (前端 JS API) ────┘
                         │
Task 8 (图标资源) ───────┤
                         ├──→ Task 9 (spec) ──→ Task 10 (build.py) ──→ Task 12
Task 11 (requirements) ──┘
```

Task 1-8 可并行开发，Task 6 依赖 1-5，Task 9 依赖 8，Task 10 依赖 9，Task 12 依赖全部。
