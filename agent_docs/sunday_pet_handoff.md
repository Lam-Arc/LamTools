# Sunday 桌宠 V1.0 交接说明（handoff）

写于 2026-10-30 晚。这一轮从「点击托盘打开桌宠」追到「黑屏 + 未响应」的根因，修了一批，还剩一个明确的拦路虎没有修完。

## 一、任务与分工

- 目标：在现有 Sunday 工程里把 Sunday 桌宠 V1.0 做到「自己能打开、能玩」的程度，不是交计划。
- 验收基线：`C:/Users/Administrator/Downloads/01_Sunday_桌宠_V1.0_设计方案.md` 与 `02_Sunday_桌宠_V1.0_功能清单.md`，P0 全过才算完成，P2 延期。
- 分工：我负责开发、编译、测试、修缺陷、环境；用户只做最终体验与产品意见。
- 硬边界：不许重启、终止、覆盖正式 Sunday 宿主（`lamcore.exe`，本轮是 PID 33916，会随重启变化，永远按「进程名 + 可执行路径」识别，禁止 `taskkill /IM lamcore.exe`）；只清理我自己起的开发实例。

## 二、清单位置

1. 本会话的计划清单：界面右侧「计划」区的 4 步（收集现场 / 判定成因 / 改代码 / 跑测试验证）。
2. 长期功能清单（必须与代码、测试对应，不许降标准）：`agent_docs/02_Sunday_桌宠_V1.0_功能清单_已填写.md`。
3. 本文件第三节就是下一轮的执行清单，按顺序做即可。

## 三、这一轮查实的根因（都有实测证据，不是猜）

| # | 根因 | 证据 | 状态 |
|---|---|---|---|
| 1 | 主窗口配置的 `additionalBrowserArgs` 会让 WebView2 建网页失败，报 `ERROR_INVALID_STATE (0x8007139F)` | 最小工程 `E:\petdiag` 加上同一串参数后启动直接 panic：`failed to create webview: WebView2 error: WindowsError(...0x8007139F)` | 已修（两个配置都删掉这串参数） |
| 2 | 覆盖层全程 `WDA_EXCLUDEFROMCAPTURE`（对截屏隐身）。全屏窗口一旦被排除出捕获，用户用 Radmin 远程看屏时就是整屏纯黑 | 桌面探测到本机在跑 Radmin Server；覆盖层 PrintWindow 恒为纯黑，而普通窗口能拍到内容 | 已修（改截图瞬间隐藏覆盖层 120ms） |
| 3 | 托盘「打开桌宠」在主线程同步建窗，事件循环要等窗口创建回话，形成死锁，表现为「点了就未响应」 | 代码路径 `handle_tray_menu` → `pet_overlay_open` → `WebviewWindowBuilder::build()` | 已修（挪到后台线程） |
| 4 | 启动早期建覆盖层窗口会拿到「半成品」窗口：所有窗口 API 返回 `FailedToReceiveMessage`、没有原生句柄，却留在窗口注册表里，把之后所有正常建窗全挡住 | 日志 `[pet] overlay window styling skipped ...`、`create pet window failed: a webview with label pet-overlay already exists` | 已修（运行期懒创建：`tauri.conf.json` 不再声明 pet-overlay 启动窗口，只在启动恢复/托盘/CLI 触发时建；运行期检测半成品就销毁重建；启动打开改为等就绪后重试） |
| 5 | 高 DPI 下窗口尺寸被多乘一次缩放：2048×1152 的屏幕被摆成 2560×1440，桌宠落到屏幕外 | 窗口枚举 `Sunday Pet rect=0,0,2560,1440`，屏幕实际 2048×1152 | 已修（`place_overlay` 设置后读回真实尺寸按比例修正，最多 4 轮） |
| 6 | 桌宠页面首次加载极慢：vite 冷启动要变换整个 UI 依赖图，实测 HTML 20:49:15 解析，到 20:49:58 才执行到 `pet.ts` | 探针服务器日志 `GET /hit-petdoc`（两次，含重载）与 `GET /hit-petjs`（一次，晚 43 秒） | **未修完，见第四节** |

顺带确认的两件事（避免下一轮重复怀疑）：

- 本机 Tauri 多窗口没问题：`E:\petdiag` 里三个窗口（含透明、隐藏、置顶、无边框）都能正常加载页面并执行脚本。
- 加了 `tauri-plugin-single-instance` 也不影响多窗口。
- 页面标题不能当作执行证据：Tauri 会保留配置标题，DOM 改标题不会反映到 `GetWindowTextW`。

## 四、下一轮清单（按顺序，做完即可看到桌宠）

