# 20 Tauri 桌面壳 审计报告

## 1. 概况

Tauri 2 桌面壳（`core/desktop/`）是 LamTools 的 Windows 桌面入口：Rust 壳负责拉起 Python 后端侧车（PyInstaller onedir 产物 `LamCore.exe`）、下发随机端口、提供窗口控制/目录选择/外链打开等 8 个自定义命令，前端（`src/main.ts` + `core/ui`）通过 `__LAMTOOLS_*__` 全局注入与壳通信。打包链路为 `scripts/package.ps1` → PyInstaller（`core/lamtools-core-backend.spec`，onedir：`LamCore.exe` + `_internal/`）→ 复制到 `src-tauri/lamcore-backend/`（gitignore 忽略，构建产物）→ `tauri build` → 自定义 NSIS 模板（`src-tauri/installer.nsi`）。设计定位"绿色便携"：所有用户数据（core.db、workspace、日志、jsonc 配置）放在安装目录旁的 `.lam/` 下（`main.rs:219-228`），安装器默认装到 setup.exe 同目录（`$EXEDIR\LamCore`）。

版本一致性良好：tauri.conf.json / Cargo.toml / package.json / pyproject.toml / `__init__.py` 五处均为 0.2.3；AGENTS.md:36 所述"Rust 选随机端口 + `get_api_base` 下发"与实现一致；`/api/health`（`factory.py:109`）与 `wait_for_health` 契约一致；`/api/core` 前缀与 `main.ts:7` 拼装一致。未发现 S1 级问题。

| 严重度 | 数量 |
| --- | --- |
| S1 | 0 |
| S2 | 2 |
| S3 | 4 |
| S4 | 7 |
| 合计 | 13 |

## 2. 问题清单

### S2

- **[S2] 开发模式后端进程树清理不完整，uvicorn reload 子进程成为孤儿**
  - 位置：`core/desktop/src-tauri/src/main.rs:194`（`--reload`）、`main.rs:316-323`（`stop_backend` 仅 `child.kill()` 直接子进程）
  - 问题：dev 模式以 `py -3.14 -m lamtools_core.cli serve --reload` 拉起后端，uvicorn 的 reload 模式在 Windows 上用 spawn 起独立子进程承载实际服务；窗口销毁时 `stop_backend` 只 kill 掉 `py.exe` 父进程，reload 子进程（连同其 stdout 句柄）继续存活。生产模式（onedir，无子进程）只在 Tauri 进程被硬杀（任务管理器结束）时才会遗留孤儿后端。
  - 影响：每次 `tauri dev` 退出后残留一个正在服务随机端口的 uvicorn 进程，持续持有 `core/core.db` 句柄与文件监视，累积后可导致下次 dev 实例 SQLite 锁冲突（`database is locked`）、端口/句柄泄漏；硬杀应用后遗留的后端会无限期占用随机端口且无任何清理。
  - 修复建议：dev 模式去掉 `--reload`（或保留但用 Windows Job Object 关联进程树，父进程退出即杀子树）；`stop_backend` 升级为进程组/Job 清理，并在 `spawn` 后记录子进程 pid 供兜底扫描。

- **[S2] 本地后端 API 无鉴权 + CORS 全放行（跨区：后端 factory.py，壳侧设计确认）**
  - 位置：`core/src/lamtools_core/app/factory.py:98-104`（`allow_origins=["*"]`、`allow_credentials=True`、`allow_methods=["*"]`）；壳侧 `main.rs:162,226-228` 仅注入端口与环境变量，无令牌
  - 问题：后端绑定 127.0.0.1 随机端口，但任何网页可跨源请求该端口（CORS `*` 允许读取响应）。端口虽随机，本地端口扫描可在毫秒级枚举出存活端口，从而定位 LamCore 后端。
  - 影响：用户浏览器中打开的任何恶意站点都有能力驱动本地 agent API（建会话、发起任务、读取项目/工件数据；命令类操作是否受审批门控取决于后端实现）。随机端口只提高发现门槛，不构成防护。
  - 修复建议：CORS 源白名单收敛为 `tauri://localhost` / `http://127.0.0.1:5173`（而非 `*`）；由壳每次启动生成随机令牌经环境变量（如 `LAMCORE_TOKEN`）下发后端，要求所有 API 携带该令牌（验证来源为壳本身）；若短期无法加鉴权，至少将 CORS 收紧并限制 `allow_credentials`。

