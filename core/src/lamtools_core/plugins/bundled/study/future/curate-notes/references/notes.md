# Three-layer notes reference

Read when calling notes, organizing the Markdown knowledge base, handling sources or links, or resolving write conflicts. This file records non-obvious details of the current contract; the skill entry contains decision rules.

## 1. Data ownership

### Raw: host snapshots

Raw is an original host-captured snapshot of a session, user mark, exam record, or knowledge node. It has a `raw_id`, `kind`, `origin_id`, original `content`, `metadata`, and capture time, and returns `immutable: true`. The Agent may read it only through `raw_list` and `raw_get`. Capturing Raw belongs to the trusted host, not the Agent's write abilities. If Raw is absent, explain the gap; do not fill it from model memory or guesswork.

### Resource: traceable material

A Resource is versioned material the Agent creates after reading Raw. It contains `resource_id`, `title`, `content`, `raw_ids`, `origin`, and `revision`. Before creating or updating one, confirm that each `raw_id` belongs to Raw actually read for this work. Content without a source belongs only in an unsaved draft. A Resource is material for organizing and citing in a Note, not the final display when a user opens a Note, and cannot impersonate the user's words.

### Note: Markdown knowledge base

A Note is an actual user-visible Markdown file. SQLite stores only its index, relationships, revision/hash, and range locks. One Study note vault can contain multiple `.md` documents. `path` is relative to the vault and is the sole source of the left file tree structure. `parent_id` means a semantic child-document relationship and creates a parent-child edge in the Note graph; it does not change the file tree. Every Note must have at least one real `resource_ids` entry. The host writes sources into frontmatter and lists them discreetly at the very end, one per line, as a reference section. The Agent submits only body, title, parent, and source IDs, not host-managed fields.

The body may use native Markdown, including headings, lists, quotations, code fences, tables, formulas, and images. A Note is not an old-style container of concatenated materials. Understand, deduplicate, and reorganize Resources before writing a complete article. Distinguish user content, exact user quotations, and AI-organized content semantically. An AI paraphrase does not change who authored the original.

## 2. Read order and actions

Before any write, read Raw, Resource, and the target Note within scope. Use the runtime schema for parameters; do not infer undocumented fields from examples.

| Action | Purpose | Key inputs or receipt |
| --- | --- | --- |
| `raw_list` | Page through Raw candidates | Filter by host-supported scope; returns immutable `raw_sources` |
| `raw_get` | Read full Raw | `raw_id`; returns `raw`, `metadata`, and immutable marker |
| `resource_list` | Find reusable material | Returns Resources, `raw_ids`, and current `revision` |
| `resource_get` | Read one Resource | `resource_id`; returns full content, source lineage, and version |
| `resource_create` | Create AI material | `title`, `content`, real `raw_ids`; receipt has `resource_id`, `revision` |
| `resource_update` | Minimally revise material | `resource_id`, `title`, `content`, `raw_ids`, current `expected_revision`; a conflict does not write |
| `list` | Query Note candidates | `q`/`query`, `offset`, `limit`; returns title, path, Resource citations, revision/hash |
| `tree` | Read Note file tree | `tree` organized by real Markdown `path`; `parent_id` concerns semantic child relationship and graph only |
| `get` | Read full Note | `note_id`; returns `body_md`, revision/hash, Resource citations, links, backlinks, locks |
| `graph` | Read overall Note relationships | Returns nodes and edges of the current Note vault for the right sidebar, not a separate knowledge layer |
| `backlinks` | Read incoming links | `note_id`; reports resolved Note relationships only |
| `create` | Create Markdown Note | `title`, `body_md`, at least one real `resource_ids`; optional `note_id`/`path`/`parent_id`; receipt has path and revision/hash |
| `update` | Atomically update Markdown Note | `note_id`, complete `body_md`, `resource_ids`, current `expected_revision` and `expected_content_hash`; only success creates a version |

Raw capture, user selection locking and unlocking, and host metadata maintenance are not Agent actions. Do not put lock state, attribution, or the source tail into body parameters.

## 3. Sources, links, and graph

`Resource.raw_ids` links a Resource to Raw; `Note.resource_ids` links a Note to Resources. Use only IDs actually returned. If a source is invalid, mark it for verification instead of substituting a similar ID. External webpages and textbooks are supplemental sources, not proof that the user learned anything.

Use `[[note:<real Note ID>]]` for Note links and `[[node:<real node ID>]]` for links to knowledge nodes. An ordinary wikilink is acceptable only when the target is unique and verified. Explain what the link means and its boundary rather than batch-linking similar titles. Text in code fences, inline code, and math must not be parsed as relationships. Return an unresolved link for missing or ambiguous targets; do not invent one.

`parent_id` denotes only a semantic parent-child relationship. It neither determines the left file tree, nor equals a wikilink or learning prerequisite. The relationship graph shows both parent-child and Note wikilink edges in the current Note's right sidebar.

## 4. Editing, locks, and conflicts

The user can select and lock a span in the Note editor. This protects against Agent writes, while the user remains free to edit. After a user edit, the host reanchors the locked range using quoted text, surrounding context, and revision. Retain lock information returned by `get` but do not try to manage locks.

When a complete body edit overlaps a lock, the service returns `NOTE_REGION_LOCKED` with `reason`, `overlaps` (or `overlap`), and range information when possible. Keep the unsaved draft, explain the affected range and reason, and offer a suggestion or ask the user to handle it. Do not remove or split the overlap to bypass the lock, write to another equivalent Note, or retry an overwrite.

`REVISION_CONFLICT` means the Note or Resource version changed. `CONTENT_HASH_CONFLICT` or an external change means the Markdown file was edited after it was read. Reread the relevant Raw, Resource, and Note and compare the latest full text before making the smallest edit. On a timeout or unclear receipt, use `get` or `list` to determine whether the write occurred before retrying.

Say “created” or “updated” only after an explicit successful receipt whose target ID and revision/hash match the change. Otherwise say “draft,” “unsaved,” “conflict,” or “service unavailable,” and give an actionable next step.

## 5. Organization examples and evidence strength

One answered question can become a Note with the main claim and conditions, derivation steps, reusable example, common confusion, and genuine links to other Notes. One mark supports only “attention given”; one translation supports only “this content was processed.” A personal misconception requires actual exam evidence or an explicit user statement, and wording must not exceed that evidence.

A self-check question may appear in the body, but seeing it, reading its answer, generating a Resource, or organizing a Note does not trigger exam sign-off or prove mastery. Exam assessment still follows the exam flow.
