# 14 构建/发布链 审计报告

## 1. 概况

本区审计构建/发布/脚本链：版本号 5 处同步（`tauri.conf.json` / `Cargo.toml` / `desktop/package.json` / `pyproject.toml` / `lamtools_core/__init__.py`，当前全部一致为 `0.2.3`）、PyInstaller spec（`core/lamtools-core-backend.spec`）、更新检查（`update/checker.py` + `operations.py`）、`scripts/` 全部入口、Tauri/NSIS 打包链与 `PACKAGING.md`、`config/defaults.py` 播种清单 vs AGENTS.md 声称。

整体结论：发布链主链路是扎实的——单一 spec 事实源（本地 `package.ps1` 与 CI `release.yml` 同用 `core/lamtools-core-backend.spec`）、CI 带后端二进制真冒烟（`/api/health` 轮询）、安装器不打包 `.lam`（用户配置不会被覆盖）、`bump-version.ps1` 5 处全同步、`checker.py` 错误全部折叠为 `check_failed` 且有单测覆盖。未发现 S1 级问题（无当前会产出坏包或丢用户数据的缺陷）。主要问题集中在：发布链缺少"tag 与版本文件一致性"校验、spec 的 hiddenimports 清单与代码库明显漂移（当前靠静态分析自动发现兜底，属演进风险）、`update.check` 同步 HTTP 阻塞事件循环、卸载器"删除应用数据"复选框实际不删除任何数据、若干死脚本/陈旧文档。

## 2. 问题清单

- **[S2] release.yml 不校验 tag 与 5 处版本号一致性，错版发布无防护**
  - 位置：`.github/workflows/release.yml:117-123`（上传步骤，全程无版本比对步骤）；对比 `scripts/bump-version.ps1:71-75`（文档要求先 bump 再打 tag）
  - 问题：工作流只按 `v*` tag 触发，从不校验 tag 版本（如 `v0.3.0`）与 `tauri.conf.json` / `__init__.py` 中的版本（如仍 `0.2.3`）是否一致。一旦漏跑或误跑 `bump-version.ps1`，CI 会正常"成功"地把 0.2.3 构建的安装包发布到 v0.3.0 Release 名下。
  - 影响：安装包文件名/产品版本与 Release 版本错位；已装 0.2.3 的用户按 `update.check`（`__version__` 0.2.3 < tag 0.3.0）会永远提示"有新版本"，下载到的却是自己正在运行的版本，更新提示死循环，用户无法收敛到 up_to_date。
  - 修复建议：workflow 第一步解析 `${{ github.ref_name }}` 并读取 `core/src/lamtools_core/__init__.py` 的 `__version__`（以及 tauri.conf.json 的 version）做相等断言，不一致直接 `exit 1`；同时在 smoke test 步骤断言 `LamCore.exe` 文件版本。

- **[S3] spec hiddenimports 清单与代码库漂移：3 个幽灵条目 + ~40 个新模块未登记**
  - 位置：`core/lamtools-core-backend.spec:35-219`（清单）；对比 `core/src/lamtools_core` 实际 154 个 `.py` 模块（spec 注释仍写 "122 Core modules"）
  - 问题：① 幽灵条目 3 个——`lamtools_core.app.approval_continuation`、`lamtools_core.kernel.summary`、`lamtools_core.project.directory_picker` 在磁盘上不存在（`find` 确认无此文件），PyInstaller 每次构建都报 hidden import 警告；② 未登记的新模块约 40 个：`mem.*`（dreaming/memory_file/store）、`artifact.registry`、`runtime.workflow`/`workflow_watcher`、`project.workflow_store`、`app.workflow_operations`/`session_autotitle`、`tool.image_tools`/`workflow_tools`/`workflow_build_tools`/`search.*`（baidu/bing/duckduckgo/external/factory/protocol）、`config.agents_md`/`imagegen_store`/`retry_store`/`subagent_prompt`/`migrate_projects`、`llm.model_capabilities`、`update.checker`/`update.operations` 等。
  - 影响：当前不炸——逐一验证过这些模块均被静态 import 可达（`http_agent_app.py:29` 静态导入 `update.operations`，`default_toolbox.py:27` 静态导入 `tool.search`，search 引擎在 `factory.py:82-85` 函数级静态导入，`session_autotitle` 被 `core_session_store.py:13`/`live_operations.py:52` 导入，全库无 `importlib` 动态加载），PyInstaller modulegraph 会自动发现；CI 冒烟测试能兜住启动失败。但清单已失去"覆盖全模块"的语义：未来任何一处动态加载（字符串/importlib）都会静默缺模块，冒烟测试（只打 `/api/health`）也测不到懒加载路径。
  - 修复建议：用 `pyi-makespec`/`pyinstaller --collect-all lamtools_core` 或写个小脚本 diff `src/lamtools_core` 与清单，删除 3 个幽灵条目、补齐新模块，并把"清单必须与模块树同步"做成 CI 检查（或改为运行时兜底 `collect_submodules`）。