### S3

- **[S3] 后端运行中崩溃无检测、无恢复**
  - 位置：`core/desktop/src-tauri/src/main.rs:157-175`（一次性启动）、`main.rs:316-323`（仅退出时清理）
  - 问题：`start_backend` 只在启动时做一次 `wait_for_health`；后端启动后 Rust 侧不再监视子进程存活。后端进程崩溃（如 uvicorn panic、Python 致命异常）后，`BackendState.child` 仍持有已死 Child，前端所有请求静默失败。
  - 影响：Agent 任务进行中后端死亡，桌面应用变成空壳且无任何用户提示、无重启；前端错误处理取决于 UI 层，用户可能误以为应用假死。
  - 修复建议：启动一个监视线程轮询 `child.try_wait()`，检测到退出（且非正常关闭路径）后：提示用户 + 可选自动重启（重新 `start_backend` 并更新 `api_base`，前端经 `get_api_base` 重新拉取）；或至少在 UI 显示"后端已停止"横幅。

- **[S3] 无单实例保护，多实例并发写同一份 .lam/core.db**
  - 位置：`core/desktop/src-tauri/Cargo.toml:11-21`（无 tauri-plugin-single-instance）、`main.rs:108-151`
  - 问题：未安装 single-instance 插件，也无进程互斥。双开应用时两个实例各自拉起随机端口后端，但共享同一 `.lam/core.db`（SQLite）与项目目录。
  - 影响：双实例并发写库可能导致 SQLite 锁错误（`database is locked`）、项目/配置互相覆盖、update.check 重复触发。
  - 修复建议：接入 `tauri-plugin-single-instance`（第二个实例聚焦已有窗口并退出）；或在 `main.rs` 用命名 Mutex（Windows `CreateMutex`）实现单实例。

- **[S3] 卸载器「删除应用数据」复选框指向错误目录，实际数据目录被留下**
  - 位置：`core/desktop/src-tauri/installer.nsi:890-906`（勾选后仅删 `$APPDATA\${BUNDLEID}` 与 `$LOCALAPPDATA\${BUNDLEID}`）；实际数据在 `$INSTDIR\.lam`（`main.rs:223-228`）；`installer.nsi:842`（`RMDir "$INSTDIR"`）
  - 问题：绿色便携模式下用户数据（core.db、workspace、日志、jsonc 配置、lam_projects）全部位于安装目录内，而卸载器的"删除应用数据"复选框删除的是应用从不写入的 `%APPDATA%\com.lamtools.lamcore` / `%LOCALAPPDATA%\com.lamtools.lamcore`。卸载主体只删除 exe、resources 与快捷方式，`RMDir "$INSTDIR"` 因 `.lam` 非空而静默失败。
  - 影响：勾选"删除应用数据"的用户误以为数据已清除，实际全部残留（隐私预期落空）；未勾选的用户卸载后整个安装目录（含全部用户数据）仍留在磁盘上，无任何提示。升级流程（`/UPDATE` 跳过删除）不受影响，数据保留是符合预期的。
  - 修复建议：将删除目标改为 `$INSTDIR\.lam` 与 `$INSTDIR\lam_projects`（仅勾选且非更新模式时），并对 `RMDir` 失败给出提示；若"绿色模式保留数据"是刻意设计，应在卸载确认页明确说明数据保留位置。

