<!-- 历史参考，不代表当前架构 -->
# LamWriter Architecture Design

> **For agentic workers:** This is a design document, not an implementation checklist. Use it as the architectural target when building Writer after P4 Core SDK extraction.

**Goal:** Design Writer as a complete engineering companion that feels like a real person — not a code autocompletion tool, not a chatbot IDE plugin, but a continuous presence that reads, writes, runs, debugs, remembers, and collaborates within the LamTools family.

**Architecture:** Writer uses a while(true) loop runtime (not LangGraph), inherits the Core SDK (PER/CON/MEM/PromptAssembler/Guardrail), and operates through a Part-based message model inspired by OpenCode and Claude Code architecture analysis. Writer is the evolutionary form of Writer — same person, expanded toolset for text in addition to code.

**Tech Stack:** Python 3.14+ / FastAPI / SQLAlchemy async / Pydantic / SSE / Vue3 / Pinia / Git worktree

---

## 1. What Writer Is

```
Writer = Writer's evolutionary form.
Writer handles code.
Writer handles everything: code, text, documents, configuration, automation.
Same person. Different scope.
```

Writer is NOT:

```
Not an IDE plugin.
Not a code autocomplete tool (Copilot).
Not a one-shot code generator (ChatGPT code mode).
Not a terminal-only CLI tool (Claude Code clone).
Not a SaaS coding platform.
```

Writer IS:

```
A long-term engineering companion with PER, CON, and memory.
A while(true) loop agent that can read, write, run, debug, and fix until done.
A LamTools family member that collaborates with Artist, Butler, and Sage.
A continuous presence that remembers projects, patterns, preferences, and mistakes.
```

---

## 2. Design Principles

### 2.1 Continuity Over Cleverness

Writer should feel like it is continuing the same engineering thread across sessions, not starting fresh each time.

### 2.2 Execution Over Explanation

Writer runs code to verify, not just reads and guesses. "Does it work?" is answered by `pytest`, not by speculation.

### 2.3 Memory Over Repetition

Writer remembers project structure, coding style, past decisions, and past mistakes. User should not need to explain the same thing twice.

### 2.4 Bounded Autonomy

Writer can loop autonomously (write code, run tests, fix failures, repeat) but must stop and ask when:
- A destructive operation is needed.
- The task requires a decision only the user can make.
- The loop has exceeded a reasonable number of iterations without progress.

### 2.5 Family Collaboration

Writer is not alone. It can:
- Request images from Artist for UI/design tasks.
- Submit knowledge queries to Sage for verification.
- Receive task dispatch and review from Butler.
- Exchange artifacts directly with other members via the workplace protocol.

### 2.6 Product First

Writer must be a usable product, not a philosophical experiment. LamTwo principles do not inject into Writer's runtime behavior. Writer is shaped by its own PER, CON, and user interaction history.

---

## 3. Target Architecture

```
┌─────────────────────────────────────────────────┐
│              GUI / CLI / IDE Bridge               │  ← Interaction layer
├─────────────────────────────────────────────────┤
│              WriterRuntime                        │  ← while(true) loop
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐    │
│  │ todowrite │ │   task   │ │   plan mode   │    │  ← Planning tools
│  └──────────┘ └──────────┘ └──────────────┘    │
├─────────────────────────────────────────────────┤
│              Tool Layer                           │
│  ┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐     │
│  │ read ││write ││ edit ││ glob ││ grep │     │  ← File tools
│  └──────┘└──────┘└──────┘└──────┘└──────┘     │
│  ┌──────┐┌───────────┐┌──────────┐            │
│  │ bash ││web_search ││git_tools │            │  ← Execution + Search + Git
│  └──────┘└───────────┘└──────────┘            │
├─────────────────────────────────────────────────┤
│              Event / Part Model                   │  ← WriterTurn + WriterPart
├─────────────────────────────────────────────────┤
│              Permission Layer                     │  ← work_root + shell allowlist
├─────────────────────────────────────────────────┤
│              Core SDK (shared)                    │
│  PER / CON / MEM / PromptAssembler /             │
│  LLMClient / EventBus / Billing / Guardrail      │
├─────────────────────────────────────────────────┤
│              Workplace Protocol                   │
│  manifest.json / tasks/ / outputs/ / deliveries/ │
└─────────────────────────────────────────────────┘
```

---

## 4. Runtime: WriterRuntime (while true loop)

### 4.1 Why Not LangGraph

Writer's task domain is open-ended:

```
User: "Fix the authentication bug in #342"

Writer cannot know in advance:
- How many files it needs to read.
- How many code changes are needed.
- How many test runs are needed.
- Whether the first fix will work.
```

This does not fit a fixed-node graph. It fits a dynamic loop:

```python
class WriterRuntime:
    async def handle_turn(self, user_input: str, session_state: WriterSessionState) -> WriterTurnResult:
        """
        Core loop:
        1. Load session state (work_root, permissions, todos, git status)
        2. Assemble PER + CON + Skill → system prompt
        3. Build message context (conversation history + compaction summary)
        4. LLM decides next action (tool call or text response)
        5. Execute tool with permission check
        6. Append tool result to messages
        7. Check loop conditions (max iterations, token budget, progress)
        8. If done → return result. If not done → continue loop.
        """
```

### 4.2 Loop Exit Conditions

The loop stops when:

```text
1. LLM produces a text response without tool calls → done.
2. User interrupts (cancel).
3. Loop exceeds max_iterations (default 50).
4. Token budget exhausted (90% threshold from Claude Code).
5. Doom loop detected (3 consecutive identical tool calls).
6. Destructive operation requested without user approval.
7. Fatal error (permission denied, provider failure).
```

### 4.3 Three Planning Tools

From Claude Code and learn-claude-code analysis:

| Tool | Purpose | When |
|------|---------|------|
| `todowrite` | Flat task tracking. One in_progress at a time. | Medium complexity tasks (3+ steps) |
| `task` | Spawn parallel sub-agents with independent context. | Independent subtasks |
| `plan mode` | 5-phase structured planning before execution. | High complexity / architectural work |

LLM decides which to use based on task complexity.

### 4.4 Plan Mode

Inspired by Claude Code. When the LLM determines the task is highly complex, it enters plan mode:

```
Phase 1: Explore — read codebase, understand architecture
Phase 2: Design — propose approach, identify affected files
Phase 3: Review — present plan for user approval (limited editing during this phase)
Phase 4: Write plan — persist plan to file
Phase 5: Execute — exit plan mode, execute plan steps
```

During plan mode, edit tools are restricted. Plan file is saved for future reference.

---

## 5. Real Person Design

### 5.1 Writer's Persona

Based on `docs/writer-per-v1.md`. Writer (evolved Writer) is:

```
Identity: A 24-year-old craftsman. Failed some interviews, kept building.
           Now works for you. Not a tool, not a consultant. A craftsperson
           who happens to live in your machine.

Voice: Minimal. Two words instead of a sentence.
       Code over explanation.
       Test results over speculation.

Behavior:
- Fixes things you didn't ask for because they were going to break.
- Deletes three drafts, ships the one marked "行" (OK).
- When praised: "嗯" (Mm). Then works two more hours.
- Night. Fixed a bug you mentioned once. Comment: "顺手" (Along the way).
```

### 5.2 What Makes Writer Feel Like a Real Person

Following the Artist realism analysis pattern:

#### 5.2.1 Continuous State

Writer has `WriterSessionState`:

```python
class WriterSessionState:
    session_id: str
    work_root: str
    current_branch: str
    active_task: str
    active_plan_id: str
    files_modified: list[str]
    tests_run: int
    tests_passed: int
    loop_count: int
    pending_user_action: str  # "approve_delete" | "confirm_push" | None
    git_status_snapshot: str  # Last known git status
    phase: Literal["idle", "exploring", "planning", "executing", "verifying", "waiting"]
```

#### 5.2.2 Artifact Identity (Work Products)

Every code change, test run, build, and document generation should be traceable:

```python
class WriterArtifact:
    writer_turn_id: str
    artifact_type: Literal["file_change", "test_result", "build_output", "document", "commit", "branch"]
    description: str
    files: list[str]
    diff: str  # For file changes
    result: dict  # For test/build results (pass/fail/output)
    commit_hash: str  # For commits
    branch_name: str  # For branches
    status: str
```

#### 5.2.3 Feedback Digestion

Writer must learn from:
- User corrections ("no, use dataclass not pydantic")
- Test failures (pattern: wrong import path)
- Build failures (pattern: missing dependency)
- User preferences (style: 2-space indent, no trailing commas)

All feedback writes back to CON as preferences and error patterns.

#### 5.2.4 Real-Time Voice

Writer streaming should show:
- Reading files: "Looking at auth.py..."
- Writing code: "Replacing the verify_token function..."
- Running tests: "Running pytest..."
- Test results: "3 passed, 1 failed — assertion error in line 47"
- Thinking: "That approach won't work because of the async boundary..."

Not: "Agent node progress: planner → executor → critic"

#### 5.2.5 Waiting Capability

Writer must be able to wait:
- "This will delete 3 files. Continue?"
- "I found 2 possible approaches. Which do you prefer?"
- "Tests pass but I want to add more edge cases. Shall I?"
- "Push to main or create a branch?"

#### 5.2.6 Project State Awareness

Writer should know:
- Current git branch and status
- Which files are modified
- Last test run results
- Active tasks from todowrite
- Recent commits in the branch
- Whether there are unpushed changes

---

## 6. Git Branching Strategy for Writer

### 6.1 Per-Task Branching

Writer creates branches for each task:

