# Computer Use 技术方案

调研时间：2026-11-09。范围：桌面端 Windows，只做本机，不考虑移动端。

## 结论

这个项目做 computer use 不是从零开始。屏幕捕获、多显示器与 DPI、窗口枚举、全屏穿透覆盖层、全局热键、工具审批分级都已有可用实现，缺的是三件事：把鼠标键盘真正注入系统、拿到界面元素的语义信息、把「看屏幕、做动作、再确认」串成 Agent 闭环。

路线选混合式：以无障碍树为主、视觉坐标为辅，截图始终保留用于验证。业界 2026 年的成熟实现都走这条路，纯像素猜坐标的准确率撑不住长任务。

## 一、现状盘点

### 已经有的

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 显示器枚举与 DPI | `core/desktop/src-tauri/src/pet/platform.rs` | EnumDisplayMonitors，返回 id、虚拟桌面坐标、物理尺寸、scale |
| 光标位置 | 同上 | GetCursorPos，物理像素 |
| 全屏截图 | 同上 | BitBlt 抓整块显示器，BGRA 转 RGBA，负高度自上而下 |
| 截图 IPC 编码 | 同上 | 自定义 PETC 帧头加原始像素，24 字节头 |
| 窗口枚举 | 同上 | EnumWindows，含标题、类名、bounds、Z 序，可按进程排除自身 |
| 穿透覆盖层 | `core/desktop/src-tauri/src/pet/mod.rs` | 全屏透明窗口，NOACTIVATE，轮询线程按命中矩形切换 set_ignore_cursor_events |
| 命中区域 | 同上 | pet_set_interactive_rects，按物理像素矩形决定哪里可点 |
| 置顶与置底 | 同上 | pet_set_z_mode，桌面地形与压底模式 |
| 全局热键 | 同上 | pet_hotkey_set，复用为紧急停止入口 |
| 独立截图窗口 | 同上 | 可激活、可 Esc 退出、5 秒心跳看门狗兜底 |
| 窗口关闭 | `core/desktop/src-tauri/src/windows_close_request.rs` | 已有 PostMessage WM_CLOSE 的处理经验 |
| 工具审批分级 | `core/src/lamtools_core/tool/operation_levels.py` | 按操作判 1、2、3 级，不按工具类型一刀切 |
| 图片进入模型 | `core/src/lamtools_core/llm/image_payload.py` | 图片块识别、过期图片降级为小 JPEG |
| 本地 WebSocket 服务 | `core/sunday-core/crates/sunday-host/src/app_server.rs` | core.app_server.v1，前端已能直连 |
| 工具注册方式 | `core/src/lamtools_core/tool/default_toolbox.py` | ToolSpec 加 handler，同步登记 operation_levels |

### 缺的

1. 输入注入：鼠标移动、按下抬起、拖拽、滚轮、键盘与组合键，目前一处都没有。
2. 界面语义：UIA 无障碍树读取，现在只能靠像素。
3. 窗口控制：激活到前台、移动、调整大小，只有关闭的雏形。
4. Agent 工具与循环：感知、动作、等待稳定、失败重试、终止条件。
5. 体验层：操作目标高亮、进度、暂停、用户接管、回放。
6. 截图与覆盖层互相污染：现有做法是截图前隐藏覆盖层再等 120 毫秒，连续截图会闪。
7. 安全边界：危险动作识别、提权窗口限制、审计日志。

## 二、两条路线的取舍

### 纯视觉路线

截图交给视觉模型，模型输出归一化坐标，程序换算成物理像素后注入。

优点是对自绘界面、游戏、远程桌面、跨平台应用都有效，实现量小。缺点是模型估坐标不稳，小控件点偏几十像素就全错；每步一张图，长任务成本和延迟都高；出错时无法自证，只能再截一张看。

### 无障碍树路线

读 Windows UIA 树，得到控件角色、名称、边界、可用动作，给每个元素一个稳定 ref，模型按 ref 操作。

优点是准、可验证、token 省，动作可以直接落到元素而不是坐标。缺点是很多应用树残缺：Electron 默认不暴露完整树，自绘界面和游戏完全没有树，部分 Java 应用需要桥接。

### 采用混合

一次快照同时返回截图和树。树里有目标就用 ref 操作，没有就退回坐标。无论哪条路，动作执行后都重新截图确认，不信任返回码。这也是 Vercel agent-desktop 和 Codex Windows 的做法。

