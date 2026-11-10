<template>
  <!--
    user:“可以自动建一个教学示例会话，使用mock数据流演示并走过完整agent流程
          （不调用真实API）”+
    (这里刻意不复用真实的会话与网络通道：消息是本地脚本生成的，发送键只推进
     阶段，审批键只改本地状态。眼睛看到的渲染却是真的聊天渲染器，所以学到的
     位置和样子跟真用的时候一致。)
  -->
  <div class="guide-demo" :class="'guide-demo--' + state.stage">
    <div class="guide-demo-frame">
      <header class="guide-demo-top">
        <span class="guide-demo-dots" aria-hidden="true"><i></i><i></i><i></i></span>
        <span class="guide-demo-title">{{ t("教学示例会话") }}</span>
        <span class="guide-demo-badge">{{ t("不联网") }}</span>
      </header>

      <div class="guide-demo-body">
        <nav class="guide-demo-rail" aria-hidden="true">
          <span v-for="icon in railIcons" :key="icon.name" class="guide-demo-rail-dot" :class="{ 'is-active': icon.active }">
            <component :is="icon.component" :size="14" :stroke-width="1.8" />
          </span>
        </nav>

        <div ref="threadEl" class="guide-demo-thread">
          <p v-if="!state.sent" class="guide-demo-empty">
            {{ t("你发的消息和我做的事，都会出现在这块地方。") }}
          </p>
          <ChatThread
            :messages="messages"
            :show-empty-state="false"
            :assistant-label="t('Sunday')"
            :assistant-model-labels="{ 'guide-demo': t('示例模型') }"
            :process-expanded-ids="expandedIds"
            :transport="demoTransport"
            @decision-select="onDecision"
          />
          <div v-if="state.stage === 'approval'" class="guide-demo-pointer" aria-hidden="true">
            <span class="guide-demo-pointer-dot"></span>
            <span class="guide-demo-pointer-text">{{ t("这里要你选一个") }}</span>
          </div>
        </div>
      </div>

      <div class="guide-demo-composer">
        <div class="guide-demo-chips" aria-hidden="true">
          <span class="guide-demo-chip">{{ t("Agent · 询问") }}</span>
          <span class="guide-demo-chip">{{ t("示例模型 · 中") }}</span>
        </div>
        <div class="guide-demo-input" :class="{ 'is-sent': state.sent }">
          {{ state.sent ? t("（已经发出去了）") : MOCK_USER_TEXT }}
        </div>
        <button
          class="guide-demo-send"
          type="button"
          :disabled="state.sent"
          :aria-label="t('发送')"
          data-guide-demo-send
          @click="onSend"
        >
          <ArrowUp :size="16" :stroke-width="2.4" aria-hidden="true" />
        </button>
      </div>
    </div>

    <div class="guide-demo-caption" aria-live="polite">
      <p class="guide-demo-caption-title">{{ caption.title }}</p>
      <p class="guide-demo-caption-why">{{ caption.why }}</p>
      <div class="guide-demo-caption-actions">
        <button class="guide-text-button" type="button" @click="replay">{{ t("重演一次") }}</button>
        <button class="guide-text-button" type="button" @click="emit('done')">{{ t("看完了，继续") }}</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowUp, Bot, CalendarClock, House, MonitorSmartphone, Puzzle, Settings, Sparkles } from 'lucide-vue-next'
import ChatThread from '@/components/ChatThread.vue'
import type { LamToolsTransport } from '@/transport/index.ts'
import type { CoreMessage } from '@/types.ts'
import {
  MOCK_USER_TEXT,
  createMockConversation,
  mockAssistantMessage,
  mockCaption,
  mockUserMessage,
  reduceMockConversation,
  type MockAction,
  type MockConversationState,
} from '@/guide/mockConversation.ts'

const emit = defineEmits<{ done: [] }>()

const state = ref<MockConversationState>(createMockConversation())
const answerChars = ref(0)
const threadEl = ref<HTMLElement | null>(null)

// 教学剧场没有后端：任何真正的字节请求都直接说清楚“这里不联网”。
const demoTransport = {
  request: async () => {
    throw new Error(t("教学示例不联网"))
  },
} as unknown as LamToolsTransport

const railIcons = [
  { name: 'chat', component: House, active: true },
  { name: 'direct', component: Sparkles, active: false },
  { name: 'superagent', component: Bot, active: false },
  { name: 'arrange', component: CalendarClock, active: false },
  { name: 'plugins', component: Puzzle, active: false },
  { name: 'settings', component: Settings, active: false },
  { name: 'account', component: MonitorSmartphone, active: false },
]

