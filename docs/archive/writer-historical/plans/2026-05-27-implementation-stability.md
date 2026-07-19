<!-- 历史参考，不代表当前架构 -->
# Implementation Layer Stabilization Plan

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Writer's implementation phase stable for 20+ file engineering-complete projects without context explosion or server crash.

**Architecture:** Five independent changes to `runtime.py` (context management + tool execution), each addressing a single failure mode. Order matters — Task 1 must complete before Tasks 3-4 are meaningful.

**Tech Stack:** Python 3.14, existing Writer runtime, no new dependencies.

---

## Root Cause Map

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| 506KB payload, 160 messages, server crash | Tool outputs (`npm install`, large files) bloat context unchecked | **Task 1**: Truncate tool outputs |
| Compaction triggers but LLM responds with tool_calls instead of summary | Compaction prompt says "continue working" — LLM skips summary | **Task 2**: Force compaction turn |
| Old messages never stripped even after compaction summary | Phase 2 (Strip) detection fails when summary is very short | **Task 2**: Robust summary detection |
| LLM enters infinite tool-call chains | No loop detection | **Task 3**: Tool call loop breaker |
| `npm install` output is 300K+ chars | `run_command` result passed through unfiltered | **Task 4**: Command output filtering |

---

## Task 1: Tool Output Truncation

**Files:** `E:\LamTools\members\writer\backend\app\core\writer\runtime.py`

**Problem:** `_run_tool` returns raw tool output directly into conversation history. Large outputs (file reads, command results) explode context.

**Steps:**
- [ ] In `_run_tool` method (around line 988), after getting tool output, apply truncation:
  - Max 4000 chars for `run_command` results (keep first 500 + last 100 + exit code)
  - Max 8000 chars for `read_file` results (already has a max, enforce it)
  - Max 2000 chars for all other tool results
  - Add `[truncated — X chars]` suffix when truncation applied
- [ ] Add a `TOOL_OUTPUT_MAX` class constant = 4000 (override per tool type)
- [ ] Log truncation events at INFO level

**Verification:**
- [ ] Create a test that calls `run_command` with a command producing >4000 chars output
- [ ] Verify output is truncated with `[truncated]` marker
- [ ] Verify logged message appears

**Commit:** `fix: truncate large tool outputs to prevent context explosion`

---

## Task 2: Independent Compaction Call — Force Text Response via `tools=[]`

**Files:** `E:\LamTools\members\writer\backend\app\core\writer\runtime.py`

**Problem:** Compaction prompt is injected as `role: "user"` message into the normal conversation. When LLM is deep in a tool-call chain (back-to-back `write_file`), it tends to respond with `tool_calls` instead of reading the user message and producing text. Phase 2 never gets a summary → old messages never stripped → context explodes → crash.

**Root cause:** A `role: "user"` message in a tool-call stream has low authority. The LLM treats it as part of the ongoing workflow, not as a command to stop and summarize.

**Solution:** Make compaction a **separate LLM call** with `tools=[]` (empty tool list). This physically prevents the LLM from calling tools — it MUST respond with text. After getting the summary, strip old messages and resume the normal conversation.

**Steps:**
- [ ] Add `_compaction_llm_request(messages: list[dict]) -> str` async method:
  - Clone the current messages
  - Append compaction prompt as `role: "user"`
  - Call `self.deps.llm_client.chat_full(messages, tools=[])` — **tools=[] is the key**
  - Return the text response (the summary)
- [ ] In `_manage_context`, Phase 3 (Compact):
  - Instead of `result.append(compaction_prompt)` and returning,
  - Call `summary = await self._compaction_llm_request(messages)` 
  - (NOTE: `_manage_context` must become `async def` for this)
  - Strip old conversation: keep system + task + compaction prompt + summary + last N messages
  - Return compacted result
- [ ] Remove `_compaction_pending` flag — no longer needed since compaction is synchronous
- [ ] Remove `_compaction_failures` counter — no longer needed
- [ ] Add timeout handling: if independent LLM call takes >60s, skip compaction and continue (graceful degradation)

**Fallback (B):** If the independent LLM call fails or times out, inject a `role: "system"` message as a last-resort compaction:
  ```python
  messages.insert(1, {"role": "system", "content": "Context overflow. Summarize your progress before continuing."})
  ```
  System messages have higher priority in many LLMs than user messages in a tool-call stream.

**Verification:**
- [ ] Unit test: mock LLM client to return summary text → verify compaction call made with `tools=[]`
- [ ] Unit test: mock LLM client to raise TimeoutError → verify graceful degradation (system message fallback)
- [ ] E2E: run recipe app → verify "Compaction call" appears in logs within 10 minutes
- [ ] E2E: verify payload never exceeds 200KB

---

## Task 3: Tool Call Loop Breaker

**Files:** `E:\LamTools\members\writer\backend\app\core\writer\runtime.py`

**Problem:** Writer can call tools indefinitely without making progress (e.g., reading the same file repeatedly, writing stubs that trigger nudges). No mechanism detects or breaks this.

