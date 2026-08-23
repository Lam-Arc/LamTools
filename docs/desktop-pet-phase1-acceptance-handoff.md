# Desktop Pet Phase 1 — 当前验收交接

日期：2026-08-23
分支：`feat/desktop-pet-phase1`
状态：实现已在本地特性分支，人工验收因已确认的阻塞问题暂停；本文件用于交给后续修复对话，不代表 Phase 1 已完成。

远端：`origin/feat/desktop-pet-phase1`

实现快照：`3a65530`（桌宠实现、3 套资源、测试和首版交接）

基线：`origin/main` 的 `7627083`；当前没有 PR，也没有合并到 `main`。

后续代理只需拉取上述分支并完整阅读本文件，即可继续修复；不应要求用户重新讲述本轮对话。

## 当前边界

- 本交接只覆盖 Agent 全局桌宠 Phase 1。
- Windows HTTP probe、既有 UI 合同测试失败和远端 CI 错误已经分流到其他对话，不属于本交接；不要在这里重新处理或混入修复。但最终合并前仍需确认这些分流事项已经闭环，不能把“分流”误当成“已通过”。
- 当前没有托盘驻留能力，因此主窗口右上角 X 的产品语义必须是“完整退出”，而不是隐藏主窗口。
- 桌宠右键快速设置中的“隐藏桌宠”只隐藏 `pet` 和 `pet-overlay`，不退出 Core；隐藏后必须能从 Main 标题栏/设置页重新启用。overlay 自己的 X 只收起面板，waiting 提醒仍保留。以上三种关闭语义不能混用。
- 不要把当前人工验收失败当成用户操作错误；以下问题都应先在代码和自动化验证中处理，再重新找用户做最终体验验收。
- 原任务书的产品和架构决策仍然有效；不要缩小范围、重做 Phase 2 设计或新增托盘语义。

必须继续遵守的架构边界：Core 是事实与执行源，Pet 只做聚合、展示和入口；保持一个 Tauri 进程和一个 LamTools Python Backend；复用现有 Runtime、Snapshot、Event Hub、Operation Catalog、`approval.respond` 和 Main composer 语义；设置仍写入 `.lam/core/config/settings.jsonc` 的 `core.pet`，Pack 根目录仍由 LamTools 数据根推导为 `.lam/core/pets/`，默认播种不得覆盖用户修改。禁止新增第二套 Agent Runtime、审批系统、Session 状态、Python 后端、独立桌宠程序、配置数据库或平行 Event Bus。

Phase 1 明确不包含：Pet Agent/PET Tools、跨 Session 自然语言管控、`send_message_to_session`、`stop_session`、AI 生成或上传图片生成桌宠、Live2D、养成/复杂互动、插件市场和云同步。

## 已确认的阻塞问题

### 1. 运行中测试无法稳定触发

第一次人工测试反复出现：

```text
Model tool arguments were incomplete or invalid JSON and were not executed
(finish_reason=tool_calls, received=34 chars).
```

这说明模型尝试调用工具，但 Core 收到的参数不是完整 JSON，因此安全地拒绝执行。该问题发生在 Agent 工具调用/流式参数拼接链路，不是桌宠窗口本身；这次测试没有真正形成可验收的 running 任务。

后续需要检查当前模型供应商的 tool-call 输出、流式 delta 合并和失败后的恢复路径。不要仅把错误显示成最终失败就算处理完成，也不要把这次测试算作通过。

### 2. 一个授权请求被桌宠显示成两个待处理事项

第二次人工测试的截图显示：

- 面板显示“当前处理 1 项，共 2 项”；
- 当前卡片标题是 `Input needed`；
- 内容是“需要授权后才能执行工具：question”；
- 用户提交后又显示“未连接到后端”。

根因已从代码确认：

1. Kernel 在工具需要授权时，同时写入 `pending_approval` 和 `pending_waiting_request`（`core/src/lamtools_core/kernel/loop.py` 约 780 行）。
2. Pet 投影层把这两个字段当成两个独立的 `PetInteraction`（`core/src/lamtools_core/app/pet.py` 约 614 行）。
3. 面板把 generic waiting 项误判成普通 ask-user，提交时调用 `turn/start`，而不是对原始授权调用 `approval/respond`。
4. 面板的 `respond` 捕获任何操作失败后都直接把连接状态设置为 `error`，因此业务请求被拒绝时也会伪装成“未连接到后端”（`core/ui/src/pet/PetOverlayApp.vue` 约 180 行）。

