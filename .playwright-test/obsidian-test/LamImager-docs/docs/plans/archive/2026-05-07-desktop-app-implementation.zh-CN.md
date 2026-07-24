# LamImager 桌面应用打包实施计划

> **For agentic workers:** 使用 executing-plans 或 subagent-driven-development 逐任务实施此计划。步骤使用复选框 (`- [ ]`) 语法追踪。

**目标:** 将 LamImager Web 应用打包为 Windows / macOS / Linux 原生桌面应用，提供系统托盘、单实例控制和更新检查功能。

**架构:** 使用 PyInstaller 将 Python 后端（FastAPI + uvicorn）打包为可执行文件，内嵌前端构建产物。pywebview 提供原生 WebView 窗口，pystray 提供跨平台系统托盘。桌面应用模块独立于现有后端代码，通过环境变量与后端通信。

**技术栈:** PyInstaller 6.x / pywebview 5.x / pystray 0.19+ / Pillow（已有）

---

## 任务 1: 修改后端配置支持环境变量数据目录

**文件:**
- `e:\LamImager\backend\app\config.py`

**步骤:**
- [ ] 修改 `Settings.DATA_DIR`，优先从环境变量 `LAMIMAGER_DATA_DIR` 读取，回退到默认的 `BASE_DIR / "data"`
- [ ] 新增 `Settings.STATIC_DIR`，优先从环境变量 `LAMIMAGER_STATIC_DIR` 读取，回退到默认的 `BASE_DIR / "frontend" / "dist"`（PyInstaller 打包后前端文件在 `sys._MEIPASS` 临时目录中，需要通过环境变量传递）
- [ ] 修改 `Settings.CORS_ORIGINS`，添加 `http://localhost` 和 `http://127.0.0.1`（不带端口），支持动态端口场景
- [ ] 修改 `backend/app/main.py` 中的 `static_dir` 变量，从 `settings.STATIC_DIR` 读取，替代硬编码的 `Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"`
- [ ] 确保 `model_post_init` 中所有依赖 `DATA_DIR` 的路径（`UPLOAD_DIR`, `DB_PATH`, `LOG_FILE`）自动跟随 `DATA_DIR` 环境变量更新

**验证:**
- [ ] 设置环境变量 `LAMIMAGER_DATA_DIR=/tmp/test_data` 后启动后端，确认数据目录为 `/tmp/test_data`
- [ ] 不设置环境变量时，确认数据目录仍为 `BASE_DIR / "data"`

**提交:** `feat: support LAMIMAGER_DATA_DIR env var for desktop packaging`

---

## 任务 2: 创建 desktop 模块目录和 __init__.py

**文件:**
- `e:\LamImager\desktop\__init__.py`
- `e:\LamImager\desktop\assets\` (目录)

**步骤:**
- [ ] 创建 `desktop/` 目录
- [ ] 创建 `desktop/__init__.py`，内容为 `__version__ = "0.1.0"`
- [ ] 创建 `desktop/assets/` 目录（存放图标资源）

**验证:**
- [ ] `python -c "import desktop; print(desktop.__version__)"` 输出 `0.1.0`

**提交:** `chore: create desktop module directory structure`

---

## 任务 3: 实现 desktop/server.py — 后端启动管理

**文件:**
- `e:\LamImager\desktop\server.py`

**步骤:**
- [ ] 实现 `find_available_port(start, end)` 函数，扫描 start 到 end 范围内的可用端口
- [ ] 实现 `ServerManager` 类：
  - `__init__(self)`: 初始化线程和事件对象
  - `start(self, port: int, data_dir: Path, static_dir: Path = None) -> None`: 在子线程中启动 uvicorn，设置 `LAMIMAGER_DATA_DIR` 和 `LAMIMAGER_STATIC_DIR` 环境变量
  - `stop(self) -> None`: 优雅停止 uvicorn 服务器
  - `is_running(self) -> bool`: 检查服务器是否运行中
- [ ] uvicorn 启动时禁用 access log（减少控制台输出），设置 `log_level="warning"`
- [ ] 使用 `uvicorn.Config` 和 `uvicorn.Server` 在子线程中运行，支持优雅关闭

**验证:**
- [ ] 在 Python 中 `from desktop.server import ServerManager; sm = ServerManager(); sm.start(8000, Path("/tmp/test")); import time; time.sleep(2); print(sm.is_running()); sm.stop()` 确认服务器启动和停止正常

**提交:** `feat: implement ServerManager for desktop app backend`

---

## 任务 4: 实现 desktop/tray.py — 系统托盘

**文件:**
- `e:\LamImager\desktop\tray.py`

**步骤:**
- [ ] 实现 `TrayManager` 类：
  - `__init__(self, on_show, on_assistant, on_settings, on_quit)`: 接收回调函数
  - `start(self) -> None`: 在子线程中启动 pystray 托盘图标
  - `stop(self) -> None`: 停止托盘
  - `update_icon(self, icon_path: str) -> None`: 更新托盘图标
- [ ] 使用 `pystray.Icon` 创建托盘图标，菜单项为：主程序、助手、设置、分隔线、退出
- [ ] 使用 `Pillow.Image` 生成默认托盘图标（纯色圆形 + 首字母 "L"），无需外部图标文件即可运行
- [ ] 托盘左键点击行为等同于「主程序」菜单项（显示窗口）

**验证:**
- [ ] 运行 `python -c "from desktop.tray import TrayManager; tm = TrayManager(lambda: print('show'), lambda: print('assistant'), lambda: print('settings'), lambda: print('quit')); tm.start()"` 确认托盘图标出现且菜单可点击

**提交:** `feat: implement TrayManager with pystray`

---

## 任务 5: 实现 desktop/updater.py — 更新检查

**文件:**
- `e:\LamImager\desktop\updater.py`

**步骤:**
- [ ] 实现 `UpdateInfo` dataclass：`version: str`, `download_url: str`, `release_notes: str`
- [ ] 实现 `UpdateChecker` 类：
  - `__init__(self, repo: str, current_version: str)`: repo 格式为 `"owner/repo"`
  - `check(self) -> UpdateInfo | None`: 调用 GitHub API `https://api.github.com/repos/{repo}/releases/latest`，比较版本号，有新版本返回 UpdateInfo，否则返回 None
  - `get_download_url(self, release: dict, platform: str) -> str`: 根据平台从 release assets 中找到对应的下载链接
- [ ] 版本比较使用 `packaging.version.parse`，如未安装则使用简单的字符串分割比较
- [ ] 网络请求使用 `urllib.request`（标准库，无需额外依赖），设置 5 秒超时
- [ ] 异常处理：网络错误、API 限流、JSON 解析失败均返回 None（静默失败）

**验证:**
- [ ] `python -c "from desktop.updater import UpdateChecker; uc = UpdateChecker('test/test', '0.0.1'); print(uc.check())"` 确认能正确调用 API（可能返回 None 因为 repo 不存在）

**提交:** `feat: implement UpdateChecker for GitHub Releases`

---

## 任务 6-12: (内容已省略，详见原文档)

完整的实施计划包含 12 个任务，涵盖:
- desktop/main.py 应用入口
- 前端 JS API 暴露
- 应用图标资源
- PyInstaller 配置
- 构建脚本
- 依赖更新
- 端到端测试

参见原始英文文档 `2026-05-07-desktop-app-implementation.md` 获取完整任务列表。
