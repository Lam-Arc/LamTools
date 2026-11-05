# Android 客户端：应用内 Linux 承载共享 Python Core

分支 `sunday/m-python-core-android`（工作树 `.worktrees/m-python`，基线
`sunday/superagent-product` @ `857de2a9`）。

目标：Sunday M 与桌面版是同一产品的两个平台版本，共用同一套业务 Core。本文记录这条
路线的取舍、已经实测通过的边界，以及尚未验证的部分。

## 一、为什么不复用 M16 的 Rust Core

M16 把业务逻辑用 Rust 重写了一遍（`core/sunday-core/crates/*`），在 Android 上跑得通，
但那是一条需要长期双份维护的实现路线：每个功能都要在 Python 和 Rust 各写一次，行为
一致性靠人工对齐。

本次改为：**Android 应用内跑一个 Linux 环境，里面启动原版 Python Core**。宿主编译除了
UI 之外不含任何业务代码，功能只存在于 `core/src/lamtools_core` 一处。

M16 仍然复用的是它的**平台资产**：Tauri 2 Android 工程脚手架、五个 Kotlin 桥
（文件选择、键盘、Keystore、生命周期、打开文件）、`tauri android` 构建流程、以及共享
UI 已有的 Android 入口（`ui/src/core-app/main-android.ts` + IPC transport）。这些是平台
事情，与业务无关，重写才是浪费。

## 二、运行机制

参考 `ccch1mneyyy/dsh-Go` 的应用内 PRoot 方案（其 `runtime/build-runtime.sh` 与
`RuntimeController.kt` 已在本地逐行核对），并做了两点针对 Python Core 的调整：

1. rootfs 用 Ubuntu 24.04 base 而不是 Alpine。Core 依赖全是 glibc wheel（PyMuPDF、
   pillow、cryptography、sqlalchemy），musl 环境需要逐个源码编译，是永久维护成本。
2. Python 用 python-build-standalone 3.14.10（AMD64 / ARM64 都有 `install_only_stripped`
   版本），直接满足 `requires-python >=3.14`，不在设备上编译任何东西。

```
APK 资产
  assets/runtime/manifest.json          版本、哈希、启动模板
  assets/runtime/rootfs-<abi>.tar.gz    Ubuntu base + Python 3.14 + core 源码 + wheels
  lib/<abi>/libproot.so                  Termux proot 5.1.107.102
  lib/<abi>/libproot-loader.so, libtalloc.so.2, libandroid-shmem.so
        │
        ├─ 首次启动：解压到 filesDir/runtime/rootfs（每个运行时版本一次）
        │
        └─ 每次启动：proot --rootfs=... /opt/sunday/start_core.py <port>
                          │
                          ├─ 绑定 127.0.0.1，启动 uvicorn（真实 Core）
                          └─ 端口与 bearer token 由宿主生成，不落盘、不进 UI
```

### 访问控制

Android 上「本机回环」等于「任何别的 App 都能连」，所以：

* Core 以 `LAMTOOLS_CORE_ALLOW_LAN=1` + `LAMTOOLS_CORE_API_TOKEN=<32 字节随机>` 启动，
  该策略下**包括 loopback 在内所有调用方**都必须带 `Authorization: Bearer`；
* 端口和 token 只存在于宿主进程内；
* WebView 不直连端口，UI 走 Tauri IPC（`core_rpc` / `core_http`），宿主转发时注入 token；
* 因此没有任何监听端口暴露给第三方 App。

实测：无 token 请求返回 401，带 token 正常返回项目列表。

## 三、已实测通过（Android 16 x86_64 模拟器）

| 项 | 结果 | 证据 |
| --- | --- | --- |
| PRoot 在 Android 16 上执行 | 通过 | `proot --rootfs=... /bin/echo PROOT_WORKS` |
| Python 3.14.10 在 guest 内运行 | 通过 | `3.14.10 ... glibc 2.39` |
| 标准库完整性 | 通过 | sqlite3 / ssl / zlib / lzma / bz2 / ctypes / hashlib / asyncio / multiprocessing / socket 全部 import 成功 |
| guest 内 DNS | 通过 | `pypi.org`、`registry.npmmirror.com` 解析成功 |
| guest 内 HTTPS + pip 安装 | 通过 | `pip install httpx aiosqlite` 成功并可导入 |
| 构建脚本产出的 rootfs 可用 | 通过 | 用 `build-runtime.sh` 产出的 `rootfs-x86_64.tar.gz` 解压后启动，Core ready |
| 真实 Core 启动 | 通过 | 数据库建表、WAL、插件加载、`Uvicorn running on 127.0.0.1` |
| 真实模型调用 | 通过 | 一次 turn 输入 14945 tokens，输出 145，`usage_source=provider` |
| Agent 工具调用 | 通过 | 模型生成 `write_file` 调用（参数完整） |
| 审批机制 | 通过 | 未授权工具进入 `waiting` + `approval_request`，含 approve/trust/deny 选项 |
| 批准后继续执行 | 通过 | 批准后出现新的 `response-1` 事件流并执行工具 |
| 文件写入落盘 | 通过 | guest 内 `notes.md` 内容与要求一致（三行文本） |
| aarch64 运行时构建 | 通过 | `out/aarch64` 产出 200 MB rootfs + 四个 `.so` |

