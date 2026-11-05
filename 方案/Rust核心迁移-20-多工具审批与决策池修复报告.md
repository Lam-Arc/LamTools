# Rust 核心迁移 20：多工具审批卡不显示，根因与修复

日期：2026-11-05
分支：`sunday/m16-projection`
设备：Android 模拟器 `sunday_tablet`，debug APK，本机 Ollama `qwen2.5:3b`

## 一句话结论

卡不显示不是投影坏了，也不是卡渲染坏了，而是**界面用来接管输入区的「决策池」从来没人往里写**。
宿主只发会话里的那张卡，池一旦存在，界面就只认池。第一张卡能点，是因为那时池还不存在；
答过一次之后池就有了，后面的卡画得出来但点不动，回合永远停在运行中。

## 一、怎么定位的

按「不预设在前端」的要求，先证明宿主做了什么：

```
11-05 06:05:41.959  core_event -> core/runItem kind=tool_call seq=18
11-05 06:05:41.960  core_event -> core/runItem kind=approval_request seq=19
```

事件确实发出去了。再把设备上的日志事件只读复制下来，用宿主自己的投影在本机重放出界面实际收到的那一帧，
字段完整：`request_id`、`options` 两个、`metadata.waitingRequest`、`tool_call_id` 都对。

所以问题不在这一帧的内容，而在**这一帧少了一条**。

界面的判定在 `pendingDecisions.ts`：

```ts
if (Array.isArray(interactions)) return selectPendingInteractionDecisions(interactions)
```

`interactions` 就是 `core.decisions`，一旦是数组就完全不再看会话里的卡片。
而它变成数组的时机是任何一条 `approval_response` 之后。宿主从来没有发过池更新，
于是：**装好后的第一张卡能点，之后所有卡都点不动**。这解释了为什么同一台机器上单工具有时正常、有时卡住。

## 二、修法

一张卡现在是两帧：

1. 会话行，用户看到的那张卡，`kind: approval_request`；
2. 交互池行，`kind: interaction_update`，`state/lifecycle: appearing`，`status: pending`，
   `turn_id` 为空，`item_id` 用请求 id，`options` 与卡完全一致。

第二帧由第一帧派生，两处不可能各说一套。池行不写 `turn_id`：池行是一次决策，不是回合事实，
写回合会让界面把已结束的回合重新点亮，这一点上一轮已经踩过。

## 三、契约与断言

样本从 12 个场景扩到 15 个，新增的都是这次报告点名的混合情况：

| 场景 | 钉住什么 |
| --- | --- |
| 一次答复两个工具，读自动执行、写要审批 | 两行各自独立，读有结果、写有卡，两个 id 不互相覆盖 |
| 第一张卡答完，第二张卡接管 | 池里旧行消失、新行出现，请求 id 不同 |
| 拒绝 | 卡结算、没有任何工具结果、回合自行结束 |

两侧都跑同一份样本：
- Rust 侧 `projection::contract::the_host_projects_the_shared_event_contract`，
  并把 `every_projected_item_is_domain_valid` 扩展成认识 `interaction_update` 这个池词汇，
  同时要求它必须带生命周期词、必须不带 turn。
- 界面侧用面板真正使用的选择函数 `selectVisiblePendingDecisions` 断言：
  卡出现时面板拿得到、答过一张之后下一张仍然拿得到、拒绝后拿不到。

界面侧 `hand the composer over` 这一条就是这次故障的回归钉：只要池行丢了，它就红。

## 四、设备验收

干净安装、新建项目、新建会话，走真实 UI：

1. 第一条指令 → 8 秒内出卡，点「批准执行」→ 6 秒内 `workspace/demo/notes.md` 落盘，内容正是 goal/progress/tomorrow，
   发送键回到「发送」。
2. 第二条指令（这是关键回归项：池里已经有上一张卡的痕迹）→ 8 秒内出卡，点批准 → 6 秒内 `second.txt` 落盘，内容 done。
3. 强制停止再打开 → 历史在，两张卡都已是结算态，没有待处理卡，发送键空闲。
4. 生命周期报告显示没有未知副作用，`outcome_unknown` 为空。

设备日志同时确认写入位置：`turn workspace for ses-…: /data/data/com.lamtools.sunday.core/workspace/demo`。

## 五、拒绝与停止为什么放在本机验证

这两条是核心语义，不是 Android 特有行为，而设备上的输入自动化在和输入法反复较劲（自动补全把字母拼进地址栏、软键盘让布局位移），
用它验证语义只会把「输入没点中」误判成「功能坏了」。所以：

- 拒绝：本机用例证明不写文件、有结算帧、没有工具结果、回合关闭、下一个回合仍然能拿到自己的审批并落盘；
- 停止：慢模型 + 中途取消，证明没写文件、报告了取消、同一个 runner 接着能接受下一条指令。

顺带纠正了一处样本错误：拒绝路径原本写的是「工具失败」，真实行为是「结算 + 回合结束」，
因为没有执行就不该报工具结果。样本按实际改了，界面断言也从「行失败」改成「行已结算」。

## 六、还没做的

- 一次答复里要求**两个都要审批**的工具：现在一次只挂一个待审批，答完再出现下一个。这是执行器的节奏，
  界面已经能连续处理；但如果后续要让多个审批同时挂着，池和面板都要按多行设计，那时再写契约。
- 设备上仍然有输入法带来的自动化噪声。真要长期用设备做验收，得先固定一个可控的输入通道，
  否则每次都在验证「我点中了没有」。

## 七、怎么复现

```
cd core/android-host/src-tauri && cargo test --lib          # 48 项，含多工具/拒绝/停止
cd core/ui && npx vitest run tests/android-host-event-contract.test.ts \
  tests/approval-projection-chain.test.ts tests/pending-decisions.test.ts
```
