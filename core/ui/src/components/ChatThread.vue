<template>
  <div class="chat-thread">
    <div v-if="messages.length === 0" class="sidebar-empty">
      <slot name="empty">
        <span>暂无消息，发送一个任务。</span>
      </slot>
    </div>

    <MessageView
      v-for="msg in messages"
      :key="msg.id"
      v-memo="[msg, assistantLabel, processExpandedIds.has(msg.id), typingMessageIds.has(msg.id), messageActions]"
      :msg="msg"
        :assistant-label="assistantLabel"
        :process-expanded-ids="processExpandedIds"
        :typing-message-ids="typingMessageIds"
        :message-actions="messageActions"
      :api-base="apiBase"
      :project-id="projectId"
      :work-root="workRoot"
      @toggle-process="onToggleProcess"
        @decision-select="onDecisionSelect"
        @fork-message="onForkMessage"
        @rollback-message="onRollbackMessage"
      >
        <template v-if="$slots['message-product']" #message-product="slotProps">
          <slot name="message-product" v-bind="slotProps" />
        </template>
        <template v-if="$slots['assistant-content']" #assistant-content="slotProps">
          <slot name="assistant-content" v-bind="slotProps" />
        </template>
        <template v-if="$slots['reasoning-content']" #reasoning-content="slotProps">
          <slot name="reasoning-content" v-bind="slotProps" />
        </template>
        <template v-if="$slots['message-footer']" #message-footer="slotProps">
          <slot name="message-footer" v-bind="slotProps" />
        </template>
      </MessageView>

    <slot name="tail" />
  </div>
</template>

<script setup lang="ts">
import type { CoreMessage } from '../types'
import MessageView from './MessageView.vue'

defineOptions({ name: 'ChatThread' })

defineSlots<{
  empty?: () => unknown
  tail?: () => unknown
  'message-product'?: (props: { message: CoreMessage }) => unknown
  'assistant-content'?: (props: { content: string; live?: boolean }) => unknown
  'reasoning-content'?: (props: { content: string; live?: boolean }) => unknown
  'message-footer'?: (props: { message: CoreMessage }) => unknown
}>()

const props = withDefaults(
  defineProps<{
    messages: CoreMessage[]
    assistantLabel?: string
    /** Set of message ids whose process section is expanded */
    processExpandedIds?: Set<string>
    /** Set of message ids that should play a typewriter reveal */
    typingMessageIds?: Set<string>
    /** Show hover actions (copy / fork / roll back) under assistant replies */
    messageActions?: boolean
    /** API base for building file raw URLs (e.g. /api/core); used for image artifact previews */
    apiBase?: string
    /** Project id whose work_root contains the image artifact paths */
    projectId?: string | null
    /** Project work_root — enables direct local file reads in Tauri (asset protocol) */
    workRoot?: string | null
  }>(),
  {
    assistantLabel: 'Assistant',
    processExpandedIds: () => new Set(),
    typingMessageIds: () => new Set(),
    messageActions: false,
    apiBase: '/api/core',
    projectId: null,
    workRoot: null,
  },
)

const emit = defineEmits<{
  'toggle-process': [messageId: string]
  'decision-select': [payload: { partId: string; option: DecisionOption; response: string }]
  'fork-message': [payload: AssistantActionPayload]
  'rollback-message': [payload: AssistantActionPayload]
}>()

interface DecisionOption {
  id: string
  label: string
  description?: string
  response?: string
}

interface AssistantActionPayload {
  turnId: string
  content: string
}

// Stable function references (not inline arrows) so MessageView props keep
// their identity across parent re-renders — inline handlers would force every
// message to re-render on every stream tick.
function onToggleProcess(messageId: string): void {
  emit('toggle-process', messageId)
}

function onDecisionSelect(payload: { partId: string; option: DecisionOption; response: string }): void {
  emit('decision-select', payload)
}

function onForkMessage(payload: AssistantActionPayload): void {
  emit('fork-message', payload)
}

function onRollbackMessage(payload: AssistantActionPayload): void {
  emit('rollback-message', payload)
}
</script>

<style>
/* Message rendering styles are global (see MessageView.vue); this component
   keeps the historical style block so the chat-thread container chrome and
   the shared part styles keep their exact previous cascade. */
</style>
<style>
.chat-thread {
  width: min(var(--content-width), 100%);
  margin: 0 auto;
  display: grid;
  grid-auto-rows: max-content;
  align-content: start;
  gap: 16px;
  min-width: 0;
}

/* Skip layout/paint of off-screen messages: a huge thread (thousands of
   parts) otherwise forces an O(thread) layout on every stream tick. With
   content-visibility:auto the browser only lays out what is near the viewport,
   keeping per-tick layout cost O(viewport). contain-intrinsic-size gives the
   scrollbar an estimate (auto caches the last real size) so scrolling does not
   jump. */
.message-view {
  content-visibility: auto;
  contain-intrinsic-size: auto 220px;
  /* Isolate each message's layout/style invalidation so a streaming text
     change doesn't reflow/re-render sibling messages (viewport-wide repaint
     showed up as 200-300ms render tasks on large threads). */
  contain: layout style;
}

/* Per-part wrapper: v-memo cache key carrier. display:contents keeps the
   wrapper box-less so it never affects layout or CSS selectors. */
.part-wrap {
  display: contents;
}

