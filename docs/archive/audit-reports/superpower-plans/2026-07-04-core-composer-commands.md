# Core Composer Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Core-owned slash commands to the composer: `/skill-name`, `/compact`, `/fork`, and a command palette opened by typing `/`.

**Architecture:** Core owns composer syntax, slash-command metadata, and product-neutral command catalog merging. Writer is the first member adapter: it exposes Core commands through the existing app-server, delegates `/fork` to the existing session fork path, implements `/compact` against Writer session storage, and reuses the existing `SKILL.md` registry for skill expansion. Member command directories may add member commands or disable selected Core commands for that member only.

**Tech Stack:** Python 3.14, SQLAlchemy, LamTools Core app-server operation catalog, Vue 3, Pinia, Node 24.17+, npm 11.17+, Vitest and Node test runner.

## Global Constraints

- `core/` is the complete base Agent substrate. If a generic Agent should have the capability, it belongs in Core.
- `core/src/lamtools_core/` must stay product-neutral: no Writer/Artist product names, persona routing, or product branches.
- `/skill-name`, `/compact`, and `/fork` are Core commands, not Writer commands.
- Member commands live under `members/{member}/command`; member command names must not override Core command names.
- A member may disable Core commands only through `members/{member}/command/config.json`; missing config and an empty disabled list mean all Core commands stay enabled.
- Unknown slash text is ordinary text and must not block send.
- A selected command that fails must stop the action, keep draft text, and show a clear error.
- `/compact` and `/fork` are action commands and must not be queued while a turn is running.
- Skill tokens can be queued only after backend skill expansion succeeds; failure keeps the draft.
- First version uses a textarea plus highlight overlay/palette state. Do not introduce a rich-text editor.
- Attachment transport remains governed by `docs/superpowers/plans/2026-07-04-core-agent-attachments.md`; this plan only depends on its `CoreInputItem` shape and pending composer behavior.
- PowerShell commands involving Chinese text must use UTF-8-safe files, JSON escaping, or script Unicode escapes, not pipe/here-string Chinese bodies.

---

## File Structure

- Create `core/ui/src/composer/syntax.ts`: product-neutral parser for `@` references and `/` command candidates outside code and quotes.
- Create `core/ui/tests/composer-syntax.test.ts`: parser fixture tests for legal/ordinary `@` and `/` forms.
- Modify `core/ui/src/types.ts`: add command catalog, command token, and skill input item types.
- Create `core/ui/src/components/CommandPalette.vue`: compact slash command menu with keyboard and mouse selection.
- Create `core/ui/src/composables/useComposerCommandPalette.ts`: textarea cursor tracking, filtering, active item, token insertion, and action selection.
- Modify `core/ui/src/index.ts`: export parser, component, composable, and types.
- Create `core/command/compact.json`: Core command definition for manual context compaction.
- Create `core/command/fork.json`: Core command definition for session fork.
- Create `core/src/lamtools_core/composer_commands.py`: product-neutral command dataclasses and catalog merge/disable logic.
- Create `core/tests/test_composer_commands.py`: Core command catalog tests, including member disable config.
- Create `members/writer/backend/app/services/command_service.py`: Writer adapter for command catalog and command execution.
- Create `members/writer/backend/app/services/composer_input_service.py`: backend parser for skill input items and runtime text expansion.
- Create `members/writer/backend/app/services/session_compaction_service.py`: deterministic manual session compaction.
- Modify `members/writer/backend/app/services/runtime_input_context.py`: prepend persisted compaction summary and omit compacted messages from future runtime history.
- Modify `members/writer/backend/app/app_server/operations.py`: register `command.catalog`, `command.execute`, and expand skills in `turn.start`/`queue.create`.
- Modify `members/writer/backend/app/app_server/connection.py`: pass new command handlers into the operation catalog.
- Modify `members/writer/backend/tests/test_writer_app_server_protocol.py`: command catalog, execution, skill expansion, queue, and disabled command tests.
- Modify `members/writer/backend/tests/test_tool_contracts.py`: keep `WriterSkillRegistry` expectations aligned if a helper becomes shared.
- Modify `members/writer/frontend/src/appServer/protocol.ts`: add `WriterSkillInputItem` and command response types.
- Modify `members/writer/frontend/src/appServer/store.ts`: add `listCommands`, `executeCommand`, and allow skill input items in `startTurn`.
- Modify `members/writer/frontend/src/api/index.ts`: add one-shot app-server command catalog/execute wrappers for view startup before the persistent socket is connected.
- Modify `members/writer/frontend/src/views/CoreWorkbenchView.vue`: wire parser, command palette, token rendering, `/compact`, `/fork`, and skill send/queue behavior.
- Modify `members/writer/frontend/tests/appServer/store.test.ts`: command operation and skill item transport tests.

---

### Task 1: Core UI Composer Syntax Parser

**Files:**
- Create: `core/ui/src/composer/syntax.ts`
- Create: `core/ui/tests/composer-syntax.test.ts`
- Modify: `core/ui/src/index.ts`

**Interfaces:**
- Produces: `ComposerSyntaxSpan`
- Produces: `parseComposerSyntax(text: string): ComposerSyntaxSpan[]`
- Produces: `findActiveSlashCandidate(text: string, cursor: number): ComposerSyntaxSpan | null`
- Consumed by: Task 2 palette state and Task 7 Writer composer integration.

- [ ] **Step 1: Write the failing parser tests**

Add `core/ui/tests/composer-syntax.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { findActiveSlashCandidate, parseComposerSyntax } from '../src/composer/syntax'

describe('parseComposerSyntax', () => {
  it('parses slash commands only at input start or after whitespace', () => {
    expect(parseComposerSyntax('/compact')).toMatchObject([
      { kind: 'slash', start: 0, end: 8, value: 'compact' },
    ])
    expect(parseComposerSyntax('请用 /brainstorming 梳理一下')).toMatchObject([
      { kind: 'slash', value: 'brainstorming' },
    ])
    expect(parseComposerSyntax('abc/compact')).toEqual([])
    expect(parseComposerSyntax('https://example.com/a/b')).toEqual([])
    expect(parseComposerSyntax('C:/tmp/a.txt')).toEqual([])
  })

  it('ignores slash commands inside quotes and markdown code', () => {
    expect(parseComposerSyntax('"/compact"')).toEqual([])
    expect(parseComposerSyntax("'/compact'")).toEqual([])
    expect(parseComposerSyntax('`/compact`')).toEqual([])
    expect(parseComposerSyntax('```md\n/compact\n```')).toEqual([])
  })

  it('keeps at-resource parsing aligned with slash parsing', () => {
    expect(parseComposerSyntax('@E:\\tmp\\a.txt')).toMatchObject([
      { kind: 'resource', value: 'E:\\tmp\\a.txt' },
    ])
    expect(parseComposerSyntax('abc@E:\\tmp\\a.txt')).toEqual([])
    expect(parseComposerSyntax('email@example.com')).toEqual([])
    expect(parseComposerSyntax('`@E:\\tmp\\a.txt`')).toEqual([])
  })

  it('finds the active slash candidate at the cursor', () => {
    const text = '请用 /comp'
    expect(findActiveSlashCandidate(text, text.length)).toMatchObject({
      kind: 'slash',
      value: 'comp',
    })
    expect(findActiveSlashCandidate('abc/comp', 8)).toBeNull()
  })
})
```

