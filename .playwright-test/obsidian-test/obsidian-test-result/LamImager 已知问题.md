# LamImager 已知问题

> 状态：✅ 有效 | 来源：unfixed-bugs.md
>
> 2026-05-13 审计，共 27 项未修复 Bug。项目已搁置，这些问题大概率不会被修复。

## 分类统计

| 不修原因 | 数量 | 编号 |
|---|---|---|
| 改动风险大于收益 | 2 | B-04, B-09 |
| 无实际影响 | 4 | B-13, B-17, B-23, B-24 |
| 类型重构范围过大 | 4 | B-18, B-19, B-26, B-27 |
| 死代码不影响运行 | 1 | B-28 |
| 代码风格/低优先级 | 16 | B-30~B-45 |

## 关键问题

### B-04: Checkpoint replan 状态处理可能有误
- `decision_node` 返回 `replan` 时，`Command(resume=action)` 可能不支持跳回 `planner`
- 不修原因：可能是 LangGraph 正常工作方式，改动风险高

### B-09: Message.metadata_ 与 Schema metadata 名称不一致
- ORM 属性名 `metadata_`（SQLAlchemy 保留字），Schema 期望 `metadata`
- 不修原因：所有路径都通过 `message_to_response()` 手动映射，运行时不会出错

### B-17: 下载到服务器本地目录功能前端完全不可用
- 后端端点存在，前端无 API 封装
- 实际是功能缺失而非 bug

## 关联

- 架构设计 → [[LamImager 架构设计]]
- E2E 测试 → [[LamImager E2E 测试]]
- 进度日志 → [[LamImager 进度日志]]
