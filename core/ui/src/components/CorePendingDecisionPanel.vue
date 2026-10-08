<template>
  <section
    v-if="items.length > 0"
    class="pending-decision"
    data-pending-decision-panel
    role="group"
    :aria-label="ariaLabel"
    @keydown.esc="handleEscape"
  >
    <header class="pending-decision__head">
      <CircleHelp class="pending-decision__icon" :size="15" :stroke-width="2" aria-hidden="true" />
      <span class="pending-decision__headline">需要你确认</span>
      <span class="pending-decision__count" role="status" aria-live="polite">{{ countLabel }}</span>
    </header>

    <ol v-if="items.length > 1" class="pending-decision__queue" aria-label="待处理项">
      <li v-for="(item, index) in items" :key="item.partId" class="pending-decision__queue-cell">
        <button
          type="button"
          class="pending-decision__queue-item"
          :aria-current="index === activeIndex ? 'true' : undefined"
          :data-pending-decision-item="item.partId"
          @click="activate(index)"
        >
          <span class="pending-decision__queue-index">{{ index + 1 }}</span>
          <span class="pending-decision__queue-title">{{ item.subject }}</span>
          <span class="pending-decision__queue-state">{{ item.submitting ? '处理中…' : (index === activeIndex ? '待你选择' : '待处理') }}</span>
        </button>
      </li>
    </ol>

    <div v-if="active" class="pending-decision__body">
      <p class="pending-decision__subject" data-pending-decision-subject>{{ active.subject }}</p>
      <p v-if="active.detail" class="pending-decision__detail">{{ active.detail }}</p>

      <ul v-if="active.facts.length > 0" class="pending-decision__facts">
        <li
          v-for="fact in active.facts"
          :key="fact.label + fact.value"
          class="pending-decision__fact"
          :class="'is-' + fact.tone"
        >
          <span class="pending-decision__fact-label">{{ fact.label }}</span>
          <span class="pending-decision__fact-value" :class="{ 'is-mono': fact.mono }">{{ fact.value }}</span>
        </li>
      </ul>

      <div v-if="active.options.length > 0" class="pending-decision__actions" role="group" aria-label="处理方式">
        <div v-for="(option, index) in active.options" :key="option.id" class="pending-decision__action">
          <span class="pending-decision__option-index" aria-hidden="true">{{ index + 1 }}</span>
          <button
            type="button"
            class="pending-decision__option"
            :class="optionClass(option)"
            :data-decision-option-id="option.id"
            :disabled="active.submitting || !channelReady"
            @click="decide(active, option)"
          >
            {{ option.label }}
          </button>
          <span v-if="option.description" class="pending-decision__option-desc">{{ option.description }}</span>
        </div>
      </div>

      <div class="pending-decision__guide">
        <span class="pending-decision__option-index" aria-hidden="true">{{ active.options.length + 1 }}</span>
        <div class="pending-decision__guide-row">
          <textarea
            :id="guideInputId"
            ref="guideInputEl"
            class="pending-decision__guide-input"
            data-pending-decision-guide
            :value="guideDraft"
            rows="1"
            :disabled="active.submitting"
            aria-label="用一句话说明要怎么处理"
            placeholder="输入你的回答…"
            @input="updateGuideDraft"
            @keydown="onGuideKeydown"
          />
          <button
            type="button"
            class="pending-decision__guide-submit"
            data-pending-decision-guide-submit
            :disabled="active.submitting || !guideDraft.trim()"
            @click="submitGuide"
          >
            发送
          </button>
        </div>
      </div>

      <p class="pending-decision__hint">
        <Info class="pending-decision__hint-icon" :size="13" :stroke-width="2" aria-hidden="true" />
        <span>点击选项直接提交；也可以写下你的处理方式，回车或点「发送」。</span>
      </p>

      <p v-if="!channelReady" class="pending-decision__notice" role="alert">
        与运行时的确认通道已断开，恢复连接后才能提交选择。
      </p>
    </div>
  </section>
</template>

