# Writer DB Transcript Design Review

## Review Purpose

This is an independent review of `docs/writer-db-transcript-design.md`.

The review checks whether the design is clear, complete, minimal, and aligned
with the target principle:

```text
backend structured facts -> database -> transcript API -> frontend rendering
```

The design direction is correct. It removes the unstable dual display path and
puts business facts back under backend/database ownership. However, several
parts still need tightening before implementation, otherwise the system can
reintroduce ambiguity under a cleaner name.

## Overall Judgment

| Area | Judgment | Reason |
|---|---|---|
| Core direction | Reliable | One durable source of truth is the right architecture for live and replay consistency. |
| Hierarchy | Mostly reliable | `work_root -> session -> turn -> model_call -> block -> artifact` matches the real domain. |
| Frontend responsibility | Reliable | Frontend is correctly reduced to rendering and local view preference. |
| Streaming persistence | Needs hardening | The write model describes intent but not enough consistency rules. |
| Final reply modeling | Needs correction | `assistant_text` and `final_reply` can duplicate or conflict. |
| Status lifecycle | Needs correction | Status names exist, but legal transitions and ownership are not defined. |
| Real-time refresh | Needs correction | Polling is acceptable, but snapshot versioning/watermarks are missing. |
| Artifact strategy | Mostly reliable | The split is right, but retention and loading contracts need definition. |
| Migration plan | Too broad | It lists phases, but does not define deletion targets or acceptance gates per phase. |

## Unreasonable Or Risky Points

### 1. `assistant_text` And `final_reply` Are Ambiguous

The design currently allows both:

- `blocks.type = assistant_text`
- `blocks.type = final_reply`
- `turn.assistant_message_id`

This creates three possible sources for the final visible assistant text.

That is dangerous because the exact bug being solved is caused by multiple
display sources disagreeing. If `assistant_text` streams during the final model
call, and then `final_reply` is inserted separately, the frontend may show a
duplicate reply or choose the wrong one.

Recommended correction:

```text
assistant_text is the streamed assistant body.
If the model call ends without tool calls and the turn completes, that same
assistant_text block becomes the final reply by status/role, not by duplication.
turn.assistant_message_id can point to the durable message record, but it must
not create a separate display source.
```

If a separate `final_reply` block is kept, the document must define exactly why
it exists and which block is renderable. At the moment, it is not justified.

### 2. Statuses Are Named But Not Modeled

The design lists statuses such as `idle`, `running`, `completed`, `failed`, and
`cancelled`, but it does not define legal transitions.

This matters because the original visible defect included a session marked
`failed` while work was still running. Without a status state machine, the same
class of bug can survive the redesign.

Recommended correction:

```text
session status derives from active turns.
turn status derives from active model calls and terminal result.
model_call status derives from provider/runtime lifecycle.
block status derives from the producer of that block.
```

The document should also define forbidden transitions, for example:

```text
completed -> running is forbidden
failed -> running is forbidden unless a new turn/model_call is created
running session with active running turn must not be displayed as failed
```

### 3. Snapshot Consistency Is Missing

Polling `/transcript` is simple and acceptable, but the document does not define
how the frontend knows whether it is seeing a coherent snapshot.

During streaming writes, the backend may update a block, a model call metric,
and a turn status in close succession. If the transcript endpoint reads halfway
through those writes, the frontend can briefly show impossible states.

Recommended correction:

- add a monotonically increasing `revision` or `updated_at` watermark at session
  or transcript level;
- make transcript projection read in one DB transaction;
- return `revision` with every transcript response;
- frontend replaces its snapshot only when the response revision is newer.

This keeps polling as a notification/read cadence while preserving DB as the
source of truth.

### 4. Ordering Is Under-Specified Across Model Calls

The design defines:

- turn order by `turns.sequence`
- model call order by `model_calls.sequence`
- block order by `blocks.sequence`

That is enough for nested rendering, but not enough for a flat process timeline
if future UI needs to interleave events across calls or show exact chronology.

Recommended correction:

Keep the nested order as the primary display contract, but add an optional
monotonic `event_sequence` or `created_at` at block level for audit and exact
temporal debugging. This should not replace the hierarchy; it only supports
diagnosis.

### 5. Tool Call Pairing Needs Stronger Constraints

