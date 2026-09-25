# LamTools E2E Assets

> **状态（2026-09-25）**：旧的 Writer 冒烟套件已删除。它指向已归档的 Writer 前端
> （`members/writer/frontend`，该路径早已不存在），也不在任何 CI 工作流中运行。
> Core 端到端用例的现行权威是 `core/tests/test_core_live_client_e2e.py`（真实
> WebSocket server；CI 的 backend 作业装 `.[dev,server]` 后会真正执行它）。
> 本目录只保留下面两类仍在使用的资产，Playwright 脚手架（`playwright.config.ts`、
> `package.json`、writer spec）随套件一并移除。

## rag-eval/ — 检索侧 RAG 评测（不调用 LLM）

用固定语料 + 黄金集量化检索质量（recall@k / precision@k / MRR）：

```bash
cd E:\LamTools
py -3.14 e2e/rag-eval/run_retrieval_eval.py --help
```

| 路径 | 内容 |
|---|---|
| `rag-eval/corpus/` | 8 份中文合同/协议语料（保秘、借款、劳务、技术服务、租赁、股权转让、采购、销售） |
| `rag-eval/golden/retrieval_golden.jsonl` | 14 问的黄金集 |
| `rag-eval/reports/` | 历次评测报告（JSON，按 `retrieval-<mode>-<时间戳>.json` 命名） |

## test-apps/ — 端到端任务素材

20 个很小的示例应用（`ai-chat*`、`ai-pipeline`、`quicknotes`、`zero-touch*`、
`stream*`、`verify`、`tiny`…），用作「让 agent 读写/改造一个小项目」的任务素材。
每个目录自带最小文件集，不含依赖安装产物。

## real-task-runs/ — 本地运行产物（已移出版本库）

2026-06 的真实任务运行日志（Writer 时代）。已 `git rm --cached` 并写入
`.gitignore`：文件仍在本机磁盘上，可直接删除以回收约 36 MB；历史上需要时用
`git log --diff-filter=D -- e2e/real-task-runs` 追溯。
