<template>
  <section
    class="question-group"
    data-question-group
    :data-group-id="groupId"
    :data-state="stateAttr"
    :class="{
      'question-group--waiting': waiting,
      'question-group--collapsed': collapsed,
      'question-group--collapsing': collapsing,
    }"
    tabindex="0"
    @keydown="onKeydown"
  >
    <!-- 收起态：摘要胶囊。点开可以追加回答，不是终点。 -->
    <button
      v-if="collapsed"
      type="button"
      class="question-group__pill"
      data-question-open
      @click="expand"
    >
      <span class="question-group__pill-dot" aria-hidden="true" />
      <span>{{ pillLabel }}</span>
      <span class="question-group__pill-chev" aria-hidden="true">{{ t('展开') }}</span>
    </button>

    <template v-else>
      <p v-if="questions.length === 0" class="question-group__empty">{{ t('没有收到问题数据') }}</p>

      <div v-for="section in sections" :key="section.key" class="question-group__section">
        <div class="question-group__ghead">
          <b :class="{ 'is-required': section.key === 'required' }">{{ section.title }}</b>
          <span>{{ section.hint }}</span>
        </div>

        <div v-for="question in section.items" :key="question.id" class="question-group__item">
          <div class="question-group__qrow">
            <span class="question-group__title">{{ question.title }}</span>
            <span class="question-group__tag">{{ typeLabel(question) }}</span>
            <span v-if="question.description" class="question-group__desc">{{ question.description }}</span>
          </div>

          <div v-if="question.options.length" class="question-group__choices">
            <button
              v-for="option in question.options"
              :key="option.label"
              type="button"
              class="question-group__choice"
              :aria-pressed="isSelected(question.id, option.label) ? 'true' : 'false'"
              :class="{ 'is-unchecking': isBursting(question.id, option.label) }"
              :disabled="disabled"
              @click="pick(question, option.label, $event)"
            >
              <span class="question-group__flash" aria-hidden="true" />
              <span class="question-group__mark" aria-hidden="true"><i /></span>
              <span class="question-group__label">
                <span>{{ option.label }}</span>
                <span v-if="option.description" class="question-group__od">{{ option.description }}</span>
              </span>
            </button>
          </div>

          <textarea
            :ref="el => setEntry(question.id, el)"
            class="question-group__entry"
            :class="{ 'is-multiline': multiline[question.id] }"
            rows="1"
            :value="custom[question.id] || ''"
            :disabled="disabled"
            :placeholder="question.placeholder || t('也可以直接输入…')"
            :aria-label="question.title"
            @input="onInput(question, $event)"
          />
        </div>
      </div>

      <div class="question-group__foot">
        <button
          type="button"
          class="question-group__submit"
          :class="{ 'is-done': confirming }"
          :disabled="disabled || !canSubmit || confirming"
          data-question-submit
          @click="submit"
        >
          <svg v-if="confirming" class="question-group__check" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4.5 12.5 L9.5 17.8 L19.5 6.5" />
          </svg>
          <template v-else>{{ submitted ? t('保存') : t('提交') }}</template>
        </button>
        <button
          v-if="!submitted && hasRequired"
          type="button"
          class="question-group__link"
          data-question-skip
          :disabled="disabled"
          @click="skip"
        >
          {{ t('跳过') }}
        </button>
        <button
          v-if="submitted"
          type="button"
          class="question-group__link"
          data-question-cancel
          @click="cancel"
        >
          {{ t('取消') }}
        </button>
        <span class="question-group__hint">{{ hintText }}</span>
        <span class="question-group__keys">{{ t('⌘/Ctrl + Enter') }}</span>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { t } from '@/i18n/index.ts'
import type { MessagePart } from '@/types.ts'
import { answeredGroupAnswers, rememberAnsweredGroup } from '@/helpers/questionGroupAnswered.ts'

interface QuestionOption {
  label: string
  description: string
}

interface QuestionItem {
  id: string
  title: string
  description: string
  type: 'single' | 'multiple' | 'text'
  required: boolean
  options: QuestionOption[]
  placeholder: string
}

// user:“确保视觉、功能和交互不退化”+(只读消息禁用问题选项及提交，同时保留原有运行态禁用)。
const props = defineProps<{ part: MessagePart; disabled?: boolean }>()
const emit = defineEmits<{
  submit: [payload: { partId: string; groupId: string; text: string; answers: Record<string, string> }]
  skip: []
}>()

