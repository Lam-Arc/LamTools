<template>
  <div v-if="attachments.length" class="attachment-tray" :aria-label="t('附件')">
    <div
      v-for="column in columns"
      :key="column.key"
      class="attachment-column"
      :class="`attachment-column--${column.kind}`"
    >
      <article
        v-for="item in column.items"
        :key="item.id"
        class="attachment-entry"
        :class="{
          'attachment-entry--media': isDisplayMedia(item),
          'attachment-entry--uploading': item.status === 'uploading',
          'attachment-entry--failed': item.status === 'failed',
        }"
        @contextmenu="onContextMenu($event, item)"
      >
        <button
          v-if="isDisplayMedia(item)"
          type="button"
          class="attachment-preview attachment-preview--media"
          :disabled="!canPreview(item)"
          :data-attachment-preview="item.id"
          :aria-label="t('预览 {0}', { 0: item.label || item.filename })"
          @click="$emit('preview', item.id)"
        >
          <img
            v-if="isDisplayImage(item) && thumbnailUrls[item.id]"
            class="attachment-media"
            :src="thumbnailUrls[item.id]"
            alt=""
          >
          <video
            v-else-if="isDisplayVideo(item) && thumbnailUrls[item.id]"
            class="attachment-media"
            :src="`${thumbnailUrls[item.id]}#t=0.1`"
            muted
            playsinline
            preload="metadata"
            @loadedmetadata="seekVideoFrame"
          ></video>
          <span v-else class="attachment-media attachment-media--placeholder">
            <FileTypeBadge :name="item.filename" :size="34" />
          </span>
          <span class="attachment-media-shade" aria-hidden="true"></span>
          <span class="attachment-media-badge" aria-hidden="true">
            <Play v-if="isDisplayVideo(item)" :size="12" fill="currentColor" :stroke-width="0" />
            <ImageIcon v-else :size="12" :stroke-width="2" />
          </span>
          <span class="attachment-media-name">{{ item.label || item.filename }}</span>
          <span v-if="item.status === 'uploading'" class="attachment-state">{{ t("上传中…") }}</span>
        </button>

        <button
          v-else
          type="button"
          class="attachment-pill"
          :disabled="!canPreview(item)"
          :data-attachment-preview="item.id"
          :title="item.error || item.label || item.filename"
          :aria-label="t('预览 {0}', { 0: item.label || item.filename })"
          @click="$emit('preview', item.id)"
        >
          <FileTypeBadge :name="item.filename" :size="22" :failed="item.status === 'failed'" />
          <span class="attachment-pill-copy">
            <span class="attachment-pill-name">{{ item.label || item.filename }}</span>
            <span class="attachment-pill-type">{{ kindLabel(item) }}</span>
          </span>
        </button>

        <span v-if="item.status === 'failed'" class="attachment-error">{{ item.error || t("上传失败") }}</span>
        <button
          v-if="item.status === 'failed'"
          type="button"
          class="attachment-retry"
          :data-attachment-retry="item.id"
          @click="$emit('retry', item.id)"
        >{{ t("重试") }}</button>
        <button
          type="button"
          class="attachment-remove"
          :data-attachment-remove="item.id"
          :aria-label="t('移除 {0}', { 0: item.label || item.filename })"
          @click="$emit('remove', item.id)"
        >
          <X :size="13" :stroke-width="2" aria-hidden="true" />
        </button>
      </article>
    </div>
  </div>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { computed, reactive, watch } from 'vue';
import {
  Eye,
  ExternalLink,
  Image as ImageIcon,
  Play,
  RotateCcw,
  Trash2,
  X,
} from 'lucide-vue-next';
import type { CoreAttachment } from '@/types.ts';
import type { LamToolsTransport, TransportHttpResponse } from '@/transport/index.ts';
import { isNativeContextTarget, openContextMenu } from '@/components/context-menu/context-menu.ts';
import type { ContextMenuEntry } from '@/components/context-menu/types.ts';
import FileTypeBadge from '@/components/FileTypeBadge.vue';

const props = defineProps<{
  attachments: CoreAttachment[];
  transport: LamToolsTransport;
}>();
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
        { id: 'retry', get label() { return t("重试") }, icon: RotateCcw, action: () => emit('retry', item.id) },
        { type: 'separator', id: 'attachment-danger-separator' },
        { id: 'remove', get label() { return t("移除") }, icon: Trash2, destructive: true, action: () => emit('remove', item.id) },
      ]
    : [
        { id: 'preview', get label() { return t("预览") }, icon: Eye, action: () => emit('preview', item.id) },
        { id: 'open', get label() { return t("系统打开") }, icon: ExternalLink, action: () => emit('open', item.id) },
        { type: 'separator', id: 'attachment-danger-separator' },
        { id: 'remove', get label() { return t("移除") }, icon: Trash2, destructive: true, action: () => emit('remove', item.id) },
      ];
  openContextMenu({
    event,
    items,
    ownerId: `attachment:${item.id}`,
    ariaLabel: t("{0} 附件操作", { 0: item.label || item.filename }),
    panelAttributes: { 'data-attachment-menu': item.id },
  });
}