- [ ] **Step 2: Run the parser tests and confirm they fail**

Run:

```powershell
Push-Location core\ui
npx vitest run tests\composer-syntax.test.ts
Pop-Location
```

Expected: FAIL because `../src/composer/syntax` does not exist.

- [ ] **Step 3: Implement the parser**

Create `core/ui/src/composer/syntax.ts`:

```ts
export type ComposerSyntaxKind = 'resource' | 'slash'

export interface ComposerSyntaxSpan {
  kind: ComposerSyntaxKind
  start: number
  end: number
  raw: string
  value: string
  quoted: boolean
}

const RESOURCE_STOP = new Set('，。；：！？、,.!?:;)]}）】》”'.split(''))
const COMMAND_NAME = /^[A-Za-z0-9_-]$/
const QUOTES = new Set(['"', "'", '“', '”', '‘', '’'])

export function parseComposerSyntax(text: string): ComposerSyntaxSpan[] {
  const spans: ComposerSyntaxSpan[] = []
  let inlineCode = false
  let quote: string | null = null
  let fence = false
  let lineStart = true

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i]
    const next3 = text.slice(i, i + 3)

    if (lineStart && next3 === '```') {
      fence = !fence
      i += 2
      lineStart = false
      continue
    }

    if (ch === '\n') {
      lineStart = true
      continue
    }
    if (lineStart && ch !== '\r') lineStart = false
    if (fence) continue

    if (ch === '`') {
      inlineCode = !inlineCode
      continue
    }
    if (inlineCode) continue

    if (quote) {
      if (matchesQuoteClose(quote, ch)) quote = null
      continue
    }
    if (QUOTES.has(ch)) {
      quote = ch
      continue
    }

    if ((ch === '@' || ch === '/') && isSyntaxBoundary(text, i)) {
      const span = ch === '@' ? parseResource(text, i) : parseSlash(text, i)
      if (span) {
        spans.push(span)
        i = span.end - 1
      }
    }
  }

  return spans
}

export function findActiveSlashCandidate(text: string, cursor: number): ComposerSyntaxSpan | null {
  return parseComposerSyntax(text).find(span =>
    span.kind === 'slash' && span.start < cursor && cursor <= span.end,
  ) ?? null
}

function isSyntaxBoundary(text: string, index: number): boolean {
  return index === 0 || /\s/.test(text[index - 1] ?? '')
}

function matchesQuoteClose(open: string, close: string): boolean {
  if (open === '“') return close === '”'
  if (open === '‘') return close === '’'
  return open === close
}

function parseResource(text: string, start: number): ComposerSyntaxSpan | null {
  const first = text[start + 1]
  if (!first) return null
  if (first === '"' || first === "'") {
    const close = text.indexOf(first, start + 2)
    if (close === -1) return null
    const raw = text.slice(start, close + 1)
    return { kind: 'resource', start, end: close + 1, raw, value: text.slice(start + 2, close), quoted: true }
  }
  let end = start + 1
  while (end < text.length) {
    const ch = text[end]
    if (/\s/.test(ch) || RESOURCE_STOP.has(ch)) break
    end += 1
  }
  if (end === start + 1) return null
  const raw = text.slice(start, end)
  return { kind: 'resource', start, end, raw, value: raw.slice(1), quoted: false }
}

function parseSlash(text: string, start: number): ComposerSyntaxSpan | null {
  let end = start + 1
  while (end < text.length && COMMAND_NAME.test(text[end])) end += 1
  const raw = text.slice(start, end)
  return { kind: 'slash', start, end, raw, value: raw.slice(1), quoted: false }
}
```

- [ ] **Step 4: Export parser helpers**

Modify `core/ui/src/index.ts`:

```ts
export {
  parseComposerSyntax,
  findActiveSlashCandidate,
  type ComposerSyntaxKind,
  type ComposerSyntaxSpan,
} from './composer/syntax';
```

- [ ] **Step 5: Run tests and checkpoint**

Run:

```powershell
Push-Location core\ui
npx vitest run tests\composer-syntax.test.ts
npm run test:contract
Pop-Location
```

Expected: PASS.

Checkpoint command for execution mode:

```powershell
git add core/ui/src/composer/syntax.ts core/ui/src/index.ts core/ui/tests/composer-syntax.test.ts
git commit -m "feat(core-ui): parse composer slash syntax"
```

---

### Task 2: Core UI Command Palette And Token Types

**Files:**
- Modify: `core/ui/src/types.ts`
- Create: `core/ui/src/components/CommandPalette.vue`
- Create: `core/ui/src/composables/useComposerCommandPalette.ts`
- Create: `core/ui/tests/command-palette.test.ts`
- Modify: `core/ui/src/index.ts`

**Interfaces:**
- Consumes: `ComposerSyntaxSpan`, `findActiveSlashCandidate`
- Produces: `CoreCommandCatalogItem`, `CoreCommandToken`, `CoreSkillInputItem`
- Produces: `useComposerCommandPalette(options)`
- Consumed by: Task 7 Writer workbench UI.

- [ ] **Step 1: Write failing UI tests**

Create `core/ui/tests/command-palette.test.ts`:

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CommandPalette from '../src/components/CommandPalette.vue'

const commands = [
  { name: 'compact', title: '压缩上下文', description: '压缩当前会话上下文', icon: 'archive', source: 'core', action: 'run_action' },
  { name: 'fork', title: '分叉', description: '从当前会话分叉', icon: 'git-branch', source: 'core', action: 'run_action' },
  { name: 'brainstorming', title: 'brainstorming', description: '梳理需求', icon: 'sparkles', source: 'core', action: 'insert_token' },
]

describe('CommandPalette', () => {
  it('renders commands and emits select', async () => {
    const wrapper = mount(CommandPalette, {
      props: { commands, activeIndex: 0 },
    })
    expect(wrapper.text()).toContain('/compact')
    await wrapper.find('[data-command-name="compact"]').trigger('mousedown')
    expect(wrapper.emitted('select')?.[0]?.[0]).toMatchObject({ name: 'compact' })
  })
})
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
Push-Location core\ui
npx vitest run tests\command-palette.test.ts
Pop-Location
```

Expected: FAIL because `CommandPalette.vue` does not exist.

- [ ] **Step 3: Add command types**

Modify `core/ui/src/types.ts`:

```ts
export type CoreCommandSource = 'core' | 'member';
export type CoreCommandAction = 'insert_token' | 'run_action' | 'expand_on_send';

export interface CoreCommandCatalogItem {
  name: string;
  title: string;
  description: string;
  icon: string;
  source: CoreCommandSource;
  action: CoreCommandAction;
  accepts_args?: boolean;
  disabled?: boolean;
  metadata?: Record<string, unknown>;
}

export interface CoreCommandToken {
  type: 'command_token';
  command: string;
  name: string;
  source_text: string;
  start: number;
  end: number;
}

export interface CoreSkillInputItem {
  type: 'skill';
  name: string;
  source_text?: string;
}
```

Extend `CoreInputItem`:

```ts
export type CoreInputItem =
  | { type: 'text'; text: string }
  | CoreAttachmentInputItem
  | CoreSkillInputItem;
```

- [ ] **Step 4: Add `CommandPalette.vue`**