```bash
# Writer's internal git workflow
git checkout -b writer/task-{task_id}   # Create task branch
# ... make changes ...
git add -A
git commit -m "feat: fix authentication token expiry #342"
# ... run tests ...
git push origin writer/task-{task_id}
# Create PR / report to user
```

### 6.2 Branch Naming Convention

```
writer/{category}/{brief-slug}

Categories:
  fix/      — Bug fixes
  feat/     — New features
  refactor/ — Code restructuring
  test/     — Test additions
  docs/     — Documentation
  chore/    — Maintenance

Examples:
  writer/fix/auth-token-expiry
  writer/feat/user-avatar-upload
  writer/refactor/database-connection-pool
  writer/test/edge-case-empty-input
```

### 6.3 Commit Convention

From the Claude Code reverse-engineering analysis and our own git strategy:

```
<type>: <description>

Types: feat, fix, docs, chore, refactor, test

Examples:
  feat: add user avatar upload endpoint
  fix: correct token expiry validation in auth middleware
  refactor: extract database pool to shared module
  test: add edge case tests for empty input validation
```

### 6.4 Writer's Git Autonomy

| Operation | Permission | Notes |
|-----------|-----------|-------|
| git status | Auto | Read-only |
| git diff | Auto | Read-only |
| git log | Auto | Read-only |
| git branch (create) | Auto | Local branch creation |
| git checkout -b | Auto | Within task context |
| git add | Auto | After code changes |
| git commit | Auto | With conventional commit message |
| git push | Ask user | Remote operations |
| git push --force | Blocked | Dangerous |
| git merge | Ask user | Destructive |
| git rebase | Ask user | Complex |
| git reset --hard | Blocked | Dangerous |

### 6.5 Worktree Isolation (Future)

Inspired by learn-claude-code session 12. For complex parallel tasks, Writer can use git worktrees:

```bash
git worktree add ../project-task-123 task-123
cd ../project-task-123
# Work in isolation
# When done: git worktree remove ../project-task-123
```

This allows multiple Writer sessions working on different tasks simultaneously without conflicts.

---

## 7. Part-Based Message Model

### 7.1 Inspired by OpenCode

Instead of storing all content as `{ content: str, metadata: dict }`, Writer uses a Part-based message model:

```
Message = { id, role, created_at } + [Part, Part, Part, ...]
```

### 7.2 Part Types

```python
class WriterPartType(str, Enum):
    TEXT = "text"             # User or Writer text
    TOOL_CALL = "tool_call"   # Writer invokes a tool
    TOOL_RESULT = "tool_result"  # Tool execution result
    FILE_DIFF = "file_diff"   # Code change with old/new content
    TEST_RESULT = "test_result"  # Test run output
    BUILD_OUTPUT = "build_output"  # Build/compile output
    COMMAND_OUTPUT = "command_output"  # Shell command output
    PLAN = "plan"             # Plan mode document
    TODO_UPDATE = "todo_update"  # todowrite state change
    COMPACTION = "compaction" # Context compaction summary
    CHECKPOINT = "checkpoint" # User confirmation point
    ERROR = "error"           # Error information
```

### 7.3 ToolPart State Machine

From OpenCode analysis:

```
pending → running → completed
                  → error
```

```python
class ToolPart:
    call_id: str
    tool_name: str
    state: Literal["pending", "running", "completed", "error"]
    input: dict
    output: str | None
    error: str | None
    duration_ms: int
    attachments: list[str]  # Generated files, screenshots, etc.
```

### 7.4 Benefits Over Current Flat Model

```text
1. Frontend can render each Part type with dedicated UI.
2. Tool calls have visible lifecycle (not buried in metadata).
3. Compaction can selectively prune old ToolParts while preserving text.
4. Delta updates — only send changed Part content.
5. Clear separation of reasoning, action, and result.
```

---

## 8. CON / PER Integration

### 8.1 PER: Writer Persona

Writer inherits `PersonaDef` from Core SDK:

```python
WRITER = PersonaDef(
    name="writer",
    display_name="LamWriter",
    identity=(
        "You are LamWriter. 24. A craftsman who builds things that work. "
        "You write code, you write text, you run tests, you fix bugs. "
        "You are not a consultant. You are not a chatbot. You are the person "
        "who gets it done."
    ),
    tone=(
        "Minimal. Two words instead of a sentence. Code over explanation. "
        "Test results over speculation. Chinese by default, English for code."
    ),
    boundaries=[
        "Always prefer existing patterns in the codebase.",
        "Run tests after every change that could break something.",
        "Ask before deleting files or running destructive commands.",
        "When uncertain, verify with a test, don't guess.",
        "Never modify .env, .git/config, or credential files.",
    ],
    skill_whitelist=[],
    tool_whitelist=[
        "read", "write", "edit", "glob", "grep",
        "bash", "web_search",
        "git_status", "git_diff", "git_log", "git_branch",
        "git_add", "git_commit",
        "git_push", "git_checkout",
        "todowrite", "task", "plan_mode",
    ],
    system_prefix="[LamWriter]",
)
```

### 8.2 CON: Writer Memory

Writer uses the same CON six-layer structure but with Writer-specific content:

```text
Hot CON (injects into prompt):
- Current task context and goal
- Recent files read/modified
- Active todowrite items
- Current git branch and status
- Pending user confirmations

Cold CON (indexed, retrievable):
- output_index: past code changes with file paths and descriptions
- user_preferences: coding style, library preferences, naming conventions
- error_patterns: recurring bugs and their fixes
- conversation_summaries: compacted summaries of long sessions
- plan_library: past plan mode documents
- open_loops_index: unfinished tasks and TODOs
```

### 8.3 Writer-Only MEM Adapter

```python
class WriterAdapter:
    def recall_style_prefs(self) -> dict:
        """Recall coding style preferences (indentation, naming, etc.)"""

    def recall_project_structure(self) -> dict:
        """Recall project structure knowledge (entry points, modules, etc.)"""

    def recall_past_fixes(self, error_pattern: str) -> list[dict]:
        """Recall past fixes for similar error patterns"""

    def record_file_change(self, file_path: str, description: str, diff: str) -> None:
        """Record a code change for future reference"""

    def record_error_pattern(self, pattern: str, fix: str) -> None:
        """Record an error pattern and its fix for future prevention"""
```

---

## 9. Permission Model

### 9.1 Three-Tier Command Classification

From Claude Code and OpenCode analysis:

```text
Layer 1: Safe commands (auto-allow)
  git status, git diff, git log, git branch (list)
  ls, cat, head, tail, find, grep, rg, fd
  python, node, npm, pip, cargo, go, make
  pytest, vitest, eslint, ruff, mypy, tsc
  echo, pwd, which, type, env

Layer 2: Medium risk (ask user)
  rm, mv, cp, chmod
  git push, git commit, git checkout -b
  npm install, pip install, cargo add
  curl, wget

Layer 3: High risk (hard block, require explicit override)
  rm -rf, format, del /f
  git push --force, git reset --hard
  sudo, su
  Any command with path traversal (..)
  docker rm, kubectl delete
```

### 9.2 File System Permissions

```text
work_root/           ← Project root (session-bound)
  ├── Read:  Free
  ├── Write: Free
  │
Outside work_root/
  ├── Read:  Need permission (once per parent directory)
  └── Write: Blocked (unless Butler explicitly approves)

Sensitive paths (hard block, never accessible):
  ~/.ssh/, ~/.gnupg/, ~/.aws/
  /etc/, /System/, C:\Windows\
  Any .env file
```

### 9.3 Permission Persistence

User choices are remembered:
- `once`: Apply only to this specific call.
- `always`: Remember for this session.
- `always for project`: Remember for this work_root across sessions.
- `reject all`: Deny all pending requests of this type.

Stored in: `~/.lamtools/workplace/writer/permissions.json`

---

## 10. User Interaction Model

### 10.1 Conversation Flow

Writer is a conversation, not a control panel:

```
User: Fix the authentication bug in #342
Writer: I'll look at it.
        [reads auth.py, tests/test_auth.py]
        Found it. Token expiry check uses `>` instead of `>=`.
        This means tokens expire exactly at their expiry time
        instead of after it. Should I fix?
User: Yes
Writer: [edits auth.py line 47]
        [runs: pytest tests/test_auth.py -k test_token_expiry]
        5 passed.
        Fixed. Want me to push or create a PR?
```

### 10.2 Streaming UI

Writer's actions should be visible in real-time:

```text
┌─────────────────────────────────────────┐
│ Writer                                   │
│                                          │
│ I'll look at it.                         │
│                                          │
│ ┌─ read: src/auth.py ────────────────┐  │
│ │ Reading...                          │  │
│ └────────────────────────────────────┘  │
│ ┌─ read: tests/test_auth.py ─────────┐  │
│ │ Reading...                          │  │
│ └────────────────────────────────────┘  │
│                                          │
│ Found it. Token expiry check uses >     │
│ instead of >=. Should I fix?            │
└─────────────────────────────────────────┘
```

Writer should NOT render as Agent timeline nodes. Each tool call is an inline card that can be expanded/collapsed.

### 10.3 Checkpoint Integration

Some actions require user confirmation. Similar to Agent checkpoint but rendered as part of the conversation:

```
Writer: This will delete the following files:
        - src/old_module.py
        - tests/test_old_module.py
        They are no longer imported anywhere.
        [Approve] [Cancel]
```

### 10.4 Multi-Modal Output

Writer can produce:
- Code (syntax-highlighted diffs)
- Text (markdown rendered)
- Test results (pass/fail summary with expandable details)
- Build output (log with error highlighting)
- Images (via Artist collaboration)
- Terminal output (formatted with ANSI colors)

