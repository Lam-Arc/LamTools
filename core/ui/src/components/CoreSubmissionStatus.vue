<script setup lang="ts">
import { t } from '@/i18n/index.ts'
import type { CoreComposerSubmission } from '@/composables/useCoreLiveComposerController.ts'

// user:“做吧”+(每条提交独立显示准备、发送、确认和错误；恢复入口不覆盖新草稿)。
defineProps<{ submissions: CoreComposerSubmission[]; canEdit: boolean; busy?: boolean }>()
const emit = defineEmits<{ retry: [id: string]; edit: [id: string]; dismiss: [id: string] }>()
const labels: Record<CoreComposerSubmission['state'], string> = {
  preparing: '正在准备', sending: '正在发送', accepted: '已接收',
  queued: '已加入待发送', guided: '引导已接收', failed: '发送失败', unknown: '接收结果待确认',
}
</script>

<template>
  <div v-for="submission in submissions" :key="submission.id" class="submission-status"
    :data-submission-id="submission.id" :data-state="submission.state">
    <div class="submission-status__body">{{ submission.text }}</div>
    <ul v-if="submission.attachments.length" class="submission-status__files" :aria-label="t('附件')">
      <li v-for="(file, index) in submission.attachments" :key="index">
        {{ file.type === 'attachment' ? file.filename || t('附件') : file.type === 'text' ? file.text : file.name }}
      </li>
    </ul>
    <div class="submission-status__footer" role="status" aria-live="polite">
      <span>{{ t(submission.intent === 'resume' && submission.state === 'failed' ? '继续未完成' : labels[submission.state]) }}</span>
      <span v-if="submission.error" class="submission-status__error">{{ submission.error }}</span>
      <template v-if="submission.state === 'failed' || submission.state === 'unknown'">
        <button type="button" class="text-btn" :disabled="busy" :data-submission-retry="submission.id" @click="emit('retry', submission.id)">
          {{ submission.state === 'unknown' ? t('确认接收结果') : t('重试') }}
        </button>
        <button v-if="submission.state === 'failed' && canEdit && submission.intent !== 'resume'" type="button" class="text-btn"
          :disabled="busy" :data-submission-edit="submission.id" @click="emit('edit', submission.id)">{{ t('重新编辑') }}</button>
      </template>
      <button v-if="['accepted', 'queued', 'guided'].includes(submission.state)" type="button" class="text-btn"
        :aria-label="t('收起发送状态')" @click="emit('dismiss', submission.id)">{{ t('收起') }}</button>
    </div>
  </div>
</template>

<style scoped>
.submission-status {
  margin: var(--space-3) 0;
  padding: var(--space-3);
  border-radius: var(--radius);
  background: var(--theme-main-soft-background);
  color: var(--theme-main-text);
  overflow-wrap: anywhere;
}
.submission-status__body { white-space: pre-wrap; max-height: 12rem; overflow: auto; }
.submission-status__files { margin: var(--space-2) 0 0; padding-left: var(--space-4); }
.submission-status__footer { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: baseline; margin-top: var(--space-2); font-size: 12px; }
.submission-status__error { color: var(--red); }
.submission-status__footer .text-btn { color: var(--theme-main-text); }
</style>
