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
`SundayCore.exe`。`scripts/package-linux.sh` 会在 WSL 文件系统内准备 Node 24、
uv 管理的 Python 3.14、Rust stable 及其缓存，然后按顺序构建前端、
Linux sidecar、AppImage 和 `.deb`，并执行后端
REST/WebSocket/Study smoke 与 `.deb` 内容检查：

脚本先把 `core/` 与 `scripts/`（含未提交源码改动）暂存到 WSL E 盘发行版的
`$HOME/.cache/lamtools-linux/build/source`，在该 ext4 工作区安装 Linux
`core/ui` 与 `core/desktop` 的 npm 依赖并编译，完成后只把 sidecar 与两个
发行包复制回仓库标准输出目录，不会把 Windows `node_modules` 改成 Linux 版本。

验收会在临时 WSL 目录执行 AppImage `--appimage-extract`，断言
`sunday-backend/SundayCore` 存在且可执行；若启用 Xvfb，还会在
`dbus-run-session` 中启动 GUI，只有超时保持存活才算通过。

    cd /mnt/e/LamTools
    bash scripts/package-linux.sh

也可从 Windows 调用（路径应指向 E 盘上的 Ubuntu-22.04 发行版）：

    wsl.exe -d Ubuntu-22.04 -- bash -lc \
      'cd /mnt/e/LamTools && bash scripts/package-linux.sh'

默认工具链缓存位于 WSL `$HOME/.cache/lamtools-linux`，可用
`LAMTOOLS_LINUX_TOOL_ROOT` 改到另一个非 `/mnt/c` 路径。构建输出位于：

    artifacts/linux-x64/sidecar/SundayCore
    core/desktop/src-tauri/target/release/bundle/appimage/Sunday_<版本>_amd64.AppImage
    core/desktop/src-tauri/target/release/bundle/deb/Sunday_<版本>_amd64.deb

Tauri Linux bundle 通过 `tauri.conf.json` 的 `bundle.resources` 将
`core/dist/SundayCore` 放入 `sunday-backend/`；Rust shell 在 Linux 上从该资源
目录启动无扩展名的 `SundayCore`。需要跳过可选的 Xvfb GUI smoke 时设置
`LAMTOOLS_SKIP_XVFB_SMOKE=1`。该脚本仅生成 Linux 产物，不升版本、不发布。

scripts/package.ps1 会从 PATH、INNO_SETUP_ISCC、机器级或当前用户的标准
Inno Setup 6 安装目录中查找编译器。也可直接向
core/desktop/installer/build-installer.ps1 传入 -IsccPath。

## 唯一支持的打包流程

    .\scripts\package.ps1

脚本依次执行：

1. 在 core/desktop 构建 Vite 前端。
2. 使用唯一的 core/lamtools-core-backend.spec 生成内部 sidecar
   core/dist/SundayCore/SundayCore.exe。
3. 执行 npx tauri build --no-bundle，只生成
   src-tauri/target/release/Sunday.exe，不会调用 Tauri 官方 NSIS bundler。
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
- 当前身份：主程序 `Sunday.exe`、后端目录 `sunday-backend/`、应用标识
  `com.lamtools.sunday`。旧版 `lamcore.exe` / `lamcore-backend/` /
  `com.lamtools.lamcore` 只作为升级与迁移的输入存在：安装器先结束旧进程再删除
  旧文件，应用启动时把旧标识下的数据搬到新标识下。

## 迁移旧身份（lamcore → Sunday）

- 主程序文件名：`Sunday.exe`（Cargo bin target 与 Tauri `mainBinaryName` 都是
  Sunday）。任务管理器「进程」页显示 Sunday，「详细信息」页显示 `Sunday.exe`。
- 应用标识：`com.lamtools.sunday`。启动时 `src-tauri/src/migration.rs` 会把
  `com.lamtools.lamcore`（以及最早的 `com.lamtools.core`）在各平台数据根下原地
  改名为新标识；Windows 同时覆盖 Roaming（应用数据）和 Local（WebView2 的
  localStorage / IndexedDB 配置）。只有新目录不存在时才搬，失败只记日志、不阻止
  启动，下次启动会重试。
- 独立后端状态目录：Windows 的 `%APPDATA%\LamCore` 会在首次启动时搬成
  `%APPDATA%\Sunday`；`plugin-system.jsonc` 的读取仍兼容旧位置。
- 后端凭据：keyring 服务名改为 `com.lamtools.sunday.remote`，读取时回退旧服务
  `com.lamtools.desktop.remote`，并在首次读取后写入新服务，已配对设备无需重配。
- 环境变量：壳给后端设置 `SUNDAY_CORE_PORT` / `SUNDAY_CORE_HOST`；Python 入口
  仍接受旧 `LAMCORE_PORT` / `LAMCORE_HOST`，旧版壳与外部脚本不会失效。
