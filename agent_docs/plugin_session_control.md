# 插件宿主契约：桌面会话控制 v1

user:“每一个地方 sunday 都有等价或者近似接口”+(将会话创建、消息接收、排队、引导、取消和持久读取统一为公开契约；复用桌面权威，并写清 DSH 差异)。

## 入口与可用时机

桌面宿主在等待插件 start/on_load 之前公开 `sessions` 服务，保留已有 `live_turn_service`。插件从公开 SDK 引用版本化协议：

```python
from lamtools_core.plugin_system import SESSIONS

class Runtime:
    def start(self, context):
        self.sessions = context.bind_service(SESSIONS)

    async def run(self, session_id: str):
        receipt = await self.sessions.call(
            "prompt", session_id,
            request_id="one-logical-message-id",
            text="整理这个项目", mode="queue",
        )
        # receipt 只证明消息已被接收，不能当作模型完成结果。
        settled = await self.sessions.call("wait", session_id, timeout=10)
        return receipt, settled

def create_plugin(context):
    return Runtime()
```

类型和结果结构位于 `lamtools_core.plugin_system.sessions`；记录使用 frozen dataclass，可通过 `dataclasses.asdict()` 转为普通字典。`SessionError` 带 `code`、`session_id`、`details`。原业务异常和取消不会伪装为成功。

服务只在具备 live host / SQLite 的桌面宿主提供。纯 Python 组装、无 live host 的进程或 process runtime 不能假定存在此能力，仍应通过 bind_service 检查。不提供新的网络端口、Typert Remote 或跨进程回调。

## 方法

| 方法 | 参数 | 返回与含义 |
| --- | --- | --- |
| `create` | 可选 `session_id`、`title`，均为关键字参数 | `SessionState`；创建新的持久 thread，不启动模型；省略 id 时生成新 id |
| `state` | `session_id` | 被动读取 `SessionState`，不激活模型 |
| `prompt` | `session_id`；必填关键字 `request_id`、`text`；可选 `mode='queue'`、`work_root=''` | `MessageReceipt`，表示已接收的文本消息 |
| `update_queue` | `session_id`、`queue_item_id`；指定 `text=...` 或 `delete=True` | `QueueChange(applied, reason)`；编辑/删除还在等待的条目 |
| `cancel` | `session_id`；可选关键字 `turn_id` | `CancelReceipt`；取消请求的回执，不等待后台收尾 |
| `events` | `session_id`；`after_seq=0`、`limit=100`、`max_bytes=1048576` | 按持久 seq 正序读取 `SessionEventPage` |
| `follow` | 与 events 相同 | 从排他游标开始的异步迭代器，持续产出 Sunday 持久事件字典 |
| `wait` | `session_id`；`timeout=30` 秒 | `SessionWaitResult(reason, state)`；等待会话停稳、受阻或达到截止时间 |

创建通过现有 `thread.start` 接收路径。数据库事务内检查 require_new，因此不会覆盖已有实体，包括项目先创建、revision 仍为 0 的空白会话。它不绑定 workspace/preset，也不承诺将会话加入某个项目分组；项目绑定属于后续工作区接口。`work_root` 目前仅在 prompt 中提供，交给原有输入和权限解析流程，不自行修改沙箱或审批配置。

## 消息模式与去重

`mode='queue'` 总是走既有 queue.create，作为下一轮输入落盘。运行中不会误变成 steer。空闲/已完成会话有可用运行器时，唤醒原有队列派发；消息转为普通轮次，写入桌面用户消息投影。没有运行器时，消息仍已接收，`wake_error` 返回调度问题，不能以此新建另一条消息。

`mode='steer'` 在已有活跃轮次时走现有 turn.steer。执行边界已关闭、目标变化或运行器明确拒绝引导时，按共享处理结果转入下一轮队列，回执的 disposition 明确反映实际去向。空闲或暂停状态不凭空制造引导轮次，而是登记队列。暂停不会被自动恢复；需要沿用已有显式 resume 控制。

`request_id` 是调用者提供的同一逻辑消息身份。宿主把 session id 与 request id 组合成持久去重键。并发重试、跨模式重试及重建 service 后的重试，都从原来的接收事件恢复身份，而不是读一份内存缓存。同一 id 重试即沿用第一次接收的内容；更改内容或创建另一条消息必须使用新 id。请求取消时，已开始的短接收/激活交接仍完成，调用方保留 CancelledError；重试应继续使用原 id。

`MessageReceipt` 字段：

- `session_id`、`request_id`、`message_id`：会话、调用方身份、宿主持久消息键。
- `disposition`：实际为 `queued` 或 `steered`。
- `event_seq`：接收事实所在的持久事件序号。
- `queue_item_id` / `turn_id`：按接收方式提供身份；排队后派发不改写原回执的接收身份。
- `accepted=True`、`completed=False`：只确认已接收，不将请求与某轮完成强绑定。
- `wake_error`：消息已落盘之后的启动交接问题；同 id 重试可重新尝试唤醒。

## 状态与等待

