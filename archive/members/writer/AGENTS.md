# LamWriter — AI Engineering & Writing Companion

> 当前架构：CoreLoopKernel + WriterKit + Slot

- Architecture: CoreLoopKernel + WriterKit → WriterTurn → WriterAction → WriterPart events → MEM writeback
- Persona一切以处理实际任务为目的
- Entry: After P4 Core SDK extraction (Phase 6 in PLAN.md)

## Doc Index

| Topic | File |
|-------|------|
| Writer 完整架构 | `docs/2026-05-20-writer-architecture.md` |
| ArchitectureAgent 图节点路线 | `docs/architecture-agent-graph-roadmap.md` |
| Writer PER | `docs/writer-per-v1.md` |
| PER/CON/MEM 心智模型 | `docs/mental-model.md` |
| LamTools 生态 | `docs/lamtools-ecosystem.md` |
| P3/P4 路线 | `docs/ROADMAP.md` |
| 总控计划 | `docs/PLAN.md` |

## Key Architecture

```
CoreLoopKernel (shared loop) + WriterKit (Writer adapter)
  → WriterSessionState (work_root, branch, phase, mode, todos)
  → PER + CON/MEM → LLM proposes WriterTurn
  → validate actions → execute with permission check → WriterPart events
  → self-review → memory writeback → state save
```

- **Part-based messages**: ToolPart state machine pending→running→completed/error.
- **Permission**: 3-tier (auto-allow / ask-user / hard-block). File ops bounded to work_root.
- **Git**: Per-task branching `writer/{category}/{slug}`, conventional commits.
- **9 interaction modes**: EXECUTE, TEACH, DISCUSS, PROTOTYPE, REVIEW, BRAINSTORM, PAIR, DECISION, COMFORT.
- **Domain-aware Hot CON matching**: different recall for code/prose/email/teaching tasks.
- **Layered window**: Hot/Warm/Cold/Permanent; configurable per task_type.

## Target Directory

```
E:\LamTools\members\writer\
├── backend/app/core/writer/
│   ├── core_kernel_adapter.py  # WriterKit (CoreLoopKernel adapter)
│   ├── schemas.py          # WriterTurn, WriterAction, WriterPart
│   ├── state_store.py      # WriterSessionState
│   ├── turn_parser.py      # LLM output → WriterTurn
│   ├── artifacts.py        # WriterArtifact metadata
│   ├── events.py           # writer_* SSE events
│   ├── permission.py       # 3-tier command permission
│   ├── git.py              # Git operations
│   └── self_review.py      # Structured self-review
├── backend/app/core/mem/adapters/writer.py  # WriterAdapter
├── backend/app/services/writer_service.py
├── backend/tests/
├── frontend/src/views/Writer.vue
├── frontend/src/stores/writer.ts
├── docs/
└── AGENTS.md
```

## Dev Commands

```bash
cd backend && py -3.14 -m uvicorn app.main:app --reload --port 6173
cd frontend && npm run dev
```

## Rules

- No emoji, Lucide SVG only. Black/white/gray UI.
- LamTwo does NOT influence Writer runtime. Writer is shaped by own PER/CON/history.
- Writer persona stays minimal regardless of task type.
- Follow existing project patterns; never impose personal preferences.
- Run tests after every change that could break something.
- **不得使用任何 mock 测试**（包括但不限于 unittest.mock、pytest-mock、Monkeypatch），除非用户明确要求使用 mock。所有测试必须针对真实实现编写。
- **与用户交流时使用中文。**
- **遇到任何问题，先查阅 OpenCode 和 Claude Code 源码寻找解决方案，评估能否直接使用或参考借鉴，再决定自行实现。**
- Git: `writer/{category}/{slug}` branches; `type: description` commits.
- **Writer 和 OpenCode 使用同一个 GLM5.1 模型**（Xunfei astron-code-latest），模型能力不是瓶颈。差距在 Writer 架构层面。