<script setup lang="ts">
/**
 * CorePendingDecisionPanel — composer-area takeover for waiting requests.
 *
 * The reported failure was a comprehension gap: when the runtime waits for an
 * approval or a question, the composer was still the most prominent input, so
 * users answered there — the text was queued as a normal turn input and the
 * request stayed unanswered. This panel replaces the composer input while any
 * request is pending, states what is being asked about, and turns every option
 * into a button on the existing decision channel.
 *
 * Decisions are emitted as `decision-select` with exactly the payload the
 * in-thread card emits, so `coreDecisionSelectionPlan` and the approval
 * controller stay the only decision path — no new protocol.
 */
import { computed, nextTick, ref, watch } from 'vue'
import { CircleHelp, Info } from 'lucide-vue-next'
import { autoGrowTextarea } from '../helpers/autoGrowTextarea'
import type { CoreDecisionChoice, CorePendingDecision } from '../appServer/pendingDecisions'

const props = withDefaults(defineProps<{
  items: CorePendingDecision[]
  /** Approval channel reachable; when false every option is disabled. */
  channelReady?: boolean
}>(), {
  channelReady: true,
})

const emit = defineEmits<{
  'decision-select': [payload: { partId: string; option: CoreDecisionChoice; response: string }]
}>()

const activeIndex = ref(0)
const guideDrafts = ref<Record<string, string>>({})
const guideInputEl = ref<HTMLTextAreaElement | null>(null)

const active = computed<CorePendingDecision | null>(() => (
  props.items[Math.min(Math.max(activeIndex.value, 0), props.items.length - 1)] ?? null
))

const countLabel = computed(() => (
  props.items.length > 1 ? `第 ${activeIndex.value + 1} / ${props.items.length} 项` : '等待你的选择'
))

const ariaLabel = computed(() => (
  props.items.length > 1 ? `需要你确认，共 ${props.items.length} 项` : '需要你确认'
))

const guideInputId = computed(() => `pending-decision-guide-${(active.value?.partId || 'none').replace(/[^A-Za-z0-9_-]/g, '_')}`)

const guideDraft = computed(() => (active.value ? guideDrafts.value[active.value.partId] || '' : ''))

// Follow the queue: keep the selected request selected when other requests
// resolve, and take the next one's place when the selected request itself is
// answered — several waiting requests get drained one after another.
watch(
  () => props.items.map(item => item.partId),
  (ids, previousIds) => {
    const previousId = previousIds?.[Math.min(activeIndex.value, Math.max((previousIds?.length || 1) - 1, 0))] || ''
    if (previousId && ids.includes(previousId)) {
      activeIndex.value = ids.indexOf(previousId)
      return
    }
    const previousPosition = previousId ? (previousIds?.indexOf(previousId) ?? -1) : -1
    activeIndex.value = Math.max(0, Math.min(previousPosition < 0 ? 0 : previousPosition, ids.length - 1))
  },
)

// One row is the resting height; each request keeps its own answer, so the
// field has to re-measure whenever the panel switches to another request.
watch(
  () => active.value?.partId,
  () => void nextTick(resizeGuideInput),
  { immediate: true },
)

function resizeGuideInput() {
  autoGrowTextarea(guideInputEl.value)
}

function activate(index: number) {
  if (index < 0 || index >= props.items.length) return
  activeIndex.value = index
}

function optionClass(option: CoreDecisionChoice): string {
  if (option.id === 'approve' || option.id === 'confirm') return 'is-approve'
  if (option.id === 'deny' || option.id === 'cancel') return 'is-deny'
  return 'is-neutral'
}

function updateGuideDraft(event: Event) {
  const target = event.target as HTMLTextAreaElement | null
  const item = active.value
  if (!item) return
  guideDrafts.value = { ...guideDrafts.value, [item.partId]: target?.value || '' }
  autoGrowTextarea(target)
}

function onGuideKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    clearGuideDraft()
    return
  }
  if (event.key !== 'Enter' || event.shiftKey) return
  // IME confirm must not submit (same guard as the composer).
  if (event.isComposing) return
  event.preventDefault()
  submitGuide()
}

function handleEscape() {
  if (guideDraft.value) clearGuideDraft()
  else guideInputEl.value?.blur()
}

function clearGuideDraft() {
  const item = active.value
  if (!item) return
  if (!guideDrafts.value[item.partId]) return
  const next = { ...guideDrafts.value }
  delete next[item.partId]
  guideDrafts.value = next
  void nextTick(resizeGuideInput)
}

