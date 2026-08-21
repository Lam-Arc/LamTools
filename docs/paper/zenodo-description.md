# Copy-ready Zenodo Paper Description

## Description

大语言模型应用正在同时组合异构模型、工具、文件和持久化状态。LamTools 是一个本地优先 Agent 运行时，将其中一条关键路径显式化：父 Agent 可以调用具有稳定名称的子会话，解析可选模型覆盖，根据子模型声明的能力转换附件，并将子会话事件与结果投影回父时间线。运行时限制递归调用和工具可见范围，同时在 SQLite 中保存审批、取消和检查点状态。

本文围绕 LamTools `v0.2.6` 的已实现能力，记录能力感知的子 Agent 委派、持久化子会话、受限工具边界、检查点与恢复机制，并提供一个小型、可审计的检索案例。定向机制测试记录为 63 项通过、1 项跳过；完整 Core 套件记录为 1,481 项通过、2 项跳过和 1 项时间阈值敏感的失败。14 问、8 文档的检索案例显示，本地混合检索将任一黄金文档 Recall@10 从 0.857 提升到 1.000，将首个任一黄金文档 MRR 从 0.821 提升到 0.917，同时使 warm query-time P95 延迟从 1.75 ms 增加到 6.67 ms。

本文是中文主版本与完整英文版本合并的 technical paper / preprint。它不声称提出新的通用路由算法，不声称模型优越性，也未经同行评审。软件对应 LamTools `v0.2.6`，commit `dd54b7fdd57f4eb0926f1dd3a94fbf2c2bb0fd8a`，Software DOI 为 `10.5281/zenodo.22039646`，Paper DOI 为 `10.5281/zenodo.22040870`。

The same record contains the complete English version after the Chinese-primary version.

## Keywords

AI agents; model delegation; multimodal capability; durable execution; local-first software; retrieval evaluation; reproducibility

## Record notes

- Keep the record as one bilingual paper; do not create separate Chinese and English records.
- Add `lamtools-technical-paper-bilingual-v0.2.6.pdf` as the main file.
- Add `lamtools-paper-supplement-v0.2.6.zip` as an optional supplementary file.
- The reserved Paper DOI is `10.5281/zenodo.22040870`; keep this draft record and replace the PDF within it.
