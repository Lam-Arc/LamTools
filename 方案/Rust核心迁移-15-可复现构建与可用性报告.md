# Rust 核心迁移 15：可复现构建与可用性验收报告

日期：2026-11-03
分支：`sunday/m3-isolated-core`
上一轮：`83b9bee2`

本轮目标从反复加固转向可用性：把手写 Kotlin 从生成目录里拿出来、让 APK 能从干净环境构建、用大屏 AVD 做脚本化多窗口验收、接入系统级凭据存储、补上模型设置界面。

生产接管仍不批准。剩余阻断项在最后一节。

---

## 一、Kotlin 源码迁出 gen/

### 问题

`MainActivity.kt` 与 `LifecycleBridge.kt` 原来只存在于 `src-tauri/gen/android/` 里。那个目录是 `tauri android init` 的产物，本来就该随手可弃：把它当唯一来源，等于把源码放在一个可以被一条命令抹掉的位置。

上一轮我把它们强制加进了 git，代价是全新克隆时 git 会把这两个文件报成已删除。那不是解决办法，只是把问题藏进版本库。

### 现在的结构

```
core/android-host/
  android-src/com/lamtools/sunday/core/     <- 手写 Kotlin 的唯一来源
    MainActivity.kt
    LifecycleBridge.kt
    KeystoreBridge.kt
  scripts/android_project.py                <- 单一入口
  src-tauri/gen/                            <- 纯生成，回到完全忽略
```

`scripts/android_project.py` 五个子命令：

| 命令 | 作用 |
|---|---|
| `sync` | 把 `android-src` 注入生成工程。字节相同则不重写，所以每次构建前跑不会触发 Kotlin 重编译 |
| `ensure` | `gen/android` 缺失时自动 `tauri android init`，然后注入 |
| `build` | `ensure` + 构建 APK |
| `verify` | 打开 APK，断言它真的含 `LifecycleBridge`、`MainActivity` 与 `.so` |
| `all` | 以上全部 |

`verify` 是这里最重要的一步：编译通过不等于注入成功，生成工程会在没有我们那三个文件的情况下照常编过。只有检查打包产物才知道。

退出码按调用方可读的方式区分：`0` 成功、`2` 环境不全（SDK/NDK/JDK/node/CLI）、`3` 工程形状不对、`4` 构建失败。

### 干净目录验证（真实执行）

把 `src-tauri/gen` 整个移走后跑 `all --debug --target x86_64`：

```
[android] generated project missing, running `tauri android init`
[android] exit 0 in 1s
[android] sync: 2 written, 0 unchanged
[android] exit 0 in 167s
[android] verify: native library: yes
[android] verify: class LifecycleBridge (dex): yes
[android] verify: class MainActivity (dex): yes
[android] the APK carries the bridge and the Rust library
```

装进模拟器后生命周期报告与之前一致（`fresh` → `pause` → `stop` → `same`），说明从零重建出来的 APK 行为相同。

一个环境事实值得记下来：`gen/` 移不走时会报 `Permission denied`，是 Gradle 守护进程占着目录。`gradlew --stop` 之后立刻可以移动。这是环境问题，不是代码问题。

---

## 二、APK 构建进 CI

新增 `.github/workflows/android-apk.yml`，触发路径为 `core/android-host/**`、`core/sunday-core/**`、`core/ui/**` 和它自己。步骤是干净 checkout → JDK 17 → node 24 → Rust `aarch64-linux-android` 目标 → NDK → 构建真实 UI → 装 Tauri CLI → `python3 scripts/android_project.py all --debug --target aarch64` → 断言注入的源文件仍在 → 上传 APK。

没有用占位前端：嵌入的是真正的应用外壳，否则这个 job 只能证明 Android 管线通，说明不了应用能构建。

### CI 第一次运行就发现的问题

失败信息：

```
error: proc macro panicked
= help: message: failed to open icon core/android-host/src-tauri/icons/icon.png:
  No such file or directory (os error 2)
```