后续修复要求：

- 一个逻辑授权请求只能投影为一个桌宠事项；`pending_approval` 与对应的 permission waiting 不能重复计数。
- 授权事项必须走 `approval/respond`；真正的 ask-user 才走 `turn/start`。
- 只有 WebSocket 真正断开/连接失败时才显示连接错误；业务错误、请求超时和审批状态冲突要显示真实原因并保留可恢复路径。
- 增加回归测试：同一工具授权同时存在两个 metadata 字段时，Pet overview 的 `waiting_count` 必须为 1，且返回类型必须是 approval。

### 3. 主窗口右上角 X 没有完整退出

当前主标题栏 X 调用的是当前 WebView 的 `window.close()`；Rust `close_window` 也只关闭传入的那个窗口。桌宠和 overlay 是同一 Tauri 进程中的另外两个窗口，主窗口关闭后它们仍可能存活，因此 `lamcore.exe` 继续占用自己的开发构建文件。

这直接导致过一次 Windows 编译错误：

```text
failed to remove ...\\src-tauri\\target\\debug\\lamcore.exe
拒绝访问。 (os error 5)
```

这次现场已经确认过残留进程：旧 `lamcore.exe` 由对应 Cargo 开发进程启动；进程已被定向停止，未执行全局无差别杀进程。

后续修复要求：

- 增加应用级退出命令，关闭 `pet-overlay`、`pet`、`main` 并停止后端，再退出 Tauri 进程。
- 主窗口右上角 X 调用应用级退出，而不是只关闭 `main`。
- 退出路径要覆盖桌宠/overlay 已显示、隐藏、正在连接和正在拖动等状态。
- 当前没有托盘，所以不要把 X 实现成 hide/minimize-to-tray。
- 增加开发重启回归：点击 X 后，`lamcore.exe`、Cargo 子进程和后端都退出，下一次 `npm run tauri dev` 不会因文件锁失败。

本轮结束前还发现并清理了 15 组遗留的 `py -3.14 -m lamtools_core.cli serve --port <随机端口>` 进程。一个正在运行的应用对应一个后端是正常现象；应用已经退出后仍有一个或多个后端监听则是不正常现象。后续验证必须同时检查 Tauri 壳、开发 runner 和 Python 后端，不得只看窗口是否消失。

## 精确人工反馈记录

以下是用户在 Tauri 真机验收中明确报告过的现象。后续代理不得只根据上面的概括修三处代码后就宣布完成：

- 左键单击桌宠不能稳定打开/聚焦 Main；右键面板中的“打开 LamTools 主窗口”也曾点击无反应。
- 右键 overlay 曾长期停在“正在连接”或显示未连接 Core；最新一次提交回答后的“未连接”又确认包含业务错误被误报为连接错误的情况。
- 主标题栏“桌宠”开关和 overlay“显示桌宠”复选框曾不同步：从 Main 打开桌宠后，overlay 复选框没有自动勾选。
- Main 的桌宠开关曾出现“先显示为开启，随后闪回关闭”；隐藏后重新打开时，窗口出现但宠物图片不显示。
- overlay 四个圆角/透明窗口边缘曾出现白边和弧度不一致，视觉上明显不统一。
- 拖动曾被 WebView 当成普通图片拖拽，出现图片拖动幽灵/复制到桌面的行为；之后虽加入 `draggable=false` 和原生拖动，但用户仍实际观察到鼠标移动约 2 cm、宠物只移动约 1 cm，抓取点与宠物分离。必须在不同 Windows 缩放、DPI、显示器和抓取位置下验证真正 1:1。
- 透明度、大小和宠物切换曾在一次人工测试中正常，但另一次测试又出现角色透明表现异常；这些只能视为需要回归，不能视为稳定通过。
- 主窗口 X 关闭后 `lamcore.exe`/Cargo/后端仍可能存活，导致下一次编译无法替换 `target/debug/lamcore.exe`。