const selections = reactive<Record<string, string[]>>({})
const custom = reactive<Record<string, string>>({})
const multiline = reactive<Record<string, boolean>>({})
const bursting = reactive<Record<string, boolean>>({})

const submitted = ref(false)
const collapsed = ref(false)
const confirming = ref(false)
const collapsing = ref(false)

/**
 * user:“我这一张卡明明回答了…随后又出现在我的回答下方，且变成了未回答，但是根据模型的回复
 * 它确实收到了我的回答”+(已回答此前只存在组件本地态里：卡片一旦被重新挂载（位置换算、
 * 同一组再发一次事件），状态就丢了，回到未回答。这里按问组 id 记在模块级，
 * 同一次会话里重新挂上来仍然是「已回答」，并回填当时的答案。)
 */
// 记录放在模块级（helpers/questionGroupAnswered.ts）：<script setup> 顶层是每个实例
// 各一份，卡片重新挂载就留不住，这里必须用模块级的。
const restoredGroupIds = new Set<string>()

/** 后端把答案写在题目上（question.answer）：这是比本地记录更权威的来源。 */
function answersFromPart(): Record<string, string> {
  const result: Record<string, string> = {}
  const nested = asRecord(metadata.value.payload)
  for (const source of [metadata.value.questions, nested ? nested.questions : undefined]) {
    if (!Array.isArray(source)) continue
    for (const record of source) {
      const item = asRecord(record)
      if (!item) continue
      const id = String(item.id || '').trim()
      const answer = String(item.answer ?? item.value ?? '').trim()
      if (id && answer) result[id] = answer
    }
  }
  return result
}

function applyStoredAnswers(groupKey: string): void {
  if (!groupKey || restoredGroupIds.has(groupKey)) return
  const stored = answeredGroupAnswers(groupKey)
  // 后端已把关闭原因写进分片，或把答案写在题目上：以数据为准。
  const closedByBackend = Boolean(metadata.value.closed_reason)
  if (!stored && !closedByBackend) return
  restoredGroupIds.add(groupKey)
  if (stored) {
    for (const [questionId, answer] of Object.entries(stored)) {
      const question = questions.value.find(item => item.id === questionId)
      if (!question) continue
      const options = question.options.map(option => option.label)
      if (options.includes(answer)) selections[questionId] = [answer]
      else if (options.length > 0 && answer.split('、').every(part => options.includes(part))) {
        selections[questionId] = answer.split('、').filter(Boolean)
      } else custom[questionId] = answer
    }
  }
  submitted.value = true
  collapsed.value = true
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? value as Record<string, unknown> : null
}

function readQuestions(value: unknown): QuestionItem[] {
  if (!Array.isArray(value)) return []
  const result: QuestionItem[] = []
  for (const item of value) {
    const record = asRecord(item)
    if (!record) continue
    const type = String(record.type || 'text')
    result.push({
      id: String(record.id || `q${result.length + 1}`),
      title: String(record.title || record.question || ''),
      description: String(record.description || record.header || ''),
      type: type === 'single' || type === 'multiple' ? type : 'text',
      required: record.required !== false,
      options: Array.isArray(record.options)
        ? record.options.map(option => {
          const entry = asRecord(option)
          if (!entry) return { label: String(option || ''), description: '' }
          return {
            label: String(entry.label || ''),
            description: String(entry.description || ''),
          }
        }).filter(option => option.label)
        : [],
      placeholder: String(record.placeholder || ''),
    })
  }
  return result
}

const metadata = computed(() => asRecord(props.part.metadata) || {})
const questions = computed(() => {
  const direct = readQuestions(metadata.value.questions)
  if (direct.length > 0) return direct
  const nested = asRecord(metadata.value.payload)
  return readQuestions(nested ? nested.questions : undefined)
})
const groupId = computed(() => String(metadata.value.question_group_id || metadata.value.group_id || ''))
const disabled = computed(() => Boolean(props.disabled) || props.part.status === 'running')
const waiting = computed(() => !submitted.value && !disabled.value)
const stateAttr = computed(() => (submitted.value ? 'answered' : 'pending'))

/**
 * user:“渲染时自动按必答和非必答分类”+(必答在前、可选在后；必答只由分组标题表达，
 * 题目旁不再重复「必答」标签，只说明这题怎么答。)
 */
const sections = computed(() => [
  { key: 'required', title: t('必答'), hint: t('填写后才能继续'), items: questions.value.filter(q => q.required) },
  { key: 'optional', title: t('可选'), hint: t('可留空'), items: questions.value.filter(q => !q.required) },
].filter(section => section.items.length > 0))

