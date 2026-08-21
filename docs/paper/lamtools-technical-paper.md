# LamTools: A Local-First Agent Runtime with Capability-Aware Delegation

**Yulin Zhang**\* and **Yiming Zhang**\*

\*Equal contribution. Author order is retained consistently in the manuscript and release metadata.

## Abstract

Large-language-model applications increasingly combine heterogeneous models, tools, files and durable state. LamTools is a local-first agent runtime that makes one such combination explicit: a parent agent can invoke a named child session, resolve an optional model override, convert attachments according to the child model's declared capability, and project the child's events and result back into the parent timeline. The runtime bounds recursion and tool visibility while preserving approval, cancellation and checkpoint state in SQLite. At the audited `v0.2.6` baseline, the complete Core suite contains 1,484 tests; the latest full rerun recorded 1,481 passed, 2 skipped and one timing-sensitive failure, while the isolated rerun of that case passed. A refreshed targeted mechanism suite recorded 63 passed and 1 skipped. A separate 14-question, 8-document retrieval case study compares BM25-only with local embedding plus hybrid retrieval. The hybrid path increases any-gold document Recall@10 from 0.857 to 1.000 and first-any-gold MRR from 0.821 to 0.917, while warm query-time p95 latency increases from 1.75 to 6.67 ms. We present these findings as version-bound engineering evidence and a reproducibility-oriented system description, not as a new routing algorithm or a claim of model superiority.

**Keywords:** AI agents; model delegation; multimodal capability; durable execution; local-first software; retrieval evaluation; reproducibility

## 1. Introduction

Agent systems are no longer defined only by a model call. A practical runtime must coordinate model turns, tools, files, approvals, interruptions and persistent state while leaving the operator able to inspect and control the task. The difficulty is amplified when configured models do not have identical capabilities. A text-oriented model may be adequate for planning and language reasoning, while a different model is needed to interpret an image or another attachment type. Treating that difference as an implicit provider detail makes the execution path difficult to test and reproduce.

LamTools addresses this problem as a local runtime for desktop and command-line workflows. The active product is the `core/` package, which exposes a shared loop to the Vue workbench, CLI and HTTP/WebSocket clients. Its runtime state, event projections, checkpoints and scheduling records are stored locally in SQLite. Provider calls can still leave the machine when a remote provider is configured; “local-first” describes ownership of orchestration state, not a promise that every model call is local [9].

This paper studies the implemented delegation path rather than treating every product feature as a separate research contribution. The path has four observable stages: the parent requests a child task; the runner resolves the effective model and execution mode; attachment content is split according to the child's declared capability; and the child timeline is returned through the parent event surface. The same runtime also supplies bounded tools, approval continuation and checkpoint-based recovery, which are necessary for the delegation path to be usable in an operator-controlled application.

The contribution is deliberately narrow and evidence-bound. First, we document a runtime composition that joins named child sessions, explicit model selection, capability-aware attachment handling, permission-bounded tools and durable local state. The key design signal is that model capability is treated as a runtime contract: it directly controls attachment conversion and is tested at the boundary where silent multimodal failures would otherwise occur. Second, we provide a behavioral evaluation of the implemented mechanism using deterministic tests rather than an unreported provider benchmark. Delegation is treated as scoped durable execution across the tested runtime components, with child identity, permissions, approval state, event projection and checkpoint scope examined together. Third, we report a small retrieval case study with stored per-question outputs to make a concrete quality/latency trade-off inspectable. Together, these choices turn an otherwise ordinary collection of agent features into an auditable engineering system description. The work does not claim priority over general multi-agent frameworks, learned model routers, memory algorithms or durable graph systems.

## 2. Results

### 2.1. Runtime architecture and the delegation path

The audited runtime has five cooperating layers. The client layer submits turns and renders events. The Core Loop Kernel coordinates model rounds, tool preparation, approval and wait states, retries, terminal convergence and event persistence. The toolbox and plugin layer exposes native, MCP and plugin tools under explicit mode and permission filters. The sub-agent layer creates or resumes a named child session, resolves a model reference, disables recursive `sub_agent` calls and forwards child events. The persistence layer stores threads, events, checkpoints, rollback/fork graph data and Arrange scheduling records.

![Figure 1. LamTools runtime architecture at the audited `v0.2.6` baseline. The solid boundary marks local orchestration state; provider calls may be remote when configured by the operator.](figures/architecture.png)

The delegation tool accepts a task, a stable child-session name, an optional model reference, an optional tool mode and attachment identifiers. A model reference may be a configured model ID or a display name. The runner canonicalizes that reference before capability lookup and downstream metadata construction. This ordering is important: capability decisions must be made against the effective model, not an ambiguous display label.

