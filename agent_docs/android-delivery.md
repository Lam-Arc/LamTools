# Android 客户端交付说明

分支 `sunday/m3-isolated-core`（主仓 `E:\LamTools`）。
共享业务实现是原版 Python Core，Android 只提供 Linux 运行环境与平台适配：SAF 文件
选择、键盘高度、进程与启动。界面是同一套共享 UI，没有第二套业务实现。

## 交付物

| 文件 | 用途 | 大小 | 交付名（Downloads） |
| --- | --- | --- | --- |
| `artifacts/android/sunday-m-arm64-debug.apk` | 手机（arm64-v8a） | 305 MB | `02-sunday-m-arm64-debug.apk` |
| `artifacts/android/sunday-m-x86_64-debug.apk` | 模拟器（x86_64） | 319 MB | — |

校验和（2026-11-09 17:36 / 17:40 构建，含内置运行时、截图与通知读取、远程链路的稳定性修复；交付时
文件名带 `02-` 前缀，内容与这里列出的一致）：

```
0bbb2dc9bf83d2f44fbed1531efe5a64072f6a14a1e3672788f041be5be97388  sunday-m-arm64-debug.apk
b5ba8abcb1c434385a34fb8571c09a9c88197ad3a957d6d80f3af8e5ec486b67  sunday-m-x86_64-debug.apk
```

## 下载渠道（2026-11-10）

user:“接 GitHub release”+(安卓包走 GitHub Release，官网给扫码入口，不再靠拷文件)。

固定位置：

```
https://github.com/Lam-Arc/LamTools/releases/download/android-latest/Sunday-mobile-arm64.apk
```

- tag 固定为 `android-latest`，资产名固定为 `Sunday-mobile-arm64.apk`，每次发布覆盖同一个
  位置。官网 `website/src/components/Download.vue` 的「下载 Android 版」和扫码二维码都
  指向它，不会随版本号失效；要换自有服务就设 `VITE_ANDROID_DOWNLOAD_URL`。
- 二维码是 `website/public/downloads/android-qr.svg`，由
  `cargo run --example qr_text -- <url>` 生成，和配对二维码共用同一个渲染器。
- 发包一条命令：`python scripts/publish-android.py`。它会先确认 APK 里确实有
  `lib/arm64-v8a/libproot.so` 与 `assets/runtime/rootfs-*`，否则拒绝上传；然后算 SHA-256、
  覆盖资产、把构建时间与校验和写进 Release 说明。`--dry-run` 只校验不上传。
- CI 里的 `android-apk.yml` 仍然只做「干净检出也能构建」的验证。可安装的包需要内置运行时，
  那份资产不进仓库（`core/android-runtime/tools/out` 被忽略），所以 CI 产物不能直接发给用户。
- 包是 debug 签名。以后换成 release 签名，老用户需要卸载重装一次，否则会报签名冲突。
**打 arm64 包必须设置 `SUNDAY_RT_ABI=aarch64` 与 `SUNDAY_RT_ASSETS=<runtime>/tools/out/aarch64/assets`。**
漏掉的包能装能开，但 APK 里既没有 `assets/runtime/rootfs-*` 也没有 `libproot.so`，启动层
会一直报 `cannot start proot: No such file or directory`——手机永远只能用远程模式，
还没到远程那一步就先看到「启动失败」。判断方法：`unzip -l` 里搜 `proot`，
没结果就是没带运行时。

