# sunday-core

The new Rust core. Windows and Android will both run this; Python is being
retired from the execution path.

Status: **M1, M2 and M3 complete and verified on the remote CI.** An end-to-end
turn runs from the CLI: message, model, tool call, approval, execution, answer,
with steer, compaction, sub-agents and crash recovery. Nothing in here has ever
touched a real user database.

## Crates

| crate | responsibility | may depend on | prod lines |
|---|---|---|---|
| `sunday-protocol` | frozen types, errors, events, ports | serde only | 584 |
| `sunday-store` | journal, receipts, tool stages, approvals, continuations | protocol, SQLite | 1,304 |
| `sunday-platform` | file and secret ports plus one OS-neutral implementation | protocol | 338 |
| `sunday-context` | token budget, message selection, compaction | protocol | 189 |
| `sunday-agent` | turn loop, budget, cancel, approval, steer, queue | protocol, store, context | 629 |
| `sunday-extensions` | sub-agent creation, permission narrowing, lifecycle | protocol, store, agent | 224 |
| `sunday-tools` | frozen tools; each declares hosts and side effect | protocol, platform | 348 |
| `sunday-cli` | inspection, self-test and an end-to-end turn | anything internal | 692 |

The rules are enforced, not documented-and-hoped:

```
python scripts/check-deps.py
```

It fails when a crate depends on a crate above it, or when a core crate mentions
`tauri`, `jni`, `lamtools_core`, `pyo3`, or spawns a process from `src/`. Tests
may spawn processes because the crash tests have to kill one.

## Run it

```
cargo test --workspace                 # 124 tests, real SQLite files, no mocks
cargo run -p sunday-cli -- health
cargo run -p sunday-cli -- store selftest --db /tmp/s.db
cargo run -p sunday-cli -- db inspect --db /tmp/s.db     # read-only, cannot write
cargo run -p sunday-cli -- journal tail --db /tmp/s.db --thread t1
cargo run -p sunday-cli -- children --db /tmp/s.db --parent t1
```

An end-to-end turn, with the approval actually gating the write:

```
# s1.json: one model turn that calls write_file
sunday turn --db /tmp/d.db --workspace /tmp/ws --thread t1 \
  --prompt "create hello.txt" --script s1.json
# -> needs_approval: appr-...

# s2.json: the turn that follows
sunday approve --db /tmp/d.db --workspace /tmp/ws --thread t1 \
  --approval appr-... --script s2.json
# -> completed: the file is written

sunday journal tail --db /tmp/d.db --thread t1
```

Steering a run in progress is a store write, not an in-memory queue:

```
sunday steer --db /tmp/d.db --thread t1 --text "also check the log"
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
| A6 | a steer written mid-run reaches the model on the next round, once | `m3_contract::a_steer_*` |
| A7 | a steer written while an approval is pending survives the resume | `m3_contract::a_steer_written_while_an_approval*` |
| A8 | compaction triggers over budget, keeps the task statement, and the turn continues | `context::tests`, `m3_contract::compaction_*` |
| A9 | the wall clock stops a slow model | `m3_contract::a_slow_model*` |
| A10 | a child cannot use an ungranted tool, and runs through the same loop | `subagent_contract::*` |
| A11 | a child left running by a crash is reported as orphaned | `subagent_contract::a_child_left_running*` |

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

* No HTTP or WebSocket protocol. `core.app_server.v1` compatibility is the next
  phase; the frozen `sunday.core.v1` types are what it will be mapped onto.
* No MCP, no skills, no plugin surface.
* No real provider call from the CLI: `turn` uses a scripted model. The adapter
  itself is real and tested against a local HTTP server.
* No Android or Windows host code. No SAF beyond the opaque-handle contract.

## Data safety

* `Store::open` creates a database at the path you give it. It never guesses a
  path and never reads `data/core.db`.
* `Store::open_read_only` opens with `immutable=1`, which is the only way to
  read a WAL-mode database without creating `-wal` and `-shm`. A database with a
  live write-ahead log is refused instead of being read as a moving target.
* The old core (`core/runtime-rs`) is untouched and still the only thing that
  writes a real user database. The new core has never opened one.
* Schema changes append steps keyed by `schema_version`; a database written by a
  newer core is refused rather than downgraded.

## Rolling back

The new core is additive. Removing `core/sunday-core` and the
`.github/workflows/sunday-core.yml` workflow restores the previous state exactly,
because nothing else in the repository imports it yet. No user data is involved.
