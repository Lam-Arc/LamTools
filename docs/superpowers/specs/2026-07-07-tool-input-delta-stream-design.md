# Tool Input Delta Stream Design

## Goal

Writer should show large tool inputs, especially `write_file.content` and `edit_file.new_string`, while the model is still generating them. The write/edit tool itself should still run once after the final arguments are complete.

This replaces execution-time fake progress with model-input streaming. The user experience target is simple: when the model is drafting a file through a tool call, the visible card should show the draft content growing naturally.

## External Alignment

OpenAI exposes function-call argument deltas as `response.function_call_arguments.delta`, where `delta` is the arguments fragment, and a `response.function_call_arguments.done` event carries the final JSON arguments.

Claude's fine-grained tool streaming uses the same product shape: tool input arrives as fragments before full validation. Anthropic explicitly calls out large parameters such as documents or code blocks, and says clients should accumulate fragments and parse after the block closes.

Sources:

- https://platform.openai.com/docs/api-reference/realtime-server-events/response/function_call_arguments/delta
- https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/fine-grained-tool-streaming

## Product Requirement

- Show the generated file body during model generation, not during file execution.
- Keep file mutation atomic: final `write_file` / `edit_file` execution happens once.
- Preserve final result behavior: completed tool cards still show the existing diff/result artifact.
- Avoid storing every tiny delta permanently; persisted state should keep only the latest preview state.
- Do not introduce a Writer-only protocol. Core owns the generic streaming model/tool protocol; Writer only maps it into its app-server/UI state.

## Current Problem

The current stream path receives tool-call argument fragments, merges them in memory, then emits repeated running `tool_call` parts containing summarized arguments and a truncated `raw_arguments`.

That causes three issues:

- The UI sees `content: 17033 chars streaming` instead of the generated body.
- Large tool arguments are repeatedly resent as accumulated snapshots.
- The same event type is doing two jobs: "tool call exists" and "tool input grew".

The earlier line-level write/edit progress attacked the wrong phase. The slow visible phase is model generation of arguments, not filesystem mutation.

## Chosen Design

Introduce a generic tool-input delta protocol in Core.

The protocol has two concepts:

1. `tool_call`: a stable running item saying which tool call exists.
2. `tool_input_delta`: an append-only model input fragment for that tool call.

The projection layer owns accumulation. It turns deltas into a latest preview state for the tool card:

```json
{
  "type": "dynamicToolCall",
  "tool_name": "write_file",
  "arguments": {
    "path": "index.html"
  },
  "input_preview": {
    "field": "content",
    "content": "<!DOCTYPE html>\n<html>...",
    "chars": 18230,
    "truncated": false
  }
}
```

The final `tool_call` still carries parsed arguments for execution. The final `tool_result` still carries tool output and file-change artifacts.

## Module Shape

### Core LLM Stream Adapter

Responsibility: normalize provider events into text, thinking, tool-call metadata, tool-input deltas, and done events.

It should not know Writer or file tools. It only knows provider stream formats and emits generic tool input fragments with IDs.

### Core Kernel

Responsibility: route normalized stream events into runtime events.

It should emit:

- running `tool_call` when a tool name/call id is known;
- `tool_input_delta` when argument fragments arrive;
- final tool call data when arguments are complete.

It should stop using `raw_arguments` as the UI transport for large argument previews.

### Runtime Projection

Responsibility: accumulate tool input deltas by `thread_id + run_id + call_id`, preserve latest preview on the run item, and keep tool-call/result item identity stable.

This is the main seam. UI and app-server should not parse half-built JSON.

### Snapshot

Responsibility: persist latest item state only.

Snapshots should not persist every delta. On reconnect/refresh, the user should see the latest preview that existed when the snapshot was written.

### Frontend

Responsibility: render `inputPreview` on running write/edit tool cards.

It should prefer:

1. running input preview while the tool call is generating;
2. final diff/result once the tool execution completes.

## Preview Extraction

The projection layer accumulates raw argument text, but the UI preview should expose only high-value fields:

- `write_file.content`
- `edit_file.new_string`
- optionally `edit_file.old_string` as collapsed metadata, not primary display

Field extraction must be tolerant of invalid JSON because streamed input can be partial. The parser should return:

```python
{
    "path": "index.html",
    "preview_field": "content",
    "preview_content": "<partial body>",
    "chars": 1234,
    "truncated": False,
}
```

If the input is not parseable yet, continue accumulating and keep the best known preview. If the final arguments cannot be parsed, the existing invalid-tool-call behavior remains responsible for surfacing the error.

## Deletions And Simplifications

After the delta protocol is in place, these become debt and should be removed or reduced:

- Partial argument summary text like `content: N chars streaming`.
- UI reliance on `raw_arguments` for live display.
- Repeated running `tool_call` events whose only purpose is to refresh accumulated argument text.
- Any execution-time write/edit progress events.

Keep these:

- final parsed `tool_args` for execution;
- final `tool_result`;
- file-change artifacts and diff rendering;
- run/turn scoped tool-card isolation.

## Failure Behavior

- Missing field preview: show the normal running tool card with path/name only.
- Partial invalid JSON: keep accumulating; do not show an error until final parsing fails.
- Excessively large preview: cap the persisted/displayed preview, mark `truncated: true`, and keep full raw accumulation only in transient runtime memory when needed for final parsing.
- Refresh during generation: show the latest preview from snapshot; new deltas continue from the live stream.

## Acceptance Criteria

- During a large `write_file`, the tool card shows file content growing before the tool executes.
- `write_file` and `edit_file` still execute exactly once with complete final arguments.
- Completed cards still show final diff/result, not the transient preview as the primary result.
- Tool cards do not cross-contaminate across turns or runs.
- Refresh/reconnect preserves the latest preview without replaying every delta.
- Existing command output streaming still works.

## Expected Complexity Outcome

Short term: implementation touches more layers than a UI-only fix.

Long term: complexity decreases because the model stream protocol becomes explicit:

- provider delta handling stays in Core;
- projection owns accumulation;
- frontend consumes a stable `inputPreview` field;
- write/edit tools remain simple atomic tools.

