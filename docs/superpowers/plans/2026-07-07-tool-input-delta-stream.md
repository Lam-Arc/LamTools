# Tool Input Delta Stream Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display streamed tool input content while the model is generating file-write/edit arguments, without adding fake filesystem execution progress.

**Architecture:** Core emits explicit tool-input deltas, projection accumulates them into latest tool-card preview state, and UI renders that preview while preserving final diff/result behavior. The seam is the runtime projection interface: callers consume stable run items, not provider-specific partial JSON.

**Tech Stack:** Python 3.14, pytest, Vue 3, TypeScript, Vitest, existing LamTools Core runtime events and Writer app-server selectors.

## Global Constraints

- PowerShell commands involving Chinese must set UTF-8 output encoding.
- Keep Core product-neutral; no Writer-specific logic inside `core/src/lamtools_core`.
- Do not add execution-time write/edit progress.
- Reuse existing runtime events, run items, snapshots, app-server selectors, and `ChatThread.vue` rendering patterns where practical.
- Stage only files changed for this plan; leave unrelated dirty files untouched.

---

## File Structure

- Modify `core/src/lamtools_core/llm/__init__.py`: add normalized stream event kind metadata for tool-input deltas if needed by types.
- Modify `core/src/lamtools_core/llm/helpers.py`: keep provider delta merge for final calls; expose reusable argument-fragment accumulation helpers only if the current helpers cannot express the new event.
- Modify `core/src/lamtools_core/kernel/loop.py`: emit `runtime.part` with `part_type="tool_input_delta"` for argument fragments and keep `tool_call` as stable call identity.
- Modify `core/src/lamtools_core/event/runtime_projection.py`: accumulate deltas into run-item payload `input_preview`.
- Modify `core/src/lamtools_core/snapshot/__init__.py`: ensure latest `input_preview` persists with the run item.
- Modify `members/writer/frontend/src/appServer/selectors.ts` or current selector file if the shape is there: pass `input_preview` from app-server item into UI part data.
- Modify `members/writer/frontend/src/views/CoreWorkbenchView.vue`: map `input_preview` to `MessagePart.inputPreview`.
- Modify `core/ui/src/types.ts`: add optional `inputPreview` to `MessagePart`.
- Modify `core/ui/src/components/ChatThread.vue`: render running write/edit input preview before final result.
- Test `core/tests/test_llm_helpers.py`, `core/tests/test_runtime_projection.py`, `core/tests/test_run_item_snapshot.py`, `members/writer/frontend/tests/appServer/selectors.test.ts`, and `core/ui/tests/chat-thread-process.test.ts`.

## Task 1: Define Core Tool Input Delta Contract

**Files:**
- Modify: `core/src/lamtools_core/kernel/loop.py`
- Modify: `core/src/lamtools_core/event/runtime_projection.py`
- Test: `core/tests/test_runtime_projection.py`

**Interfaces:**
- Produces: runtime event payload with `part_type="tool_input_delta"`, `tool_name`, `call_id`, `delta`, `arguments_text`, and `response_index`.
- Consumes: existing run-item projection function that already handles `runtime.part`.

- [ ] **Step 1: Write failing projection test**

```python
def test_runtime_projection_accumulates_tool_input_delta_preview():
    first = project_runtime_event(RuntimeProjectionInput(
        id="evt-1",
        thread_id="thread-1",
        phase="runtime.part",
        sequence=1,
        summary="",
        preview="",
        payload={
            "part_type": "tool_call",
            "status": "running",
            "tool_name": "write_file",
            "call_id": "call-1",
            "tool_args": {"path": "index.html"},
            "run_id": "run-1",
        },
    ))
    second = project_runtime_event(RuntimeProjectionInput(
        id="evt-2",
        thread_id="thread-1",
        phase="runtime.part",
        sequence=2,
        summary="",
        preview="",
        payload={
            "part_type": "tool_input_delta",
            "status": "running",
            "tool_name": "write_file",
            "call_id": "call-1",
            "delta": "{\"path\":\"index.html\",\"content\":\"<html>",
            "arguments_text": "{\"path\":\"index.html\",\"content\":\"<html>",
            "run_id": "run-1",
        },
    ))
    assert first[0].item_id == second[0].item_id
    assert second[0].payload["input_preview"]["field"] == "content"
    assert second[0].payload["input_preview"]["content"] == "<html>"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.14 -m pytest core/tests/test_runtime_projection.py::test_runtime_projection_accumulates_tool_input_delta_preview -q`