Create `core/ui/src/components/CommandPalette.vue`:

```vue
<template>
  <div v-if="commands.length" class="command-palette" role="listbox" aria-label="命令">
    <button
      v-for="(command, index) in commands"
      :key="command.name"
      class="command-item"
      :class="{ active: index === activeIndex }"
      type="button"
      role="option"
      :aria-selected="index === activeIndex"
      :data-command-name="command.name"
      @mousedown.prevent="$emit('select', command)"
    >
      <span class="command-icon">{{ iconLabel(command.icon) }}</span>
      <span class="command-copy">
        <strong>/{{ command.name }}</strong>
        <small>{{ command.description }}</small>
      </span>
    </button>
  </div>
</template>

<script setup lang="ts">
import type { CoreCommandCatalogItem } from '../types'

defineProps<{
  commands: CoreCommandCatalogItem[]
  activeIndex: number
}>()

defineEmits<{
  select: [command: CoreCommandCatalogItem]
}>()

function iconLabel(icon: string): string {
  if (icon === 'git-branch') return '⑂'
  if (icon === 'archive') return '□'
  if (icon === 'sparkles') return '*'
  return '/'
}
</script>

<style scoped>
.command-palette {
  position: absolute;
  left: 0;
  right: 0;
  bottom: calc(100% + 8px);
  max-height: 280px;
  overflow: auto;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text, currentColor) 16%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--theme-composer-background, #111) 96%, black);
  padding: 6px;
  box-shadow: 0 18px 38px rgba(0, 0, 0, 0.28);
  z-index: 20;
}
.command-item {
  width: 100%;
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  border: 0;
  border-radius: 8px;
  padding: 8px;
  background: transparent;
  color: var(--theme-composer-text, currentColor);
  text-align: left;
}
.command-item.active,
.command-item:hover {
  background: color-mix(in srgb, var(--theme-composer-text, currentColor) 10%, transparent);
}
.command-icon {
  display: grid;
  place-items: center;
  color: color-mix(in srgb, var(--theme-composer-text, currentColor) 70%, transparent);
}
.command-copy {
  min-width: 0;
  display: grid;
  gap: 2px;
}
.command-copy strong,
.command-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.command-copy small {
  color: color-mix(in srgb, var(--theme-composer-text, currentColor) 62%, transparent);
}
</style>
```

- [ ] **Step 5: Add palette composable**

Create `core/ui/src/composables/useComposerCommandPalette.ts`:

```ts
import { computed, ref, type Ref } from 'vue'
import { findActiveSlashCandidate } from '../composer/syntax'
import type { CoreCommandCatalogItem } from '../types'

export interface ComposerCommandPaletteOptions {
  text: Ref<string>
  cursor: Ref<number>
  commands: Ref<CoreCommandCatalogItem[]>
}

export function useComposerCommandPalette(options: ComposerCommandPaletteOptions) {
  const activeIndex = ref(0)

  const activeSlash = computed(() => findActiveSlashCandidate(options.text.value, options.cursor.value))
  const filteredCommands = computed(() => {
    const span = activeSlash.value
    if (!span) return []
    const query = span.value.toLowerCase()
    return options.commands.value
      .filter(command => command.name.toLowerCase().startsWith(query))
      .slice(0, 12)
  })
  const open = computed(() => filteredCommands.value.length > 0)

  function move(delta: number) {
    const total = filteredCommands.value.length
    if (!total) return
    activeIndex.value = (activeIndex.value + delta + total) % total
  }

  function selected(): CoreCommandCatalogItem | null {
    return filteredCommands.value[activeIndex.value] ?? null
  }

  function reset() {
    activeIndex.value = 0
  }

  return { activeSlash, filteredCommands, open, activeIndex, move, selected, reset }
}
```

- [ ] **Step 6: Export component and composable**

Modify `core/ui/src/index.ts`:

```ts
export { default as CommandPalette } from './components/CommandPalette.vue';
export { useComposerCommandPalette } from './composables/useComposerCommandPalette';
export type {
  CoreCommandSource,
  CoreCommandAction,
  CoreCommandCatalogItem,
  CoreCommandToken,
  CoreSkillInputItem,
} from './types';
```

- [ ] **Step 7: Run tests and checkpoint**

Run:

```powershell
Push-Location core\ui
npx vitest run tests\command-palette.test.ts tests\composer-syntax.test.ts
npm run build
Pop-Location
```

Expected: PASS.

Checkpoint command for execution mode:

```powershell
git add core/ui/src/types.ts core/ui/src/components/CommandPalette.vue core/ui/src/composables/useComposerCommandPalette.ts core/ui/src/index.ts core/ui/tests/command-palette.test.ts
git commit -m "feat(core-ui): add composer command palette"
```

---

### Task 3: Core Command Catalog Loader

**Files:**
- Create: `core/command/compact.json`
- Create: `core/command/fork.json`
- Create: `core/src/lamtools_core/composer_commands.py`
- Create: `core/tests/test_composer_commands.py`
- Modify: `core/src/lamtools_core/__init__.py`

**Interfaces:**
- Produces: `ComposerCommandDefinition`
- Produces: `load_command_catalog(core_roots: list[Path], member_roots: list[Path]) -> list[ComposerCommandDefinition]`
- Produces: `load_disabled_core_commands(member_roots: list[Path]) -> set[str]`
- Consumed by: Task 4 Writer command service.

- [ ] **Step 1: Add failing catalog tests**

Create `core/tests/test_composer_commands.py`:

```python
from pathlib import Path

from lamtools_core.composer_commands import load_command_catalog


def write_json(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_catalog_loads_core_before_member_and_blocks_overrides(tmp_path: Path):
    core = tmp_path / "core"
    member = tmp_path / "members" / "writer"
    write_json(core / "command" / "compact.json", '{"name":"compact","title":"Compact","description":"Core compact","icon":"archive","action":"run_action"}')
    write_json(member / "command" / "git-status.json", '{"name":"git status","title":"Git status","description":"Show git status","icon":"git-branch","action":"run_action"}')
    write_json(member / "command" / "compact.json", '{"name":"compact","title":"Bad","description":"Override","icon":"x","action":"run_action"}')

    catalog = load_command_catalog(core_roots=[core], member_roots=[member])

    assert [item.name for item in catalog] == ["compact", "git status"]
    assert catalog[0].source == "core"
    assert catalog[1].source == "member"


def test_member_config_disables_core_command_for_that_member(tmp_path: Path):
    core = tmp_path / "core"
    writer = tmp_path / "members" / "writer"
    artist = tmp_path / "members" / "artist"
    write_json(core / "command" / "fork.json", '{"name":"fork","title":"Fork","description":"Fork session","icon":"git-branch","action":"run_action"}')
    write_json(writer / "command" / "config.json", '{"disabled_core_commands":["fork","unknown"]}')

    writer_catalog = load_command_catalog(core_roots=[core], member_roots=[writer])
    artist_catalog = load_command_catalog(core_roots=[core], member_roots=[artist])

    assert [item.name for item in writer_catalog] == []
    assert [item.name for item in artist_catalog] == ["fork"]
```

- [ ] **Step 2: Run failing Core tests**

Run:

```powershell
py -3.14 -m pytest core\tests\test_composer_commands.py -q
```

Expected: FAIL because `lamtools_core.composer_commands` does not exist.