## 三、目标架构

### 分层

```
体验层    覆盖层高亮 / 动作轨迹 / 进度 / 暂停接管 / 审批
决策层    Agent 工具 + 系统提示 + 循环控制 + 失败升级
执行层    input.mouse / input.key / input.scroll / window.focus
感知层    screen.capture / windows.list / uia.tree
```

### 进程归属

原生能力放 Rust 侧，原因有三个：UIA 是 COM 接口，Rust 的 windows crate 比 Python 用 ctypes 拼 COM 干净得多；SendInput 和截图都是低层调用，放 Rust 便于统一做坐标校验；项目正在渐进式 Rust 重构，这部分能力天然属于 `core/sunday-core/crates/sunday-platform` 的端口抽象，后续可以换实现而不动上层。

Python 工具层只做薄封装，通过本机回环服务调用 Rust。鉴权用启动时生成的一次性 token，只监听 127.0.0.1。不走「前端转发」，前端不在线时功能会失效。

如果只想先用最快方式验证可行性，可以第一版直接在 Python 用 ctypes 调 user32 和 gdi32 做截图与注入，Rust 只负责覆盖层。验证通过后再把实现迁到 Rust，接口保持不变。

## 四、工具契约

建议七个工具，名字和参数稳定后不要轻易改，模型靠它们形成习惯。

### screen_capture

参数：target 取 screen、monitor、window、region；monitor_id；window_id；region；max_width 默认 1280。
返回：图片块，加上物理像素宽高、显示器原点、scale、采集时间。

### ui_snapshot

参数：window_id 可选，depth 默认 4，include_offscreen 默认 false。
返回：窗口列表，加元素数组。每个元素给 ref、role、name、bounds、states、actions。

### ui_click

参数：ref 或 x、y；button 取 left、right、middle；count；modifiers。
执行前校验目标窗口在前台，ref 失效则重新快照一次再试。

### ui_type

参数：text；mode 取 unicode、keys、paste；ref 可选。
unicode 用 KEYEVENTF_UNICODE 直接发字符，绕开输入法。paste 走剪贴板，适合长文本。

### ui_key

参数：keys 数组，例如 ["ctrl","shift","t"]；repeat。

### ui_scroll

参数：ref 或 x、y；delta；axis。

### ui_drag

参数：from 与 to，各支持 ref 或坐标；duration。

### computer_task

参数：action 取 start、status、pause、resume、stop；goal；limits。
这个工具是给用户看的：任务编号、当前步骤、已用步数、剩余预算、暂停原因。

分级登记到 `operation_levels.py`：第一版全部动作按 1 级放行，不再逐动作弹审批。user:“无需做安全边界”+(用户要求去掉拦截后改成这样)。

## 五、循环怎么跑

每一步固定顺序：

1. 快照，同时拿到截图与元素树。
2. 模型输出一个动作，必须带目标 ref 或坐标，以及一句预期结果。
3. 校验动作合法：目标窗口仍是那个窗口，坐标落在虚拟桌面内，动作在本次任务允许的等级内。
4. 注入。
5. 等待界面稳定：像素差异小于阈值且树结构不再变化，最多等 1.5 秒，不用固定 sleep。
6. 再快照，比对预期。不符合就把失败原因带回模型，最多重试三次。
7. 三次仍失败，停止并请用户接手，附上最后两张截图。

硬性限制：单任务步数上限默认 40，超时上限默认 10 分钟，成本上限按 token 算。任何一步用户输入真实鼠标键盘就立即暂停。

## 六、关键坑

**坐标必须全程用物理像素。** 截图给的是物理像素，SendInput 的绝对坐标要按虚拟桌面归一化到 0 到 65535。这台机器 150% 缩放，逻辑坐标和物理坐标一混用就必然点偏，这条已经在 `ops/windows-window-capture-dpi.md` 里踩过。

**覆盖层会污染截图。** 现有实现是截图前隐藏覆盖层、等 120 毫秒、截完再显示。computer use 每步都截图，这样会持续闪烁。三个处理方向：任务运行期间干脆不显示覆盖层；只在动作前后短暂显示；改用 Windows.Graphics.Capture 采集并排除自身窗口。第三种最干净，但要新写采集代码。

