# E2E 真实任务测试 — Phase 3 观测报告

日期：2026-07-19

## Task 1：Flutter MVP 端到端开发

### Writer ✓ 通过

| 指标 | 结果 |
|------|------|
| 指令 | "阅读 prompt.md，去实现" |
| 输出 | 25 个 Dart 文件，完整 MVP |
| `flutter analyze` | EXIT=0（自修复后） |
| `flutter test` | EXIT=0 |
| 耗时 | ~14 分钟 |
| checklist 使用 | 尝试调用但遇 `files=null` bug，自主放弃后直接写代码 |

**观测要点**：
- 模型理解任务后直接`flutter create`→`pub add`→写完整 25 个文件→`analyze`→`test`，全程自主
- `analyze` 第一次 exit=1，模型读取错误日志，定位 4 个问题，逐个修复
- 修复过程中未被软提示中断——`TOOL_PROGRESS_REQUIRED` 正常工作
- `write_checklist` 遇到工具参数bug（`files=null`），模型诊断后放弃plan直行代码
- CLI 文件流显示正常：`file write_file 1234 chars: import 'dart:convert';...`
- 编辑文件流只显示字符增量 `+N chars`，不重复刷屏

### Core ✗ 未执行

Core 服务器启动连续失败：
- 第1次：`graph_id` 无效参数 — checkpoint ORM 缺字段
- 第2次：`CoreAppDb` 无 `goal_store` 属性 — 合并遗留
- 第3次：`open_core_app_db` 不接受 `member_defaults` 参数 — 合并遗留

## Task 2：项目生命周期 + 版本回退

**未执行**。阻塞：Core 服务不可用，checkpoint 系统依赖 Core 服务器。

## Task 3：Sage 研究任务

**未执行**。阻塞：Sage 服务从未启动，配置未验证。

## 合并后遗症

| # | 问题 | 文件 | 影响 |
|---|------|------|------|
| 1 | `CoreCheckpoint` ORM 缺 `graph_id`、`parent_checkpoint_id`、`edge_kind`、`reason`、`label` | `core_db.py` | Core 服务无法启动 |
| 2 | `CoreAppDb` 缺 `goal_store`、`SqlAlchemyGoalStore` | `core_db.py` | Core 服务无法启动 |
| 3 | `open_core_app_db()` 签名不匹配 | `http_agent_app.py` | Core 服务无法启动 |
| 4 | `spreadsheet.py` 缺失 | 未部署 | import 错误 |

## 结论

Writer 在合并后表现完好——工具、软提示、错误修复、CLI 流显示全部正常。Core 和 Sage 需解决合并冲突后才能继续验证。
