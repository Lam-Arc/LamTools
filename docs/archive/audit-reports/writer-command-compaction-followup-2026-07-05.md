# Writer command and compaction follow-up, 2026-07-05

## Exposed issues

1. `/compact` candidate appears, but selecting it can look like nothing happened.
   - Expected: execute the same compact command path as any other command.
   - If compaction cannot run, keep the input and show a clear error near the composer.

2. Manual `/compact` and automatic token-budget compaction must share the same structured compaction strategy.
   - Manual command uses the Writer service compaction interface.
   - Automatic runtime compaction uses the Core structured compactor.
   - Both must preserve user decisions, constraints, paths, command results, and next actions.

3. `fork` creates the new session, but the visible URL can still point at the old session.
   - Expected: after any session selection, the URL query reflects the active session.

4. Long runs can have long quiet periods while the model prepares large tool-call payloads.
   - Keep this as a second-pass UX improvement after command correctness is fixed.

## First repair pass

- Make command failures visible at the composer, not only in the right-side status panel.
- Keep the command text on failure so users can retry.
- Route send-button clicks through the same submit function as form submit.
- Sync `?session=` whenever the active session changes.
