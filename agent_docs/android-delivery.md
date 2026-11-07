# Android 客户端交付说明

分支 `sunday/m-python-core-android`（工作树 `.worktrees/m-python`）。
共享业务实现是原版 Python Core，Android 只提供 Linux 运行环境与平台适配：SAF 文件
选择、键盘高度、进程与启动。界面是同一套共享 UI，没有第二套业务实现。

## 交付物

| 文件 | 用途 | 大小 |
| --- | --- | --- |
| `artifacts/android/sunday-m-arm64-debug.apk` | 手机（arm64-v8a） | 297 MB |
| `artifacts/android/sunday-m-x86_64-debug.apk` | 模拟器（x86_64） | 311 MB |

校验和：

```
3025f0ae5e406fa38f8025de3799a469d585e4881f58f468c437d3dfa0eea37f  sunday-m-arm64-debug.apk
ec425a0149bd03456b279a1ebf219ce11b0319d18ec1b3b51f867d1554279292  sunday-m-x86_64-debug.apk
```

两个包都是 **debug 签名**，安装需要允许未知来源。包变大是因为内置了 iroh（QUIC + rustls + ring）。一个包只带一个 ABI 的运行时，这是
设计使然：运行时要包含该架构的 Python 解释器，通用包会带错一半。

## 安装与首次使用

```bash
adb install -r artifacts/android/sunday-m-arm64-debug.apk
adb shell am start -n com.lamtools.sunday.core/.MainActivity
```

首次启动会：

1. 把 APK 里的运行时归档（约 200 MB）流式复制到应用私有目录；
2. 解压成约 600 MB 的 rootfs，跳过 Android 拒绝的两个无关文件（perl、gunzip）；
3. 启动 proot 与其中的 Python Core；
4. 直接进入工作台。

模型与供应商走共享 UI 自己的入口：没有配置时工作台弹出「欢迎使用 Sunday」，点「开始配置」
进入设置里的模型与供应商，与桌面完全一致。Android 没有独立的首启配置页，也没有独立的
工具授权页：权限就在输入框上方那个「运行模式与权限」按钮里。

应用私有目录布局：

```
files/runtime/
  rootfs-<runtimeVersion>/   运行时镜像，升级时整体替换
  userdata/                  数据库、配置、工作区（绑定为 guest 的 /root/.sunday）
  guest.log                  Core 与 proot 的日志
```

用户数据与运行时分离，所以升级不会带走会话和密钥。

## 附件

`添加附件` 打开系统的文档选择器（SAF），选中后：

1. Kotlin 把文件复制到 `files/runtime/userdata/inbox/<请求 id>/`；
2. 宿主把宿主路径换成 guest 路径 `/root/.sunday/inbox/...`；
3. 共享 UI 用它本来就有的 `POST /api/core/sessions/{id}/attachments/reference` 登记；
4. Core 记录这条附件（`managed: false`），模型侧按绝对路径读取。

第 4 步依据 Core 现有的 `build_capability_aware_attachment_input`：模型收到的是附件的
绝对路径，需要内容时由 `read_file` 工具按需读取。所以附件本身不进请求体，宿主也不需要
把二进制搬过 IPC。

## 启动首屏

冷启动分三段，全程有反馈：

1. 原生窗口底色先出现，挡掉 WebView 之前的白帧。
2. HTML 启动层接管，显示 SUNDAY 标记、旋转环动画、阶段文字与进度条。
3. 解压进度是真实字节数，分母由构建时写进 manifest 的 `rootfsUnpackedBytes` 提供，事件从 `runtime.rs` 的 tar 循环发出，按 500ms 或 2% 节流。
4. 阶段依次是「准备运行时 → 解压运行时 → 启动核心 → 正在加载界面」。首屏渲染出内容后启动层淡出；45 秒仍无内容也会移除，避免永久遮挡。
5. 启动失败时显示错误与「重试」，不再落在空白。

## 手机悬浮环

设置 → 通用 → 手机悬浮环：

- 未授权时按钮是「去授权」，跳系统「显示在其他应用上层」页；回到应用后自动重查。
- 已授权可以开启，服务是 `specialUse` 前台服务，带常驻通知。
- 悬浮按钮可拖动，松手吸附左右边缘；点一下进入操作态，按钮变色。
- 操作态是全屏透明层，任意位置长按 450ms 浮出 Pin 环；按住移动选择，松开执行；点环外或松手在中心死区取消。
- 扇区动作：提问 / 注意 / 记录把提示词填进输入框但不发送；对话把应用拉到前台；切换会话打开会话列表；框选与子环明确提示手机上暂不支持。
- 环的半径、环宽、扇区来自 `.lam/pet/config.json` 的 ping 段；没有配置时用内置默认扇区。
- 服务被系统杀掉后不静默：设置页会显示「已被系统关闭，请重新开启」。

