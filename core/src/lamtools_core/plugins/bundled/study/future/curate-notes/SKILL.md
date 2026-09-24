---
name: curate-notes
description: Turn trustworthy original snapshots into traceable Resources in Study, and maintain a user knowledge base of multiple Markdown Note documents. Use to organize, connect, or revise notes; reading or marking content is not mastery evidence.
metadata:
  version: "4.0.0"
  study-stage: "active"
---

# Maintain Study's three-layer notes

This skill keeps only constraints that change decisions. Read [Three-layer notes reference](references/notes.md) for action fields and details.

## 1. Three layers

- **Raw:** Original host-captured snapshots from sessions, marks, exams, and knowledge nodes. Raw is read-only evidence. The Agent may read it but must not create, rewrite, fabricate, or write guesses back into Raw.
- **Resource:** Versioned material the Agent generates from Raw. Each Resource must cite real `raw_ids` and preserve source lineage and version. It supplies Notes; it is not the final note the user sees and must not impersonate the user's words.
- **Note:** A real Markdown document in the user's knowledge base. Its path and complete Markdown body are authoritative. It may have a parent document, `[[note:<id>]]` and `[[node:<id>]]` links, backlinks, and native Markdown syntax. Every Note must cite at least one real Resource. The host manages frontmatter, source notes at the end, and index fields.

## 2. Read before acting

1. Load this skill, then read Raw, relevant Resources, and the target Note within the request's scope. If no Note is specified, find candidates with `tree` or `list` and continue in pages; do not scan unrelated sessions.
2. Identify reusable Resources and Notes and record their actual sources and revision/hash. Reading content, receiving a mark, reading a Note, or generating a self-test does not establish mastery.
3. Derive personal facts only from Raw. Distinguish model explanation, external material, and the user's exact words. If sources are missing, conflicting, or stale, mark the point for verification; do not invent IDs, question numbers, or conclusions.

## 3. Make minimal incremental changes

- Create or update a Resource first, then cite it when creating or updating a Note. Do not display a Resource directly as the final Note.
- For Resources, use `resource_create` or `resource_update` with real `raw_ids` and the current `expected_revision`. For Notes, use `create` or `update` with real `resource_ids`, the current Note revision, `expected_content_hash`, and the complete `body_md`.
- Preserve formulas, code, lists, quotations, and user formatting in the full Markdown Note. Do not rewrite content the user did not request or manually write or overwrite host-managed frontmatter and source material at the end.
- Disambiguate with `[[note:<real ID>]]` and `[[node:<real ID>]]`; put links where they matter in the body. `graph` is a relationship view in the current Note's right sidebar, not another knowledge layer or background task.
- After the user enters a Note, they request maintenance of the current document through Notes chat. Do not claim a save without a successful receipt and matching target revision/hash.

## 4. User protection and conflicts

- The user can select and lock a range in the UI. The lock prevents Agent edits, not user edits. The Agent does not call lock or unlock actions or fabricate lock status.
- On `NOTE_REGION_LOCKED`, keep the unsaved draft, report the `reason` and `overlap` or overlapping range, then offer a suggestion or ask the user to decide. Do not bypass the lock, fragment an overlapping change, silently overwrite it, or create an equivalent Note elsewhere.
- On `REVISION_CONFLICT`, `CONTENT_HASH_CONFLICT`, or an external Markdown change, reread Raw, Resource, and Note as relevant and compare the current content before making the smallest edit. Do not retry blindly.
- Claim creation or update only when the tool explicitly succeeds and its receipt identifies the matching target and revision/hash. Treat failures, timeouts, and unclear status as unsaved.

## 5. Sources and expression

Preserve the original words and identify them as a quotation when quoting the user. Do not attribute AI paraphrases to the user. State personal misconceptions only as strongly as evidence permits; exam conclusions still come from the exam process. Organization alone produces no mastery, pass status, or long-term memory.

Read [Three-layer notes reference](references/notes.md) for action fields, Markdown file rules, error receipts, and examples. Read [Resources and tool decisions](references/resources.md) when external-source boundaries matter.
