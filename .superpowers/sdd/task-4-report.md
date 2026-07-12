# Task 4 Report: Writer Command Catalog, Skill Expansion, And App-Server Operations

## Scope

- Writer backend only.
- Allowed write scope respected.
- `/fork`, command catalog, and skill expansion implemented now.
- `/compact` intentionally returns a clear unavailable result because Task 5 compaction service does not exist yet.

## RED Evidence

Command run before implementation:

```powershell
py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py -k "command_catalog or skill" -q
```

Observed failure:

```text
ImportError: cannot import name 'handle_command_catalog_operation' from 'app.app_server.operations'
```

Interpretation:

- Writer app-server did not expose command catalog operations yet.
- Skill expansion path did not exist yet.

## GREEN Evidence

Required verification:

```powershell
py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py -k "command_catalog or skill or queue_create_rejects_attachment_input" -q
```

Result:

```text
5 passed, 63 deselected
```

Required skill contract verification:

```powershell
py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -k skill -q
```

Result:

```text
4 passed, 29 deselected
```

Additional backend verification for command execution:

```powershell
py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py -k command_execute -q
```

Result:

```text
1 passed, 67 deselected
```

Whitespace check:

```powershell
git diff --check -- members/writer/backend/app/services/command_service.py members/writer/backend/app/services/composer_input_service.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py
```

Result:

- Exit code `0`
- Only line-ending warnings, no diff errors

## Files Changed

- `members/writer/backend/app/services/command_service.py`
- `members/writer/backend/app/services/composer_input_service.py`
- `members/writer/backend/app/app_server/operations.py`
- `members/writer/backend/app/app_server/connection.py`
- `members/writer/backend/tests/test_writer_app_server_protocol.py`

## What Changed

### 1. Command catalog and execution

- Added Writer command catalog service that merges Core commands with dynamically discovered Writer skills.
- Added app-server operations:
  - `command.catalog`
  - `command.execute`
- Registered both operations in the Writer operation catalog and connection handlers.

### 2. Skill expansion before runtime

- Added composer input preparation service with dual outputs:
  - visible input for stored user-facing message text
  - runtime input for expanded skill content
- `turn.start` now:
  - expands `skill` input items before acceptance
  - stores visible `/skill` text in the user message
  - sends expanded skill body to runtime text

### 3. Queue behavior

- `queue.create` now expands skill items before queue acceptance.
- Queue acceptance uses expanded runtime items only after expansion succeeds.
- Missing-skill failures now stop before any queue event is accepted.

### 4. Tests

- Added protocol tests for:
  - command catalog includes Core commands and dynamic skills
  - turn start keeps visible `/skill` text while runtime receives expanded skill content
  - queue create fails before acceptance when selected skill is missing
  - queue create stores expanded skill content after backend expansion succeeds
  - command execute supports `/fork` and returns a temporary unavailable result for `/compact`
- Updated operation catalog coverage tests for new command methods.

## Sequencing Concern

- Task 4 brief referenced `session_compaction_service.py`, but that service is scheduled for Task 5 and is not present.
- To keep Task 4 unblocked without leaking Task 5 implementation into this task, `/compact` currently returns:
  - `status: unavailable`
  - a clear reason that compaction is deferred to Task 5

## Commit Target

Required commit message:

```text
feat(writer): expose core composer commands
```

## Review Fixes

Date:

- 2026-07-04

Findings addressed:

1. Queued skill input now keeps user-visible `/skill` text in queue and dispatched transcript storage, while runtime still receives the expanded skill body.
2. Dynamic skill commands now follow the same disable and name-reservation rules as Core-sourced insert-token commands.

Implementation notes:

- `queue.create` still validates and expands skill items before acceptance, but queue payload now stores:
  - `input`: visible composer items for user-facing persistence
  - `runtime_input`: expanded items for later runtime dispatch
- Queue dispatch now uses visible `input` for turn acceptance and transcript persistence, and uses `runtime_input` for the runtime text path. Older queue entries without `runtime_input` still fall back to `input`.
- Dynamic skill commands are filtered out when their normalized name:
  - appears in member `command/config.json` `disabled_core_commands`
  - collides with any already-loaded command name such as `fork` or `compact`

Additional regression coverage:

- command catalog hides skill names disabled by member config
- command catalog hides skill names that collide with reserved command names
- queue accepted payload keeps visible `/skill` input plus expanded `runtime_input`
- queue dispatch stores visible `/skill` in the user message while runtime receives expanded skill content

