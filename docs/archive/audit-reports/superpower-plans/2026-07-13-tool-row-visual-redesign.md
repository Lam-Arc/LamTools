# Tool Row Visual Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every non-`run_command` tool card in the shared chat timeline with one restrained, accessible row system while preserving file diff, test, and generic result detail structures. Keep `run_command` unchanged.

**Architecture:** Keep `ChatThread.vue` as the single shared rendering owner for Core and Writer. Reuse its existing tool data, expansion state, diff renderer, test renderer, generic output renderer, and projection helpers; add only a small status-label helper and shared row semantics, then replace non-command category cards with neutral row tokens. The existing command renderer remains untouched. No backend, protocol, projection, or member-specific implementation changes are required.

**Tech Stack:** Vue 3.5, TypeScript 6, scoped CSS, Vitest 4, Vue Test Utils, Vite 8.

## Global Constraints

- Default tool presentation has `min-height: 32px` with no decorative card background, rounded outer frame, or shadow.
- Tool categories use neutral color; semantic color is reserved for running, success, failure, and pending states.
- File diff, test result, and generic result structures remain available inside the expanded row.
- Real-time, historical, Core, and Writer views use the same shared implementation.
- Preserve existing projection, execution, expansion, copy, and wrap behavior; do not add parallel state.
- Keyboard focus must remain visible, state must not rely on color alone, and reduced-motion mode must disable pulsing and expansion motion.
- Do not modify the already-confirmed approval behavior or its click-target safety.
- Do not modify `run_command` markup, spacing, terminal output, or visual styling.

---

## File Map

- Modify `core/ui/src/components/ChatThread.vue`: shared tool-row markup, status copy, neutral row styling, expanded detail styling, responsive and reduced-motion behavior.
- Modify `core/ui/tests/chat-thread-process.test.ts`: DOM contract, status semantics, expansion regressions, and source-level anti-card assertions.
- Verify `members/writer/frontend/src/views/CoreWorkbenchView.vue`: no code change expected; it consumes the shared `ChatThread` export.
- Verify `members/writer/frontend/tests/runtime/runtimeResourceWidget.test.ts`: no code change expected; Writer shared-UI regression surface.

### Task 1: Lock the unified tool-row contract with failing tests

**Files:**
- Modify: `core/ui/tests/chat-thread-process.test.ts`
- Test: `core/ui/tests/chat-thread-process.test.ts`

**Interfaces:**
- Consumes: existing `ChatThread` prop `messages` and internal `togglePartExpand(part, live)`, `toolExpandedIds`, and `toolCollapsedIds` state.
- Produces: DOM contract `.process-tool-row`, `.tool-row-name`, `.tool-row-summary`, `.tool-row-status`, and `aria-expanded` for every expandable non-command tool.

- [ ] **Step 1: Add a failing real-time tool-row semantics test**

Add a test using the existing `mount(ChatThread, { props: { messages } })` helper pattern:

```ts
it('renders live tools as neutral accessible rows with textual status', async () => {
  const messages: CoreMessage[] = [{
    id: 'm-live-tool-row',
    role: 'assistant',
    content: '',
    timestamp: '2026-07-13T00:00:00.000Z',
    metadata: { live: true, timeline: true },
    parts: [{
      id: 'p-live-tool-row',
      partType: 'tool_call',
      status: 'running',
      toolName: 'write_file',
      toolArgs: { path: 'notes.txt' },
      content: 'writing notes.txt',
    }],
  }];

  const wrapper = mount(ChatThread, { props: { messages } });
  const row = wrapper.find('.process-tool-row');

  expect(row.exists()).toBe(true);
  expect(row.attributes('aria-expanded')).toBe('false');
  expect(row.find('.tool-row-name').text()).toBe('write_file');
  expect(row.find('.tool-row-summary').text()).toContain('notes.txt');
  expect(row.find('.tool-row-status').text()).toBe('运行中');
  expect(row.classes()).not.toContain('tool-card');
});
```

- [ ] **Step 2: Add a failing historical status matrix test**

Render completed, error, and pending tool parts in a historical message and assert the non-color status text:

