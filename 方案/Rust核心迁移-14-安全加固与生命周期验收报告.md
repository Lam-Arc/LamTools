# Rust 核心迁移 14：安全加固与生命周期验收报告

日期：2026-11-03
分支：`sunday/m3-isolated-core`
前一轮：`2b84800b`（第 13 轮，安全边界与单一宿主）

本轮的四个目标：把 API Key 绑定到确认过的端点、用操作系统生命周期替代前端自报、用实测数据决定 WAL 检查点策略、给只读工具划出隐私边界。结论先说：四项都做完了，WAL 那一项**实测推翻了原来的优化设想**，所以代码上没做优化，只补了监控。

生产接管仍然不批准。剩余阻断项在最后一节列全。

---

## 一、Provider 凭据安全

### 做了什么

`core/sunday-core/crates/sunday-host/src/provider.rs` 从"能被调用的校验函数"变成"真实调用路径上的闸门"。

| 规则 | 实现 | 测试 |
|---|---|---|
| Key 与供应商 + 目标端点绑定 | `ProviderBook`：`(vendor id) -> (scheme://host:port)` | `a_tampered_address_does_not_carry_the_key_along` |
| 改地址必须重新确认 | `admit()` 返回 `NeedsApproval`，调用方不确认就不发 | `a_changed_endpoint_is_blocked_until_it_is_confirmed`（Android 侧） |
| 默认 HTTPS | `Endpoint::parse` 先验协议再谈绑定，HTTP 公网主机连解析都过不去 | `plain_http_to_a_public_host_is_refused_even_with_opt_in` |
| HTTP 必须显式声明 | `TransportPolicy { allow_insecure_local }`，默认 `false`，且只对回环/私网生效 | `plain_http_to_localhost_needs_the_explicit_opt_in` |
| 拒绝带凭据的跨源重定向 | `reqwest` 的 `Policy::none()`，一个 3xx 都不跟 | `a_cross_origin_redirect_never_reaches_the_other_host` |
| URL 格式/协议/主机/端口校验 | 拒嵌入凭据、拒 query、拒 fragment、拒通配符主机 | 5 项 |
| 密钥不进日志/错误/事件/UI | `redact_secret` 在错误分类前执行；`public_view` 只暴露 `has_api_key` 布尔 | `an_error_body_that_echoes_the_key_is_redacted` |

三个设计决定值得单独说：

**绑定不含路径，含端口。** `https://host/v1` 换到 `/v2` 是同一个信任决定，换端口不是。`a_path_change_on_the_same_host_stays_authorised` 和 `a_custom_port_is_a_different_destination` 固定了这个分界。

**没有记录绑定的旧 Key 视为未授权，不视为默认同意。** 升级上来的用户会看到一次确认提示，这是正确的一次性摩擦；反过来假设"以前能用所以现在也能用"正是配置被篡改时的漏洞。

**绑定文件里没有 Key，也没有 Key 的摘要。** 密钥在平台机密存储里，绑定文件只有端点指纹。摘要能告诉我们的只是"Key 变了"，而 Key 变了是用户主动做的事。`the_binding_file_holds_no_key` 守住这条。

### 负向验证（真实网络，不是 mock）

`core/sunday-core/crates/sunday-llm/tests/credential_safety.rs` 对着真 socket 跑：

```
a_cross_origin_redirect_never_reaches_the_other_host ... ok
a_same_origin_redirect_is_also_refused ... ok
an_error_body_that_echoes_the_key_is_redacted ... ok
a_permission_failure_does_not_quote_the_provider_body ... ok
an_unsigned_certificate_aborts_the_handshake ... ok
```

证书那一项用的是真实 TLS 握手：`tests/fixtures/self-signed-cert.der` 起一个 `tokio-rustls` 服务端，断言**握手完成次数为 0**，而不是只断言错误文本长得像证书错误。

### 变异验证（证明测试不是空的）

把保护拆掉，对应测试必须失败。第一版有两条测试是空的，被这一步抓出来：

| 拆掉的保护 | 预期失败的测试 | 结果 |
|---|---|---|
| 重定向恢复默认跟随 | 两条重定向测试 | 都失败 ✔ |
| 错误体不再脱敏 | `an_error_body_that_echoes_the_key_is_redacted` | 失败 ✔ |
| 401 开始引用响应体 | `a_permission_failure_does_not_quote_the_provider_body` | 失败 ✔ |
| 接受非法证书 | `an_unsigned_certificate_aborts_the_handshake` | 失败 ✔ |