Expected: fail because `tool_input_delta` is not projected yet.

- [ ] **Step 3: Implement minimal projection support**

Add `part_type == "tool_input_delta"` handling in `runtime_projection.py`. Use the same tool item id as `tool_call`. Payload should update `input_preview` and not create a separate visible item.

- [ ] **Step 4: Run test**

Run: `py -3.14 -m pytest core/tests/test_runtime_projection.py::test_runtime_projection_accumulates_tool_input_delta_preview -q`

Expected: pass.

## Task 2: Add Partial Tool Argument Preview Extraction

**Files:**
- Modify: `core/src/lamtools_core/event/runtime_projection.py`
- Test: `core/tests/test_runtime_projection.py`

**Interfaces:**
- Produces: `extract_tool_input_preview(tool_name: str, arguments_text: str) -> dict[str, object] | None`.
- Consumes: Task 1 projection support.

- [ ] **Step 1: Write failing tests**

```python
def test_extract_tool_input_preview_write_file_content():
    preview = extract_tool_input_preview(
        "write_file",
        "{\"path\":\"index.html\",\"content\":\"hello\\nworld",
    )
    assert preview == {
        "field": "content",
        "content": "hello\nworld",
        "chars": 11,
        "truncated": False,
    }

def test_extract_tool_input_preview_ignores_read_tools():
    assert extract_tool_input_preview("read_file", "{\"path\":\"a.py\"}") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.14 -m pytest core/tests/test_runtime_projection.py -q -k "extract_tool_input_preview"`

Expected: fail because the helper does not exist.

- [ ] **Step 3: Implement extraction helper**

Implement a small tolerant scanner for string fields. It must handle escaped `\\n`, `\\"`, and `\\\\` enough for live preview. It should target `write_file.content` and `edit_file.new_string`.

- [ ] **Step 4: Run tests**

Run: `py -3.14 -m pytest core/tests/test_runtime_projection.py -q -k "extract_tool_input_preview or tool_input_delta"`

Expected: pass.

## Task 3: Emit Tool Input Delta From Kernel Stream

**Files:**
- Modify: `core/src/lamtools_core/kernel/loop.py`
- Test: `members/writer/backend/tests/test_writer_core_kernel_adapter.py`

**Interfaces:**
- Consumes: existing `tool_call_delta` stream event.
- Produces: one stable running `tool_call` plus `tool_input_delta` updates as arguments grow.

- [ ] **Step 1: Write failing kernel-stream test**

Extend the existing streaming tool-call test around streamed `write_file` arguments. Assert that emitted runtime parts include:

```python
assert any(
    event.payload.get("part_type") == "tool_input_delta"
    and event.payload.get("tool_name") == "write_file"
    and "content" in event.payload.get("arguments_text", "")
    for event in sink.events
)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k streamed_tool_call_delta`

Expected: fail because only running `tool_call` parts are emitted.

- [ ] **Step 3: Emit delta events**

In the stream loop, when a tool-call delta appends function arguments, emit `tool_input_delta` with the raw fragment and current accumulated arguments text. Continue resolving final tool calls exactly as before.

- [ ] **Step 4: Reduce old summary reliance**

Keep `tool_args` summary for path/command chips. Stop using `content: N chars streaming` as the main visible content once `input_preview` exists.

- [ ] **Step 5: Run targeted tests**

Run:

```powershell
py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "streamed_tool_call_delta or write_file or edit_file"
py -3.14 -m pytest core/tests/test_runtime_projection.py -q
```

Expected: pass.

## Task 4: Persist Latest Preview In Snapshot