## 已有实现范围

当前分支已经包含以下实现，后续应在此基础上修复，不要另起第二套系统：

- Core Pet settings、Pack loader、Overview reducer/service、全局 Event Hub 订阅、overview/packs operation。
- `pet status`、`pet config`、`pet packs` CLI。
- Tauri `pet` 和 `pet-overlay` 窗口、定位/拖动、显示隐藏、聚焦 Main 等命令。
- Main 标题栏/设置入口、Pet UI、overlay、状态动画、队列和连接客户端。
- default-cat、default-fox、default-robot 三套 PNG 资源、template、README、资源构建/透明度修复脚本。

已知架构偏差：原任务书要求不要继续把全部桌宠窗口逻辑塞进 `main.rs`，建议拆成 `pet.rs`、`pet_window.rs`、`pet_position.rs`；当前仅拆出了 `pet_position.rs`，大量桌宠协调逻辑仍在 `main.rs`。后续应评估并完成合理拆分，至少不能继续扩大 `main.rs`。

## 之前人工反馈、需要后续统一回归

这些问题在前序验收中出现过，部分曾有局部修复或自动化验证，但在当前阻塞问题修复后必须重新确认，不得直接视为已交付：

- 左键单击桌宠是否稳定打开主窗口；等待事项时是否打开 overlay。
- 右键 overlay 的连接状态、打开主窗口按钮是否真正可用。
- 主窗口“显示桌宠”和 overlay“显示桌宠”的开关是否双向同步。
- overlay 圆角/透明窗口边缘是否四角一致，不出现白色或弧度不匹配。
- 桌宠拖动在不同 DPI、显示器和抓取位置下是否保持鼠标与图片 1:1 跟手；此前已有原生拖动与 DPI 自动化检查，但仍需最终 Tauri 人工回归。
- 宠物切换、透明度、大小、位置保存、多显示器恢复和重启后的设置读取。
- running、waiting/ask-user、approval、error 四种状态及 waiting 队列、错误气泡。

## 原任务书完成门槛及当前状态

下表是原始 Phase 1 完成定义的完整收敛版。没有一项可以因为“代码看起来存在”而跳过验证：

| # | 完成门槛 | 当前交接状态 |
|---|---|---|
| 1 | 真正的 Windows 独立悬浮 Pet；透明、置顶、无任务栏、最小命中区域 | 已实现主体，Tauri 人工验收未完成 |
| 2 | `idle/running/waiting/error` 四状态实时正确、序列帧明显可区分 | 未完成真实状态 E2E |
| 3 | 固定优先级 `waiting > error > running > idle` | reducer 有基础测试，组合 E2E 未完成 |
| 4 | Main 后台时 approval 可直接在 Pet 完成 | 当前阻塞：重复投影和错误响应路由 |
| 5 | Main 后台时 ask-user 可直接在 Pet 完成，效果与 Main composer 相同 | 当前阻塞：提交路径/连接错误未闭环 |
| 6 | Main 前台不重复弹；重新聚焦时主动 overlay 收起 | 未完成真机 focus 路由验收 |
| 7 | 多 waiting 按时间稳定排序、去重、不丢失；成功后等服务端确认再进入下一条 | 当前重复计数，3 Session E2E 未做 |
| 8 | 当前周期 error 提醒、不强弹，点击可定位 Project/Session；历史 error 不污染 | reducer 有部分测试，导航 E2E 未做 |
| 9 | 左键、拖动、右键、scale、opacity、hide/reopen 正常 | 多项人工问题待修/回归 |
| 10 | 多显示器恢复、拔屏 fallback、越界 clamp、不同 DPI 正确 | 原生拖动有纯逻辑检查，完整真机未验收 |
| 11 | `enabled=false`、位置和设置在重启/升级后保留，不被默认资源覆盖 | 有部分设置测试，重启/升级人工验收未完成 |
| 12 | 2～3 套默认 Pack 四状态可用 | 已提交 3 套资源，四状态视觉/打包读取仍需验收 |
| 13 | 自定义 Pack、坏 Pack、缺状态、路径逃逸、fallback 正常 | loader 有基础测试，Main/Pet 真机流程未验收 |
| 14 | GUI 非视觉语义有同源 CLI | CLI 已实现，完整 CLI 合同测试未证明 |
| 15 | Python、UI、Rust 和相关合同测试完整通过 | 仅有局部通过记录，见下节缺口 |
| 16 | Tauri dev 与 packaged Windows 真机人工验收通过 | 未完成；本轮人工验收已停止 |
| 17 | Pet 崩溃、坏资源、断连、Vue 异常均不影响 Core/Agent/审批/SQLite | 故障隔离 E2E 未完成 |