- **[S3] `update.check` 同步 HTTP 调用阻塞 FastAPI 事件循环最长 10 秒**
  - 位置：`core/src/lamtools_core/update/operations.py:24-27`（`async def update_check` 内直接同步调用 `check_update()`）；`core/src/lamtools_core/update/checker.py:62-76`（`httpx.Client` 同步、`REQUEST_TIMEOUT_SECONDS = 10.0`）
  - 问题：操作处理器是 async，但 `check_update()` 是阻塞式 `httpx.Client.get`（connect+read 共 10s 预算）。在事件循环线程直接执行，期间该进程所有其他 API/WS 请求全部排队。无网络（离线/被墙/超时）时设置页每点一次"检查更新"就全局冻结最多 10s。
  - 影响：桌面后端在弱网/离线环境下明显卡顿；`cli update check`（`cli.py:2265`）无此问题但同一函数。
  - 修复建议：`await asyncio.to_thread(check_update)`（或换 `httpx.AsyncClient`）；顺带可加并发去抖（同一次检查未完成时复用结果），避免连点。

- **[S3] 卸载器"删除应用数据"复选框实际不删除任何数据，且 APPDATA 路径与后端不一致**
  - 位置：`core/desktop/src-tauri/installer.nsi:890-906`（勾选后 `RmDir /r "$APPDATA\${BUNDLEID}"` / `"$LOCALAPPDATA\${BUNDLEID}"`，BUNDLEID=`com.lamtools.lamcore`）；对比 `core/desktop_backend.py:76-77`（无 LAMTOOLS_HOME 时的回退数据目录是 `%APPDATA%\LamCore`，产品名而非 bundle id）；green 模式下数据实际在 `$INSTDIR\.lam`（`core/desktop/src-tauri/src/main.rs:223` 设置 LAMTOOLS_HOME=app_dir/.lam），而卸载器对 `$INSTDIR` 只做非递归 `RMDir`（`installer.nsi:839-842`）
  - 问题：① 正常打包运行（Rust 恒设 LAMTOOLS_HOME）数据在 `$INSTDIR\.lam`，卸载器从不删它——勾选"删除应用数据"后数据完整残留；② 即便走了 APPDATA 回退，后端写 `%APPDATA%\LamCore`，卸载器删 `%APPDATA%\com.lamtools.lamcore`，路径对不上。
  - 影响：用户明确选择"删除数据"卸载后，聊天记录/配置/core.db 仍留在磁盘（隐私与预期不符）；复选框是无效 UI。
  - 修复建议：明确产品语义——若 green 模式数据随应用是设计（与"安装器不打包 .lam、更新不覆盖用户配置"一致），应把复选框文案/行为改为删除 `$INSTDIR\.lam`（卸载时可选），并统一后端 APPDATA 回退目录名与 BUNDLEID 一致（或干脆移除 APPDATA 回退）。

- **[S3] `dev.ps1` / `restart.ps1` / `start-core.ps1` 不设 PYTHONPATH，文档推荐的后端启动在未 pip install 环境静默失败**
  - 位置：`scripts/dev.ps1:32`、`scripts/restart.ps1:36`、`scripts/start-core.ps1:31`（`py -3.14 -m lamtools_core.cli serve ...` 均无 `$env:PYTHONPATH`）；对比 `scripts/core.cmd:4` 显式 `set "PYTHONPATH=%LAMTOOLS_ROOT%\core\src;..."`；文档 `docs/cli-guide.md:10` 明确推荐 `.\lamtools.cmd dev core backend`
  - 问题：`lamtools.cmd` → `lamtools_cli.py` → `dev.ps1` 链路中没有任何一环设置 PYTHONPATH；若开发机未执行 `pip install -e core[dev]`，`py -3.14 -m lamtools_core.cli` 直接 ModuleNotFoundError，且 `Start-Process` 后台启动无任何错误提示（窗口一闪而过），用户看到"后端没起来"但无原因。
  - 影响：新手按文档走 dev 流程时后端静默起不来，与 `core.cmd` 的行为不一致（同仓库两套入口一个设路径一个不设）。
  - 修复建议：三个脚本在 Start-Process 前统一 `$env:PYTHONPATH = "$Root\core\src" + ($env:PYTHONPATH ? ";$env:PYTHONPATH" : "")`，或复用 `scripts/core.cmd` 的探测逻辑。