The document says `tool_call_id` connects call/result blocks, but it does not
define cardinality.

Ambiguity:

- Can one tool call have multiple result blocks?
- Can a failed tool call have no result block?
- Can result arrive before call block is completed?
- What happens when streamed tool args are malformed until complete?

Recommended correction:

Define the contract:

```text
one tool_call block may have zero or one terminal tool_result block;
streaming args update the tool_call block until the call is dispatched;
tool_result references the same tool_call_id;
failed execution is represented as a tool_result block with failed status or an
error block explicitly attached to the tool_call_id.
```

If multiple result artifacts exist, they should be artifacts attached to one
result block, not many competing result blocks unless the domain requires it.

### 6. Metrics Need A Clear Aggregation Rule

The process bar requirement is:

```text
x s, x calls, x total input tokens, x total output tokens
missing values display as X
```

The design says metrics come from `model_calls`, but it does not define exactly
how missing, partial, and running values aggregate.

Recommended correction:

```text
call count = count(model_calls for the turn)
input tokens = sum known input_tokens; null if none are known
output tokens = sum known output_tokens; null if none are known
duration = completed_at - started_at for terminal calls; now - started_at only
for currently running calls; historical running records must remain unknown or
be repaired by backend, not estimated by frontend
```

The frontend should format unknown as `X`; it should not invent missing metrics.

### 7. Polling Interval Is A UI Policy, Not A Durable Contract

The document specifies 300-1000 ms polling. That is a reasonable starting range,
but it should not become the architecture.

Recommended correction:

Document the actual contract as:

```text
frontend periodically refetches transcript while backend reports the session or
turn as active.
```

The exact interval should be a frontend policy constant, tuned for latency and
load.

### 8. Artifact Retention And Privacy Are Not Defined

The artifact split is right, but complete artifact storage can grow quickly and
may include sensitive command output, paths, diffs, or images.

Recommended correction:

The document should define:

- whether artifacts are retained forever or garbage-collected with sessions;
- maximum inline preview size;
- whether full payloads live in DB, files, or content-addressed storage;
- whether artifact reads require the same work root/session authorization;
- how missing artifact files are represented.

Without this, artifact storage can become a future reliability and privacy bug.

### 9. Migration Direction Does Not Yet Enforce Subtraction

The migration section says to remove fallback display paths, but it does not
name deletion gates.

For this task, subtraction is not optional. The implementation plan should make
old paths fail tests or disappear, otherwise dual logic will remain.

Recommended correction:

Each phase should have a deletion target, for example:

```text
after transcript endpoint is used by ChatThread, remove frontend runtime-event
projection for reasoning/tool/final display;
after block schema is authoritative, reject records without turn/model_call/type
at backend persistence boundaries;
after artifact records exist, remove inline full artifact payload rendering from
transcript rows.
```

### 10. The Document Mentions A Messages Table Without Defining The Contract

The completeness table says user messages and final replies come from a
messages table, but the design does not define whether that table already
exists, what it owns, or how it relates to `turns` and `blocks`.

Recommended correction:

Either define the message table contract or remove it from the core design and
make `turns` own user/final text directly for the first implementation.

The current wording leaves an implementation gap.

## What Should Be Changed Before Implementation

The design should be amended before code work starts:

1. Make `assistant_text` the only renderable assistant body block unless a
   separate `final_reply` block has a proven purpose.
2. Add explicit status derivation and forbidden transitions.
3. Add transcript snapshot `revision` and transactional read requirements.
4. Define tool call/result cardinality.
5. Define exact metric aggregation and unknown-value behavior.
6. Add artifact retention, preview size, and authorization rules.
7. Convert the migration section into a subtractive migration plan with deletion
   gates.
8. Define or remove the referenced messages table contract.

## Final Review Conclusion

The design captures the correct architecture and is a strong basis for the
rewrite. It is not yet implementation-ready because several concepts that must
be singular are still plural:

- assistant text vs final reply;
- live status vs terminal status;
- transcript read timing vs streaming write timing;
- tool call vs tool result ownership;
- message table vs block table ownership.

Those must be resolved in the document first. Otherwise the implementation can
look cleaner while preserving the same root cause: more than one place is
allowed to decide the same display fact.