启动图标与桌面一致，是 Sunday 笑脸，由 `core/desktop/src-tauri/icons/icon.png` 重新生成到各密度 mipmap；此前生成工程里残留的旧「88」图标已替换。

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
| 状态栏让位 | 通过 | 界面启动后主动读取宿主缓存的 insets，状态栏 24px 已验证；窄屏主区从屏幕最上沿开始，只有内容让过状态栏 |
| 手机主区 | 通过 | 窄屏下主区满幅，无边框、无圆角、无阴影，左侧没有白线 |
| 手机侧栏 | 通过 | 最下方一排与桌面竖栏一致：聊天 / Super-agent / 定时任务 / 资料库 / 插件 / 设置 / 远程连接；侧栏自带的搜索、插件、设置页脚在手机上关闭，避免重复 |
| 打开侧栏 | 通过 | 左上角悬浮按钮位于状态栏下方，点一下打开抽屉，抽屉打开时按钮自动消失；设置、插件、项目设置与分屏打开时按钮也会隐藏，不挡返回键 |
| 配对界面（两端） | 通过 | 电脑只有一个动作：生成票据即开始接受连接，二维码 + 点击复制的票据 + 换一张 / 停止；手机只有一个主动作：扫码连接，粘贴票据收在次要入口，扫码成功直接连；没有可信设备时不显示设备区 |
| 配对连接可靠性（两端） | 通过（部分） | 出票前等中继就绪，票据现在带 中继 + 公网 + 局域网 三个地址（实测 `RELAY ... connected`）；网络变化时传输进程重发 `TICKET`，宿主更新二维码；手机连接时显示“先试直连 x，失败走中继”和已等待秒数，45 秒超时给出目标地址与原因；扫码改为实时相机预览，帧直接交给 Rust 解码。真机实时识别与跨网络实际握手未验 |
| 消息直播（手机本地 Core） | 通过（契约 + 设备） | 修复：IPC 通道此前把核心事件的整帧当成 `params`，界面拿不到 thread_id / seq / payload，发出消息后要退出重进才看得到回复。修复后设备上发出消息即出现 turn/accepted 与 core/runItem 的直播反馈；契约测试 `tests/ipc-transport.test.ts` 覆盖事件、快照与服务器请求 |
| 设置分区 | 通过 | 手机上设置顶部只剩 模型 / 通用 / 桌宠 / 界面 / 工具模式 / 权限 / 上下文 / Sub agent / 关于，旧的「手机控制」分区已删除 |
| 桌面标题栏 | 通过 | 标题栏不再有「账号与设备」气泡与手机图标；配对统一走竖栏底部的远程连接页 |
| 手机分屏 | 通过 | 分屏在手机上整屏铺开，左上角返回键关闭分屏；系统返回同样先关分屏 |
| 返回无死角 | 通过 | 返回按层退：分屏 → 整版界面 → 退到后台，任何一层都能出来 |
| 思考滑块 | 通过 | 轨道与刻度一起声明 touch-action:none，触摸可以拖动而不是只点选 |
| 点击高亮 | 通过 | 去掉触屏点击高亮与非键盘的焦点框，键盘操作仍保留可见焦点 |
| 附件/引用 | 通过 | 引用 token 固定行高，插入后重新量输入框高度，不再整块错位 |
| 设备连接（传输层） | 部分 | 两进程直连 + Core 转发 + 事件推送实测通过；手机 App 与 PC 之间的整链未在设备上点过 |
| 电脑出码（桌面端） | 通过 | 2026-11-06，dev 实例里点「生成票据」得到 `sunday1:` 票据（159 字符，含本机局域网地址 `192.168.31.220:57788`）与 61×61 的真 SVG 二维码（93,715 字节、1,491 个 rect）；点「开始接受连接」后状态变为「正在接受连接」，`sunday-p2p` 进程由桌面宿主拉起 |
| 远程模式 | 部分 | 手机会在连着电脑时整条走隧道（RemoteTransport），否则用本机 Core；切换靠重载，未在设备上点过 |
| 手机扫码（入口与解码） | 通过 | 侧栏「远程连接」→「设备连接」里有「扫码」，点开拉起系统相机；解码逻辑用生成 PNG 读回验证，字符串逐字节相等 | `core/p2p/src/scan.rs` 用 `qrcode` 生成 PNG、`rqrr` 读回，字符串逐字节相等；相机取图走 `FilePickerBridge` 的 `camera` 分支：拍照 → 复制进核心能读的目录 → `host_path` 换回宿主路径 |
| 远程重连 | 通过（逻辑） | 票据记在本机，入口与请求失败时都会按它重连一次；连不上回落本机 Core |
| 运行位置标记 | 通过（逻辑） | 远端模式下界面右上角常驻「在电脑上运行」 |
| 界面错位（点图片链接） | 通过 | 根因是分屏状态被持久化后仍套用桌面分栏几何；手机上不再套用，并在启动时清掉遗留状态 |
| 启动首屏 | 通过 | 冷启动 t15 原生底色，t60 启动层显示 1% / 4 MB 515 MB，之后进入欢迎页；日志完整出现 staging → unpacking → starting → waiting → ready |
| 手机悬浮环（服务与环） | 通过 | 系统窗口列表先出现悬浮按钮，点击后变成两个窗口；长按截图看到六扇区环；注入扇区动作后输入框出现「来自悬浮环」 |
| 小窗 | 未验证 | 命令与回落代码已接，未在设备上点过 |

## 2026-11-07 深夜：远程模式、启动顺序与设备切换

这一轮把用户报的「连上电脑没有项目」「peer closed stream」「电脑手机按钮点了没反应」「多设备怎么切」
逐条落到根因上，全部在模拟器上验过，真机只验了启动耗时。

### 三个真 bug