- [ ] **Step 3: Add Core command resource files**

Create `core/command/compact.json`:

```json
{
  "name": "compact",
  "title": "压缩上下文",
  "description": "压缩当前会话上下文",
  "icon": "archive",
  "action": "run_action",
  "accepts_args": false
}
```

Create `core/command/fork.json`:

```json
{
  "name": "fork",
  "title": "分叉",
  "description": "从当前会话创建分叉",
  "icon": "git-branch",
  "action": "run_action",
  "accepts_args": false
}
```

- [ ] **Step 4: Implement command catalog loader**

Create `core/src/lamtools_core/composer_commands.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CommandAction = Literal["insert_token", "run_action", "expand_on_send"]
CommandSource = Literal["core", "member"]


@dataclass(frozen=True)
class ComposerCommandDefinition:
    name: str
    title: str
    description: str
    icon: str
    action: CommandAction
    source: CommandSource
    accepts_args: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "icon": self.icon,
            "action": self.action,
            "source": self.source,
            "accepts_args": self.accepts_args,
        }


def load_command_catalog(*, core_roots: list[Path], member_roots: list[Path]) -> list[ComposerCommandDefinition]:
    disabled = load_disabled_core_commands(member_roots)
    core_commands = [
        item for item in _load_definitions(core_roots, source="core")
        if item.name not in disabled
    ]
    core_names = {item.name for item in core_commands}
    member_commands = [
        item for item in _load_definitions(member_roots, source="member")
        if item.name not in core_names
    ]
    return [*core_commands, *member_commands]


def load_disabled_core_commands(member_roots: list[Path]) -> set[str]:
    disabled: set[str] = set()
    for root in member_roots:
        config = root / "command" / "config.json"
        if not config.is_file():
            continue
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        raw = data.get("disabled_core_commands") if isinstance(data, dict) else None
        if isinstance(raw, list):
            disabled.update(_normalize_name(item) for item in raw if _normalize_name(item))
    return disabled


def _load_definitions(roots: list[Path], *, source: CommandSource) -> list[ComposerCommandDefinition]:
    seen: set[str] = set()
    commands: list[ComposerCommandDefinition] = []
    for root in roots:
        command_dir = root / "command"
        if not command_dir.is_dir():
            continue
        for path in sorted(command_dir.glob("*.json")):
            if path.name == "config.json":
                continue
            command = _read_definition(path, source=source)
            if command is None or command.name in seen:
                continue
            seen.add(command.name)
            commands.append(command)
    return commands


def _read_definition(path: Path, *, source: CommandSource) -> ComposerCommandDefinition | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    name = _normalize_name(data.get("name"))
    if not name:
        return None
    action = str(data.get("action") or "run_action")
    if action not in {"insert_token", "run_action", "expand_on_send"}:
        return None
    return ComposerCommandDefinition(
        name=name,
        title=str(data.get("title") or name),
        description=str(data.get("description") or ""),
        icon=str(data.get("icon") or "/"),
        action=action,  # type: ignore[arg-type]
        source=source,
        accepts_args=bool(data.get("accepts_args") or False),
    )


def _normalize_name(value: object) -> str:
    raw = str(value or "").strip().lstrip("/")
    return " ".join(raw.split()).lower()
```

- [ ] **Step 5: Export Core command types**

Modify `core/src/lamtools_core/__init__.py`:

```python
from lamtools_core.composer_commands import (
    ComposerCommandDefinition,
    load_command_catalog,
    load_disabled_core_commands,
)
```

- [ ] **Step 6: Run tests and checkpoint**

Run:

```powershell
py -3.14 -m pytest core\tests\test_composer_commands.py -q
py -3.14 -m pytest core\tests -q
```

Expected: PASS.

Checkpoint command for execution mode:

```powershell
git add core/command core/src/lamtools_core/composer_commands.py core/src/lamtools_core/__init__.py core/tests/test_composer_commands.py
git commit -m "feat(core): add composer command catalog"
```

---

### Task 4: Writer Command Catalog, Skill Expansion, And App-Server Operations

**Files:**
- Create: `members/writer/backend/app/services/command_service.py`
- Create: `members/writer/backend/app/services/composer_input_service.py`
- Modify: `members/writer/backend/app/app_server/operations.py`
- Modify: `members/writer/backend/app/app_server/connection.py`
- Modify: `members/writer/backend/app/app_server/queue.py`
- Modify: `members/writer/backend/app/app_server/runtime_context.py`
- Modify: `members/writer/backend/tests/test_writer_app_server_protocol.py`

**Interfaces:**
- Consumes: `load_command_catalog`, `WriterSkillRegistry`, `fork_session_response`
- Produces: `writer_command_catalog(work_root: str | Path | None) -> list[dict[str, object]]`
- Produces: `prepare_composer_input(work_root, input_items) -> PreparedComposerInput`
- Produces JSON-RPC methods: `command.catalog`, `command.execute`
- Consumed by: Task 6 frontend store and Task 7 Writer view.

- [ ] **Step 1: Add failing backend protocol tests**

Append to `members/writer/backend/tests/test_writer_app_server_protocol.py`:

```python
@pytest.mark.asyncio
async def test_command_catalog_includes_core_and_dynamic_skills(tmp_path, monkeypatch):
    skill_dir = tmp_path / ".codex" / "skills" / "reviewer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: reviewer\ndescription: Review code\n---\nREVIEW BODY\n",
        encoding="utf-8",
    )

    outcome = await handle_command_catalog_operation(
        request_id=1,
        params={"work_root": str(tmp_path)},
    )

    names = [item["name"] for item in outcome.response["result"]["commands"]]
    assert "compact" in names
    assert "fork" in names
    assert "reviewer" in names


@pytest.mark.asyncio
async def test_turn_start_expands_selected_skill_without_changing_visible_message(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'skill-turn.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    skill_dir = tmp_path / ".codex" / "skills" / "reviewer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: reviewer\ndescription: Review code\n---\nREVIEW BODY\n",
        encoding="utf-8",
    )

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-skill", title="Skill", work_root=str(tmp_path)))
            await db.commit()

        outcome = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-skill",
                "client_message_id": "client-skill",
                "work_root": str(tmp_path),
                "input": [
                    {"type": "text", "text": "请 "},
                    {"type": "skill", "name": "reviewer", "source_text": "/reviewer"},
                    {"type": "text", "text": " 这个改动"},
                ],
            },
            session_factory=session_factory,
        )

        assert "error" not in outcome.response
        assert outcome.runtime_start["text"].find("REVIEW BODY") >= 0
        async with session_factory() as db:
            message = (await db.execute(select(WriterMessage))).scalar_one()
            assert message.content == "请 /reviewer 这个改动"
    finally:
        await engine.dispose()
```

- [ ] **Step 2: Run failing protocol tests**

Run:

```powershell
py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py -k "command_catalog or skill" -q
```

Expected: FAIL because command operations and skill input expansion do not exist.

- [ ] **Step 3: Implement Writer command catalog service**

