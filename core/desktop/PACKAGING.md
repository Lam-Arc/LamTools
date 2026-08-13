# LamCore 桌面应用打包

## 前置依赖

- Node.js 24+、npm
- Python 3.14（与 PyInstaller 兼容）
- Rust toolchain（`rustup` + stable）+ Tauri CLI（`npm i -D @tauri-apps/cli` 已在 `package.json`）
- Windows：NSIS（Tauri installer bundler）

## 打包流程

**必须通过 `scripts/package.ps1` 完成**，不要直接执行 `npx tauri build`。

```powershell
.\scripts\package.ps1
```

脚本按顺序执行三步：

1. **前端构建**：`core/desktop` 下 `npm run build`（Vite SPA → `core/desktop/dist/`）
2. **Python 后端打包**：`py -3.14 -m PyInstaller lamtools-core-backend.spec --clean --noconfirm`，产物 `dist/LamCore/`
3. **Tauri 打包**：把后端产物复制到 `core/desktop/src-tauri/lamcore-backend/`，再 `npx tauri build` 生成 Windows 安装包；最后 `patch-nsis.ps1` 修补 NSIS 脚本

## 为什么不能直接 `tauri build`

`tauri.conf.json` 的 `beforeBuildCommand` 只构建前端（`npm run build`），**不跑 PyInstaller**。
若后端产物 `LamCore.exe` 缺失，桌面应用启动时 `find_backend_exe` 找不到后端，会弹窗报错
"LamCore 后端启动失败"（见 `src-tauri/src/main.rs` 的 `setup` 错误分支）。
`tauri.conf.json` 还把 `lamcore-backend` 列为 resource，缺失时 bundling 也会失败。

`package.ps1` 负责编排完整链路（前端 → PyInstaller → 复制 → Tauri → NSIS），是唯一受支持的打包入口。

## 开发模式

开发时无需打包，用：

```powershell
.\scripts\dev.ps1 core    # Core 前后端 dev server (5172 / 5173)
```

## 版本号与发布

**版本号只有 5 处且必须同步**（更新检查 `update.check` 用后端 `__version__` 与
GitHub Releases 比较，版本不一致会误报/漏报）：

1. `core/desktop/src-tauri/tauri.conf.json`
2. `core/desktop/src-tauri/Cargo.toml`
3. `core/desktop/package.json`
4. `core/pyproject.toml`
5. `core/src/lamtools_core/__init__.py` 的 `__version__`

统一用脚本改，不要手改：

```powershell
.\scripts\bump-version.ps1 0.3.0
```

### 发布流程（自动化）

```powershell
.\scripts\bump-version.ps1 0.3.0   # 1. 升版本（5 处同步）
git commit -am "chore: bump version to 0.3.0"   # 2. 提交
git tag v0.3.0                                    # 3. 打 tag
git push origin v0.3.0                            # 4. 推送（单独推 tag，不要用 --tags 批量推）
```

推送 tag 后 `.github/workflows/release.yml` 自动完成：前端构建 → PyInstaller →
后端二进制冒烟测试 → Tauri 打包 → 产物校验 → 上传 `LamCore_*_x64-setup.exe`
到 GitHub Releases。应用内「设置 → 关于与更新」即会检测到新版本并引导下载。

**手动触发构建**（不打 tag 验证构建链路）：仓库 Actions 页对 `Build & Release`
选 `Run workflow`（workflow_dispatch）——产物上传为 Actions artifact 而非 Release。

手动打包发布（不走 CI）时：跑 `.\scripts\package.ps1`，然后手动把
`core/desktop/src-tauri/target/release/bundle/nsis/LamCore_*_x64-setup.exe`
上传到 GitHub Releases（tag `vX.Y.Z`，命名与版本一致）。

**spec 单一事实源**：PyInstaller spec 只有一份 `core/lamtools-core-backend.spec`
（路径相对 spec 所在目录），本地 `package.ps1` 与 CI `release.yml` 都 cd 到
`core/` 后使用它——不要另建 spec。

## 更新检查机制（检测 + 引导下载）

- 检测链：前端 RPC `update.check` → 后端 `lamtools_core.update.checker`（httpx 调
  GitHub API `releases/latest`，semver 与 `__version__` 比较）。
- 下载引导：应用内「下载安装包」通过 `__LAMTOOLS_OPEN_URL__` 在系统浏览器打开
  安装包直链，由用户手动运行安装（未签名安装包不做静默安装）。
- CLI 等价能力：`py -3.14 -m lamtools_core.cli update check [--json]`。
- 不做：tauri-plugin-updater / minisign 签名 / latest.json（如未来升级全自动静默
  更新，开 `bundle.createUpdaterArtifacts` 并补 `latest.json` 上传即可，release.yml
  已预留 `.sig` 上传）。
