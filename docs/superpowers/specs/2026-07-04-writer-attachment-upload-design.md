# Core Agent Composer Syntax Design

Date: 2026-07-04
Status: Approved Core-first design; updated with `@` resource-reference and `/` command input rules; pending implementation plan

> 维护标注（2026-08-03）：Member 产品已归档至 `archive/members/`。本文中 `members/{member}/command` 等路径描述为设计时的架构约定，归档后不再有活跃 member 实现；Core 侧的通用命令、附件、skill 协议设计仍然有效。

维护标注：本设计最初从 Writer 附件上传入口提出。经架构确认后，附件上传不按 Writer 私有能力实现，而按 Core 的通用 Agent 基础能力实现；Writer 只是第一处产品落地入口。

维护标注（2026-07-04）：后续讨论把“附件上传入口”上移为通用 `@资源引用` 输入能力。附件上传按钮仍可存在，但语义应变成“在当前光标处插入一个已解析的 `@附件引用`”。手写 `@本地文件路径` 时，系统实时检测并高亮；检测不到真实资源时按普通文本处理，不报错、不阻断。

维护标注（2026-07-04）：后续讨论继续把 `/指令` 纳入同一套 Core Composer Syntax。`/skill-name`、`/compact`、`/fork` 属于通用 Agent 命令，放在 `core/command` 管理。Writer 这类 member 只在 `members/writer/command` 追加自己的命令，例如未来的 `/git ...`，不得把通用命令私有化。member 可以在自己的 command 配置中禁用指定 Core 命令；默认不禁用，且只影响当前 member。

## Goal

Add the first reliable composer syntax layer to the Core Agent base.

The first version lets a user reference local files from the composer text with `@...`. When the referenced resource can be confirmed, the UI highlights that span and the send path converts it to structured input at the same text position. When the candidate cannot be confirmed, it remains ordinary text.

The same layer also supports slash commands with `/...`. Core owns generic command syntax, command palette behavior, token rendering, and command contracts. Member products only register member-specific commands.

Attachment upload is one resolver/backend behavior under this input model. Writer receives the first product surface through the Core workbench/runtime path.

## Current Context

Writer already has most of the backend attachment surface, but it is not the target architecture boundary:

- A database table for attachments.
- Local storage under the session work root.
- REST upload, list, preview, download, and open routes.
- App-server operations for listing, reading, previewing, and opening attachments.
- Runtime context that can expose a session attachment index.

The implemented attachment loop is the base transport. The next missing product loop is the `@` reference input layer plus protocol closure:

- Core UI needs a composer reference parser that can detect `@` candidates without misreading email, code, or quoted text.
- Core UI needs the same parser to detect `/` commands without misreading paths, URLs, code, or quoted text.
- Core UI needs local highlighting for confirmed references. A plain textarea cannot style partial text, so the first version should use a synchronized highlight overlay rather than a full rich-text editor.
- Writer needs a resolver that can check whether a local file path exists without uploading or copying it during typing.
- Send still needs to convert confirmed references to ordered structured input blocks and bind accepted attachment IDs to the persisted user message.
- Writer already has a `session.fork` app-server operation and a UI button for session fork. `/fork` should call that existing path through the generic command contract, not create a parallel fork flow.
- Core runtime already has automatic context compaction and compaction display parts. `/compact` should expose a manual command path for that existing concept instead of inventing another history format.
- Skill discovery/loading already follows `SKILL.md` files under project, user, Core, and member roots. `/skill-name` should reuse that skill registry behavior and move the trigger to the user input layer.

## Mature-Solution Alignment

OpenAI's Responses API treats files as explicit input resources such as `input_file`, and long-document retrieval as a separate file-search/vector-store tool. Anthropic's current file support follows the same broad shape: upload or reference a file, then include the reference in a model request.

OpenAI Codex and Claude Code both use slash commands as a command-palette style control surface for agent sessions. Claude also exposes skills/custom commands as slash-invoked reusable behavior. LamTools should follow that split: `/` is an agent control/input affordance, while resource files stay explicit structured resources.