Create `members/writer/backend/app/services/command_service.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.resource_dirs import core_resource_roots, writer_resource_roots
from app.core.writer.skills import WriterSkillRegistry
from app.models.session import WriterSession
from app.services.session_fork_service import fork_session_response
from app.services.session_compaction_service import compact_session_context_response
from lamtools_core.composer_commands import ComposerCommandDefinition, load_command_catalog
from sqlalchemy.ext.asyncio import AsyncSession


def writer_command_catalog(work_root: str | Path | None) -> list[dict[str, Any]]:
    commands = load_command_catalog(
        core_roots=core_resource_roots(),
        member_roots=writer_resource_roots(),
    )
    return [item.to_dict() for item in [*commands, *_skill_commands(work_root)]]


async def execute_writer_command(
    db: AsyncSession,
    *,
    session_id: str,
    command: str,
    work_root: str | Path | None = None,
) -> dict[str, Any]:
    name = command.strip().lstrip("/").lower()
    available = {item["name"] for item in writer_command_catalog(work_root)}
    if name not in available:
        raise ValueError(f"Command not available: {name}")
    if name == "fork":
        session = await db.get(WriterSession, session_id)
        title = f"{session.title if session else 'Session'} fork"
        forked = await fork_session_response(db, session_id, title=title, isolated_worktree=True)
        return {"status": "forked", "session": forked}
    if name == "compact":
        result = await compact_session_context_response(db, session_id=session_id)
        return {"status": "compacted", "compaction": result}
    raise ValueError(f"Command is not executable as an action: {name}")


def _skill_commands(work_root: str | Path | None) -> list[ComposerCommandDefinition]:
    return [
        ComposerCommandDefinition(
            name=skill.name,
            title=skill.name,
            description=skill.description,
            icon="sparkles",
            action="insert_token",
            source="core",
            accepts_args=False,
        )
        for skill in WriterSkillRegistry().available(work_root)
    ]
```

- [ ] **Step 4: Implement composer input preparation**

Create `members/writer/backend/app/services/composer_input_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.writer.skills import WriterSkillRegistry


@dataclass(frozen=True)
class PreparedComposerInput:
    visible_items: list[dict[str, Any]]
    runtime_items: list[dict[str, Any]]
    visible_text: str
    runtime_text: str


def prepare_composer_input(
    *,
    work_root: str | Path | None,
    input_items: list[dict[str, Any]],
) -> PreparedComposerInput:
    visible_items: list[dict[str, Any]] = []
    runtime_items: list[dict[str, Any]] = []
    visible_parts: list[str] = []
    runtime_parts: list[str] = []
    registry = WriterSkillRegistry()

    for item in input_items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "skill":
            name = str(item.get("name") or "").strip()
            if not name:
                raise ValueError("skill name is required")
            content = registry.load_prompt_content(work_root, name)
            if content.startswith('Skill "') and "not found" in content:
                raise ValueError(content)
            source_text = str(item.get("source_text") or f"/{name}")
            visible_items.append({"type": "text", "text": source_text})
            runtime_items.append({"type": "text", "text": content})
            visible_parts.append(source_text)
            runtime_parts.append(content)
            continue
        visible_items.append(item)
        runtime_items.append(item)
        if item_type == "text":
            text = str(item.get("text") or "")
            visible_parts.append(text)
            runtime_parts.append(text)

    return PreparedComposerInput(
        visible_items=visible_items,
        runtime_items=runtime_items,
        visible_text="".join(visible_parts).strip(),
        runtime_text="".join(runtime_parts).strip(),
    )
```

- [ ] **Step 5: Wire operations**

Modify `members/writer/backend/app/app_server/operations.py`:

```python
from app.services.command_service import execute_writer_command, writer_command_catalog
from app.services.composer_input_service import prepare_composer_input
```

Add parameters to `build_writer_operation_catalog`:

```python
    command_catalog: OperationRpcHandler,
    command_execute: OperationRpcHandler,
```

Register:

```python
    catalog.register("command.catalog", _handler(command_catalog))
    catalog.register("command.execute", _handler(command_execute))
```

Add handlers:

```python
async def handle_command_catalog_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
) -> WriterOperationOutcome:
    work_root = params.get("work_root") or params.get("workRoot")
    return WriterOperationOutcome(
        response=rpc_result(request_id, {"commands": writer_command_catalog(work_root if isinstance(work_root, str) else None)})
    )


async def handle_command_execute_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or "")
    command = str(params.get("command") or "")
    if not session_id or not command:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id and command are required"))
    try:
        async with session_factory() as db:
            result = await execute_writer_command(
                db,
                session_id=session_id,
                command=command,
                work_root=params.get("work_root") or params.get("workRoot"),
            )
            snapshot = await load_snapshot(db, session_id)
            await db.commit()
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"result": result, "snapshot": snapshot}))
```

Update `handle_turn_start_operation` before `accept_turn_start`:

```python
        prepared = prepare_composer_input(
            work_root=params.get("work_root") or params.get("workRoot") or session.work_root,
            input_items=input_items,
        )
        events = await accept_turn_start(
            db,
            thread_id=thread_id,
            client_message_id=client_message_id,
            input_items=prepared.visible_items,
            work_root=params.get("work_root") or params.get("workRoot"),
        )
```

Update `runtime_start`:

```python
            "text": prepared.runtime_text,
            "attachment_ids": input_attachment_ids(prepared.runtime_items),
```

Update `handle_queue_create_operation` so skills are expanded before queue acceptance:

```python
        session = await db.get(WriterSession, thread_id)
        work_root = session.work_root if session is not None else None
        prepared = prepare_composer_input(work_root=work_root, input_items=input_items)
        events = await accept_queue_item(
            db,
            thread_id=thread_id,
            client_message_id=client_message_id,
            input_items=prepared.runtime_items,
            mode=str(params.get("mode") or "next_turn"),
        )
```

- [ ] **Step 6: Wire connection catalog**

Modify `members/writer/backend/app/app_server/connection.py` imports and `_operation_catalog` call:

```python
from app.app_server.operations import (
    handle_command_catalog_operation,
    handle_command_execute_operation,
)
```

Pass:

```python
            command_catalog=self._command_catalog,
            command_execute=self._command_execute,
```

Add methods:

```python
    async def _command_catalog(self, request: JsonRpcRequest) -> None:
        outcome = await handle_command_catalog_operation(request_id=request.id, params=request.params)
        await self._send(outcome.response)

    async def _command_execute(self, request: JsonRpcRequest) -> None:
        outcome = await handle_command_execute_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)
```

- [ ] **Step 7: Run backend tests and checkpoint**

Run:

```powershell
py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py -k "command_catalog or skill or queue_create_rejects_attachment_input" -q
py -3.14 -m pytest members\writer\backend\tests\test_tool_contracts.py -k skill -q
```

Expected: PASS.

Checkpoint command for execution mode:

```powershell
git add members/writer/backend/app/services/command_service.py members/writer/backend/app/services/composer_input_service.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/tests/test_writer_app_server_protocol.py
git commit -m "feat(writer): expose core composer commands"
```

---

### Task 5: Manual Context Compaction

**Files:**
- Create: `members/writer/backend/app/services/session_compaction_service.py`
- Modify: `members/writer/backend/app/services/runtime_input_context.py`
- Modify: `members/writer/backend/tests/test_writer_app_server_protocol.py`
- Create: `members/writer/backend/tests/test_session_compaction_service.py`

**Interfaces:**
- Produces: `compact_session_context_response(db, session_id: str) -> dict[str, object]`
- Produces: runtime history behavior where `session.context_summary` is prepended and compacted messages are omitted.
- Consumed by: Task 4 `execute_writer_command`.