const messages = computed<CoreMessage[]>(() => {
  const list: CoreMessage[] = []
  const user = mockUserMessage(state.value)
  if (user) list.push(user)
  const assistant = mockAssistantMessage(state.value, answerChars.value)
  if (assistant) list.push(assistant)
  return list
})

const expandedIds = computed(() => new Set(['guide-demo-assistant']))
const caption = computed(() => mockCaption(state.value))

let timers: Array<ReturnType<typeof setTimeout>> = []
let streamTimer: ReturnType<typeof setInterval> | null = null

function clearTimers(): void {
  for (const timer of timers) clearTimeout(timer)
  timers = []
  if (streamTimer) clearInterval(streamTimer)
  streamTimer = null
}

function after(ms: number, run: () => void): void {
  timers.push(setTimeout(run, ms))
}

function dispatch(action: MockAction): void {
  state.value = reduceMockConversation(state.value, action)
}

function onSend(): void {
  if (state.value.stage !== 'idle') return
  dispatch('send')
  clearTimers()
  after(1500, () => dispatch('advance'))
  after(2600, () => dispatch('advance'))
}

function onDecision(payload: { option: { id: string } }): void {
  const id = payload.option.id
  if (id !== 'allow-once' && id !== 'trust-kind' && id !== 'deny') return
  dispatch(id)
  clearTimers()
  if (id !== 'deny') {
    after(1700, () => dispatch('advance'))
  }
}

function replay(): void {
  clearTimers()
  answerChars.value = 0
  state.value = createMockConversation()
}

function startAnswerStream(): void {
  const full = mockAssistantMessage(state.value)?.content || ''
  answerChars.value = 0
  if (!full) return
  const step = Math.max(1, Math.ceil(full.length / 90))
  streamTimer = setInterval(() => {
    answerChars.value = Math.min(full.length, answerChars.value + step)
    // 结论一边出，视线一边跟到底：教学演示里没人愿意自己找滚动条。
    const node = threadEl.value
    if (node) node.scrollTop = node.scrollHeight
    if (answerChars.value >= full.length && streamTimer) {
      clearInterval(streamTimer)
      streamTimer = null
    }
  }, 24)
}

watch(
  () => state.value.stage,
  (stage, previous) => {
    if (stage !== previous && (stage === 'answered' || stage === 'denied')) startAnswerStream()
    if (stage === 'approval') {
      // 审批卡出现后把视线带过去，免得用户以为没反应。
      requestAnimationFrame(() => {
        threadEl.value?.scrollTo({ top: threadEl.value.scrollHeight, behavior: 'smooth' })
      })
    }
  },
)

onBeforeUnmount(clearTimers)
</script>

<style scoped>
.guide-demo {
  display: grid;
  gap: var(--space-3);
  --text: var(--theme-main-text, #fbf7f0);
}

.guide-demo-frame {
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius);
  background: var(--theme-main-background, #1b1d22);
  box-shadow: var(--shadow-md);
}

.guide-demo-top {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 34px;
  padding: 0 var(--space-3);
  border-bottom: 1px solid color-mix(in srgb, var(--text) 9%, transparent);
  background: var(--theme-main-soft-background, rgba(255, 255, 255, .04));
}

.guide-demo-dots {
  display: flex;
  gap: 5px;
}

.guide-demo-dots i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--text) 18%, transparent);
}

.guide-demo-title {
  font-size: 11.5px;
  font-weight: 620;
  color: color-mix(in srgb, var(--text) 62%, transparent);
}

.guide-demo-badge {
  margin-left: auto;
  padding: 2px 7px;
  border: 1px solid color-mix(in srgb, var(--text) 14%, transparent);
  border-radius: 999px;
  font-size: 10.5px;
  color: color-mix(in srgb, var(--text) 52%, transparent);
}

.guide-demo-body {
  display: flex;
  min-height: 0;
  height: 320px;
}

.guide-demo-rail {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--space-2) 5px;
  border-right: 1px solid color-mix(in srgb, var(--text) 8%, transparent);
  background: color-mix(in srgb, var(--text) 2%, transparent);
}

.guide-demo-rail-dot {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: var(--radius-sm);
  color: color-mix(in srgb, var(--text) 34%, transparent);
}

.guide-demo-rail-dot.is-active {
  background: color-mix(in srgb, var(--text) 10%, transparent);
  color: color-mix(in srgb, var(--text) 82%, transparent);
}

