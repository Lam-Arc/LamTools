# 可动系统上下文与运行时便签

这份文档记录两条与缓存直接相关的规则：

1. 系统提示词在一个“压缩周期”内冻结，变化只追加到请求尾部。
2. 运行时的计划、PID、验证状态只追加变化字段，不重发整张便签。

两条规则的目标相同：已经发出的前缀不再改写，让服务端的提示词缓存尽可能多地复用。

## 不变量

- **系统提示词在上下文压缩之前绝不变动。** 会话建立或上一次压缩成功后，第一次请求渲染出的整段系统提示词会被冻结；之后每一步发送的都是这份文本。（模型备注仍是已知例外，见“不在范围内”。）
- **变化只追加。** 任何块的内容变化都作为一条尾部系统消息追加，绝不回写前面的系统提示词。
- **只有两种状态。** 块要么 `changed`（给变化后的内容），要么 `deleted`。没有“回退”状态；内容改回旧值也按 `changed` 处理。
- **严格延续。** 冻结文本随会话状态落库，应用重启后继续使用同一份，不会因为关闭期间修改了 AGENTS.md 就整段重算。
- **压缩时重建。** 上下文压缩成功是唯一允许系统提示词本身更新的时刻；那时用最新内容重新冻结，并把此前的差异全部吸收掉。

## 压缩周期

一个压缩周期从会话第一次构造请求开始，到下一次上下文压缩成功为止。状态保存在：

```text
state.metadata["movable_system_context"]
```

```json
{
  "version": 1,
  "epoch_id": "…",
  "system_prompt": "冻结的整段系统提示词",
  "block_labels": {"project_agents": "AGENTS.md"},
  "reported": {"project_agents": "sha256(上一次已告知模型的内容)"},
  "created_turn_id": "…"
}
```

状态字段名仍为 `epoch_id`，用于兼容已持久化的会话；界面与文档统一称“压缩周期”。

- 第一次请求只做播种，不产生通知。
- 之后每一步重新计算各块内容，按 SHA-256 与 `reported` 比较。
- `reported` 表示“模型已经被通知到的最新内容”，不是冻结基线；同一次变化不会在后续步骤重复通知。
- 系统提示词全文必须持久化。只存摘要无法在重启后还原字节。

## 系统提示词块

| key | 内容 |
|---|---|
| `instructions` | 当前成员的指令（Study 模式为内置 Study 指令） |
| `session_identity` | 项目路径、会话 id、当前模型 |
| `subagent_guidance` | 子代理指南、委派策略、角色分配 |
| `shell` | 当前命令 shell |
| `tool_protocol` | 通用工具协议与完成规则 |
| `completion_rule` | 最终答复要求 |
| `skills_index` | 可用技能索引 |
| `mcp_servers` | 可激活的 MCP 服务器名单 |
| `project_<name>` | AGENTS.md、CLAUDE.md、CONTEXT.md、全局/项目记忆索引等 |
| `image_fidelity` | 图片保真说明 |

块按固定顺序拼成整段文本；拼接结果与引入压缩周期之前逐字节一致。

## 通知格式

一次请求只追加一条，多个块按 key 排序合并：

```text
[System context update]
System message "AGENTS.md" are changed, now:
（变化后的完整内容）

System message "skills index" are deleted; the copy in the leading system prompt no longer applies.
```

- 只写变化后的内容，不重复原文。
- `deleted` 必须明确说明顶部旧副本已失效，否则模型会同时看到两个版本。
- 通知是带 `provider_tail_system` 标记的 system 消息，位于运行时上下文之后、请求最后。
- Kernel 写入持久历史时会把它转成 `provider_tail_system_historical` 副本，下一步起原地不动，成为可复用前缀的一部分；不会每一步搬回尾部。

## 压缩时

压缩输入会排除两类消息：

- `key = "movable_context_notice"` 的系统通知
- `key = "runtime_context_delta"` 的运行时便签

压缩成功后：

1. 用当前所有块的最新内容重新渲染系统提示词，建立新压缩周期（`rebuild_movable_system_context`）。
2. 把当前请求的第一条 system 消息替换成新文本，让压缩后的这次请求就看到最新版本。
3. 补发一张完整的运行时便签，作为新的运行时基线。

旧通知和旧便签不再保留，它们表达的差异已经合并进新系统提示词和完整便签。

## 运行时便签

运行时便签保存的是会话状态，不属于系统提示词：