![Figure 2. Sequence of the implemented delegation path. Capability conversion, child-session persistence and bounded tool execution are explicit runtime steps rather than hidden provider behavior.](figures/delegation-sequence.png)

Table 1 separates observable mechanisms from claims that are not made. This boundary is part of the result: a system paper becomes less reproducible when planned or historical features are silently mixed with the active baseline.

| Runtime surface | Implemented behavior at `v0.2.6` | Evidence used here | Claim boundary |
|---|---|---|---|
| Core loop | Model rounds, tool preparation, approval/wait, retries, terminal state and event persistence | Full Core suite | Runtime behavior, not model-quality superiority |
| Child sessions | Named session creation/reuse, optional model override, child event forwarding | Targeted delegation tests | Explicit delegation primitive, not a learned router |
| Attachment handling | Text remains available; supported multimodal content becomes blocks; unsupported content is deferred | Attachment capability tests | Capability-aware conversion, not universal multimodal support |
| Tool boundary | Child recursion disabled; read/execute modes and allow-lists are enforced | Sub-agent and toolbox tests | Bounded permissions, not a complete security proof |
| Durable state | SQLite threads/events, checkpoints, rollback/fork, cancellation and Arrange recovery | Checkpoint, persistence and scheduling tests | Implemented recovery paths, not a new persistence theory |
| RAG plugin | BM25/FTS5 fallback, optional local vectors and hybrid retrieval | Stored 14-question retrieval reports | Small case study, not a general benchmark |

### 2.2. Capability-aware attachment handling

For each attachment, the runtime obtains the stored attachment record and reads the configured capability of the effective child model. Supported content is emitted as a model content block. Text attachments remain available as text. Unsupported multimodal content is deferred according to the attachment service contract rather than silently presented as if the child model could interpret it. This behavior moves the capability boundary into a testable runtime component instead of scattering provider-specific checks across the UI.

The child kernel uses the same core loop as the parent, but recursive `sub_agent` calls are disabled. The caller may select a read-oriented mode, full execution mode or an explicit allowed-tool set. If a tool requires approval, the child can enter a waiting state; an approval continuation appends the tool result to durable child history before resuming. Parent identifiers on child events allow the UI to display delegated work without conflating the child timeline with the parent turn.

This design has a modest interpretation. It is an integration mechanism that makes heterogeneous model use explicit and observable. It does not learn which model is optimal, estimate a universal capability score, or establish that delegation improves answer quality for arbitrary providers.

### 2.3. Durable state, control and recovery

LamTools creates checkpoints around model turns and represents checkpoint relationships as a graph. A restore can select a scope, such as the child conversation, without rewriting the parent conversation. A fork creates a new session while preserving a graph edge to the source checkpoint. The same state boundary supports cancellation persistence and approval continuation, so an interrupted or waiting child is not reduced to an in-memory callback.

Arrange adds scheduled and event-triggered jobs. The runtime records occurrences, handles pause and cancellation transitions, reclaims expired leases and checks stale active turns during startup recovery. These features matter because delegation in a desktop runtime is not only a one-shot function call: the operator must be able to stop, inspect, resume or branch a task. The tests validate these transitions using deterministic stores and clocks; they do not claim production-scale fault tolerance.

### 2.4. Version-bound evaluation overview

The evaluation separates deterministic runtime behavior from retrieval quality. The first gate asks whether the implementation preserves its stated state and permission transitions. The second is a small quality case study over a fixed corpus and golden questions. Figure 3 shows the recorded test counts and derived retrieval-score differences; it does not turn the two kinds of evidence into one aggregate score.

![Figure 3. Evaluation overview. The left panel reports recorded test counts; the right panel reports the local-hybrid minus BM25-only change for stored retrieval metrics.](figures/evaluation-overview.png)

All values refer to LamTools `v0.2.6`, tag `v0.2.6`, commit `dd54b7fdd57f4eb0926f1dd3a94fbf2c2bb0fd8a`. The latest correctly configured full Core run collected 1,484 tests and recorded 1,481 passed, 2 skipped, one timing-sensitive failure and three warnings. The complete output is retained in `docs/paper/evidence/core-pytest-v0.2.6-20260820.log`. The failing assertion was the parallel-tool timing threshold; the same test passed in an isolated rerun retained at `docs/paper/evidence/timing-sensitive-isolated-v0.2.6-20260821.log`. The refreshed targeted mechanism run covered delegation, named sessions, model override, capability handling, checkpoint graph operations, rollback/fork and Arrange scheduling/recovery; it recorded 63 passed and 1 skipped test in `docs/paper/evidence/targeted-mechanism-v0.2.6-20260821.log`. The targeted run is a mechanism probe, not an independent replacement for the full suite.