- 不迁移的边界：`LamTools` 家族目录（`%APPDATA%\LamTools`、XDG 的
  `LamTools`）、`LAMTOOLS_*` 变量、mDNS 服务类型 `_lamtools._tcp.local.` 和
  移动端 `com.lamtools.mobile` 都是跨产品/协议契约，改名会断开配对或让其他
  LamTools 工具读不到数据。

## 任务管理器里的进程身份

装机版与开发模式在任务管理器里显示的名字不同，这是有意为之，不是缺陷：

- **装机版**：主程序 `Sunday.exe` 带 Sunday 文件描述与产品名；后端是随包的
  Python 运行时，安装时部署为 `sunday-backend\sunday-core.exe`，并带
  「Sunday Core Backend」文件描述与 Sunday 产品名。所以在任务管理器「进程」页里
  两者分别显示为 Sunday 与 Sunday Core Backend，一眼能看出属于同一产品。

  改名分两处完成，缺一不可：PyInstaller 产物本身已叫 `SundayCore.exe`
  （`lamtools-core-backend.spec` 的 `name`），安装包 payload 组装这一步再由
  `installer/build-installer.ps1` 改成 `sunday-core.exe`。改名必须发生在版本资源
  写入之后——文件描述来自 spec 的 `version=`，改名搬不动资源。重命名 onedir
  引导程序是安全的：它按自身路径解析 `_internal`。应用壳侧的后端查找顺序是
  `sunday-core.exe` → `SundayCore.exe` → `LamCore.exe`，项目 `core/dist/` 与
  便携目录直接使用未改名的 `SundayCore.exe`；旧 `LamCore` 布局仅作兜底。

- **开发模式（`npx tauri dev`）**：后端由**系统** Python 解释器直接跑
  （`py -3.14 -m lamtools_core.cli serve --port 随机`），进程名与文件描述都随
  解释器，在任务管理器里就是 `python.exe`。这一层改不了名字：解释器属于系统安装，
  改它等于改系统 Python。这是开发模式的固有差别，也不该消除——开发模式跑的是源码，
  与装机版的进程形象本来就不同。排查问题时用「端口 + 命令行」定位这个后端，不要
  按进程名认（历史上正是按进程名把它当成了无关的 Python 进程）。

  另注意：`npx tauri dev` 会监视 `src-tauri/`，改动其中任何文件（纯 Rust 改动也算）
  都会自动重编译并重启应用窗口与其后端（日志里的 `File ... changed. Rebuilding
  application...`）。有人正在看窗口时不要动 Rust 源码，否则窗口会当场重启、后端随机
  端口也会换一个——看起来像环境自己崩了，其实是热重载。

## 升级与正在运行的应用

关闭主窗口只会把 Sunday 收进托盘，进程和打包的后端仍在运行，所以覆盖安装必须
先让旧程序退出：

- 安装器用 Restart Manager 关闭占用 Sunday.exe、sunday-backend/ 内程序文件的
  进程（`CloseApplications=force`）。从 lamcore 版本升级时，`{app}\lamcore.exe`
  和旧 `lamcore-backend/` 也在锁检测范围内，同样会先被结束。
  `CloseApplicationsFilter` 是**逗号分隔**的通配列表；写成分号会让它匹配不到任何
  文件、整条保护静默失效。
- 结束进程这一步由 `installer/sunday-release-files.ps1` 完成（安装包内的
  `[Code]` 在准备阶段解压执行），它回答的是「谁在用这些文件」，而不是「谁的可执行
  文件在这个目录里」：
  - 用 Windows Restart Manager 逐个文件查询持有者（`SundayRestartManager.cs` 在
    **打包时**编译成 `SundayRestartManager.dll`，安装时只加载）。之所以不在安装时
    用 PowerShell 的 `Add-Type`：那要调用用户机器上的 `csc.exe`，而被策略/杀软锁住的
    机器直接拒绝执行，诊断会退化成「查不到持有者」。
  - 只结束属于 Sunday 的进程：可执行文件在 `{app}` 下、加载了 `{app}` 内的模块
    （典型就是开发模式留在后台的 `python.exe` 占着
    `lamcore-backend\_internal\msvcp140.dll`），或命令行指向本目录的旧卸载器。
    其它进程即使占着目录里的数据文件也只报告、不结束——0.3.38 之前「只按可执行
    文件路径匹配」漏掉了前一类，锁检测只能中止安装，静默安装里就表现为安装窗口
    自己消失。
  - Restart Manager 不可用时（程序集缺失、查询报错）退化为 `tasklist /m` 找到持有
    同名模块的进程，再逐个核对模块真实路径，仍只结束确认属于 Sunday 的 PID。
