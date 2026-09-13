# Sunday 桌面应用打包

## 前置依赖

- Node.js 24+、npm
- Python 3.14（与 PyInstaller 兼容）
- Rust stable toolchain
- Inno Setup 6.6.1（命令行编译器 ISCC.exe）

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

Tauri 的 bundle.active 固定为 false；不要把 NSIS target、template 或 resource
复制重新加回 tauri.conf.json。安装器 payload 的组装由 package.ps1 和
build-installer.ps1 负责。

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

推送 vX.Y.Z tag 后，.github/workflows/release.yml 会完成版本一致性校验、
前端与 sidecar 构建、后端冒烟、Tauri --no-bundle 构建、安装器编译，以及
真实的静默安装、启动、同目录升级、卸载和数据保留验证。发布资产只匹配
Sunday_*_x64-setup.exe；应用内更新检查也只选择这一命名。

手动触发 workflow 时不会发布 Release，只上传 sunday-installer 构建产物。
