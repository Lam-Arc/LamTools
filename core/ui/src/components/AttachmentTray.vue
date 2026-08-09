<template>
  <div v-if="attachments.length" class="attachment-tray" aria-label="附件">
    <div
      v-for="item in attachments"
      :key="item.id"
      class="attachment-row"
      :class="{ 'attachment-row--failed': item.status === 'failed' }"
    >
      <button
        type="button"
        class="attachment-main"
        :disabled="item.status === 'failed'"
        :data-attachment-preview="item.id"
        @click="$emit('preview', item.id)"
      >
        <span class="attachment-kind">{{ kindLabel(item) }}</span>
        <span class="attachment-name">{{ item.label || item.filename }}</span>
        <span class="attachment-meta">{{ formatSize(item.size) }}</span>
      </button>
      <span v-if="item.status === 'failed'" class="attachment-error">{{ item.error || '上传失败' }}</span>
      <button
        v-if="item.status === 'failed'"
        type="button"
        class="attachment-action"
        :data-attachment-retry="item.id"
        @click="$emit('retry', item.id)"
      >
        重试
      </button>
      <button
        v-else
        type="button"
        class="attachment-action"
        :data-attachment-open="item.id"
        @click="$emit('open', item.id)"
      >
        本机打开
      </button>
      <button
        type="button"
        class="attachment-remove"
        :data-attachment-remove="item.id"
        :aria-label="`移除 ${item.label || item.filename}`"
        @click="$emit('remove', item.id)"
      >
        ×
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { CoreAttachment } from '../types';

defineProps<{
  attachments: CoreAttachment[];
}>();

defineEmits<{
  remove: [id: string];
  retry: [id: string];
  preview: [id: string];
  open: [id: string];
}>();

function kindLabel(item: CoreAttachment): string {
  if (item.status === 'failed') return 'FAIL';
  const previewType = String(item.preview_type || '').toLowerCase();
  if (previewType === 'image') return 'IMG';
  if (previewType === 'pdf') return 'PDF';
  if (previewType === 'text') return 'TXT';
  return 'FILE';
}

function formatSize(size: number): string {
  if (!Number.isFinite(size) || size <= 0) return '';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}
</script>

<style scoped>
.attachment-tray {
  display: grid;
  gap: 6px;
  padding: 9px 12px 0;
}

.attachment-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 6px;
  align-items: center;
  min-height: 32px;
  border: 1px solid color-mix(in srgb, currentColor 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, currentColor 8%, transparent);
  padding: 4px 5px 4px 8px;
  color: inherit;
}

.attachment-row--failed {
  border-color: color-mix(in srgb, var(--red) 36%, transparent);
  background: color-mix(in srgb, var(--red) 9%, transparent);
}

.attachment-main {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 7px;
  border: 0;
  background: transparent;
  color: inherit;
  padding: 0;
  text-align: left;
}

.attachment-main:disabled {
  cursor: default;
}

.attachment-kind {
  flex: 0 0 auto;
  min-width: 34px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, currentColor 12%, transparent);
  padding: 2px 5px;
  font-size: 10px;
  font-weight: 800;
  line-height: 1.4;
  text-align: center;
}

.attachment-name {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-meta,
.attachment-error {
  flex: 0 0 auto;
  color: color-mix(in srgb, currentColor 58%, transparent);
  font-size: 11px;
  line-height: 1.35;
  white-space: nowrap;
}

.attachment-error {
  color: var(--red);
  font-weight: 700;
}

.attachment-action,
.attachment-remove {
  min-width: 28px;
  height: 24px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: inherit;
  padding: 0 6px;
  font-size: 12px;
  font-weight: 800;
}

.attachment-remove {
  width: 24px;
  padding: 0;
  font-size: 16px;
}

.attachment-action:hover,
.attachment-remove:hover {
  background: color-mix(in srgb, currentColor var(--alpha-hover), transparent);
}
</style>