```ts
expect(wrapper.findAll('.tool-row-status').map(node => node.text())).toEqual([
  '已完成',
  '失败',
  '等待中',
]);
```

Also assert all three rows share `.process-tool-row` and none has a category-specific visual tag or status-dot element:

```ts
expect(wrapper.findAll('.process-tool-row')).toHaveLength(3);
expect(wrapper.findAll('.tool-type-tag')).toHaveLength(0);
expect(wrapper.findAll('.process-tool-row .process-step-marker')).toHaveLength(0);
```

- [ ] **Step 3: Add failing expansion preservation assertions**

Use the existing file and test fixtures and assert their specialized bodies still appear after clicking a row. Separately assert `run_command` retains `.tool-card-header--command` and `.command-output` without `.process-tool-row`:

```ts
await fileRow.trigger('click');
expect(wrapper.find('.diff-block').exists()).toBe(true);

await testRow.trigger('click');
expect(wrapper.find('.test-result-card').exists()).toBe(true);

expect(wrapper.find('.tool-card-header--command').exists()).toBe(true);
expect(wrapper.find('.command-output').exists()).toBe(true);
expect(wrapper.find('.tool-card-header--command.process-tool-row').exists()).toBe(false);
```

- [ ] **Step 4: Run the focused tests and confirm the new contract fails**

Run:

```powershell
Set-Location E:\LamTools\core\ui
npm run test:contract -- --run tests/chat-thread-process.test.ts
```

Expected: failure because `.process-tool-row`, textual status, and `aria-expanded` do not exist yet.

- [ ] **Step 5: Commit the red tests**

```powershell
git add -- core/ui/tests/chat-thread-process.test.ts
git commit -m "test(ui): define unified tool row contract"
```

### Task 2: Implement one neutral row vocabulary across all shared branches

**Files:**
- Modify: `core/ui/src/components/ChatThread.vue`
- Test: `core/ui/tests/chat-thread-process.test.ts`

**Interfaces:**
- Consumes: `MessagePart.status`, `toolTypeLabel(part)`, `readableProcessTitle(part)`, `toolArgsPreview(part.toolArgs)`, `hasToolDisplay(part)`, and `shouldShowToolBody(part, live)`.
- Produces: `toolStatusLabel(part: MessagePart): string` and the shared `.process-tool-row` DOM contract.

- [ ] **Step 1: Add the minimal status-label helper**

Place the helper beside the existing display-label helpers:

```ts
function toolStatusLabel(part: MessagePart): string {
  if (part.status === 'running') return '运行中';
  if (part.status === 'error') return '失败';
  if (part.status === 'pending') return '等待中';
  return '已完成';
}
```

- [ ] **Step 2: Replace the live tool header with shared row semantics**

Keep the existing click handler and body branches, but replace the visible header structure with:

```vue
<button
  v-if="hasToolDisplay(part)"
  type="button"
  class="tool-row"
  :class="`tool-row--${part.status}`"
  :aria-expanded="shouldShowToolBody(part, true)"
  @click="togglePartExpand(part, true)"
>
  <span class="process-step-marker" aria-hidden="true" />
  <span class="tool-row-name">{{ toolTypeLabel(part) }}</span>
  <span class="tool-row-summary">
    {{ shouldShowToolArgsPreview(part) ? toolArgsPreview(part.toolArgs || {}) : readableProcessTitle(part) }}
  </span>
  <span class="tool-row-status">{{ toolStatusLabel(part) }}</span>
  <span v-if="hasToolDisplay(part)" class="tool-expand-chevron" aria-hidden="true">
    {{ shouldShowToolBody(part, true) ? '▾' : '▸' }}
  </span>
</button>
<div v-else class="tool-row" :class="`tool-row--${part.status}`">
  <span class="process-step-marker" aria-hidden="true" />
  <span class="tool-row-name">{{ toolTypeLabel(part) }}</span>
  <span class="tool-row-summary">
    {{ shouldShowToolArgsPreview(part) ? toolArgsPreview(part.toolArgs || {}) : readableProcessTitle(part) }}
  </span>
  <span class="tool-row-status">{{ toolStatusLabel(part) }}</span>
</div>
```