function typeLabel(question: QuestionItem): string {
  if (question.type === 'multiple') return t('多选')
  if (question.type === 'single' && question.options.length > 0) return t('单选')
  return t('自由输入')
}

function isSelected(questionId: string, label: string): boolean {
  return (selections[questionId] || []).includes(label)
}

function answerFor(question: QuestionItem): string {
  const typed = String(custom[question.id] || '').trim()
  if (typed) return typed
  return (selections[question.id] || []).join('、')
}

const hasRequired = computed(() => questions.value.some(question => question.required))
const requiredLeft = computed(() => questions.value.filter(q => q.required && !answerFor(q)).length)
const canSubmit = computed(() => requiredLeft.value === 0)
const answeredCount = computed(() => questions.value.filter(q => answerFor(q)).length)
const pillLabel = computed(() => t('已回答 {0} 个问题', { 0: answeredCount.value }))
const hintText = computed(() => (requiredLeft.value > 0 ? t('还差 {0} 道必答', { 0: requiredLeft.value }) : ''))

// 挂载即回填：同一次会话里这张卡重新挂上来时，仍然是「已回答」并带回当时的答案。
watch([groupId, questions], () => {
  applyStoredAnswers(groupId.value)
}, { immediate: true })

/* ── 输入框：胶囊内自动换行，最高 84px，再多内部滚动 ─────────────── */
const entries: Record<string, HTMLTextAreaElement | null> = {}

function setEntry(id: string, el: unknown) {
  entries[id] = (el as HTMLTextAreaElement) || null
}

function autoGrow(id: string) {
  const el = entries[id]
  if (!el) return
  const scroll = el.scrollHeight
  if (!scroll) return
  el.style.height = 'auto'
  const next = Math.min(scroll, 84)
  el.style.height = `${next}px`
  multiline[id] = next > 30
}

function growAll() {
  questions.value.forEach(question => autoGrow(question.id))
}

function onInput(question: QuestionItem, event: Event) {
  const el = event.target as HTMLTextAreaElement
  custom[question.id] = el.value
  autoGrow(question.id)
}

/* ── 点击：只改这一行，卡片不重渲染 ─────────────────────────────── */
function burstKey(questionId: string, label: string): string {
  return `${questionId}::${label}`
}

function isBursting(questionId: string, label: string): boolean {
  return Boolean(bursting[burstKey(questionId, label)])
}

/**
 * user:“选项取消后那个圆环作为向外扩展消失；如果你是用黑白圆相叠的话，就是黑圆扩大”
 * +(取消的那一行播一次外扩动画。先摘掉类再下一帧加回去，连续点同一个选项也能重放。)
 */
function burst(questionId: string, label: string) {
  const key = burstKey(questionId, label)
  if (bursting[key]) delete bursting[key]
  const start = () => {
    bursting[key] = true
    window.setTimeout(() => { delete bursting[key] }, 420)
  }
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(start)
  else window.setTimeout(start, 16)
}

/** 点击的那一下：只在这一行的叠层上闪一次，用 WAAPI 重放。 */
function flash(target: EventTarget | null) {
  const row = target as HTMLElement | null
  const layer = row?.querySelector?.('.question-group__flash') as HTMLElement | null
  if (!layer || typeof layer.animate !== 'function') return
  layer.animate([{ opacity: 0.9 }, { opacity: 0 }], { duration: 260, easing: 'ease-out' })
}

function pick(question: QuestionItem, label: string, event: MouseEvent) {
  if (disabled.value) return
  const current = selections[question.id] || []
  const wasOn = current.includes(label)

  if (question.type === 'multiple') {
    selections[question.id] = wasOn ? current.filter(item => item !== label) : [...current, label]
  } else {
    selections[question.id] = wasOn ? [] : [label]
    const dropped = current.find(item => item !== label)
    if (dropped) burst(question.id, dropped)   // 单选换选：被顶掉的那一项也外扩
  }

  if (wasOn) burst(question.id, label)
  flash(event.currentTarget)

  // 选了选项就清空自由输入，两者不并存
  custom[question.id] = ''
  const entry = entries[question.id]
  if (entry) {
    entry.value = ''
    autoGrow(question.id)
  }
}

/* ── 提交 / 收起 / 追加 ──────────────────────────────────────────── */
let snapshot: { selections: Record<string, string[]>; custom: Record<string, string> } | null = null

