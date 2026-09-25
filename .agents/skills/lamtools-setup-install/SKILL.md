---
name: lamtools-setup-install
description: '在 Sunday Core 完成新的 Windows Inno Setup 构建或版本更新后，定位对应安装包，安装到 E:\setuptest\对应版本目录，启动并校验主程序与后端进程。仅用于本地打包版验收，不用于开发模式或 GitHub 发布。'
---

# Sunday Setup 安装与启动验证

在每次完成 Sunday 的 Windows setup 构建或 setup 版本更新后执行本 skill，完成本机安装版冒烟验证。

## 适用时机

- `scripts/package.ps1` 或其他构建流程刚产出/更新了
  `Sunday_<版本号>_x64-setup.exe`。
- 用户要求安装、启动并确认新构建的 setup 版本。
- 不用于 `npm run tauri dev`、`scripts/dev.ps1`，也不代替 GitHub Release 发布流程。

## 标准流程

1. 从用户明确给出的版本号开始；没有给出时，让 helper 从 Sunday Inno Setup 输出目录中选择最新的 setup。
2. 使用本 skill 自带的 `scripts/install_setup.ps1`。默认精确匹配
   `core/desktop/src-tauri/target/release/bundle/inno/Sunday_<版本号>_x64-setup.exe`，并按需回退到
   `dist/` 或 `dist-plugins/` 中的同名包。
3. 默认安装到 `E:\setuptest\<版本号>`，每个版本使用独立目录，不删除旧版本目录。
4. 安装成功后启动安装目录内的 `lamcore.exe`，等待并确认主程序与
   `lamcore-backend\LamCore.exe` 进程都来自该版本目录。
5. helper 使用 Inno Setup 的 `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=...` 安装；不得退回 NSIS `/S /D=...`。
6. 回报实际使用的 setup 路径、安装目录、版本和已验证的进程 PID；任何一步失败都停止，不要把旧进程当作新版本成功。

## 执行命令

已知版本号时：

```powershell
& .\.agents\skills\lamtools-setup-install\scripts\install_setup.ps1 -Version <版本号> -ForceCloseExisting
```

版本号未知、需要使用最新构建包时：

```powershell
& .\.agents\skills\lamtools-setup-install\scripts\install_setup.ps1 -ForceCloseExisting
```

setup 不在默认构建目录时，显式传入 `-SetupPath <绝对路径>`。如需改变测试根目录，传入
`-InstallRoot <目录>`；默认值保持为 `E:\setuptest`。

`-ForceCloseExisting` 只关闭目标版本安装目录下的 LamTools 进程，用于同版本重复安装；不要关闭其他目录或开发环境的进程。

## 验收与边界

- setup 文件不存在、文件名版本与请求版本不一致、安装器返回非零退出码、`lamcore.exe` 缺失，或启动超时：立即报告失败原因。
- 只操作用户指定的 setup 和版本隔离目录；不删除历史安装目录，不修改版本号，不提交或推送代码/tag。
- 使用 PowerShell helper 的最终 JSON 作为证据；必要时再用 `Get-CimInstance Win32_Process` 复核进程路径。