另外仍必须验证：用户隐藏 Pet 时所有 Pet 提醒停止但 Core 不受影响；重新启用后重新读取最新 overview；error 只表示当前应用周期的新失败；状态变化通过 overview diff/global subscription 推送，不能高频轮询或把 token delta 推给 Pet；reduced-motion 下信息仍清晰且状态不能只靠颜色表达。

## 自动化与验证证据边界

此前执行记录显示以下局部检查曾通过：Desktop `npm run build`/类型检查、`cargo check`、`cargo test`（3 个纯逻辑测试），以及一组相关 Python 定向测试（37 个通过，带既有 warning）。这些结果发生在最新人工验收前后代码基本稳定的阶段，但没有作为完整日志产物提交；接手方应重新运行并保存最终结果。

当前明确缺口：

- 没有完成原任务书要求的完整 `pytest`。
- 分支中没有新增 Pet 专属 UI contract/Vitest 测试；sprite、queue、dedupe、bubble、点击、settings、fallback 等前端合同覆盖不足。
- Rust 目前只有 overlay anchor/position 一类 3 个纯逻辑测试，opacity/scale clamp、monitor fallback、应用级退出没有完整覆盖。
- approval/ask-user 的真实 `Agent waiting → Pet → user → Core → Agent continue` E2E 没有通过。
- 没有完成 packaged Windows build/install/运行验证，也没有证明退出后不残留进程。
- 没有完成 3 Session waiting、状态优先级、Main focus、error 导航、多显示器、持久化、自定义/坏 Pack、故障隔离和长时间运行验证。

Tauri 是唯一 UI 验收环境。Vite 浏览器页面、静态截图、单元测试或进程日志都不能替代最终 Tauri 真机验收。

## 开发启动与进程注意事项

- 从 `core/desktop` 运行 `npm run tauri dev`；必须由接手方自己保留对应终端。
- `devUrl` 固定为 `127.0.0.1:5173`。若 5173 被占用，Vite 跳到 5174，Tauri 仍会加载 5173 的错误页面；启动前先确认没有旧 Vite。
- 当前分支已经包含 Vite 固定监听 127.0.0.1、忽略 `src-tauri/target`、补 `PYTHONPATH` 和修正 Core 目录定位等开发启动修复。
- 在应用级退出修复前，关闭窗口后还要检查 `lamcore.exe`、Cargo/Vite 和 `lamtools_core.cli serve`；不要无差别结束系统中所有 Python/Node/Cargo，只处理确认属于本仓库的进程树。

## 后续接手顺序

1. 先修复授权事项重复投影和错误的 `turn/start` 路由，并补单元/集成回归测试。
2. 再修复“操作失败误报未连接”的连接状态展示。
3. 修复运行中测试的 malformed tool-call 参数链路，至少能用稳定的测试任务触发 running。
4. 实现应用级完整退出并验证开发重启不再锁定 `lamcore.exe`。
5. 补齐原任务书要求的 UI/Rust/Python 自动化覆盖并运行完整验证。
6. 修复并回归前述 UI/交互问题，完成 Tauri dev 与 packaged Windows 验收。
7. 由未参与主要实现的独立代理再次对照本文件和原始完成门槛复核；主代理修复遗漏后，才邀请用户做最后一轮最小人工验收。

## 当前验收结论

本轮人工验收停止。当前不能声明“可交付”，也不能合并到 `main`。后续代理应以本文件中的阻塞问题、精确人工反馈和 17 条完成门槛为准继续修复，修复完成后再由用户做最后一轮人工测试。接手方不需要读取本对话才能理解当前状态；若代码证据与本文件冲突，以现场代码和可复现结果为准，并更新本文件。
