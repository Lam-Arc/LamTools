# Behaviour parity with the Python core

The point of this file is to stop a rebuild from quietly losing something the
Python core already did well. Every row says what the new core does today, and
every "same" claim has a test that fails if it stops being true.

These are not differential tests that execute Python. They encode the observed
behaviour, with the Python evidence named, so drift is visible. A live
differential run is deferred until a module is actually ported.

## Same behaviour, with a test

| behaviour | Python evidence | new core | test |
|---|---|---|---|
| paths cannot escape the workspace | `tool/workspace_files.py:699` raises `outside work_root` | same rule, same refusal | `platform/tests/python_parity.rs::path_outside_the_workspace_is_refused` |
| a write never leaves half a file | `tool/workspace_files.py:197 atomic_write_bytes` (temp + `os.replace`) | same pattern, no leftover temp | `platform/tests/python_parity.rs::a_write_never_leaves_a_partial_file` |
| a changed file is not silently overwritten | version hash, failure code `content_version_changed` | compare-and-swap on `ETag` | `platform/tests/python_parity.rs::a_changed_file_is_not_silently_overwritten` |
| HTML is reduced to text, containers dropped | `tool/web_tools.py` clean + truncate | same reduction, same 30 000 limit | `tools/tests/python_parity.rs::script_and_style_bodies_never_reach_the_model` |
| non-absolute URL refused before any request | web tool argument validation | same | `tools/tests/python_parity.rs::a_relative_url_is_refused_before_any_request` |
| truncation is announced to the model | `clean[:30000]` with a marker | same limit, pinned marker sentence | `tools/tests/python_parity.rs::the_truncation_marker_is_the_documented_one` |

## Better on purpose, so parity would be a regression

| behaviour | Python | new core | why the change |
|---|---|---|---|
| max rounds | none; bounded only by 100 retries × 360 s | `RunBudget { max_rounds: 16 }` | an unbounded loop cannot be reasoned about or budgeted |
| approval expiry | never expires, by design ("a timeout is not consent") | TTL required, zero refused | on a phone an approval card can sit for hours; consent must be tied to a decision, not to a stale screen |
| approval scope | by tool name; `ApproveForSession` is per tool | bound to `args_digest`, single use | the user approves specific arguments; a different call must not ride the same consent |
| concurrent run on a thread | `accept_run` refuses the second run | the second run queues | a double tap on a phone must not surface as an error |
| error shape | 3 string variants in `RuntimeError` | 11 typed variants with stable exit codes | the UI and the CLI need to branch on cause |
| result unknown | no such state anywhere | `ToolStage::Unknown` plus `OutcomeUnknown` | a killed process between dispatch and result must not silently re-run a write |
| event ordering | events and checkpoints written independently | journal append and receipt commit in one transaction | a crash cannot leave a receipt with no event |
| steering | guidance kept in the task registry, staged/offered/consumed | guidance rows in SQLite, consumed with its own event before the row is marked | a restart cannot lose or double-apply an instruction |
| compaction | summarises the middle, keeps recent steps | same, and it can never drop the system prompt or the task statement | the agent must not forget what it was asked to do |

## Known gaps, recorded rather than hidden

| gap | consequence today | where it will be closed |
|---|---|---|
| sensitive paths | **closed**: `.env`, `.env.*`, `.ssh/`, `id_rsa`, `.pem`, `.key`, `.git/` are refused for read and write | `platform/tests/python_parity.rs::sensitive_paths_are_blocked_like_the_python_core` |
| symlink escape | **closed**: a link pointing outside the workspace is refused | `platform::tests::a_symlink_pointing_outside_is_refused` |
| absolute paths | **closed**: drive letters, UNC prefixes and leading separators are refused on every platform | `platform::tests::refuses_absolute_paths_in_every_shape` |
| identical-tool-result guard | a model can repeat the same call until the budget stops it | `max_identical_tool_results: 10` in Python; port with the loop in M3 |
| no sub-agents, MCP, skills | those capabilities are unavailable | M4 |
| no protocol compatibility | an existing desktop UI cannot talk to this core | M3 |

## How to keep this honest

When a gap closes, move its row up to "same behaviour" and add the test in the
same change. When a behaviour changes on purpose, move it to the second table
with the reason. A row that is neither tested nor reasoned about is a bug in this
document.