**5/5 命中。** 第一次跑时"脱敏"那条仍然是绿的：因为 401 的错误压根不带响应体，脱敏被移除也看不出来。改成 400（唯一会把响应体拼进错误的状态码之一）之后才真正测住。

### 接入的两条真实路径

- CLI：`sunday serve` 的 `model_from_args` 改成先过 `admit()`。地址变了但没有 `--confirm-endpoint`，直接拒绝启动并说明原因，不是警告。
- Android：`provider::build_model` 同样过闸门。未批准时返回一个**拒绝一切请求的模型**（`CoreError::PermissionDenied`），而不是"这次先放行"。配置里的 `confirm_endpoint` 必须由设置界面写入，配置文件不能自己给自己授权。

`public_view` 增加 `endpoint_approved` 与 `endpoint_prompt`，让界面能说清"为什么模型不回答"，同时不含任何密钥。

---

## 二、Android 原生生命周期

### 关键事实：Tauri 只暴露一半

读 `tauri-2.12.5/src/app.rs` 确认：`WindowEvent::Suspended` 由 `onPause` 触发，`WindowEvent::Resumed` 由 `onResume` 触发，**`onStop` 没有任何原生出口**。而用户要求用 `onStop` 处理后台状态，因为 `onPause` 在旋转屏幕和权限弹窗时也会触发。

所以 `onStop` 必须从 Kotlin 直接进入 Rust。做法是新增 `LifecycleBridge.kt` 的一个 `external fun`，配一个 `#[no_mangle] extern "system"` 的 JNI 函数，绕开 webview。这也顺带满足了"不能只依赖 Vue 主动通知"：后台的 webview 正是 Android 最先节流的东西。

### 四类事件被区分开

`core/sunday-core/crates/sunday-host/src/lifecycle.rs`：

| OS 事件 | 含义 | 动作 |
|---|---|---|
| `onPause` | 失焦，可能仍然可见 | 只记内存时间戳，**不写盘、不碰数据库** |
| `onStop` | 不可见，可能被冻结或杀死 | 写一个很小的标记文件 |
| `onDestroy` | Activity 说再见 | 在标记里记下 `destroyed` |
| 没有 `onDestroy` + 下次进程号不同 | 进程死了 | 读日志 |

进程号是每次启动生成的 8 字节随机值。旋转屏幕会重建 Activity 但进程不变，所以进程号相同即"没有被中断"；被杀死或被强停会换进程号。

### 五条铁律的落点

1. **日志是事实，标记是提示。** 恢复报告里 `journal` 字段来自 `Store::recover()`，`advisory_threads` 才来自标记，而且名字里就写着它是提示。
2. **同一进程仍在跑就必须显示运行中。** `turn_state` 的第一优先级是 `running_threads` 非空，此时代码根本不看日志和标记。`a_resume_in_the_live_process_reports_running_not_interrupted` 守住。
3. **不自动重放。** 所有报告形状都带 `auto_resumed_turns: false`；`a_tool_killed_mid_flight_needs_a_decision_and_is_not_replayed` 用真实 Store 验证：已派发、非幂等的调用在 `recover()` 之后是 `Unknown`，不是可重排队。
4. **不可读的日志不等于没问题。** `Journal::Unavailable` 一律报 `needs_attention`。
5. **不承诺后台一定跑完。** `on_stop` 报告里 `background_execution_guaranteed: false`。

### 设备上发现并修掉的两个真 bug

这两个只有真跑起来才会暴露：

**一、冷启动的第一次 `onResume` 丢失。** Android 在 `setup()` 注册状态之前就送来 `onResume`，于是最该报的那份报告——"上一个进程死了"——永远不产生。修法是在 `setup()` 末尾主动做一次 resume。

**二、强停会误报"任务中断"。** 前台被强停、什么都没在跑时，`previous_end: unclean` 就触发 `needs_attention`，等于给每一次正常关应用弹横幅。改成只有"标记说当时有任务在跑"才要求处理，同时保留 `previous_end` 这个事实。

第三个修正来自思考：重启报告之后必须把标记归拢到当前进程，否则同一进程后续每次恢复都会再报一次"重启"。

### 验收结果（Android 16 模拟器，x86_64，1080x1920）

证据来源：`/data/user/0/com.lamtools.sunday.core/lifecycle.reports.log`（追加式审计日志，只写不读回做决策），通过 `run-as` 读取。