function takeSnapshot() {
  const nextSelections: Record<string, string[]> = {}
  const nextCustom: Record<string, string> = {}
  Object.keys(selections).forEach(key => { nextSelections[key] = [...selections[key]] })
  Object.keys(custom).forEach(key => { nextCustom[key] = custom[key] })
  return { selections: nextSelections, custom: nextCustom }
}

function restoreSnapshot() {
  const saved = snapshot
  if (!saved) return
  Object.keys(selections).forEach(key => { delete selections[key] })
  Object.keys(custom).forEach(key => { delete custom[key] })
  Object.keys(saved.selections).forEach(key => { selections[key] = [...saved.selections[key]] })
  Object.keys(saved.custom).forEach(key => { custom[key] = saved.custom[key] })
  nextTick(growAll)
}

function submit() {
  if (!canSubmit.value || disabled.value || confirming.value) return
  const answers: Record<string, string> = {}
  const lines: string[] = []
  questions.value.forEach((question, index) => {
    const answer = answerFor(question)
    if (!answer) return
    answers[question.id] = answer
    lines.push(`Q${index + 1} ${question.title}：${answer}`)
  })
  if (lines.length === 0) return

  snapshot = takeSnapshot()
  const answeredKey = groupId.value
  if (answeredKey) {
    // user:“已回答过的卡展开之后再补充回答”+(补答要合并进已有记录，覆盖会让先前的答案
    // 从摘要与回填里消失。)
    rememberAnsweredGroup(answeredKey, { ...(answeredGroupAnswers(answeredKey) || {}), ...answers })
    restoredGroupIds.add(answeredKey)
  }
  submitted.value = true
  confirming.value = true

  // 先画对勾（300ms），再整卡收起（500ms），最后只剩摘要胶囊
  window.setTimeout(() => {
    confirming.value = false
    collapsing.value = true
    window.setTimeout(() => {
      collapsing.value = false
      collapsed.value = true
    }, 500)
  }, 300)

  emit('submit', {
    partId: props.part.id,
    groupId: groupId.value,
    text: lines.join('\n'),
    answers,
  })
}

function expand() {
  collapsed.value = false
  nextTick(growAll)
}

/**
 * user:“跳过等于 done 没问题吧？”+(跳过不是本地收起：交给宿主发恢复请求，由后端
 * 把组关成 done 并继续这一回合；卡片自己不改状态，避免说跳过后回合还停着。)
 */
function skip() {
  if (disabled.value || submitted.value) return
  emit('skip')
}

/** user:“追加回答为什么没有取消键？”+(展开追加时取消丢弃改动，回到摘要胶囊。) */
function cancel() {
  restoreSnapshot()
  collapsed.value = true
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
    if (!canSubmit.value || disabled.value) return
    event.preventDefault()
    submit()
    return
  }
  if (event.key === 'Escape' && submitted.value && !collapsed.value) {
    event.preventDefault()
    cancel()
  }
}

nextTick(growAll)
</script>

<style scoped>
/* 卡片外形：2px 边；「等你处理」时边框本身是流光，不叠加实色边。 */
.question-group {
  --text: var(--theme-main-text, currentColor);
  --hairline: color-mix(in srgb, var(--text) 10%, transparent);
  position: relative;
  margin: var(--space-2, 8px) 0;
  padding: 10px 12px 8px;
  border: 2px solid color-mix(in srgb, var(--text) 26%, transparent);
  border-radius: var(--radius, 12px);
  background: var(--theme-main-background, transparent);
  color: var(--text);
  font-size: 13px;
  line-height: 1.5;
  outline: none;
  transition: opacity 500ms ease, transform 500ms ease, border-color 200ms ease-out;
}

.question-group--collapsed {
  border-color: transparent;
  padding: 0;
  background: transparent;
}

.question-group--collapsing {
  opacity: 0;
  transform: translateY(-4px) scale(0.992);
}

.question-group--waiting {
  border-color: transparent;
}

