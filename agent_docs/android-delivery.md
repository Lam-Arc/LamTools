# Android 客户端交付说明

分支 `sunday/m-python-core-android`（工作树 `.worktrees/m-python`）。
共享业务实现是原版 Python Core，Android 只提供 Linux 运行环境与平台适配：SAF 文件
选择、键盘高度、进程与启动。界面是同一套共享 UI，没有第二套业务实现。

## 交付物

| 文件 | 用途 | 大小 |
| --- | --- | --- |
| `artifacts/android/sunday-m-arm64-debug.apk` | 手机（arm64-v8a） | 294 MB |
| `artifacts/android/sunday-m-x86_64-debug.apk` | 模拟器（x86_64） | 308 MB |

校验和：

```
bc155a3fcd9e8c7af933baa3d2951845045a05d73f6603c00bc4a6ad023e81ec  sunday-m-arm64-debug.apk
a33bc0baffc9268dc06f8418c9a6eb19b75f58f2a2d09fb01a2f86fdfe1ed204  sunday-m-x86_64-debug.apk
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
| 远程模式 | 部分 | 手机会在连着电脑时整条走隧道（RemoteTransport），否则用本机 Core；切换靠重载，未在设备上点过 |
| 远程重连 | 通过（逻辑） | 票据记在本机，入口与请求失败时都会按它重连一次；连不上回落本机 Core |
| 运行位置标记 | 通过（逻辑） | 远端模式下界面右上角常驻「在电脑上运行」 |
| 界面错位（点图片链接） | 通过 | 根因是分屏状态被持久化后仍套用桌面分栏几何；手机上不再套用，并在启动时清掉遗留状态 |

## 未验证（不得当作通过）

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