- **[S3] CSP 关闭 + asset 协议作用域 `**`，XSS 可读任意本地文件**
  - 位置：`core/desktop/src-tauri/tauri.conf.json:25-30`（`"csp": null`、`"assetProtocol": { "enable": true, "scope": ["**"] }`）
  - 问题：`csp: null` 使 WebView 无内容安全策略；`assetProtocol.scope: ["**"]` 使 `convertFileSrc` 可解析任意本地路径。两者叠加：若 SPA 内出现任意 XSS（agent 输出渲染、外部 HTML 注入等），攻击脚本可直接读取磁盘上任意文件（经 asset 协议）并外传。
  - 影响：本地文件泄露（含 `.lam` 下全部用户数据、密钥配置等）。当前无 shell/fs 等危险能力（见亮点），故未升级为 RCE，但文件读取面全开。
  - 修复建议：配置最小 CSP（`default-src 'self' tauri: asset: http://127.0.0.1:*`，script-src 收紧）；asset 协议 scope 收敛为 `.lam/artifacts`、`.lam/workspace` 等实际预览目录（可配合 `core:asset:allow-asset` 按需授权），不要用 `**`。

### S4

- **[S4] 健康检查只校验响应体包含 "200" 子串**
  - 位置：`core/desktop/src-tauri/src/main.rs:292-314`（`response.contains("200")`，行 305）
  - 问题：`GET /api/health` 后仅检查响应文本是否含 `"200"`；若端口被其他进程占用且返回含 "200" 文本的页面（如错误页里的状态码说明），会误判后端健康；后端返回非 200（如 500）但错误信息含 "200" 时同样误判。
  - 影响：极端情况下启动校验失真，前端拿到不可用 API。概率低。
  - 修复建议：解析 HTTP 状态行（`response.starts_with("HTTP/1.1 200")`）并校验 JSON 体 `{"status":"ok"}`。

- **[S4] 选端口 TOCTOU 竞争**
  - 位置：`core/desktop/src-tauri/src/main.rs:287-290`
  - 问题：`pick_free_port` 绑定 `127.0.0.1:0` 拿端口后立即释放，再由后端重新绑定；释放与后端 bind 之间存在窗口，其他进程可能抢走该端口，导致后端绑定失败并触发 90 秒健康检查超时 + 错误弹窗。
  - 修复建议：让后端以 `port=0` 方式自选端口，通过后端日志/stdout 回传实际端口，或由壳持有 listener 并 `SO_REUSEADDR` 传给后端；简单起见可接受现状（概率低），但至少把重试一次纳入考虑。

- **[S4] capabilities 冗余：3 个 core:window 权限未被使用**
  - 位置：`core/desktop/src-tauri/tauri.conf.json:31-42`（`allow-minimize` / `allow-toggle-maximize` / `allow-close`）
  - 问题：最小化/最大化/关闭均由自定义命令（`main.rs:41-58`）经 `invoke` 实现（`core/ui/src/components/TitleBar.vue:87-89`），`core:window` 的这三个权限无任何前端调用（全库无 `getCurrentWindow()` 用法）；实际必需的只有 `core:window:allow-start-dragging`（`data-tauri-drag-region`）。
  - 影响：无安全后果，但违背最小权限原则，权限面比实际需要大。
  - 修复建议：删除三个未用权限，仅保留 `core:window:allow-start-dragging`；若未来改用 `@tauri-apps/api/window` 再按需加回。

- **[S4] `installer/installer.nsi` 是过时渲染产物，版本与路径均已失真**
  - 位置：`core/desktop/installer/installer.nsi:31-32`（`VERSION "0.1.0"`，实际 0.2.3）、`:42`（硬编码本机绝对路径 `E:\LamTools\...\lamcore.exe`）、`:189-206`（简化版重装页：`ExecWait '$R0 /S _?=$INSTDIR'` 用新默认安装目录而非旧安装位置卸载）
  - 问题：该文件最后一次改动在 2026-07-29 旧 checkpoint 提交，是早期"patch-nsis 时代"的渲染产物，与现行模板 `src-tauri/installer.nsi`（tauri.conf `"template": "installer.nsi"` 实际使用）并存且已失真；其中 `_?=$INSTDIR` 在旧安装目录不同于 setup.exe 目录时会错误地卸载、报"卸载失败"并中止升级。
  - 影响：目前无人引用（grep 确认），但作为仓库内误导性文件，若被误用（手动 makensis、错误接线）会造成升级阻断。
  - 修复建议：删除 `installer/installer.nsi`（或移入归档），并在 PACKAGING.md 注明唯一有效的模板路径。

