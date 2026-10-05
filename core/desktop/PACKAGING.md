# Sunday 桌面应用打包

## 前置依赖

- Node.js 24+、npm
- Python 3.14（与 PyInstaller 兼容）
- Rust stable toolchain
- Inno Setup 6.6.1（命令行编译器 ISCC.exe）

Linux 原生构建使用 Ubuntu 22.04（含 WSL2）以及 WebKitGTK 4.1。依赖可用
以下命令安装；apt 缓存和 WSL 发行版应放在非 C 盘：

    sudo apt-get update
    sudo apt-get install -y build-essential curl wget ca-certificates file \
      pkg-config patchelf libssl-dev libxdo-dev libdbus-1-dev libgtk-3-dev \
      libwebkit2gtk-4.1-dev libjavascriptcoregtk-4.1-dev \
      libayatana-appindicator3-dev librsvg2-dev xdg-utils \
      desktop-file-utils appstream squashfs-tools libfuse2 xvfb xauth dbus-x11

## Linux x64（WSL/Ubuntu 22.04）

Linux sidecar 必须在 Linux 原生 Python 上构建，不能复用 Windows 的
`LamCore.exe`。`scripts/package-linux.sh` 会在 WSL 文件系统内准备 Node 24、
uv 管理的 Python 3.14、Rust stable 及其缓存，然后按顺序构建前端、
Linux sidecar、AppImage 和 `.deb`，并执行后端
REST/WebSocket/Study smoke 与 `.deb` 内容检查：

脚本先把 `core/` 与 `scripts/`（含未提交源码改动）暂存到 WSL E 盘发行版的
`$HOME/.cache/lamtools-linux/build/source`，在该 ext4 工作区安装 Linux
`core/ui` 与 `core/desktop` 的 npm 依赖并编译，完成后只把 sidecar 与两个
发行包复制回仓库标准输出目录，不会把 Windows `node_modules` 改成 Linux 版本。

验收会在临时 WSL 目录执行 AppImage `--appimage-extract`，断言
`lamcore-backend/LamCore` 存在且可执行；若启用 Xvfb，还会在
`dbus-run-session` 中启动 GUI，只有超时保持存活才算通过。

    cd /mnt/e/LamTools
    bash scripts/package-linux.sh

也可从 Windows 调用（路径应指向 E 盘上的 Ubuntu-22.04 发行版）：

    wsl.exe -d Ubuntu-22.04 -- bash -lc \
      'cd /mnt/e/LamTools && bash scripts/package-linux.sh'

默认工具链缓存位于 WSL `$HOME/.cache/lamtools-linux`，可用
`LAMTOOLS_LINUX_TOOL_ROOT` 改到另一个非 `/mnt/c` 路径。构建输出位于：

    artifacts/linux-x64/sidecar/LamCore
    core/desktop/src-tauri/target/release/bundle/appimage/Sunday_<版本>_amd64.AppImage
    core/desktop/src-tauri/target/release/bundle/deb/Sunday_<版本>_amd64.deb

Tauri Linux bundle 通过 `tauri.conf.json` 的 `bundle.resources` 将
`core/dist/LamCore` 放入 `lamcore-backend/`；Rust shell 在 Linux 上从该资源
目录启动无扩展名的 `LamCore`。需要跳过可选的 Xvfb GUI smoke 时设置
`LAMTOOLS_SKIP_XVFB_SMOKE=1`。该脚本仅生成 Linux 产物，不升版本、不发布。

scripts/package.ps1 会从 PATH、INNO_SETUP_ISCC、机器级或当前用户的标准
Inno Setup 6 安装目录中查找编译器。也可直接向
core/desktop/installer/build-installer.ps1 传入 -IsccPath。

## 唯一支持的打包流程

    .\scripts\package.ps1

脚本依次执行：

1. 在 core/desktop 构建 Vite 前端。
2. 使用唯一的 core/lamtools-core-backend.spec 生成内部 sidecar
   core/dist/LamCore/LamCore.exe。
3. 执行 npx tauri build --no-bundle，只生成
   src-tauri/target/release/lamcore.exe，不会调用 Tauri 官方 NSIS bundler。
4. 将应用壳和 sidecar 暂存到
   src-tauri/target/release/sunday-installer/stage/，再由仓库自有
   installer/Sunday.iss 生成：

    core/desktop/src-tauri/target/release/bundle/inno/Sunday_<版本>_x64-setup.exe

Windows 流程显式使用 `--no-bundle`，不要在 Windows 上调用 Linux 的
AppImage/.deb targets；Windows 安装器 payload 的组装由 package.ps1 和
build-installer.ps1 负责。Linux 构建则使用上面的 `bundle.active`、
`appimage`/`deb` targets 与 sidecar resource 配置。

CI 固定使用 Inno Setup 6.6.1，避免编译器版本漂移导致产物或
授权条款变化；本地发布验证也应传入同版本的 `-IsccPath`。

## 安装行为

- 默认当前用户安装到 %LOCALAPPDATA%\Programs\Sunday，不要求管理员权限。
- 可选创建桌面快捷方式；开始菜单、Windows“已安装的应用”、卸载入口自动注册。
- 静默安装：

    Sunday_<版本>_x64-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART

- 指定目录：

    Sunday_<版本>_x64-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="E:\Apps\Sunday"

