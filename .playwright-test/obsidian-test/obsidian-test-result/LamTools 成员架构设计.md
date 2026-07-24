# LamTools 成员架构设计

> 状态：✅ 有效 | 来源：coder-architecture.md, 2026-05-20-writer-architecture.md, 2026-05-21-mate-architecture.md, 2026-05-21-sage-architecture.md, 2026-05-22-butler-detailed-design.md
>
> 各成员的技术架构设计。这些是 P4 Core SDK 抽取后的目标架构。

## 架构选型原则

**域决定架构，不是架构偏好决定域。**

| 成员 | 执行引擎 | 原因 |
|---|---|---|
| Writer | runtime loop（while(true) + 工具） | LLM 能读自己的产出，策略错代价低 |
| Artist | runtime loop + 创作阶段 | 创作过程反复试、评审、修改 |
| Sage | graph/workflow + 验证 | 要求可追溯、可审核 |
| Butler | graph/workflow + 权限 | 要求可控、可审计、可重试 |
| Mate | state machine + small loop | 不需要复杂图，也不该无限工程循环 |

## LamCoder/Writer 架构

### 执行引擎：LoopEngine

```python
while True:
    response = await llm.chat(messages, tools=tools)
    if response.has_tool_calls:
        for call in response.tool_calls:
            result = await execute_tool(call)
            messages.append(tool_result(call, result))
    else:
        return ExecutionResult(content=response.content)
```

### 三个规划工具

| 工具 | 来源 | 职责 |
|---|---|---|
| `todowrite` | OpenCode | 平面任务追踪，一次只一个 in_progress |
| `task` | OpenCode | 子代理并行，独立 sub-session |
| `plan mode` | OpenCode | 5 阶段结构化规划：explore→design→review→write→exit |

### bash 安全模型

```
Layer 1: 白名单（git/ls/cat/py/node/npm/pytest...）— 免审批
Layer 2: 灰名单（rm/mv/cp/curl/docker...）— 需审批
Layer 3: 黑名单（format/rm -rf //sudo...）— 硬拦截
```

### Writer 进化路径

Coder → Writer 不改引擎，只扩展工具集（+文本工具）和 PER（+语气维度）。

## LamButler 架构

### 十二条独立职能

详见 [[LamTools 生态设计]] 中的 Butler 职能表。

### 评价与干预机制

三路径干预：
1. **节点触发**（计划内置，主动）——步骤级/阶段级/产物级验收
2. **需求触发**（异常响应，被动）——方向偏离/依赖断裂/意图误解
3. **召唤触发**（用户主动）——无需判定条件

评价三档：通过 / 需修改 / 推翻

## LamSage 架构

- 持续搜集 → 鉴别 → 整理 → 入库
- 入库前多源交叉验证 + 置信度标记
- 主动轮询——定期扫描前沿信息源
- 好奇心——看见相邻知识空白主动去填（收敛的，与 Creator 的发散正交互补）
- 权威性底线：假消息会污染全链

## LamMate 架构

- 初始 PER 为空——随 CON 积累，LLM 从 CON 反向推导出 PER
- 一旦 PER 生成，锁定后续行为范围
- 成员活动反向同步——知道其他成员经历了什么
- 记忆载体——用户在其他成员的经历不该在回到 Mate 时清零

## 成员协作协议

> 来自未命名 1.md 的草案思考

成员间协作不应做成普通 tool，而应是 **Runtime 级协作协议**：

```
tool：我需要一个动作
agent：我需要一个专业判断
member：我需要另一个角色共同承担任务
```

建议两个接口：
- `call_agent(name, task, mode, context)` — 调用当前成员内部能力
- `call_member(name, task, mode, context, contract)` — 调用其他成员 Runtime

## 关联

- 生态设计 → [[LamTools 生态设计]]
- 人格设计 → [[LamTools 成员人格设计]]
- 心智模型 → [[LamImager 心智模型]]
- 开发路线 → [[LamImager 开发路线图]]
- 碎片笔记 → [[LamImager 碎片笔记]]