**前台锁限制。** SetForegroundWindow 有前台锁，后台进程直接调用经常失败，需要 AttachThreadInput 或模拟一次 Alt 键。提权窗口和 UWP 应用不接受普通权限进程的注入，必须检测出来明确报错，不要让模型反复重试。

**输入法。** 中文用 KEYEVENTF_UNICODE 逐字符发送最稳，绕开输入法状态。但游戏和部分自绘控件只认虚拟键码，需要保留 keys 模式。

**树为空的应用。** Electron 默认不暴露完整无障碍树，自绘界面和游戏完全没有。遇到就自动退回视觉路线，不要在这里卡住。

**用户接管。** 用低级键盘鼠标钩子或 GetAsyncKeyState 轮询检测真实输入，命中即暂停任务并归还控制权。现有 `platform.rs` 已经用 GetAsyncKeyState 做 Esc 兜底和组合热键检测，可以沿用同一手法。

**截图体积。** 4K 全屏 PNG 有数 MB，先缩到 1280 宽再进模型，原图存成产物留证据。现有 `llm/image_payload.py` 会对过期图片降级，但首帧还是要自己控制大小。

## 七、分阶段落地

### 阶段一，最小闭环

做 screen_capture、ui_click、ui_type、ui_scroll 四个工具，第一版用 ctypes 直接调 user32 和 gdi32，坐标全程物理像素。

验收：让 Agent 打开记事本、输入一段中文、保存到桌面。全程有截图证据，动作日志可回放。

### 阶段二，提准与稳定

Rust 侧补 UIA 树读取与元素 ref，补窗口激活与焦点校验，补稳定检测与失败重试。

验收：在 Chrome 里搜索并打开指定网页；在系统设置里改一个开关；两次任务都不点偏。

### 阶段三，体验

覆盖层显示当前动作目标、鼠标轨迹、进度与暂停按钮。任务卡片可回看每一步截图。

验收：用户中途动鼠标能立刻接管，恢复后从当前界面状态继续，而不是从头开始。

### 阶段四，边界

危险动作审批、应用白名单、审计日志、多显示器与远程桌面场景。

验收：删除文件、发送消息、支付类目标都被拦下并要求确认，审计日志能完整还原一次任务。

## 八、待决策

1. 原生能力放 Tauri 侧还是 `sunday-platform` 端口。放 Tauri 上手快，放端口抽象后续迁移成本低。
2. 是否允许后台窗口操作。用 PostMessage 注入可以不动真实鼠标，不打扰用户，但兼容性明显差。
3. 视觉模型选型。坐标定位能力需要实测，当前模型是否够用还没有数据。
4. 复用桌宠覆盖层还是新建独立覆盖层。复用省事，但桌宠和 Ping 已经占了两个全屏窗口，再加一个容易互相干扰。

## 九、验收测试怎么写

按项目规则先写测试再实现：

- 坐标换算单测：逻辑坐标、物理坐标、虚拟桌面负原点、多显示器拼接。
- 动作校验单测：越界坐标、失效 ref、窗口已切换时都必须拒绝执行。
- 覆盖层不污染截图：隐藏前后截同一屏，像素应一致。
- 用户接管：模拟真实输入事件，任务状态必须从 running 变 paused。
- 审批分级：点击、输入落在 2 级，关闭窗口与危险目标落在 3 级。
- 真实注入只做集成测试，不进单测，避免测试机被乱点。

## 十、实现结果

第一版已落地，能力、工具、界面、验证四块都在。

### 代码位置

- `core/src/lamtools_core/computer_use/win32.py`：显示器、窗口、截图、SendInput、前台激活、用户输入检测、剪贴板
- `core/src/lamtools_core/computer_use/capture.py`：PNG 编码、缩放、网格与落点标注、data URL
- `core/src/lamtools_core/computer_use/uia.py`：常驻 PowerShell 助手，带超时重启
- `core/src/lamtools_core/computer_use/uia_helper.ps1`：UIA 读树与语义点击，UTF-8 BOM
- `core/src/lamtools_core/computer_use/session.py`：任务状态机、步数与超时、用户接管
- `core/src/lamtools_core/computer_use/tools.py`：computer_use 工具的十三个动作
- `core/ui/src/components/ComputerUseBar.vue`：右下角任务状态条，暂停、继续、结束
- `core/tests/test_computer_use.py`：40 项单元与装配测试
- `core/scripts/verify_computer_use.py`：真实桌面端到端验收脚本