/* ── System messages ── */
.chat-thread .system-row {
  display: flex;
  justify-content: center;
  padding: 8px 16px;
}
.system-bubble {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 16px;
  border-radius: var(--radius-lg);
  font-size: 13px;
  max-width: 640px;
  line-height: 1.45;
}
.system-bubble--info {
  background: color-mix(in srgb, var(--blue) 12%, transparent);
  color: var(--blue);
  border: 1px solid color-mix(in srgb, var(--blue) 25%, transparent);
}
.system-bubble--done {
  background: color-mix(in srgb, var(--green) 12%, transparent);
  color: var(--green);
  border: 1px solid color-mix(in srgb, var(--green) 25%, transparent);
}
.system-bubble--error {
  background: color-mix(in srgb, var(--red) 14%, transparent);
  color: var(--red);
  border: 1px solid color-mix(in srgb, var(--red) 30%, transparent);
}
.system-bubble--waiting {
  background: color-mix(in srgb, var(--orange) 12%, transparent);
  color: var(--orange);
  border: 1px solid color-mix(in srgb, var(--orange) 25%, transparent);
}
.system-icon {
  font-size: 14px;
  flex-shrink: 0;
}
.assistant-terminal-error {
  display: flex;
  gap: 8px;
  margin: 8px 0 4px;
  padding: 8px 10px;
  border-left: 2px solid color-mix(in srgb, var(--red) 72%, transparent);
  background: color-mix(in srgb, var(--red) 7%, transparent);
  color: color-mix(in srgb, var(--red) 78%, var(--theme-main-text, #fff) 22%);
  font-size: 12px;
  line-height: 1.5;
}
.assistant-terminal-error__label {
  flex: none;
  font-weight: 700;
}
.shallow-thinking-pending {
  display: inline-flex;
  align-items: baseline;
  min-width: 0;
  color: color-mix(in srgb, var(--green) 72%, var(--theme-main-text, #fff) 28%);
  font-size: 12px;
  font-weight: 650;
  line-height: 1.45;
}
.shallow-thinking-pending--process {
  margin-left: 22px;
}
.shallow-thinking-pending-row {
  padding: 1px 0 2px;
}
.reasoning-body--pending {
  margin-top: 0;
  margin-bottom: 4px;
  padding-bottom: 0;
}
.shallow-thinking-dots {
  display: inline-flex;
  width: 1.2em;
}
.shallow-thinking-dots span {
  animation: shallow-thinking-dot 1.2s ease-in-out infinite;
}
.shallow-thinking-dots span:nth-child(2) {
  animation-delay: .15s;
}
.shallow-thinking-dots span:nth-child(3) {
  animation-delay: .3s;
}

/* ── Process step color coding — marker 仅 error 时显示红点 ── */
.process-step--error .process-step-marker {
  background: var(--red, #e5484d);
  box-shadow: none;
}
@keyframes stream-spin { to { transform: rotate(360deg); } }
@keyframes process-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .4; }
}
@keyframes shallow-thinking-dot {
  0%, 70%, 100% { opacity: .28; }
  35% { opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .shallow-thinking-dots span {
    animation: none;
    opacity: 1;
  }
}

/* ── Part dot status colors — 以 main area 文字为底 ── */
.part-dot--completed { color: var(--theme-main-text, #fff); }
.part-dot--error { color: color-mix(in srgb, var(--theme-main-text, #fff) 30%, var(--red) 70%); }
.part-dot--running { color: var(--theme-main-text, #fff); }

/* ── Expandable tool cards ── */
.process-stream--history {
  align-items: stretch;
  counter-reset: reasoning-step;
}
.process-stream--live,
.process-stream--inline {
  counter-reset: reasoning-step;
}
.process-stream--history .process-step {
  max-width: 100%;
}
.chat-thread .process-stream--history .process-step--context,
.chat-thread .process-stream--history .process-step--tool {
  display: block !important;
  grid-template-columns: none !important;
}
.process-step--tool {
  display: block;
  width: 100%;
  min-width: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  padding: 0;
  box-shadow: none;
  overflow: visible;
}
.process-stream--history .process-step--tool + .process-step--tool {
  margin-top: 2px;
}
.process-stream--history .process-step--tool:has(.tool-card-header--command) + .process-step--tool,
.process-stream--history .process-step--tool + .process-step--tool:has(.tool-card-header--command) {
  margin-top: 8px;
}
.tool-card-header {
  position: relative;
  z-index: 0;
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  min-height: 28px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-areas:
    "marker title"
    ". args";
  align-items: center;
  column-gap: 6px;
  row-gap: 4px;
  border: none;
  background: none;
  color: inherit;
  cursor: default;
  padding: 1px 0 7px;
  font-size: inherit;
  text-align: left;
  overflow: hidden;
}
.tool-card-header .process-step-marker {
  grid-area: marker;
}
.tool-card-header .process-step-title {
  grid-area: title;
  min-width: 0;
}
.tool-card-header .process-step-title:empty {
  display: none;
}
.tool-card-header.has-detail {
  cursor: pointer;
}
.tool-card-header.has-detail:hover .process-step-title {
  color: color-mix(in srgb, var(--theme-main-text, #fff) 86%, transparent);
}
.process-tool-row {
  min-height: 32px;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: nowrap;
  gap: 8px;
  border-radius: 0;
  background: transparent;
  padding: 4px 6px;
  position: relative;
  transition: color 160ms ease-out;
}
.process-tool-row::before {
  content: ""; position: absolute; inset: 0;
  border-radius: 0; background: transparent; pointer-events: none;
  -webkit-mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
  mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
}
.process-tool-row .process-step-title {
  flex: 0 1 auto;
}
.process-tool-row.has-detail:hover::before {
  background: color-mix(in srgb, var(--theme-main-text, #fff) var(--alpha-hover), transparent);
}
.process-tool-row:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--blue) 72%, transparent);
  outline-offset: 1px;
}
.tool-row-summary {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  line-height: 1.4;
  font-weight: 400;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 72%, transparent);
}
.tool-row-args {
  display: none;
}
.tool-row-status {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent);
  font-size: 12px;
  line-height: 1.4;
  font-weight: 400;
  white-space: nowrap;
}
.tool-row-status--retry {
  color: var(--orange);
  cursor: pointer;
}

/* ── Model retry progress bar ── */
.model-retry-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 0;
}
.model-retry-bar__label {
  flex: 0 0 auto;
  font-size: 11px;
  font-weight: 550;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 44%, transparent);
  white-space: nowrap;
}
.model-retry-bar__track {
  flex: 0 1 auto;
  display: flex;
  gap: 1px;
  height: 4px;
  background: color-mix(in srgb, var(--theme-main-text, #fff) 6%, transparent);
  border-radius: 2px;
}
.model-retry-bar__segment {
  flex: 0 0 2px;
  height: 100%;
  background: transparent;
  border-radius: 0.5px;
  transition: background-color 0.2s ease;
}
.model-retry-bar__segment--filled {
  background: color-mix(in srgb, var(--theme-main-text, #fff) 26%, transparent);
}
.tool-card-header--command .process-step-title {
  grid-area: title;
  font-weight: 400;
}
.process-step--tool .process-step-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  line-height: 1.4;
  font-weight: 400;
  letter-spacing: 0;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 72%, transparent);
}
.tool-card-body {
  position: relative;
  z-index: 0;
  clear: both;
  margin-top: 8px;
  padding-left: 0;
  width: 100%;
  min-width: 0;
  overflow: auto;
  max-height: 800px;
  opacity: 1;
  transition: max-height 0.28s cubic-bezier(0.2, 0.8, 0.2, 1),
              opacity 0.22s ease,
              margin 0.28s cubic-bezier(0.2, 0.8, 0.2, 1),
              padding 0.28s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.tool-card-body--closed {
  max-height: 0;
  opacity: 0;
  margin-top: 0;
  margin-bottom: 0;
  padding-top: 0;
  padding-bottom: 0;
}
.tool-card-body--row {
  margin: 2px 0 10px 18px;
  width: calc(100% - 18px);
}
.tool-color--warn + .tool-card-body,
.tool-color--warn .tool-card-body {
  opacity: .82;
}
.process-inline-toggle {
  grid-column: 1 / -1;
  display: flex;
  align-items: baseline;
  gap: 8px;
  width: 100%;
  min-width: 0;
  border: 0;
  background: transparent;
  color: inherit;
  padding: 0;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.process-inline-toggle .process-step-title {
  flex: 0 0 auto;
}
.process-inline-toggle .process-step-detail {
  flex: 1 1 auto;
  min-width: 0;
}
.process-detail-panel {
  grid-column: 1 / -1;
  margin: 6px 0 8px 22px;
  position: relative;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 10%, transparent);
  border-radius: 6px;
  background: color-mix(in srgb, var(--bg) 34%, transparent);
}
.process-detail-panel--error {
  border-color: color-mix(in srgb, var(--red) 32%, transparent);
}
.process-detail-panel pre {
  margin: 0;
  max-height: 260px;
  overflow: auto;
  padding: 28px 10px 9px;
  color: var(--theme-main-text, var(--text));
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}
.process-detail-copy {
  position: absolute;
  top: 5px;
  right: 6px;
  min-height: 20px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 12%, transparent);
  border-radius: 4px;
  background: color-mix(in srgb, var(--theme-main-text, #fff) 6%, transparent);
  color: color-mix(in srgb, var(--theme-main-text, #fff) 70%, transparent);
  font-size: 11px;
  line-height: 1;
  cursor: pointer;
}
.process-step--error .process-step-detail {
  white-space: normal;
  overflow: visible;
  text-overflow: clip;
  word-break: break-word;
}
.process-step--context {
  display: block;
  width: 100%;
  min-width: 0;
}
.context-group-header {
  width: 100%;
  display: grid;
  grid-template-columns: auto minmax(0, max-content) minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
  border: none;
  background: none;
  color: inherit;
  padding: 0;
  font-size: inherit;
  cursor: pointer;
  text-align: left;
}
.context-group-header .process-step-detail {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.context-group-header:hover .process-step-title {
  text-decoration: underline;
  text-underline-offset: 2px;
}
.context-tool-list {
  display: grid;
  gap: 2px;
  margin-top: 6px;
  padding-left: 24px;
  min-width: 0;
}
.context-tool-row {
  min-width: 0;
  width: 100%;
  padding: 5px 0 7px;
  overflow: hidden;
}
.context-tool-head {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(84px, max-content) minmax(0, 1fr);
  align-items: center;
  gap: 8px;
}
.context-tool-head .tool-args-preview {
  display: none;
}
.context-tool-output {
  margin-top: 4px;
  max-height: 220px;
  overflow: auto;
}
.tool-output {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: var(--theme-main-soft-background, color-mix(in srgb, var(--theme-main-text, #fff) 5%, transparent));
  border: 1px solid var(--theme-main-border, color-mix(in srgb, var(--theme-main-text, #fff) 10%, transparent));
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
  color: var(--theme-main-text, var(--text));
  max-height: 320px;
  overflow: auto;
}
.tool-output-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  width: 100%;
  max-width: 100%;
  margin-bottom: 7px;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 62%, transparent);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.4;
}
.tool-output-meta span {
  min-width: 0;
  padding: 2px 7px;
  border: 1px solid var(--theme-main-border, color-mix(in srgb, var(--theme-main-text, #fff) 10%, transparent));
  border-radius: var(--radius-sm);
  background: var(--theme-main-subtle-background, color-mix(in srgb, var(--theme-main-text, #fff) 4%, transparent));
  white-space: normal;
  overflow-wrap: anywhere;
}
.tool-output-content {
  margin: 0;
  font: inherit;
  color: inherit;
  white-space: pre;
  word-break: normal;
  min-width: max-content;
  cursor: pointer;
}
.tool-output-content--wrap {
  white-space: pre-wrap;
  word-break: break-word;
  min-width: 0;
}
.tool-output--error {
  border-color: color-mix(in srgb, var(--red) 30%, transparent);
  background: color-mix(in srgb, var(--red) 6%, transparent);
  color: var(--red);
  cursor: pointer;
  user-select: all;
}
.tool-output--error:hover {
  background: color-mix(in srgb, var(--red) 10%, transparent);
}
.tool-card-body--row .tool-output,
.context-tool-output {
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}
.tool-card-body--row .tool-output-meta span,
.context-tool-output .tool-output-meta span {
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}
.tool-card-body--row .tool-output--error {
  background: transparent;
}

.process-step--model-text {
  width: 100%;
  min-width: 0;
  display: grid;
  gap: 6px;
  padding: 2px 0 8px;
}

.process-text-head {
  min-width: 0;
  display: inline-grid;
  grid-template-columns: max-content minmax(0, max-content);
  align-items: center;
  gap: 7px;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 62%, transparent);
  font-size: 12px;
  line-height: 1.35;
  font-weight: 680;
}

.process-text-content {
  display: block;
  min-width: 0;
  margin-left: 20px;
  max-width: 76ch;
  color: var(--theme-main-text, var(--text));
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.checklist-card {
  min-width: 0;
  display: grid;
  gap: 8px;
  padding: 10px 11px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 10%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-text, #fff) 4%, transparent);
}

.decision-card {
  --decision-attention: color-mix(in srgb, #b49a60 72%, var(--theme-main-text, #fff) 28%);
  min-width: 0;
  display: grid;
  gap: 9px;
  padding: 7px 0 9px 14px;
  border-left: 2px solid color-mix(in srgb, var(--theme-main-text, #fff) 18%, transparent);
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.decision-card-head,
.checklist-card-head {
  min-width: 0;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.decision-card-title {
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--theme-main-text, var(--text));
  font-size: 13px;
  font-weight: 600;
  line-height: 1.35;
}

.decision-card-status {
  color: color-mix(in srgb, var(--theme-main-text, #fff) 62%, transparent);
  font-size: 11px;
  font-weight: 600;
  line-height: 1.35;
  white-space: nowrap;
}

.decision-card--pending {
  border-left-color: var(--decision-attention);
}

.decision-card-detail {
  margin: 0;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.decision-options {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0;
  padding-top: 4px;
  border-top: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 9%, transparent);
}

.decision-option-group {
  width: 100%;
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(76px, max-content) minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 8%, transparent);
}

.decision-option-group:last-child {
  border-bottom: 0;
}

.decision-option {
  min-width: 76px;
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--theme-main-text, var(--text));
  padding: 7px 2px;
  cursor: pointer;
  text-align: left;
  transition: color 160ms ease;
  position: relative;
}
.decision-option::before {
  content: ""; position: absolute; inset: 0;
  border-radius: 0; background: transparent; pointer-events: none;
  -webkit-mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
  mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
}

.decision-option:hover::before {
  background: color-mix(in srgb, var(--theme-main-text, #fff) var(--alpha-hover), transparent);
}
.decision-option:hover {
  color: color-mix(in srgb, var(--theme-main-text, #fff) 78%, var(--decision-attention) 22%);
}

.decision-option:focus-visible,
.decision-guide-toggle:focus-visible,
.decision-guide-submit:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--blue) 78%, transparent);
  outline-offset: 2px;
}

.decision-option--approve {
  color: color-mix(in srgb, var(--green) 82%, var(--theme-main-text, #fff) 18%);
}

.decision-option--approve:hover::before {
  background: color-mix(in srgb, var(--green) var(--alpha-hover), transparent);
}
.decision-option--approve:hover {
  color: color-mix(in srgb, var(--green) 94%, var(--theme-main-text, #fff) 6%);
}

.decision-option--deny {
  background: transparent;
  color: color-mix(in srgb, var(--red) 82%, var(--theme-main-text, #fff) 18%);
}

.decision-option--deny:hover::before {
  background: color-mix(in srgb, var(--red) var(--alpha-hover), transparent);
}
.decision-option--deny:hover {
  color: color-mix(in srgb, var(--red) 94%, var(--theme-main-text, #fff) 6%);
}

.decision-option-label {
  font-size: 12px;
  font-weight: 600;
  line-height: 1.35;
}

.decision-option-desc {
  min-width: 0;
  max-width: none;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent);
  font-size: 11px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.decision-card-decision {
  margin: 0;
  color: color-mix(in srgb, var(--green) 76%, var(--theme-main-text, #fff) 24%);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.decision-guide {
  padding-top: 1px;
}

.decision-guide-toggle {
  width: max-content;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 64%, transparent);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.45;
  cursor: pointer;
}

.decision-guide-toggle:hover {
  color: var(--theme-main-text, var(--text));
}

.decision-guide-fields {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 7px;
  align-items: end;
  margin-top: 8px;
}

.decision-guide-input {
  min-width: 0;
  width: 100%;
  resize: none;
  border: 1px solid color-mix(in srgb, var(--theme-control-text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-control-background) 70%, transparent);
  color: var(--theme-control-text);
  padding: var(--space-2);
  font: inherit;
  font-size: 12px;
  line-height: 1.45;
}

.decision-guide-input:focus {
  outline: none;
}

.decision-guide-submit {
  border: 1px solid color-mix(in srgb, var(--blue) 38%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--blue) 12%, transparent);
  color: var(--theme-main-text, var(--text));
  padding: 7px 9px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.45;
  white-space: nowrap;
  cursor: pointer;
}

.decision-guide-submit:disabled {
  cursor: not-allowed;
  opacity: .45;
}

.sub-line-block {
  position: relative;
  min-width: 0;
  display: grid;
  gap: 8px;
  margin-left: 4px;
  padding-left: 22px;
}

.sub-line-block::before {
  content: "";
  position: absolute;
  left: 6px;
  top: 4px;
  bottom: 4px;
  width: 1px;
  background: color-mix(in srgb, var(--theme-main-text, #fff) 16%, transparent);
}

/* ── Compact process group summary ── */
.process-group-summary {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  width: 100%;
  padding: 4px 0;
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  text-align: inherit;
  cursor: pointer;
  border-radius: 0;
  opacity: 0.8;
  position: relative;
}
.process-group-summary::before {
  content: ""; position: absolute; inset: 0;
  border-radius: 0; background: transparent; pointer-events: none;
  -webkit-mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
  mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
}
.process-group-summary:hover {
  opacity: 1;
}
.process-group-summary:hover::before {
  background: color-mix(in srgb, var(--theme-main-text, #fff) var(--alpha-hover), transparent);
}
.process-group-text {
  min-width: 0;
  font-size: 12px;
  line-height: 1.4;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 72%, transparent);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 运行中：分组摘要收缩到文字宽度，流光扫过范围=文字区域 */
.process-group-summary--running .process-group-text {
  justify-self: start;
}
.process-group-body {
  padding: 4px 0 4px 12px;
  border-left: 2px solid color-mix(in srgb, var(--theme-main-text, #fff) 10%, transparent);
}

.sub-line-heading {
  min-width: 0;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  width: 100%;
  padding: 4px 0;
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  text-align: inherit;
  cursor: pointer;
  border-radius: 0;
  position: relative;
}
.sub-line-heading::before {
  content: ""; position: absolute; inset: 0;
  border-radius: 0; background: transparent; pointer-events: none;
  -webkit-mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
  mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
}
.sub-line-heading:hover::before {
  background: color-mix(in srgb, var(--theme-main-text, #fff) var(--alpha-hover), transparent);
}

.sub-line-title {
  display: inline-block;
  justify-self: start;
  max-width: 100%;
  min-width: 0;
  color: var(--theme-main-text, var(--text));
  font-size: 13px;
  font-weight: 600;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

/* 运行态标题流光（工具行 / sub-agent 行通用）：
   v-beam 指令给标题加 beam-host 并注入 beam-sweep 光束元素，
   JS rAF 驱动 transform；只有 running 状态下光束才显示。
   光束 = 聊天区背景主题变量（--theme-main-background），
   mask 做左右渐隐 → 完全随主题联动；扫过时标题被背景色短暂覆盖，
   范围被 overflow:hidden 限制在标题区域。 */
.beam-host {
  position: relative;
  overflow: hidden;
}
.beam-sweep {
  display: none;
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 36%;
  min-width: 40px;
  background: var(--theme-main-background, #111111);
  -webkit-mask-image: linear-gradient(to right, transparent, #000 32%, #000 68%, transparent);
  mask-image: linear-gradient(to right, transparent, #000 32%, #000 68%, transparent);
  pointer-events: none;
  will-change: transform;
  z-index: 1;
}
.process-step--running .process-step-title .beam-sweep,
.sub-line--running .sub-line-title .beam-sweep,
.process-group-summary--running .process-group-text .beam-sweep {
  display: block;
}

.sub-line-status {
  color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent);
  font-size: 11px;
  line-height: 1.35;
  white-space: nowrap;
}

.sub-line-delivery-meta {
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-left: 18px;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 58%, transparent);
  font-size: 11px;
  line-height: 1.35;
}

.sub-line-delivery-meta span {
  padding: 2px 6px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-text, #fff) 5%, transparent);
}

.sub-line-body {
  display: grid;
  gap: 8px;
}

.sub-line-block .user-row {
  padding: 1px 0 4px;
}

.sub-line-block .user-bubble {
  max-width: min(76%, 520px);
  border-radius: var(--radius);
  border-bottom-right-radius: 6px;
  padding: 7px 10px;
  font-size: 12px;
  line-height: 1.5;
}

.sub-line-block .assistant-answer {
  margin-top: 4px;
}

.sub-line-block .assistant-answer,
.sub-line-block .part-text-content {
  font-size: 12px;
  line-height: 1.55;
}

.sub-line-block .process-step {
  font-size: 11px;
  line-height: 1.42;
}

.sub-line-block .process-step--tool {
  border-radius: 0;
  padding: 0;
}

.sub-line-block .tool-card-header {
  grid-template-columns: auto minmax(0, 1fr);
  column-gap: 5px;
  row-gap: 3px;
}

.sub-line-block .tool-card-body {
  margin-top: 6px;
}

.sub-line-block .tool-output {
  padding: 7px 9px;
  font-size: 11px;
  line-height: 1.45;
  max-height: 260px;
}

.sub-line-block .tool-output-meta {
  font-size: 10px;
}

.sub-line-block .tool-output-meta span {
  padding: 1px 5px;
}

.sub-line-block .tool-args-preview,
.sub-line-block .diff-header,
.sub-line-block .diff-file,
.sub-line-block .diff-line-num {
  font-size: 10px;
}

.sub-line-block .tool-args-preview {
  margin-left: 0;
}

.sub-line-block .diff-lines {
  font-size: 11px;
  line-height: 1.5;
}

.sub-line-block .diff-line {
  grid-template-columns: 30px minmax(0, 1fr);
  min-height: 18px;
}

.sub-line-block .diff-line-num {
  width: 30px;
  padding: 0 5px 0 7px;
}

.sub-line-block .diff-line-content {
  padding: 0 8px 0 7px;
}

.sub-line-block .reasoning-toggle {
  min-height: 24px;
  gap: 6px;
}

.sub-line-block .process-step--reasoning .process-step-title {
  font-size: 11px;
}

.sub-line-block .reasoning-duration {
  font-size: 10px;
}

.sub-line-block .reasoning-body {
  margin: 2px 0 6px 20px;
  max-height: none;
  overflow: visible;
  font-size: 12px;
  line-height: 1.55;
}

.checklist-card {
  border-color: color-mix(in srgb, var(--blue) 18%, transparent);
  background: color-mix(in srgb, var(--theme-main-text, #fff) 3%, transparent);
}

.checklist-card-head .process-step-title {
  font-size: 13px;
  font-weight: 600;
}

.checklist-items {
  display: grid;
  gap: 7px;
  margin: 0;
  padding: 0;
  list-style: none;
  counter-reset: checklist-item;
}

.checklist-item {
  min-width: 0;
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  counter-increment: checklist-item;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 72%, transparent);
  font-size: 12px;
  line-height: 1.45;
}

.checklist-item::before {
  content: counter(checklist-item) ".";
  color: color-mix(in srgb, var(--theme-main-text, #fff) 44%, transparent);
  font-variant-numeric: tabular-nums;
}

.checklist-box {
  grid-column: 2;
  width: 14px;
  height: 14px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 28%, transparent);
  border-radius: 3px;
  display: inline-grid;
  place-items: center;
  color: var(--green);
  font-size: 11px;
  line-height: 1;
}

.checklist-text {
  grid-column: 3;
  min-width: 0;
  overflow-wrap: anywhere;
}

.checklist-item--completed .checklist-text {
  color: color-mix(in srgb, var(--theme-main-text, #fff) 48%, transparent);
  text-decoration: line-through;
  text-decoration-thickness: 1px;
}

.test-result-card {
  min-width: 0;
  display: grid;
  gap: 7px;
  margin: 2px 0;
  padding: 0;
}
.test-result-head {
  min-width: 0;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 8px;
}
.test-result-state {
  font-size: 12px;
  font-weight: 700;
  color: var(--theme-main-text, var(--text));
}
.test-result-card--passed .test-result-state {
  color: var(--green);
}
.test-result-card--failed .test-result-state {
  color: var(--red);
}
.test-result-command {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent);
  font-family: var(--font-mono);
  font-size: 11px;
}
.test-result-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.test-result-meta span {
  padding: 0;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent);
  font-family: var(--font-mono);
  font-size: 11px;
}
.test-result-meta span + span::before {
  content: "·";
  margin-right: 6px;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 32%, transparent);
}
.test-result-output {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  padding: 3px 0 0;
  color: var(--theme-main-text, var(--text));
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ── Reasoning collapsible panel ── */
.process-step--reasoning {
  display: block;
  width: 100%;
  min-width: 0;
  padding: 2px 0;
  counter-increment: reasoning-step;
}
.process-step--reasoning + .process-step--reasoning {
  margin-top: 3px;
}
.reasoning-toggle {
  width: 100%;
  min-width: 0;
  min-height: 28px;
  display: grid;
  grid-template-columns: max-content minmax(0, max-content) auto;
  align-items: center;
  gap: 8px;
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 2px 6px 2px 0;
  cursor: pointer;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 74%, transparent);
  font: inherit;
  text-align: left;
  transition: color .14s ease;
  position: relative;
}
.reasoning-toggle::before {
  content: ""; position: absolute; inset: 0;
  border-radius: 0; background: transparent; pointer-events: none;
  -webkit-mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
  mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
}
.reasoning-toggle:hover {
  color: color-mix(in srgb, var(--theme-main-text, #fff) 88%, transparent);
}
.reasoning-toggle:hover::before {
  background: color-mix(in srgb, var(--theme-main-text, #fff) var(--alpha-hover), transparent);
}
.process-step--reasoning .process-step-marker {
  display: none;
}
.process-step--reasoning .process-step-title {
  color: color-mix(in srgb, var(--theme-main-text, #fff) 66%, transparent);
  font-size: 12px;
  font-weight: 680;
}
.reasoning-duration {
  min-width: 0;
  max-width: min(240px, 40vw);
  justify-self: start;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 60%, transparent);
  font-style: normal;
}
.reasoning-body {
  margin: 3px 0 8px 24px;
  max-height: 800px;
  overflow: auto;
  padding: 2px 0 6px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 62%, transparent);
  font-size: 13px;
  line-height: 1.65;
  font-style: normal;
  text-wrap: pretty;
  opacity: 1;
  transition: max-height 0.28s cubic-bezier(0.2, 0.8, 0.2, 1),
              opacity 0.22s ease,
              margin 0.28s cubic-bezier(0.2, 0.8, 0.2, 1),
              padding 0.28s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.reasoning-body--closed {
  max-height: 0;
  opacity: 0;
  margin-top: 0;
  margin-bottom: 0;
  padding-top: 0;
  padding-bottom: 0;
}
.reasoning-body .process-step-detail {
  display: block;
  overflow: visible;
  color: inherit;
  white-space: pre-wrap;
  word-break: break-word;
  -webkit-line-clamp: unset;
}

.compaction-step {
  display: block;
  width: 100%;
  min-width: 0;
  padding: 2px 0;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 62%, transparent);
}
.compaction-toggle {
  display: grid;
  grid-template-columns: 12px minmax(0, max-content) minmax(0, 1fr) minmax(12px, max-content);
  align-items: center;
  column-gap: 6px;
  width: 100%;
  min-width: 0;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  color: inherit;
  font: inherit;
  text-align: left;
  position: relative;
}
.compaction-toggle::before {
  content: ""; position: absolute; inset: 0;
  border-radius: 0; background: transparent; pointer-events: none;
  -webkit-mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
  mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
}
.compaction-toggle:disabled {
  cursor: default;
}
.compaction-toggle:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--accent, #79bcff) 72%, transparent);
  outline-offset: 3px;
  border-radius: 4px;
}
.compaction-toggle .process-step-title {
  min-width: 0;
  white-space: nowrap;
}
.compaction-toggle .process-step-detail {
  min-width: 0;
  overflow-wrap: anywhere;
}
.compaction-toggle:hover::before {
  background: color-mix(in srgb, var(--theme-main-text, #fff) var(--alpha-hover), transparent);
}
.compaction-toggle:hover .process-step-title {
  color: var(--accent, #79bcff);
}
.compaction-toggle:disabled:hover .process-step-title {
  color: inherit;
}
/* compaction-step marker — 与 conversation status 同规范 */
.compaction-step--running .process-step-marker {
  width: 9px; height: 9px;
  margin: 4px auto 0;
  border: 2px solid color-mix(in srgb, var(--theme-main-text, #fff) 14%, transparent);
  border-top-color: var(--theme-main-text, #fff);
  background: transparent;
  border-radius: 50%;
  animation: stream-spin .9s linear infinite;
}
.compaction-step--compacted .process-step-marker {
  background: var(--theme-main-text, #fff);
}
.compaction-step--not_needed .process-step-marker {
  background: color-mix(in srgb, var(--theme-main-text, #fff) 34%, transparent);
}
.compaction-step--failed .process-step-marker {
  background: color-mix(in srgb, var(--theme-main-text, #fff) 30%, var(--red) 70%);
}
.compaction-summary {
  box-sizing: border-box;
  width: min(100%, 720px);
  margin: 6px 0 0 18px;
  padding: 2px 0 6px;
  border: 0;
  background: transparent;
}
.compaction-summary-text {
  margin: 0;
  max-height: 320px;
  overflow: auto;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 72%, transparent);
  font-family: inherit;
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
.compaction-summary-text--streaming::after {
  content: "";
  display: inline-block;
  width: 1px;
  height: 1em;
  margin-left: 3px;
  transform: translateY(2px);
  background: currentColor;
  opacity: .58;
  animation: stream-caret 900ms steps(2, start) infinite;
}
@media (prefers-reduced-motion: reduce) {
  .compaction-step--running .process-step-marker,
  .compaction-summary-text--streaming::after {
    animation: none;
  }
}

/* ── Tool args preview ── */
.tool-args-preview {
  grid-area: args;
  min-width: 0;
  font-size: 12px;
  line-height: 1.4;
  font-weight: 400;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent);
  max-width: min(100%, 760px);
  overflow-wrap: anywhere;
  white-space: normal;
  justify-self: start;
}

/* ── Diff-style file blocks ── */
.diff-block {
  min-width: 0;
  width: 100%;
  max-width: 100%;
  margin: 0;
  color: var(--theme-main-text, var(--text));
  max-height: 400px;
  overflow: auto;
}
.diff-header {
  min-width: 0;
  min-height: 29px;
  box-sizing: border-box;
  padding: 5px 0;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  border-bottom: 1px solid var(--theme-main-border, color-mix(in srgb, var(--theme-main-text, #fff) 10%, transparent));
  display: flex;
  align-items: center;
  gap: 8px;
  position: sticky;
  top: 0;
  z-index: 2;
}
.wrap-toggle {
  flex: 0 0 auto;
  margin-left: auto;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 68%, transparent);
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 1.2;
  padding: 2px 0 2px 6px;
  cursor: pointer;
}
.wrap-toggle:hover {
  color: var(--theme-main-text, var(--text));
  text-decoration: underline;
  text-underline-offset: 2px;
}
.diff-block--read .diff-header {
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 78%, transparent);
}
.diff-block--write .diff-header {
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 78%, transparent);
}
.diff-file {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
  font-size: 11px;
}
.diff-lines {
  min-width: max-content;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
  min-width: 100%;
}
.diff-block:not(.diff-block--wrap) .diff-lines {
  min-width: max-content;
}
.diff-block--wrap .diff-lines {
  min-width: 0;
}
.diff-line {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  min-height: 20px;
}
.diff-line:nth-child(even) {
  background: var(--theme-main-subtle-background, color-mix(in srgb, var(--theme-main-text, #fff) 2%, transparent));
}
.diff-line-num {
  width: 34px;
  padding: 0 6px 0 10px;
  text-align: right;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 38%, transparent);
  font-size: 11px;
  user-select: none;
  border-right: 1px solid var(--theme-main-border, color-mix(in srgb, var(--theme-main-text, #fff) 9%, transparent));
  background: var(--theme-main-subtle-background, color-mix(in srgb, var(--theme-main-text, #fff) 3%, transparent));
}
.diff-line-content {
  white-space: pre;
  word-break: normal;
  color: var(--theme-main-text, var(--text));
  padding: 0 10px 0 8px;
  min-width: 0;
}
.diff-block--wrap .diff-line-content {
  white-space: pre-wrap;
  word-break: break-word;
}
/* Diff line markers — follows Claude Code unified diff style */
.diff-line--add {
  background: color-mix(in srgb, var(--green) 7%, var(--theme-main-subtle-background, transparent));
}
.diff-line--add .diff-line-content {
  color: color-mix(in srgb, var(--green) 72%, var(--theme-main-text, #fff) 28%);
}
.diff-line--add .diff-line-num {
  color: color-mix(in srgb, var(--green) 76%, var(--theme-main-text, #fff) 24%);
  font-weight: 700;
}
.diff-line--del {
  background: color-mix(in srgb, var(--red) 7%, var(--theme-main-subtle-background, transparent));
}
.diff-line--del .diff-line-content {
  color: color-mix(in srgb, var(--red) 74%, var(--theme-main-text, #fff) 26%);
}
.diff-line--del .diff-line-num {
  color: color-mix(in srgb, var(--red) 78%, var(--theme-main-text, #fff) 22%);
  font-weight: 700;
}
.diff-line--meta {
  background: color-mix(in srgb, var(--blue) 5%, var(--theme-main-subtle-background, transparent));
}
.diff-line--meta .diff-line-content {
  color: color-mix(in srgb, var(--theme-main-text, #fff) 60%, transparent);
}
@media (max-width: 720px) {
  .process-tool-row {
    gap: 6px;
    padding-inline: 2px;
  }
  .tool-card-body--row {
    margin-left: 10px;
    width: calc(100% - 10px);
  }
  .context-tool-list {
    padding-left: 14px;
  }
  .context-tool-head {
    grid-template-columns: minmax(72px, max-content) minmax(0, 1fr);
  }
}
@media (prefers-reduced-motion: reduce) {
  .process-tool-row,
  .tool-card-body--row {
    animation: none;
    transition: none;
  }
  .reasoning-body,
  .tool-card-body {
    transition: none !important;
  }
}

/* ── Assistant reply hover actions ── */
.assistant-actions {
  display: flex;
  gap: 2px;
  padding: 4px 0 0;
  opacity: 0;
  pointer-events: none;
  transition: opacity 150ms ease-out;
}
.assistant-message:hover .assistant-actions,
.assistant-message:focus-within .assistant-actions {
  opacity: 1;
  pointer-events: auto;
}
.assistant-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 20px;
  border: 0;
  border-radius: var(--radius-sm);
  padding: 0;
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 46%, transparent);
  cursor: pointer;
  transition: background-color 150ms ease-out, color 150ms ease-out;
}
.assistant-action:hover,
.assistant-action:focus-visible {
  background: color-mix(in srgb, var(--theme-main-text, #fff) 9%, transparent);
  color: var(--theme-main-text, #fff);
}
.assistant-action:focus-visible {
  outline: 2px solid var(--blue, #79bcff);
  outline-offset: 1px;
}
.assistant-action svg {
  width: 15px;
  height: 15px;
}
.assistant-action--copied {
  color: var(--green, #32d17d);
}
@media (prefers-reduced-motion: reduce) {
  .assistant-actions,
  .assistant-action {
    transition: none;
  }
}
</style>