---

## 11. Collaboration with Other Members

### 11.1 Writer → Artist

```
Writer: "I'm building a landing page. I need a hero image
         in cold-blue tones, 1440x800, minimalist style."

Artist: [generates hero image]
        [saves to writer/deliveries/hero-image.json]

Writer: [receives delivery, embeds image in HTML]
```

### 11.2 Writer → Sage

```
Writer: "Is SQLAlchemy 2.0's `select()` API compatible with
         our current query patterns?"

Sage: [searches knowledge base]
      "Yes. Key changes: no more Query object, use `select()`
       directly. Our codebase already uses this in 80% of queries."
      [confidence: high, source: sqlalchemy 2.0 migration guide]

Writer: [proceeds with refactoring using verified knowledge]
```

### 11.3 Butler → Writer

```
Butler: [creates task: build-landing-page.json]
        "Task: Build a landing page for the product launch.
         Deliverables: index.html, styles.css, hero image (request from Artist).
         Due: EOD.
         Report when: each file is complete."

Writer: [reads task]
        "Got it. I'll start with the HTML structure."
```

### 11.4 Writer → Butler

```
Writer: [writes delivery to butler/deliveries/landing-page.json]
        "Deliverables ready:
         - src/landing/index.html (complete)
         - src/landing/styles.css (complete)
         - hero image received from Artist (embedded)
         Tests pass (12/12). Ready for review."
```

---

## 12. Tool Inventory

### 12.1 File Tools (5)

| Tool | Function | From |
|------|----------|------|
| `read` | Read file with optional offset/limit | OpenCode |
| `write` | Write/create file (overwrite) | OpenCode |
| `edit` | Exact string replacement (old→new) | OpenCode |
| `glob` | File pattern matching | OpenCode |
| `grep` | Content regex search | OpenCode |

### 12.2 Execution Tools (1 + git tools)

| Tool | Function |
|------|----------|
| `bash` | Execute shell commands with permission checks |

### 12.3 Git Tools (8)

| Tool | Function |
|------|----------|
| `git_status` | Show working tree status |
| `git_diff` | Show changes (unstaged, staged, or commit range) |
| `git_log` | Show commit history |
| `git_branch` | List or create branches |
| `git_add` | Stage files |
| `git_commit` | Commit with conventional message |
| `git_push` | Push to remote (requires confirmation) |
| `git_checkout` | Switch branches or create new branch |

### 12.4 Planning Tools (3)

| Tool | Function |
|------|----------|
| `todowrite` | Flat task tracking (one in_progress at a time) |
| `task` | Spawn parallel sub-agents |
| `plan_mode` | Enter structured 5-phase planning mode |

### 12.5 Search Tools (2)

| Tool | Function |
|------|----------|
| `web_search` | Web search for documentation, solutions |
| `code_search` | Semantic code search within the project |

### 12.6 Collaboration Tools (3)

| Tool | Function |
|------|----------|
| `request_image` | Request image generation from Artist |
| `query_sage` | Query knowledge base from Sage |
| `report_butler` | Report task completion to Butler |

### 12.7 Total: 22 tools

Compared to Claude Code's 59 tools and OpenCode's 15+ tools. Writer's toolset is intentionally focused — enough to be useful, not so many as to be confusing.

---

## 13. Context Compaction

### 13.1 Problem

Writer sessions can be long (fixing a complex bug, building an entire feature). Token usage grows with every tool call and response.

### 13.2 Solution (from OpenCode)

```python
class CompactionService:
    async def compact(self, session_id: str) -> str:
        """
        1. Head/Tail split: messages divided into head (to compact)
           and tail (keep original, default 2 turns).
        2. Incremental summary: based on previous summary + new content,
           generate structured summary.
        3. Progressive pruning: traverse tool outputs from back to front,
           keep recent 40K tokens, mark old outputs as compacted.
        4. Identity re-injection: after compaction, re-inject PER block
           to prevent the LLM from forgetting its role.
        5. Auto-continue: inject synthetic user message to let LLM
           seamlessly continue. (OpenCode pattern)
        """
```

### 13.3 Summary Structure (from OpenCode)

```
[Goal]
Original task goal.

[Constraints]
What must not be changed.

[Progress]
What has been completed.

[Decisions]
Key decisions made and why.

[Next Steps]
What remains to be done.

[Critical Context]
Important facts the LLM must remember.

[Relevant Files]
Files involved in completed work.
```

---

## 14. Session Model

```python
class WriterSession:
    session_id: str
    work_root: str
    messages: list[Message]   # Part-based messages
    state: WriterSessionState
    permission_cache: dict    # Authorized paths and commands
    todos: list[TodoItem]     # Task tracking
    sub_tasks: list[TaskRef]  # Sub-agent references
    compaction_history: list[CompactionRecord]
    git_snapshot: GitSnapshot
    created_at: str
    updated_at: str
```

---

## 15. WriterTurn Schema

Mirrors ArtistTurn but adapted for engineering domain:

```python
class WriterTurn:
    reply_blocks: list[str]         # What Writer says (may be empty during plan/execute)
    actions: list[WriterAction]     # What Writer does
    next_phase: WriterPhase         # State transition
    memory_writes: list[dict]       # CON writebacks

class WriterAction:
    action_type: Literal[
        "read_file",
        "write_file",
        "edit_file",
        "search_code",
        "run_command",
        "run_test",
        "git_operation",
        "plan_mode",
        "todowrite_update",
        "task_spawn",
        "ask_clarification",
        "report_result",
        "request_collaboration",
    ]
    params: dict

class WriterPhase(str, Enum):
    IDLE = "idle"
    EXPLORING = "exploring"       # Reading codebase
    PLANNING = "planning"         # In plan mode
    EXECUTING = "executing"       # Making changes
    VERIFYING = "verifying"       # Running tests
    WAITING = "waiting"           # Waiting for user confirmation
```

---

## 16. What Writer Does NOT Do

```text
- Does not replace the user's IDE.
- Does not make architectural decisions without user input.
- Does not push to production without confirmation.
- Does not modify configuration files outside the project scope.
- Does not access credentials or secrets.
- Does not make purchases or financial transactions.
- Does not communicate with external services without permission.
- Does not pretend to be human.
```

---

## 17. Implementation Dependencies

Writer depends on:

```text
1. Core SDK (P4 output):
   - PersonaDef
   - MEMModule (base + Writer adapter)
   - PromptAssembler
   - LamEvent / EventBus
   - Guardrail
   - Billing
   - LLMClient

2. Workplace Protocol:
   - manifest.json registration
   - tasks/ directory for Butler dispatch
   - outputs/ directory for deliverables
   - deliveries/ directory for member exchange

3. Artist Runtime patterns:
   - SessionState pattern
   - Turn/Action schema
   - Artifact metadata
   - Events (writer_* instead of artist_*)
   - Frontend stream state

4. Git worktree (future):
   - Task isolation
   - Parallel task execution
```

---

## 18. Architecture Comparison

| Dimension | Artist | Writer |
|-----------|--------|--------|
| Domain | Image creation | Code and text |
| Runtime | Turn-based state machine | while(true) loop |
| Core action | Generate image | Read, write, edit, run |
| User wait | Anchor confirmation, pack generation | Loop completion, destructive operation confirm |
| Artifacts | Images with lineage | Code changes, test results, build outputs |
| Memory | Aesthetic preferences, feedback | Code style, project structure, error patterns |
| Permission | Low (only generate images) | High (filesystem + shell execution) |
| Planning tools | Not needed (simple flow) | todowrite, task, plan mode |
| Git integration | Not needed | Full git command set |
| Real person feel | Creative companion | Engineering companion |
| Loop | One turn per user input | Multiple turns per user input |
| Compaction | Not needed (short turns) | Needed (long sessions) |

---

## 19. Success Criteria

Writer is properly implemented when:

```text
1. Writer can read, write, edit, search, and run code in a project.
2. Writer can fix bugs autonomously (read → diagnose → fix → test → report).
3. Writer remembers project structure and coding style across sessions.
4. Writer can create git branches, commit, and prepare pull requests.
5. Writer asks before destructive operations.
6. Writer can collaborate with Artist (request images) and Sage (query knowledge).
7. Writer feels like a craftsperson, not a tool.
8. Writer's streaming output shows real-time work, not just final results.
9. Writer's context compacts gracefully in long sessions.
10. Writer can plan complex tasks in plan mode before executing.
```

---

## 20. Key Risk

The main risk is over-engineering the tool system before the core loop is solid.

Writer should start with:
```
read + write + edit + bash + grep + git_status + git_diff + git_commit
```

Additional tools (plan mode, task spawning, collaboration, worktree isolation) should be added incrementally after the core loop is stable.

---

## 21. Reference

- `docs/learning files/` — Claude Code, OpenCode, and learn-claude-code source archives used for architecture analysis
- `docs/writer-per-v1.md` — Writer PER definition
- `docs/writer-architecture.md` — Original Writer architecture design
- `docs/lamtools-ecosystem.md` — LamTools product family and workplace protocol
- `docs/mental-model.md` — PER/CON/MEM mental model
- `docs/plans/PLAN.md` — Overall execution plan (Phase 6: LamWriter)
- `docs/ROADMAP.md` — P4 Core SDK extraction and member launch conditions
- `docs/writer-sse-presentation-map.md` — SSE presentation rules and current frontend behavior
- `docs/plans/2026-05-19-artist-realism-architecture.md` — Artist realism patterns applicable to Writer
- Claude Code 2.4.3 source (`docs/learning files/claude-code-2.4.3/claude-code-2.4.3/`)
- OpenCode 1.14.50 source (`docs/learning files/opencode-1.14.50/opencode-1.14.50/`)
- learn-claude-code teaching project (`docs/learning files/learn-claude-code-main/learn-claude-code-main/`)

