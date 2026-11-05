# Super-agent 产品化：功能清单与端到端验收

日期：2026-11-05
分支：`sunday/superagent-product`（基于 `sunday/reliable-merge` `13ee92e2`）
工作树：`E:\LamTools\.worktrees\superagent`

## 一、起点：以源码为准的盘点

盘点结论先说：Super-agent 原本是一套**没有出口的底层模块**。

| 能力 | 源码位置 | 原状态 |
| --- | --- | --- |
| Source / Policy / Eval | `superagent/models.py`、`policy.py` | 已实现，硬闸门完整 |
| Ticket / Assignment / Effect | `models.py`、`effects.py` | 已实现，状态机完整 |
| Store | `store.py` + `core_db.py` 的 `SqlAlchemySuperagentStore` | 已实现，按 kind 分区的单表 |
| Worktree 隔离 | `worktree.py` | 已实现，ticket 号进分支与目录 |
| 排期 | `http_agent_app.py` 注入 `arrange_manager.create` | 已接通，复用 Arrange |
| 操作面 | `app/superagent_operations.py` | 已注册 9 个操作 |
| CLI | `cli_commands/superagent.py` | 已实现 ingest / tickets / show / approve / reject / stop |
| 界面 | — | **完全没有** |
| 用户交付入口 | — | **没有**，只能靠外部事件 + 环境变量授权 |
| 结果回写 | — | **断的**：`start_assignment` / `finish_assignment` 只有测试在调，生产链路没人调 |
| 规划 / 委派 / 验证 | — | 没有，工单指令就是目标原文 |

最关键的断点：排期把工单推成 `running` 之后，执行结果永远回不来，**每张工单都会停在 running**。这就是「模块的集合」与「能用的产品」之间的全部距离。

## 二、这次补上的东西

### 1. 执行闭环

- `submit_goal`：用户直接把目标交给 Super-agent。仓库白名单仍然生效，推送与 PR 默认关闭，选择记进审计。同一目标在活跃期间重复提交返回 duplicate，不会排两次。
- `begin_execution`：排期前一次备好执行现场。是 git 仓库就开独立工作树和分支，是普通目录就原地执行；随后按目标生成指令。
- `record_execution_result`：结果写回工单。成功进 `review`，失败进 `blocked` 并带上真实错误。
- `close_ticket` / `retry_ticket`：验收通过或退回，失败或已交付的可以再跑一次。停下与重试都会先取消底层排期任务，不会出现「界面说停了、后台还在跑」或者「重试叠出好几个任务抢同一个工作树」。
- `http_agent_app`：排期器调用 `begin_execution`，`execute_arranged_job` 执行完回写；执行抛异常时也回写失败。排期本身仍然交给 Arrange，没有第二套调度器。

### 2. 指令：让它真的自己做完

`superagent/prompt.py` 生成的指令要求：先摸清现状再动手、用 `write_checklist` 写计划、独立子任务用 `sub_agent` 委派（并把当前模型 id 直接给它，不让它编模型名）、必须跑真实命令验证、按四段格式汇报（做了什么 / 怎么验证的 / 没做到什么 / 用户接下来要做什么）。

### 3. 人工关口

- **开工前确认**：`require_approval` 让工单停在 `blocked`（`awaiting-user-approval`），人批准后才排期。
- **交付验收**：`review` 阶段由人 `close` 收下或退回。
- 明确拒绝 `permission_preset="ask"`：ask 要求每次工具调用都在会话里点头，后台工单没有可回答的审批卡。实测结果是工单空转到超时、一个字节都没写，所以直接拒绝并指向 `require_approval`。

### 4. 界面

`CoreSuperAgentPanel.vue`，三个视图：交付目标、看进度、验收或退回。阶段用文字加圆点（执行中脉冲，待验收蓝色，需处理橙色），不靠颜色单独表达。接在左侧导航（聊天之后），同时进分屏菜单，复用现有页面绑定、顶部条动作和设计 token。

### 5. CLI

`core superagent goal / report / close / retry` 与界面走同一条 RPC，满足「每个界面能力都有对应 CLI」。

## 三、端到端验收

环境：真实服务器 `core serve`，真实模型 `opencode-go-deepseek-v4.1-flash`，两个独立的真实 git 仓库（`wordcount`、`logsum`，起始提交里函数是 `NotImplementedError`，测试是红的）。

### 场景一：多任务并行 + 工作树隔离

同时交付两个目标到两个仓库。