- **[S4] `patch-nsis.ps1` 已成死代码，且 PACKAGING.md 描述与其矛盾**
  - 位置：`scripts/patch-nsis.ps1:12`（硬编码输出 `LamCore_0.2.2_x64-setup.exe`）、`core/desktop/PACKAGING.md:22`（"最后 `patch-nsis.ps1` 修补 NSIS 脚本"）
  - 问题：`package.ps1`（commit 2505e71 同批改动）已明确"无需再跑 patch-nsis.ps1"，但脚本本身仍留在 `scripts/`，PACKAGING.md:22 仍描述旧的"三步 + patch"流程；patch-nsis.ps1 还硬编码 0.2.2 版本输出名，任何人按文档手动执行会得到过期产物。
  - 影响：文档与实现漂移，误操作风险。
  - 修复建议：删除 `patch-nsis.ps1`，同步修正 PACKAGING.md 第 3 步描述。

- **[S4] `find_backend_exe` 残留 "// ... rest unchanged" 编辑标记注释**
  - 位置：`core/desktop/src-tauri/src/main.rs:259`
  - 问题：查找逻辑中残留一句无信息量的编辑期注释（"其余保持不变"），且与下方分支 3 的注释风格不一致，属清理遗漏。
  - 影响：可读性（死注释）。
  - 修复建议：删除该行注释。

- **[S4] 工作根环境变量契约存在双根与 dev/prod 不一致（跨区）**
  - 位置：`core/desktop/src-tauri/src/main.rs:226-228`（仅设 `LAMTOOLS_PROJECTS_ROOT`= `app_dir\lam_projects`）；`core/desktop_backend.py:96-99`（`setdefault("LAMTOOLS_CORE_WORK_ROOT", data_dir/"workspace"` = `.lam\workspace`）；`core/src/lamtools_core/app/http_agent_app.py:229-232`（work_root 解析顺序：显式 → `LAMTOOLS_CORE_WORK_ROOT` → `ensure_projects_root()/"default"`）
  - 问题：壳设置的 `LAMTOOLS_PROJECTS_ROOT` 只影响项目库（project store），而 agent 默认工作根由 `LAMTOOLS_CORE_WORK_ROOT` 决定，生产环境下被 desktop_backend.py 预置为 `.lam\workspace`；dev 模式（cmd_serve，未设该变量）则落到 `lam_projects/default`。结果：同一应用存在 `.lam\workspace` 与 `lam_projects` 两个"根"，且 dev 与 prod 的默认工作根不同。
  - 影响：默认任务（未显式传 work_root）在 dev 与 prod 落在不同目录，用户/测试在两种模式下看到不同工作区；目录语义分裂，排障成本高。
  - 修复建议：统一由壳设置 `LAMTOOLS_CORE_WORK_ROOT`（或让 desktop_backend.py 优先读 `LAMTOOLS_PROJECTS_ROOT`），使 work_root 与 projects root 收敛为同一目录，并让 dev/prod 默认一致。

- **[S4] 启动阶段阻塞 setup，后端未就绪前无窗口**
  - 位置：`core/desktop/src-tauri/src/main.rs:116-141`、`:173`
  - 问题：`start_backend` 与 `wait_for_health`（最长 90 秒）在 `setup` 内同步执行，窗口在 setup 返回后才创建；后端启动慢（首次运行、机器负载高）时用户只看到任务栏图标，最长 90 秒无任何界面反馈。
  - 影响：首启体验差，用户易误判"没打开"而重复启动（叠加单实例缺失问题）。
  - 修复建议：先建窗口再异步拉后端，就绪前前端显示"正在启动后端…"占位；或缩短超时并在窗口内展示进度/错误而非仅系统弹窗。

## 3. 该区 Top 3 问题