LamTools should follow the same resource-reference model. The first version should not paste file bodies into the user's text input and should not build a new retrieval platform. It should also avoid a Writer-only slash-command surface for generic agent actions.

References:

- OpenAI file inputs guide: https://developers.openai.com/api/docs/guides/file-inputs
- OpenAI file search guide: https://developers.openai.com/api/docs/guides/tools-file-search
- Anthropic file support overview: https://docs.anthropic.com/en/docs/build-with-claude/files
- OpenAI Codex slash commands: https://developers.openai.com/codex/cli/slash-commands
- Claude Code slash commands: https://docs.anthropic.com/en/docs/claude-code/commands
- Claude Code skills: https://code.claude.com/docs/en/skills

## Scope

In scope for the first `@` reference version:

- Parse legal `@` reference candidates in composer text.
- Ignore `@` candidates inside fenced code blocks, inline code, and quoted text.
- Ignore `@` when it is not at the start of input or immediately preceded by whitespace.
- Realtime-detect local-file candidates after input changes with debounce.
- Highlight confirmed local-file references.
- Treat unconfirmed, unsupported, or missing resources as ordinary text.
- Convert confirmed local-file references to ordered structured attachment input on send.
- Keep existing explicit file selection as a supported entry point, but insert an `@filename` anchor at the current cursor position after successful upload.
- Share parser fixtures between frontend and future CLI implementations.

In scope for the first `/` command version:

- Parse legal `/` command candidates in composer text.
- Ignore `/` candidates inside fenced code blocks, inline code, and quoted text.
- Ignore `/` when it is not at the start of input or immediately preceded by whitespace.
- Show a command palette when the user types `/` at a legal command boundary.
- Filter command palette items by the typed command fragment.
- Support mouse selection, Enter, Escape, and Up/Down navigation.
- Render selected skill tokens in pale blue inline with the input text.
- Resolve `/skill-name` from the generic skill registry and expand it to skill content at send/enqueue time.
- Execute `/compact` as a generic manual context-compaction command.
- Execute `/fork` as a generic session-fork command.
- Manage generic command definitions under `core/command`.
- Allow member-specific command definitions under `members/{member}/command`, for example future Writer `/git ...` commands.
- Allow a member to disable selected Core commands through `members/{member}/command/config.json`.
- Share slash-command parser fixtures between frontend and future CLI implementations.

Already in scope from the attachment transport layer:

- Select local files from the Core composer as used by Writer.
- Drag local files onto the composer.
- Upload files to the current agent session.
- Show uploaded files as pending attachments before send.
- Remove pending attachments before send.
- Send text plus attachment IDs in one accepted user message.
- Bind accepted attachment IDs to the persisted user message.
- Show message attachments in chat history.
- Preview text-like attachments and open non-text attachments through existing backend routes.
- Expose attachment metadata and stored local paths in Core runtime context.
- Preserve clear failure behavior.

Out of scope for this version:

- Rich-text chip editor.
- URL/webpage fetching.
- Directory references.
- Current-session resource-name search.
- Provider-native cloud file IDs.
- Automatic VLM model switching.
- OCR fallback.
- PDF, Word, spreadsheet, or image parsing.
- Vector search over uploaded files.
- Queueing messages that include attachments.
- Sharing attachments across sessions.
- Nested command grammars beyond one command plus optional command arguments.
- Member-specific commands beyond proving the registration boundary.
- User-authored custom slash command authoring UI.
- Slash commands inside CLI interactive mode, except shared parser/contract preparation.
- Command aliases beyond the canonical command names.

## `@` Reference Syntax

Only these forms enter reference parsing:

```text
@E:\tmp\a.txt
请看 @E:\tmp\a.txt
请看 @"E:\My Docs\a.txt"
请看 @'E:\My Docs\a.txt'
```

These forms are ordinary text:

```text
abc@E:\tmp\a.txt
email@example.com
"@E:\tmp\a.txt"
'@E:\tmp\a.txt'
“@E:\tmp\a.txt”
‘@E:\tmp\a.txt’
`@E:\tmp\a.txt`
```

