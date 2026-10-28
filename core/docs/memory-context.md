# Memory context recall

<!-- user:“上下文应当能够被精确召回，记忆也应当保存记忆时的精确位置”+(说明来源位置、原文保存与召回边界)。 -->

When an agent writes, appends to, or edits a memory, the kernel captures the
original available conversation text before executing the tool. The memory
contains a `memory-context:<source_id>` link. The snapshot records the session,
turn, run, saving tool-call ID, workspace, and each message's original
`history_seq`, turn/message/item identifiers when available. Its
`lamtools-context://sessions/.../turns/...?call=...` URI is a source locator;
these URIs do not add a desktop navigation route.

Use the existing `memory` tool to load the latest saved context:

```json
{"action":"reload_context","scope":"project","path":"decisions/encoding.md"}
```

To load an older source, include the `source_id` from its link. The result
contains the original messages, source locator, available source IDs, capture
time, and `untrusted_context: true`. It is historical evidence returned as a
tool result, not a replacement system instruction.

By default, a snapshot includes the latest user message and following
assistant/tool messages up to the memory call. To save an earlier available
range, pass inclusive `source_start_seq` and/or `source_end_seq` values when
writing, appending, or editing. An absent boundary or reversed range fails
without changing the memory. Missing history is never reconstructed from a
summary or invented. If only a summary remains available, the captured text
is that summary; it cannot recover the already unavailable original messages.

Snapshots are immutable by content hash, stored under the memory tier's hidden
`.contexts/<sha256>.json` directory. They survive restarts and moving/renaming
the Markdown memory within its tier. Rewriting via the agent tool retains
older source links; appending/editing adds another. Snapshot files are excluded
from memory listings and prompt indexes. Unreferenced snapshots are retained;
this feature does not introduce automatic source retention cleanup.

The context is limited to 200,000 serialized characters. Oversized captures
fail and request a smaller range, rather than silently truncating original
text. System messages, provider-private state and media payloads are excluded;
omitted media is marked on its message. Original text blocks and tool-call
arguments are retained. This is text recall, not media playback or rereading
the current version of an external file/webpage.

Missing snapshots and legacy memories without provenance return
`source_not_found`; changed snapshots return `source_corrupt`. CLI, RPC and
direct library writes outside an agent run have no conversation history to
capture, so they remain supported without manufacturing provenance.