- 模型能力说明
- 当前模式
- 后台进程（PID → 命令）
- 当前计划（目标、文件、每一步的状态和描述）
- 验证要求、修复提示、证据调用 ID
- 空回复重试指令

状态保存在 `state.metadata["runtime_context_reported"]`。

- 会话第一次构造请求，或压缩后：发一张完整快照。
- 之后每一步只比较字段，只追加变化项，例如：

```text
[Runtime context update]
- Plan step step-2: completed · 写报告
- Process 1234: exited
```

- 更新消息同样是尾部 system 消息；写入历史后转为 historical 副本，原地不动。
- 没有变化时不发消息，也不重复整张便签。

## 图片降级

图片不是系统提示词块，但它的字节变化同样会影响前缀：

- 图片产生后的**第一次**请求仍发送原图，让模型看清细节。
- **第二次**请求起，改为 360p、256 色索引色 PNG：横图最多 640×360，竖图最多 360×640。
- 降级副本由内容哈希缓存，固定参数重编码，同一输入每次生成完全相同的字节。
- 无法解码时原样返回，不丢图、不阻断请求。
- 已经很小且本来就在 360p 框内的 JPEG 保持原样。

降级时机会改写图片所在位置之后的前缀，因此缓存损失从图片位置开始；图片通常在一轮末尾产生，损失约等于最后一轮。

计数口径统一为“模型已经回答过几次”：

- 用户消息、工具消息、审批恢复写入的工具结果都记录这个计数。
- `image_step_allowance` 直接返回记录值；`current_step <= allowance` 时保持原图。
- 下一次请求使用同一个计数，仍为原图；再下一次计数加一，才降级。

压缩不会重置这个额度。压缩只重建系统提示词与摘要；保留的消息按 `history_seq` 映射回原始历史对象，因此持久历史保存原图，请求层每次按计数生成副本。已过窗口的图片在压缩后仍是低清；需要细节时重新读取文件，生成新的消息与计数。

## 不在范围内

- **工具数组不冻结。** MCP 激活、`load_skill` 的 `on_load` 工具仍会改变 tools 数组，下一轮整段前缀失效一次。MCP 使用频率低，暂不处理。
- **模型备注仍在传输层注入。** `cli.py` 的 `_messages_with_model_notes` 会把备注拼到第一条 system 消息末尾；备注中途变化会静默改写冻结前缀。这是当前唯一未封住的系统提示词入口。
- **原生 Anthropic 没有显式缓存断点。** 全仓没有 `cache_control`，Anthropic 不会自动缓存；前缀稳定只是必要条件，还需要单独的缓存标记。
- **路由粘性只覆盖 OpenCode。** 只有 OpenCode 携带 `x-opencode-session`；OpenAI 的 `prompt_cache_key` 和网关侧粘滞尚未使用。

## 代码位置

- `core/src/lamtools_core/prompt/movable.py`：块、压缩周期、比较、通知文本。
- `core/src/lamtools_core/app/base_agent.py`：`_compose_system_prompt`、`_runtime_context_fields`、`_runtime_context_delta`、`rebuild_movable_system_context`、`emit_runtime_context_snapshot`。
- `core/src/lamtools_core/runtime/context_delta.py`：运行时便签的元数据 key 与判定。
- `core/src/lamtools_core/kernel/loop.py`：通知/便签提交、压缩过滤、压缩周期重建、历史副本、保留消息按 `history_seq` 映射回原始对象。
- `core/src/lamtools_core/llm/image_payload.py`：图片降级。
- `core/src/lamtools_core/app/approval_resolution.py`：审批恢复工具结果的图片标记。

## 观测与排查

- 后端日志：`<数据目录>/backend.log`。
- 低命中率诊断：`[cache-diagnostic]`，包含请求形状、首个变化位置、工具签名和路由信息。
- 历史修复：`[kernel:history-repair]`，只在历史确实被修复时出现，记录 session、悬空调用数、孤立结果数和首个修复位置。
- 排查顺序：先看是否有 `[cache-diagnostic]` 指出的块变化；再看是否发生了压缩（新压缩周期）；最后检查工具数组是否变化、历史是否被修复。

## 测试

- `core/tests/test_movable_system_context.py`：冻结、变化通知、删除、重启延续、压缩重建、运行时增量。
- `core/tests/test_image_payload.py`：360p/8bit 输出、确定性、失败开放、计数口径。
- `core/tests/test_kernel.py`：通知提交、历史修复日志、压缩相关行为。
