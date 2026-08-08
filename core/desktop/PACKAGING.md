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
