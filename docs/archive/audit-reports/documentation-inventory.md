# Documentation Inventory

日期：2026-06-29

## 保留

| 文档 | 理由 |
|------|------|
| `AGENTS.md` | 根维护规则，保留最小入口、边界和文档索引。 |
| `README.md` | monorepo 对外概览和开发入口。 |
| `docs/monorepo-migration.md` | 迁移历史和 subtree 决策依据。 |
| `docs/cli-opencode-alignment.md` | CLI 形态对齐记录，约束 `[member] run` 和未来 `lam run` 方向。 |
| `docs/cli-guide.md` | 当前源码口径的 CLI 使用指南，区分 Core 维护命令与 Writer/Artist 成员命令。 |
| `docs/gui-guide.md` | 当前源码口径的 GUI 使用指南，标明稳定入口和未稳定暴露的能力。 |
| `docs/agent-code-inventory-2026-06-29.md` | Agent 代码功能底图，按 LLM 前/中/后/其他映射代码功能区。 |
| `docs/core-simplification-review-2026-06-29.md` | Core/Member 复用与精简审查，记录 LLM、prompt、tool、event、state 的收敛路线。 |
| `docs/cli-gui-entry-audit-2026-06-29.md` | CLI/GUI 功能入口事实审查，记录外部入口、内部接口和当前缺口。 |
| `docs/cli-gui-entry-optimization-plan-2026-06-29.md` | CLI/GUI 入口优化方案，规划根命令、成员命令、GUI 信息架构和操作目录。 |
| `docs/decomplexity-interface-review-2026-06-29.md` | 从入口 Interface 反推深模块的去复杂化方案，作为下一步删减和收敛依据。 |
| `docs/decomplexity-multi-angle-review-2026-06-29.md` | 多角度去复杂化复核，从状态事实源、事件协议、工具权限、prompt、配置、Kernel、UI、测试产物八个角度给出减法路线。 |
| `core/README.md` | Core SDK 当前范围和模块索引。 |
| `core/docs/core-loop-kernel-design.md` | Core 主循环骨架设计依据。 |
| `core/docs/core-sdk-full-extraction-plan.md` | Core 抽取总纲，已精简掉过期自审和重复段落。 |
| `core/docs/new-member-core-onboarding.md` | 新成员接入 Core 的最小指引。 |
| `core/docs/plans/2026-06-04-final-lamtools-shape-audit.md` | 最终形态审计记录，保留在 plans 下作为历史证据。 |
| `members/writer/AGENTS.md` | Writer 产品级规则。 |
| `members/writer/docs/PLAN.md` | Writer 当前执行计划入口。 |
| `members/writer/docs/ROADMAP.md` | Writer 技术路线。 |
| `members/writer/docs/2026-05-20-writer-architecture.md` | Writer 架构说明。 |
| `members/writer/docs/novel-writing-design.md` | Writer 小说能力设计。 |
| `members/writer/docs/mental-model.md` | Writer 心智模型参考。 |
| `members/writer/docs/lamtools-ecosystem.md` | Writer 侧生态语义参考。 |
| `members/artist/README.md` | Artist 产品入口说明。 |
| `members/artist/docs/ROADMAP.md` | Artist 技术路线。 |
| `members/artist/docs/design-language.md` | Artist 视觉和品牌设计语言。 |
| `members/artist/docs/mental-model.md` | Artist 心智模型参考。 |
| `members/artist/docs/lamtools-ecosystem.md` | Artist 侧生态语义参考。 |
| `members/artist/docs/competitive-research.md` | 产品竞品研究，仍可作为方向参考。 |
| `members/artist/docs/butler-per-v1.md` | Butler 人格参考。 |
| `members/artist/docs/learning-report.md` | 历史学习报告，保留但不作为当前架构真相。 |

## 删除

| 文档 | 理由 |
|------|------|
| `docs/final-lamtools-shape-completion.md` | 一次性验收记录；当前证据由迁移记录和 plans 下审计文档承接。 |
| `core/docs/core-sdk-extraction-audit.md` | 早期抽取审计，已被 Core 总纲和 kernel 设计覆盖。 |
| `core/docs/core-sdk-review.md` | 旧 review 记录，问题已被后续计划和实现吸收。 |
| `members/writer/ENV_CAPABILITY.md` | 旧环境快照，Python 版本等信息已过期，容易误导。 |
| `members/writer/docs/coder-architecture.md` | Coder 旧命名文档，当前成员是 Writer，已由 writer 架构文档承接。 |
| `members/writer/docs/coder-per-v1.md` | Coder 旧命名人格文档，当前 Writer 文档承接。 |
| `members/artist/docs/coder-architecture.md` | Artist 内的 Coder 旧副本，跨成员语义错误。 |
| `members/artist/docs/coder-per-v1.md` | Artist 内的 Coder 旧副本，跨成员语义错误。 |
| `members/writer/docs/writer-architecture.md` | 未跟踪的批量改名产物，存在 “Writer → Writer” 等误导语义，未保留。 |
| `members/writer/docs/writer-per-v1.md` | 未跟踪的批量改名产物，内容被当前 Writer 规则和架构文档覆盖，未保留。 |
| `members/artist/docs/writer-architecture.md` | 未跟踪副本，位于 Artist 下但内容是 Writer，路径语义错误，未保留。 |
| `members/artist/docs/writer-per-v1.md` | 未跟踪副本，位于 Artist 下但内容是 Writer，路径语义错误，未保留。 |

## 仍需人工判断

无。当前保留文档都已有明确用途；后续若要恢复人格/架构长文，应从 Writer 当前实现重新整理，而不是恢复 Coder 旧副本。

## 规则

- 根文档只写稳定入口和边界，不承载过期计划细节。
- `docs/` 放 monorepo 级事实；组件内部 `docs/` 放产品事实。
- 旧仓库路径只允许作为迁移历史出现，不作为日常工作入口。
- 当前成员 CLI 是 `writer run ...` / `artist run ...`；`lamtools` 根命令与操作目录仍是优化方案，不是已完成入口。