## 小窗

设置里的「小窗显示」进入系统画中画。进入成功后界面收到 `pip-mode`，进小窗时恢复 WebView 渲染，避免小窗画面静止。设备不支持或系统拒绝时把 Sunday 拉回前台并提示，不会停在一个没有反应的按钮上。

## 已验证（Android 16 x86_64 模拟器，debug 构建）

| 项 | 结果 | 证据 |
| --- | --- | --- |
| 安装 | 通过 | `adb install` 成功，包名 `com.lamtools.sunday.core` |
| 启动与解压 | 通过 | 首次解压 596 MB，用时约 30 秒，跳过 2 个条目 |
| 运行时升级 | 通过 | 版本化目录替换镜像，用户数据保留 |
| Core 启动 | 通过 | `libproot.so` 与 `python3.14` 为应用自身 uid 进程 |
| 应用内 DNS | 通过 | rootfs 内 `/etc/resolv.conf`，模型域名可解析 |
| 共享 UI | 通过 | 工作台、项目列表、会话、输入框、设置全部渲染 |
| 项目入口 | 通过 | 项目列表显示 MyProject；新建项目后进入其会话 |
| 真实模型对话 | 通过 | 用户消息 → 模型回复 → 工具调用 → 审批 → 最终回复 |
| 附件选择与登记 | 通过 | SAF 选中文件 → `inbox/pick-.../0/SUNDAY-ATTACH-PROBE.txt` → `attachments/reference` 返回 200 → 输入框出现附件 chip |
| 工具授权入口 | 通过 | 输入框上方「运行模式与权限：执行 · 询问」，点开是共享 UI 自己的菜单 |
| 键盘高度 | 通过 | 键盘弹出时输入框与发送键抬到键盘之上（截图核对），不再被遮挡 |
| 发送路径 | 通过 | 界面日志确认 `submitComposer` 校验通过并提交（`mode: send`，无阻塞） |
| 返回键 | 通过 | 整版界面（设置/插件/项目设置）在会话栏页名旁与手机左上角都有返回键；系统返回键先关整版界面，无视图可关才退到后台 |
| 状态栏让位 | 通过 | 宿主上报状态栏高度，标题条偏移与整版内容一起让位，不再压到系统栏下面 |
| 手机侧栏 | 通过 | 侧栏最下方一排纯图标（模式 / 资料库 / 定时任务 / 插件 / 设置 / 远程连接），名称只在提示与读屏标签里 |
| 手机分屏 | 通过 | 分屏在手机上整屏铺开，左上角返回键关闭分屏；系统返回同样先关分屏 |
| 返回无死角 | 通过 | 返回按层退：分屏 → 整版界面 → 退到后台，任何一层都能出来 |
| 思考滑块 | 通过 | 轨道与刻度一起声明 touch-action:none，触摸可以拖动而不是只点选 |
| 点击高亮 | 通过 | 去掉触屏点击高亮与非键盘的焦点框，键盘操作仍保留可见焦点 |
| 附件/引用 | 通过 | 引用 token 固定行高，插入后重新量输入框高度，不再整块错位 |
| 设备连接（传输层） | 部分 | 两进程直连 + Core 转发 + 事件推送实测通过；手机 App 与 PC 之间的整链未在设备上点过 |
| 电脑出码（桌面端） | 通过 | 2026-11-06，dev 实例里点「生成票据」得到 `sunday1:` 票据（159 字符，含本机局域网地址 `192.168.31.220:57788`）与 61×61 的真 SVG 二维码（93,715 字节、1,491 个 rect）；点「开始接受连接」后状态变为「正在接受连接」，`sunday-p2p` 进程由桌面宿主拉起 |
| 远程模式 | 部分 | 手机会在连着电脑时整条走隧道（RemoteTransport），否则用本机 Core；切换靠重载，未在设备上点过 |
| 手机扫码（解码） | 通过（逻辑） | `core/p2p/src/scan.rs` 用 `qrcode` 生成 PNG、`rqrr` 读回，字符串逐字节相等；相机取图走 `FilePickerBridge` 的 `camera` 分支：拍照 → 复制进核心能读的目录 → `host_path` 换回宿主路径 |
| 远程重连 | 通过（逻辑） | 票据记在本机，入口与请求失败时都会按它重连一次；连不上回落本机 Core |
| 运行位置标记 | 通过（逻辑） | 远端模式下界面右上角常驻「在电脑上运行」 |
| 界面错位（点图片链接） | 通过 | 根因是分屏状态被持久化后仍套用桌面分栏几何；手机上不再套用，并在启动时清掉遗留状态 |
| 启动首屏 | 通过 | 冷启动 t15 原生底色，t60 启动层显示 1% / 4 MB 515 MB，之后进入欢迎页；日志完整出现 staging → unpacking → starting → waiting → ready |
| 手机悬浮环（服务与环） | 通过 | 系统窗口列表先出现悬浮按钮，点击后变成两个窗口；长按截图看到六扇区环；注入扇区动作后输入框出现「来自悬浮环」 |
| 小窗 | 未验证 | 命令与回落代码已接，未在设备上点过 |