Do not use native `disabled` for non-expandable rows. Render them with the explicit non-button `<div class="tool-row">` branch above so their text keeps normal contrast and keyboard navigation contains only actionable rows.

- [ ] **Step 3: Apply the same row structure to both historical tool branches**

Replace the two duplicated `.tool-card-header` structures in timeline and non-timeline history with the same names, summary, status, `aria-expanded`, and chevron ordering. Preserve each branch's existing `togglePartExpand(group.part, false)` and body renderer without changing the data flow.

- [ ] **Step 4: Convert context-group child cards to compact child rows**

Keep `.context-tool-list`, but change each `.context-tool-card` to `.context-tool-row` with the same neutral name/summary alignment:

```vue
<div class="context-tool-row">
  <span class="tool-row-name">{{ toolTypeLabel(item) }}</span>
  <span class="tool-row-summary">
    {{ shouldShowToolArgsPreview(item) ? toolArgsPreview(item.toolArgs || {}) : readableProcessTitle(item) }}
  </span>
</div>
```

Keep `context-tool-output` immediately below the row when output exists.

- [ ] **Step 5: Run the focused contract tests**

Run:

```powershell
Set-Location E:\LamTools\core\ui
npm run test:contract -- --run tests/chat-thread-process.test.ts
```

Expected: Task 1 tests pass; existing expansion, diff, command, test, decision, reasoning, and timeline tests remain green.

- [ ] **Step 6: Commit the semantic row implementation**

```powershell
git add -- core/ui/src/components/ChatThread.vue core/ui/tests/chat-thread-process.test.ts
git commit -m "feat(ui): unify tool process rows"
```

### Task 3: Replace category cards and decorative chrome with restrained shared styling

**Files:**
- Modify: `core/ui/src/components/ChatThread.vue`
- Test: `core/ui/tests/chat-thread-process.test.ts`

**Interfaces:**
- Consumes: textual state labels from Task 2; non-command rows do not use colored status dots.
- Produces: neutral row visuals and semantic-state tokens used by every live/history branch.

- [ ] **Step 1: Add source-level anti-card assertions**

Extend the existing source-style test:

```ts
const source = readFileSync(new URL('../src/components/ChatThread.vue', import.meta.url), 'utf8');
expect(source).not.toContain('.tool-color--read .tool-type-tag');
expect(source).not.toContain('.tool-color--write .tool-type-tag');
expect(source).not.toContain('.context-tool-card {');
expect(source).not.toContain('text-shadow: 0 0 8px');
expect(source).toContain('.process-tool-row:focus-visible');
expect(source).toContain('@media (max-width: 720px)');
```

- [ ] **Step 2: Replace the expandable tool-card CSS block**

Use a single restrained row system:

```css
.process-step--tool {
  width: 100%;
  min-width: 0;
  padding: 0;
  border: 0;
  background: transparent;
}

.process-tool-row {
  width: 100%;
  min-width: 0;
  min-height: 32px;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: nowrap;
  gap: 8px;
  padding: 4px 6px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: inherit;
  text-align: left;
  transition: background-color 160ms ease-out, color 160ms ease-out;
}

.process-tool-row:hover {
  background: color-mix(in srgb, var(--theme-main-text, #fff) 4%, transparent);
}

.process-tool-row:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--blue) 72%, transparent);
  outline-offset: 1px;
}

.tool-row-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 82%, transparent);
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 650;
}

.tool-row-summary {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 58%, transparent);
  font-family: var(--font-mono);
  font-size: 11.5px;
}

.tool-row-status {
  color: color-mix(in srgb, var(--theme-main-text, #fff) 54%, transparent);
  font-size: 11px;
  white-space: nowrap;
}

```

Delete the category-color tag rules and retain `toolColorClass()` only if another non-visual behavior still consumes it. If it becomes unused, remove the helper and its tests instead of leaving dead code.

- [ ] **Step 3: Make expanded bodies subordinate rather than nested cards**

Set `.tool-card-body` to `margin: 2px 0 10px 18px`, remove outer decorative shadows, and use one shared `--tool-detail-bg`-style value through existing theme variables. Preserve internal borders only where they define code/diff structure.

