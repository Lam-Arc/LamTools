# LamWriter Evaluation Framework v1

> 12-dimension, 100-point rubric. Target: >=90 points.
> All criteria grounded in observable artifacts (files, SSE events, token counts, timestamps).

## Scoring Rubric

| # | Dimension | Pts | 0-Point Criteria | 50% Criteria | 100% Criteria | What to Measure | How to Measure |
|---|-----------|-----|-------------------|--------------|---------------|-----------------|----------------|
| 1 | Task Completion | 12 | <50% of requested deliverables exist; core functionality broken | All deliverables exist but >=1 has missing features or broken flows | All deliverables exist, functional, and match spec | File existence + functional correctness per spec item | Checklist: each spec item -> file exists? run_command test passes? |
| 2 | Code Logic Correctness | 10 | Runtime errors in >=3 files; tests fail >50% | Runtime errors in 1-2 files; tests pass >=70% | Zero runtime errors; all tests pass; no obvious logic bugs | Error count from run_command output; test pass rate | Run test suite; count stderr errors; parse test output |
| 3 | Architecture Design | 9 | Flat structure; no separation of concerns; circular deps | Basic layering (src/tests/docs); some separation | Clean module boundaries; clear entry points; no circular deps | Directory structure; import graph; entry point clarity | list_dir for tree; search_content for imports |
| 4 | Maintainability | 8 | No type hints; magic numbers; functions >80 lines; no error handling | Some type hints; functions mostly <50 lines; basic error handling | Consistent type hints; functions <40 lines; proper error handling; DRY | Type annotation coverage; function length; magic number count | search_content for type patterns; run linter |
| 5 | Documentation Clarity | 8 | No README; no inline comments; no API docs | README exists with setup instructions; key functions commented | README with setup/architecture/usage; public APIs documented | README completeness; docstring/comment coverage | Read README; search_content for docstrings |
| 6 | Doc Staleness & Archival | 7 | Docs contradict code (wrong paths, outdated APIs); no CHANGELOG | Docs mostly accurate; CHANGELOG exists but incomplete | All docs match current code; CHANGELOG current; no orphaned docs | Doc-code consistency; orphaned references | search_content for paths in docs -> verify files exist |
| 7 | Frontend Visual Quality | 8 | Broken layout; unstyled elements; no responsive; console errors | Functional layout; basic responsive; minor visual inconsistencies | Polished layout; consistent design system; responsive; accessible | Layout integrity; CSS consistency; responsive breakpoints | Check CSS variables usage; responsive media queries |
| 8 | Backend Performance | 7 | Obvious N+1 queries; no caching; sync blocking in async context | No N+1; basic caching; async where needed | Optimized queries; proper caching; fully async; reasonable cold start | Query patterns; response times; resource usage | search_content for query patterns; measure response times |
| 9 | Token Efficiency | 7 | Total tokens >2x baseline; redundant reads; re-reading same files | Tokens within 1.3-2x baseline; some redundant reads | Tokens within 1.3x baseline; minimal redundant reads | Total input/output tokens; redundant tool calls | Sum tokens from SSE usage events; count duplicate read_file calls |
| 10 | Time Efficiency | 7 | Wall time >3x expected; long idle gaps; unnecessary re-planning | Wall time 1.5-3x expected; minor gaps; occasional re-planning | Wall time within 1.5x expected; tight action sequencing | Wall clock time; inter-action gaps | Timestamps from SSE events; gap analysis |
| 11 | Multi-Turn Autonomy | 9 | Stops after first error; asks user >3 times; doesn't self-verify | Recovers from 1-2 errors; asks <=2 times; self-verifies key changes | Recovers from all errors autonomously; self-verifies all changes | Error recovery count; user clarification requests; self-verification | Parse SSE events for ask_clarification; count run_command after write_file |
| 12 | Error Recovery | 8 | Crashes on error; doom loop (>=3 identical retries); no fallback | Retries with modification after 1-2 failures; breaks doom loop | Adapts strategy on failure; never doom loops; uses git rollback if needed | Retry behavior; strategy changes on failure; doom loop detection | Parse ToolPart state: error -> next action type; count consecutive identical calls |

**Total: 100 points | Target: >=90**

## Weight Rationale

- Task Completion (12): Prime directive -- if the job isn't done, nothing else matters.
- Code Logic (10) + Architecture (9): Code that works but is structured poorly is technical debt.
- Multi-Turn Autonomy (9): Core differentiator of an agent vs. one-shot generator.
- Maintainability (8) + Docs (8) + Frontend (8): Equal weight -- portfolio must be presentable, readable, maintainable.
- Error Recovery (8): Autonomous agents must handle failure.
- Doc Staleness (7) + Backend Perf (7) + Token Efficiency (7) + Time Efficiency (7): Quality refinements.

## Evaluation Task

```
You are LamWriter. Create a complete personal portfolio website project in the work_root directory.

## Requirements

### 1. Frontend (HTML/CSS/JS, no frameworks)
- index.html: Hero section with name/tagline, About section, Projects grid (6 cards), Contact form
- styles.css: CSS custom properties for theming, responsive (mobile/tablet/desktop), dark/light mode toggle, smooth scroll, animations on scroll
- app.js: Theme toggle, form validation (client-side), scroll animations (IntersectionObserver), project data from JSON

### 2. Data
- projects.json: 6 project entries with title, description, tags, link, image placeholder

### 3. Backend API (Python FastAPI)
- api/main.py: GET /api/projects (serve projects.json), POST /api/contact (validate + log)
- api/requirements.txt: fastapi, uvicorn, pydantic
- api/tests/test_api.py: 5+ tests covering both endpoints, validation, error cases

### 4. Documentation
- README.md: Project overview, architecture diagram (ASCII), setup instructions, API reference, deployment notes
- CHANGELOG.md: Initial release entry
- docs/architecture.md: Module responsibilities, data flow, design decisions

### 5. Quality
- All tests must pass (pytest api/tests/)
- No console errors in browser
- CSS validates (no !important hacks)
- Type hints on all Python functions
- Conventional commit messages

### 6. Git
- Initialize git repo
- Create branch writer/feat/portfolio-website
- Commit after each logical step with conventional commit messages
- Final commit: all files, tests passing

Work autonomously. Verify your work. Do not ask for help unless genuinely stuck on a user decision.
```

## Measurement Infrastructure

Per-session metrics (from SSE event stream):
- total_input_tokens: sum of all usage.prompt_tokens
- total_output_tokens: sum of all usage.completion_tokens
- wall_time_ms: last event timestamp - first event timestamp
- tool_call_count: {read_file: N, write_file: N, ...}
- duplicate_reads: count of read_file calls with same path within 5 turns
- error_count: ToolPart state=error count
- clarification_count: ask_clarification action count
- self_verify_count: run_command after write_file within 3 turns
- doom_loop_count: >=3 consecutive identical tool calls
- strategy_change_count: different action type after error vs. same type
- git_rollback_count: git checkout/restore after error
- inter_action_gaps: [ms] between consecutive tool calls

## Caveats

- GLM5.1 function calling reliability: If >20% of tool calls are malformed, discount dimensions 9-12 by 30% (LLM limitation, not Writer architecture limitation).
- Subjective visual scoring: Dimension 7 has inherent subjectivity. Mitigate by checking CSS structure quantitatively.
- Token baseline: Establish by running the same task multiple times and taking the median.