**冷启动（首次，无标记）**
```json
{"process":"fresh","previous_end":"none","turn_state":"idle","auto_resumed_turns":false,
 "journal":{"available":true,"outcome_unknown":[],"abandoned_receipts":[]}}
```

**切到后台再回前台（同一进程）**
```json
{"signal":"stop","persisted":true,"turn_stopped":false,"background_execution_guaranteed":false,
 "noted_threads":[]}
{"signal":"resume","process":"same","previous_end":"none","turn_state":"idle",
 "backgrounded_for_ms":1694,"auto_resumed_turns":false}
```

**后台 + 强杀 + 重启**
```json
{"process":"restarted","previous_end":"unclean","turn_state":"idle",
 "note":"The previous process ended unexpectedly, but nothing was running and the journal has no unfinished work."}
```

**工具执行中进程死亡 + 重启**（把一份"非幂等调用已派发、没有结果"的真实数据库放进设备数据目录，再重启应用）
```json
{"process":"restarted","previous_end":"unclean","turn_state":"needs_attention",
 "journal":{"available":true,"outcome_unknown":["call-1"]},
 "note":"The previous process ended while work was in flight. What is unfinished comes from the journal.",
 "auto_resumed_turns":false}
```

**旋转屏幕**：`AndroidManifest.xml` 声明了 `configChanges="orientation|screenSize|..."`，Activity 不会被重建，核心**完全收不到生命周期信号**。旋转前后报告日志零新增，进程号不变。这是正确行为：旋转不是中断。也意味着"Activity 在同一进程内被重建"这条分支由单元测试覆盖（`a_rotation_is_not_an_interruption`），不是设备覆盖。

**分屏：未能验收。** `am start --windowingMode 3|4` 对已运行任务被系统忽略（返回"its current task has been brought to the front"），最近任务里的拖拽分区靠盲坐标也没落中。不把它记成通过。

### 单元测试

`sunday-host` 里 15 项，不依赖 Android：

```
a_pause_writes_nothing_and_touches_no_turn
a_pause_does_not_create_or_touch_a_database
a_stop_records_the_process_without_claiming_a_guarantee
a_resume_in_the_live_process_reports_running_not_interrupted
a_resume_with_nothing_running_is_idle
a_rotation_is_not_an_interruption
a_first_launch_is_fresh_not_a_restart
a_restart_without_a_goodbye_is_an_abnormal_death
a_kill_with_nothing_running_does_not_ask_for_attention
a_restart_is_reported_once_and_then_the_process_is_the_same
a_destroyed_activity_is_a_clean_end
the_journal_decides_what_was_interrupted
an_unreadable_journal_is_not_all_clear
a_corrupt_marker_is_not_a_crash_report
a_tool_killed_mid_flight_needs_a_decision_and_is_not_replayed
```

---

## 三、SQLite WAL 治理

### 先测默认，再决定

顺序按用户要求：先量默认自动检查点的延迟，有尖峰才引入独立连接的后台 PASSIVE。结果是没有尖峰。

测量环境：`cargo test --release`，Windows，真实落盘，`synchronous=FULL` 保持不变。每条样本 = 一条用户消息（3 次提交：用户消息、工具事件、助手回复）。

**默认（`wal_autocheckpoint` = 1000 页）**

| 载荷 | p50 | p95 | p99 | p99.9 | 最大 | WAL 峰值 | >3×中位数的提交 |
|---|---|---|---|---|---|---|---|
| 0.5 KB | 5.936 ms | 6.059 ms | 9.879 ms | 11.973 ms | 11.973 ms | 4051 KB | 0 |
| 8 KB | 5.945 ms | 6.082 ms | 11.970 ms | 13.981 ms | 13.981 ms | 4051 KB | 0 |
| 64 KB | 5.940 ms | 13.919 ms | 15.932 ms | 18.038 ms | 18.038 ms | 4107 KB | 3 / 500 |

**改成 4000 页 + 独立连接后台 PASSIVE（每 50 ms）**

| 载荷 | p50 | p95 | p99 | p99.9 | 最大 | WAL 峰值 | >3×中位数的提交 |
|---|---|---|---|---|---|---|---|
| 0.5 KB | 5.937 ms | 6.530 ms | 7.995 ms | 15.842 ms | 15.842 ms | 16113 KB | 0 |
| 8 KB | 5.942 ms | 6.070 ms | 7.891 ms | 14.827 ms | 14.827 ms | 16129 KB | 0 |
| 64 KB | 5.928 ms | 6.584 ms | 13.987 ms | 17.944 ms | 17.944 ms | 16298 KB | 1 / 500 |