## 未验证（不得当作通过）

* **手机扫电脑的二维码**：电脑这一半已经真实走过（见上表「电脑出码」，出的是 `sunday1:`
  票据与真 SVG 图形，桌面上「开始接受连接」也点了）；手机那一半——相机拍屏幕 → 解码 →
  填入 → 点「连接」→ 显示「已连到 <id>」——还没有在真机上走。要在真机验收，桌面保持
  「正在接受连接」，手机装 `artifacts/android/sunday-m-arm64-debug.apk` 后扫码即可；
  连上后桌面侧的唯一可见证据是 `%APPDATA%\Sunday\p2p\p2p-trust.json` 里新增一条设备记录
  （桌面 UI 不显示对端 ID）。
* **悬浮环长按拖动选中**：长按出环、滑动高亮、松手执行这一段没有在设备上完整跑通。已验证的是环渲染与动作投递，注入扇区动作后输入框收到文字。设备上的连续触摸需要真机或更可靠的注入工具。
* **小窗（PiP）**：入口、回落与 WebView 恢复代码已接，设备上未点过。
* **实体 arm64 设备**：本机只有 x86_64 模拟器。ARM64 APK 已产出并检查了内容（5 个
  `arm64-v8a` 库、`rootfs-aarch64.targz`），但没有在真机上安装运行。
* **附件端到端对话**：附件已登记到 Core（200 OK），但"带着附件发一条消息、模型用
  `read_file` 读回内容"这一步没有在设备上点出来。脚本化点击的坐标在键盘弹出后不可靠，
  本轮改为核对代码路径：`attachmentInputItems` → `buildCoreComposerInputItems` →
  `turn/start` 的 `input_items` → Core 的 `build_capability_aware_attachment_input`。
* **返回键逐页导航**：已改为最小化而不是结束进程，但没有逐页验证。
* **前后台切换与 Activity 重建**：`core_start` 已改为复用正在运行的 guest（只有镜像版本
  变化才重启），未在设备上构造该场景验证。
* **停止任务按钮**：UI 停止按钮与 Core 停止路径未单独验证。
* **资料库上传**：这条路要字节流，安卓的 SAF 只给路径，当前会明确报错「当前平台暂不支持
  从资料库上传文件」，不是静默失败。

## 已知问题

1. 上传过程中进程被杀会留下一段 `pending://` 草稿，界面因此拒绝发送，直到把那个附件
   引用移除。桌面同样存在这个草稿状态，只是不容易撞上。
2. 审批通过后最终回复的渲染有延迟（实测那次对话几十秒内完整出现），不是失败。
3. 多客户端并发没有验证：宿主现在一条 socket 承载所有页面，重连时重新订阅当前会话。
4. 共享 UI 的一条 CSP 规则拒绝了一个 `data:` 字体（logcat 里可见），不影响布局与阅读。

## 复现构建

```bash
# 1. 运行时（Linux / WSL）
core/android-runtime/tools/build-runtime.sh x86_64
core/android-runtime/tools/build-runtime.sh aarch64

# 2. UI
cd core/ui && npm install && npm run build:android

# 3. APK（工作树里没有 node_modules，需要指向主仓的 tauri CLI）
cd core/android-host
export TAURI_CLI=/e/LamTools/core/desktop/node_modules/@tauri-apps/cli/tauri.js
export SUNDAY_RT_ABI=aarch64
export SUNDAY_RT_ASSETS=$PWD/../android-runtime/tools/out/aarch64/assets
python scripts/android_project.py all --debug --target aarch64
```

## 验收脚本

* `core/android-host/scripts/verify-apk.sh` 安装并报告设备上真实发生了什么；
* `core/android-host/scripts/seed-model.sh` 在无法点击 WebView 时写入模型配置；
* `core/android-host/scripts/android_ui.py` 用无障碍树按文字点击，避免猜坐标；
* `core/android-host/scripts/android_cdp.py` 调试包的 DevTools 观察通道。