- [ ] **Step 1: Write failing compaction tests**

Create `members/writer/backend/tests/test_session_compaction_service.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.message import WriterMessage
from app.models.session import WriterSession
from app.services.runtime_input_context import prepare_runtime_input_context
from app.services.session_compaction_service import compact_session_context_response


@pytest.mark.asyncio
async def test_manual_compaction_persists_summary_and_runtime_uses_it(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'compact.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with session_factory() as db:
            session = WriterSession(id="s1", title="Compaction")
            db.add(session)
            for index in range(12):
                db.add(WriterMessage(session_id="s1", role="user" if index % 2 == 0 else "assistant", content=f"message-{index}"))
            await db.commit()

            result = await compact_session_context_response(db, session_id="s1")
            await db.refresh(session)

            assert result["compacted_messages"] == 6
            assert "message-0" in session.context_summary
            assert session.runtime_state["manual_compaction"]["retained_message_count"] == 6
    finally:
        await engine.dispose()
```

- [ ] **Step 2: Run failing compaction tests**

Run:

```powershell
py -3.14 -m pytest members\writer\backend\tests\test_session_compaction_service.py -q
```

Expected: FAIL because `session_compaction_service.py` does not exist.

- [ ] **Step 3: Implement deterministic compaction service**

Create `members/writer/backend/app/services/session_compaction_service.py`:

```python
from __future__ import annotations

from datetime import timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import WriterMessage
from app.models.session import WriterSession
from app.models.base import now
from app.services.session_rollback_markers import is_rolled_back_metadata

RETAIN_MESSAGE_COUNT = 6
MAX_MESSAGE_CHARS = 1200
MAX_SUMMARY_CHARS = 20000


async def compact_session_context_response(db: AsyncSession, *, session_id: str) -> dict[str, Any]:
    session = await db.get(WriterSession, session_id)
    if session is None:
        raise LookupError("Session not found")
    messages = await _load_messages(db, session_id)
    if len(messages) <= RETAIN_MESSAGE_COUNT:
        raise ValueError("没有足够的历史可压缩")

    compacted = messages[:-RETAIN_MESSAGE_COUNT]
    retained = messages[-RETAIN_MESSAGE_COUNT:]
    summary = _build_summary(session.context_summary or "", compacted)
    runtime_state = dict(session.runtime_state or {})
    runtime_state["manual_compaction"] = {
        "compacted_at": now().astimezone(timezone.utc).isoformat(),
        "compacted_message_ids": [message.id for message in compacted],
        "retained_message_ids": [message.id for message in retained],
        "retained_message_count": len(retained),
    }
    session.context_summary = summary[:MAX_SUMMARY_CHARS]
    session.runtime_state = runtime_state
    return {
        "session_id": session_id,
        "compacted_messages": len(compacted),
        "retained_messages": len(retained),
        "summary": session.context_summary,
    }


async def _load_messages(db: AsyncSession, session_id: str) -> list[WriterMessage]:
    result = await db.execute(
        select(WriterMessage)
        .where(WriterMessage.session_id == session_id)
        .where(WriterMessage.role.in_(("user", "assistant")))
        .order_by(WriterMessage.created_at.asc())
    )
    return [
        message for message in result.scalars().all()
        if message.content and not is_rolled_back_metadata(message.metadata_)
    ]


def _build_summary(existing: str, messages: list[WriterMessage]) -> str:
    lines: list[str] = []
    if existing.strip():
        lines.extend([existing.strip(), "", "追加压缩历史："])
    else:
        lines.append("已压缩的历史上下文：")
    for index, message in enumerate(messages, start=1):
        role = "用户" if message.role == "user" else "助手"
        content = " ".join(str(message.content or "").split())
        if len(content) > MAX_MESSAGE_CHARS:
            content = content[:MAX_MESSAGE_CHARS] + "..."
        lines.append(f"{index}. {role}: {content}")
    return "\n".join(lines)
```

- [ ] **Step 4: Make runtime history use compaction summary**

Modify `members/writer/backend/app/services/runtime_input_context.py`:

```python
from app.models.session import WriterSession
```

Inside `_load_recent_history`, load the session and compacted IDs:

```python
    session = await db.get(WriterSession, session_id)
    runtime_state = session.runtime_state if session and isinstance(session.runtime_state, dict) else {}
    compaction = runtime_state.get("manual_compaction") if isinstance(runtime_state, dict) else {}
    compacted_ids = set(compaction.get("compacted_message_ids") or []) if isinstance(compaction, dict) else set()
```

Filter messages:

```python
        if not is_rolled_back_metadata(message.metadata_) and message.id not in compacted_ids
```

Prepend summary:

```python
    if session and session.context_summary:
        history.insert(0, {"role": "system", "content": session.context_summary})
```

Modify `core_kernel_adapter.py` history conversion to keep `system` history:

```python
            if role in ("system", "user", "assistant") and content:
                initial_history.append(ChatMessage(role=role, content=content))
```

- [ ] **Step 5: Run compaction tests and backend command tests**

Run:

```powershell
py -3.14 -m pytest members\writer\backend\tests\test_session_compaction_service.py -q
py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py -k "command_execute or command_catalog" -q
```

Expected: PASS.

Checkpoint command for execution mode:

```powershell
git add members/writer/backend/app/services/session_compaction_service.py members/writer/backend/app/services/runtime_input_context.py members/writer/backend/app/core/writer/core_kernel_adapter.py members/writer/backend/tests/test_session_compaction_service.py
git commit -m "feat(writer): compact session context on command"
```

---

### Task 6: Writer Frontend Store And API Command Transport

**Files:**
- Modify: `members/writer/frontend/src/appServer/protocol.ts`
- Modify: `members/writer/frontend/src/appServer/store.ts`
- Modify: `members/writer/frontend/src/api/index.ts`
- Modify: `members/writer/frontend/src/types/index.ts`
- Modify: `members/writer/frontend/tests/appServer/store.test.ts`

**Interfaces:**
- Consumes backend `command.catalog` and `command.execute`.
- Produces: `store.listCommands(workRoot?: string)`.
- Produces: `store.executeCommand(threadId, command, workRoot?)`.
- Produces: `WriterInputItem` union with `type: 'skill'`.
- Consumed by: Task 7 Writer view.

- [ ] **Step 1: Add failing store tests**

Modify `members/writer/frontend/tests/appServer/store.test.ts`:

```ts
test('store transports skill input items and command operations', async () => {
  setActivePinia(createPinia())
  const store = useWriterAppServerStore()
  const calls: Array<{ method: string; params: Record<string, unknown> }> = []

  store.client = {
    request: async (method: string, params: Record<string, unknown>) => {
      calls.push({ method, params })
      if (method === 'command.catalog') return { commands: [{ name: 'compact', action: 'run_action' }] }
      if (method === 'command.execute') return { result: { status: 'compacted' }, snapshot: snapshot(2, 'idle') }
      return { snapshot: snapshot(1, 'running') }
    },
  } as never

  await store.startTurn('thread-1', [
    { type: 'text', text: '请 ' },
    { type: 'skill', name: 'reviewer', source_text: '/reviewer' },
  ])
  const commands = await store.listCommands('E:\\LamTools')
  await store.executeCommand('thread-1', 'compact', 'E:\\LamTools')

  assert.equal(calls[0].method, 'turn/start')
  assert.deepEqual(calls[0].params.input, [
    { type: 'text', text: '请 ' },
    { type: 'skill', name: 'reviewer', source_text: '/reviewer' },
  ])
  assert.deepEqual(commands, [{ name: 'compact', action: 'run_action' }])
  assert.equal(calls[2].method, 'command.execute')
})
```