**结论：不采用。** p99 的差值在噪声内且正负翻转（-1.9 / -4.1 / -1.9 ms），p99.9 和最大值反而变差（+3.9 ms、+0.8 ms、-0.1 ms），而 WAL 峰值从 4 MB 涨到 16 MB，**+297%**。用四倍磁盘换一个测不出来的改进，不是优化。

Windows 上 5.94 ms ≈ 3 × 1.98 ms，延迟分布本身被约 2 ms 的 fsync/定时器粒度量子化，这也是为什么 4 ms 级的检查点事件在分布里很难与噪声区分。

### 一次检查点到底多贵

不靠分布推断，直接量：关掉自动检查点，写到 1000 帧（117 次提交，4003 KB），然后计时一次完整 PASSIVE，重复 6 轮，每轮按提交数重新填满。

```
round 0: 6.030 ms
round 1: 3.938 ms
round 2: 4.000 ms
round 3: 4.062 ms
round 4: 5.921 ms
round 5: 4.082 ms
中位 4.082 ms（min 3.938 / max 6.030）
```

即：**每 117 次 8 KB 提交付出一次约 4 ms 的检查点**。这解释了两张表：它落在 p99.9 附近，不在 p99 里。

第一版这个测试有缺陷：用 WAL 文件大小判断"日志是否重新填满"，而 PASSIVE 从不截断文件，所以只有第一轮是真实测量，后四轮都在空转（0.004 ms）。改成按提交数填满后才得到上面这组数。

### 饥饿与恢复

长读事务会挡住 PASSIVE。测试用第二个连接持有一个打开的快照：

```
with the reader open: 1569 frames, 297 backfilled, file 6312 KB, starved true
after the reader closed: 1569 frames, 1569 backfilled, starved false
```

**这里修掉一个真 bug。** 原来的 `wal_health()` 用 `PRAGMA wal_checkpoint` 返回的第一列 `busy` 判断饥饿，而 SQLite 只对 `RESTART`/`FULL`/`TRUNCATE` 置位，PASSIVE 永远是 0，也就是说 `starved` 永远不会为真——"检查点饥饿"这个指标从来没有生效过。改成比较"日志里的帧数"与"已回填的帧数"，并且同时报告帧字节数和 `-wal` 文件字节数（PASSIVE 不截断，只看帧数会把一个从不缩小的文件看成健康）。

### 落地的策略

- `synchronous=FULL` 不变。
- `wal_autocheckpoint` 保持默认 1000 页，**不加后台检查点线程**。
- 保留 `wal_health()` 作为监控原语：帧数、已回填、文件字节、是否饥饿。
- `checkpoint()`（TRUNCATE）只给维护窗口和测试用。

持久性没变：500 条已提交事件，在后台检查点全程运行的情况下进程被非正常终止，重开后 `seq` 连续无空洞（`a_background_checkpoint_does_not_weaken_durability`）。

---

## 四、Pure 工具的隐私边界

`SideEffect::Pure` 只说明不改状态，不说明可以看什么。一次读取返回私钥比一次写入更糟，因为结果会直接进入模型上下文，再从那里发给供应商。

### 三层边界分别守

**文件读取。** `LocalFiles::resolve` 本来就在读路径上应用 `PathPolicy`，缺的是证据和覆盖范围。本轮补齐并扩充规则：新增 `.kube`/`.docker`/`.azure` 目录段，`id_dsa`/`.git-credentials`/`.npmrc`/`.pypirc`/`.htpasswd` 文件名，`.pfx`/`.jks`/`.keystore`/`.ppk` 扩展名。

**模型上下文。** 被拒绝的读取**不产生 `ToolOutput`**，所以没有任何东西可以放进提示词。测试断言错误信息里既不含内容也不含变量名。

**网络发送。** `web_fetch` 原来只查 `http(s)://` 前缀，并且跟随最多 20 次重定向。这两点合起来就是一个只读工具的后门：指向 `127.0.0.1` 拿本机服务，或者指向 `169.254.169.254` 拿云元数据凭据，或者用一个公网 URL 302 到 `127.0.0.1` 绕过一次性的检查。