根目录 `.gitignore` 有一条 `*.png`，把 Android 的启动图标一起挡掉了，只有 `icon.ico` 早先被强制加入过。本地因为文件一直在，永远看不到这个问题。

修法是给那个路径开例外，理由写在 `.gitignore` 里：`tauri::generate_context!` 在编译期读这些文件，没有它们干净 checkout 根本编不过。

---

## 三、大屏 AVD 与多窗口验收

### 为什么之前分屏从来没成功

查清了：`am start --windowingMode 3|4`（分屏主/次）**对已存在的任务被系统忽略**，返回 "Activity not started, its current task has been brought to the front"。之前几次尝试都败在这里，和屏幕尺寸无关。

平台文档化的多窗口入口是自由窗口：开发者选项 `enable_freeform_support` + `am start --windowingMode 5`。开启后重启，同一台设备上真的得到了自由窗口：

```
mWindowingMode=freeform
mBounds=Rect(971, 245 - 1589, 1343)      窗口 618x1098
display=2560x1600                        应用自认为 sw412dp w412dp h732dp
```

这是真正的多窗口形态：窗口小于屏幕，桌面在其后可见。

### 大屏 AVD

新增 `scripts/android_emulator.py`，`create/start/wait/stop/install/sh/state` 六个子命令，平板与手机两个 profile。平板是 2560x1600@240dpi、4GB 内存、`hw.multiWindowSupport=true`。

之前那台手机 AVD 是 320x480（config.ini 里压根没写宽高，模拟器用了默认值），低于分屏可用尺寸，也不像任何真实设备。

### 验收脚本与结果

`scripts/android_acceptance.py`，每项给出通过 / 失败 / 不支持三态和证据，不支持项必须写原因。

| 检查 | 结果 | 证据 |
|---|---|---|
| 多窗口能力 | 通过 | `cmd activity supports-split-screen-multi-window` → true |
| 自由窗口进入 | 通过 | 窗口 (618,1098) 在 (2560,1600) 内 |
| 切回全屏 | 通过 | freeform → fullscreen，边界等于显示尺寸 |
| 显示尺寸变更 | 通过 | `cmd window size 1600x1000` 生效，应用存活 |
| Home 后台化自由窗口 | 通过 | `pause` `stop` → 返回 `resume`，同一进程 |
| 被全屏应用覆盖 | 通过 | 覆盖时 `stop`，返回时 `resume`，无自动重放 |
| 自由窗口下旋转 | 通过 | 无任何后台转换信号 |
| 单实例 Core | 通过 | 一次进程生命周期内 `sunday core ready` 只出现一次 |
| 键盘弹出 | 通过 | 聚焦文本框后 `mInputShown=true`，应用存活 |
| 键盘收起 | **不支持** | 见下 |

**键盘收起记的是不支持，不是通过。** 这台镜像上 `dumpsys input_method` 在焦点离开后仍报 `mInputShown=true`，`adb shell ime` 没有 hide 子命令，按 BACK 会结束 Activity 而不是收起键盘。手动点应用自己的"返回"按钮曾让状态变回 false，但不可靠复现。留待真机验收。

### 首轮跑出来的三条错误断言（都已修正）

1. `wm size` 把覆盖尺寸放在 `Override size:` 行，只读 `Physical size:` 会把生效的变更看成被忽略。
2. 按 Home 后自由窗口确实从屏幕消失（截图确认），所以 `stop` 是对的。任务保留的 bounds 是记忆值，不代表可见。
3. 脚本点设置入口点得太早，在首帧之前，点到了别的地方。加上首帧等待。

---

## 四、Android KeyStore

### 设计

`KeystoreBridge.kt` 在 AndroidKeyStore 内生成 AES-256 密钥（GCM、无用户认证要求，因为密钥要在应用运行时用），密文是 `iv + body` 的 Base64。Rust 经 JNI 调用。

