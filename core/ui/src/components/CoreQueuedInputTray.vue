<script setup lang="ts">
import { ref } from 'vue'

import { t } from '@/i18n/index.ts'

import { Goal } from 'lucide-vue-next'
import type { CoreGoal } from '@/durable/types.ts'

export interface CoreQueuedInputTrayItem {
  id: string
  text: string
  status?: string
  position?: number
}

const props = defineProps<{
  items: CoreQueuedInputTrayItem[]
  goal?: CoreGoal | null
  editingId?: string | null
  draft?: string
  canGuide?: boolean
  submittingIds?: Set<string>
}>()

const emit = defineEmits<{
  edit: [item: CoreQueuedInputTrayItem]
  save: [item: CoreQueuedInputTrayItem]
  cancel: []
  delete: [item: CoreQueuedInputTrayItem]
  guide: [item: CoreQueuedInputTrayItem]
  'cancel-goal': [goal: CoreGoal]
  'update:draft': [value: string]
  reorder: [items: CoreQueuedInputTrayItem[]]
}>()

function inputValue(event: Event): string {
  return (event.target as HTMLInputElement | null)?.value ?? ''
}

function isSubmitting(itemId: string): boolean {
  return props.submittingIds?.has(itemId) === true
}

// user:“排队项可拖拽上下移动重新排序”+(行内 HTML5 拖拽：按住行拖到目标位置，
//   上下半区决定插到目标行之前还是之后；松手提交一份完整新顺序，顺序没变不提交)。
const draggingId = ref('')
/** 拖拽悬停目标：id + 是否插到该行之前，用来画插入线。 */
const dropHint = ref<{ id: string; before: boolean } | null>(null)

function canDrag(item: CoreQueuedInputTrayItem): boolean {
  return item.status === 'queued' && !isSubmitting(item.id) && props.editingId !== item.id
}