- **[S3] `patch-nsis.ps1` 已死但仍被文档引用，且硬编码版本 0.2.2**
  - 位置：`scripts/patch-nsis.ps1:14`（`$OutExe = "...\LamCore_0.2.2_x64-setup.exe"` 硬编码）；`scripts/package.ps1:79-81`（注释明言"无需再跑 patch-nsis.ps1 做字符串手术"，模板已固化中文 UI）；`core/desktop/PACKAGING.md:22`（仍写"最后 `patch-nsis.ps1` 修补 NSIS 脚本"）
  - 问题：patch-nsis.ps1 的字符串手术已被 `src-tauri/installer.nsi` 自定义模板取代（git 历史 76252f5 引入模板），脚本无人调用；若有人按 PACKAGING.md 手动执行，会因版本硬编码 0.2.2 把产物复制成错误文件名，且其目标路径（`target/release/nsis/x64/installer.nsi`）在 tauri 新版本布局下不一定存在。
  - 影响：维护者被文档误导执行死脚本；版本硬编码与当前 0.2.3 漂移。
  - 修复建议：删除脚本或在头部加"已废弃"横幅并说明替代方案；同步修正 PACKAGING.md 第 22 行。

- **[S3] `bump-version.ps1` 同步失败仅打黄色 [SKIP]，不中断不报错，5 处版本可静默失步**
  - 位置：`scripts/bump-version.ps1:37-51`（`Update-File` 对缺失文件/模式不匹配返回 `$false` 只打印 [SKIP]），56-68 行五处调用均不检查返回值
  - 问题：任一文件缺失或格式漂移（如有人手改 `version = "0.2.3"` 为带引号变体、或新增第二处 `__version__`）时，脚本照常打印"=== Done ==="并给出 commit/tag 指引，退出码仍为 0。
  - 影响：发布者误以为 5 处已同步，实际版本漂移 → 更新检查误报/漏报、安装包版本错乱（与 S2 同源）。
  - 修复建议：任一 `Update-File` 返回 `$false` 时累计失败并在结尾 `exit 1`；同时可加"bump 后 grep 5 处应全部等于新版本"的最终断言。

- **[S4] `core/desktop/installer/installer.nsi` 是无人引用的陈旧模板副本，版本硬编码 0.1.0**
  - 位置：`core/desktop/installer/installer.nsi`（`!define VERSION "0.1.0"`，与 `src-tauri/installer.nsi` 大量重复但缺 handlebars 变量）；`tauri.conf.json:52` 实际引用 `src-tauri/installer.nsi`
  - 问题：仓库存在两份 installer.nsi，唯一生效的是 `src-tauri/` 下的 handlebars 模板；`desktop/installer/` 副本是早期硬编码版本，无人维护（版本仍 0.1.0）。
  - 影响：维护者误以为它是生效模板而修改它，改完发现不生效；硬编码版本误导版本审计。
  - 修复建议：删除副本，或在文件头加"已废弃，以 src-tauri/installer.nsi 为准"。

- **[S4] `scripts/start.bat` 引用不存在的 `members\writer\start.py`**
  - 位置：`scripts/start.bat:4`（`py -3.14 "members\writer\start.py"`）；仓库根无 `members/` 目录（仅 `.worktrees/`、`archive/` 残留）
  - 问题：members 体系已归档，start.bat 是遗留物，运行即"系统找不到指定的路径"。
  - 修复建议：删除；若仍需快速启动请改为调用 `start-core.ps1` 或 `lamtools.cmd dev`。

- **[S4] 仓库根遗留 `kill-lamcore.ps1` / `kill-port.ps1` / `check-port.ps1` 全部失效**
  - 位置：`E:\LamTools\kill-lamcore.ps1`（按进程名 `lamtools-core,lamtools-core-backend` 杀——旧 spec 产物名，现打包产物是 `LamCore.exe`，`lamtools-core-backend` 名已随 commit 2505e71 废弃）；`kill-port.ps1` / `check-port.ps1` 硬编码 PID 28220/35076
  - 问题：三个脚本匹配不到任何当前进程/端口，纯死代码。
  - 修复建议：删除，或改用 `scripts/restart.ps1` 的 netstat 按端口杀法（`LamCore.exe` 名也应纳入）。

