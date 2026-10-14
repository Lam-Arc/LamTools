# Sunday 0.3.19 — proposed Windows stable release

- Keep sub-agent execution state and steering consistent with the main turn.
- Resume a stopped turn without duplicating its user input or replaying completed tools.
- Keep the internal Core API local; require authentication for explicitly configured LAN access.
- Improve Workflow persistence and plugin startup, failure diagnostics and recovery.
- Protect unsaved settings drafts when navigating or closing editors.
- Add optional raw model request/response recording for diagnostics, disabled by default.
- Repair legacy conversation revision drift after restoring older data.
- Show model setup failures immediately and leave the conversation available for retry.

Workflow remains an optional external plugin, excluded from the desktop installer.
Six-digit WAN pairing is deprecated and unsupported.
