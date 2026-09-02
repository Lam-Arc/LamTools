<template>
  <div v-if="attachments.length" class="attachment-tray" aria-label="附件">
    <article
      v-for="item in attachments"
      :key="item.id"
      class="attachment-card"
      :class="{
        'attachment-card--image': isDisplayImage(item),
        'attachment-card--failed': item.status === 'failed',
      }"
      @contextmenu="onContextMenu($event, item)"
    >
      <button
        type="button"
        class="attachment-preview"
        :class="{ 'attachment-preview--image': isDisplayImage(item) }"
        :disabled="item.status === 'failed'"
        :data-attachment-preview="item.id"
        :aria-label="`预览 ${item.label || item.filename}`"
        @click="$emit('preview', item.id)"
      >
        <span class="attachment-visual" :class="`attachment-visual--${kindTone(item)}`">
          <img
            v-if="thumbnailUrls[item.id]"
            class="attachment-thumbnail"
            :src="thumbnailUrls[item.id]"
            alt=""
          >
          <component
            :is="kindIcon(item)"
            v-else
            :size="22"
            :stroke-width="1.8"
            aria-hidden="true"
          />
        </span>
        <span v-if="!isDisplayImage(item)" class="attachment-copy">
          <span class="attachment-name" :title="item.label || item.filename">
            {{ item.label || item.filename }}
          </span>
          <span class="attachment-type">{{ kindLabel(item) }}</span>
        </span>
      </button>

      <span v-if="item.status === 'failed'" class="attachment-error">{{ item.error || '上传失败' }}</span>
      <button
        v-if="item.status === 'failed'"
        type="button"
        class="attachment-retry"
        :data-attachment-retry="item.id"
        @click="$emit('retry', item.id)"
      >
        重试
      </button>
      <button
        type="button"
        class="attachment-remove"
        :data-attachment-remove="item.id"
        :aria-label="`移除 ${item.label || item.filename}`"
        @click="$emit('remove', item.id)"
      >
        <X :size="14" :stroke-width="2" aria-hidden="true" />
      </button>
    </article>
  </div>
</template>

<script setup lang="ts">
import { reactive, watch, type Component } from 'vue';
import {
  File,
  FileArchive,
  FileImage,
  FileText,
  Eye,
  ExternalLink,
  Sheet,
  RotateCcw,
  Trash2,
  X,
} from 'lucide-vue-next';
import type { CoreAttachment } from '../types';
import { isNativeContextTarget, openContextMenu } from './context-menu/context-menu';
import type { ContextMenuEntry } from './context-menu/types';

const props = withDefaults(defineProps<{
  attachments: CoreAttachment[];
  apiBase?: string;
}>(), {
  apiBase: '',
});
const thumbnailUrls = reactive<Record<string, string>>({});

const emit = defineEmits<{
  remove: [id: string];
  retry: [id: string];
  preview: [id: string];
  open: [id: string];
}>();

function onContextMenu(event: MouseEvent, item: CoreAttachment): void {
  if (isNativeContextTarget(event.target)) return;
  const failed = item.status === 'failed'
  const items: ContextMenuEntry[] = failed
    ? [
        { id: 'retry', label: '重试', icon: RotateCcw, action: () => emit('retry', item.id) },
        { type: 'separator', id: 'attachment-danger-separator' },
        { id: 'remove', label: '移除', icon: Trash2, destructive: true, action: () => emit('remove', item.id) },
      ]
    : [
        { id: 'preview', label: '预览', icon: Eye, action: () => emit('preview', item.id) },
        { id: 'open', label: '系统打开', icon: ExternalLink, action: () => emit('open', item.id) },
        { type: 'separator', id: 'attachment-danger-separator' },
        { id: 'remove', label: '移除', icon: Trash2, destructive: true, action: () => emit('remove', item.id) },
      ];
  openContextMenu({
    event,
    items,
    ownerId: `attachment:${item.id}`,
    ariaLabel: `${item.label || item.filename} 附件操作`,
    panelAttributes: { 'data-attachment-menu': item.id },
  });
}

function extension(item: CoreAttachment): string {
  return item.filename.split('.').pop()?.toLowerCase() || '';
}

function kindLabel(item: CoreAttachment): string {
  if (item.status === 'failed') return '上传失败';
  const ext = extension(item);
  if (ext) return ext.toUpperCase();
  const previewType = String(item.preview_type || '').toLowerCase();
  return previewType && previewType !== 'external' ? previewType.toUpperCase() : '文件';
}

function kindTone(item: CoreAttachment): string {
  const ext = extension(item);
  if (item.status === 'failed') return 'failed';
  if (ext === 'pdf') return 'pdf';
  if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext)) return 'archive';
  if (['xls', 'xlsx', 'csv'].includes(ext)) return 'sheet';
  if (item.preview_type === 'image' || item.mime_type.startsWith('image/')) return 'image';
  if (item.preview_type === 'text' || item.mime_type.startsWith('text/')) return 'text';
  return 'file';
}