Markdown fenced code blocks are ordinary text for reference parsing:

````text
```md
@E:\tmp\a.txt
```
````

The boundary rule is strict:

- `@` at input start is parseable.
- `@` after whitespace is parseable.
- `@` after any non-whitespace character is not parseable.

Unquoted references end at whitespace or one of these punctuation characters:

```text
，。；：！？、,.!?:;)]}）】》”
```

Quoted references use `@"..."` or `@'...'` and end at the matching quote. The quote wraps only the target; the `@` itself must still be outside quotes.

## `/` Command Syntax

Only these forms enter command parsing:

```text
/
/compact
/fork
/brainstorming
请用 /brainstorming 梳理一下
```

These forms are ordinary text:

```text
abc/compact
https://example.com/a/b
C:/tmp/a.txt
" /compact"
"/compact"
'/compact'
`/compact`
```

Markdown fenced code blocks are ordinary text for command parsing:

````text
```md
/compact
```
````

The boundary rule matches `@`:

- `/` at input start is parseable.
- `/` after whitespace is parseable.
- `/` after any non-whitespace character is not parseable.

Unquoted command names use lowercase kebab-case or underscore-style names:

```text
/skill-name
/compact
/fork
/git status
```

The command name ends at whitespace or punctuation. Text after the command name is command arguments only for commands that explicitly declare arguments. First-version Core commands do not need extra arguments.

Unknown commands are ordinary text unless the user selected a known command from the palette. This keeps `/tmp/path`, prose, and unfinished typing non-blocking.

Action commands are standalone in the first version:

- If the composer contains only `/compact` plus whitespace, sending or selecting it runs context compaction.
- If the composer contains only `/fork` plus whitespace, sending or selecting it runs session fork.
- If `/compact` or `/fork` appears inside a longer message, it is treated as ordinary text unless the user selected it from the palette and the UI explicitly runs the action.

Skill commands are insertable tokens:

- A skill command appears in the palette as `/skill-name`.
- Selecting it inserts a pale-blue `skill-name` token at the cursor.
- The visible composer remains concise; it does not paste the full skill body.
- At send or enqueue time, the backend resolves the token and expands it to the current skill content snapshot.
- If the user deletes the token text, the skill is no longer sent.

## Command Registry

Command definitions live in two layers:

- `core/command`: generic agent commands. First version includes dynamic `/skill-name`, `/compact`, and `/fork`.
- `members/{member}/command`: member-specific commands. Writer can later add `/git ...` here.

Core command names are reserved. A member command must not override a Core command with the same bare name. If a member needs a domain command, it should use a clear namespace such as `/git status`, not `/fork`.

Members may disable selected Core commands for their own product surface through a local config file:

```json
{
  "disabled_core_commands": ["fork"]
}
```

The config location is `members/{member}/command/config.json`.

Rules:

- Missing config means no Core command is disabled.
- Empty `disabled_core_commands` means no Core command is disabled.
- Disabling a Core command affects only that member.
- A disabled Core command is omitted from that member's command catalog and cannot be executed through the slash-command operation for that member.
- Disabled command names use bare names without `/`, for example `fork`, `compact`, or `skill-name`.
- Invalid or unknown disabled command names are ignored with diagnostics, not treated as fatal catalog errors.
- A member config cannot rename Core commands and cannot replace disabled Core commands with member commands of the same name.

The registry output is a command catalog, not product business logic embedded in Core UI. Each command entry should expose only:

- command name
- display title
- short description
- icon key
- source layer
- action type: `insert_token`, `run_action`, or `expand_on_send`
- whether it accepts arguments

Runtime execution can still be adapted by the active member while the command identity stays generic. For example, `/fork` is a Core command, but Writer may implement the current session fork through its existing app-server operation until session storage is fully Core-owned.

The command palette merges Core commands first and member commands second. Core commands appear above member commands when the typed filter matches both.

## Realtime Detection

Typing a legal `@` candidate does not upload or copy files.

