# 插件手动压缩会话历史

user:“宿主能力补齐和接口完善与文档更新”+(复用真实桌面压缩路径，明确结果、取消、修订冲突及生命周期边界)。

受管桌面 Python 插件在 start/on_load 中取得 `context.compaction`，异步调用 `compact_now(session_id, *, expected_revision)`。宿主由桌面会话服务安装为 `compaction_control`；旧 agent preset 的 `compaction` 服务保持原用途。缺少桌面宿主时取得接口抛 LookupError，没有启动作用域时抛 ServiceError。

```python
from lamtools_core.plugin_system import SESSIONS, CompactionError

async def start(context):
    # 实际插件应把操作放在其业务入口；这里演示如何读取修订号和发起调用。
    sessions = context.bind_service(SESSIONS)
    api = context.compaction
    state = await sessions.call("state", "existing-session-id")
    try:
        result = await api.compact_now(state.session_id, expected_revision=state.last_event_seq)
    except CompactionError as error:
        # 不自动重试；may_have_changed=True 时先核对持久事件与运行历史。
        print(error.code, error.may_have_changed)
    else:
        print(result.status)
```

接口固定取得视图时的工作目录与插件启动代。session_id 是最多 256 字符的非空字符串，首尾空白会去除；expected_revision 必须是非负整数，bool、字符串、小数和 None 均拒绝。修订号来自 SESSIONS.state 的 last_event_seq；它是桌面事件流修订号，不是运行历史的内容版本。

## 执行与结果

只允许已知且 idle/completed 的会话。正在运行、暂停、等待授权、失败或取消状态保守拒绝，先用现有会话流程处理。接口沿用 SESSIONS 当前桌面宿主的会话访问范围，没有新增按插件划分的会话授权；插件应明确选择目标，不把上下文工作目录当作会话归属凭据。既有进程后端目前不会自动获得这个 Python API 的远程桥接。

先读取现有会话，避免创建未知目标；检查修订号并交给同一 `command.execute compact` 桌面路径再次检查修订号、认领运行、发布控制事件和调用实际压缩提供方。手动压缩期间，同宿主的普通回合和另一压缩不能抢占运行认领。原始历史保留，摘要及有效历史过滤沿用现有运行存储，不新建压缩状态表。

调用完成返回公开 SDK 的不可变 `CompactionResult`：

| 字段 | 含义 |
| --- | --- |
| session_id | 目标会话 ID |
| status | compacted / not_needed / cancelled |
| summary | 已压缩时的摘要文本；其他结果通常为空 |
| reason | 提供方返回的可选原因，非稳定错误码 |
| before_tokens / after_tokens | 提供方返回的估算值；未提供时为 None |
| compacted_messages / retained_messages | 提供方返回的消息数；未提供时为 None |

只有 compacted 表示提供方确认压缩；它必须携带非空摘要与非负整数计数。not_needed 不是“已经做过”，后续仍可再次请求；同一目标没有请求 ID 去重。cancelled 不代表成功，也不代表内容已回滚。未知状态、跨会话结果、缺失或错误类型的数据会作为 invalid-response 报错，不能当作成功。

提供方缺失、摘要失败或持久化故障不伪造成功。`CompactionError` 有 code、session_id、may_have_changed；后者表示本次压缩可能已经产生控制记录或修改运行状态，并非压缩成功标记。它为 false 也不保证其他并发操作没有修改会话。进入执行后遇到一般错误保守设为 true，不能依靠捕获异常盲目重试。code 包括 `compaction/invalid-session`、`invalid-revision`、`not-found`、`busy`、`conflict`、`closed`、`host-changed`、`invalid-response`、`operation-failed`（均加 compaction/ 前缀）。消息仅供诊断，不按文本判断。

## 取消与停用

调用者取消会传播 asyncio.CancelledError，即使桌面内部已将取消转为持久 cancelled 结果；桌面取消目标运行时，调用者收到 status=cancelled。取消不是事务回滚，已提交摘要、事件或底层提供方已做的更改不会由门面撤回。底层提供方须遵守取消协议；本门面不设置独立执行截止时间。

每次调用登记启动代租约。停用先拒绝新调用并等待已接收调用结束，沿用既有生命周期的等待/重试行为；不会强制取消已接收的压缩。旧视图在停用或重启后不可继续使用。应用关闭后新请求被拒绝，正在执行的运行由既有桌面关闭流程管理。

压缩期间的新消息可以通过 SESSIONS 排队并持久保存。本接口不保证压缩结束时立即唤醒该队列，也不清空它；这与 DSH 的完整 maintenance/FIFO 唤醒协议存在差异。not_needed 仍可能产生桌面控制事件，因此不是无写入操作。

## 与 DSH 的差异

依据固定版本的[官方手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/compaction/compaction/README.md)及[服务源码](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/compaction/compaction/src/index.ts)。compactNow 只能近似移植为此接口：agent/signal/sourceCommandId 需人工改写，返回值和错误也不同。

未开放 compactIfNeeded、compactRegion、tokenMeter、summary-error waterfall、tool pairing 边界工具或 DSH checkpoint/source 标记。Sunday 使用进程内运行注册表和自身持久记录，不提供 DSH 的 compaction/start/end 持久锁、崩溃孤锁恢复或跨进程互斥保证。桌面事件与运行历史属于现有两条持久化路径，本门面未把它们改成跨存储原子事务。自动策略仍由既有压缩控制器负责，插件不能用此接口注册或替换压缩引擎。

迁移报告新增 compactionMethods，仅 compactNow 提供 suggestedContract，其余保留 agent-required 待办。验收覆盖真实桌面命令、实际压缩与数据库重开、排他、修订冲突、取消和启动代撤回；不代表 DSH 运行兼容。测试：`core/tests/test_plugin_compaction_access.py` 与迁移测试。