- [ ] **Step 2: Run failing frontend store test**

Run:

```powershell
Push-Location members\writer\frontend
npm test -- tests/appServer/store.test.ts
Pop-Location
```

Expected: FAIL because `WriterInputItem` and store methods do not support skills/commands.

- [ ] **Step 3: Extend protocol types**

Modify `members/writer/frontend/src/appServer/protocol.ts`:

```ts
export interface WriterSkillInputItem {
  type: 'skill'
  name: string
  source_text?: string
}

export type WriterInputItem = WriterTextInputItem | WriterAttachmentInputItem | WriterSkillInputItem

export interface WriterCommandCatalogItem {
  name: string
  title?: string
  description?: string
  icon?: string
  source?: 'core' | 'member' | string
  action?: 'insert_token' | 'run_action' | 'expand_on_send' | string
  accepts_args?: boolean
}
```

- [ ] **Step 4: Add store command methods**

Modify `members/writer/frontend/src/appServer/store.ts` imports:

```ts
import type { WriterAppSnapshot, WriterCommandCatalogItem, WriterInputItem } from './protocol.ts'
```

Add actions:

```ts
    async listCommands(workRoot?: string): Promise<WriterCommandCatalogItem[]> {
      await this.ensureClient()
      const response = await this.client!.request('command/catalog', {
        ...(workRoot ? { work_root: workRoot } : {}),
      })
      return Array.isArray(response.commands) ? response.commands as WriterCommandCatalogItem[] : []
    },
    async executeCommand(threadId: string, command: string, workRoot?: string): Promise<Record<string, unknown>> {
      await this.ensureClient()
      const response = await this.client!.request('command/execute', {
        thread_id: threadId,
        command,
        ...(workRoot ? { work_root: workRoot } : {}),
      })
      this.applyResponse(response)
      return response.result && typeof response.result === 'object'
        ? response.result as Record<string, unknown>
        : {}
    },
```

- [ ] **Step 5: Add one-shot API wrappers**

Modify `members/writer/frontend/src/api/index.ts`:

```ts
export function listCommands(workRoot?: string): Promise<unknown[]> {
  return appServerOperation<{ commands?: unknown[] }>('command.catalog', {
    ...(workRoot ? { work_root: workRoot } : {}),
  }).then(result => result.commands ?? [])
}

export function executeCommand(sessionId: string, command: string, workRoot?: string): Promise<Record<string, unknown>> {
  return appServerOperation<{ result?: Record<string, unknown> }>('command.execute', {
    session_id: sessionId,
    command,
    ...(workRoot ? { work_root: workRoot } : {}),
  }).then(result => result.result ?? {})
}
```

- [ ] **Step 6: Run frontend tests and checkpoint**

Run:

```powershell
Push-Location members\writer\frontend
npm test
npm run build
Pop-Location
```

Expected: PASS.

Checkpoint command for execution mode:

```powershell
git add members/writer/frontend/src/appServer/protocol.ts members/writer/frontend/src/appServer/store.ts members/writer/frontend/src/api/index.ts members/writer/frontend/tests/appServer/store.test.ts
git commit -m "feat(writer-ui): transport composer commands"
```

---

### Task 7: Writer Workbench Command Palette Integration

**Files:**
- Modify: `members/writer/frontend/src/views/CoreWorkbenchView.vue`

**Interfaces:**
- Consumes: `CommandPalette`, `parseComposerSyntax`, `useComposerCommandPalette`, `CoreCommandCatalogItem`
- Consumes: `appServerStore.listCommands`, `appServerStore.executeCommand`
- Produces user-visible behavior for typing `/`, selecting commands, skill token send, `/compact`, and `/fork`.

- [ ] **Step 1: Add view state and command loading**

Modify imports in `CoreWorkbenchView.vue`:

```ts
import {
  AttachmentTray,
  CommandPalette,
  parseComposerSyntax,
  useComposerCommandPalette,
  type CoreCommandCatalogItem,
  type CoreInputItem,
} from '@lamtools/ui'
```

Add state near composer refs:

```ts
const composerCursor = ref(0)
const commandCatalog = ref<CoreCommandCatalogItem[]>([])
const commandError = ref('')
```

Add palette setup:

```ts
const commandPalette = useComposerCommandPalette({
  text: composerText,
  cursor: composerCursor,
  commands: commandCatalog,
})
```

Add cursor update:

```ts
function updateComposerCursor() {
  composerCursor.value = composerTextareaEl.value?.selectionStart ?? composerText.value.length
}
```

Load commands when active session/work root changes:

```ts
watch(activeSessionId, async () => {
  commandCatalog.value = []
  const workRoot = currentSessionWorkRoot()
  try {
    if (!isAppServerActive.value && activeSessionId.value) {
      await appServerStore.connect(api.API_BASE, activeSessionId.value)
    }
    commandCatalog.value = await appServerStore.listCommands(workRoot)
  } catch (err) {
    commandError.value = err instanceof Error ? err.message : String(err)
  }
}, { immediate: true })
```

- [ ] **Step 2: Add command selection behavior**

Add functions:

```ts
function replaceActiveSlash(command: CoreCommandCatalogItem): void {
  const span = commandPalette.activeSlash.value
  const el = composerTextareaEl.value
  if (!span || !el) return
  const replacement = command.action === 'insert_token' ? `/${command.name}` : ''
  composerText.value = `${composerText.value.slice(0, span.start)}${replacement}${composerText.value.slice(span.end)}`
  void nextTick(() => {
    const cursor = span.start + replacement.length
    el.focus()
    el.setSelectionRange(cursor, cursor)
    updateComposerCursor()
  })
}

async function selectComposerCommand(command: CoreCommandCatalogItem) {
  commandPalette.reset()
  if (command.action === 'insert_token') {
    replaceActiveSlash(command)
    return
  }
  replaceActiveSlash(command)
  await executeComposerAction(command.name)
}

async function executeComposerAction(command: string) {
  if (!activeSessionId.value) {
    runtimeStatusText.value = '请先选择会话'
    return
  }
  if (composerIsRunning.value) {
    runtimeStatusText.value = '当前正在运行，请等本轮结束后再执行命令'
    return
  }
  try {
    const result = await appServerStore.executeCommand(activeSessionId.value, command, currentSessionWorkRoot())
    if (command === 'fork') {
      const session = result.session as Session | undefined
      if (session?.id) {
        upsertForkedSession(session)
        await selectSession(session.id)
      }
    }
    runtimeStatusText.value = command === 'compact' ? '上下文已压缩' : '命令已执行'
  } catch (err) {
    runtimeStatusText.value = err instanceof Error ? err.message : String(err)
  }
}
```

- [ ] **Step 3: Build skill input items from composer text**

Add helper:

```ts
function buildComposerInputItems(text: string, attachments: CoreInputItem[]): CoreInputItem[] {
  const spans = parseComposerSyntax(text)
    .filter(span => span.kind === 'slash')
    .filter(span => commandCatalog.value.some(command => command.name === span.value && command.action === 'insert_token'))

  if (!spans.length) return [{ type: 'text', text }, ...attachments]

  const items: CoreInputItem[] = []
  let cursor = 0
  for (const span of spans) {
    if (span.start > cursor) items.push({ type: 'text', text: text.slice(cursor, span.start) })
    items.push({ type: 'skill', name: span.value, source_text: span.raw })
    cursor = span.end
  }
  if (cursor < text.length) items.push({ type: 'text', text: text.slice(cursor) })
  return [...items, ...attachments]
}
```

Change `submitWriterText` input item construction:

```ts
  const inputItems = buildComposerInputItems(cleaned, attachments)
```

Before normal send, detect standalone action commands:

```ts
  const actionCommand = standaloneActionCommand(cleaned)
  if (actionCommand) {
    await executeComposerAction(actionCommand)
    if (options.clearComposer) clearComposerAfterPersisted(cleaned)
    return
  }
```

Add:

```ts
function standaloneActionCommand(text: string): string {
  const spans = parseComposerSyntax(text)
  if (spans.length !== 1) return ''
  const span = spans[0]
  if (span.kind !== 'slash') return ''
  if (text.slice(0, span.start).trim() || text.slice(span.end).trim()) return ''
  const command = commandCatalog.value.find(item => item.name === span.value)
  return command?.action === 'run_action' ? command.name : ''
}
```

- [ ] **Step 4: Wire keyboard and palette template**

Add keydown handler:

```ts
async function handleComposerKeydown(event: KeyboardEvent) {
  updateComposerCursor()
  if (commandPalette.open.value) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      commandPalette.move(1)
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      commandPalette.move(-1)
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      commandPalette.reset()
      return
    }
    if (event.key === 'Enter') {
      const selected = commandPalette.selected()
      if (selected) {
        event.preventDefault()
        await selectComposerCommand(selected)
        return
      }
    }
  }
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    await sendWriterTask()
  }
}
```

Replace textarea key binding:

```vue
@input="resizeComposerTextarea(); updateComposerCursor()"
@click="updateComposerCursor"
@keyup="updateComposerCursor"
@keydown="handleComposerKeydown"
```

Place palette above the textarea inside `#composer-textarea`:

```vue
<div class="composer-input-wrap">
  <CommandPalette
    v-if="commandPalette.open.value"
    :commands="commandPalette.filteredCommands.value"
    :active-index="commandPalette.activeIndex.value"
    @select="selectComposerCommand"
  />
  <textarea ... />
</div>
```

Add CSS:

```css
.composer-input-wrap {
  position: relative;
}
```

- [ ] **Step 5: Run frontend verification**

Run:

```powershell
Push-Location core\ui
npm run build
Pop-Location
Push-Location members\writer\frontend
npm test
npm run build
Pop-Location
```

Expected: PASS.

Checkpoint command for execution mode:

```powershell
git add members/writer/frontend/src/views/CoreWorkbenchView.vue
git commit -m "feat(writer-ui): wire slash command palette"
```

---

### Task 8: End-To-End Verification And Demo

**Files:**
- No source file changes unless verification finds a defect.
- Output: `tmp/writer-core-composer-commands-demo-YYYYMMDD-HHMMSS.mp4`

**Interfaces:**
- Consumes all previous tasks.
- Produces manual verification evidence.

- [ ] **Step 1: Run full targeted test suite**

Run:

```powershell
py -3.14 -m pytest core\tests\test_composer_commands.py core\tests\test_command_tools.py -q
py -3.14 -m pytest members\writer\backend\tests\test_writer_app_server_protocol.py -k "command or skill or compaction or attachment" -q
py -3.14 -m pytest members\writer\backend\tests\test_session_compaction_service.py -q
Push-Location core\ui
npx vitest run tests\composer-syntax.test.ts tests\command-palette.test.ts tests\attachment-tray.test.ts
npm run build
Pop-Location
Push-Location members\writer\frontend
npm test
npm run build
Pop-Location
```

Expected: all commands exit with code 0.

- [ ] **Step 2: Launch Writer**

Run:

```powershell
.\scripts\dev.ps1 writer all
```

Expected: backend and frontend become reachable; the frontend opens or reports the local URL.

- [ ] **Step 3: Manual browser checks**

Use the in-app browser or Playwright against the Writer URL:

1. Type `/` and confirm the command palette opens.
2. Type `/comp` and confirm `/compact` is the filtered command.
3. Press ArrowDown/ArrowUp and confirm active row changes.
4. Press Escape and confirm the palette closes without changing text.
5. Type `/brainstorming` or another available skill and select it; confirm pale-blue token rendering is visible.
6. Send a message containing the skill token; confirm the visible user message stays concise and the runtime receives expanded skill content.
7. Run standalone `/compact`; confirm no user message is added and status says context was compressed.
8. Run standalone `/fork`; confirm a new session appears and becomes active.
9. Start a running turn, then try `/fork`; confirm it stops with a wait-until-finished prompt and does not queue the command.
10. Type `abc/compact`, `https://example.com/a/b`, and `C:/tmp/a.txt`; confirm they are ordinary text.

- [ ] **Step 4: Record demo video**

Record the visible checks for `/`, skill token insertion, `/compact`, and `/fork`.

Save as:

```text
E:\LamTools\tmp\writer-core-composer-commands-demo-YYYYMMDD-HHMMSS.mp4
```

- [ ] **Step 5: Final checkpoint**

Run:

```powershell
git status --short
```

Expected: only files from this plan and the already-active attachment work are changed. Do not stage unrelated user changes.

Checkpoint command for execution mode:

```powershell
git add core/command core/src/lamtools_core/composer_commands.py core/tests/test_composer_commands.py core/ui/src core/ui/tests members/writer/backend/app members/writer/backend/tests members/writer/frontend/src members/writer/frontend/tests docs/superpowers/plans/2026-07-04-core-composer-commands.md
git commit -m "feat(core): add composer slash commands"
```

---

## Self-Review

**Spec coverage**

- `/` trigger and palette: Task 1, Task 2, Task 7.
- `/skill-name` pale-blue token and backend expansion: Task 2, Task 4, Task 6, Task 7.
- `/compact` as generic Core command: Task 3, Task 4, Task 5, Task 7.
- `/fork` as generic Core command: Task 3, Task 4, Task 7.
- `core/command` and `members/{member}/command`: Task 3.
- Member `config.json` disables Core commands only for that member: Task 3 and Task 4.
- Unknown slash text remains ordinary text: Task 1 and Task 7.
- Running-turn action commands are not queued: Task 7 and Task 8.
- Failure preserves draft and stops action: Task 4, Task 7.
- Existing attachment transport is not reimplemented: all tasks build on existing `CoreInputItem` and do not change upload storage.

**Placeholder scan**

- The plan contains no placeholder tokens or open-ended “add handling” instructions.
- Every new public function has an exact name and file path.

**Type consistency**

- Frontend command items use `CoreCommandCatalogItem` and Writer transport uses `WriterCommandCatalogItem`.
- Skill input item shape is `{"type":"skill","name":"...","source_text":"/..."}` in Core UI, Writer protocol, and backend parser.
- Action command names are bare names in backend (`compact`, `fork`) and slash-prefixed only in visible text.