| 工单 | 结果 | 独立复核 |
| --- | --- | --- |
| `tkt_214052bab7f948ea` wordcount 词频统计 | `closed` | 我本人在工作树里跑 `pytest`：12 passed；`python -m wordcount` 输出 `apple 3 / banana 2 / cherry 1`，与 `top_words` 一致；改动只在 `ticket/tkt_214052bab7f948ea` 分支，`master` 未动，未推送 |
| `tkt_f85d553adb20f980` logsum 级别统计 | `closed` | 我本人跑 `pytest`：10 passed；CLI 输出与 `awk \| sort \| uniq -c` 的结果逐项一致 |

两张工单各自一个工作树、各自一条分支，互不覆盖。

### 场景二：开工前人工审批

`tkt_1a9222a3e2860d6e` 以 `require_approval` 提交。

- 提交后状态 `ask_human`，工单 `blocked`，原因 `awaiting-user-approval`。
- 批准前工作树目录**不存在**，说明确实没开工。
- `approve` 之后状态 `running`，工作树随即创建，模型开始执行。

### 场景三：中断恢复

对正在执行的工单直接杀掉服务器进程，然后重启。

- 重启日志：`recovered 5 stale active turn(s) after unexpected shutdown`，排期被重新接管。
- 第一次实测时，恢复后的重试全部撞在 `RuntimeStateConflictError: Session ... is being written by another running process` 上，工单永远停在 `running`。这是真缺陷，已修：执行抛异常时结果也会回写工单。
- 修完之后工单落到 `blocked`，并带上 `RuntimeStateConflictError: ...` 这条真实原因，不再空转。
- 工作树里已经写下的改动全部保留。中断前那一段改到一半的代码，重启后仍然在。
- 试过把存储的「落后 revision 一律拒绝」放宽成「自己进程写的就放过」，重试确实能跑通（冲突计数 0），但这会让两个运行时交叉写同一行、旧状态覆盖新状态，正是既有安全用例 `test_core_runtime_store_rejects_stale_concurrent_state_write` 固定住的边界。已回退，不拿数据安全换这一条恢复路径。

结论：强杀会打断当前这一轮，重启后 Arrange 重新接管；已经落到工作树里的工作不会丢，工单带着真实原因停在 `blocked` 让人判断。自动续跑还差运行时侧的「启动时释放已死进程的占用」，本次没有做。

## 四、过程中发现并修掉的真实缺陷

1. **工单永远停在 running**：结果回写钩子只在执行正常返回时跑，抛异常就什么都不写。已改为异常路径也回写失败。
2. **`approve` 返回旧状态**：批准后排期已经把工单推到 running，但接口返回的是排期前的对象，界面会显示成还没开工。已改为返回刷新后的记录。
3. **`ask` 档在后台空转**：见上文，已改为明确拒绝并指向 `require_approval`。
4. **「停下」停不下、重试叠任务**：`stop` 只改工单阶段，底层排期任务照跑；`retry` 不取消上一轮，同一张工单可能叠出好几个任务抢一个工作树。两处都改成先取消再动状态。

## 五、现在的功能清单

用户可以做的：

- 把一段复杂目标交给它，指定目录、基线分支、是否允许推送 / PR、要不要先确认。
- 在列表里看每张工单做到哪一步（待开始 / 执行中 / 待验收 / 需处理 / 已交付）。
- 打开详情看目标、权限边界、每次执行的分支与工作树、结果摘要与错误。
- 批准开工、验收通过、退回、再跑一次、停下。
- 跳到这次执行的会话里看完整过程。
- 命令行做同样的事。

它自己做的：读代码摸清现状、写计划、拆解、委派子任务、改代码、跑测试验证、处理失败、按四段汇报、把改动提交到工单分支且不推送。

## 六、还没做的

- **GitHub 工作流**：没有专门的 PR / 评论副作用执行器。`effects.py` 里的幂等 outbox 还在，但没有接远端适配器。当前它靠 `run_command` 调 `git` / `gh`，受工单的推送 / PR 权限约束。要真正做成「一键开 PR」还差一个 GitHub 适配器。
- **强杀后的自动续跑**：能停得干净（工单带原因落到 blocked、工作不丢），但不能自动接着跑。要自动续跑得让运行时在启动时释放已死进程的会话占用，那会牵动「两个运行时不得交叉写」的守卫，本次明确没做。
- **`ask` 档的逐条审批**：明确不支持，没有做后台审批卡。
- **观察器驱动**：Observer 已接通（事件触发排期），但这次没有做「外部事件自动建工单」的端到端验收，只验证了用户直接交付。