**Files:**
- Modify: `core/src/lamtools_core/snapshot/__init__.py`
- Test: `core/tests/test_run_item_snapshot.py`

**Interfaces:**
- Consumes: run item payload with `input_preview`.
- Produces: snapshot item preserving latest `input_preview`.

- [ ] **Step 1: Write failing snapshot test**

```python
def test_snapshot_preserves_tool_input_preview():
    snapshot = apply_run_item_event_sequence([
        RunItemEvent(
            kind="tool_call",
            item_id="thread-1:run-1:call-1:tool",
            thread_id="thread-1",
            turn_id="turn-1",
            status="running",
            payload={
                "type": "dynamicToolCall",
                "tool_name": "write_file",
                "arguments": {"path": "index.html"},
                "input_preview": {"field": "content", "content": "<html>", "chars": 6, "truncated": False},
            },
        )
    ])
    item = snapshot["items"]["thread-1:run-1:call-1:tool"]
    assert item["payload"]["input_preview"]["content"] == "<html>"
```

- [ ] **Step 2: Run test**

Run: `py -3.14 -m pytest core/tests/test_run_item_snapshot.py -q -k input_preview`

Expected: fail if snapshot drops nested preview payload.

- [ ] **Step 3: Implement preservation**

Keep `input_preview` in the same payload merge path as `arguments`, `tool_result`, and `metadata`.

- [ ] **Step 4: Run test**

Run: `py -3.14 -m pytest core/tests/test_run_item_snapshot.py -q -k "input_preview or tool_call"`

Expected: pass.

## Task 5: Pass Preview Through Writer Frontend Mapping

**Files:**
- Modify: `members/writer/frontend/src/appServer/selectors.ts` or the current selector source that builds chat messages.
- Modify: `members/writer/frontend/src/views/CoreWorkbenchView.vue`
- Modify: `core/ui/src/types.ts`
- Test: `members/writer/frontend/tests/appServer/selectors.test.ts`

**Interfaces:**
- Consumes: app-server item payload `input_preview`.
- Produces: `MessagePart.inputPreview`.

- [ ] **Step 1: Write failing selector test**

Add a running `write_file` item with:

```ts
input_preview: {
  field: 'content',
  content: '<html>',
  chars: 6,
  truncated: false,
}
```

Assert the selected message part exposes:

```ts
assert.deepEqual(part.inputPreview, {
  field: 'content',
  content: '<html>',
  chars: 6,
  truncated: false,
})
```

- [ ] **Step 2: Run test**

Run from `members/writer/frontend`: `npm test -- --run tests/appServer/selectors.test.ts -t input_preview`

Expected: fail because the field is not mapped.

- [ ] **Step 3: Add type and mapping**

Add:

```ts
inputPreview?: {
  field: string
  content: string
  chars: number
  truncated?: boolean
}
```

Map `input_preview` / `inputPreview` through to `MessagePart`.

- [ ] **Step 4: Run test**

Run from `members/writer/frontend`: `npm test -- --run tests/appServer/selectors.test.ts -t input_preview`

Expected: pass.

## Task 6: Render Live Tool Input Preview

**Files:**
- Modify: `core/ui/src/components/ChatThread.vue`
- Test: `core/ui/tests/chat-thread-process.test.ts`

**Interfaces:**
- Consumes: `MessagePart.inputPreview`.
- Produces: visible live preview in write/edit tool card body.

- [ ] **Step 1: Write failing UI test**

Create a running `write_file` part:

```ts
{
  id: 'tool-1',
  partType: 'tool_call',
  status: 'running',
  toolName: 'write_file',
  toolArgs: { path: 'index.html' },
  inputPreview: {
    field: 'content',
    content: '<html>\n<body>Live</body>',
    chars: 24,
    truncated: false,
  },
}
```

Assert rendered text contains `index.html` and `<body>Live</body>`.

- [ ] **Step 2: Run test**

Run from `core/ui`: `npm run test -- chat-thread-process.test.ts -t inputPreview`

Expected: fail because no preview UI exists.

- [ ] **Step 3: Render preview**

Add a branch in tool-card body before final result display:

- show preview only when `part.status === "running"` and `part.inputPreview?.content`;
- label it as generated input, not tool output;
- reuse existing streamed text rendering behavior if practical;
- keep final diff/result preferred after completion.

- [ ] **Step 4: Run UI tests**

Run from `core/ui`: `npm run test -- chat-thread-process.test.ts -t "inputPreview|tool"`

Expected: pass.

## Task 7: Remove Obsolete Streaming Summary Behavior

**Files:**
- Modify: `core/src/lamtools_core/kernel/loop.py`
- Test: `members/writer/backend/tests/test_writer_core_kernel_adapter.py`
- Test: `core/tests/test_runtime_projection.py`

**Interfaces:**
- Consumes: successful tool input preview from earlier tasks.
- Produces: no user-facing `content: N chars streaming` placeholder for write/edit content.

- [ ] **Step 1: Write failing cleanup assertion**

Add an assertion to the streaming tool-call test:

```python
assert all(
    event.payload.get("tool_args", {}).get("content") != "13 chars streaming"
    for event in sink.events
    if event.payload.get("part_type") == "tool_call"
)
```

- [ ] **Step 2: Run test**

Run: `py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k streamed_tool_call_delta`

Expected: fail if the placeholder still exists.

- [ ] **Step 3: Remove placeholder**

Keep path/command summary chips. For large content fields, rely on `input_preview` instead of string placeholders.

- [ ] **Step 4: Run targeted tests**

Run:

```powershell
py -3.14 -m pytest core/tests/test_runtime_projection.py core/tests/test_run_item_snapshot.py -q
py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "streamed_tool_call_delta or write_file or edit_file"
```

Expected: pass.

## Task 8: End-To-End Verification And Commit

**Files:**
- No new source files expected.
- Commit only files changed by this plan.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: verified local behavior and a scoped commit.

- [ ] **Step 1: Run full targeted backend checks**

Run:

```powershell
$OutputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
py -3.14 -m pytest core/tests/test_runtime_projection.py core/tests/test_run_item_snapshot.py core/tests/test_llm_helpers.py -q
py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "streamed_tool_call_delta or write_file or edit_file or run_command_emits_running_output_parts"
```

Expected: pass.

- [ ] **Step 2: Run frontend checks**

Run:

```powershell
cd core/ui
npm run test -- chat-thread-process.test.ts
cd ../../members/writer/frontend
npm test -- --run tests/appServer/selectors.test.ts
```

Expected: pass.

- [ ] **Step 3: Inspect changed files**

Run from repo root:

```powershell
git status --short
git diff --stat
```

Expected: only plan-related source and tests are modified, plus this plan/spec if not already committed.

- [ ] **Step 4: Commit**

Run:

```powershell
git add core/src/lamtools_core/llm/__init__.py core/src/lamtools_core/llm/helpers.py core/src/lamtools_core/kernel/loop.py core/src/lamtools_core/event/runtime_projection.py core/src/lamtools_core/snapshot/__init__.py core/tests/test_llm_helpers.py core/tests/test_runtime_projection.py core/tests/test_run_item_snapshot.py core/ui/src/types.ts core/ui/src/components/ChatThread.vue core/ui/tests/chat-thread-process.test.ts members/writer/frontend/src/appServer/selectors.ts members/writer/frontend/src/views/CoreWorkbenchView.vue members/writer/frontend/tests/appServer/selectors.test.ts docs/superpowers/specs/2026-07-07-tool-input-delta-stream-design.md docs/superpowers/plans/2026-07-07-tool-input-delta-stream.md
git commit -m "feat: stream tool input previews"
```

Expected: commit includes only this feature.

## Self-Review

- Spec coverage: covered provider alignment, Core event protocol, projection accumulation, snapshot persistence, frontend rendering, cleanup, and verification.
- Placeholder scan: no unresolved placeholders.
- Type consistency: `input_preview` is wire/payload shape; `inputPreview` is frontend `MessagePart` shape.
- Scope check: one protocol slice; implementation can be completed task by task without mixing unrelated Writer runtime work.