| Evidence stream | Unit of analysis | Recorded result | Interpretation |
|---|---|---:|---|
| Full Core suite | Repository test cases | 1,481 passed; 2 skipped; 1 timing-sensitive failure | Broad regression evidence, with one unresolved environment-sensitive test |
| Targeted runtime suite | Delegation, persistence and scheduling cases | 63 passed; 1 skipped | Direct behavioral evidence for the paper's mechanism |
| Retrieval case study | 14 questions over 8 documents, two retrieval modes | 14 stored records per mode | Small, inspectable quality/latency comparison |
| Reproducibility target | Release and source state | `v0.2.6` / `dd54b7f...` | Prevents mixing later code with reported values |

### 2.5. Retrieval case study and trade-off

The repository contains an eight-document Chinese contract corpus and a 14-question golden set. The questions include exact, numeric, paraphrase and multi-document forms. The stored comparison is between BM25-only and local embedding plus hybrid retrieval. Local hybrid retrieval raises any-gold document Recall@1 by 0.071, Recall@5 and Recall@10 by 0.143, and first-any-gold MRR by 0.096. Warm query-time p95 latency rises by 4.92 ms, approximately 3.8 times the BM25-only value in the recorded environment.

| Configuration | Any-gold Recall@1 | Any-gold Recall@5 | Any-gold Recall@10 | First-any-gold MRR | Warm query p95 |
|---|---:|---:|---:|---:|---:|
| BM25-only | 0.786 | 0.857 | 0.857 | 0.821 | 1.75 ms |
| Local embedding + hybrid | 0.857 | 1.000 | 1.000 | 0.917 | 6.67 ms |
| Difference | +0.071 | +0.143 | +0.143 | +0.096 | +4.92 ms |

![Figure 4. Per-question evidence from the stored retrieval reports. Rank zero means that the gold document was not retrieved; the latency panel preserves observed wall-clock values rather than a fitted distribution.](figures/retrieval-per-query.png)

The per-question view makes the aggregate result less misleading. BM25-only misses the multi-document arbitration question and the paraphrase about deposit return, whereas local hybrid retrieval returns a gold document for both at a non-zero rank. The hybrid path also changes some top-document ordering and increases every recorded per-question latency. The case study supports a narrow engineering statement: the local vector leg improves coverage on this corpus at a measurable local latency cost. It does not support claims about legal-answer correctness, large-scale retrieval quality or provider-independent performance.

## 3. Discussion

The strongest technical signal is not that LamTools calls another model. It is that the call is made legible as a capability contract and a durable scope. The effective model, attachment capability, child-session identity, tool mode, approval state and parent projection can each be inspected, tested and recovered. This provides a runtime guard against a class of silent multimodal mismatches before they are misinterpreted as model failures; it is not a measured provider failure-rate reduction. The cost is additional state coordination and a larger failure surface than a single model call. A child session may wait for approval, require recovery or carry content that the selected model cannot consume; making those conditions explicit improves observability but does not remove them.

The retrieval case study illustrates the same trade-off at another layer. Adding a local vector leg improves first-hit coverage for this small corpus, but warm query-time p95 latency increases from 1.75 to 6.67 ms. The correct conclusion is not that hybrid retrieval is better in the abstract. It is that the runtime can expose a measurable quality/latency choice and preserve per-question evidence needed to revisit that choice.

For software-oriented agent systems, a credible paper should state which behavior is implemented, which behavior is planned, what baselines hold constant and where the evidence stops. LamTools is a compact case study of that discipline: its strongest result is an auditable connection between capability handling, durable control and measurable trade-offs, not evidence that a local runtime or delegation policy is universally superior.

## 4. Related work

General multi-agent frameworks such as AutoGen [1] and AgentScope [5] provide abstractions and platform support for building multi-agent applications. LamTools overlaps at the level of agent composition but makes a narrower runtime claim: its child is a durable tool invocation with a stable identity, bounded recursion and explicit model/capability handling. The paper does not compare task quality against these platforms or claim a new multi-agent protocol.

FrugalGPT studies cascades across language models for cost and quality [2], while RouteLLM learns routers from preference data [3]. These lines of work motivate heterogeneous model use, but LamTools does not train a router, learn a cascade policy or optimize a cost objective. Its evidence concerns the explicit execution path that allows an operator or configured call to select a child model and preserve the consequences in local runtime state.

