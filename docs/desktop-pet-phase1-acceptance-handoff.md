# Desktop Pet Phase 1 — 当前验收交接

日期：2026-08-23
分支：`feat/desktop-pet-phase1`
状态：实现已在本地特性分支，人工验收因已确认的阻塞问题暂停；本文件用于交给后续修复对话，不代表 Phase 1 已完成。

## 当前边界

- 本交接只覆盖 Agent 全局桌宠 Phase 1。
- HTTP probe 和 CI 的分流问题不属于本交接，不要在这里重新处理或混入修复。
- 当前没有托盘驻留能力，因此主窗口右上角 X 的产品语义必须是“完整退出”，而不是隐藏主窗口。
- 不要把当前人工验收失败当成用户操作错误；以下问题都应先在代码和自动化验证中处理，再重新找用户做最终体验验收。

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

## 之前人工反馈、需要后续统一回归

这些问题在前序验收中出现过，部分曾有局部修复或自动化验证，但在当前阻塞问题修复后必须重新确认，不得直接视为已交付：

- 左键单击桌宠是否稳定打开主窗口；等待事项时是否打开 overlay。
- 右键 overlay 的连接状态、打开主窗口按钮是否真正可用。
- 主窗口“显示桌宠”和 overlay“显示桌宠”的开关是否双向同步。
- overlay 圆角/透明窗口边缘是否四角一致，不出现白色或弧度不匹配。
- 桌宠拖动在不同 DPI、显示器和抓取位置下是否保持鼠标与图片 1:1 跟手；此前已有原生拖动与 DPI 自动化检查，但仍需最终 Tauri 人工回归。
- 宠物切换、透明度、大小、位置保存、多显示器恢复和重启后的设置读取。
- running、waiting/ask-user、approval、error 四种状态及 waiting 队列、错误气泡。

## 后续接手顺序

1. 先修复授权事项重复投影和错误的 `turn/start` 路由，并补单元/集成回归测试。
2. 再修复“操作失败误报未连接”的连接状态展示。
3. 修复运行中测试的 malformed tool-call 参数链路，至少能用稳定的测试任务触发 running。
4. 实现应用级完整退出并验证开发重启不再锁定 `lamcore.exe`。
5. 修复并回归前述 UI/交互问题，重新启动 Tauri 做完整人工验收。

## 当前验收结论

本轮人工验收停止。当前不能声明“可交付”，也不能合并到 `main`。后续代理应以本文件中的阻塞问题为准继续修复，修复完成后再由用户做最后一轮人工测试。
