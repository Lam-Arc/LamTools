# Rust 核心迁移 19：真实任务端到端验收报告

日期：2026-11-05
分支：`sunday/m16-projection`（worktree `.worktrees/m16`）
设备：Android 模拟器 `sunday_tablet`，ABI x86_64，debug APK
模型：本机 Ollama `qwen2.5:3b`，经 `10.0.2.2:11434/v1`

## 一句话结论

**从干净安装到重启恢复，全流程在设备上用真实 UI 操作跑通了**：新建工作环境、新建会话、发指令、审批、执行、文件落盘、结果显示、关掉应用再打开历史都在。
过程中设备暴露出两个只有真机才看得见的缺陷，都已按契约修掉并补了断言。
还剩一个产品层面的真问题：Agent 写文件的位置不是用户建的工作环境，见第六节。

## 一、本地先验证，再上设备

设备只回答 Android 特有的事。业务逻辑先在本机用真代码路径跑：

| 断言 | 位置 | 覆盖 |
| --- | --- | --- |
| 指令 → 审批卡 → 批准 → 文件内容一致 → 结果 → 回合结束 | `core/android-host/src-tauri/src/loop_contract.rs` | 真实 `CoreRunner`、真实存储、真实 `write_file`、真实审批门，只把模型换成脚本 |
| 同一份事件流，投影后能画出卡和文件 | 同上 | 宿主输出到界面之间那一步 |
| 第二个回合有自己的身份 | 同上 | 回合 id 唯一，`run_started` 不会被当成重复丢掉 |
| 重放的事实保持同一个身份、同一份内容、同一个时间 | 同上 | 去重与时间戳 |
| 派发后死掉、没有结果的写：报为未知，且拒绝再次执行 | 同上 | 故障注入，落库的 `tool_call_stages` 为准 |
| 新进程读同一个库，历史完整、卡片不再可点 | 同上 | 恢复 |
| 协议字段与桌面核一致 | `src/projection/contract.rs` + `core/ui/tests/android-host-event-contract.test.ts` | 同一份样本两侧读，12 个场景 |

数字：宿主 `cargo test --lib` 44 项；界面契约 11 项；`sunday-store` 67 项、`sunday-host` 59 项。

## 二、设备验收的实际步骤

全部通过模拟器 UI 完成，没有注入数据库、没有调用测试入口。

1. 卸载重装 debug APK，清空应用数据，当作新装。
2. 启动，进入设置：接口地址 `http://10.0.2.2:11434/v1`、模型 `qwen2.5:3b`，端点确认显示“该地址可用”，工具权限显示读取放行、写入每次询问。
3. 新建项目：地址 `…/workspace/demo`，项目 `demo` 建成。
4. 新建会话，输入 `Create notes.md with three lines: goal, progress, tomorrow.`，发送。
5. 约 10 秒后出现审批卡：`等待确认：write_file`，带“批准执行 / 拒绝执行”。
6. 点“批准执行”。
7. 8 秒后：`workspace/notes.md` 存在，内容正是 `goal` / `progress` / `tomorrow` 三行；发送键回到“发送”。
8. 强制停止应用，再启动：用户指令、助手回复、`@notes.md` 引用、本轮成果都在；没有遗留审批卡；发送键是空闲态。

## 三、设备暴露的缺陷一：答复把已完成的回合重新点亮

**症状**：回合成功、主张行都渲染完之后，发送键仍然是“停止运行”，正文写着“正在输出”。

**证据**：把设备上的库只读复制下来看日志，这次会话的事件顺序是

```
11 run_completed          （turn 无）
12 ...                    （回合完成）
13 approval_resolved      turn=-
```

`approval_resolved` 是核心在答案落地之后写的，**它本身不带 turn_id**。投影按“补上当前回合”的老规则给它填了 `turn-1893…-1`，界面把“指名某个回合的审批答复”理解为“该回合继续”，于是刚报完完成的回合又被置为运行中。

**修法**：`item/approval_resolved` 永不继承回合。答复要关的那一行在工具准备时就记住了，跟回合无关，所以脱离回合不损失任何东西。
断言：两份样本（带显式空 turn、完全不带的真实形状）加一条界面断言“答复晚于回合完成时，回合必须保持不活跃”。

## 四、设备暴露的缺陷二：一批结算事件挤在同一个空 id 上

恢复一段老会话时，日志里出现 8 条 `ses-…:::tool`。那是恢复时补结算的终结事件，只有请求 id、没有工具调用，而 id 是按工具调用拼的，空调用就拼出了空作用域，8 条共用一个 id。

**修法**：没有工具调用的终结事件用请求 id 作为行 id，与桌面核一致。样本加了一个场景钉住它。

## 五、顺带修掉的时间戳问题

`journal_events.created_at` 从 v1 就在库里，读路径一直没取，所以每帧的 `created_at` 是空串，手机端条目时间戳是 0。现在：

- `sunday_protocol::Event` 带上日志行时间；
- 两条读路径（`events`、`history_page`）都取它；
- `BridgeEvent` 带 `created_at_ms`，只有来自日志行时才有值；
- `event_json` 输出 RFC-3339，未知时**省略**该键而不是给空串；
- 投影用帧上的时刻给条目盖时间，不再现取当前时间。

闭环测试从外部验证：重放同一事实，事件 id、内容、时间三者都不变。

## 六、没解决的：Agent 写文件的位置不是用户建的工作环境

这是这一轮最重要的遗留问题，**用户能直接看到**。

- 用户新建的项目 `demo`，工作目录是 `…/workspace/demo`。
- Agent 的写根是 `…/workspace`，于是 `notes.md` 落在了 `workspace/` 而不是 `workspace/demo/`。
- 界面把 `@notes.md` 按项目目录解析：`GET /files/resolve-reference?path=notes.md -> 404`，引用上带红点。

也就是说“创建工作环境”目前对 Agent 的落盘位置没有约束。修它需要把工具根从“进程一个”改成“按会话所属项目”，属于架构层改动，不是补一个参数。

## 七、另一个小遗留

强制停止发生在回合刚结束之后时，启动报告会报 `abandoned_receipts` 一条、`turn_state: needs_attention`。界面照常加载、可以用，但这条记录没有任何地方向用户解释。

## 八、怎么复现这一轮

```
# 本机
cd core/android-host/src-tauri && cargo test --lib
cd core/ui && npx vitest run tests/android-host-event-contract.test.ts

# 设备
export ANDROID_IGNORE_TAURI_VERSION_MISMATCH=1
cd core/android-host && python scripts/android_project.py all --debug --target x86_64
adb install -r src-tauri/gen/android/app/build/outputs/apk/universal/debug/app-universal-debug.apk
```

设备上跑完整流程时，注意项目地址只能填应用沙盒内的路径，填 `/sdcard/...` 会被明确拒绝。