### APK 端到端（Android 16 x86_64 模拟器，debug 签名）

| 项 | 结果 | 证据 |
| --- | --- | --- |
| APK 构建 | 通过 | `app-universal-debug.apk` 282 MB，含 `rootfs-x86_64.targz` 与 5 个 `.so` |
| 安装 | 通过 | `adb install` 成功，包名 `com.lamtools.sunday.core` |
| 首次初始化 | 通过 | Kotlin 流式复制 assets → 解压 596 MB rootfs（跳过 2 个 Android 拒绝的条目）→ 写入安装标记 |
| 应用内启动 Core | 通过 | `libproot.so` 与 `python3.14` 均为 app 自身 uid 进程，Uvicorn 监听随机 loopback 端口 |
| 共享 UI 加载 | 通过 | 与桌面同一套 `LamToolsApp`，中文界面、软键盘 inset、配置页与主界面均正常渲染 |
| UI ↔ Core 通道 | 通过 | WebSocket `/api/core/app-server` accepted，`GET /api/core/projects` 200 |
| 配置生效 | 通过 | 写入 Core 的 providers/models 后重启，UI 从配置页进入主界面 |
| 二次启动 | 通过 | 已安装时跳过解压，Core 直接拉起 |

## 四、已知缺陷

1. **返回键直接退出 App**。WebView 内的弹窗/键盘不拦截系统返回键，用户按返回会离开
   应用而不是关闭当前面板。需要在 Activity 层拦截并交给 WebView 处理。
2. **“选择项目”在 Android 上不可用**。该入口依赖系统文件选择器，而宿主把
   `filePicker` 报为不可用，按钮点了没有反馈。
3. **新建项目表单在软键盘弹出时按钮被遮挡**，且提交后没有可见的失败提示；用
   `scripts/seed-model.sh` 直接写配置可以绕过，但这是产品缺陷不是方案。

## 五、未验证

* **实体 Android 设备（arm64）**：本机在线设备只有 x86_64 模拟器。aarch64 的 rootfs 和
  proot 已经构建出来，但没有在真机上跑过。
* **APK 安装与首次初始化**：构建流程已跑通，安装/解压/首启尚未在设备上验收。
* **前后台切换、异常退出恢复**：Core 自身的 turn journal 恢复逻辑未在 Android 上验证。
* **Android 文件选择与附件传递**：宿主目前把 `filePicker`/attachments 报为不可用，
  UI 相应地隐藏入口。
* **会话/历史/Library 的 UI 操作**：依赖上面的 APK 验收。
* **便携模型供应商差异**：只验证了 opencode-go（OpenAI 兼容）一个端点。

## 五、已知限制

* 每个 APK 只带一个 ABI 的运行时（rootfs 内含该 ABI 的 Python），不产出通用包。
* PRoot 是用户态路径翻译，比桌面慢：Core 冷启动约 3–4 秒，`run_command` 有明显额外开销。
* runtime 解压后约 600 MB；首次启动要为解压付时间。
* bundled 插件 `network-exploration` 在启动时报「仅支持 Windows 桌面端」并跳过；这是插件
  自身的能力判断，不是移植缺陷。其余 bundled 插件正常加载。

## 六、交付物

| 项 | 位置 |
| --- | --- |
| APK（debug 签名，x86_64） | `artifacts/android/sunday-m-x86_64-debug.apk`（501 MB，未压缩含调试符号） |
| APK SHA-256 | `d2768e581a8f5f2cbfb9c30c24fe1e3f10262f21d20e52692b094567262787d1` |
| 源码 | 分支 `sunday/m-python-core-android`，工作树 `.worktrees/m-python` |
| 运行时构建 | `core/android-runtime/tools/build-runtime.sh`（x86_64 / aarch64） |
| 安装与验证脚本 | `core/android-host/scripts/`（`android_project.py`、`verify-apk.sh`、`seed-model.sh`） |

**这是 debug 签名，不是可发布版本。** 安装需要开启「允许安装未知来源」。首次启动会解压
约 600 MB 的运行时，耗时取决于设备存储速度（模拟器约 40 秒）。

安装与初始化：

```bash
adb install -r artifacts/android/sunday-m-x86_64-debug.apk
adb shell am start -n com.lamtools.sunday.core/.MainActivity
```

首次进入会停在「连接模型」页：填接口地址（OpenAI 兼容）、模型 ID 与 API Key，保存后
核心会重启并写入 Core 自己的 providers/models 配置，再进入主界面。

## 七、构建与运行

```bash
# 1. 构建运行时（Linux/WSL）
core/android-runtime/tools/build-runtime.sh x86_64     # 模拟器
core/android-runtime/tools/build-runtime.sh aarch64    # 真机

# 2. 构建 UI
cd core/ui && npm install && npm run build:android

# 3. 构建 APK
cd core/android-host
export SUNDAY_RT_ABI=x86_64
export SUNDAY_RT_ASSETS=$PWD/../android-runtime/tools/out/x86_64/assets
python scripts/android_project.py all --debug --target x86_64
```

`android_project.py sync` 会把运行时所需的 Gradle 配置（`useLegacyPackaging`、单 ABI 过滤、
assets 目录）注入 `gen/android/app/build.gradle.kts`，保证重新生成工程后配置不丢。