function decide(item: CorePendingDecision, option: CoreDecisionChoice) {
  if (item.submitting || !props.channelReady) return
  emit('decision-select', {
    partId: item.partId,
    option,
    response: option.wireResponse,
  })
}

function submitGuide() {
  const item = active.value
  if (!item || item.submitting) return
  const text = guideDraft.value.trim()
  if (!text) return
  const option: CoreDecisionChoice = { id: 'guide', label: '引导', wireResponse: text }
  clearGuideDraft()
  emit('decision-select', { partId: item.partId, option, response: text })
}
</script>

<style scoped>
/* Composer-area takeover surface: composer theme area, composer tokens. */
.pending-decision {
  --text: var(--theme-composer-text);
  display: grid;
  gap: var(--space-2);
  min-width: 0;
  padding: var(--space-2) var(--space-4) var(--space-1);
}

.pending-decision__head {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.pending-decision__icon {
  /* Waiting-state semantics: --orange 70% against the area text. */
  color: color-mix(in srgb, var(--orange) 70%, var(--text));
}

.pending-decision__headline {
  min-width: 0;
  color: var(--text);
  font-size: 13px;
  font-weight: 650;
  line-height: 1.35;
}

.pending-decision__count {
  color: color-mix(in srgb, var(--text) 62%, transparent);
  font-size: 11px;
  font-weight: 600;
  line-height: 1.35;
  white-space: nowrap;
}

/* Several waiting requests read as a pager strip: numbered entries, the active
   one stated in words, so the panel never hides which request it is answering. */
.pending-decision__queue {
  display: flex;
  gap: var(--space-1);
  min-width: 0;
  margin: 0;
  padding: 0;
  list-style: none;
  overflow-x: auto;
}

.pending-decision__queue-cell {
  min-width: 0;
  flex: 0 1 auto;
}

.pending-decision__queue-item {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  max-width: 240px;
  min-width: 0;
  padding: 4px var(--space-2);
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 72%, transparent);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
  transition: background-color 140ms ease-out, border-color 140ms ease-out;
}

.pending-decision__queue-item:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}

.pending-decision__queue-item:active {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.pending-decision__queue-item[aria-current='true'] {
  border-color: color-mix(in srgb, var(--orange) 45%, transparent);
  color: var(--text);
}

.pending-decision__queue-index {
  font-variant-numeric: tabular-nums;
  font-weight: 650;
}

.pending-decision__queue-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pending-decision__queue-state {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--text) 52%, transparent);
}

.pending-decision__body {
  display: grid;
  gap: var(--space-2);
  min-width: 0;
  padding-top: var(--space-2);
  border-top: 1px solid color-mix(in srgb, var(--text) 8%, transparent);
}

.pending-decision__subject {
  margin: 0;
  color: var(--text);
  font-size: 14px;
  font-weight: 650;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.pending-decision__detail {
  margin: 0;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 12.5px;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.pending-decision__facts {
  display: grid;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.pending-decision__fact {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  min-width: 0;
  font-size: 12px;
  line-height: 1.5;
}

.pending-decision__fact-label {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--text) 45%, transparent);
}

.pending-decision__fact-value {
  min-width: 0;
  color: color-mix(in srgb, var(--text) 80%, transparent);
  overflow-wrap: anywhere;
}

.pending-decision__fact-value.is-mono {
  font-family: var(--font-mono);
  font-size: 11.5px;
}

.pending-decision__fact.is-warn .pending-decision__fact-value {
  color: color-mix(in srgb, var(--orange) 74%, var(--text));
  font-weight: 600;
}

/* Numbered choice rows — the same shape as the in-thread card: the marker and
   the consequence stay outside the click target, so a misread costs nothing. */
.pending-decision__actions {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-1);
  min-width: 0;
}

.pending-decision__action {
  display: grid;
  grid-template-columns: auto fit-content(50%) minmax(0, 1fr);
  align-items: baseline;
  column-gap: var(--space-2);
  min-width: 0;
}

.pending-decision__option-index {
  color: color-mix(in srgb, var(--text) 42%, transparent);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  line-height: 1.5;
}

/* One recipe for the panel's choice rows: transparent surface, tone in the
   text, hover and active from the shared alpha scale. */