`SessionState` 返回：session_id、last_event_seq、status、running、active_turn_id、active_run_id、paused_turn_id、queued_count、queue_item_ids。last_event_seq 是持久事件读取游标，不是 CAS revision，也不是完整历史。

status 采用桌面持久投影的状态；running 同时考虑宿主的执行认领。两者可能短暂不同，例如轮次已持久完成但运行认领还未释放，不会仅凭一个字段宣称完全空闲。历史暂停轮次不会被当作当前取消目标。

wait 不关联某一条 prompt 的完成归属，也不返回假造的助手回答。reason：

| reason | 含义 |
| --- | --- |
| `idle` | 没有活跃运行和待处理队列；不等于任务成功，仍须检查 status 和事件 |
| `blocked` | 会话暂停/等待，或失败、取消后仍有待处理队列；不保证一定是人工审批 |
| `timeout` | 截止时仍未停稳；不取消 Agent |
| `closed` | 宿主关闭，返回最后一次已读取的状态 |

timeout 接受有限的 0–60 秒；0 为立即读取。取消 wait 只取消读取，不向模型发送停止。宿主关闭先唤醒被动读取，再清理插件和数据库。

## 取消与队列

cancel 使用桌面既有 turn.cancel，保留当前待处理队列；不偷偷改为终止全部资源或删除消息。省略 turn_id 时，从当前活跃/暂停的逻辑轮次确定目标；显式旧目标不会命中新代运行。

回执可能为 cancelling、idle 或 stale_target。cancelling 仍有后台收尾，completed=False；需要观察 state/events 或继续 wait。队列编辑返回 applied=False 时，调用者必须处理 reason，不能当作修改成功。删除条目只操作指定队列身份，不清空其他输入。

## 历史与跟随

events 使用 Sunday 已有持久 AppEventEnvelope，主要字段为 seq、event_id、thread_id、method、payload 等，不是 DSH 的 SessionEvent.type/data。after_seq 为排他游标；返回 next_after_seq 和 has_more。limit 限 1–500；max_bytes 限 512–4194304，约束返回事件的 JSON 字节总量，不包含外层封装开销。

游标超前报 session/invalid-cursor；历史有缺口或被清理报 session/cursor-expired；单个事件超过预算报 session/event-too-large，不跳过该事件、不推进游标。调用者可增大预算或交给 agent 处理，不会返回貌似完整但少了一段的记录。

follow 逐页读取同一持久源，追平后默认每 250ms 查询一次，故提交后遗漏通知仍能读到。它不订阅 hub，不提供瞬态 token，也不制造 snapshot/ready 帧。先读 state 获取当前事实；要历史则从 0 读取，要新增事实则从已保存的 next_after_seq 继续。

迭代器由插件持有，应在取消/卸载时关闭。持续读取应作为插件自己的任务管理；在该任务的 finally 中调用 feed.aclose()，在 on_dispose 中取消并等待该任务。不要把一个无限 follow 循环当成普通短服务调用租约。直接 get() 返回的原对象仍遵循受信任 Python 调用边界；详见 [受管服务契约](plugin_owned_services.md)。

## 与 DSH 的映射及剩余工作

| DSH 调用面 | 当前 Sunday 近似入口 | 需要 agent 适配 |
| --- | --- | --- |
| session.create | sessions.create | 仅新 thread 身份与标题；workspace、preset、复用策略未覆盖 |
| session.prompt | sessions.prompt | 对象参数转关键字参数；content 仅文本；request_id 与回执格式不同 |
| session.updateQueue | sessions.update_queue | 字段命名及编辑/删除动作 |
| session.cancel | sessions.cancel | 精确轮次目标、异步收尾及保留队列 |
| session.state / wait | sessions.state / wait | 状态字段与停稳条件，不能把 idle 当成功 |
| session.events / follow | sessions.events / follow | Sunday 事件词汇、游标、跟随无初始快照与瞬态 chunk |

尚未提供：模型目录/选择、附件、会话列表/搜索、fork、完整历史投影、冷 Agent 激活/恢复工厂、Agent.inject、结构化 content、Remote 编解码和 UI slots。保持原 `live_turn_service` 供已有频道插件使用，但移植新插件应先读本契约，不能直接调用内核 operation_catalog 的 turn.start 绕过 live 接收。

本服务为受信任 Python 宿主接口，沿用原有会话可见性、成员输入准备和权限快照路径，不新增对外授权。完整 DSH 运行与权限语义仍需在后续阶段逐项适配。迁移脚本只提供 agent-required 的建议映射，不执行盲目替换。

## 验收

先编写本批测试并确认缺失实现时失败，再实现。`core/tests/test_plugin_session_control.py` 的 **31 项测试通过**，使用实际 SQLite、桌面 live 处理器、队列派发和应用启动流程；模型运行用有限的测试处理器代替，不调用外部模型。覆盖并发/持久去重、暂停/引导/排队、创建竞争、空白实体保护、取消和历史边界。未使用 Computer Use。

合并同一需求此前新增的服务注册与迁移测试后，验收结果见 [实施进度](dsh_compatibility.md)。没有以此宣称 DSH JS/TS 原样运行兼容。