`secrets.rs` 三种模式，区别是重点：

| 模式 | 何时 | 写入行为 |
|---|---|---|
| `Sealed` | Android，密钥库可用 | 加密后落盘，删除任何明文 |
| `PlainFile` | 桌面构建 | 仅属主可读的文件（不等于密钥库，界面如实标注） |
| `Broken` | Android 但密钥库拒绝 | **拒绝写入**并返回原因，绝不降级成明文 |

旧版明文密钥在首次读取时自动迁移：加密、落盘、然后才删除明文。

### 踩到并修掉的三个真问题

**一、桥从未注册。** 第一次跑出来的是"the bridge was never registered"。原因是 Kotlin 对象惰性初始化：Rust 在 `setup()` 里探针时，`KeystoreBridge` 的 `init` 还没跑过。修法是 `MainActivity.onCreate` 在 `super` 之前先触碰它一次。

**二、附加线程找不到应用自己的类。** 注册之后仍然每次调用都抛 Java 异常，而 Kotlin 侧一条日志都没有，说明方法根本没被进入。这是 JNI 的经典陷阱：从附加的原生线程 `FindClass` 用的是系统类加载器，找不到应用类。修法是在 `nativeRegister` 这一次来自该类自身的调用里缓存 `GlobalRef`，之后都用它。

**三、密钥读不出来被当成"没有密钥"。** `build_model` 原来写的是 `read_api_key(dir).unwrap_or_default()`，一份解不开的密文（换了设备、清了密钥库、恢复了备份）会和"没配置"完全一样，用户只会在供应商那里收到 401。改成明确拒绝并说明原因，同时把"密文是否真的能解开"写进启动日志与 `model_config`。

### 设备实测

```
credential storage: "android-keystore" (needs migration: false, key present: true, readable: true)
```

`readable: true` 是在**进程重启之后**读到的，也就是密文真的被解开了。

从界面填入密钥后落盘的文件：

```
-rw-------  core.secret.enc     68 字节密文
```

没有 `core.secret` 明文文件。

---

## 五、模型设置界面

### 为什么不复用桌面那张设置页

桌面 `CoreSettings.vue` 编辑的是一个供应商目录（多个供应商、多个模型）。这个宿主只有一个端点、一把密钥。合在一起会变成每个处理函数里都有一个平台分支，两边都难读。

所以新增 `core/ui/src/core-app/AndroidSettings.vue`，从 `main-android.ts` 以浮层接入，首次打开才挂载。共享的应用外壳没有改动。

### 界面包含

供应商（自建/OpenAI/Anthropic）、接口地址、模型、允许本地明文 HTTP、API Key（保存/替换/删除）、端点确认、逐工具授权。

三条界面不做的事，因为后端不允许：

1. 不显示密钥，也拿不到密钥。只知道有没有、存在哪里、能不能解开。
2. 不能靠改地址替用户批准目的地。改地址会清掉批准，界面转黄。
3. 不假装保存成功。密钥库拒绝时把错误原样显示。

### 真实交互（模拟器，逐步操作）

| 操作 | 结果 |
|---|---|
| 打开设置 | 显示当前真实的供应商、地址、模型、Keystore 后端 |
| 填入 `sk-test-keystore-0173` 并保存 | 生成 `core.secret.enc` 密文，无明文文件；端点确认转为"未批准" |
| 点"批准当前地址" | `provider.bindings.json` 写入 `openai-compatible -> http://10.0.2.2:11434` |
| 授予 `write_file` 免询问 | `core.config.json` 的 `granted_tools` 出现 `write_file`，再点一次撤销 |
| 授予 `read_file` | `granted_tools` 变为 `["read_file"]` |
| 把地址改成 `:11435` 并保存 | `confirm_endpoint` 置 false，绑定文件仍是 `:11434`，界面回到黄色"该地址尚未批准" |