| 现象 | 直接原因 | 为什么一直没被发现 |
| --- | --- | --- |
| 连上电脑没有项目 | 界面用相对路径 `/projects`。本机通道在宿主里补了 `/api/core` 前缀，隧道的远程转发没补，电脑端每个这样的请求都是 404 | 远程模式只验过「能转发一次 REST」，没验「界面上真的出现项目」 |
| 事件从来没推给手机 | 传输连的是 `/app-server`，Core 挂在 `/api/core/app-server`；连接错误被 `is_err()` 吞掉 | 事件是异步的，没有它界面也不会立刻报错，只是不更新 |
| 发送消息报 peer closed stream | 隧道只转发了 REST，界面读会话、工作台快照走 JSON-RPC，全部落在「未知方法」上；旧版传输进程遇到一次握手失败就整体退出 | 契约分散在三端（界面 / 核心 / 传输），没有一处共同的真相 |

补的东西：`core/p2p/src/rpc.rs`，每条隧道连接各开一条到 Core 的 JSON-RPC 通道（与事件泵分开，
免得大回复把事件堵住），`serve` 里未知方法一律转发过去。

### 启动顺序

原来 `core_start` 挡在挂载前面，界面要等核心。现在：界面先挂出来，数据通道加一道闸
（`gateTransport`），核心没就绪时请求排队；拨号在后台进行，连上了再重开一次切到电脑。
模拟器上启动层 2 到 4 秒退场；真机上这一版之前测到 2 到 6 秒（旧包 36 秒）。

### 设备切换（2026-11-07 深夜，第二次改）

user:“工作环境的切换从输入框挪到设备连接那个页面”“设备连接页面你也要重做一遍，现在的样式
太普通了，不易用”+(所以输入框上方那个入口去掉了，设备连接页改成以设备清单为主体：本机一行、
每台配对过的电脑一行，行内直接切换；扫码与粘贴退到清单下面当「添加设备」)。

页面结构：标题 + 一句用途说明 + 刷新；设备清单（当前设备带绿色「当前」标记，其他设备带
「切换」）；扫码连接 / 粘贴票据；一行用法提示；可信设备折叠区。模拟器截图
`.lam/tmp/device-page3.png`。

原来的做法

`workspaceControl` 之前从没被宿主提供，所以输入框上方那个菜单永远是空的、点了没反应。
现在列出「本机」加每一台配对过的电脑，切换时先 `p2p_disconnect` 再按新选择重开。
抽屉里那个点不动的「同步项目」按钮删掉了（它发的是没人接的事件）。

模拟器验收：本机 → TestPC 后出现「在电脑上运行 / 工作环境：TestPC」；再选回「本机」后
「工作环境：本机」且远程标记消失。

## 2026-11-07 晚：首屏重做（网格渐变）

user:“铺满屏幕，渐变流动，高级而令人舒适，要这种效果，不用常规的圈或者条”
“要的是像苹果或者说谷歌那种，就是很高级的流动感”+(旧启动层是转圈加一条进度条，
换成一整屏会流动的渐变，进度只用文字说明)。

做法：`index-android.html` 里放一张 canvas，逐像素算一张 30x54 的低分辨率色场再平滑
放大——色与色之间是插值，没有圆心、没有边、没有色带；五个色点各自沿 12 到 26 秒的周期
游动，另外每帧对坐标做一层缓慢的正弦扭曲，所以颜色像流体一样互相挤，而不是整体平移。
曝光压到四成左右，底子仍是近黑，颜色只作为光存在。文字只留 `SUNDAY`、阶段名与一行
说明；没有转圈，也没有进度条。

同批修掉三处启动期瑕疵：

| 位置 | 改动 | 证据 |
| --- | --- | --- |
| `MainActivity.kt` | 窗口与 WebView 的底色统一成 `#070912`，杀掉 WebView 绘制前的白底 | 逐秒取样：1s `(20,22,30)`、2s `(7,9,18)`（原来第 2 秒是纯白 `255,255,255`）、3s 起色场出现 |
| `MainActivity.kt` | 启动期 `enableEdgeToEdge(SystemBarStyle.dark(...))`，状态栏图标改为浅色 | 启动截图里时间与电量从黑变白，可读 |
| `bootScreen.ts` | 启动层移除时广播 `sunday-boot-done`，色场停止计算 | 层消失后不再有 rAF 循环 |
| `android_project.py` | 原生启动底色 `#14161a` → `#0b0c10` → `#070912`，和 HTML 启动层同色 | 1s 那一帧与 2s 之后的帧颜色接近，交接看不出接缝 |

