# LamWriter — AI Engineering & Writing Companion

> Current architecture: CoreLoopKernel + WriterKit + Slot

- Architecture: CoreLoopKernel + WriterKit → WriterTurn → WriterAction → WriterPart events → MEM writeback
- The persona exists to accomplish practical tasks.
- Entry: After P4 Core SDK extraction (Phase 6 in PLAN.md)

## Documentation Index

| Topic | File |
|-------|------|
| Complete Writer architecture | `docs/2026-05-20-writer-architecture.md` |
| ArchitectureAgent graph-node roadmap | `docs/architecture-agent-graph-roadmap.md` |
| Writer PER | `docs/writer-per-v1.md` |
| PER/CON/MEM mental model | `docs/mental-model.md` |
| LamTools ecosystem | `docs/lamtools-ecosystem.md` |
| P3/P4 roadmap | `docs/ROADMAP.md` |
| Master plan | `docs/PLAN.md` |

## Key Architecture

```
CoreLoopKernel (shared loop) + WriterKit (Writer adapter)
  → WriterSessionState (work_root, branch, phase, mode, todos)
  → PER + CON/MEM → LLM proposes WriterTurn
  → validate actions → execute with permission check → WriterPart events
  → self-review → memory writeback → state save
```

- **Part-based messages**: ToolPart state machine pending→running→completed/error.
- **Permission**: 3-tier (auto-allow / ask-user / hard-block). File operations are bounded to work_root.
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

## Development Commands

```bash
cd backend && py -3.14 -m uvicorn app.main:app --reload --port 6173
cd frontend && npm run dev
```

## Rules

- No emoji; use Lucide SVG only. Use a black/white/gray UI.
- LamTwo does NOT influence Writer runtime. Writer is shaped by its own PER/CON/history.
- Keep the Writer persona minimal regardless of task type.
- Follow existing project patterns; never impose personal preferences.
- Run tests after every change that could break something.
- **Do not use any mock-based tests** (including but not limited to `unittest.mock`, `pytest-mock`, or Monkeypatch) unless the user explicitly requests mocks. All tests must exercise the real implementation.
- **Communicate with the user in English.**
- **When a problem occurs, first inspect the OpenCode and Claude Code source code for solutions. Assess whether they can be used directly or adapted before deciding to implement a solution independently.**
- Git: use `writer/{category}/{slug}` branches and `type: description` commits.
- **Writer and OpenCode use the same GLM5.1 model** (Xunfei astron-code-latest); model capability is not the bottleneck. The gap is in Writer's architecture.
