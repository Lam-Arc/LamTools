# Android 客户端交付说明

分支 `sunday/m-python-core-android`（工作树 `.worktrees/m-python`）。
共享业务实现是 `sunday/superagent-product` 上的原版 Python Core，Android 只提供 Linux
运行环境与平台适配。

## 交付物

| 文件 | 用途 | 大小 |
| --- | --- | --- |
| `artifacts/android/sunday-m-arm64-debug.apk` | 手机（arm64-v8a） | 257 MB |
| `artifacts/android/sunday-m-x86_64-debug.apk` | 模拟器（x86_64） | 258 MB |

校验和（本次构建）：

```
c951cdd2907e5a9080ce5ba577ea94a8e065795310fbb2f666ca475ea8b9349b  sunday-m-arm64-debug.apk
aff9d4e13d4304ff09ce37904bc2dd32a581d6b4e87437630ba86c403002f215  sunday-m-x86_64-debug.apk
```

两个包都是 **debug 签名**，安装需要允许未知来源。一个包只带一个 ABI 的运行时，这是
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
4. 进入「连接模型」页，填 OpenAI 兼容端点、模型 ID 与 API Key。

保存后核心会重启并读取配置，进入工作台。之后再启动不会重复解压。

应用私有目录布局：

```
files/runtime/
  rootfs-<runtimeVersion>/   运行时镜像，升级时整体替换
  userdata/                  数据库、配置、工作区（绑定为 guest 的 /root/.sunday）
  guest.log                  Core 与 proot 的日志
```

用户数据与运行时分离，所以升级不会带走会话和密钥。

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
| 真实模型对话 | 通过 | 用户消息 → 模型回复 "I'll run a single command to get the kernel details." |
| 工具调用与审批 | 通过 | 审批卡片显示 `uname -sr`，批准后 `approval/respond ok` |
| 工具后续跑 | 通过 | 第二步 `model response received step=1 content_len=174` |

## 未验证（不得当作通过）

* **实体 arm64 设备**：本机只有 x86_64 模拟器。ARM64 APK 已产出并检查了内容（5 个
  `arm64-v8a` 库、`rootfs-aarch64.targz`），但没有在真机上安装运行。
* **文件选择与附件传递**：宿主把 `filePicker` 报为不可用，UI 相应隐藏入口。
* **返回键**：已改为最小化而不是结束进程，但未在设备上逐页验证导航。
* **前后台切换与 Activity 重建**：未做专项验证。
* **停止任务**：UI 的停止按钮与 Core 的停止路径未单独验证。

## 已知问题

1. 审批通过后，Core 已经产出最终回复，UI 有时仍停留在「正在处理」，需要刷新或重进
   会话才显示。属事件渲染时序问题，不是业务失败。
2. 多客户端并发没有验证：宿主现在一条 socket 承载所有页面，重连时会重新订阅当前会话。

## 复现构建

```bash
# 1. 运行时（Linux / WSL）
core/android-runtime/tools/build-runtime.sh x86_64
core/android-runtime/tools/build-runtime.sh aarch64

# 2. UI
cd core/ui && npm install && npm run build:android

# 3. APK
cd core/android-host
export SUNDAY_RT_ABI=aarch64
export SUNDAY_RT_ASSETS=$PWD/../android-runtime/tools/out/aarch64/assets
python scripts/android_project.py all --debug --target aarch64
```

## 验收脚本

* `core/android-host/scripts/verify-apk.sh` 安装并报告设备上真实发生了什么；
* `core/android-host/scripts/seed-model.sh` 在无法点击 WebView 时写入模型配置。