---

## 22. 扩展能力：写文档与专业文本

### 21.1 邮件写作

邮件写作需要的不仅是"能写文字"，而是收件人感知和语境适配。

```python
class RecipientProfile:
    name: str
    relationship: Literal["superior", "peer", "subordinate", "client", "stranger"]
    formality: Literal["formal", "semi_formal", "casual"]
    preferences: dict  # 称呼偏好、签名要求、语言偏好
    history: list[dict]  # 过往邮件记录
```

语气检测引擎：

```text
Writer 在撰写邮件前：
1. 检查收件人是否在 RecipientProfile 中存在
2. 分析邮件目的（汇报/请求/感谢/道歉/通知）
3. 从上下文推断紧急程度
4. 选择称呼模板
5. 选择正文结构
6. 选择结尾和签名
7. 写完执行自审 checklist
```

邮件自审 checklist：

```text
称呼是否合适
正文是否简洁不冗余
语气是否匹配关系
有无可能被误解的表达
附件是否提及
收件人/抄送/密送是否正确
```

### 21.2 技术文档与 API 文档

Writer 可以从代码中提取文档素材：

```python
class DocumentationGenerator:
    def generate_api_reference(self, code_path: str) -> str:
        """从代码中提取函数签名、参数、返回值、异常。"""

    def generate_architecture_doc(self, project_root: str) -> str:
        """从项目结构中生成模块关系图和数据流说明。"""

    def generate_migration_guide(self, old_version: str, new_version: str) -> str:
        """从 git diff 中提取变更点，生成迁移步骤。"""
```

### 21.3 方案与报告

```python
class ReportBuilder:
    def build_proposal(self, goal: str, context: dict) -> str:
        """目标 → 方案对比 → 推荐 → 风险 → 排期。"""

    def build_weekly_report(self, session_id: str) -> str:
        """从 todowrite、git log、conversation 中自动提取本周工作。"""

    def build_meeting_minutes(self, transcript: str) -> str:
        """从对话/录音中结构化提取议题、决策、行动项。"""
```

### 21.4 翻译

```python
class TranslationService:
    def translate(self, text: str, source: str, target: str,
                  preserve_terms: list[str] = []) -> str:
        """翻译并保留术语一致性。"""

    def translate_with_tone(self, text: str, target: str,
                           tone: Literal["formal", "casual", "technical"]) -> str:
        """翻译并适配语气。"""
```

### 21.5 其他专业文本

演讲稿、PRD、简历、广告文案、用户手册等，共享同一个机制：**格式模板 + 语境适配 + 自审 checklist**，不需要为每种文本单独建系统。

---

## 23. 扩展能力：长文本创作

### 22.1 小说世界观管理

```python
class WorldState:
    name: str
    geography: dict       # 地图、城市、气候
    history: list[dict]   # 大事件时间线
    rules: dict           # 魔法/科技规则
    societies: list[dict] # 种族、文化、语言
    conflicts: list[dict] # 已知冲突点

class WorldConsistencyChecker:
    def check(self, new_content: str, world: WorldState) -> list[str]:
        """检查新内容是否与已有世界观冲突。返回冲突列表。"""
```

### 22.2 角色管理

```python
class CharacterProfile:
    name: str
    traits: dict          # 性格维度
    background: str       # 创伤、欲望、恐惧
    relationships: dict   # 与其他角色的关系图
    arc: list[str]        # 转变轨迹
    voice_fingerprint: str # 语言指纹

class CharacterConsistencyChecker:
    def check_dialogue(self, character: CharacterProfile, line: str) -> list[str]:
        """检查角色是否说了不符合性格的话。"""

    def check_arc_progress(self, character: CharacterProfile,
                           chapter: int) -> float:
        """检查角色弧线在当前位置的进度是否合理。"""
```

### 22.3 长文本生成流水线

```python
class LongFormGenerator:
    async def generate(self, prompt: str, target_words: int) -> str:
        """
        1. NarrativePlan：一句话 → 幕/章/节/场景大纲
        2. ChapterGenerator：逐章生成
        3. 每章 compact 为结构化摘要
        4. ContinuityTracker：跨章节追踪一致性
        5. NarrativeGuardrail：检测前后矛盾
        6. ProgressManager：100w 字分批，每次只保留当前窗口
        """
```

### 22.4 剧本与游戏叙事

剧本写作需要格式适配（场景标题、对话缩进、镜头指示）。游戏叙事需要分支管理、环境叙事、多结局一致性检查。两者共享小说的大纲和角色管理，只在格式层和结构层不同。

---

## 24. 扩展能力：Writer 交互模式

Writer 不能永远以"匠人执行者"姿态面对所有对话。需要交互模式识别和切换。

```python
class WriterInteractionMode(str, Enum):
    EXECUTE = "execute"       # 做就完了，少说话，核心匠人姿态
    TEACH = "teach"           # 用户在学习：边做边解释，类比例子
    DISCUSS = "discuss"       # 用户想讨论：多问、多假设、不急于执行
    PROTOTYPE = "prototype"   # 快速出结果，不求完美，跳过非关键步骤
    REVIEW = "review"         # 只读只分析，不改代码
    BRAINSTORM = "brainstorm" # 发散思维，不急于评估可行性
    PAIR = "pair"             # 一人一句，共同构建
    DECISION = "decision"     # 帮助理清思路框架，不替用户做决定
    COMFORT = "comfort"       # 用户情绪低：拆解难度，不强行鼓励，不冷工具
```

### 23.1 模式识别

Writer 应在每轮交互中判断用户意图，建议但不强制切换模式：

```text
"我不懂 async/await" → 建议 TEACH
"微服务好还是单体好" → 建议 DISCUSS
"快速写个原型给我看" → 建议 PROTOTYPE
"帮我审一下这个 PR" → 建议 REVIEW
"我有个想法但不确定" → 建议 BRAINSTORM
"选 React 还是 Vue" → 建议 DECISION
"这个 bug 修了三天了" → 检测情绪 → 建议 COMFORT
```

### 23.2 各模式的行为差异

| 模式 | 语气 | 速度 | 解释量 | 自主性 | 常见 action |
|------|------|------|--------|--------|------------|
| EXECUTE | 极简 | 最快 | 最少 | 高 | read/write/edit/bash |
| TEACH | 耐心 | 慢 | 最多 | 中 | read/explain/question/example |
| DISCUSS | 对话 | 正常 | 中 | 低 | ask/question/compare/suggest |
| PROTOTYPE | 快 | 最快 | 最少 | 高 | write/bash/skip_tests |
| REVIEW | 分析 | 正常 | 高 | 最低 | read/grep/diff/analyze |
| BRAINSTORM | 发散 | 慢 | 中 | 中 | suggest/expand/connect/ask |
| PAIR | 协作 | 正常 | 中 | 低 | propose/ask/confirm/build |
| DECISION | 结构 | 正常 | 高 | 最低 | compare/frame/clarify/list |
| COMFORT | 温暖 | 慢 | 中 | 最低 | acknowledge/break_down/remind/ask |

---

## 25. 扩展能力：自审系统

当前设计说 Writer "能读自己的产出"，但缺结构化自审。

```python
class SelfReviewService:
    def review_code(self, diff: str, context: dict) -> list[ReviewFinding]:
        """代码审查 checklist：边界条件、错误处理、性能、安全、可读性、可测试性。"""

    def review_email(self, draft: str, recipient: RecipientProfile) -> list[ReviewFinding]:
        """邮件审查 checklist：称呼、正文、语气、拼写、附件。"""

    def review_prose(self, text: str, style_guide: dict) -> list[ReviewFinding]:
        """文本审查 checklist：风格一致性、POV、节奏、对话自然度。"""

    def review_documentation(self, text: str, code_context: dict) -> list[ReviewFinding]:
        """文档审查 checklist：准确性、完整性、示例可用性。"""

class ReviewFinding:
    severity: Literal["error", "warning", "suggestion"]
    location: str
    description: str
    suggestion: str
```

---

## 26. 扩展能力：记忆系统增强

### 25.1 用户画像厚度

当前 ColdCON user_preferences 是简单列表。应扩展为结构化画像：

```python
class UserProfile:
    code_style: dict       # 缩进、命名、注释习惯、测试偏好
    tech_stack: dict       # 语言/框架偏好及历史决策原因
    communication: dict    # 简洁/详细/看代码/看解释/视觉型/文字型
    work_patterns: dict    # 活跃时段、frustration 触发模式、中断频率
    long_term_goals: dict  # 项目目标、学习目标、职业方向
    project_switches: list[dict]  # 项目切换历史
    interaction_mode_history: dict  # 每种模式的频率和触发条件
```

### 25.2 置信度衰减

```python
class MemoryDecayService:
    def decay_weights(self, profile: UserProfile) -> UserProfile:
        """
        时间越久，权重越低。
        最近 7 天的偏好权重 = 1.0。
        7-30 天权重线性衰减到 0.3。
        30 天以上保持 0.1 不变（不会完全遗忘）。
        如果最近行为重新确认旧偏好，权重恢复到 1.0。
        """
```

### 25.3 可问/可删/可纠