MemGPT treats context management and interrupts as an operating-system-inspired memory problem [4]. LangGraph documents checkpoint savers, threads and durable graph state [8]. LamTools shares the engineering concern for resumable execution, but its evidence concerns its own SQLite checkpoint graph, approval continuation, child-session state and rollback/fork operations. MCP standardizes prompts, resources and tools for LLM applications [7]; LamTools integrates MCP within a broader local, approval-aware toolbox that also contains native and plugin-scoped tools. AgentDojo evaluates tool-using agents under prompt-injection attacks [6]; LamTools implements local approval and visibility boundaries, but does not provide a security proof or adversarial-robustness evaluation.

The local-first framing is grounded in the principles of local ownership, availability and user control described by Kleppmann et al. [9]. LamTools applies that framing to orchestration state in a desktop runtime; it does not claim that every configured provider call remains local.

| Related line | What prior work provides | LamTools boundary |
|---|---|---|
| Multi-agent platforms | Agent and platform abstractions [1, 5] | Runtime-level child-session operation |
| Model routing | Cost/quality selection and learned routers [2, 3] | Explicit selection path; no learned optimizer |
| Stateful agents | Context management and interruption concepts [4] | SQLite runtime state and checkpoint graph |
| Durable graphs | Checkpoints, threads and savers [8] | Local approval, child scopes, rollback/fork |
| Tool security and interoperability | Tool protocols and adversarial evaluation [6, 7] | MCP plus native/plugin tools under local permissions; no security proof |
| Local-first software | Local ownership and user control principles [9] | Local orchestration state, not necessarily local providers |

## 5. Methods

### 5.1. Audit and version control

The evidence boundary was established by reading the active `core/` package, its tests, release workflow, configuration and documentation at `v0.2.6`. Archived products and roadmap-only features were excluded. Every paper-facing result is tied to tag `v0.2.6` and commit `dd54b7fdd57f4eb0926f1dd3a94fbf2c2bb0fd8a`; the repository audit was performed on 20 August 2026 and the logged full rerun on 21 August 2026. The full Core run used the temporary `LAMTOOLS_COMMAND_SHELL=pwsh` selection because the default Git Bash environment could not resolve the Windows Python command; this is an environment-selection detail, not a missing Python installation.

### 5.2. Deterministic runtime evaluation

The runtime evaluation uses fake deterministic model clients and temporary SQLite workspaces. Tests assert state transitions and event projections rather than asking a provider to produce a subjective answer. The targeted set covers canonical model-ID resolution; named child-session reuse; model override; multimodal forwarding and text-model deferral; tool mode and allow-list behavior; recursive delegation blocking; approval continuation; cancellation persistence; parent/child event projection; checkpoint graph creation; scoped restore; rollback; fork; scheduled execution; pause/cancel transitions; lease reclaim; and startup recovery.

The full and targeted counts are reported as recorded test outcomes. Skips remain visible. No failed test was removed from the paper-facing evidence, and no provider-backed score was substituted for a deterministic behavioral assertion.

### 5.3. Retrieval protocol

The retrieval case study uses the repository's stored 14-question golden set, eight-document Chinese contract corpus and two report files: `e2e/rag-eval/reports/retrieval-none-20260815-095234.json` and `e2e/rag-eval/reports/retrieval-local-20260815-101253.json`. The same questions and gold-document labels are used in both modes. The reports retain per-question rank, top-document identifiers, vector-hit counts where applicable and wall-clock latency. The paper-facing derivation is stored in `docs/paper/evidence/retrieval-derived-v0.2.6.json` and is generated by `docs/paper/derive_retrieval_metrics.py` without rewriting the raw reports.

For a question set of size (N), any-gold document Recall@k is the fraction of questions for which any gold document appears in the first (k) deduplicated document results. Multi-document questions count as a hit when any gold document appears; complete-set recall is not measured. MRR is (N^{-1}\sum_i 1/r_i), where (r_i) is the rank of the first any-gold document and a missing rank contributes zero. Warm query-time p95 is calculated by inclusive linear interpolation over the stored per-question timings. The reported differences are direct arithmetic differences between derived aggregate values; no confidence interval or significance test is claimed because the case study is small and the stored reports do not contain repeated independent runs.

### 5.4. Provider smoke-test protocol

The paper-facing claims remain deterministic, but a separate provider smoke test is prepared for the OpenCode Go endpoint [11]. The endpoint is OpenAI-compatible and uses `/chat/completions` for `deepseek-v4-flash` and `mimo-v2.5`. Each model receives the same fixed prompt with temperature zero and a small output cap. The smoke test records only model, HTTP status, response shape, latency and provider-reported usage; it intentionally does not retain generated text or credentials. These results may be reported as an implementation sanity check only, not as a benchmark or model-quality evaluation.