改成：解析成真正的 `Url`；只允许 http/https；拒绝 URL 里的凭据；拒绝本机与私网主机；**每一次重定向都重新校验**。第一跳可以是被明确配置的本机端点，重定向不可以——重定向是远端服务器决定的，不是用户。

### 一个判定，两处使用

`is_local_host` 抽到 `sunday-platform`，`sunday-host`（允许本机的 http，需显式开启）和 `sunday-tools`（一律拒绝）共用一份实现。同一类地址规则写两遍，早晚会有一份是错的。

这个判定本身也被测试抓过一次：第一版把 `fd00:ec2::254` 归到公网（它其实是 AWS 元数据地址，落在 fc00::/7 私有段内），而且完全没解析 `::ffff:127.0.0.1` 这种带点分后缀的映射地址。

### CI 抓到一个本地测不出来的漏洞

第一次推送后 Linux 作业失败，`a_symlink_cannot_smuggle_a_credential_past_the_policy` 的日志是：

```
called `Result::unwrap_err()` on an `Ok` value: ToolOutput { content:
"{\"content\":\"sk-live-should-never-be-readable-4a7f\",\"path\":\"innocent.txt\",...}" }
```

也就是说，`read_file` 通过一个叫 `innocent.txt` 的软链接，把 `.ssh/id_rsa` 的内容读出来了。

原因：`LocalFiles::resolve` 把 `PathPolicy` 作用在**用户输入的那串相对路径**上（`innocent.txt`，不在拒绝列表里），之后只校验链接解析后的目标是否还在工作区内——而 `.ssh/id_rsa` 确实在工作区内，两道检查都过了。

这个漏洞在 Windows 上没暴露，因为本地测试里的软链接分支是 `#[cfg(unix)]`，Windows 建软链接需要特权，于是那一段被静默跳过，测试**绿色的同时洞是开着的**。

修法是策略作用在解析后的真实路径上：

```rust
if let Ok(relative) = resolved.strip_prefix(&self.root) {
    let actual = relative.to_string_lossy().replace('\\', "/");
    if !actual.is_empty() && !self.policy.allows(&actual) {
        return Err(CoreError::PermissionDenied { resource: format!("{rel} resolves to a protected path") });
    }
}
```

对尚不存在的路径，`deepest_existing` 会落到最近的已存在祖先目录，所以新建文件只检查它落在哪个目录里，这正是应该检查的东西。

测试也改成两个平台都跑：能建链接就断言，建不了就**明确打印原因**而不是安静通过。修完之后做了变异验证——把那行判断改成 `false`，测试立刻失败。

这是本轮第二次被平台差异藏住真问题（第一次是 Provider 那条把 401 当成脱敏证据的空测试）。

### 负向测试

`core/sunday-core/crates/sunday-tools/tests/read_privacy.rs`：

```
credentials_are_never_readable_through_a_pure_tool ... ok   （26 个敏感路径逐一验证）
ordinary_files_are_still_readable ... ok
a_symlink_cannot_smuggle_a_credential_past_the_policy ... ok
a_refused_read_puts_nothing_into_the_model_context ... ok
the_network_tool_cannot_be_pointed_at_this_machine ... ok
```

`web_fetch` 侧另有 5 项：本机默认被拒、元数据端点被拒（含 IPv6 与私网）、非 http 协议被拒、URL 带凭据被拒、**重定向到本机时第二个服务器连接数为 0**。

### 变异验证

| 拆掉的保护 | 结果 |
|---|---|
| 清空 `PathPolicy` 的拒绝列表 | 26 个敏感路径测试失败 ✔ |
| 去掉 `web_fetch` 的本机判定 | 网络边界测试失败 ✔ |
| 策略不作用在解析后的路径上 | 软链接测试失败 ✔ |

**3/3 命中。**

---

## 五、闸门与数字

`sunday-core` 工作区，本轮结束状态：

```
cargo fmt --all -- --check                          干净
cargo clippy --workspace --all-targets -- -D warnings   0 警告
python scripts/check-deps.py                        ok 10 crates, edges and tokens clean
cargo test --workspace                              240 passed / 0 failed / 38 ignored
```

上一轮同口径：181 passed / 32 ignored。本轮新增 59 项。

远端 CI（GitHub Actions，真实执行）：

| 运行 | 提交 | dependency rules | windows | linux | android target check |
|---|---|---|---|---|---|
| 41672518148 | 7d251787 | 成功 | 成功 | **失败**（软链接漏洞） | 成功 |
| 41674834852 | 94190a21 | 成功 | 成功 | 成功 | 成功 |

