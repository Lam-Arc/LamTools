# LamImager 碎片笔记

> 状态：❓ 内容不确定 | 来源：未命名.md, 未命名 1.md, 未命名 2.md
>
> 三篇未命名文件，内容是开发过程中的随手记录和思考碎片。部分内容已超越 LamImager 范畴，涉及 LamTools 全家桶的架构思考。

## 未命名.md — Writer 测试问题 + 成员运行范式思考

### Writer 真实任务暴露的问题

阻塞级：
1. **完成判定太弱**——旧验证只看 compile/import/pytest，没发现调用了不存在的方法。已修：新增 `python_api_refs`
2. **修复态读循环**——Writer 反复 read_file/recall_session 不改。已修：限制只读轮次后强制 write
3. **修复态只给摘要导致无法编辑**——已修：修复态保留必要文件内容
4. **完成会话无法 CLI 精确召回**——已修：CLI tool 使用后端一致 data_dir
5. **完成态 state 读不回来**——Runtime 保存 `loop_position=idle` 但 schema 不允许。已修

高风险：
6. **任务分支被占用时退回 writer/main**——已修：自动生成 fallback 分支
7. **edit_file 短匹配破坏代码**——未彻底修
8. **复杂任务首次独立开发质量不够稳**——需新版验证器重跑

### 成员运行范式总结 ❓

> ⚠️ 这是作者的架构思考草案，非最终决策

```
Writer  → runtime loop
Artist  → runtime loop + creative stages
Sage    → graph/workflow + verification
Butler  → graph/workflow + permissions
Mate    → state machine + small loop
```

可抽象成同一个底座：Runtime（LoopRuntime / GraphRuntime / StateMachineRuntime）+ Agent + Tool + Action + Memory + DecisionPoint + Checkpoint

### Search Agent 限制
- 默认 DuckDuckGo HTML fallback，稳定性不如本地 SearXNG
- 未做来源可信度分级
- 未接入 DesignAgent 自动 research hook
- 未缓存搜索/抓取结果

## 未命名 1.md — 模型微调任务设计 + 成员协作协议草案

### 三个模型微调任务

| 任务 | 复杂度 | 目标 |
|---|---|---|
| 基于开源模型微调 | 中等 | 能加载、能推理、能回答目标领域 |
| 继续预训练 + 指令微调 | 高 | 领域语料吸收 + SFT |
| 从零预训练 1B/2B | 极高 | tokenizer/架构/数据/训练全链路 |

### 成员协作协议草案 ❓

> ⚠️ 重要的架构思考：成员间协作不应做成普通 tool

```
tool：我需要一个动作
agent：我需要一个专业判断
member：我需要另一个角色共同承担任务
```

建议两个接口：
- `call_agent(name, task, mode, context)` — 内部能力
- `call_member(name, task, mode, context, contract)` — 跨成员协作

协作返回结构化：`{status, summary, result, decision_points, risks, next_actions}`

详见 → [[LamTools 成员架构设计]]

## 未命名 2.md — Complex Task System Prompt

> 这是 `artist.py ct` 复杂任务模式的完整系统提示词源码。

核心规则：
- 用户询问方向/建议/分析时不调用 generate_image
- 用户要求"改/修改/更/简化"等视觉变化时必须选目标图作为 reference
- anchor prompt 越短越好——用最少的词表达核心设定
- 品牌 anchor 写法："X视觉系统：品牌名：...，配色：...。风格：..."
- 角色 anchor 写法："X角色设计稿：发色/服装/装备。风格：..."
- identity_contract 写进 visual_memory，后续验收用
- reference 只能填本轮 visible_artifacts 里已有的图
- 每个 loop 只能调用一次工具

## 关联

- 成员架构 → [[LamTools 成员架构设计]]
- Artist Runtime → [[LamImager Artist Runtime]]
- 生态设计 → [[LamTools 生态设计]]
- 心智模型 → [[LamImager 心智模型]]