1. **看门狗分两档**（`core/desktop/src-tauri/src/pet/mod.rs` 的 `poll_loop`）：页面首次联系前宽限 90 秒，一旦收到过心跳/命中矩形就退回 15 秒。现在写死 15 秒，把还在编译依赖的慢启动页面判死了。
2. **判死时不要 `stop_polling`**：现在判死会 `poll_running=false`，导致页面后来 ready 了也没有命中矩形轮询，桌宠即使显示也不可交互。改成只隐藏窗口并置穿透，轮询线程留着。
3. **`pet_overlay_ready` 里重启轮询并重新 `place_overlay`**：页面报到时确保 `start_polling` 在跑、窗口尺寸是对的。
4. **缩短首屏时间**（可选但建议）：`core/desktop/pet.html` 里给主模块加 `<link rel="modulepreload" href="./src/pet.ts">`，或把桌宠页拆成不依赖整个 UI 目录的独立入口，减少 vite 需要变换的模块量（实测 pet.html 的依赖图会把大半个 UI 拖进来）。
5. **交互与人格验收**：等页面能快速就绪后，验证命中矩形、拖拽、右键菜单、Ping 轮盘、会话卡片、气泡审批。
6. 收尾：`core/ui` 的 `npm run pet:test`（105 条）、`vue-tsc --noEmit`、`cargo test --bin Sunday pet::` 全绿；把 `agent_docs/02_Sunday_桌宠_V1.0_功能清单_已填写.md` 的状态按代码实测更新。

## 五、这一轮改动的文件

- `core/desktop/src-tauri/tauri.conf.json`：删 `additionalBrowserArgs`（改由 `pet::browser_args` 统一注入，配置窗口与运行时窗口共用同一份）；不声明 `pet-overlay` 启动窗口，覆盖层只由 Rust 懒创建。
- `core/desktop/tauri.pet-dev.conf.json`：同上（开发实例专用配置）。
- `core/desktop/src-tauri/src/pet/platform.rs`：去掉 `WDA_EXCLUDEFROMCAPTURE`；取窗口句柄加重试。
- `core/desktop/src-tauri/src/pet/mod.rs`：截图瞬间隐藏覆盖层；心跳与「页面判死」；穿透状态自愈；半成品窗口销毁重建；`place_overlay` DPI 修正；页面 ready 才显示；临时诊断日志（`[pet] diag window ...`，下一轮可删）。
- `core/desktop/src-tauri/src/main.rs`：托盘建窗挪后台线程；`--open-pet` 等就绪后重试建窗；注册 `pet_overlay_heartbeat`、`pet_overlay_ready`。
- `core/ui/src/pet/bridge.ts`：新增 `overlayHeartbeat()`、`overlayReady()`。
- `core/ui/src/pet/ui/usePetRuntime.ts`：boot 起心跳（2 秒一次）、ready 后双 rAF 再报 ready、shutdown 清定时器；标题写进度（排查用）。
- `core/desktop/src/pet.ts`：窗口标题写加载进度、全局错误与未处理拒绝写标题（排查用，可保留）。

## 六、怎么跑、怎么验

```bat
cd E:\LamTools\core\desktop
npm run pet:dev            :: 开发实例：vite 5299 + 后端 5298 + 数据目录 E:\LamTools\.lam-petdev，自动开桌宠
npm run pet:dev -- --no-open
npm run pet:verify         :: 105 条前端测试
npm run pet:e2e            :: 端到端（尚未跑通，见风险）
```

没有用户参与时的验收手段（这一轮用的就是这些）：

- 窗口枚举看 `vis` 与 `rect`（期望 `Sunday Pet` = `0,0,2048,1152`，可见即页面已报到）。脚本样例在 `.lam/artifacts/pet-diag/`。
- 探针法：页面里挂一个指向本地静态服务器的图片请求，服务端日志能区分「HTML 解析了」和「脚本执行了」。静态服务器用 `python -m http.server 8899`，注意工具的就绪探测要求服务根目录是工作区。
- 前端控制台留存：`core/data/core-agent/frontend-console.log`，每次页面启动会有一行 `developer console retention enabled`，数量就是「有多少个页面真的跑起来了」。
- 后端日志：`E:\LamTools\.lam-petdev\backend.log`。
- 证据文件（截图、抓取脚本）：`.lam/artifacts/pet-diag/`，含 `crawl.mjs`（抓模块图）、`cdp.mjs` / `eval.mjs`（CDP 读页面）、`webview2.ps1`（列 WebView2 进程）、`add-pet-window.cjs`（往配置里加窗口）。
- 对照工程：`E:\petdiag`（三窗口 + 单实例插件的最小 Tauri 工程，用来证明「多窗口能跑」）。

## 七、风险与坑

1. **端口残留**：`npm run pet:dev` 被强杀时，vite 会留在 5299，下次启动直接报「Port 5299 is already in use」。启动前先确认 5299/5298 空闲。
2. **单实例插件**：直接跑 `target\debug\Sunday.exe` 会因为标识和正式版相同（`com.lamtools.sunday`）被单实例挡掉，表现为进程一闪而过。要单独跑必须用 `tauri.pet-dev.conf.json` 构建的实例。
3. **远程看屏**：用户是通过 Radmin 之类的抓屏方式看桌面的，任何「对截屏隐身」的窗口都会变成整屏黑。以后不要再给全屏覆盖层加 `WDA_EXCLUDEFROMCAPTURE`。
4. **端到端未跑通**：`npm run pet:e2e` 受 `DevToolsActivePort` 问题影响还没通，原因是没有给自动化单独准备不带额外浏览器参数的窗口。
5. **正式实例不可动**：本轮只杀 `Sunday.exe`（开发实例）与我自己起的 vite / 探针服务器，`lamcore.exe` 始终未碰。
6. **`pet.html` 依赖太重**：桌宠页把整个 `@/pet/**` 都拉进来，vite 首次变换很慢。这是慢启动的根源，长远应拆独立入口。