function onDragStart(item: CoreQueuedInputTrayItem, event: DragEvent): void {
  if (!canDrag(item)) {
    event.preventDefault()
    return
  }
  draggingId.value = item.id
  event.dataTransfer?.setData('text/plain', item.id)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function onDragOver(item: CoreQueuedInputTrayItem, event: DragEvent): void {
  if (!draggingId.value || draggingId.value === item.id) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  const bounds = (event.currentTarget as HTMLElement | null)?.getBoundingClientRect()
  const before = bounds ? (event.clientY - bounds.top) < bounds.height / 2 : true
  dropHint.value = dropHint.value?.id === item.id && dropHint.value.before === before
    ? dropHint.value
    : { id: item.id, before }
}

function onDragLeave(item: CoreQueuedInputTrayItem): void {
  if (dropHint.value?.id === item.id) dropHint.value = null
}

function onDrop(item: CoreQueuedInputTrayItem, event: DragEvent): void {
  event.preventDefault()
  const hint = dropHint.value
  dropHint.value = null
  const draggedId = draggingId.value || event.dataTransfer?.getData('text/plain') || ''
  draggingId.value = ''
  if (!draggedId || draggedId === item.id) return
  const others = props.items.filter(candidate => candidate.id !== draggedId)
  const targetIndex = others.findIndex(candidate => candidate.id === item.id)
  if (targetIndex < 0) return
  const insertIndex = hint?.before ? targetIndex : targetIndex + 1
  const dragged = props.items.find(candidate => candidate.id === draggedId)
  if (!dragged) return
  const next = [...others.slice(0, insertIndex), dragged, ...others.slice(insertIndex)]
  if (next.every((candidate, index) => candidate.id === props.items[index]?.id)) return
  emit('reorder', next)
}

function onDragEnd(): void {
  draggingId.value = ''
  dropHint.value = null
}
</script>

<template>
  <div
    v-if="goal || items.length"
    class="core-queued-input-tray core-guidance-queue-panel optical-glass optical-glass--low-trans"
    :data-status="goal?.status"
    :aria-label="t('目标与待发送输入')"
  >
    <div v-if="goal" class="core-queued-goal-row" :data-status="goal.status" role="status">
      <span class="core-queued-goal-icon" aria-hidden="true"><Goal :size="13" :stroke-width="1.8" /></span>
      <span class="core-queued-goal-objective">{{ goal.objective }}</span>
      <span class="core-queued-goal-status">{{ goal.status === 'blocked' ? t("已暂停") : t("进行中") }}</span>
      <button type="button" class="core-queued-goal-cancel" @click="emit('cancel-goal', goal)">{{ t("取消") }}</button>
    </div>
    <div
      v-for="(item, index) in items"
      :key="item.id"
      class="core-queued-input-row"
      :class="{
        'is-editing': editingId === item.id,
        'is-dragging': draggingId === item.id,
        'is-drop-before': dropHint?.id === item.id && dropHint.before,
        'is-drop-after': dropHint?.id === item.id && !dropHint.before,
      }"
      :draggable="canDrag(item)"
      :aria-label="t('排队项，可拖拽调整顺序')"
      @dragstart="onDragStart(item, $event)"
      @dragover="onDragOver(item, $event)"
      @dragleave="onDragLeave(item)"
      @drop="onDrop(item, $event)"
      @dragend="onDragEnd"
    >
      <div class="core-queued-input-copy">
        <span class="core-queued-input-status" :title="t('拖拽调整顺序')">{{ item.position || index + 1 }}.</span>
        <input
          v-if="editingId === item.id"
          :value="draft"
          class="core-queued-input-edit"
          :data-queued-input-edit="item.id"
          @input="emit('update:draft', inputValue($event))"
          @blur="emit('save', item)"
          @keydown.enter.prevent="emit('save', item)"
          @keydown.esc.prevent="emit('cancel')"
        />
        <span v-else class="core-queued-input-text">{{ item.text }}</span>
      </div>
      <div class="core-queued-input-actions">
        <!-- 折叠态：省略号指示器 -->
        <button class="core-queued-input-ellipsis" tabindex="-1" aria-hidden="true">
          <svg viewBox="0 0 16 4" aria-hidden="true" class="ellipsis-icon">
            <circle cx="2" cy="2" r="1.5" fill="currentColor" />
            <circle cx="8" cy="2" r="1.5" fill="currentColor" />
            <circle cx="14" cy="2" r="1.5" fill="currentColor" />
          </svg>
        </button>
        <!-- 展开态：三个操作按钮 -->
        <div class="core-queued-input-buttons">
          <button
            class="core-queued-input-action core-queued-input-delete"
            type="button"
            :disabled="item.status === 'dispatching' || isSubmitting(item.id)"
            :title="t('删除')"
            :aria-label="t('删除待发送内容')"
            @click="emit('delete', item)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
          <button
            class="core-queued-input-action"
            type="button"
            :disabled="item.status !== 'queued' || isSubmitting(item.id)"
            :title="t('编辑')"
            :aria-label="t('编辑待发送内容')"
            @click="emit('edit', item)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 20h9" />
              <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4 11.5-11.5Z" />
            </svg>
          </button>
          <button
            class="core-queued-input-action"
            type="button"
            :disabled="!canGuide || item.status !== 'queued' || isSubmitting(item.id)"
            :aria-label="t('作为引导发送')"
            @click="emit('guide', item)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ===== Goal and queued input panel, attached to the composer ===== */

.core-queued-input-tray {
  --text: var(--theme-composer-text);
  --optical-glass-surface: var(--theme-composer-background);
  --optical-glass-overlay: transparent;
  position: relative;
  margin: 0;
  overflow: hidden;
  /* user:“只在上面拼接一个下方不是圆角的矩形，上边是圆角”+(托盘只开上圆角，
     下方直角贴在输入栏上沿；宽度由输入栏上方的共享挂载点收窄)。 */
  border-radius: var(--composer-radius) var(--composer-radius) 0 0;
}

.core-queued-input-tray[data-status='blocked'] {
  --optical-glass-overlay: color-mix(in srgb, var(--orange) 10%, transparent);
}

.core-queued-goal-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 34px;
  padding: 6px 16px;
  color: var(--theme-composer-text);
  font-size: 13px;
  line-height: 1.4;
}

.core-queued-goal-icon {
  flex: 0 0 auto;
  opacity: .55;
}