.guide-demo-thread {
  position: relative;
  flex: 1 1 auto;
  min-width: 0;
  overflow-y: auto;
  padding: var(--space-2) var(--space-1) var(--space-3);
  scrollbar-width: thin;
  /* 滚动到底时顶部会切掉半行：用渐隐代替硬边，读起来不像坏掉。 */
  mask-image: linear-gradient(to bottom, transparent 0, #000 14px, #000 calc(100% - 6px), transparent 100%);
}

/* 真渲染器在演示框里要收一收：正文与过程按窄栏排版，不撑破卡片。 */
.guide-demo-thread :deep(.thread) {
  max-width: none;
}

.guide-demo-thread :deep(.chat-thread) {
  padding: 0 var(--space-2);
}

/* 教学消息没有真实计时，也没有真实的模型记录：整行元信息会露出「耗时 —」，
   看起来像出错。这里只保留消息本身的正文与过程。 */
.guide-demo-thread :deep(.assistant-meta) {
  display: none;
}

.guide-demo-empty {
  display: grid;
  place-items: center;
  min-height: 200px;
  margin: 0;
  padding: var(--space-4);
  text-align: center;
  font-size: 12.5px;
  line-height: 1.7;
  color: color-mix(in srgb, var(--text) 32%, transparent);
}

/* 教学演示没有接“自由填写处理方式”这条通道：留着会让人点了没反应，
   这一步只教三个按钮的含义。 */
.guide-demo-thread :deep(.decision-guide) {
  display: none;
}

.guide-demo-pointer {
  position: sticky;
  bottom: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: max-content;
  margin: var(--space-1) auto 0;
  padding: 4px var(--space-2);
  border: 1px solid color-mix(in srgb, var(--decision-attention, #b49a60) 55%, transparent);
  border-radius: 999px;
  background: var(--theme-main-background, #1b1d22);
  animation: guide-demo-bob 1.8s ease-in-out infinite;
}

.guide-demo-pointer-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--decision-attention, #b49a60);
}

.guide-demo-pointer-text {
  font-size: 11.5px;
  color: color-mix(in srgb, var(--text) 76%, transparent);
}

.guide-demo-composer {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3) var(--space-3);
  border-top: 1px solid color-mix(in srgb, var(--text) 9%, transparent);
}

.guide-demo-chips {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex: 0 0 auto;
}

.guide-demo-chip {
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--text) 7%, transparent);
  font-size: 10px;
  white-space: nowrap;
  color: color-mix(in srgb, var(--text) 62%, transparent);
}

.guide-demo-input {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 0 var(--space-2);
  font-size: 13px;
  color: color-mix(in srgb, var(--text) 86%, transparent);
}

.guide-demo-input.is-sent {
  color: color-mix(in srgb, var(--text) 40%, transparent);
  font-style: italic;
}

.guide-demo-send {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 50%;
  background: var(--theme-control-solid, #fbf7f0);
  color: var(--theme-control-text, #2e3138);
  cursor: pointer;
  transition: filter var(--dur-fast, .16s) var(--ease-out, ease-out), transform var(--dur-fast, .16s) var(--ease-out, ease-out);
}

.guide-demo-send:hover:not(:disabled) {
  filter: brightness(.94);
  transform: translateY(-1px);
}

.guide-demo-send:disabled {
  cursor: default;
  opacity: .45;
}

.guide-demo-caption {
  display: grid;
  gap: 2px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid color-mix(in srgb, var(--text) 10%, transparent);
  border-radius: var(--radius);
  background: var(--theme-main-soft-background, rgba(255, 255, 255, .04));
}

.guide-demo-caption-title {
  margin: 0;
  font-size: 13px;
  font-weight: 680;
}

.guide-demo-caption-why {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: color-mix(in srgb, var(--text) 60%, transparent);
}

.guide-demo-caption-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  margin-top: 2px;
}

.guide-text-button {
  border: 0;
  padding: 2px 0;
  background: transparent;
  color: color-mix(in srgb, var(--text) 46%, transparent);
  font: inherit;
  font-size: 12px;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}

.guide-text-button:hover {
  color: color-mix(in srgb, var(--text) 78%, transparent);
}

.guide-demo-caption-actions .guide-text-button {
  color: color-mix(in srgb, var(--text) 58%, transparent);
}

.guide-demo-caption-actions .guide-text-button:hover {
  color: var(--text);
}

@keyframes guide-demo-bob {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-3px); }
}

@media (max-width: 640px) {
  .guide-demo-body { height: 240px; }
  .guide-demo-rail { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  .guide-demo-pointer { animation: none; }
  .guide-demo-send { transition: none; }
}
</style>