- **[S4] `tool.verification` / `kernel.hooks` 无任何运行时引用，仅靠 spec hiddenimports 存在**
  - 位置：`core/lamtools-core-backend.spec:156,218`；全库 grep 确认 `tool.verification` 仅被 `tests/test_tool_verification.py` 引用，`kernel.hooks` 无任何 import 方（其 docstring 仍描述已归档的 Writer/Artist members）
  - 问题：这两个 hiddenimport 是 commit 0f7a3a6 防御性添加；模块本身在运行时不可达（无 importlib、无字符串引用）。若未来删除或重构，spec 会继续报幽灵条目（与第二条同源）。
  - 修复建议：确认这两个模块确属遗留后移除 hiddenimport 或从代码库删除；至少把 spec 注释里的"122 Core modules"改为自动生成。

- **[S4] PyInstaller 版本未固定，构建可复现性风险**
  - 位置：`.github/workflows/release.yml:52`（`pip install pyinstaller` 无版本约束）；本地 `scripts/package.ps1:44` 同
  - 问题：PyInstaller 主版本升级（如 6.x→7.x）可能改变 spec 字段语义/hook 行为，同 spec 在不同时间构建出不同产物。
  - 修复建议：固定 `pyinstaller==<pin>`（或 `~=`），并加入构建缓存/锁文件。

- **[S4] `bump-version.ps1` 不更新 `Cargo.lock` 中的 lamcore 包版本**
  - 位置：`scripts/bump-version.ps1:56-68`（仅 5 个文件）；`core/desktop/src-tauri/Cargo.lock:1643-1644`（`name = "lamcore"` / `version = "0.2.3"`）
  - 问题：bump 后 Cargo.lock 滞后到下次 `cargo build` 自动修正；若未来 CI 改用 `--locked` 会直接构建失败。当前 release.yml 用 `npx tauri build`（非 --locked），风险低。
  - 修复建议：bump 脚本顺手用 `cargo update -p lamcore` 或直接替换 Cargo.lock 中包版本。

- **[S4] spec 未打包 `skills/`，打包应用与 pip 安装行为不一致**
  - 位置：`core/lamtools-core-backend.spec:21-29`（datas 仅 desktop/dist、config/resources、config/command、config/llm_adapters）；`core/pyproject.toml:27-29`（wheel force-include 含 `"skills" = "lamtools_core/resources/skills"`）
  - 问题：wheel 安装版内置 `skills/observe-events`（`composer_commands.default_core_skill_roots` 可发现），PyInstaller 包内 `_MEIPASS/skills` 不存在 → 打包应用无任何内置 skill，仅剩用户 `.lam/core/skills`。当前 `composer_commands.py:42-52` 的 fallback 恰好让 config/command 在打包态可用，但 skills 缺失。
  - 影响：打包应用与 pip 版能力不一致；若内置 skill 属预期功能则打包应用缺失。
  - 修复建议：确认意图；若需要则在 `_datas` 补 `("skills", "skills")` 并同步 `default_core_skill_roots` 的打包路径解析。

- **[S4] 杂项：spec 死变量、package.ps1 步骤编号混乱、compare_versions 段数边界**
  - 位置：`core/lamtools-core-backend.spec:16`（`_PROJECT_ROOT` 定义后未使用）；`scripts/package.ps1:21,38,58,78`（标题分别为 "Step 1/3"、"Step 2/3"、"Step 3/4"、"Step 4/4"）；`core/src/lamtools_core/update/checker.py:44-59`（`compare_versions` 按数字段数比较，`"0.2.3"` vs `"0.2.3.0"` 返回 -1 视为更新，`"1.0"` vs `"1.0.0"` 同理）
  - 问题：前三者为纯观感/整洁问题；compare_versions 的段数差异在当前 tag 规则（`^\d+\.\d+\.\d+$`，bump-version.ps1:27 强制）下不会触发，但若未来允许 4 段版本会误判。
  - 修复建议：删 `_PROJECT_ROOT`；统一 package.ps1 为 Step x/3；compare_versions 对段数补齐 0 再比（或加单测锁定 x.y.z 假设）。

## 3. 该区 Top 3 问题