function extension(item: CoreAttachment): string {
  return item.filename.split('.').pop()?.toLowerCase() || '';
}

const VIDEO_EXTENSIONS = new Set(['mp4', 'webm', 'mov', 'm4v', 'ogv', 'mkv', 'avi'])

// user:“图片和视频附件以大缩略显示”+(输入框上方的待发附件里，图片和视频直接铺大缩略图；
// 文档类使用“中号胶囊”，图标 + 文件名 + 类型，避免一排大卡片挤满输入区)。
function isDisplayImage(item: CoreAttachment): boolean {
  return item.status !== 'failed' && (item.preview_type === 'image' || item.mime_type.startsWith('image/'))
}

function isDisplayVideo(item: CoreAttachment): boolean {
  return item.status !== 'failed'
    && (item.preview_type === 'video' || item.mime_type.startsWith('video/') || VIDEO_EXTENSIONS.has(extension(item)))
}

function isDisplayMedia(item: CoreAttachment): boolean {
  return isDisplayImage(item) || isDisplayVideo(item)
}

function canPreview(item: CoreAttachment): boolean {
  return item.status !== 'failed' && item.status !== 'uploading'
}

interface TrayColumn {
  key: string
  kind: 'media' | 'stack'
  items: CoreAttachment[]
}

/** Media cards are as tall as three compact pills; keep that rule in one place. */
const STACK_CAPACITY = 3

// user:“那三个附件纵向堆叠起来，夹在图片和视频的中间”+
// (保持上传顺序：媒体各自占一列；连续的小附件按 3 个一列纵向叠放，
// 第 4 个另起一列但仍留在原来的位置。例如 图片+4附件+视频+1附件+视频 →
// 图片 / 3附件 / 1附件 / 视频 / 1附件 / 视频。)
const columns = computed<TrayColumn[]>(() => {
  const result: TrayColumn[] = []
  let stack: CoreAttachment[] = []
  let stackIndex = 0
  const flush = () => {
    if (!stack.length) return
    result.push({ key: `stack-${stackIndex++}`, kind: 'stack', items: stack })
    stack = []
  }
  props.attachments.forEach((item, index) => {
    if (isDisplayMedia(item)) {
      flush()
      result.push({ key: `media-${item.id || index}`, kind: 'media', items: [item] })
      return
    }
    stack.push(item)
    if (stack.length >= STACK_CAPACITY) flush()
  })
  flush()
  return result
})

function kindLabel(item: CoreAttachment): string {
  if (item.status === 'failed') return t("上传失败");
  if (item.status === 'uploading') return t("上传中…");
  const ext = extension(item);
  if (ext) return ext.toUpperCase();
  const previewType = String(item.preview_type || '').toLowerCase();
  return previewType && previewType !== 'external' ? previewType.toUpperCase() : t("文件");
}

function blobDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener('load', () => resolve(String(reader.result || '')));
    reader.addEventListener('error', () => reject(reader.error));
    reader.readAsDataURL(blob);
  });
}

function seekVideoFrame(event: Event): void {
  const video = event.target
  if (!(video instanceof HTMLVideoElement)) return
  try { video.currentTime = 0.1 } catch { /* Some codecs reject early seeks. */ }
}

async function loadThumbnail(item: CoreAttachment): Promise<void> {
  if (!isDisplayMedia(item) || thumbnailUrls[item.id]) return;
  try {
    const response = await props.transport.request<TransportHttpResponse>({
      kind: 'http',
      method: 'GET',
      path: `/attachments/${encodeURIComponent(item.id)}/download`,
    });
    if (response.status < 200 || response.status >= 300) return;
    thumbnailUrls[item.id] = await blobDataUrl(new Blob([Uint8Array.from(response.body)], {
      type: response.headers['content-type'] || item.mime_type || 'application/octet-stream',
    }));
  } catch {
    // Keep the neutral type placeholder if the local attachment is unavailable.
  }
}

watch(
  () => [props.transport, ...props.attachments.map(item => `${item.id}:${item.status || ''}`)],
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
  align-content: flex-end;
  align-items: flex-end;
  gap: var(--space-2);
  max-height: 216px;
  overflow-y: auto;
  padding: var(--space-2) var(--space-3) 0;
  scrollbar-width: thin;
}