Typing a legal `/` candidate does not send a message and does not run a command by itself.

The frontend parses candidates after input changes, then calls lightweight resolvers with debounce. The `@` resolver only checks whether a candidate is a confirmed resource. For the first version, only existing local files resolve. The `/` resolver reads the command catalog and filters available commands.

Input-state statuses:

- `pending`: detection is in progress.
- `resolved`: the candidate is a confirmed local file.
- `command`: the candidate is a known command or inserted command token.
- `plain`: the candidate is not a confirmed resource and should be rendered as ordinary text.

There is intentionally no `failed` state for missing files or unsupported targets. A missing file path, unsupported URL, or unmatched resource name should quietly return to ordinary text.

There is also no `failed` state for unknown slash text during typing. Unknown slash text stays ordinary text until the user selects a known command or submits a standalone known action command.

## User Experience

The composer uses text as the canonical visible representation. Confirmed references are highlighted in place. Because native textarea cannot color only part of its text, the first version should use a synchronized highlight overlay rather than replacing the composer with a rich-text editor.

When a user types `@E:\tmp\a.txt` and that file exists, the `@...` span changes to reference color. If the file does not exist, the text stays normal and sending is not blocked.

When a user types `/` at a legal command boundary, the command palette opens above the composer. The palette is visually similar to common Codex/Claude command menus: icon, command title, and short description in a compact list. The screenshot provided by the user is an example of density and behavior, not a pixel-perfect target.

Known skill tokens render in pale blue. Action commands do not need to remain in the input after execution. On success, `/compact` and `/fork` clear only the command text they consumed; unrelated user draft text is not discarded.

The `+` attachment button remains, but its semantics change:

1. User places the cursor in the textarea.
2. User selects a file with `+`.
3. Upload succeeds.
4. The composer inserts an `@filename` anchor at the cursor position.
5. The uploaded attachment row remains visible as supporting state.
6. Sending uses the `@filename` anchor position when constructing structured input.

If the user deletes the inserted `@filename` text, that uploaded attachment is no longer sent.

History shows attachments on the user message they belong to. Text-like files can be previewed. Other files can be opened with the system default app.

History should record action commands as session events when useful, not as user messages. A successful `/compact` may add a compaction event. A successful `/fork` switches to the forked session.

## Data Flow

Typed local-file reference path:

1. User types a legal `@` candidate.
2. Frontend parser finds the candidate if it is outside code and quotes.
3. Frontend asks Writer resolver whether the target is an existing local file.
4. Resolved candidates are highlighted. Plain candidates stay normal.
5. On send, frontend/backend re-parse the current text and re-check candidates.
6. Still-resolved local files are registered/copied as attachments.
7. The text is split into ordered structured input blocks.
8. Backend persists the user message with attachment references and binds attachment rows to that message.
9. Runtime receives the user text plus an attachment index containing filename, type, size, local path, and whether each attachment belongs to the current message or history.

Explicit upload path:

1. User selects or drops files in the composer.
2. Frontend uploads each file to the current session.
3. Backend stores the file under the session attachment directory and creates an attachment record.
4. Frontend inserts an `@filename` anchor at the current cursor position and stores returned attachment metadata in pending composer state.
5. User sends the message.
6. Frontend sends ordered text plus attachment references through the app-server turn start request.
7. Backend validates that each attachment belongs to the same session.
8. Backend persists the user message with attachment references and binds attachment rows to that message.

The app-server input should carry structured attachment references rather than only a separate hidden frontend state. A minimal input shape is:

```json
[
  { "type": "text", "text": "请总结 " },
  {
    "type": "attachment",
    "attachment_id": "uuid",
    "filename": "brief.md",
    "mime_type": "text/markdown",
    "preview_type": "text",
    "source_text": "@E:\\tmp\\brief.md"
  },
  { "type": "text", "text": " 的重点" }
]
```

The backend should still store canonical attachment IDs in message parts so old and new paths can read them consistently.

Skill command send path:

1. User types `/` and selects a skill.
2. Frontend inserts a pale-blue skill token at the current cursor position.
3. User sends the message or the message enters the text queue.
4. Backend re-parses the current text and command token metadata.
5. Backend resolves the skill against the generic skill registry.
6. If the skill exists, backend expands it to a structured prompt block at the token position.
7. The visible user message can keep the concise `/skill-name` token while the runtime receives the expanded skill content.

Manual compact path:

1. User chooses `/compact` or sends standalone `/compact`.
2. Frontend calls the generic command execution operation.
3. Backend runs manual context compaction for the active session.
4. Backend persists the resulting compaction summary/state.
5. UI shows a clear success event or a clear failure message.

Fork path:

1. User chooses `/fork` or sends standalone `/fork`.
2. Frontend calls the generic command execution operation.
3. Backend forks the active session using the existing session fork implementation for the active member.
4. UI inserts the forked session into the session list and switches to it.

## Failure Policy

Principle: if an action fails, stop that action and show a clear prompt. Do not silently continue with a weaker path.

Realtime detection miss:

- Do not show an error.
- Do not block sending.
- Treat the candidate as ordinary text.

Explicit upload failure:

- Stop the upload action.
- Mark the failed file clearly.
- Keep text and already uploaded pending attachments in place.
- Do not send a message until the user retries or removes the failed item.

Send failure before backend acceptance:

- Stop sending.
- Keep text and pending attachments in the composer.
- Show the error.

Send-time local-file registration failure:

- Stop sending only if the candidate had already been confirmed and entered the attachment registration path.
- Keep text and pending attachments in the composer.
- Show the error.

Send-time unconfirmed or missing `@` candidate:

- Treat it as ordinary text.
- Do not stop sending.

Unknown slash text:

- Treat it as ordinary text.
- Do not stop sending.
- Do not show an error while the user is typing.

Skill resolution failure after selecting a known skill:

- Stop sending or enqueueing.
- Keep the composer text and skill token in place.
- Show a clear error that the skill could not be loaded.

Action command failure:

- Stop the action.
- Keep any unrelated composer text intact.
- Show the command error clearly.
- Do not send a fallback user message containing the command text.

Runtime failure after backend acceptance:

- The message is already part of history.
- Do not put the text or attachments back into the composer.
- Show the failed run result in the conversation.

Running turn with attachment input:

- Do not enqueue attachment-bearing input in the current text-only queue.
- Stop the send action and tell the user to send the attachment message after the current turn finishes.
- Keep existing pure-text queue behavior unchanged.

Running turn with skill-token text input:

- Resolve the skill at enqueue time.
- If resolution succeeds, enqueue the expanded prompt snapshot.
- If resolution fails, stop enqueueing and keep the composer text.

Running turn with action commands:

- Do not enqueue `/compact` or `/fork`.
- Stop the action and tell the user to run it after the current turn finishes, unless the active runtime explicitly marks that action as safe while running.

## Image Attachments

Image attachments are allowed in the first version, but automatic model switching is not.

Behavior:

- If the current model is explicitly marked as not supporting image input, stop before sending and tell the user to choose an image-capable model.
- If the current model is explicitly marked as supporting image input, allow sending.
- If model capability is unknown, default to allowing the send.
- If the provider rejects the request because images are unsupported, stop the run and show the provider error.
- Do not auto-switch to a VLM model.
- Do not run OCR fallback.

The design should reserve model capability structure for later expansion, for example `input_modalities` or `supports_vision`. The first version may use existing model metadata when present and treat missing metadata as unknown.

## State Ownership

Resolved `@` candidates belong to the current composer text. They are cacheable UI state only; send-time parsing and validation must not trust stale frontend state.

Resolved `/` command candidates belong to the current composer text. Palette state is UI-only; execution and skill expansion must be validated again by the backend.

Pending explicit uploads belong to the composer for the active session.

Switching sessions should not leak pending attachments into another session. The simplest safe behavior is to clear pending attachments on session change and require the user to reattach files. This avoids accidental cross-session sends.