.question-group--waiting::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  padding: 2px;
  background: conic-gradient(
    from var(--qg-angle),
    color-mix(in srgb, var(--text) 12%, transparent) 0deg,
    color-mix(in srgb, var(--text) 12%, transparent) 20deg,
    color-mix(in srgb, var(--text) 50%, transparent) 55deg,
    color-mix(in srgb, var(--text) 95%, transparent) 90deg,
    color-mix(in srgb, var(--text) 50%, transparent) 125deg,
    color-mix(in srgb, var(--text) 12%, transparent) 160deg,
    color-mix(in srgb, var(--text) 12%, transparent) 200deg,
    color-mix(in srgb, var(--text) 50%, transparent) 235deg,
    color-mix(in srgb, var(--text) 95%, transparent) 270deg,
    color-mix(in srgb, var(--text) 50%, transparent) 305deg,
    color-mix(in srgb, var(--text) 12%, transparent) 340deg,
    color-mix(in srgb, var(--text) 12%, transparent) 360deg
  );
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  mask-composite: exclude;
  pointer-events: none;
  animation: qg-rotate 8s linear infinite;
}

@property --qg-angle {
  syntax: "<angle>";
  initial-value: 0deg;
  inherits: false;
}

@keyframes qg-rotate {
  to { --qg-angle: 360deg; }
}

/* 收起后的摘要胶囊 */
.question-group__pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 14px;
  border: 1px solid color-mix(in srgb, var(--text) 26%, transparent);
  border-radius: 999px;
  background: transparent;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font: inherit;
  font-size: 12.5px;
  cursor: pointer;
  animation: qg-pill-in 500ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
  transition: background-color 100ms ease-out, color 100ms ease-out, border-color 100ms ease-out;
}

.question-group__pill:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover, 8%), transparent);
  color: var(--text);
  border-color: color-mix(in srgb, var(--text) 40%, transparent);
}

.question-group__pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--green);
}

.question-group__pill-chev {
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: 10px;
}

@keyframes qg-pill-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: none; }
}

.question-group__empty {
  margin: 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--text) 45%, transparent);
}

/* 分组：必答在前、可选在后 */
.question-group__section + .question-group__section {
  margin-top: 4px;
  border-top: 1px solid var(--hairline);
}

.question-group__ghead {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 7px 0 2px;
  font-size: 11px;
  letter-spacing: 0.04em;
}

.question-group__ghead b {
  font-weight: 620;
  color: color-mix(in srgb, var(--text) 65%, transparent);
}

.question-group__ghead b.is-required {
  color: color-mix(in srgb, var(--decision-attention, #b49a60) 88%, var(--text));
}

.question-group__ghead span {
  color: color-mix(in srgb, var(--text) 25%, transparent);
}

.question-group__item {
  padding: 4px 0 8px;
}

.question-group__item + .question-group__item {
  border-top: 1px dashed color-mix(in srgb, var(--text) 8%, transparent);
}

.question-group__qrow {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-height: 18px;
}

.question-group__title {
  font-weight: 500;
}

.question-group__tag {
  padding: 0 5px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--text) 6%, transparent);
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: 10px;
  line-height: 15px;
}

.question-group__desc {
  color: color-mix(in srgb, var(--text) 25%, transparent);
  font-size: 11px;
}

/* 选项：一项一行；点击只改这一行 */
.question-group__choices {
  display: grid;
  gap: 3px;
  margin-top: 5px;
}

.question-group__choice {
  position: relative;
  isolation: isolate;
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  min-height: 30px;
  padding: 3px 11px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font: inherit;
  font-size: 12.5px;
  text-align: left;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  transition: background-color 110ms ease-out, color 110ms ease-out, border-color 110ms ease-out;
}

.question-group__choice:hover:not(:disabled) {
  background: color-mix(in srgb, var(--text) var(--alpha-hover, 8%), transparent);
  color: var(--text);
}

.question-group__choice:active:not(:disabled) {
  background: color-mix(in srgb, var(--text) var(--alpha-active, 12%), transparent);
}

.question-group__choice:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--text) 45%, transparent);
}

.question-group__choice[aria-pressed="true"] {
  background: color-mix(in srgb, var(--text) 5.5%, transparent);
  border-color: var(--hairline);
  color: var(--text);
}

.question-group__choice:disabled {
  opacity: 0.5;
  cursor: default;
}

.question-group__flash {
  position: absolute;
  inset: 0;
  z-index: -1;
  border-radius: inherit;
  background: color-mix(in srgb, var(--text) 16%, transparent);
  opacity: 0;
  pointer-events: none;
}

.question-group__mark {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 15px;
  height: 15px;
  border: 1.5px solid var(--hairline);
  border-radius: 50%;
  transition: border-color 140ms ease-out, background-color 140ms ease-out, transform 90ms ease-out;
}

