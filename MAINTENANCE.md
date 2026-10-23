# 维护标记

- Member 产品（Writer / Sage / Imager）已于 2026-08 归档至 `archive/members/`，不再维护。所有活跃开发在 `core/` 内进行。
- 系统提示词不变量：自上一次上下文压缩起，系统提示词中的信息块冻结不变；内容变化只追加一条 `changed`（变化后的内容）或 `deleted`（旧副本失效）的系统信息到请求尾部，没有回退状态，也不改写前面的任何内容（包括 AGENTS.md、MEMORY.md、技能索引等）。运行时的计划、PID、验证状态同样只追加变化字段。工具数组（tools）暂不冻结。详细设计见 `docs/movable-system-context.md`。