**Steps:**
- [ ] Add loop detection fields:
  - `_consecutive_tool_calls: int = 0` — reset in `run()`
  - `_last_tool_name: str = ""` — track for repetition detection
  - In the while-true loop, after a tool call turn, increment `_consecutive_tool_calls`
  - Reset to 0 when LLM responds with text (non-tool-call)
- [ ] At `_consecutive_tool_calls >= 8`:
  - Inject system message: `"PAUSE. You have made {count} consecutive tool calls. Summarize current state in 1-2 sentences, then continue."`
  - This forces a text response → compaction can trigger
- [ ] At `_consecutive_tool_calls >= 15`:
  - Force context strip (same as Task 2 force-strip logic)
  - Reset counter
  - Log at WARNING: `"Tool call loop detected — forced context strip"`
- [ ] Also detect repeated tool calls (same tool + same args 3x in a row):
  - Inject: `"You called {tool} with the same arguments 3 times. Move on."`

**Verification:**
- [ ] Test: simulate 8 consecutive tool calls → verify system message injected
- [ ] Test: simulate 15 consecutive tool calls → verify force-strip triggered
- [ ] Test: simulate 3 repeated identical calls → verify nudge injected

**Commit:** `fix: detect and break tool call loops after 8 consecutive calls`

---

## Task 4: Command Output Filtering

**Files:** `E:\LamTools\members\writer\backend\app\core\writer\runtime.py`

**Problem:** Commands like `npm install`, `pip install`, `cargo build` produce massive output (300K+ chars for npm). This output is largely useless for context but consumes huge token budget.

**Steps:**
- [ ] Create a method `_filter_command_output(command: str, output: str) -> str`:
  - For install-like commands (`npm install`, `pip install`, `yarn`, `cargo build`, `go get`, `bundle install`):
    - Return: first 300 chars of output + `"Exit code: {code}"` + last line (summary line)
    - Suffix: `"[full output omitted — install command]"`
  - For test commands:
    - Return: first 500 chars + `"...[truncated]..."` + last 20 lines (test summary)
  - For all other commands:
    - Apply Task 1 truncation (4000 chars)
- [ ] Call `_filter_command_output` in `_run_tool` for `run_command` actions
- [ ] Add `INSTALL_COMMANDS` set: `{"npm install", "pip install", "yarn add", "yarn", "cargo build", "go get", "bundle install", "pnpm install", "npm init -y", "pip install -r"}`
- [ ] Match command by prefix check against `INSTALL_COMMANDS`

**Verification:**
- [ ] Test: `npm install react` → verify output ≤ 500 chars
- [ ] Test: `python app.py` → verify full Task 1 truncation applies
- [ ] Test: `pytest` → verify first 500 + last 20 lines pattern applies

**Commit:** `fix: filter install command outputs to prevent context bloat`

---

## Task 5: Pre-Call Context Budget Check

**Files:** `E:\LamTools\members\writer\backend\app\core\writer\runtime.py`

**Problem:** Context check happens in `_manage_context()` during message building, but there's no pre-call budget check. The LLM call is made regardless of how bloated the context already is.

**Steps:**
- [ ] In the while-true loop, before each LLM call, add a pre-check:
  ```python
  estimated_tokens = self._estimate_context_tokens(messages)
  if estimated_tokens > usable * 0.85:
      # Force compaction turn — inject prompt, wait for summary, strip
      self._compaction_pending = True
      messages = self._manage_context(messages)  # Will inject compaction prompt
  ```
- [ ] Add `_estimate_context_tokens(messages: list[dict]) -> int` method:
  - Sum `_estimate_tokens(m.get("content", ""))` for all messages
  - Add 200 token padding per message for role/format overhead
- [ ] Only proceed with LLM call if estimated tokens < usable * 0.90

**Verification:**
- [ ] Test: create 50 messages with large content → verify pre-check blocks call and forces compaction
- [ ] Test: after compaction, verify estimated tokens < 60% of usable

**Commit:** `fix: pre-call context budget check to prevent oversized LLM requests`

---

## Execution Order

```
Task 1 (tool truncation) → foundation for all other tasks
  ↓
Task 2 (independent compaction call) → LLM physically blocked from calling tools during compaction
  ↓                         ↓
Task 3 (loop breaker)     Task 4 (command filtering)   Task 5 (pre-call budget)
```

Task 1 must complete first. Task 2 is the key architectural change. Tasks 3-5 are independent of each other and can be parallelized after Task 2.

## Post-Implementation E2E Verification

After all tasks complete, re-run `tests/bench_v3.py` ("开发一个食谱管理应用") with 30-minute timeout:
- [ ] Server does not crash
- [ ] Payload never exceeds 200KB
- [ ] "Strip:" or "Compaction" appears in logs
- [ ] Recipe app files produced (≥ 5 files, ≥ 30KB total)
- [ ] No `npm install` output in conversation context