For generic output:

```css
.tool-output {
  padding: 9px 10px;
  border: 0;
  border-radius: 6px;
  background: color-mix(in srgb, var(--theme-main-text, #fff) 4%, transparent);
}

.tool-output-meta span {
  padding: 0;
  border: 0;
  background: transparent;
}
```

- [ ] **Step 4: Preserve specialized structures while quieting decoration**

- File diff: keep `.diff-header`, line numbers, add/delete colors, wrap/scroll toggle; remove category-tinted outer background.
- Command output: do not modify its header, command line, terminal chrome, stdout/stderr body, spacing, colors, or interaction.
- Test result: keep passed/failed copy and metadata; remove card-like outer shadow and saturated inactive background.
- Context tools: use `.context-tool-row` with a subtle bottom divider and no outer frame.

- [ ] **Step 5: Run focused tests and inspect the generated CSS**

Run:

```powershell
Set-Location E:\LamTools\core\ui
npm run test:contract -- --run tests/chat-thread-process.test.ts
npm run build
```

Expected: tests pass; build completes without Vue/TypeScript/CSS errors.

- [ ] **Step 6: Commit the restrained visual system**

```powershell
git add -- core/ui/src/components/ChatThread.vue core/ui/tests/chat-thread-process.test.ts
git commit -m "style(ui): distill tool process presentation"
```

### Task 4: Add narrow-screen and reduced-motion safeguards, then verify Core and Writer

**Files:**
- Modify: `core/ui/src/components/ChatThread.vue`
- Modify: `core/ui/tests/chat-thread-process.test.ts`
- Verify: `members/writer/frontend/src/views/CoreWorkbenchView.vue`
- Verify: `members/writer/frontend/tests/runtime/runtimeResourceWidget.test.ts`

**Interfaces:**
- Consumes: Task 3 `.process-tool-row` and specialized detail styles.
- Produces: responsive row collapse and reduced-motion safety shared by both products.

- [ ] **Step 1: Add responsive CSS assertions**

Assert the source contains a narrow layout that hides no status and truncates only the summary:

```ts
expect(source).toMatch(/@media \(max-width: 720px\)[\s\S]*\.tool-row-summary/);
expect(source).toMatch(/prefers-reduced-motion: reduce[\s\S]*\.process-tool-row/);
```

- [ ] **Step 2: Implement narrow-screen row behavior**

```css
@media (max-width: 720px) {
  .process-tool-row {
    gap: 6px;
    padding-inline: 2px;
  }

  .tool-card-body {
    margin-left: 10px;
  }
}
```

- [ ] **Step 3: Complete reduced-motion behavior**

```css
@media (prefers-reduced-motion: reduce) {
  .process-tool-row,
  .tool-card-body,
  .process-step-marker {
    animation: none;
    transition: none;
  }
}
```

- [ ] **Step 4: Run all shared UI and Writer regressions**

Run:

```powershell
Set-Location E:\LamTools\core\ui
npm run test:contract
npm run build

Set-Location E:\LamTools\members\writer\frontend
npm test
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 5: Perform live visual acceptance**

Open the running Core workbench at `http://127.0.0.1:5173` and verify one real session containing:

- collapsed and expanded file tools;
- collapsed and expanded command output;
- passed or failed test output;
- a running tool;
- a historical completed tool;
- the existing approval item;
- viewport widths near 1440px and 390px;
- keyboard focus and reduced-motion mode.

Acceptance evidence must include screenshots showing the shared row system in both collapsed and expanded states. Confirm there are no nested decorative cards, horizontal page overflow, clipped status copy, or approval interaction regressions.

- [ ] **Step 6: Run final diff hygiene and commit**

```powershell
Set-Location E:\LamTools
git diff --check
git add -- core/ui/src/components/ChatThread.vue core/ui/tests/chat-thread-process.test.ts
git commit -m "test(ui): verify responsive tool rows"
```

Expected: only the intended shared UI files are included in the implementation commits; unrelated dirty-worktree changes remain untouched.
