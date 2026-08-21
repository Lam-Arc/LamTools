# LamTools Audit Evidence

Baseline audited: `v0.2.6` / commit `dd54b7fdd57f4eb0926f1dd3a94fbf2c2bb0fd8a`.

This file records the evidence boundary for the technical paper. It is deliberately
more conservative than the product README: design documents and roadmap text are
not treated as proof of an implemented capability.

## Architecture audit

The active product is the `core/` tree. It contains a Python Core Loop Kernel,
LLM/provider adapters, a toolbox with approval policies, session and event
persistence, checkpoints, sub-agent execution, HTTP/WebSocket operations, a Vue
workbench, and a Tauri/PyInstaller desktop shell. `archive/` and the historical
member products are not part of the current system claim.

The runtime path relevant to this paper is:

```text
UI / CLI / HTTP operation
        |
        v
Core agent + Core Loop Kernel
        |
        +--> model/provider adapter
        +--> toolbox and approval gate
        +--> sub-agent runner
        |       +--> named child session
        |       +--> optional model override
        |       +--> capability-aware attachment conversion
        |       +--> child event forwarding
        |
        +--> SQLite-backed state, events, checkpoints, and Arrange jobs
```

The `plugins/lamtools-rag` package is a separate plugin. Its current implemented
surface is deterministic document indexing/search, FTS5/BM25 fallback, optional
sqlite-vec support, document reading, citation validation, and plugin/operation
registration. Some session-search paths exist in code but are not treated as a
fully validated paper contribution until their stale integration check is aligned.

## Contribution evidence matrix

| Candidate contribution | Status | Code evidence | Test/runtime evidence | Paper suitability |
|---|---|---|---|---|
| Local-first modular agent runtime | IMPLEMENTED | `core/src/lamtools_core`, SQLite state, provider/tool/plugin layers, Tauri shell | Core suite; release workflow includes backend and installer smoke checks | Good system context; avoid calling the composition novel |
| Capability-aware sub-agent delegation | IMPLEMENTED | `tool/sub_agent_runner.py`, `agent.py`, attachment capability splitting, model-id resolution | `test_core_sub_agent_runner.py`: model override, named sessions, attachment forwarding, text-model deferral, display-name resolution; refreshed targeted run: 63 passed, 1 skipped | Best primary mechanism story |
| Durable child sessions and parent/child event projection | IMPLEMENTED | `sub_session`, `SubAgentEventForwardingSink`, runtime state stores, checkpoint coordination | Named-session reuse, cancellation persistence, approval continuation, parent timeline tests | Strong supporting mechanism |
| Checkpoint graph, rollback, and fork | IMPLEMENTED | runtime checkpoint stores and graph operations | checkpoint graph/rollback tests passed in targeted run | Good persistence story, but secondary unless expanded |
| Arrange persistent task scheduling and recovery | IMPLEMENTED | `runtime/arrange.py`, app startup recovery, lease/occurrence handling | Arrange runtime tests cover once, interval, event, pause, cancel, lease reclaim, and recovery | Supporting evidence; not main story yet |
| RAG document retrieval | IMPLEMENTED | `plugins/lamtools-rag/rag_engine`, plugin tools and operations | Existing 14-question retrieval reports | Optional second case study; citation-gate behavior is outside this report's evidence |
| RAG session-history retrieval | PARTIAL | Handler and operation exist; session indexer exists | Existing integration script still expects an older P2 stub and fails one stale assertion | Do not claim as fully validated |
| VLM format router, complete table extraction, large-scale contract workflow | PLANNED/PARTIAL | Described in `docs/rag-plugin-design.md`; not all corresponding modules are present | No complete end-to-end evidence at this baseline | Exclude from current claims |
| Archived Writer/Sage/Imager functionality | ARCHIVED | `archive/` and historical documents | Historical E2E documents are negative or stale evidence | Exclude |

## Related work map

| Area | Representative source | Boundary for LamTools |
|---|---|---|
| Multi-agent frameworks | AutoGen and AgentScope provide general multi-agent abstractions and platform support | LamTools is narrower: a runtime-level child-session tool with explicit capability/model/attachment handling, not a general conversation programming framework |
| Heterogeneous model selection and cost routing | FrugalGPT studies cascades; RouteLLM learns routers from preference data | LamTools does not claim to learn an optimal router; it provides an explicit runtime delegation path and measures engineering trade-offs |
| Persistent agents and memory | MemGPT studies virtual context management and interrupts | LamTools focuses on durable runtime state, checkpoints, child sessions, and recovery rather than a new memory algorithm |
| Durable execution/checkpointing | LangGraph documents thread checkpoints, pending writes, and SQLite/Postgres savers | LamTools has its own SQLite-backed checkpoint graph and approval/rollback integration; comparative novelty is not claimed |
| Tool/data integration and security | MCP standardizes prompts, resources, and tools; AgentDojo evaluates tool use under prompt injection | LamTools includes MCP integration inside a local approval-aware toolbox, while retaining native tools and plugin-scoped visibility; it is not a security proof |
| Local-first software | Kleppmann et al. describe local ownership, availability, privacy and user control | LamTools applies the local-first framing to an agent desktop runtime; it is an engineering choice, not a new local-first protocol |