### 5.5. Reproducibility and release state

The reproducibility bundle includes manuscript sources, bibliography, figure generator, generated figures, evaluation harness, golden questions, raw JSON reports and methodology notes. The software target is the existing public GitHub Release `v0.2.6`; the historical tag is not amended. Provider credentials, private configuration and user data are excluded. The paper record should archive one combined Chinese-primary/English PDF, while the software record should archive the existing release separately.

## 6. Limitations and non-claims

The evaluation is small and mostly deterministic. No provider-backed model-quality comparison, external user study or large-scale benchmark was performed. The retrieval corpus has eight documents and 14 questions; the observed values should not be generalized to legal retrieval, other languages or larger corpora. The report files do not contain a complete machine-environment fingerprint, so the values are version-bound case-study evidence. Provider behavior, API latency, model versions, network conditions and local hardware can change the results.

Some RAG session-history paths are present but not treated as fully validated because an older integration check retains a stale expectation. Planned VLM format routing, complete table extraction and large-scale contract workflows are excluded. The system overlaps conceptually with prior agent runtimes, routing work, persistence systems and tool protocols; no priority or “first” claim is made. Finally, the paper has not undergone peer review and the two-author equal-contribution statement reflects author agreement, not a venue's editorial decision.

## 7. Data and code availability

LamTools is available at `https://github.com/Lam-Arc/LamTools`. The exact reproducibility target is the public `v0.2.6` software release [10], commit `dd54b7fdd57f4eb0926f1dd3a94fbf2c2bb0fd8a`. The RAG harness, corpus, golden questions and raw reports are tracked under `e2e/rag-eval/` in that release. The frozen software release is archived at Software DOI `https://doi.org/10.5281/zenodo.22039646`; this bilingual paper record is identified by Paper DOI `https://doi.org/10.5281/zenodo.22040870`.

## 8. AI assistance disclosure

Generative AI tools were used as auxiliary support during the preparation and review of this work. The research, technical decisions, interpretation, and final review were human-led.

## 9. Conclusion

LamTools is an implemented local-first agent runtime whose most defensible paper story is capability-aware child-agent delegation integrated with durable state, explicit tool boundaries and operator control. At the fixed `v0.2.6` baseline, deterministic tests make delegation and recovery behavior inspectable, while the stored retrieval case study exposes a concrete quality/latency trade-off. The paper's value is therefore a reproducible system description with visible evidence boundaries, not an inflated claim of a universal routing method. A future release can expand provider-backed evaluation and external usage evidence; the present record remains valid when its exact version, limitations and non-peer-reviewed status stay visible.

## References

1. Wu, Q., Bansal, G., Zhang, J., et al. (2023). AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation. arXiv:2308.08155. https://doi.org/10.48550/arXiv.2308.08155

2. Chen, L., Zaharia, M., and Zou, J. (2023). FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance. arXiv:2305.05176. https://doi.org/10.48550/arXiv.2305.05176

3. Ong, I., Almahairi, A., Wu, V., et al. (2024). RouteLLM: Learning to Route LLMs with Preference Data. arXiv:2406.18665. https://doi.org/10.48550/arXiv.2406.18665

4. Packer, C., Wooders, S., Lin, K., et al. (2023). MemGPT: Towards LLMs as Operating Systems. arXiv:2310.08560. https://doi.org/10.48550/arXiv.2310.08560

5. Gao, D., Li, Z., Pan, X., et al. (2024). AgentScope: A Flexible yet Robust Multi-Agent Platform. arXiv:2402.14034. https://doi.org/10.48550/arXiv.2402.14034

6. Debenedetti, E., Zhang, J., Balunovic, M., et al. (2024). AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents. arXiv:2406.13352. https://doi.org/10.48550/arXiv.2406.13352

7. Model Context Protocol. (2025). Model Context Protocol Specification, protocol revision 2025-06-18. https://modelcontextprotocol.io/specification/2025-06-18/server/index

8. LangChain. (n.d.). LangGraph Persistence and Checkpointing. Official documentation. https://docs.langchain.com/oss/python/langgraph/persistence

9. Kleppmann, M., Wiggins, A., van Hardenberg, P., and McGranaghan, M. (2019). Local-first software: You own your data, in spite of the cloud. Proceedings of Onward! '19, 154–178. https://doi.org/10.1145/3359591.3359737

10. Zhang, Yulin, and Zhang, Yiming. (2026). LamTools (Version v0.2.6) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.22039646

11. OpenCode. (n.d.). Go documentation: endpoints, models and compatibility. Official documentation. https://opencode.ai/docs/go/