1. **[S2] 发布链无"tag ↔ 版本文件"一致性校验**（release.yml:117-123）——错版安装包会带着"永远有新版本"的更新死循环发布出去，且 CI 全程绿灯。
2. **[S3] PyInstaller spec hiddenimports 与代码库漂移**（spec:35-219）——3 个幽灵条目 + ~40 个未登记模块，当前靠静态分析"碰巧"兜底，是打包链路最大的长期演进风险；CI 冒烟测试只覆盖启动路径，覆盖不到懒加载模块。
3. **[S3] `update.check` 同步阻塞事件循环**（operations.py:24-27）——弱网/离线时设置页一次检查更新可冻结整个后端 10 秒。

## 4. 亮点

- **单一 spec 事实源**：`package.ps1` 与 `release.yml` 都 cd 到 `core/` 用同一份 `lamtools-core-backend.spec`（commit 2505e71 删掉了曾导致本地/CI 双 spec 漂移的根级旧 spec），spec 路径全部相对 spec 目录，`desktop_backend.py` 的 `_MEIPASS/config/*` 资源路径与 spec datas 一一对应。
- **CI 真冒烟**：release.yml 对打包后的 `LamCore.exe` 做"启动 + 轮询 `/api/health`"测试（随机端口 5300-5900、LAMTOOLS_HOME 指临时目录），比"二进制能起来"严格得多，能兜住 hiddenimports/数据文件缺失/默认配置播种问题。
- **版本 5 处当前完全一致（0.2.3）**：tauri.conf.json:4、Cargo.toml:3、desktop/package.json:4、pyproject.toml:7、`__init__.py:3` 全部同步；bump-version.ps1 的 5 个正则均能在现行文件上命中，且带 BOM 安全写入。
- **更新检查设计克制**：`checker.py` 所有网络/解析失败折叠为 `check_failed` 永不 raise（105 行注释明确策略）；无安装包资产的 release 视为 up_to_date 而非报错；下载 URL 直接取 GitHub API 的 `browser_download_url`，无手工拼接；`releases/latest` 天然排除 prerelease；配套 `tests/test_update_check.py` 覆盖相等/更新/过期/无资产/断网/`v` 前缀/段数 7 类场景。
- **用户数据保护语义闭环**：安装器不打包 `.lam`（tauri.conf.json resources 仅 `lamcore-backend`），`ensure_default_config_files` 幂等不覆盖用户编辑；安装目录经注册表 `RestorePreviousInstallLocation` 在更新时回到原安装位置，不会随 setup.exe 所在目录漂移；更新走"检测 + 引导下载"，不做未签名静默安装，风险自限。
- **AGENTS.md 与 defaults.py 声称完全对账**：播种清单（loadtools/access_tools/hooks/mcp/README 复制 + AGENTS/load_context/memory/model_retry/subagent 代码内默认）与 `defaults.py:110-144` 逐项一致。
- **端口假设全链路一致**：ports.json（5172/5173）↔ dev.ps1/restart.ps1 ↔ vite.config.ts（desktop:5173、ui 默认 5173）↔ tauri.conf.json devUrl ↔ `desktop_backend.py` 默认 5172 ↔ 各测试脚本默认 URL 全部吻合。

## 5. 审计范围与方法

- 范围：`core/pyproject.toml`、`core/lamtools-core-backend.spec`、`core/src/lamtools_core/update/`（checker.py、operations.py、`__init__.py`）、`core/src/lamtools_core/__init__.py`、`scripts/` 全部（package/build/dev/restart/test/bump-version/patch-nsis/lamtools_cli.py/lamtools.cmd/core.cmd/start.bat/start-core.ps1/ports.json/test-arrange-*）、`core/desktop/`（package.json、vite.config.ts、src-tauri/tauri.conf.json、Cargo.toml、Cargo.lock、installer.nsi、main.rs 相关段、PACKAGING.md、installer/ 旧副本）、根级 `lamtools.cmd`/`core.cmd`/`start-core.bat`/`kill-*.ps1`/`check-port.ps1`、`.github/workflows/release.yml` 与 `ci.yml`、`core/config/` 资源目录与 `config/defaults.py`（只核对播种清单与 AGENTS.md 声称）。
- 方法：全程只读。用 `find`/`grep`/`comm` 对 spec hiddenimports 与磁盘模块树做精确 diff；逐条验证"spec 未登记模块"的 import 可达性（静态 import 链、函数级 import、`importlib` 检索确认全库无动态加载）；核对 5 处版本号（含 Cargo.lock）；比对 PACKAGING.md/AGENTS.md 声称与实现（installer.nsi 模板、patch-nsis.ps1 调用链、播种清单）；检索 5172/5173 全仓引用与死脚本引用。未运行任何构建/打包命令，未修改任何代码文件。