## Minimal evaluation plan

### Phase A: deterministic runtime-behavior evaluation

Use a fake deterministic LLM client and temporary SQLite workspaces, so the test
does not depend on provider availability or API prices. Run a small matrix of
text-only and multimodal attachment cases with and without a child model override.
Record:

- route/capability correctness;
- whether supported content becomes a model content block;
- whether unsupported content is deferred rather than silently dropped;
- canonical model-id propagation;
- named child-session history reuse;
- tool allow-list and `consider`/`execute` mode behavior;
- approval continuation and cancellation persistence;
- parent event projection and final-result status.

Each case should retain the prompt, model config, expected route, observed route,
event log, result, software version, tag, and commit SHA. This evaluates runtime
behavior, not model intelligence.

### Phase B: retrieval case study

The repository already contains a 14-question golden set and reports under
`e2e/rag-eval/reports/`. The observed stored reports are:

| Mode | Any-gold Recall@1 | Any-gold Recall@5 | Any-gold Recall@10 | First-any-gold MRR | Warm-query p95 |
|---|---:|---:|---:|---:|---:|
| BM25-only | 0.786 | 0.857 | 0.857 | 0.821 | 1.75 ms |
| Local embedding + hybrid retrieval | 0.857 | 1.000 | 1.000 | 0.917 | 6.67 ms |

These numbers are derived evidence, not a universal benchmark. The paper-facing
derivation is stored in `docs/paper/evidence/retrieval-derived-v0.2.6.json` and
is generated by `docs/paper/derive_retrieval_metrics.py` without rewriting the
raw reports. Any-gold Recall@k deduplicates returned document IDs; a multi-document
question counts as a hit when any gold document appears, so complete-set recall is
not measured. Warm-query p95 uses inclusive linear interpolation over the 14
stored per-question values. The honest interpretation is higher first-hit coverage
at a measurable local-embedding latency cost. The compared files are
`retrieval-none-20260815-095234.json` and
`retrieval-local-20260815-101253.json`, both present in `v0.2.6`.
The current working-tree revision of `e2e/rag-eval/run_retrieval_eval.py` only
corrects analysis-time document de-duplication and inclusive p95 derivation; it
is paper-preparation code and is not claimed to be part of the frozen `v0.2.6`
software tag.

### Phase C: release-bound verification

After any paper-facing bug fix, rerun the selected matrix on one frozen commit.
Do not combine pre-fix and post-fix observations. The final manuscript must state
the exact version, tag, commit SHA, and evaluation date.

### Phase D: optional provider smoke test

The paper includes a separate, non-benchmark connectivity check for the OpenCode
Go OpenAI-compatible endpoint. It targets `deepseek-v4-flash` and `mimo-v2.5`
through `/chat/completions` with one fixed prompt, temperature 0, and a small
output cap. The prepared script records only model, HTTP status, response shape,
latency and provider-reported usage. It does not retain generated text or API
credentials. This check is not part of the deterministic paper evidence until a
local environment variable is supplied and both requests complete successfully.

## Known evidence gaps

- No provider-backed model-quality comparison has been run at this baseline.
- The RAG integration script has stale expectations and one assertion bug; this
  is repository hygiene to fix before treating it as a clean gate.
- The retrieval reports do not contain a complete machine-environment fingerprint;
  retain the values as version-bound case-study evidence and document this limit.
- A correctly configured full Core rerun collected 1,484 tests and recorded
  `1481 passed, 2 skipped, 1 failed, 3 warnings` in about five minutes. The one
  failure was the timing-sensitive parallel-tool threshold
  (`elapsed < 0.09 s`); the same test passed when isolated in a targeted rerun.
  This is reported as an unresolved test-environment flake, not silently
  counted as a pass. The run required `PYTHONPATH=core/src` and
  `LAMTOOLS_COMMAND_SHELL=pwsh`; without those selections, the machine's Git
  Bash cannot resolve the package or Windows Python command. This is an
  environment-selection issue, not a missing Python installation.
- No external user study or large benchmark exists.
- No `CITATION.cff` existed before this audit; the initial file added alongside
  this evidence record is a preparation artifact, not a published citation.