.attachment-column {
  display: flex;
  flex: 0 0 auto;
  flex-direction: column;
  justify-content: flex-end;
  gap: 4px;
}

/* 媒体卡与“最多三个胶囊”的列等高：图/视频 104px = 3 × 32px + 2 × 4px。 */
.attachment-column--media,
.attachment-column--stack {
  height: 104px;
}

.attachment-column--stack {
  align-items: stretch;
  max-width: min(260px, 70vw);
}

.attachment-entry {
  position: relative;
  min-width: 0;
}

.attachment-entry--uploading { opacity: .72; }

/* 中号胶囊：图标 + 文件名 + 类型。 */
.attachment-pill {
  display: inline-flex;
  width: 100%;
  max-width: 260px;
  height: 32px;
  align-items: center;
  gap: var(--space-1);
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: 999px;
  padding: 0 26px 0 5px;
  background: color-mix(in srgb, var(--theme-composer-soft-background) 82%, transparent);
  color: var(--text);
  text-align: left;
  transition: background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
}

.attachment-pill:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--text) 22%, transparent);
  background: color-mix(in srgb, var(--text) var(--alpha-hover), var(--theme-composer-soft-background));
}

.attachment-pill:disabled { cursor: default; }

.attachment-pill-copy {
  display: grid;
  min-width: 0;
  gap: 0;
}

.attachment-pill-name {
  overflow: hidden;
  font-size: 11.5px;
  font-weight: 680;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-pill-type {
  color: color-mix(in srgb, var(--text) 58%, transparent);
  font-size: 9px;
  font-weight: 650;
  letter-spacing: .05em;
  line-height: 1.15;
}

/* 中大卡片：图片/视频缩略图。 */
.attachment-preview--media {
  position: relative;
  display: block;
  width: 104px;
  height: 104px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius);
  padding: 0;
  background: color-mix(in srgb, var(--theme-composer-soft-background) 80%, transparent);
  color: var(--text);
}

.attachment-preview--media:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--text) 24%, transparent);
}

.attachment-media {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.attachment-media--placeholder {
  display: grid;
  place-items: center;
}

.attachment-media-shade {
  position: absolute;
  inset: auto 0 0;
  height: 46%;
  background: linear-gradient(to top, color-mix(in srgb, #000 62%, transparent), transparent);
  pointer-events: none;
}

.attachment-media-name {
  position: absolute;
  right: var(--space-1);
  bottom: 5px;
  left: var(--space-1);
  overflow: hidden;
  color: #fff;
  font-size: 10.5px;
  font-weight: 650;
  text-overflow: ellipsis;
  text-shadow: 0 1px 2px color-mix(in srgb, #000 55%, transparent);
  white-space: nowrap;
}

.attachment-media-badge {
  position: absolute;
  top: var(--space-1);
  left: var(--space-1);
  display: grid;
  width: 20px;
  height: 20px;
  place-items: center;
  border-radius: 50%;
  background: color-mix(in srgb, #000 48%, transparent);
  color: #fff;
}

.attachment-state {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  background: color-mix(in srgb, #000 42%, transparent);
  color: #fff;
  font-size: 11px;
  font-weight: 650;
}

.attachment-entry--failed .attachment-preview--media,
.attachment-entry--failed .attachment-pill {
  border-color: color-mix(in srgb, var(--red) 46%, transparent);
  background: color-mix(in srgb, var(--red) 10%, var(--theme-composer-soft-background));
}

.attachment-error {
  position: absolute;
  right: 6px;
  bottom: -16px;
  max-width: 100%;
  overflow: hidden;
  color: var(--red);
  font-size: 10px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 叠放列里空间只有 32px，一条错误文字会把下一枚胶囊挤走；
   失败态用红色胶囊 + 悬浮提示表达，重试按钮仍在。 */
.attachment-column--stack .attachment-error { display: none; }

.attachment-remove,
.attachment-retry {
  position: absolute;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: color-mix(in srgb, var(--text) 62%, transparent);
}

.attachment-remove {
  top: 50%;
  right: 5px;
  display: grid;
  width: 20px;
  height: 20px;
  padding: 0;
  place-items: center;
  transform: translateY(-50%);
}

.attachment-entry--media .attachment-remove {
  top: 5px;
  right: 5px;
  transform: none;
  background: color-mix(in srgb, #000 46%, transparent);
  color: #fff;
}

.attachment-retry {
  right: 26px;
  top: 50%;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
  transform: translateY(-50%);
}

.attachment-remove:hover,
.attachment-retry:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.attachment-entry--media .attachment-remove:hover { background: color-mix(in srgb, #000 64%, transparent); color: #fff; }

@media (prefers-reduced-motion: reduce) {
  .attachment-pill { transition: none; }
}
</style>
