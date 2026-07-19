# Core Sub Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Writer sub-agent execution onto a Core-owned reusable sub-session MVP.

**Architecture:** Core owns sub-session identity, numbering, and tool filtering. Writer keeps its existing Kit/model/tool adapters and calls Core to run a reusable sub session through `CoreLoopKernel`.

**Tech Stack:** Python 3.14, pytest, `lamtools_core`, Writer backend.

## Global Constraints

- Core must not know Writer product names.
- MVP does not add parallel sub agents, locks, queues, workspaces, branches, role templates, or `write_scope`.
- Sub agent tools equal parent tools minus `sub_agent`.
- Sub sessions are reusable by parent session plus agent name.

---

### Task 1: Core Sub-Session Identity

**Files:**
- Create: `core/src/lamtools_core/sub_session.py`
- Test: `core/tests/test_sub_session.py`

**Interfaces:**
- Produces: `SubSessionManager.get_or_create(parent_state, agent_name) -> SubSessionRef`
- Produces: `filter_sub_agent_tools(tools, sub_agent_tool_name="sub_agent") -> list[dict]`

- [x] Write tests for stable numbering and tool filtering.
- [x] Run `py -3.14 -m pytest core/tests/test_sub_session.py -q` and verify failure.
- [x] Implement the minimal Core module.
- [x] Run the same test and verify pass.

### Task 2: Writer MVP Routing

**Files:**
- Modify: `members/writer/backend/app/core/writer/core_kernel_adapter.py`
- Modify: `members/writer/backend/app/core/writer/agent_runtime.py`
- Test: `members/writer/backend/tests/test_agent_runtime.py`
- Test: `members/writer/backend/tests/test_tool_contracts.py`

**Interfaces:**
- Consumes: `SubSessionManager.get_or_create`
- Consumes: `filter_sub_agent_tools`
- Produces: Writer `sub_agent` tool result metadata with `agent_index`, `agent_name`, and `sub_session_id`

- [x] Add failing Writer tests for no `write_scope`, no role allowlist, no parallel sub-agent policy, and stable sub-session metadata.
- [x] Run targeted Writer tests and verify failure.
- [x] Change Writer routing to use Core sub-session identity and existing `CoreLoopKernel`.
- [x] Run targeted Writer tests and verify pass.

### Task 3: Verification

**Files:**
- No new files.

- [x] Run targeted Core and Writer backend tests.
- [x] If shared runtime imports are affected, run `py -3.14 -m pytest core/tests -q`.
- [x] Report any existing unrelated failures separately.

## Verification Completed

- `py -3.14 -m pytest core/tests/test_sub_session.py -q` -> 5 passed.
- `py -3.14 -m pytest members/writer/backend/tests/test_agent_runtime.py members/writer/backend/tests/test_tool_contracts.py members/writer/backend/tests/test_writer_core_kernel_adapter.py members/writer/backend/tests/test_writer_service.py -q` -> 252 passed, existing Windows asyncio closed-pipe warnings.
- `py -3.14 -m pytest core/tests -q` -> 512 passed.
- `py -3.14 -m py_compile ...` on changed Python files -> passed.
- `git diff --check` -> passed, with Git CRLF conversion warnings only.