.question-group__mark i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--theme-control-text, var(--text));
  transform: scale(0.2);
  opacity: 0;
  transition: transform 200ms cubic-bezier(0.2, 1.6, 0.4, 1), opacity 110ms ease-out;
}

.question-group__choice:active:not(:disabled) .question-group__mark {
  transform: scale(0.82);
}

.question-group__choice[aria-pressed="true"] .question-group__mark {
  border-color: var(--theme-control-solid, var(--text));
  background: var(--theme-control-solid, var(--text));
}

.question-group__choice[aria-pressed="true"] .question-group__mark i {
  transform: scale(1);
  opacity: 1;
}

/* 取消选中：黑点向外扩张吃掉白底，扩出边框后淡掉 */
.question-group__choice.is-unchecking .question-group__mark {
  transition: background-color 260ms ease-out, border-color 260ms ease-out;
}

.question-group__choice.is-unchecking .question-group__mark i {
  animation: qg-dot-out 320ms cubic-bezier(0.2, 0.75, 0.3, 1) forwards;
}

@keyframes qg-dot-out {
  0% { transform: scale(1); opacity: 1; }
  55% { transform: scale(2.1); opacity: 0.95; }
  100% { transform: scale(3.9); opacity: 0; }
}

.question-group__label {
  display: flex;
  align-items: baseline;
  gap: 7px;
  min-width: 0;
}

.question-group__od {
  color: color-mix(in srgb, var(--text) 25%, transparent);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 自由输入：胶囊，自动换行，最高 84px */
.question-group__entry {
  display: block;
  width: 100%;
  min-height: 30px;
  max-height: 84px;
  margin-top: 5px;
  padding: 6px 14px;
  box-sizing: border-box;
  border: 1px solid var(--hairline);
  border-radius: 999px;
  background: var(--theme-main-sunken-background, rgba(0, 0, 0, 0.18));
  color: inherit;
  font: inherit;
  font-size: 12.5px;
  line-height: 18px;
  resize: none;
  overflow: hidden;
  transition: border-color 110ms ease-out, border-radius 110ms ease-out;
  scrollbar-width: thin;
}

.question-group__entry.is-multiline {
  border-radius: 14px;
  overflow-y: auto;
}

.question-group__entry::placeholder {
  color: color-mix(in srgb, var(--text) 25%, transparent);
}

.question-group__entry:focus,
.question-group__entry:focus-visible {
  outline: none;
  border-color: color-mix(in srgb, var(--text) 45%, transparent);
}

.question-group__entry:disabled {
  opacity: 0.5;
}

.question-group__foot {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--hairline);
}

.question-group__submit {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 28px;
  padding: 0 14px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: var(--theme-control-solid, var(--control, rgba(127, 127, 127, 0.24)));
  color: var(--theme-control-text, inherit);
  font: inherit;
  font-size: 12px;
  font-weight: 560;
  cursor: pointer;
  transition: filter 100ms ease-out, width 160ms ease-out, padding 160ms ease-out;
}

.question-group__submit:hover:not(:disabled) {
  filter: brightness(0.94);
}

.question-group__submit:disabled {
  opacity: 0.38;
  cursor: default;
}

.question-group__submit.is-done {
  width: 28px;
  padding: 0;
  opacity: 1;
}

.question-group__check {
  width: 15px;
  height: 15px;
}

.question-group__check path {
  fill: none;
  stroke: currentColor;
  stroke-width: 2.6;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 26;
  stroke-dashoffset: 26;
  animation: qg-draw-check 300ms ease-out forwards;
}

@keyframes qg-draw-check {
  to { stroke-dashoffset: 0; }
}

.question-group__link {
  height: auto;
  padding: 0;
  border: 0;
  background: none;
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.question-group__link:hover {
  color: var(--text);
}

.question-group__hint {
  color: color-mix(in srgb, var(--text) 25%, transparent);
  font-size: 11px;
}

.question-group__keys {
  margin-left: auto;
  color: color-mix(in srgb, var(--text) 25%, transparent);
  font-size: 11px;
}

@media (prefers-reduced-motion: reduce) {
  .question-group--waiting::before {
    animation: none;
    opacity: 0.55;
  }

  .question-group__pill,
  .question-group__choice.is-unchecking .question-group__mark i,
  .question-group__check path {
    animation: none;
  }

  .question-group__check path {
    stroke-dashoffset: 0;
  }
}

@media (max-width: 640px) {
  .question-group__keys {
    display: none;
  }

  .question-group__submit {
    flex: 1;
  }
}
</style>