浏览器预览：`.lam/artifacts/boot-preview/index.html`，由
`python .lam/artifacts/boot-preview/build.py` 从 `index-android.html` 里抽取 CSS、标记与
色场脚本生成，不复制第二份样式。`R` 重播、`E` 失败态、`P` 手机尺寸，地址后加 `?hold=1`
停帧只看渐变。

色场在模拟器上逐秒采样 `(47,56,123) → (80,63,150) → (97,72,161) → (57,84,131)`，
说明它在动而不是一张静态图；真机 arm64 未验。

## 2026-11-07 晚：相机方向与「Connection lost」的根因

两个报上来的问题各有独立成因，都不是界面文案问题。

**相机方向。** `QrScanActivity` 建好预览却从没调用 `setDisplayOrientation`，传感器方向
90° 的手机拿到的就是横躺且被拉满整屏的画面。现在按 `(传感器方向 - 屏幕旋转)` 转正，
再把 SurfaceView 按转正后的比例居中（多出来的部分留黑底），布局完成后再套一次。
模拟器实测：`preview 1280x720 sensor=90 screen=0 display=90`、`surface 1080x1920 in box
1080x2400`，截图确认画面居中、上下留黑、不再被拉宽。真机传感器方向不同也走同一个公式，
但真机画面未验。

**Connection lost。** 这个字符串来自 quinn（`ReadError::ConnectionLost`），不是业务层
报错，含义是手机和电脑之间的 QUIC 连接断了。真正让"第一次连上、后面连不上"的是传输
进程的退出路径：`ServerLink::accept` 只要遇到一次握手超时（手机在 45 秒超时后放弃拨号，
留下的那次握手会在服务端超时）就 `return Err`，`sunday-p2p serve` 整个进程跟着退出，
进程一死后桌面这边就再也接不到任何设备，`p2p.log` 里只剩一行 `Error: handshake failed`。
实测复现与修复后对比：同一台机器、同样中断两次握手，修复前进程消失，修复后只多两行
`ACCEPT ERROR handshake failed: timed out`，进程仍在监听。

同批修掉的还有四处：

| 位置 | 改动 | 证据 |
| --- | --- | --- |
| `core/p2p/src/bin/cli.rs` | 握手失败只记日志、睡 1 秒继续等；端点关闭才退出 | 见上，进程存活 |
| `core/p2p/src/bin/cli.rs` | 每条连接各起一个任务，不再一条一条排队服务 | 手机保持连接时，另一个客户端 `call --method ping` 立即得到 `{"pong":true}` |
| `core/p2p/src/link.rs` + `core/android-host/.../p2p_bridge.rs` | `Client` 记住读帧任务是否还活着；`p2p_status` 按真实存活回答；`p2p_call` 发现隧道死了就丢掉并给中文提示 | 杀掉电脑端传输进程后，手机「设备连接」由「已连接」变为「未连接」 |
| `core/ui/src/components/RemoteConnectionPanel.vue` | 记住票据就显示「重连上次的电脑」；电脑端每 3 秒静默刷新连接状态 | 重装启动后自动回到「已连接 / 已连到 16c281…41c7」；电脑端换票/重启传输后同一张票据仍可重连 |

电脑端的「手机已连接」显示还需要桌面应用本身重装：宿主 `p2p_host.rs` 这次加了读取
`PEER` 状态，但正在运行的桌面版仍是旧宿主。

## 2026-11-09：远程链路修复批次（提交 `6822b447`、`7327bf99`）

这一批把 `agent_docs/p2p-link-audit.md` 第二轮审查里的问题全部落到了代码上。APK 已重打
（见上表校验和），电脑端的传输程序已换成同一份 `sunday-p2p.exe`。

| 问题 | 修法 | 验证 |
| --- | --- | --- |
| 远程模式下附件、图片/PDF 预览、素材库全部不可用（隧道只搬文本） | `core_http` 改成字节透传（请求/响应都带 base64 与原始响应头，服务端解码 chunked） | 真实隧道 `core_http GET /projects` 返回 200 与可解码 JSON；Rust 单测覆盖二进制与 chunked |
| 撤销设备不生效 | 名单每次握手前重读；新增撤销名单，在自动信任之前检查；设备页可「重新允许」 | 端到端：撤销后连接被拒并看到「可能已被撤销授权」，重新允许后恢复 |
| 断线要等 180 秒超时才被发现 | 客户端 12 秒心跳、40 秒判死；服务端 120 秒无帧收连接；宿主发 `lost`，界面显示断线并重连 | `cargo test`；真机待验 |
| 断线不通知界面、远程期间不重连 | `RemoteTransport` 监听 `p2p-progress`；常驻重连循环改为「只要还记着票据就守着」 | 类型检查；真机待验 |
| 失败重放可能重复执行写操作 | 只重放读操作，写操作明确报「没有确认送达」 | `vitest tests/remote-codec.test.ts` |
| 请求串行（服务端逐条 await、手机宿主整段持锁） | 服务端每条 Call 独立任务；`Client::call` 改 `&self`，宿主只取一次 `Arc` 就放锁 | 编译与单测；真机待验性能 |
| 事件 Lagged 静默丢帧 | 服务端与手机宿主都补发 `thread/gap`，界面走已有的重新 resume；手机转发任务不再因 Lagged 退出 | 代码审查；真机待验 |
| 桌面配对命令阻塞 IPC 线程 | 改异步命令 + `spawn_blocking`，二维码按票据缓存 | 编译通过 |
| 电脑名显示成十六进制 id | `Welcome` 带对端名字 | 代码审查；真机待验 |
| 「换一张」换不了票据 | 去掉这个按钮 | 界面 |

