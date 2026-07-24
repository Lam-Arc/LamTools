# LamImager 心智模型

> 状态：✅ 有效 | 来源：mental-model.md, ROADMAP.md
>
> 这是 LamTools 全家桶的认知架构设计，最初在 LamImager 中设计，后成为 LamTools 生态的核心模型。

## 核心系统

| 符号 | 全称 | 职责 | 变不变 |
|------|------|------|------|
| PER | Persona | 人格底色——他是谁、怎么说话、底线 | 永远不变 |
| CON | Context | 上下文管理 + 记忆保存 | 实时更新 |
| PLAN | Plan | 执行计划 | CON + PER → LLM 生成 |
| Skill | — | 外部导入的人设外指令文件 | 用户提供 |

> 已精简：去掉了独立的 Mentation 层——PER 锁住人格基调，CON 提供情境信号，LLM 自行调节。

## 运转逻辑

```
PER (恒定) ──┐
              ├──→ 指导 LLM 输出风格
CON (实时) ──┘
  ▲              │
  │              ▼
  │           LLM ──→ PLAN ──→ 驱动工作
  │                          │
  └──── 状态更新 ──────────── CON
```

关键原则：
- **PER 是滤网，CON 是输入**——PER 锁死输出边界，CON 告诉 LLM 当前发生什么
- **PLAN 单向生成**——从 PER + CON 推导，不循环依赖
- **Skill 是外部文件**——进入 CON 作为信号源，经 PER 过滤后生效

## CON 分层（五层）

| 层 | 存什么 | 进 prompt | 膨胀 |
|---|---|---|---|
| LLM Messages | 对话历史 | 是（固定窗口） | 自然膨胀→裁剪 |
| Hot CON | 标签匹配选出的偏好/参数/PLAN骨架 | 是（System Prompt） | 不膨胀 |
| Active State | 活跃任务、等待反馈 | 否（被问时查询） | 不膨胀 |
| Cold CON | 结构化索引（档案柜目录） | 否 | 膨胀但只查询 |
| Log | 完整原始记录 | 否（只写不读） | 膨胀 |

### Cold CON 六项索引

1. 用户档案（偏好维度 + 权重）
2. 对话摘要（hash + 标题 + 总结 + 标签）
3. 产出索引（图片/代码 + 反馈 + 标签）
4. 偏好溯源（偏好 → 来源）
5. PLAN 库（历史骨架 + 评分）
6. 成员动态（其他成员状态摘要）

## Prompt 组装线

```
PER ───────────┐
Skill ─────────┤
Hot CON(偏好) ─┼──→ System Prompt
Hot CON(参数) ─┤
Hot CON(PLAN) ─┘
```

组装顺序不可换：**PER → Skill → Hot CON**

## 成员分工

| 角色 | owns | 职责 |
|---|---|---|
| CON | memory | 档案系统 |
| MEM | retrieval/write | 取档和归档机制 |
| Butler | maintenance | 档案馆秩序 |
| Sage | judgment | 档案内容真伪与可复用性 |

## 三种记忆层级

1. **Event Memory**——发生了什么（CON/Log 记录）
2. **Experience Memory**——为什么成功/失败（CON + 自评 + 反馈）
3. **Knowledge Memory**——规律是否可靠（Sage 评估）

## 进化闭环

```
经验 → 评估 → 升级 → 预防/复用 → 新表现
```

## 关联

- 架构落地 → [[LamImager 架构设计]]
- 开发路线 → [[LamImager 开发路线图]]
- 生态设计 → [[LamTools 生态设计]]
- 成员架构 → [[LamTools 成员架构设计]]