function kindIcon(item: CoreAttachment): Component {
  const tone = kindTone(item);
  if (tone === 'archive') return FileArchive;
  if (tone === 'sheet') return Sheet;
  if (tone === 'image') return FileImage;
  if (tone === 'pdf' || tone === 'text') return FileText;
  return File;
}

function isDisplayImage(item: CoreAttachment): boolean {
  return item.status !== 'failed'
    && (item.preview_type === 'image' || item.mime_type.startsWith('image/'));
}

function blobDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener('load', () => resolve(String(reader.result || '')));
    reader.addEventListener('error', () => reject(reader.error));
    reader.readAsDataURL(blob);
  });
}

async function loadThumbnail(item: CoreAttachment): Promise<void> {
  if (!props.apiBase || !isDisplayImage(item) || thumbnailUrls[item.id]) return;
  try {
    const response = await fetch(`${props.apiBase}/attachments/${encodeURIComponent(item.id)}/download`);
    if (!response.ok) return;
    thumbnailUrls[item.id] = await blobDataUrl(await response.blob());
  } catch {
    // Keep the neutral image placeholder if the local attachment is unavailable.
  }
}

watch(
  () => [props.apiBase, ...props.attachments.map(item => `${item.id}:${item.status || ''}`)],
  () => {
    const activeIds = new Set(props.attachments.map(item => item.id));
    for (const id of Object.keys(thumbnailUrls)) {
      if (!activeIds.has(id)) delete thumbnailUrls[id];
    }
    for (const item of props.attachments) void loadThumbnail(item);
  },
  { immediate: true },
);
</script>

<style scoped>
.attachment-tray {
  --text: var(--theme-composer-text);
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-3) 0;
}

.attachment-card {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  width: min(240px, 100%);
  min-height: 68px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--theme-composer-soft-background) 72%, transparent);
  color: var(--text);
  transition:
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out);
}

.attachment-card:hover {
  border-color: color-mix(in srgb, var(--text) 20%, transparent);
  background: color-mix(in srgb, var(--text) var(--alpha-hover), var(--theme-composer-soft-background));
  transform: translateY(-1px);
}

.attachment-card:active {
  background: color-mix(in srgb, var(--text) var(--alpha-active), var(--theme-composer-soft-background));
  transform: translateY(0);
}

.attachment-card--failed {
  border-color: color-mix(in srgb, var(--red) 36%, transparent);
  background: color-mix(in srgb, var(--red) 8%, var(--theme-composer-soft-background));
}

.attachment-card--image {
  display: block;
  width: 88px;
  min-height: 88px;
}

.attachment-preview {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-3);
  border: 0;
  background: transparent;
  color: inherit;
  padding: var(--space-2) 36px var(--space-2) var(--space-2);
  text-align: left;
}

.attachment-preview:disabled {
  cursor: default;
}

.attachment-preview--image {
  width: 88px;
  height: 88px;
  padding: 0;
}

.attachment-preview--image .attachment-visual {
  flex-basis: 88px;
  width: 88px;
  height: 88px;
  border-radius: 0;
}

.attachment-visual {
  display: grid;
  flex: 0 0 48px;
  width: 48px;
  height: 48px;
  place-items: center;
  overflow: hidden;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: color-mix(in srgb, var(--text) 72%, transparent);
}

.attachment-visual--pdf,
.attachment-visual--failed {
  background: color-mix(in srgb, var(--red) 14%, transparent);
  color: var(--red);
}

.attachment-visual--archive {
  background: color-mix(in srgb, var(--orange) 14%, transparent);
  color: var(--orange);
}

.attachment-visual--image {
  background: color-mix(in srgb, var(--purple) 14%, transparent);
  color: var(--purple);
}

.attachment-visual--sheet {
  background: color-mix(in srgb, var(--green) 14%, transparent);
  color: var(--green);
}

.attachment-visual--text {
  background: color-mix(in srgb, var(--blue) 14%, transparent);
  color: var(--blue);
}

.attachment-thumbnail {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.attachment-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.attachment-name {
  overflow: hidden;
  font-size: 13px;
  font-weight: 720;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-type,
.attachment-error {
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 12px;
  line-height: 1.35;
}

.attachment-error {
  align-self: end;
  padding: 0 0 var(--space-2);
  color: var(--red);
  font-weight: 700;
}

.attachment-remove,
.attachment-retry {
  position: absolute;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 65%, transparent);
}

.attachment-remove {
  top: var(--space-1);
  right: var(--space-1);
  display: grid;
  width: 28px;
  height: 28px;
  padding: 0;
  place-items: center;
}

.attachment-retry {
  right: var(--space-2);
  bottom: var(--space-1);
  height: 28px;
  padding: 0 var(--space-2);
  font-size: 12px;
  font-weight: 700;
}

.attachment-remove:hover,
.attachment-retry:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.attachment-remove:active,
.attachment-retry:active {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

@media (prefers-reduced-motion: reduce) {
  .attachment-card {
    transition: none;
  }

  .attachment-card:hover {
    transform: none;
  }
}
</style>