仍需注意：

- 正在运行的桌面应用还是旧宿主（没有 `p2p_allow`、没有子进程守护），设备页的「重新允许」
  要在桌面重装/重启之后才会出现；撤销与重连本身在传输进程里，已经生效。
- 电脑端传输进程现在由我手动起在 `%APPDATA%\Sunday\p2p`，直连 Core 的 59928 端口；
  重启桌面应用之后请打开一次「设备连接」让宿主自己拉起传输进程，避免指向已经死掉的端口。
- 真机还没有安装这一版 APK：无线调试当前是关的（5555 / 34127 都拒绝连接）。

## 2026-11-09：安卓设备控制（android_use）

user:“加，安卓控制，上模拟器里把它跑通”+(让 Sunday 自己读手机界面、点按、滑动、输入、
返回桌面、打开应用)。

**怎么开**：系统设置 → 无障碍 → 「Sunday 设备控制」打开。重装 APK 之后这个开关会失效，
需要在设置里重新打开一次（两次重装都这样）；也可以直接用 adb：

```
adb shell settings put secure enabled_accessibility_services   com.lamtools.sunday.core/com.lamtools.sunday.core.SundayAccessibilityService
adb shell settings put secure accessibility_enabled 1
```

**结构**：

| 位置 | 作用 |
| --- | --- |
| `SundayAccessibilityService.kt` | 读屏（文字、描述、位置、可点击/可编辑/可滚动）与点按、长按、滑动、写文本、全局动作、打开应用、列出可启动应用 |
| `DeviceControlBridge.kt` | Rust 与服务的唯一入口；服务没开时如实回答「无障碍服务没有开启」 |
| `device_control.rs` | 宿主在 127.0.0.1 随机端口开一条只认令牌的通道，端口与一次性令牌写进 `files/runtime/userdata/device-control.json`，guest 看到 `/root/.sunday/device-control.json` |
| `android_use.py` | Core 的工具；只在 `SUNDAY_HOST_PLATFORM=android` 时注册，桌面与远程模式不出现 |

**模拟器验收（x86_64 / API 36）**，全部是真实动作：

| 动作 | 结果 |
| --- | --- |
| status | `connected: true` |
| snapshot | 读到系统对话框与设置页的完整树（包名、1080x1920、每个元素的文字与 bounds） |
| tap_node（Wait） | 关掉了 System UI 的 ANR 对话框 |
| open_app com.android.settings | 前台切到设置 |
| tap_node（网络和互联网） | 进入二级页，标题变成 Internet / Networks available / SIMs |
| global back | 回到设置首页 |
| 点搜索 → set_text 「battery」 | 输入框里出现 battery |
| 桌面侧调用同一个 Python handler | snapshot 返回 14 行可读树，global home 返回 ok |
| screenshot | 480x853 JPEG，`model_image_data_url` 带原图字节，画面是真实界面（不是黑屏） |
| notifications | `connected: true`，读回系统通知的包名、标题、正文；用 `cmd notification post` 发的测试通知也在列表里 |

**读取能力（2026-11-10 补）**：

- `screenshot`：走无障碍的 `takeScreenshot`，拷成 ARGB_8888、按 `max_width` 缩放、JPEG 82，
  只把 base64 交给工具层；工具把它挂到 `model_image_data_url`，不落盘。
- 无障碍配置必须写 `android:canTakeScreenshot="true"`，否则系统直接拒绝：
  `Services don't have the capability of taking the screenshot`。加上之后 `capabilities`
  从 33 变成 161。