1. **后端进程树清理不完整（dev 孤儿进程 / 硬杀遗留孤儿）** — S2。`stop_backend` 只杀直接子进程，uvicorn `--reload` 子进程在 Windows 上必然残留，累积成句柄与 DB 锁风险；生产模式硬杀应用后后端无限期存活。
2. **本地 API 无鉴权 + CORS `*`（跨区）** — S2。随机端口只是发现门槛，浏览器中任意站点可枚举端口并驱动本地 agent API；建议 CORS 白名单 + 启动令牌。
3. **卸载器数据语义与绿色便携设计脱节** — S3。勾选"删除应用数据"删的是应用从不使用的 `%APPDATA%` 路径，真实数据（`$INSTDIR\.lam`）被静默保留，卸载后整个目录残留且无提示。

## 4. 亮点

- **绿色便携设计自洽**：`LAMTOOLS_HOME` → `.lam/`（core.db/workspace/backend.log/核心配置全在安装根内，`main.rs:223-228` + `desktop_backend.py:60-99`），升级（`/UPDATE` 跳过删除）不触碰用户数据，与 `ensure_default_config_files` 幂等播种配合，更新永不覆盖用户配置（PACKAGING.md 亦明确）。
- **错误路径有兜底**：后端启动失败在 Windows 下弹中文 MessageBox（`main.rs:126-137`），PACKAGING.md 明示失败场景与排查路径；`wait_for_health` 90 秒宽限避免负载机误报。
- **安全面收敛到位**：无 shell/fs/process 等任何危险插件（Cargo.toml 仅 5 个依赖，acl-manifests 仅 core 插件）；`open_external_url` 严格校验 http(s) scheme（`main.rs:95-102`）；`dragDropEnabled: false` 使拖拽走 HTML5 事件（App.vue 注释明示）；自定义命令全部无副作用放大面。
- **契约一致性良好**：随机端口 + `get_api_base` 下发与 AGENTS.md:36 完全一致；`/api/health`、`/api/core` 前缀、`__LAMTOOLS_API_BASE__` 拼装、vite 代理 5172（仅纯浏览器 dev 用）三方对得上；五处版本号 0.2.3 全部同步；`additionalBrowserArgs` 禁用后台节流贴合 agent 长任务场景。
- **打包链路单一事实源**：PyInstaller spec 唯一（`core/lamtools-core-backend.spec`），package.ps1 与 CI release.yml 一致；CI 含后端二进制真冒烟（`/api/health` 轮询）与安装包产物校验。

## 5. 审计范围与方法

本区审计范围（全部只读，未运行任何构建/启动命令）：

- `core/desktop/src-tauri/src/main.rs`（331 行，逐行）、`build.rs`、`Cargo.toml`、`Cargo.lock`（tauri 2.11.5 / wry 0.55.1）
- `core/desktop/src-tauri/tauri.conf.json`、`src-tauri/installer.nsi`（现行 handlebars 模板）、`installer/installer.nsi`（陈旧渲染产物）、`src-tauri/gen/schemas/`（capabilities.json / acl-manifests.json）
- `core/desktop/vite.config.ts`、`src/main.ts`、`package.json`、`index.html`、`PACKAGING.md`
- `core/desktop/src-tauri/lamcore-backend/`（PyInstaller onedir 产物目录结构，未运行）
- 关联契约核对（只读 grep）：`core/desktop_backend.py`（入口）、`core/src/lamtools_core/app/factory.py`（CORS/health）、`app/http_agent_app.py`（work_root）、`config/root.py`（LAMTOOLS_HOME/PROJECTS_ROOT）、`cli.py`（serve）、`core/lamtools-core-backend.spec`、`scripts/{dev,package,patch-nsis}.ps1`、`scripts/ports.json`、`.github/workflows/release.yml`、AGENTS.md、`core/ui` 中 `__LAMTOOLS_*__` 与拖拽区域消费点、git 历史、`tauri-dev.log`（仅查看）。

方法：逐文件精读 + 交叉 grep 验证壳/后端/前端三方契约（端口、API 前缀、环境变量、版本号、安装路径），对 NSIS 两版文件做差异比对，并核对文档（PACKAGING.md / AGENTS.md）与实现的漂移。