- Inno AppId 是稳定升级身份，后续版本不得修改。
- 应用内部兼容边界继续使用 lamcore.exe、
  lamcore-backend/LamCore.exe 与 identifier com.lamtools.lamcore。

## 升级与正在运行的应用

关闭主窗口只会把 Sunday 收进托盘，进程和打包的后端仍在运行，所以覆盖安装必须
先让旧程序退出：

- 安装器用 Restart Manager 关闭占用 lamcore.exe、lamcore-backend/ 内程序文件的
  进程（`CloseApplications=force`）。`CloseApplicationsFilter` 是**逗号分隔**的
  通配列表；写成分号会让它匹配不到任何文件、整条保护静默失效。
- Restart Manager 对这一对进程并不可靠（它关不掉「隐藏而不退出」的窗口应用，也
  关不掉无窗口的后端，却仍报告已处理），所以安装步骤开始时会自行结束安装目录内的
  Sunday 进程：只匹配可执行文件路径位于 `{app}` 下的进程，不会误伤同名但装在别处的
  程序。
- 应用收到系统级关闭请求（注销、关机）时走完整退出流程，不再只收进托盘，随后由
  后端作业对象保证不留孤儿进程（`windows_close_request`）。普通关闭窗口仍只收进
  托盘。
- 结束进程后确认 lamcore.exe 与 lamcore-backend/ 内所有文件都能独占打开；仍被占用
  （例如扫描器持有一个数据文件）则拒绝本次安装并保持既有安装完整（`CurStepChanged`
  守卫）。删除动作在该守卫之后，所以拒绝时不会留下半残安装。静默安装不弹窗，以非零
  退出码和 `Refusing to install:` 日志行体现。
- 验收：`scripts/verify-desktop-lifecycle.ps1` 覆盖安装、系统关闭请求、运行中升级、
  拒绝升级不损坏、卸载保留数据；release.yml 的安装冒烟步骤调用它，也可本地对任意
  安装包运行（机器上不要另有一个 Sunday 实例在跑）。

## 旧 NSIS 安装迁移与用户数据

旧版把用户数据保存在安装目录内：

    .lam/
    lam_projects/

Inno 安装器会检测旧 LamCore / LamTools Core 的卸载注册表项：

- 默认复用旧 InstallLocation。
- 新旧安装目录相同时，静默移除旧程序文件后原地安装 Sunday。
- 用户主动选择不同目录时，不自动卸载旧版，避免让旧目录里的本地数据失去入口。
- 同目录升级仅替换 lamcore.exe 与 lamcore-backend/。
- 默认卸载只移除程序文件、快捷方式和 ARP 注册，始终保留 .lam/ 与
  lam_projects/。清理本地数据需要用户显式手动删除。

## WebView2

build-installer.ps1 会下载并缓存微软官方 Evergreen bootstrapper，并把它嵌入
setup。安装时仅在未检测到 WebView2 Runtime 时运行该 bootstrapper。
离线或复现构建可用 -WebView2BootstrapperPath 指定已下载的官方文件。

## 开发模式

开发时不需要安装器：

    cd core\desktop
    npm run tauri dev

## 版本号与发布

版本号仍有 5 处且必须同步：

1. core/desktop/src-tauri/tauri.conf.json
2. core/desktop/src-tauri/Cargo.toml
3. core/desktop/package.json
4. core/pyproject.toml
5. core/src/lamtools_core/__init__.py

统一运行：

    .\scripts\bump-version.ps1 0.3.3

预发布版本（`0.3.7-beta.1`）走同一条链：`bump-version.ps1` 与 release.yml 的
tag 校验都接受 `X.Y.Z[-pre][+build]`，`update.check` 的版本比较也按 semver
排序（正式版高于同名预发布）。Cargo.lock 里 `sunday`/`lamcore` 的版本随
`cargo build` 自动跟上，提交前确认已同步。

推送 vX.Y.Z tag 后，.github/workflows/release.yml 会完成版本一致性校验、
前端与 sidecar 构建、后端冒烟、Tauri --no-bundle 构建、安装器编译，以及
真实的静默安装、启动、同目录升级、卸载和数据保留验证。发布资产只匹配
Sunday_*_x64-setup.exe；应用内更新检查也只选择这一命名。

手动触发 workflow 时不会发布 Release，只上传 sunday-installer 构建产物。

## 站点下载与更新清单

桌面端更新检查的首选来源是官网清单
`https://47.114.43.99.nip.io/downloads/desktop-update.json`，GitHub Releases
是回退（且始终是更新说明的来源）。

发布后需要把两样东西放到站点的 `downloads/` 目录：

1. `Sunday_<版本>_x64-setup.exe`（版本化文件名，清单里的
   `download_url` 指向它）
2. `desktop-update.json` —— 构建产物 `desktop-update-manifest`
   （release.yml 的「Build official-site update manifest」步骤产出并上传为
   Actions artifact；本地构建也可用
   `py -3.14 scripts/build-desktop-update.py` 从
   `core/desktop/src-tauri/target/release/bundle/inno/` 里最新的安装包生成）。

清单也可以先不传：检查器现在两源都问、取版本较高者，落后的清单只会让下载
地址回退到 GitHub，不会再屏蔽新版本（2026-09-25 审计 P1）。反向的坑也要
记住：清单一旦落后且不再更新，用户侧的「来源」标签会一直显示 GitHub。