- `notifications`：`SundayNotificationListenerService` 保留最近 40 条（同一 package+title
  覆盖，避免聊天刷屏），不经过无障碍，所以无障碍没开也能读；需要用户在「通知使用权」里
  允许一次。模拟器上可用
  `adb shell settings put secure enabled_notification_listeners com.lamtools.sunday.core/com.lamtools.sunday.core.SundayNotificationListenerService`，
  真机必须在系统设置里点。
- `DeviceControlBridge` 先看 action 是不是 `notifications`，是就交给监听服务，不再要求
  无障碍在线。

**限制**：

- WebView 的输入框对 `performAction(CLICK/SET_TEXT)` 会抛异常（`length=1; index=1`）；
  `tap_node` 与 `set_text` 现在都会捕获并回退（点中心 / 聚焦后重试），不再让一次异常
  变成整个动作失败。
- 只能读到系统无障碍愿意暴露的节点；密码框、部分自绘界面读不到文字。
- 工具只出现在手机本机的 Core；「远程模式」跑在电脑上的 Core 没有它。
- 手机 App 里还没有「去开无障碍」的引导页，目前要用户自己去系统设置。
- 截图在 60 Hz 以下的动态画面里可能拿到上一帧；这一层不做任何识别，交给模型判断。

## 2026-11-10：远程连接不稳定（频繁断连 / RPC 连接失败）

user:“手机端远控电脑连接不稳定，频繁断连，或者RPC连接失败，需要优化一下”。

**先让日志能读**：`p2p.log` 以前没有时间戳，只能看出「很多次」，看不出间隔是 2 秒还是
2 分钟。`diary()` 现在每行前加 `YYYY-MM-DD HH:MM:SSZ`，这是定位下面几个根因的前提。

**证据（新日志，UTC）**：

```
04:17:42Z PEER 6ba8… trusted=true          # 连上
03:58:04Z PEER-ERROR … cannot write a frame header: connection lost: timed out
03:58:46Z PEER-ERROR … closed by peer: heartbeat lost (code 0)
```

两条错误之间只隔 42 秒，而连接建立到 `timed out` 只有 28 秒。

**根因一：服务端读帧被 `select!` 取消，读位置错乱。**

`ServerLink::serve` 以前把 `read_frame` 直接放在 `select!` 里和「处理已完成的调用」并列。
另一条分支先完成时，正在读的那一帧被取消——QUIC 不接受这种取消，已经读走的字节就丢了。
下一次 `read_frame` 把半个帧体的字节当成新帧头，读位置从此错开，服务端会卡在一个永远读
不满的长度上：它不再消费对端的数据，手机端的写窗口被堵住，心跳发不出去。

证据就是这一轮加的心跳诊断：

```
05:20:09 heartbeat #1 sent          # 服务端 ping #1 received
05:20:29 heartbeat skipped: the write lock is busy
05:21:19 heartbeat #7 sent          # 服务端 ping #7 received
```

中间 5 次心跳全部卡在写锁上，服务端一个都没收到。现在读帧放进独立任务，谁也取消不了它；
写回复也放进独立任务，读循环只管读。

**根因二：QUIC 的 30 秒空闲超时先于应用层心跳触发。**

iroh 默认 `max_idle_timeout` 是 30 秒（`iroh` 源码里测试注释写的就是 "3s idle timeout
instead of the 30s default"）。手机端在加载会话时，一条几十 MB 的回复把写方向的
`SendStream` 锁占住；应用层心跳是「sleep 10 秒 → 拿写锁 → 写 Ping」，它排在锁后面发不
出去。QUIC 的空闲计时不看你在不在排队，28 秒后直接把连接关掉，电脑侧下一次写帧就报
`connection lost: timed out`；客户端再过一会儿也判死，报 `heartbeat lost`。

修复在 `identity.rs`，两端共用同一个 endpoint：

- `keep_alive_interval = 10s`：链路层自己发保活，不依赖业务层拿锁；
- `max_idle_timeout = 120s`：和传输进程自己的 `IDLE_TIMEOUT` 对齐。

`link.rs` 的心跳同时改成 `try_lock`：拿不到写锁说明正在发真实数据，连接肯定活着，跳过
这一轮而不是排队；判死从 26 秒放到 120 秒，与链路层的空闲上限对齐。

**根因二：断线后每条调用要等满 180 秒。**

`Client::call` 以前只在 180 秒超时或对端回错时返回。断线发生在一次调用中间时，用户看到
的是「点了没反应」。现在连接有一条 `watch` 通道，读帧失败或心跳判死都会通知它，等回复
的调用当场返回「和电脑的连接断开了：正在重连」，界面能立刻显示断开并开始重连。

**根因三：桥的写半边死了，上层不知道。**