### 与原方案的差异

UIA 没有走 Rust，改成常驻 PowerShell 助手。原因是 PowerShell 直接调用 .NET 的 UIAutomationClient，比 Rust 里处理 COM 的 VARIANT 和 BSTR 少一半代码，且已验证稳定；Python 侧用 JSON 行协议调用，超时就杀进程重启。这条路少了一个 cargo 构建环节，后续要换 Rust 实现时接口不变。

坐标语义定成「截图像素」：模型看图给数，程序按 scale 换算成物理屏幕坐标。这比让模型心算缩放比例少一个出错环节。

### 验证结果

- 单元测试 40 项通过，覆盖坐标换算、状态机、步数超时、分级、安全判定、HTTP 状态端点、工具箱装配
- 真实端到端通过：打开记事本、读到 40 个元素、点编辑区、输入中文、读回内容一致、截图落盘、用户移动鼠标后自动暂停并拦下动作、resume 后正常结束
- 前端构建通过，类型检查没有新增错误

### 已知边界

- user:“无需做安全边界”+(不做窗口归属、权限级别和点击落点拦截，动作直接执行)
- 提权窗口的输入注入仍会被系统 UIPI 拦掉，表现是点击没反应，工具不会提前拒绝
- 自绘界面和游戏没有无障碍树，只能靠视觉坐标
- 截图期间覆盖层会被隐藏，现有实现沿用桌宠那套，连续截图时状态条本身不在截图里
- 剪贴板粘贴模式会改写用户剪贴板
- 用户一动真实鼠标键盘，任务自动暂停，确认后 resume 继续

## 十一、后台注入与覆盖层

### 后台注入

user:“不抢占真实鼠标的方式你可以看看 叫做 okww”+(参考 ok-script 的做法：向目标窗口
PostMessage 投递鼠标键盘消息，不移动真实光标，窗口被遮挡也能收到)。

- `win32.background_click` 把屏幕坐标转客户区后发 WM_MOUSEMOVE、WM_LBUTTONDOWN、WM_LBUTTONUP
- `win32.background_type` 先发 WM_ACTIVATE 和 WM_SETFOCUS 让控件拿到键盘焦点，再逐字符发 WM_CHAR
- `win32.background_press_keys` 发 WM_KEYDOWN、WM_KEYUP，组合键按顺序按下抬起
- `win32.capture_window` 用 PrintWindow 的 PW_RENDERFULLCONTENT 抓窗口，被遮挡也能拿到内容

实测结论：

- 传统 Win32 控件（tkinter Entry）：后台点击和中文输入都生效，真实鼠标坐标完全不变
- Chromium（Edge 地址栏）：后台点击和输入都生效，地址栏能收到文字，鼠标坐标不变
- WinUI（Windows 11 记事本）：不接收 WM_CHAR，后台输入无效

所以不是纯 PostMessage，而是按窗口类名分流：`Notepad`、`ApplicationFrameWindow`、
`WinUIDesktopWin32WindowClass` 这三类直接走 SendInput 前台注入，其余默认后台。
`background=false` 可以强制前台，`drag` 始终用 SendInput，因为拖拽需要真实轨迹。

点击不做画面变化检测：点击经常没有视觉反馈，按画面判断必然误判成失败，会把一次点击做两遍。
输入也不做检测：有的应用输入了但界面延迟刷新，检测同样会误判，直接信任投递结果更可预测。

### 覆盖层

- 独立窗口 `computer-use-overlay`，全屏透明，加载 `core/desktop/computer-use.html`
- 4px 流动黯彩边框：conic-gradient 旋转加 mask 只留边框，暂停时减速变暗
- 提示条：「Sunday 正在操作你的电脑，esc 或点击此处以停止」，可点击
- Agent 光标：渐变彩填充加 2px 纯白边线，位置来自后端 `status.cursor`
- Esc 由 Rust 轮询 GetAsyncKeyState 检测，命中后 POST 停止并关窗
- 主界面的 `ComputerUseBar` 轮询到任务开始时拉起覆盖层，结束时收掉
- 用户输入自动暂停已移除，停止入口统一为 Esc 和点击提示条