最后一条是这轮最关键的产品行为：**改一个输入框不能把手里的密钥送到新主机**，用户必须重新看到新地址并按下批准。

### 授权改为运行时可换

原来 `CoreRunner` 的授权策略是启动时固定的字段，改授权要重启应用。那不叫可配置。

改成 `Arc<LivePolicy>`（内部 `RwLock<GrantPolicy>`），下一次工具调用立即生效；已决定的调用保留原决定，否则会出现工具已经跑起来才被批准的情况。读写分别走读锁和写锁，热路径上没有额外分配。

工具清单也收敛到 `CoreRunner::build_tools` 一处，`tool_catalog` 读同一份。设置界面因此不可能给出一个不存在的工具的授权。

---

## 六、闸门与数字

`sunday-core`：

```
cargo fmt --all -- --check                              干净
cargo clippy --workspace --all-targets -- -D warnings   0 警告
python scripts/check-deps.py                            ok 10 crates, edges and tokens clean
cargo test --workspace                                  240 passed / 0 failed / 38 ignored
```

Android 宿主自身：`cargo test --lib` 12 passed。

APK：`python scripts/android_project.py all --debug --target x86_64` 成功，`verify` 三项全过。

设备验收：`android_acceptance.py` 9 项通过、1 项不支持、0 项失败。

数据安全：真实用户库 `data/core.db` 全程未读写，大小 `3676884992` 字节、mtime `1793633617`，与前几轮一致。设备上操作的是模拟器里应用自己的数据目录。

---

## 七、剩余阻断项

按是否阻断正式接管排序。

1. **没有真机验证。** 本轮全部设备证据来自 AVD。Keystore 在模拟器上可用不代表在某些厂商 ROM 上可用；键盘收起、分屏手势都还没在真机验证。
2. **设置界面只覆盖模型与权限。** 工作目录、会话、附件仍然没有界面，应用现在能配置但还不能完成一次真实任务。
3. **改模型仍需重启应用生效。** 界面已如实提示，但模型是启动时构建的，热切换还没做。
4. **键盘收起未断言。** 见第三节，留给真机。
5. **`web_fetch` 没有注册进 runner。** 核心里有这个工具，Android 宿主的工具清单里没有它，设置界面也就不会显示。这是产品缺口，不是 bug。
6. **任务质量只测了压缩后续执行一项**（沿用前几轮）。
7. **事件表没有归档策略**（沿用前几轮）。

---

## 八、本轮交付物

新增：

- `core/android-host/android-src/com/lamtools/sunday/core/MainActivity.kt`
- `core/android-host/android-src/com/lamtools/sunday/core/LifecycleBridge.kt`
- `core/android-host/android-src/com/lamtools/sunday/core/KeystoreBridge.kt`
- `core/android-host/scripts/android_project.py`
- `core/android-host/scripts/android_emulator.py`
- `core/android-host/scripts/android_acceptance.py`
- `core/android-host/src-tauri/src/keystore.rs`
- `core/android-host/src-tauri/src/settings.rs`
- `core/ui/src/core-app/AndroidSettings.vue`
- `.github/workflows/android-apk.yml`

改写：

- `core/android-host/src-tauri/src/secrets.rs`（三种模式，拒绝降级，自动迁移）
- `core/android-host/src-tauri/src/config.rs`（保存、供应商字段、凭据存储视图）
- `core/android-host/src-tauri/src/lib.rs`（命令注册、启动日志）
- `core/android-host/src-tauri/src/provider.rs`（密钥不可读时拒绝）
- `core/android-host/.gitignore`（`gen/` 回到纯忽略）
- `core/ui/src/core-app/main-android.ts`（设置浮层接入）
- `core/sunday-core/crates/sunday-host/src/policy.rs`（`LivePolicy`）
- `core/sunday-core/crates/sunday-host/src/runner.rs`（工具清单收敛、运行时策略）
- `.gitignore`（Android 图标例外）