`rpc.rs` 里只有读半边退出会把 `dead` 置 true；写半边（发不出去 Core 的请求）退出时
`is_dead()` 仍是 false，于是 `cli.rs` 不会重建桥，之后每条 RPC 都报「RPC 通道已关闭」，
一直错到重新配对。现在写半边退出也置 `dead`，并且每 10 秒发一个 WebSocket Ping，让桥的
写方向一直有真实流量（空闲的桥以前连 Pong 都要攒着等下一次写）。

**根因四：界面的补救预算太短。**

`remoteTransport.request` 在隧道断开时会 `ensureRemote(8_000)`，蜂窝或走中继时 8 秒不够
一次握手，于是普通抖动被报成「连接断开」。改成 20 秒；`p2p-progress` 收到 `lost` 后
界面自己静默重连一次（1.5 秒后，45 秒预算），成功就恢复，失败才停在断开状态让用户处理。

**验收**：

| 项 | 结果 | 证据 |
| --- | --- | --- |
| `core/p2p` 单测 | 通过 | `cargo test`：9 项全通过 |
| Core 的 ws 保活 | 通过 | 用 `core/p2p/examples/idle_probe` 直连 `ws://127.0.0.1:59928/api/core/app-server`，20 秒收到 Core 的 Ping，45 秒仍是 open |
| 模拟器远程模式 | 通过 | 写入票据后界面右上角「在电脑上运行」，加载出电脑上的真实会话（截图核对） |
| 心跳真的发出去了 | 通过（诊断） | 客户端 logcat 的 `heartbeat #1 sent` 与服务端的 `ping #1 received` 一一对应 |
| 断连点被定位 | 通过（诊断） | 紧接着出现 `heartbeat skipped: the write lock is busy`，服务端 120 秒后报「对端长时间没有任何帧」 |
| 重写服务端后的协议回归 | 通过 | 回环票据（`127.0.0.1:<port>`）分别连旧 exe 和重写后的 exe，都是 `PEER …` + `{"pong":true}`；重写后的 exe 再经隧道 `core_http GET /projects`，解码回真实项目列表 |
| 修复后长时间复测 | 未完成 | 模拟器到电脑的 UDP 路径在这一轮整体不通：局域网地址 ping 不回，服务端只看到 `aborted by peer`，连本机对 192.168.31.220 的拨号也超时。机器上跑着 FlClash，非 loopback 的 UDP 被 TUN 接管，回环不受影响——这也是为什么回环对照能过。要在代理关闭或真机上补验长时间稳定性 |
| 断线即时失败 | 通过（代码路径） | `call` 里的 `lost.changed()` 分支；未在设备上制造断线复测 |

**仍未解决**：

- 手机 app 被杀或在后台被系统冻结时，连接一定会断，回到前台要重连一次；这一次已经能
  静默恢复，但仍会有一次「断开 → 连上」的过程。
- `ACCEPT ERROR handshake failed: aborted by peer` 仍会出现：客户端拨号超时/切换目标时
  会主动放弃握手，服务端如实记一笔，不影响下一次。
- 这一轮的心跳诊断日志（`heartbeat #n sent` / `ping #n received`）先留着，等长时间稳定性
  复测通过再收成只在异常时打印。
- **挂 TUN 模式代理（FlClash 等）时，直连地址的 UDP 会被接管**：这时手机和电脑即使在同一
  Wi-Fi 也握不上手，只能靠中继，而中继同样走 UDP。这一轮的最后几次失败全部属于这一类，
  和代码无关。要么给 Sunday 的进程加直连规则，要么在本机网络里关闭 TUN。

## 未验证（不得当作通过）

* **手机扫电脑的二维码**：电脑这一半已经真实走过（见上表「电脑出码」，出的是 `sunday1:`
  票据与真 SVG 图形，桌面上「开始接受连接」也点了）；手机那一半——相机拍屏幕 → 解码 →
  填入 → 点「连接」→ 显示「已连到 <id>」——还没有在真机上走。要在真机验收，桌面保持
  「正在接受连接」，手机装 `artifacts/android/sunday-m-arm64-debug.apk` 后扫码即可；
  连上后桌面侧的唯一可见证据是 `%APPDATA%\Sunday\p2p\p2p-trust.json` 里新增一条设备记录
  （桌面 UI 不显示对端 ID）。
* **真机实时扫码识别**：模拟器确认了点击“扫码连接”直接打开相机预览（不再调系统拍照），亮度帧解码有 Rust 单测；真机对着真实二维码识别的完整链路还没走。
* **手机端真实模型回复流式**：模拟器上没有可用的模型配置，设置里的模型菜单为空，本轮只验证到直播事件与失败提示；真实回复逐字出现在界面这一段还没有在设备上走通。
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