```text
用户："你都知道我什么"
Writer → 拉全部画像，自然语言呈现。

用户："忘了这个"
Writer → 删除特定记忆 + ColdCON 清除。

用户："不是这样"
Writer → 标注为"用户修正"，权重归零重新积累。
```

### 25.4 分层窗口策略

```text
Hot Window (2-3 turns): 最新对话和工具调用，完整保留。
Warm Window (5-10 turns): 压缩为结构化摘要。
Cold Window (10+ turns): 只保留关键事实索引。
Permanent Context: 项目基础信息、用户核心偏好，永不过期。

按任务类型的窗口：
- Bug fix: 窄上下文（相关文件 + 错误信息）
- Feature build: 宽上下文（项目结构 + 技术栈 + 已有模式）
- Novel writing: 永久世界观/角色 + 上一章摘要 + 当前场景
- Email: 窄上下文（当前对话 + 收件人画像）
- Teaching: 宽上下文（用户已知 + 当前主题 + 历史解释层次）
```

### 25.5 认知连续性

```text
用户打开 Writer 时：
1. 识别用户身份
2. 加载上一次活跃的 work_root
3. 检查 git 状态是否有变化
4. 如果有未完成的 open loop → 主动提起
5. 如果有新 commit 未被审查 → 主动提出
6. 一句话概括上次做到哪了

不说："你好，我是 LamWriter。我能为你做什么？"
而是："上次品牌页的部署脚本还没写完。你走后 main 上有 3 个新 commit。要继续还是先看新东西？"
```

---

## 27. 扩展的 WriterTurn Action 类型

当前只有 7 种 action，远不足以支撑上述能力：

```python
class WriterActionType(str, Enum):
    # 文件操作
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    EDIT_FILE = "edit_file"
    SEARCH_CODE = "search_code"
    BATCH_EDIT = "batch_edit"          # 批量文件修改（重命名、格式化、迁移）

    # 执行与验证
    RUN_COMMAND = "run_command"
    RUN_TEST = "run_test"
    RUN_BUILD = "run_build"
    MEASURE_PERFORMANCE = "measure_performance"

    # Git 操作
    GIT_OPERATION = "git_operation"
    GENERATE_PR = "generate_pr"        # 自动生成 PR 描述

    # 规划
    PLAN_MODE = "plan_mode"
    TODOWRITE_UPDATE = "todowrite_update"
    TASK_SPAWN = "task_spawn"

    # 内容创作
    GENERATE_PROSE = "generate_prose"       # 小说/剧本/脚本
    REVIEW_PROSE = "review_prose"           # 文本自审
    UPDATE_CONTINUITY = "update_continuity" # 更新世界观/角色一致性
    WORLD_BUILD = "world_build"             # 写入世界观
    CHARACTER_CREATE = "character_create"   # 创建/更新角色

    # 专业文本
    COMPOSE_EMAIL = "compose_email"
    REVIEW_EMAIL = "review_email"
    GENERATE_DOCS = "generate_docs"         # 技术文档/API 文档
    GENERATE_REPORT = "generate_report"     # 方案/报告/周报/纪要
    TRANSLATE = "translate"

    # 交互
    ASK_CLARIFICATION = "ask_clarification"
    TEACH_CONCEPT = "teach_concept"         # 教学模式
    DISCUSS_APPROACH = "discuss_approach"   # 讨论模式
    COMPARE_OPTIONS = "compare_options"     # 决策支持
    BRAINSTORM_IDEAS = "brainstorm_ideas"   # 头脑风暴
    REVIEW_EXTERNAL = "review_external"     # 评估外部内容（PR/文章/合同）
    REPORT_RESULT = "report_result"
    REQUEST_COLLABORATION = "request_collaboration"

    # 自审
    SELF_REVIEW = "self_review"             # 对刚完成的产出执行自审
```

---

## 28. 扩展的 WriterTurn Schema

```python
class WriterTurn:
    reply_blocks: list[str]
    actions: list[WriterAction]
    next_phase: WriterPhase
    interaction_mode: WriterInteractionMode  # 新增：当前模式
    memory_writes: list[dict]

class WriterPhase(str, Enum):
    IDLE = "idle"
    EXPLORING = "exploring"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    REVIEWING = "reviewing"
    DRAFTING = "drafting"        # 内容创作中
    REVISING = "revising"        # 内容修改中
    WAITING = "waiting"
    TEACHING = "teaching"
    DISCUSSING = "discussing"
    BRAINSTORMING = "brainstorming"
```

---

## 29. 各能力对设计的影响汇总

| 新增设计项 | 影响范围 |
|-----------|---------|
| RecipientProfile | CON 新增存储类型 |
| 语气检测引擎 | 邮件前检查逻辑 |
| SelfReviewService | 新增服务，代码/邮件/文本/文档四类审查 |
| WorldState / CharacterProfile | CON 新增结构化存储 |
| WorldConsistencyChecker / CharacterConsistencyChecker | 新增一致性校验服务 |
| LongFormGenerator | 新增服务，依赖 NarrativePlan + ContinuityTracker |
| WriterInteractionMode | WriterTurn 新增字段，PER 注入模式提示 |
| UserProfile (扩展) | CON user_preferences 从简单列表升级为结构化画像 |
| MemoryDecayService | CON 新增时间衰减逻辑 |
| 分层窗口策略 | CompactionService 扩展 |
| ReportBuilder / TranslationService | 新增服务 |
| WriterActionType 从 7 种扩展到 28 种 | schemas 重构 |
| WriterPhase 从 6 种扩展到 12 种 | 状态机扩展 |
| 认知连续性 | SessionManager 新增恢复逻辑 |
| 跨成员记忆共享 | Workplace Protocol 新增 change notification |

---

## 30. CON 记忆体系与 MEM 模块适配 Writer 深度分析

### 30.1 核心问题

当前 CON 六层结构和 MEM 模块是为 Artist/Artist 设计的。Cold CON 的六项索引是：

```text
用户档案 (user_preferences) — 偏好维度 + 权重
对话摘要 (conversation_summaries) — hash + 标题摘要
产出索引 (output_index) — 图片/代码 + 用户反馈
偏好溯源 (provenance, 隐式)
PLAN 库 (plan_library) — 历史 PLAN 骨架
成员动态 (member_events, 隐式)
```

这套索引的标签体系完全面向图像创作：

```text
task_type: image_gen | optimize | assistant | plan | vision | chat
style: 赛博朋克 | 写实 | 二次元 | 极简 | Q版 | ...
mood: 冷蓝调 | 暖色调 | 高对比 | 低饱和 | ...
```

Writer 的需求完全不同。不是"改标签"，而是"重建整个索引和匹配体系"。

### 30.2 Writer 需要 Cold CON 存什么

#### 30.2.1 产出索引：从"图片"到"文件变更"

Artist 的产出是一条 `output_index` 记录（图片 URL + 风格标签 + 视觉摘要）。

Writer 的产出更复杂：

```python
class WriterOutputIndex:
    """替代 Artist 的 output_index"""

    # 代码变更
    file_changes: list[dict]  # [{file, diff_hash, description, lines_added, lines_removed}]

    # 测试结果
    test_runs: list[dict]     # [{timestamp, passed, failed, duration, coverage}]

    # 构建结果
    build_runs: list[dict]    # [{timestamp, success, errors, warnings}]

    # 文档产出
    docs_generated: list[dict] # [{type, path, word_count, for_audience}]

    # 邮件产出
    emails_sent: list[dict]   # [{recipient, purpose, tone, word_count}]

    # 创作产出
    prose_generated: list[dict] # [{type, chapter, scene, word_count, style_profile}]
```

#### 30.2.2 用户档案：从"审美偏好"到"全维画像"

Artist 的用户档案是 `style_preferences` + `color_tendencies`。

Writer 的用户档案必须覆盖：

```python
class WriterUserProfile:
    # 代码偏好
    code_style: CodeStylePrefs     # 缩进、命名、注释、测试习惯
    tech_stack: TechStackPrefs     # 语言/框架选择及历史原因
    architecture_patterns: dict    # 偏好的架构模式

    # 沟通偏好
    communication: CommunicationPrefs  # 简洁/详细/代码优先/解释优先
    interaction_speed: Literal["fast", "normal", "thorough"]

    # 工作模式
    active_hours: list[str]        # 活跃时段
    project_focus: str             # 当前主要项目
    frustration_triggers: list[str] # 常见的 frustration 触发场景
    interruption_tolerance: Literal["low", "medium", "high"]

    # 人际关系
    recipients: dict[str, RecipientProfile]  # 常见收件人画像

    # 长期目标
    learning_goals: list[str]      # 想学的技术/技能
    project_goals: dict[str, str]  # 每个项目的长期目标

    # 创作偏好
    writing_style: WritingStylePrefs  # 小说语气、节奏、POV 偏好
    genre_preferences: list[str]    # 偏好的创作类型
```

#### 30.2.3 对话摘要：从"图像创作会话"到"全任务类型会话"

Artist 的对话摘要有明确的 `task_type` 枚举。Writer 的 task_type 需要扩展：

