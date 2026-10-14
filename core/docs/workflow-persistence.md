# Workflow persistence reliability

The JSON queue is the authoritative queue/history record. Enqueue, status
updates, cancellation, deletion and clearing acknowledge success only after
the atomic file replacement succeeds. The writer flushes and fsyncs the
temporary file before replacement. A failed commit restores the previous
in-memory view; returned items do not share mutable state with the store.

Required queue, snapshot and journal failures use `WorkflowPersistenceError`
(a `RuntimeError`). Workflow RPCs retain `status: error` and the existing
`error` message, adding `code: WORKFLOW_PERSISTENCE_FAILED` and `retryable: true`.
If enqueue committed but worker startup recovery failed, the error also carries
`queue_id` and `run_id`: inspect that existing task instead of enqueuing it again.
The existing Workflow UI error handler rejects these responses. No failed write
produces an accepted, running or completed queue event.

Execution starts only after the running queue state is committed. Background
write failures leave the worker alive and expose a failed projection with
`metadata.persistence_error`, including the last persisted status. Existing
waiters receive the persistence error. Terminal and paused results awaiting a
commit remain in a pending map; the worker retries their writes once per second
without invoking the executor again. Shutdown and re-enable flush pending
results before treating old running records as interrupted work. Explicit
cancellation remains terminal rather than inheriting a concurrent shutdown pause.

Snapshots are required resumable state, not disposable computation caches.
Snapshot writes publish their cache only after commit, and read errors are not
treated as missing snapshots. Required persistence errors bypass node retries.
When a snapshot commit fails, the runner records a terminal failure in its
independent journal if that journal is still available. Terminal run status
notifications follow journal persistence. A recovered terminal journal result
is an idempotent read of the same run, avoiding repeated side effects.

Related boundaries: explicit content-cache deletion/clearing rolls back and
reports failed writes; ordinary pure-node cache insertion stays best effort.
Workflow-definition deletion no longer ignores filesystem errors. An optional
rewrite of a readable legacy queue remains best effort because it does not
accept new work. GUI/event delivery is still best effort; periodic queue reads
recover the authoritative state rather than relying on notification delivery.

## Verification and limits

`core/tests/test_workflow_persistence.py` injects write/fsync/read failures and
checks rollback, RPC errors, execution gating, background recovery, snapshot
recovery, cancellation during commits, pending results at shutdown, and explicit
cache/definition mutations. `core/ui/tests/workflow-runtime-services.test.ts`
checks that the existing API rejects persistence-error payloads.

The queue remains a single-process, cached JSON store. This change does not add
cross-process queue claims or protect against independent writers replacing the
same file. Pending results are in memory until their queue write succeeds;
after process loss the bundled runner uses the durable journal/snapshots.
Third-party runners without durable recovery cannot promise exactly-once side
effects. If both checkpoint and journal persistence fail, an externally completed
side effect can remain uncertain and requires investigation. Atomic replacement
and file fsync do not constitute a platform-independent power-loss guarantee.
