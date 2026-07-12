# Core Agent Workbench Foundation Plan

## Goal

Move generic Agent App infrastructure from Writer into Core so Core Agent can run with the same base workbench capabilities as Writer, while Writer keeps only Writer-specific overlay behavior.

Acceptance target:

- Core Agent GUI and CLI can run an agent turn through Core-owned infrastructure.
- Core GUI shows immediate user message, running assistant state, streamed or incrementally updated reasoning/text/tool parts, and stop/send state.
- Core exposes base operations for turn start, turn cancel, approval response, queue input, command catalog, model/thinking options, and snapshot/event resume.
- Writer uses Core-owned transport/control/projection where possible and does not duplicate generic Agent workbench logic.
- Writer keeps product-specific project semantics, AGENTS.md management, Writer commands, Writer-specific artifacts, and coding/review workflow.

## Product Reading

The user goal is not "make Core look like Writer by copying UI." The real goal is:

1. Core is a standalone base Agent App.
2. Member apps behave like patches/modes over Core.
3. All reusable agent infrastructure lives in Core.
4. Writer remains functional after the migration.
5. Any GUI capability has a matching CLI/backend operation.

## Mature Pattern Alignment

OpenAI Agents and Claude Code both separate the agent runtime/control plane from product-specific behavior:

- Agent loop, model calls, tool calls, approvals, streaming events, sessions, and handoffs belong to the runtime/control plane.
- Skills/hooks/MCP/permissions are layered configuration and execution infrastructure.
- Product/member code should register prompts, commands, tools, policy overlays, and presentation preferences instead of owning the runtime loop.

LamTools should follow the same shape:

- Core owns the live Agent App protocol and workbench primitives.
- Members provide overlay adapters.

## Scope

### In Scope

- Core live transport and snapshot/event feed.
- Core turn lifecycle operations.
- Core cancel/stop operation.
- Core approval response operation.
- Core queue/steer operation shape, at least enough to match Writer base behavior.
- Core command catalog exposure.
- Core model/thinking/shallow pass-through for per-turn execution.
- Core UI controller/client for live workbench state.
- Core composer base controls: model select, thinking select, shallow toggle, send/stop.
- Writer migration to call Core-owned frontend/backend primitives where practical.
- Tests proving Core and Writer both use the shared base path.

### Out of Scope For This Slice

- Rewriting Writer project management.
- Removing Writer-specific Git/checkpoint/review features.
- Redesigning settings pages.
- Changing provider adapter request-body logic unless required for per-turn model/thinking pass-through.
- Large visual redesign.

## Boundary Rules

Core owns:

- Thread/session lifecycle as generic Agent App state.
- Turn start/cancel/steer/queue operations.
- Runtime event and snapshot protocol.
- Tool-call display protocol.
- Approval protocol.
- Model and thinking selection contract.
- Generic composer behavior.
- Generic command catalog contract.
- Generic attachments/artifacts protocol, where not tied to Writer project storage.
- Permissions/hooks/skills/MCP loading and execution infrastructure.

Writer owns:

- Writer product persona.
- Writer project/work-root semantics.
- AGENTS.md editing.
- Writer-specific commands such as compact/fork only when they depend on Writer policy.
- Coding workflow, review workflow, branch/checkpoint presentation if it is Writer-specific.
- Writer-specific artifact rendering and labels.
- Provider-specific UI hints only until Core has a provider capability registry.

## Proposed Architecture

### Backend

Add a Core-owned live app-server/control module under `core/src/lamtools_core/app/`:

- `live_protocol.py`: JSON-RPC style request/response/event shapes, shared naming, and operation aliases.
- `live_hub.py`: thread-scoped publish/subscribe over app events and snapshots.
- `live_operations.py`: Core base operations for thread read/resume, turn start/cancel, queue, approval, command catalog, and config reads.
- `live_connection.py`: WebSocket connection loop, modeled after Writer app-server but product-neutral.
- `live_router.py`: FastAPI router for `/api/core/app-server` and token/auth if needed.

Core turn execution must publish app events during execution, not only after the whole run finishes. If the existing kernel sink is batch-only, add a publishing sink that records each runtime event and updates the snapshot immediately.

Writer backend then becomes an adapter:

- Keep Writer runtime lifecycle and product operations.
- Replace generic app-server protocol/connection logic with Core live connection where possible.
- Register Writer overlay operations into the Core operation catalog.
- Keep Writer-specific database tables until a separate migration plan moves them.

### Frontend

Add Core-owned frontend live workbench modules under `core/ui/src/`:

- `appServer/client.ts`: generic WebSocket JSON-RPC client.
- `appServer/store.ts`: generic connection/reconnect/snapshot state.
- `appServer/selectors.ts`: generic snapshot-to-chat-message projection.
- `composables/useAgentWorkbenchController.ts`: live send/stop/queue/approval/model/thinking state.
- `components/AgentComposerControls.vue`: model select, thinking select, shallow toggle, send/stop slot defaults.

Core demo app should use these modules directly.

Writer frontend should import and configure the Core modules:

- Provide Writer session/project/work-root adapter.
- Provide Writer overlay commands and artifact renderers.
- Remove duplicated generic WebSocket, snapshot, queue, approval, send/stop, model/thinking composer logic where the Core module covers it.