Verification after review fix:

```powershell
py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py -k "command_catalog or skill or queue_create_rejects_attachment_input or command_execute" -q
py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -k skill -q
```

Results:

- `9 passed, 62 deselected`
- `4 passed, 29 deselected`

## Re-review Fix: normalized skill command filtering

Date:

- 2026-07-04

Finding addressed:

- Dynamic skill command filtering now uses the same normalized-name semantics as Core command loading before comparing against reserved names and `disabled_core_commands`.

RED evidence:

```powershell
py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py -k "command_catalog or skill or queue_create_rejects_attachment_input or command_execute" -q
```

Observed failure before the fix:

```text
FAILED test_command_catalog_hides_skill_names_disabled_by_member_config
FAILED test_command_catalog_hides_mixed_case_skill_names_that_collide_with_core_commands
```

Failure detail:

- A skill named `/Disabled Skill Catalog` still appeared even when member config disabled `disabled skill catalog`.
- A skill named `/Fork` still appeared alongside the reserved `fork` command.

GREEN evidence:

```powershell
py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py -k "command_catalog or skill or queue_create_rejects_attachment_input or command_execute" -q
py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -k skill -q
```

Results after the fix:

- `10 passed, 62 deselected`
- `4 passed, 29 deselected`

Implementation notes:

- Dynamic skill command names are now normalized with the same rules as Core commands:
  - trim
  - strip leading `/`
  - collapse internal whitespace
  - lowercase
- Reserved-name checks and member `disabled_core_commands` checks now compare normalized names.
- Emitted dynamic skill command names are also normalized, while titles keep the readable skill label without the leading slash.

## Final Re-review Fix: normalized skill command round-trip

Date:

- 2026-07-04

Finding addressed:

- Dynamic skill commands now round-trip through the same exposed command name:
  - catalog emits the normalized command name
  - turn and queue skill expansion accept that normalized name
  - runtime still loads the original skill content

RED evidence:

```powershell
py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py -k "command_catalog or skill or queue_create_rejects_attachment_input or command_execute" -q
```

Observed failure before the fix:

```text
FAILED test_turn_start_expands_normalized_mixed_case_skill_command_name
```

Failure detail:

- A skill with frontmatter name `/Review Mixed` appeared in the catalog as `review mixed`.
- Submitting `review mixed` back through turn input failed with:
  - `Skill "review mixed" not found. Available skills: /Review Mixed, ...`

GREEN evidence:

```powershell
py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py -k "command_catalog or skill or queue_create_rejects_attachment_input or command_execute" -q
py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -k skill -q
```

Results after the fix:

- `11 passed, 62 deselected`
- `4 passed, 29 deselected`

Implementation notes:

- Added a regression test covering:
  - slash-prefixed mixed-case skill frontmatter
  - normalized command name emitted by catalog
  - successful turn expansion using that normalized name
- Added a minimal resolver in the Writer command service:
  - keep exact-name lookup first
  - fall back to normalized-name matching only for dynamic skill resolution
- Missing-skill behavior stays explicit because unresolved names still flow through the existing registry error path.

## Re-review Fix: queued edit clears stale runtime payload

Date:

- 2026-07-04

Finding addressed:

- Editing a queued item now replaces the stored runtime payload as well as the visible input, so later dispatch cannot reuse stale expanded skill content from the old queue item.

RED evidence:

```powershell
py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py -k "queue_update_replaces_stale_runtime_input_before_dispatch" -q
```

Observed failure before the fix:

```text
FAILED test_queue_update_replaces_stale_runtime_input_before_dispatch
```

Failure detail:

- Queue update changed the visible text to `改成普通文本`.
- Dispatch still returned the old expanded reviewer skill body in `runtime_input`.

GREEN evidence:

```powershell
py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py -k "command_catalog or skill or queue_create_rejects_attachment_input or command_execute or queue_update" -q
py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -k skill -q
```

Results after the fix:

- `12 passed, 62 deselected`
- `4 passed, 29 deselected`

Implementation notes:

- Added a regression that:
  - creates a queued skill item with expanded `runtime_input`
  - edits it to plain text through `queue.update`
  - dispatches it and verifies runtime receives only the edited text
- Kept the fix inside queue update handling:
  - edited text now overwrites both `input` and `runtime_input`
  - no reducer changes needed
  - queue create still stores expanded runtime skill content before acceptance
