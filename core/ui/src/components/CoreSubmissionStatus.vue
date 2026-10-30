<script setup lang="ts">
import { computed } from 'vue'
import { CircleAlert, CircleHelp, LoaderCircle } from 'lucide-vue-next'
import { t } from '@/i18n/index.ts'
import type { CoreComposerSubmission } from '@/composables/useCoreLiveComposerController.ts'

// user:“这个东西它太丑了，它不太协调”+(发送状态收成输入栏上方的一行低透玻璃胶囊，
// 不再把整段正文铺成聊天区里的大块卡片)。
// user:“你悬浮的胶囊应该在它的上方，它不存在时在输入栏的上方”+(胶囊与目标/排队托盘
// 共用同一个固定在输入栏上沿的挂载点，本组件只负责胶囊本身的高度)。
const props = defineProps<{ submissions: CoreComposerSubmission[]; canEdit: boolean; busy?: boolean }>()
const emit = defineEmits<{ retry: [id: string]; edit: [id: string]; dismiss: [id: string] }>()

// 只显示仍在进行或需要用户处理的提交：已接收/已排队/引导已接收会由聊天消息
// 或下方目标与排队托盘承接，再画一次只会在界面上闪一下。
const visibleStates = new Set<CoreComposerSubmission['state']>(['preparing', 'sending', 'failed', 'unknown'])
const rows = computed(() => props.submissions?.filter(submission => visibleStates.has(submission.state)) ?? [])
const labels: Partial<Record<CoreComposerSubmission['state'], string>> = {
  preparing: '正在准备', sending: '正在发送', failed: '发送失败', unknown: '接收结果待确认',
}
function isActive(state: CoreComposerSubmission['state']): boolean {
  return state === 'preparing' || state === 'sending'
}
function oneLine(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}
function filesLabel(count: number): string {
  return `${count} 个附件`
}
</script>

<template>
  <!-- user:“这个胶囊淡入淡出”+(状态行的出现、消失和重排都走同一条淡入淡出过渡)。
       group 常驻但空着时不占高度，否则 v-if 拆掉整组会让淡出动画来不及播放。 -->
  <TransitionGroup
    tag="div"
    name="submission-status"
    appear
    class="submission-status-stack"
  >
    <div
      v-for="submission in rows"
      :key="submission.id"
      class="submission-status optical-glass optical-glass--low-trans"
      :data-submission-id="submission.id"
      :data-state="submission.state"
      role="status"
      aria-live="polite"
    >
      <span class="submission-status__icon" :class="{ 'is-spinning': isActive(submission.state) }" aria-hidden="true">
        <LoaderCircle v-if="isActive(submission.state)" :size="14" :stroke-width="1.8" />
        <CircleAlert v-else-if="submission.state === 'failed'" :size="14" :stroke-width="1.9" />
        <CircleHelp v-else :size="14" :stroke-width="1.9" />
      </span>
      <span class="submission-status__label">{{ t(labels[submission.state] || '') }}</span>
      <span v-if="submission.error" class="submission-status__error" :title="submission.error">{{ submission.error }}</span>
      <span v-else-if="oneLine(submission.text)" class="submission-status__preview" :title="oneLine(submission.text)">{{ oneLine(submission.text) }}</span>
      <span v-if="submission.attachments.length" class="submission-status__meta">{{ filesLabel(submission.attachments.length) }}</span>
      <span v-if="submission.state === 'failed' || submission.state === 'unknown'" class="submission-status__actions">
        <button
          type="button"
          class="btn btn--ghost submission-status__action"
          :disabled="busy"
          :data-submission-retry="submission.id"
          @click="emit('retry', submission.id)"
        >
          {{ submission.state === 'unknown' ? t('确认接收结果') : t('重试') }}
        </button>
        <button
          v-if="submission.state === 'failed' && canEdit && submission.intent !== 'resume'"
          type="button"
          class="btn btn--ghost submission-status__action"
          :disabled="busy"
          :data-submission-edit="submission.id"
          @click="emit('edit', submission.id)"
        >{{ t('重新编辑') }}</button>
      </span>
    </div>
  </TransitionGroup>
</template>

<style scoped>
/* ===== 输入栏上方的发送状态胶囊 =====
   挂在输入栏上沿的共享位置上：有目标/排队托盘时在托盘上方，没有时贴着输入栏。
   一个状态一行，正文只做单行预览，不再复述整条消息。 */
.submission-status-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  pointer-events: none;
}

/* 有状态行时才和托盘/输入栏留出间距；空组不占高度。 */
.submission-status-stack:has(> .submission-status) {
  margin-bottom: var(--space-2);
}

.submission-status {
  --text: var(--theme-composer-text);
  --optical-glass-surface: var(--theme-composer-background);
  --optical-glass-overlay: transparent;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 0 1 auto;
  width: fit-content;
  /* user:“长消息是自动省略后面的内容啊，不要让它被挤得太长，或者挤出第二行，用…”
     +(胶囊自身限宽，正文超出一律收成一行省略号，不换行也不撑满输入栏)。 */
  max-width: min(100%, 34rem);
  min-height: 32px;
  padding: 3px var(--space-2) 3px var(--space-3);
  border-radius: 999px;
  color: var(--text);
  font-size: 12px;
  line-height: 1.35;
  pointer-events: auto;
}

.submission-status__icon {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  color: color-mix(in srgb, var(--text) 65%, transparent);
}

.submission-status__icon.is-spinning svg {
  animation: submission-status-spin 0.9s linear infinite;
}

.submission-status[data-state='failed'] .submission-status__icon {
  color: color-mix(in srgb, var(--red) 70%, var(--text) 30%);
}

.submission-status[data-state='unknown'] .submission-status__icon {
  color: color-mix(in srgb, var(--orange) 70%, var(--text) 30%);
}

.submission-status__label {
  flex: 0 0 auto;
  font-weight: 560;
}

.submission-status__preview {
  min-width: 0;
  flex: 0 1 auto;
  overflow: hidden;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.submission-status__error {
  min-width: 0;
  flex: 0 1 auto;
  overflow: hidden;
  color: color-mix(in srgb, var(--red) 78%, var(--text) 22%);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.submission-status__meta {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--text) 45%, transparent);
  white-space: nowrap;
}

.submission-status__actions {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--space-1);
}

.submission-status__action.btn--ghost {
  min-height: 24px;
  padding: 0 var(--space-1);
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 12px;
}

.submission-status__action.btn--ghost:hover:not(:disabled) {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.submission-status__action.btn--ghost:active:not(:disabled) {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

/* 淡入淡出：出现时从下方轻轻浮起，消失时只收透明度。 */
.submission-status-enter-active,
.submission-status-leave-active,
.submission-status-move {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.submission-status-enter-from,
.submission-status-leave-to {
  opacity: 0;
  transform: translateY(4px) scale(0.98);
}

@keyframes submission-status-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .submission-status-enter-active,
  .submission-status-leave-active,
  .submission-status-move {
    transition: opacity 0.18s ease;
  }

  .submission-status-enter-from,
  .submission-status-leave-to {
    transform: none;
  }

  .submission-status__icon.is-spinning svg {
    animation: none;
  }
}
</style>
