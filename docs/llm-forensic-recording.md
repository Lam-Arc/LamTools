# quality-task-1 — LLM HTTP forensic recording

Raw recording is a developer diagnostic, disabled by default. Enable it in the
environment of the Sunday backend/native process before launching it:

```powershell
$env:LAMTOOLS_LLM_RAW_RECORDING = '1'
$env:LAMTOOLS_LLM_FORENSIC_DIR = 'E:\LamTools\data\llm-forensics'
```

Unset the switch or set it to `0` to disable recording. This is an environment
switch, with no separate GUI feature. CLI and app-routed backend calls use the
same recorder. If the directory override is absent, the default is
`<LAMTOOLS_CORE_DATA_DIR>/llm-forensics`, or `data/llm-forensics` relative to the
process working directory when that data-directory variable is absent.

Each actual HTTP attempt has its own UUID directory containing:

- `request.bin`: the complete serialized entity body actually supplied to the
  HTTP client, including JSON whitespace, ordering, Unicode encoding, and
  multipart boundaries and uploaded file bytes.
- `response.bin`: entity-body bytes received from HTTP, before character
  decoding or content decompression. Compressed bodies remain compressed.
- `metadata.json`: session/run/step, routed model, provider, protocol, sanitized
  endpoint, UTC timestamps, HTTP status, retry index, persisted byte counts,
  SHA-256 checksums, and capture state. Native empty-response retry and redirect
  indexes are also recorded.

No body redaction, length limit, summary, or fingerprint replaces the bytes.
Headers, URL credentials/query/fragment, and exception messages are excluded
from diagnostic metadata. Raw bodies intentionally retain all their contents;
keep these local evidence files when investigating an anomaly. SHA-256 values
provide integrity checks, not a substitute for inspecting the actual payload.

## Coverage and completion

Python `CoreHttpLLMClient` covers OpenAI Chat Completions, OpenAI Responses,
Anthropic Messages, Gemini, and custom profiles sharing those dispatch paths.
The app router delegates to this client; CLI, sub-agent, title, and compaction
requests also use it. Streaming/non-streaming attempts, provider error bodies,
transport failures, and retries are recorded independently. Python image
generation and multipart image edits use the same recorder.

The shared Rust runtime records the same four text protocols and its image
generation endpoint. With recording enabled, native redirect hops are captured
individually before following them; automatic decompression is disabled to
preserve entity bytes. Ordinary behavior stays unchanged when recording is off.
Reference-image downloads, returned image URL downloads, web/search/MCP traffic,
and arbitrary external commands are not model inference requests and are outside
this recorder.

For SSE, the recorder drains raw bytes after `[DONE]` or a native terminal event
until HTTP EOF. The existing read/idle/cancellation deadlines still apply. A
server that never closes can therefore end with an interrupted/failed capture;
`[DONE]` alone never proves completion. Parser limits do not truncate recorded
bytes already received; an early parser error/consumer close leaves the record
explicitly incomplete if HTTP EOF was not reached.

`complete` means both bodies were persisted and HTTP EOF was observed. HTTP
errors can have complete body captures; check `status`/`http_state` separately.
`failed` and `interrupted` preserve available bytes. A process kill can leave
`in_progress`, invalid/missing metadata, or bytes beyond the last manifest count;
none of those states is complete. Capture write failures surface as operation
errors rather than silently sending an unrecorded request. Captures use flush
and filesystem synchronization; disk exhaustion or a killed process cannot
guarantee evidence that never reached durable storage.

Kernel requests and kernel-executed image tools carry actual session/run/step
identity. Native agent calls inherit hook session/run identity and the current
tool-round index (native `step`), with turn identity as fallback when no separate
run identity exists. Auxiliary/direct calls without those identities explicitly
report `partial_or_unavailable` or `host_does_not_supply_request_identity` rather
than inventing them. Raw recording does not reconstruct missing historical
requests and makes no cache-policy changes.

## Investigating a cache anomaly

Cache warnings now include `forensic_record_id` and
`previous_forensic_record_id`. Open those directories and compare their actual
`request.bin` files. JSON bodies can be parsed locally to compare tool schema
descriptions, parameters, ordering, messages, and request options; the original
bytes remain available for checking serialization differences. A process
restart has no in-memory cache-comparison baseline, but the independently
persisted records remain available.

Audit a directory without network access or modifying records:

```powershell
py -3.14 -m lamtools_core.llm.forensics E:\LamTools\data\llm-forensics
```

The command reports actual sizes, metadata state, checksum/count discrepancies,
and `verified_complete`. Its exit status is nonzero if any record is incomplete
or invalid. It reads live captures conservatively and never guesses that a
process has died. Missing/invalid metadata requires inspecting the body files;
it does not justify discarding them.

## Verification scope

Acceptance uses local HTTP mocks and localhost TCP servers only. Tests cover
exact JSON/multipart bytes, large and compressed bodies, all text protocols,
post-terminal tails, HTTP errors, retry records, cancellation, early close,
storage failures, checksum corruption, and cache-record correlation. Existing
kernel, compaction, provider, toolbox, and app-routing tests are also exercised.
No historical requests are replayed and no paid model calls are made.

Verified in this task: 399 Python tests passed, 1 skipped; all 165 shared native
runtime tests passed with recording enabled. The original 164-test native suite
also passed with recording disabled, before the additional redirect test. The
Python app tests emitted aiosqlite connection-cleanup
and datetime-adapter warnings; those warnings were not changed or suppressed.
`cargo check` and `git diff --check` passed. The skip is not a passed acceptance
gate.

Recording synchronizes body writes and metadata on each received chunk, adding
disk latency and storage consumption while enabled. There is no automatic
rotation/deletion that would discard evidence. Production throughput, installed
desktop/mobile execution, power-loss durability, and real provider behavior
have not been verified by this task.

## Changed files

- `core/src/lamtools_core/llm/forensics.py` — recorder and read-only integrity audit.
- `core/src/lamtools_core/llm/cache_diagnostics.py` — current/previous raw record correlation.
- `core/src/lamtools_core/llm/retry.py` — attempt identity and deterministic stream closure.
- `core/src/lamtools_core/cli.py` — all profiled text HTTP dispatch and raw SSE draining.
- `core/src/lamtools_core/kernel/loop.py` — session/run/step propagation and tool capture context.
- `core/src/lamtools_core/tool/image_tools.py` — generation/edit HTTP dispatch.
- `core/runtime-rs/src/forensics.rs` — native recorder, redirect handling, and local tests.
- `core/runtime-rs/src/provider.rs` — native text attempts and all SSE protocol readers.
- `core/runtime-rs/src/image_gen.rs` — native image generation attempts.
- `core/runtime-rs/src/lib.rs` — native inference/compaction/tool identity scopes.
- `core/tests/test_llm_forensics.py` — Python forensic acceptance tests.
- `docs/llm-forensic-recording.md` — usage, evidence, and limitations.

Existing unrelated changes and untracked files were retained. The previously
untracked `cache_diagnostics.py` was extended in place. No commits or releases
were created.