## Implementation Tasks

### Task 1: Prove The Current Gap With Tests

Add failing tests before implementation:

- Core UI controller test: after submit, user message and assistant waiting state appear before turn completion.
- Core UI controller test: running state flips composer action from send to stop.
- Core HTTP/live backend test: turn start can be observed before final completion.
- Core operation test: per-turn thinking/model fields are accepted and propagated into execution context.

Expected initial state: tests fail because Core currently waits for final `startTurn`.

### Task 2: Add Core Live Event Publication

Implement a Core event sink that persists and publishes each runtime event as it happens.

Minimal behavior:

- Append run item event.
- Apply thread snapshot.
- Publish event to subscribers.
- Keep existing final HTTP route behavior compatible.

Verification:

- Backend unit test sees an event/snapshot before operation completion.
- Existing Core HTTP route tests still pass.

### Task 3: Add Core Live Operations

Create Core-owned base operations:

- `thread.read`
- `thread.resume`
- `turn.start`
- `turn.cancel`
- `turn.steer` or `queue.create` if running
- `approval.respond`
- `command.catalog`
- `config.providers.list`
- `config.models.list`
- `config.resolved.get`

Minimal behavior:

- Match Writer operation names/aliases where possible.
- Keep Core DB separate from member DB.
- Use shared config DB for provider/model data.
- Per-turn request accepts `model_id`, `thinking_enabled`, `thinking_budget`, and `shallow_thinking_enabled`.

Verification:

- Core tests prove operations exist and return Writer-compatible envelopes/snapshots where generic.

### Task 4: Add Core Live WebSocket/SSE Route

Preferred route:

- WebSocket JSON-RPC, because Writer already uses that model and it supports bidirectional approval/stop/queue.

Fallback:

- SSE for events plus HTTP POST operations only if WebSocket extraction proves too risky.

Verification:

- Backend test opens a Core live connection, starts a turn, receives snapshot/event, then can resume from `last_seen_seq`.

### Task 5: Move Core Frontend Workbench Client/Store

Create generic Core UI modules from Writer equivalents:

- Connection state.
- Request/response handling.
- Snapshot hydration.
- Reconnect and resume.
- Chat message selection.
- Initial waiting assistant message.
- Reasoning/text/tool/approval projection.

Verification:

- Core UI tests prove live messages update without waiting for final completion.
- Snapshot selector tests are copied/adapted from Writer and pass in Core UI.

### Task 6: Add Core Composer Base Controls

Move generic composer controls into Core UI:

- Model selector.
- Thinking selector.
- Shallow toggle.
- Send/stop action.
- Disabled/running states.

Verification:

- Core UI tests prove send/stop button state.
- Core UI tests prove thinking/model payload included in turn start.

### Task 7: Migrate Writer Frontend To Core Base

Replace duplicated Writer generic logic with Core imports.

Keep Writer code for:

- Project grouping.
- Work-root selection.
- AGENTS.md.
- Writer-specific commands and panels.
- Writer-specific artifact behavior.

Verification:

- Writer frontend typecheck.
- Writer existing app-server tests or UI tests still pass.
- Static scan shows Writer no longer owns generic client/store/selector logic except adapters.

### Task 8: Migrate Writer Backend To Core Live Base

Extract product-neutral pieces from Writer app-server to Core or wrap Core live connection.

Keep Writer code for:

- Writer database models.
- Project/session creation specifics.
- Writer runtime lifecycle adapter.
- Writer overlay operations.

Verification:

- Writer backend tests pass for turn start, interrupt, queue, approval, command catalog, config, and snapshot.
- Core backend tests pass independently against Core DB.

### Task 9: Live Acceptance

Run real tasks:

1. Core GUI or Core live CLI with Kimi K2.6:
   - Ask it to create a markdown file over 10 lines.
   - Verify reasoning block, text block, tool call, at least two model rounds, live UI state, and persisted Core DB snapshot.
2. Writer GUI or Writer CLI:
   - Run equivalent Writer task.
   - Verify Writer uses Core base controls/operations and Writer-specific behavior still works.

## Risk Register

1. Core batch sink may be too deep in the current kernel path.
   - Mitigation: add a live sink adapter without changing kernel semantics.

2. Writer app-server mixes generic and Writer-specific data too tightly.
   - Mitigation: first extract frontend generic modules, then backend operation seams.

3. Per-turn model/thinking may be currently fixed at app startup.
   - Mitigation: make per-turn execution config explicit in Core operation payload and tests.

4. Queue/approval continuation may differ between Core and Writer.
   - Mitigation: match operation contract first, then converge implementation.

5. Full extraction may exceed one safe slice.
   - Mitigation: stop only at a verified Core-owned base path; leave documented follow-up only for clearly Writer-specific surfaces.

## Self-Review Checklist

- No new parallel runtime path should remain in Writer for generic Agent behavior.
- No `core/src/lamtools_core` code may mention Writer or LamWriter.
- Writer must not duplicate Core client/store/selector behavior after migration.
- Core must independently run as an Agent App.
- Core and Writer must both pass targeted backend and frontend tests.
- Real Kimi K2.6 task must prove thinking, text, tool call, loop continuation, and persistence.