- 应用内更新（`update.install`）连两点一起做：安装程序以脱离后端作业对象的方式启动
  （`JOB_OBJECT_LIMIT_BREAKAWAY_OK` + `CREATE_BREAKAWAY_FROM_JOB`，否则它会随应用退出
  被作业对象一起结束），随后应用经 `quit_app` 走一次真正的退出，而不是只收进托盘。
  安装程序确认启动之后应用才退出；启动失败保留应用并报错。
- 应用内更新用的是**静默档**：`/SILENT /NORESTART /AUTORESTART=1 /LOG=<更新目录>`。
  `[Run]` 里那条「启动 Sunday」带 `skipifsilent`（用户双击安装包时才有意义），所以
  静默那趟由 `CurStepChanged(ssDone)` 里读 `/AUTORESTART=1` 补一次自启动——更新到最后
  剩一个关着的窗口，等于没装完。CI 与本地验收用 `scripts/verify-desktop-lifecycle.ps1`
  的这一用例守着（静默安装后应用必须自己回来），公网通道另由
  `scripts/verify-update-install.ps1` 走一遍。
- 应用收到系统级关闭请求（注销、关机）时走完整退出流程，不再只收进托盘，随后由
  后端作业对象保证不留孤儿进程（`windows_close_request`）。普通关闭窗口仍只收进
  托盘。
- 结束进程后确认 Sunday.exe 与 sunday-backend/ 内所有文件都能独占打开，并把三种
  失败分开：句柄占用（win32 32/33）、只读属性（就地清掉，不算失败）、权限不足
  （ACL 或安全软件，结束进程没用）。仍被占用则拒绝本次安装并保持既有安装完整
  （`CurStepChanged` 守卫在删除动作之前），拒绝时不会留下半残安装。
- 拒绝不能是静默的：安装程序会把「阶段、持有进程名与 PID、阻塞文件、完整日志路径」
  写进失败报告（应用内更新经 `/FAILREPORT=` 指到更新目录的
  `install-failure.txt`，手动安装写到 `%LOCALAPPDATA%\Temp\sunday-update\`），
  `/SILENT`（应用内更新那一档，用户就在机器前）还会弹出可读的说明框，然后把旧版本
  重新拉起来，用户面对的是「弹窗 + 应用还在」。只有 `/VERYSILENT` 这种真无人值守
  的组合才不弹窗，靠非零退出码、失败报告与 `Refusing to install:` 日志行留痕。
  脚本弹窗要用 `SuppressibleMsgBox`，普通 `MsgBox` 不认
  `/SUPPRESSMSGBOXES`，会把无人值守安装挂在那里。
- 应用侧对应的是「启动之后确认它真的活着」：安装程序以脱离后端作业对象的方式启动
  后，`update/installer.py` 会问一句 `IsProcessInJob`——如果它还在某个作业对象里
  （脱离只对最内层作业生效），就换成 shell 交接重新启动；启动后立刻退出（退出码非
  零）也会被判为失败，应用不退出、报错保留。启动参数、PID、日志与失败报告路径都会
  写进更新目录的 `install-launch.json`，供不可复现的机器排查。
- 验收：`scripts/verify-desktop-lifecycle.ps1` 覆盖安装、系统关闭请求、运行中升级、
  拒绝升级不损坏、卸载保留数据；release.yml 的安装冒烟步骤调用它，也可本地对任意
  安装包运行（机器上不要另有一个 Sunday 实例在跑）。
  `scripts/verify-installer-file-release.ps1` 专门守着「文件放行」这一层：外部
  `python.exe` 持有安装目录 DLL、无关进程只持有数据文件（必须拒绝且不结束对方）、
  只读文件、权限不足、全新安装，用两个真实安装包（旧版 + 待测版）跑一遍。

## 旧 NSIS 安装迁移与用户数据

旧版把用户数据保存在安装目录内：

    .lam/
    lam_projects/

Inno 安装器会检测旧 LamCore / LamTools Core 的卸载注册表项：

- 默认复用旧 InstallLocation。
- 新旧安装目录相同时，静默移除旧程序文件后原地安装 Sunday。
- 用户主动选择不同目录时，不自动卸载旧版，避免让旧目录里的本地数据失去入口。
- 同目录升级仅替换 `Sunday.exe` 与 `sunday-backend/`；从 lamcore 版本升级时，
  `[InstallDelete]` 会一并删除旧的 `lamcore.exe`、`lamcore-backend/` 与更早的
  `LamCore/` 目录，避免留下第二个可启动的旧入口。
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
排序（正式版高于同名预发布）。Cargo.lock 里 `sunday` 的版本随
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