Accepted attachments belong to the persisted message and session history.

Executed action commands belong to session event history, not to the next user message.

## Testing

Parser fixture tests:

- `@E:\tmp\a.txt` at input start is a candidate.
- `请看 @E:\tmp\a.txt` is a candidate.
- `abc@E:\tmp\a.txt` is ordinary text.
- `email@example.com` is ordinary text.
- `"@E:\tmp\a.txt"` and `'@E:\tmp\a.txt'` are ordinary text.
- Chinese quotes around `@...` are ordinary text.
- Inline code containing `@...` is ordinary text.
- Fenced code blocks containing `@...` are ordinary text.
- `@"E:\My Docs\a.txt"` parses as one target.
- `/` at input start opens command parsing.
- `请用 /brainstorming 梳理一下` parses `/brainstorming` as a command candidate.
- `abc/compact`, `https://example.com/a/b`, and `C:/tmp/a.txt` are ordinary text.
- `"/compact"`, `'/compact'`, inline code, and fenced code blocks containing `/compact` are ordinary text.

Backend tests:

- Upload creates a sanitized stored file and attachment record.
- Local-file resolver returns resolved for existing files and plain for missing files.
- Accepted message binds attachment IDs to the user message.
- Attachment IDs from another session are rejected.
- Runtime attachment index marks current-message attachments correctly.
- Text preview truncates large files and handles UTF-8/GB18030/UTF-16 as today.
- Command catalog returns Core commands before member commands.
- Member commands cannot override Core command names.
- Missing member command config leaves all Core commands enabled.
- Member command config can disable selected Core commands for that member only.
- Disabled Core commands are not returned in that member's command catalog.
- Disabled Core commands cannot be executed through that member's slash-command operation.
- `/skill-name` resolves through the generic skill registry and expands into prompt content.
- Missing selected skill stops send/enqueue and preserves the draft.
- `/compact` runs manual context compaction and records a compaction event.
- `/fork` uses the existing session fork path and returns the forked session.
- Action commands are rejected while a turn is running unless explicitly safe.

Frontend tests:

- Typing an existing local-file reference highlights it after resolver success.
- Typing a missing local-file reference leaves it as ordinary text.
- Email, quoted text, inline code, and fenced code are not highlighted.
- Selecting a file uploads it and shows a pending row.
- Selecting a file inserts an `@filename` anchor at the current cursor position.
- Removing a pending attachment prevents it from being sent.
- Successful send clears pending attachments.
- Failed upload blocks send until resolved.
- Failed send before acceptance keeps text and attachments.
- Running turn with pending attachments shows the wait-until-finished prompt.
- Typing `/` at a legal boundary opens the command palette.
- Typing `/comp` filters the palette to `/compact`.
- Arrow keys, Enter, Escape, and mouse selection work.
- Selecting a skill inserts a pale-blue skill token at the current cursor.
- Selecting `/compact` executes the action instead of sending a user message.
- Selecting `/fork` executes the action and switches to the forked session on success.
- Unknown slash text remains ordinary text and can be sent.

Manual verification:

- Start Writer.
- Type an existing local file path as `@E:\path\file.txt` and confirm it becomes highlighted.
- Type a missing local file path as `@E:\path\missing.txt` and confirm it stays ordinary text.
- Type a real local path inside quotes, inline code, and a fenced code block and confirm it is not highlighted.
- Use `+` to upload a `.txt` file and confirm `@filename` is inserted at the cursor position.
- Send a message containing a confirmed `@` local-file reference.
- Confirm the user message shows the attachment.
- Confirm runtime can reference the stored local path.
- Upload an image with unknown model capability and confirm send is allowed.
- Use or simulate an explicitly non-image-capable model and confirm sending is blocked before runtime.
- Type `/` and confirm the command palette opens.
- Select a skill command and confirm the pale-blue token appears at the cursor.
- Send a message with a skill token and confirm the runtime receives expanded skill content.
- Run `/compact` and confirm no user message is sent.
- Run `/fork` and confirm a new session is created and selected.