.pending-decision__option {
  min-height: 32px;
  padding: 4px 7px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 12.5px;
  font-weight: 650;
  text-align: left;
  cursor: pointer;
  transition: background-color 140ms ease-out, color 140ms ease-out;
}

.pending-decision__option:hover:not(:disabled) {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}

.pending-decision__option:active:not(:disabled) {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.pending-decision__option:disabled {
  opacity: .45;
  cursor: default;
}

.pending-decision__option.is-approve {
  color: color-mix(in srgb, var(--green) 78%, var(--text));
}

.pending-decision__option.is-approve:hover:not(:disabled) {
  background: color-mix(in srgb, var(--green) var(--alpha-hover), transparent);
}

.pending-decision__option.is-approve:active:not(:disabled) {
  background: color-mix(in srgb, var(--green) var(--alpha-active), transparent);
}

.pending-decision__option.is-deny {
  color: color-mix(in srgb, var(--red) 78%, var(--text));
}

.pending-decision__option.is-deny:hover:not(:disabled) {
  background: color-mix(in srgb, var(--red) var(--alpha-hover), transparent);
}

.pending-decision__option.is-deny:active:not(:disabled) {
  background: color-mix(in srgb, var(--red) var(--alpha-active), transparent);
}

.pending-decision__option:focus-visible,
.pending-decision__queue-item:focus-visible,
.pending-decision__guide-submit:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--blue) 78%, transparent);
  outline-offset: 2px;
}

.pending-decision__option-desc {
  min-width: 0;
  color: color-mix(in srgb, var(--text) 55%, transparent);
  font-size: 11.5px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

/* Free-form answer: numbered as the row after the offered choices. */
.pending-decision__guide {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: baseline;
  column-gap: var(--space-2);
  min-width: 0;
}

.pending-decision__guide-row {
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
  min-width: 0;
}

/* One row at rest, grown by `autoGrowTextarea` as the answer is typed, then
   scrolling at the five-line cap (the global composer textarea hides that
   overflow, which would silently cut a long explanation). */
.pending-decision__guide-input {
  flex: 1 1 auto;
  min-width: 0;
  padding: 8px var(--space-2);
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--text);
  font: inherit;
  font-size: 13px;
  line-height: 1.45;
  resize: none;
  max-height: calc(5 * 1.45em + 16px);
  overflow-y: auto;
}

/* Inputs carry no focus decoration — the caret is the focus indicator. */
.pending-decision__guide-input:focus-visible {
  outline: none;
}

.pending-decision__guide-input::placeholder {
  color: color-mix(in srgb, var(--text) 45%, transparent);
}

.pending-decision__guide-submit {
  flex: 0 0 auto;
  min-height: 30px;
  padding: 6px var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: var(--theme-control-background);
  color: var(--theme-control-text);
  font: inherit;
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
  transition: filter 140ms ease-out;
}

.pending-decision__guide-submit:hover:not(:disabled) {
  filter: brightness(.94);
}

.pending-decision__guide-submit:active:not(:disabled) {
  filter: brightness(.9);
}

.pending-decision__guide-submit:disabled {
  opacity: .45;
  cursor: default;
}

/* What each surface answers: the field is the free-form choice, the hint says
   so once instead of leaving the user to guess. */
.pending-decision__hint {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  margin: 0;
  color: color-mix(in srgb, var(--text) 50%, transparent);
  font-size: 11.5px;
  line-height: 1.45;
}

.pending-decision__hint-icon {
  flex: 0 0 auto;
}

.pending-decision__notice {
  margin: 0;
  color: color-mix(in srgb, var(--orange) 74%, var(--text));
  font-size: 11.5px;
  line-height: 1.45;
}

@media (max-width: 640px) {
  .pending-decision {
    padding: var(--space-2) var(--space-3) var(--space-1);
  }

  /* A phone must not clip a decision: every choice starts a new row, the
     consequence drops under its label, and the answer field sits above a
     full-width send button. */
  .pending-decision__action {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .pending-decision__option-desc {
    grid-column: 2;
  }

  .pending-decision__queue-item {
    max-width: 60vw;
  }

  .pending-decision__guide-row {
    flex-direction: column;
    align-items: stretch;
  }

  .pending-decision__guide-submit {
    width: 100%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .pending-decision__queue-item,
  .pending-decision__option,
  .pending-decision__guide-submit {
    transition: none;
  }
}
</style>