第一次 Linux 失败是本轮最有价值的产出：它在 Windows 上永远是绿的。

Android 宿主自身的单元测试（此前从未编译通过，本轮修好）：

```
cargo test --lib (android-host)    11 passed / 0 failed
```

这里面有一个测试意外发现了真问题：`a_hosted_vendor_without_a_key_is_blocked` 最初把供应商写成 `openai-compatible`，而这类端点允许无 Key，于是闸门正确地放行了一个空 Key 客户端，测试随即**真的向 api.openai.com 发了请求**。这类"单元测试打真网络"的隐患靠跑一遍才发现。

数据安全：真实用户库 `data/core.db` 全程未读写，大小 `3676884992` 字节、mtime `1793633617`，与前面各轮开始前一致。设备上操作的是模拟器里应用自己的数据目录。

---

## 六、剩余阻断项

按"是否阻断正式接管"排序。前四项每一项单独都足以阻断。

1. **Android Keystore 未接入。** `secrets::backend()` 如实返回 `RestrictedFile`，密钥现在是一个 0600 的普通文件。在这条完成之前，**不得宣称密钥达到系统级安全存储**。
2. **没有真机验证。** 本轮全部设备证据来自 AVD（Android 16，x86_64）。模拟器通过不等于真机通过，这是发布前的强制项。
3. **分屏未验收。** 见第二节，工具能力限制，不是代码问题，但确实是验收缺口。
4. **APK 构建未进 CI。** 现在靠手工 `tauri android build` + 手工签名。
5. **权限 UI 缺失。** Provider 端点确认和 `GrantPolicy` 的逐工具授权，目前只有配置字段和命令行开关，没有设置界面。缺 UI 时 Android 端的表现是"模型拒绝回答并给出原因"，这是安全的，但不可用。
6. **只有一个供应商 wire 被真实跑过。** Anthropic 分支有测试，但没有对着真实端点验证过。
7. **任务质量只测了压缩后续执行一项**（沿用上轮）。
8. **事件表没有归档策略**（沿用上轮）。

另外两个已知的、不阻断但需要写下来的取舍：

- `web_fetch` 有一个 `allowing_local_endpoints` 构造器，只给测试和明确配置过的开发环境用。生产路径必须永远是默认构造。
- `PathPolicy` 的前缀规则会把 `.env.example` 也拒掉。这是保守方向的误伤，和 Python 核的规则一致。

---

## 七、本轮交付物

新增：

- `core/sunday-core/crates/sunday-host/src/provider.rs`（绑定层与闸门）
- `core/sunday-core/crates/sunday-host/src/private_file.rs`（唯一的"仅属主可读文件"实现）
- `core/sunday-core/crates/sunday-host/src/lifecycle.rs`（生命周期判定）
- `core/sunday-core/crates/sunday-llm/tests/credential_safety.rs`（5 项传输负向测试）
- `core/sunday-core/crates/sunday-llm/tests/fixtures/self-signed-cert.der`、`self-signed-key.der`
- `core/sunday-core/crates/sunday-store/tests/wal_checkpoint.rs`（5 项测量）
- `core/sunday-core/crates/sunday-tools/tests/read_privacy.rs`（5 项隐私边界）
- `core/android-host/.gitignore`（`gen/` 里手写的两个 Kotlin 源改为强制跟踪）
- `core/android-host/src-tauri/src/provider.rs`（Android 侧闸门）
- `core/android-host/src-tauri/gen/android/app/src/main/java/com/lamtools/sunday/core/LifecycleBridge.kt`

改写：

- `core/android-host/src-tauri/src/lifecycle.rs`（薄壳，判断全在 `sunday-host`）
- `core/android-host/src-tauri/src/config.rs`（供应商字段与公开视图）
- `core/android-host/src-tauri/src/lib.rs`（JNI 桥、冷启动报告、模型闸门）
- `core/android-host/src-tauri/gen/android/app/src/main/java/com/lamtools/sunday/core/MainActivity.kt`（四个系统回调）
- `core/sunday-core/crates/sunday-tools/src/web_fetch.rs`（网络边界）
- `core/sunday-core/crates/sunday-platform/src/lib.rs`（共享 `is_local_host`，扩充 `PathPolicy`）
- `core/sunday-core/crates/sunday-cli/src/serve.rs`、`main.rs`（CLI 接入闸门）