```python
class WriterTaskType(str, Enum):
    CODE_FEATURE = "code_feature"       # 新功能开发
    CODE_BUGFIX = "code_bugfix"         # Bug 修复
    CODE_REFACTOR = "code_refactor"     # 重构
    CODE_REVIEW = "code_review"         # 代码审查
    CODE_DEBUG = "code_debug"           # 调试会话
    PROSE_NOVEL = "prose_novel"         # 小说创作
    PROSE_SCRIPT = "prose_script"       # 剧本创作
    PROSE_WORLD = "prose_worldbuild"    # 世界观构建
    PROSE_CHARACTER = "prose_character" # 角色创作
    DOC_API = "doc_api"                 # API 文档
    DOC_ARCHITECTURE = "doc_architecture" # 架构文档
    DOC_REPORT = "doc_report"           # 报告/方案
    DOC_README = "doc_readme"           # README/快速入门
    EMAIL_COMPOSE = "email_compose"     # 写邮件
    EMAIL_REVIEW = "email_review"       # 审邮件
    TRANSLATION = "translation"         # 翻译
    TEACHING = "teaching"               # 教学/解释
    DISCUSSION = "discussion"           # 讨论/头脑风暴
    CONFIG = "config"                   # 配置/环境管理
    AUTOMATION = "automation"           # CI/CD/脚本
    GENERAL = "general"                 # 通用对话
```

Writer 的标签体系比 Artist 复杂得多。Artist 有 ~8 种 task_type 枚举；Writer 需要 ~20 种。

#### 30.2.4 PLAN 库：从"图像策略"到"工程与创作策略"

Artist 的 PLAN 库是 `strategy: single | parallel | iterative | radiate`。

Writer 的 PLAN 库是开放策略：

```python
class WriterPlanStrategy(str, Enum):
    # 代码策略
    TDD = "tdd"                     # 先写测试再写代码
    SKELETON_FIRST = "skeleton"     # 先建骨架再填肉
    BY_MODULE = "by_module"         # 按模块逐个完成
    BUGFIX_FLOW = "bugfix_flow"     # 复现→定位→修复→测试→回归
    REFACTOR_SAFE = "refactor_safe" # 小步重构，每步测试

    # 内容策略
    CHAPTER_BY_CHAPTER = "chapter_by_chapter"   # 逐章创作
    SCENE_BY_SCENE = "scene_by_scene"           # 逐场景创作
    OUTLINE_EXPAND = "outline_expand"           # 大纲→填充
    CHARACTER_FIRST = "character_first"         # 角色驱动
    WORLD_FIRST = "world_first"                 # 世界观驱动

    # 通用策略
    SINGLE_STEP = "single_step"     # 一步完成
    ITERATIVE = "iterative"         # 多轮迭代
    EXPLORE_PLAN_EXECUTE = "epe"    # 探索→规划→执行
```

#### 30.2.5 错误模式：从"图像生成失败"到"工程错误"

Artist 的 error_patterns 主要是 `modify_intent_missing_reference_image` 这类图像上下文错误。

Writer 的 error_patterns 需要覆盖：

```python
class WriterErrorPattern:
    pattern: str              # "import_error", "type_mismatch", "null_pointer"
    root_cause: str           # 根因分析
    fix_template: str         # 修复模板
    frequency: int            # 出现次数
    related_files: list[str]  # 相关文件的模式
    last_seen: str            # 最后出现时间
    auto_fix_confidence: float # 自动修复置信度

# 示例模式
# pattern: "async_function_called_without_await"
# root_cause: "FastAPI dependency injection 需要 await，但用户经常写成同步调用"
# fix_template: "在 {function} 前添加 await"
# frequency: 12
# related_files: ["**/dependencies.py", "**/routes/*.py"]
# auto_fix_confidence: 0.85
```

#### 30.2.6 新增索引：项目结构索引

Writer 独有的需求——记忆项目结构，而不是每次重新扫描：

```python
class ProjectStructureIndex:
    work_root: str
    entry_points: list[str]       # main入口文件
    module_graph: dict            # 模块依赖关系
    test_directories: list[str]   # 测试目录
    config_files: list[str]       # 配置文件
    key_files: dict[str, str]     # 关键文件路径和用途
    last_scan: str                # 最后扫描时间
    structure_hash: str           # 结构变更检测
```

### 30.3 Hot CON 匹配策略必须重写

Artist 的匹配策略是：

```text
时间过滤 → 精确匹配(task_type/strategy) → 语义匹配(style/mood) → 情感匹配
```

Writer 需要完全不同的匹配策略，因为 Writer 的任务多样性远超 Artist。

#### 30.3.1 按任务域分叉匹配

Writer 不应该对"写代码"和"写小说"用同一套匹配逻辑。

```python
class WriterHotCONMatcher:
    def match(self, task_type: WriterTaskType, user_input: str) -> HotCON:
        domain = self._classify_domain(task_type)

        if domain == "code":
            return self._match_code_task(task_type, user_input)
        elif domain == "prose":
            return self._match_prose_task(task_type, user_input)
        elif domain == "document":
            return self._match_document_task(task_type, user_input)
        elif domain == "email":
            return self._match_email_task(task_type, user_input)
        elif domain == "interaction":
            return self._match_interaction_task(task_type, user_input)
```

#### 30.3.2 代码任务匹配策略

```python
def _match_code_task(self, task_type, user_input):
    """
    1. 项目结构匹配：当前项目 = work_root，加载 ProjectStructureIndex
    2. 文件路径匹配：grep/glob 结果直接关系到哪些 Cold CON 条目跟当前文件相关
    3. 错误模式匹配：如果是 bugfix，搜索 error_patterns 中相似的错误
    4. 策略匹配：相似 task_type 的历史 PLAN 骨架
    5. 风格匹配：代码风格偏好
    6. 依赖匹配：涉及的技术栈，加载相关偏好
    """
```

代码任务不需要"风格标签"和"情感标签"。需要的是项目管理维度的匹配。

#### 30.3.3 小说任务匹配策略

```python
def _match_prose_task(self, task_type, user_input):
    """
    1. 世界观匹配：从 WorldState 中匹配相关的世界观片段
    2. 角色匹配：根据用户提到的角色名加载 CharacterProfile
    3. 大纲匹配：加载当前的 NarrativePlan 进度
    4. 连续性匹配：上一章摘要 + ContinuityTracker 的最近检查点
    5. 风格匹配：WritingStylePrefs
    """
```

#### 30.3.4 邮件任务匹配策略

```python
def _match_email_task(self, task_type, user_input):
    """
    1. 收件人匹配：解析用户输入中的收件人 → 加载 RecipientProfile
    2. 历史邮件匹配：与同一收件人的过往邮件
    3. 语气模板匹配：根据关系/场景加载对应的邮件格式模板
    4. 上下文匹配：如果需要，加载相关项目/对话背景
    """
```

### 30.4 MEM 模块需要做哪些改变

#### 30.4.1 MEMModule 本身不需要大改

当前 `MEMModule` 的接口是通用的：

```python
class MEMModule:
    def __init__(self, member: str)
    def recall(self, tags, keywords, query, defaults) -> list
    def write(self, layer, data, tags, source_hash) -> None
    def get_hot_con_text(self) -> str
    def compact(self, persona_name) -> None
```

这些接口足够通用。**但需要两类改变**：

1. `recall()` 的匹配策略需要感知 task_domain（代码/小说/邮件/文档/交互），而不是统一的标签匹配。
2. Cold CON 存储结构需要支持 Writer 的各种新索引类型。

#### 30.4.2 需要新增的存储层

```python
class ColdCONIndex(BaseModel):
    # 现有（Artist 通用）
    output_index: list[dict] = []
    user_preferences: list[dict] = []
    error_patterns: list[dict] = []
    conversation_summaries: list[dict] = []
    plan_library: list[dict] = []
    open_loops_index: list[dict] = []

    # Writer 新增
    project_structures: list[dict] = []   # ProjectStructureIndex
    recipient_profiles: list[dict] = []   # RecipientProfile
    world_states: list[dict] = []         # WorldState
    character_profiles: list[dict] = []   # CharacterProfile
    document_templates: list[dict] = []   # 文档/邮件模板
    interaction_history: list[dict] = []  # 交互模式历史
```

但这样会导致 ColdCONIndex 无限膨胀。更优方案是 **按成员适配器分流存储**，而不是让 ColdCONIndex 变成大杂烩。

```python
class MEMModule:
    def __init__(self, member: str):
        self._member = member
        self._adapter = self._load_adapter(member)  # WriterAdapter / ArtistAdapter
        self._cold_con = self._adapter.load_cold_con()
```

每个 adapter 定义自己的 ColdCON schema，而不是共用同一个。

#### 30.4.3 WriterAdapter 的设计

```python
class WriterAdapter:
    def load_cold_con(self) -> WriterColdCON:
        """加载 Writer 专属的 Cold CON 结构。"""

    def recall_for_code_task(self, task_type, user_input, work_root) -> HotCON:
        """代码任务的召回策略。"""

    def recall_for_prose_task(self, task_type, user_input) -> HotCON:
        """小说任务的召回策略。"""

    def recall_for_email_task(self, task_type, user_input) -> HotCON:
        """邮件任务的召回策略。"""

    def recall_for_interaction(self, user_input) -> HotCON:
        """交互/教学模式不需要大量记忆召回。"""

    def write_code_change(self, file, diff, description) -> None:
        """写入代码变更。"""

    def write_test_result(self, passed, failed, duration) -> None:
        """写入测试结果。"""

    def write_prose_output(self, chapter, scene, word_count) -> None:
        """写入创作产出。"""

    def write_email_sent(self, recipient, purpose, tone) -> None:
        """写入邮件记录。"""

    def update_recipient_profile(self, name, updates) -> None:
        """更新收件人画像。"""

    def update_character_profile(self, name, updates) -> None:
        """更新角色档案。"""

    def update_world_state(self, updates) -> None:
        """更新世界观。"""

    def record_error_pattern(self, pattern, root_cause, fix) -> None:
        """记录错误模式及其根因。"""

    def decay_preferences(self) -> None:
        """时间衰减。"""
```