## 配对排障日志

- 电脑：`%APPDATA%\Sunday\p2p\p2p.log`，由 `sunday-p2p` 自己追加，记录每次出票、中继状态、对端连入（`PEER ...`）和接收错误；桌面宿主新版本也会把传输进程的后续输出写进同一份日志。
- 手机：`files/runtime/guest.log`（核心）与 `adb logcat`（宿主 `[sunday] ...` 行）。

## 真机验收（2026-11-08，vivo V2536A / Android 16 / arm64）

远程模式五步，全部在真机上点出来，不是模拟器结论：

1. 项目 `E:\mobile control test`（在电脑上创建，手机远程可见）；
2. 手机上新建会话并发送「请立即回复你好」，模型 `opencode-go-deepseek-v4.1-flash` 回复
   「你好。」，30 秒内出现在界面；
3. 让它创建文件，`E:\mobile control test\Hello World.txt` 落地，内容 `hello from sunday m`，
   助手回报路径；
4. 让它调子代理：`calc_helper` 启动、返回 1+1=2、结果回到主会话；
5. 让它调 `ask`：手机上弹出选项卡（保留 / 删除），点「保留」后回合继续并给出总结。

同时还确认了：

* 远程模式下模型、权限、插件全部可用（同一份配置由手机继承，不需要在手机上重配）；
* 手机独立运行：本地 Core 在真机上 `proot` 启动成功，3 秒内应答 `core.ready`；
* 断联恢复：换掉电脑侧传输进程后，手机会自动重拨并切回远程，不需要重开应用；
* 冷启动到界面 5.1 秒（`am start` 到无障碍树出现输入框，含 0.35 秒轮询误差）。

手机独立运行（脱离电脑）也用真实模型走通了一轮：本地 Core 在手机上起 proot，`opencode-go`
的 `deepseek-v4.1-flash` 回复「是的，我运行在你这台手机上，工作目录是 /root/.sunday/work」。
权限设为「每次询问」后让它写文件，手机上弹出审批卡（批准执行 / 批准并允许 / 拒绝执行）；
点「拒绝执行」后助手承认文件未创建、盘上无改动。停止按钮也能中断一轮长回答。杀掉应用
（`am force-stop`）再启动，本机会话与回复都在，本地数据库持久化正常。

切换电脑/本机修过一个真 bug：以前点「切换到电脑」只保存票据、断掉隧道就重载，重载时通道
还没通，界面先落回本机，再赌一次后台拨号；而启动阶段那次自动切换留了一个 sessionStorage
去重标记（防重载打转），重载并不清它，于是第二次点就被自己上一次的记录挡住——表现就是
「点切换，转一圈，还在本机」，只有把应用从后台退出重进才恢复正常。现在用户主动切换时先清
掉那条标记，并且**先连上再重载**，一次到位。

设备页与断联文案也顺手改了一版：点整行就能切换（以前只有非当前项才有一颗很小的「切换」
按钮），「当前」按界面实际使用的环境显示，而不是拿隧道状态去猜；断联提示从「回远程连接
点刷新」改成指向真正存在的「设备连接」。资料库页面在本机模式下能正常打开（空库显示空态）。

多客户端并发（同一会话手机与电脑同时发）实测：core 是唯一写方，一轮只接受一个 turn；
后发的那个立刻收到 `SESSION_BUSY / session has an active turn`，客户端按既有逻辑转成排队或
引导，不会两个回合并行。跨设备的会话列表：以前新建会话只通知订阅该会话的连接，实测另一
连接什么都收不到；现在 `thread/start` 会向所有连接广播 `session/created`，另外界面每 20 秒
对一次 `/sessions` 兜底。**这两处要电脑端更新到含该提交的 core 与前端后才生效。**

## 已知问题

1. 上传过程中进程被杀会留下一段 `pending://` 草稿，界面因此拒绝发送，直到把那个附件
   引用移除。桌面同样存在这个草稿状态，只是不容易撞上。
2. 审批通过后最终回复的渲染有延迟（实测那次对话几十秒内完整出现），不是失败。
3. 附件选择在真机上只走到一半：系统的文件选择器能打开、能选到文件、宿主也注册了
   picker 桥，但自动化在「完成」之后的系统 chooser 上被打断，没有把文件送进输入框；
   而且这次选择器返回期间应用进程被系统重建了一次（pid 变了），输入框内容随之丢失。
   需要在真机上人工点一次确认，并考虑选择器返回后恢复输入框草稿。
4. 悬浮环长按拖动、系统小窗仍未在真机上验收。
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
