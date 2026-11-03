# sunday-core

The new Rust core. Windows and Android will both run this; Python is being
retired from the execution path.

Status: **M1 and M2 complete, M3 not approved.** There is no network model
client and no turn command in the CLI yet, on purpose. Nothing in here has ever
touched a real user database.

## Crates

| crate | responsibility | may depend on | prod lines |
|---|---|---|---|
| `sunday-protocol` | frozen types, errors, events, ports | serde only | 579 |
| `sunday-store` | journal, receipts, tool stages, approvals, continuations | protocol, SQLite | 1,016 |
| `sunday-platform` | file and secret ports plus one OS-neutral implementation | protocol | 242 |
| `sunday-agent` | turn loop, budget, cancel, approval hand-off, queue | protocol, store | 548 |
| `sunday-tools` | frozen tools; each declares hosts and side effect | protocol, platform | 348 |
| `sunday-cli` | headless entry point, inspection and self-test | anything internal | 248 |

The rules are enforced, not documented-and-hoped:

```
python scripts/check-deps.py
```

It fails when a crate depends on a crate above it, or when a core crate mentions
`tauri`, `jni`, `lamtools_core`, `pyo3`, or spawns a process from `src/`. Tests
may spawn processes because the crash tests have to kill one.

## Run it

```
cargo test --workspace                 # 63 tests, real SQLite files, no mocks
cargo run -p sunday-cli -- health
cargo run -p sunday-cli -- store selftest --db /tmp/s.db
cargo run -p sunday-cli -- db inspect --db /tmp/s.db     # read-only
cargo run -p sunday-cli -- journal tail --db /tmp/s.db --thread t1
```

Android cross-compile, verified locally with NDK 30:

```
CC_aarch64_linux_android=<ndk>/bin/aarch64-linux-android21-clang.cmd \
AR_aarch64_linux_android=<ndk>/bin/llvm-ar.exe \
cargo build --target aarch64-linux-android \
  -p sunday-protocol -p sunday-store -p sunday-platform -p sunday-agent
```

## The guarantees this layer owns

| id | rule | test |
|---|---|---|
| S1 | one `request_id` produces one receipt and one event; a different body under the same id is refused | `store_contract::s1*` |
| S2 | `seq` is contiguous per thread, survives reopening, and a repeated `event_id` is a no-op | `store_contract::s2*` |
| S3 | tool intent is durable before any side effect | `store_contract::s3*` |
| S4 | a dispatched non-idempotent call with no result becomes `unknown` and is never replayed | `store_contract::s4*`, `loop_contract::a4*` |
| S5 | an approval is bound to an argument digest | `store_contract::s5` |
| S6 | an expired approval is not consent | `store_contract::s6` |
| S7 | an approval can be spent once; a zero TTL is refused | `store_contract::s7*` |
| S8 | a projection rebuilds from the journal alone | `store_contract::s8` |
| A1 | round and tool-call budgets are explicit and enforced | `loop_contract::a1*` |
| A2 | after cancel no tool starts | `loop_contract::a2` |
| A4 | unknown outcome stops the turn | `loop_contract::a4` |
| A5 | a second run queues instead of being refused | `loop_contract::a5*` |

## Fault injection

These are real, not simulated return values:

| what | how | where |
|---|---|---|
| process killed after dispatch | child process calls `abort()` after `mark_dispatched` | `store_contract::k1` |
| write interrupted mid-transaction | child opens raw SQLite, inserts, `abort()` before commit | `store_contract::k2` |
| two processes writing at once | two child processes append 20 events each | `store_contract::c2` |
| recovery re-run | `recover()` twice, second must be a no-op | `store_contract::k3` |
| abandoned receipt | process dies after `accept_command` | `store_contract::k4` |
| inspection cannot write | file size before and after `db inspect` | `store_contract::k5` |
| newer schema refused | bump `schema_version` to 99 | `store_contract::k6` |

## What is deliberately not here yet

* No model transport. `sunday-llm` exists only as a validated prototype in
  `.tmp/migration-trial`; it becomes a crate in M3.
* No guidance/steer, no context compaction, no sub-agents, no MCP, no skills.
* No HTTP or WebSocket protocol. `core.app_server.v1` compatibility is M3.
* No permission layer. Sensitive paths such as `.env` are not blocked yet; there
  is a parity test that records this as a known gap instead of pretending.
* No Android or Windows host code. No SAF.

## Data safety

* `Store::open` creates a database at the path you give it. It never guesses a
  path and never reads `data/core.db`.
* `Store::open_read_only` refuses to create anything and is what `db inspect`
  uses. A test asserts the file size does not change.
* The old core (`core/runtime-rs`) is untouched and still the only thing that
  writes a real user database. The new core has never opened one.
* Schema changes append steps keyed by `schema_version`; a database written by a
  newer core is refused rather than downgraded.

## Rolling back

The new core is additive. Removing `core/sunday-core` and the
`.github/workflows/sunday-core.yml` workflow restores the previous state exactly,
because nothing else in the repository imports it yet. No user data is involved.