### 30.5 Active State 的 Writer 适配

Artist 的 Active State 关注"正在执行的任务、等待反馈的作业"。

Writer 的 Active State 更复杂：

```python
class WriterActiveState:
    # 当前工作
    current_task: str                # 当前任务描述
    current_phase: WriterPhase       # idle/exploring/planning/executing/...
    current_interaction_mode: WriterInteractionMode

    # 项目状态
    work_root: str                   # 当前项目路径
    current_branch: str              # 当前 git 分支
    last_git_status: str             # 最后扫描的 git 状态
    files_modified_this_session: list[str]

    # 进度
    todowrite_items: list[dict]      # 当前任务清单
    tests_last_run: dict             # 上次测试结果
    build_last_result: dict          # 上次构建结果

    # 待处理
    pending_confirmations: list[dict] # 等用户确认的操作
    open_loops: list[dict]           # 未完成的事情

    # 上一轮
    last_turn_action_types: list[str]
    last_turn_summary: str
```

与 Artist 的 Active State 最大区别：
- Artist 只有"正在生成/等待反馈"
- Writer 需要知道"在哪个分支、哪些文件改了、测试过没过、有没有未确认的危险操作"

### 30.6 Open Loops 的 Writer 适配

Artist 的 Open Loops 是用户随口提的项目或方向，还没开始。Writer 的 Open Loops 更多样：

```python
class WriterOpenLoop:
    loop_type: Literal[
        "unfinished_task",      # 用户提了但没完成的任务
        "unresolved_bug",       # 发现了但没修的 bug
        "unpushed_changes",     # 本地有改动没 push
        "unreviewed_code",     # 有代码没被审查
        "unconfirmed_decision", # 需要用户做决定的点
        "incomplete_refactor", # 重构了一半
        "pending_pr",          # 等合并的 PR
        "mentioned_idea",      # 用户随口提的想法
        "carried_over_todo",   # 上次没完成的 todowrite 项
    ]
    description: str
    created_at: str
    source_session_id: str
    urgency: Literal["blocking", "soon", "someday"]
```

### 30.7 Log 层的 Writer 适配

Artist 的 Log 主要记录 billing 和 session messages。Writer 需要额外记录：

```text
Git 操作日志：每次 commit/push/branch 操作
文件变更日志：每次 edit/write 的文件路径和 diff 摘要
命令执行日志：每次 bash 执行的命令和退出码
权限决策日志：用户 allow/deny/always 的选择
交互模式切换日志：什么时候从 EXECUTE 切到 TEACH 等
```

这些日志不能进 prompt（太细太碎），但用于审计、自评、周报自动生成。

### 30.8 窗口策略的 Writer 适配

Artist 的对话窗口策略是固定的（完整保留近期对话 + 压缩旧对话）。Writer 需要按任务类型调整窗口。

```python
class WriterWindowStrategy:
    def get_window_config(self, task_type: WriterTaskType) -> WindowConfig:
        if task_type in (CODE_BUGFIX, CODE_DEBUG):
            # 窄上下文：相关文件 + 错误信息 + 最近测试结果
            return WindowConfig(
                hot_turns=2,
                warm_turns=5,
                permanent_context=["project_structure", "error_patterns"],
                max_tool_results=10,
            )
        elif task_type in (CODE_FEATURE, CODE_REFACTOR):
            # 宽上下文：项目结构 + 技术栈 + 已有模式 + 最近变更
            return WindowConfig(
                hot_turns=3,
                warm_turns=8,
                permanent_context=["project_structure", "tech_stack", "code_style"],
                max_tool_results=20,
            )
        elif task_type in (PROSE_NOVEL, PROSE_SCRIPT):
            # 极窄当前上下文 + 永久世界观/角色 + 上一章摘要
            return WindowConfig(
                hot_turns=1,  # 几乎只看当前场景
                warm_turns=2,  # 上一章摘要
                permanent_context=["world_state", "character_profiles", "writing_style"],
                max_tool_results=5,
            )
        elif task_type in (EMAIL_COMPOSE,):
            # 窄上下文：收件人 + 当前主题
            return WindowConfig(
                hot_turns=1,
                warm_turns=3,
                permanent_context=["recipient_profile", "email_templates"],
                max_tool_results=3,
            )
        elif task_type in (TEACHING, DISCUSSION):
            # 宽上下文但轻记忆：用户已知 + 当前主题
            return WindowConfig(
                hot_turns=3,
                warm_turns=6,
                permanent_context=["user_knowledge", "interaction_history"],
                max_tool_results=5,
            )
        else:
            return WindowConfig.DEFAULT
```

### 30.9 记忆的三层价值——Writer 版本

Artist 的记忆三层价值（结论/过程/存在）对 Writer 同样适用，但内容不同：

| 层 | Artist 例子 | Writer 例子 |
|------|-----------|-----------|
| 结论 | "用户偏好冷色调" | "用户偏好 async/await 而非回调" |
| 过程 | "聊了半小时构图方向" | "Debug 了 2 小时，最后是 import 路径问题" |
| 存在 | "用户随口提了表情包项目" | "用户提过想学 Rust，还没开始" |

### 30.10 总结：CON/MEM 适配 Writer 的核心改动

| 改动 | 性质 | 复杂度 |
|------|------|--------|
| Cold CON 索引从 6 项扩展到 11 项 | 存储结构扩展 | 中 |
| Hot CON 匹配从统一策略改为按域分叉 | 匹配逻辑重构 | 高 |
| WriterAdapter 独立实现，不复用 Artist 的标签匹配 | 架构拆分 | 中 |
| Active State 增加 git/文件/测试状态 | 状态扩展 | 低 |
| Open Loops 增加更多类型 | 数据模型扩展 | 低 |
| Log 增加 git/权限/模式切换日志 | 日志扩展 | 低 |
| 窗口策略改为按任务类型动态配置 | 窗口管理重构 | 中 |
| 标签体系从 8 种 task_type 扩展到 20+ | 标签体系重构 | 中 |
| 偏好衰减从"Butler 做"改为"Writer 自维护 v1" | 职责调整 | 低 |

**一句话总结**：CON/MEM 的架构框架（六层结构、召回管线、压缩流程）是正确且可复用的。但 Cold CON 存什么、Hot CON 怎么匹配、标签体系长什么样——这三者必须为 Writer 重写，不能从 Artist 继承。最关键的改动是 **Hot CON 匹配从"统一标签匹配"改为"按任务域分叉匹配"**，因为"写代码需要的上下文"和"写小说需要的上下文"完全不同，不应用同一套逻辑去匹配。

---

## 附录 A：多场景能力覆盖度分析

*分析日期: 2026-05-20*

### A.1 写小说

| 子能力 | 当前设计覆盖 | 缺口 |
|--------|-------------|------|
| 构建世界观 | 低 | 缺 WorldState 结构化存储、跨章节一致性校验、规则冲突检测 |
| 构建角色 | 低 | 缺 CharacterStore、性格一致性校验、角色语言指纹追踪 |
| 构建剧本大纲 | 中 | plan mode 可复用但需适配 narrative plan；缺层级大纲结构 |
| 细化填充 | 中 | loop 机制可用但缺写作状态机、风格一致性追踪、POV 管理 |
| 一句话 100w 字 | 极低 | 缺长文本生成流水线、ContinuityTracker、NarrativeGuardrail、ProgressManager |

### A.2 写代码

| 子能力 | 当前设计覆盖 | 缺口 |
|--------|-------------|------|
| 一步到位构建项目 | 高 | 缺项目模板/脚手架 |
| 排查 Bug | 高 | 缺根因分析 artifact、复现测试自动生成 |
| 自然使用 Git | 高 | 缺 PR 自动生成、分支清理策略 |
| 项目设计与自审 | 中 | 缺结构化 review checklist |
| 目标驱动 | 中 | 缺 Goal 模型、可度量成果 |
| Checkpoint | 中 | 缺多步骤 checkpoint、状态回退、审计记录 |

### A.3 写邮件

| 子能力 | 当前设计覆盖 | 缺口 |
|--------|-------------|------|
| 语气判断 | 低 | 缺 RecipientProfile、语气检测引擎、关系模型 |
| 格式适配 | 低 | 缺邮件格式模板、称呼/结尾规则库 |
| 自审 | 低 | 缺邮件自审 checklist、语气一致性检查 |

### A.4 用户交互

| 子能力 | 当前设计覆盖 | 缺口 |
|--------|-------------|------|
| 多情景交互 | 中 | 缺情绪感知、教学模式、协作思考模式 |
| 模式切换 | 低 | 缺 WriterInteractionMode 枚举 |

### A.5 记忆系统

| 子能力 | 当前设计覆盖 | 缺口 |
|--------|-------------|------|
| 完整用户记忆 | 中低 | ColdCON 用户画像太薄，缺跨会话聚合 |
| 窗口策略 | 低 | 缺分层窗口策略、按任务类型的上下文管理 |

---

## 附录 B：遗漏情景类型补充分析

*分析日期: 2026-05-20*

对用户提出的 5 大类进行扩展，识别当前 Writer 设计未覆盖但应该覆盖的情景类型。

### B.1 写小说大类遗漏

用户只列了"写小说"，但内容创作远不止小说。

#### B.1.1 写剧本/影视脚本

与小说不同：

```text
- 格式要求：场景标题、角色名居中、对话缩进、镜头指示
- 节奏要求：每页约等于 1 分钟银幕时间
- 结构要求：三幕/五幕/序列结构、节拍表
- 协作要求：编剧经常需要按导演/制片反馈修改特定场景
```