.core-queued-goal-objective {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-queued-goal-status {
  flex: 0 0 auto;
  margin-left: auto;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 11px;
  white-space: nowrap;
}

.core-queued-goal-cancel {
  flex: 0 0 auto;
  padding: 2px 8px;
  border: 1px solid color-mix(in srgb, var(--text) 16%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 11px;
  cursor: pointer;
  line-height: 1.4;
}

.core-queued-goal-cancel:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.core-queued-input-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 34px;
  gap: 8px;
  padding: 6px 10px;
  font-size: 12px;
}

.core-queued-input-row + .core-queued-input-row,
.core-queued-goal-row + .core-queued-input-row {
  border-top: 1px solid color-mix(in srgb, var(--theme-composer-text) 6%, transparent);
}

/* --- 拖拽重排序：抓手、拖动中的行、插入位置线 --- */

.core-queued-input-row[draggable='true'] {
  cursor: grab;
}

.core-queued-input-row.is-dragging {
  opacity: 0.45;
}

/* 插入线画在目标行的上/下边缘，覆盖相邻行共享的 border。 */
.core-queued-input-row.is-drop-before {
  box-shadow: inset 0 2px 0 color-mix(in srgb, var(--theme-composer-text) 55%, transparent);
}

.core-queued-input-row.is-drop-after {
  box-shadow: inset 0 -2px 0 color-mix(in srgb, var(--theme-composer-text) 55%, transparent);
}

.core-queued-input-copy {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 7px;
  flex: 1;
}

.core-queued-input-status {
  position: relative;
  z-index: 6;
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--theme-composer-text) 40%, transparent);
}

.core-queued-input-text {
  min-width: 0;
  overflow: hidden;
  color: color-mix(in srgb, var(--theme-composer-text) 75%, transparent);
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* --- Inline edit field replaces the preview text, so the two never overlap. --- */

.core-queued-input-edit {
  min-width: 0;
  flex: 1;
  font: inherit;
  font-size: 12px;
  line-height: 1.4;
  color: var(--theme-composer-text);
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: var(--radius-sm);
  outline: none;
  padding: 2px var(--space-1);
  box-sizing: border-box;
}

/* ===== Hover-expand action buttons ===== */

.core-queued-input-actions {
  flex: 0 0 auto;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  height: 28px;
  width: 28px;
  overflow: hidden;
  border-radius: var(--radius);
  transition: width 250ms cubic-bezier(0.4, 0, 0.2, 1),
              border-radius 200ms ease 50ms;
}

/* user:“做吧”+(键盘进入队列操作区时，同样展开并显示操作按钮)。 */
.core-queued-input-actions:hover,
.core-queued-input-actions:focus-within {
  width: 92px;
  border-radius: var(--radius);
  transition: width 250ms cubic-bezier(0.4, 0, 0.2, 1);
}

/* --- Ellipsis indicator (collapsed state) --- */

.core-queued-input-ellipsis {
  position: absolute;
  right: 0;
  top: 0;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 50%;
  background: color-mix(in srgb, var(--theme-composer-text) 4%, transparent);
  color: color-mix(in srgb, var(--theme-composer-text) 45%, transparent);
  cursor: pointer;
  pointer-events: auto;
  opacity: 1;
  transition: opacity 120ms ease;
}

.ellipsis-icon {
  width: 16px;
  height: 4px;
}

.core-queued-input-actions:hover .core-queued-input-ellipsis {
  opacity: 0;
  pointer-events: none;
  transition: opacity 80ms ease;
}

/* --- Action buttons (expanded state) --- */

.core-queued-input-buttons {
  display: flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transform: translateX(6px);
  pointer-events: none;
  transition: opacity 180ms ease 60ms, transform 180ms ease 60ms;
}

.core-queued-input-actions:hover .core-queued-input-buttons,
.core-queued-input-actions:focus-within .core-queued-input-buttons {
  opacity: 1;
  transform: translateX(0);
  pointer-events: auto;
  transition: opacity 180ms ease 100ms, transform 180ms ease 100ms;
}

/* --- Individual action buttons --- */

.core-queued-input-action {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: color-mix(in srgb, var(--theme-composer-text) 4%, transparent);
  color: color-mix(in srgb, var(--theme-composer-text) 60%, transparent);
  cursor: pointer;
  font-size: 11px;
  white-space: nowrap;
  transition: background 140ms ease, color 140ms ease;
}

.core-queued-input-action:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-composer-text) var(--alpha-hover), transparent);
  color: var(--theme-composer-text);
}

.core-queued-input-action:disabled {
  cursor: default;
  opacity: 0.38;
}

.core-queued-input-action svg {
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
}

/* --- Delete button: red on hover --- */

.core-queued-input-delete:hover:not(:disabled) {
  background: color-mix(in srgb, var(--red) var(--alpha-hover), transparent);
  color: var(--red, #e53e3e);
}

/* ===== Responsive ===== */

@media (max-width: 720px) {
  .core-queued-goal-status {
    display: none;
  }

  .core-queued-input-row {
    align-items: flex-start;
    flex-direction: column;
  }

  .core-queued-input-copy {
    width: 100%;
  }

  .core-queued-input-actions {
    align-self: flex-end;
  }
}
</style>