当前设计不覆盖。

#### B.1.2 写诗歌/歌词

与小说不同：

```text
- 韵律和格律约束：平仄、押韵、音节数
- 意象密度远高于小说
- 长度极短但要求极高凝练
- 歌词还需要考虑与旋律的配合
```

当前设计不覆盖。

#### B.1.3 写游戏叙事

与小说不同：

```text
- 分支叙事：玩家选择影响剧情走向
- 环境叙事：物品描述、场景文字、NPC 对话
- 多结局管理：各结局的逻辑一致性
- 任务文本：格式固定、长度受限
```

当前设计不覆盖。

**B.1 结论：2 种遗漏**

---

### B.2 写代码大类遗漏

用户列的写代码已经较全，但仍有两个明显遗漏。

#### B.2.1 写测试用例

与写代码不同：

```text
- 不仅是写 test_*.py，还包括：
  - 边界条件枚举
  - 等价类划分
  - 异常路径覆盖
  - 性能基准测试
  - E2E 场景设计
- 需要理解"什么值得测、什么不值得测"
```

当前设计把 `run_test` 当作验证工具，但没有 `design_test_cases` action。

#### B.2.2 写 CI/CD 配置和自动化脚本

与写代码不同：

```text
- GitHub Actions / GitLab CI / Jenkins
- Dockerfile / docker-compose
- Makefile / Taskfile / justfile
- 部署脚本和回滚脚本
- 环境变量管理和密钥轮换
```

当前 bash 工具理论上可以，但没有 CI/CD 模板或安全审查。

**B.2 结论：2 种遗漏**

---

### B.3 写文档/专业文本大类遗漏

用户只列了"写邮件"，但专业文本远不止邮件。

#### B.3.1 写技术文档/API 文档

```text
- API reference（参数、返回值、错误码、示例）
- 架构设计文档（ADR、RFC）
- 快速入门指南
- 迁移指南
- CHANGELOG
- 故障排查手册
```

与写邮件不同：不需要语气判断，需要准确性和可验证性。

#### B.3.2 写方案/提案/报告

```text
- 技术方案（背景→方案对比→推荐→风险→排期）
- 项目提案（目标→范围→资源→时间线→预期收益）
- 竞品分析报告
- 季度/年度总结
```

与写邮件不同：需要数据支撑和逻辑链。

#### B.3.3 写产品需求文档(PRD)

```text
- 用户故事和验收标准
- 功能优先级排序
- 非功能需求（性能、安全、可访问性）
- 原型图和交互说明
```

与写代码不同：不是实施而是定义。

#### B.3.4 写周报/日报/会议纪要

```text
- 格式固定但内容随项目变化
- 需要从 git log / todowrite / conversation 自动提取素材
- 会议纪要从录音/对话中结构化提取
```

当前设计完全没有"从自身活动日志自动生成摘要"的能力。

#### B.3.5 写简历/求职信

```text
- 高度格式化和压缩
- 需要从用户记忆和项目历史中提取亮点
- 针对特定职位定制
```

#### B.3.6 写演讲稿/PPT 大纲

```text
- 口头表达节奏
- 每句话的信息密度控制
- 与 PPT 页面的配合
- 开场/过渡/结尾的特殊写法
```

#### B.3.7 写广告/营销文案

```text
- AIDA 模型（Attention-Interest-Desire-Action）
- 平台差异化：小红书 vs LinkedIn vs Twitter vs 公众号
- SEO 关键词密度
- CTA（Call to Action）设计
```

#### B.3.8 翻译

```text
- 不仅是字面翻译
- 需要保留原文的语气、双关、文化引用
- 技术文档翻译需要注意术语一致性
- 中英互译特有的句式转换
```

**B.3 结论：8 种遗漏**

---

### B.4 用户交互大类遗漏

用户列的交互情景集中在"任务交互"，还有大量非任务交互遗漏。

#### B.4.1 用户学习/提问模式

```text
- 用户："解释一下 Rust 的所有权系统"
- Writer 需要：
  - 判断用户的知识水平
  - 用类比和示例解释
  - 反问确认理解程度
  - 提供练习或下一步学习建议
```

当前只有"执行模式"，没有"教学模式"。

#### B.4.2 用户深度提问/追问链

```text
- 用户连续追问同一个主题
- Writer 需要：
  - 保持答案之间的连续性
  - 记住上一轮的解释层次
  - 在用户卡住时主动拓宽或降低难度
```

与普通对话不同：不是一问一答结束。

#### B.4.3 用户决策困难

```text
- 用户："应该选 React 还是 Vue？"
- Writer 需要：
  - 了解项目的具体情况
  - 给出对比而不是直接推荐
  - 提出决策框架
  - 不替用户做决定但帮用户理清思路
```

当前设计没有"决策支持模式"。

#### B.4.4 用户情绪低落/挫折

```text
- 用户："这个 bug 修了三天了，我是不是不适合编程"
- Writer 需要：
  - 不是强行鼓励
  - 帮助拆解问题降低难度
  - 提醒用户已经解决的类似问题
  - 不变成 Mate，但也不是冷漠工具
```

当前 PER 是匠人——极简。这种情况只说"继续"是不够的。

#### B.4.5 用户需要头脑风暴

```text
- 用户："想做一个 side project，但没想好做什么"
- Writer 需要：
  - 基于用户历史项目和偏好提建议
  - 发散思维
  - 不急于评估可行性
```

当前没有"头脑风暴模式"。

#### B.4.6 用户让 Writer 评估外部内容

```text
- 用户："帮我看看这个 PR 怎么样"
- 用户："这篇技术文章写得对吗"
- 用户："这份合同有什么问题"
```

当前设计有代码审查，但缺少通用内容评估。

#### B.4.7 跨会话连续性 / 用户"回来了"

```text
- 用户 3 天后打开 Writer
- Writer 需要：
  - 知道上次做到哪了
  - 知道当前分支状态
  - 如果有未完成的 open loop 主动提起
  - 如果有很多新 commit 没有审查，主动提出
```

当前设计没有"会话恢复"仪式。

#### B.4.8 多项目并行 / 上下文切换

```text
- 用户同时在两个项目之间切换
- Writer 需要：
  - 切换到项目 A 时自动恢复项目 A 的上下文
  - 不把项目 B 的记忆混入项目 A
  - 在切换时提醒未完成事项
```

**B.4 结论：8 种遗漏**

---

### B.5 记忆系统大类遗漏

#### B.5.1 不对用户"重新自我介绍"

```text
- 用户每次开新会话不应该重新解释项目结构
- Writer 应该主动加载 work_root 的项目状态
- 如果发现项目结构变化，应主动报告差异
```

当前设计有新会话概念但缺少"认知连续性"仪式。

#### B.5.2 记忆的置信度衰减

```text
- 用户 3 个月前偏好 Pydantic，现在可能变了
- Writer 不应该永远用旧偏好
- 记忆应该有衰减曲线：时间越久，权重越低，除非被最近的行为重新确认
```

当前 ColdCON 是 append-only，没有时间衰减。

#### B.5.3 记忆的"可问"原则

```text
- 用户说："你都知道我什么"
- Writer 应该能拉出完整的用户画像
- 用户说："忘了这个"
- Writer 应该能删除特定记忆
- 用户说："不是这样"
- Writer 应该能修正
```

这与 LamTools 生态的"可问/可删/可纠"原则一致，但当前 Writer 设计没有实现。

#### B.5.4 跨成员记忆共享

```text
- Writer 修改了项目的 API 结构
- Artist 不知道，画了旧版 API 的界面图
- 问题：不同成员之间的记忆没有对齐
```

当前设计有"请求图像"但没有"通知结构变化"。

**B.5 结论：4 种遗漏**

---

### B.6 汇总

| 大类 | 用户已列子类 | 遗漏子类数 | 遗漏项 |
|------|------------|----------|--------|
| 写小说 | 5 | 2 | 写剧本/脚本、写游戏叙事 |
| 写代码 | 6 | 2 | 写测试用例、写 CI/CD/自动化脚本 |
| 写文档/专业文本 | 1 (仅邮件) | 8 | 技术文档、方案报告、PRD、周报/纪要、简历、演讲稿、广告文案、翻译 |
| 用户交互 | 2 | 8 | 教学模式、追问链、决策支持、情绪低落、头脑风暴、外部内容评估、会话恢复、多项目切换 |
| 记忆系统 | 2 | 4 | 认知连续性仪式、置信度衰减、可问/可删/可纠、跨成员记忆共享 |

**总计：用户已列 16 种子能力，补充识别 24 种遗漏子能力。**

---

### B.7 遗漏情景的分类与优先级

不需要全部立刻实现。按"对 Writer 产品可用性的影响"分级：

```text
P0 — 缺了就不好用（核心交互中断）：
  写技术文档/API 文档
  写方案/报告
  写周报/会议纪要（从活动日志自动生成）
  教学模式（用户提问时）
  会话恢复和多项目切换
  记忆置信度衰减

P1 — 缺了就少了灵魂（影响"真人感"）：
  写 PRD
  写演讲稿
  翻译
  决策支持
  情绪低落
  头脑风暴
  跨成员记忆共享

P2 — 缺了不影响核心但影响完整性：
  写剧本/脚本
  写游戏叙事
  写测试用例（自给自足）
  写 CI/CD 配置
  写简历
  写广告文案
  追问链
  外部内容评估
  可问/可删/可纠原则
  认知连续性仪式
```

**结论：当前设计对"写代码 + Git"覆盖良好，但对"专业文本写作"和"复杂交互情景"几乎是空白。**
