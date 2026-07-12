<script setup lang="ts">
export interface CoreQueuedInputTrayItem {
  id: string
  text: string
  status?: string
  position?: number
}

const props = defineProps<{
  items: CoreQueuedInputTrayItem[]
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
  'update:draft': [value: string]
}>()

function inputValue(event: Event): string {
  return (event.target as HTMLInputElement | null)?.value ?? ''
}

function isSubmitting(itemId: string): boolean {
  return props.submittingIds?.has(itemId) === true
}
</script>

<template>
  <div v-if="items.length" class="core-queued-input-tray" aria-label="待发送输入">
    <div v-for="(item, index) in items" :key="item.id" class="core-queued-input-row">
      <div class="core-queued-input-copy">
        <span class="core-queued-input-status">{{ item.position || index + 1 }}.</span>
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
        <button
          class="core-queued-input-icon-action"
          type="button"
          :disabled="item.status !== 'queued' || isSubmitting(item.id)"
          title="编辑"
          aria-label="编辑待发送内容"
          @click="emit('edit', item)"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 20h9" />
            <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4 11.5-11.5Z" />
          </svg>
        </button>
        <button
          type="button"
          :disabled="!canGuide || item.status !== 'queued' || isSubmitting(item.id)"
          aria-label="作为引导发送"
          @click="emit('guide', item)"
        >
          引导
        </button>
        <button
          class="core-queued-input-icon-action"
          type="button"
          :disabled="item.status === 'dispatching' || isSubmitting(item.id)"
          title="删除"
          aria-label="删除待发送内容"
          @click="emit('delete', item)"
        >
          ×
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.core-queued-input-tray {
  position: absolute;
  right: var(--queued-input-right-inset, 0);
  bottom: calc(100% + 8px);
  left: var(--queued-input-left-inset, 20px);
  width: calc(100% - var(--composer-side-width, 58px) - var(--queued-input-left-inset, 20px) - var(--queued-input-right-inset, 0px));
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 10%, transparent);
  background: color-mix(in srgb, var(--theme-surface) 96%, transparent);
}

.core-queued-input-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 36px;
  gap: 8px;
  padding: 7px 8px;
  font-size: 12px;
}

.core-queued-input-row + .core-queued-input-row {
  border-top: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 7%, transparent);
}

.core-queued-input-copy {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 7px;
  flex: 1;
}

.core-queued-input-status {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--theme-backdrop-text) 50%, transparent);
}

.core-queued-input-text {
  min-width: 0;
  overflow: hidden;
  color: color-mix(in srgb, var(--theme-backdrop-text) 82%, transparent);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-queued-input-edit {
  min-width: 0;
  width: 100%;
  border: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 16%, transparent);
  background: color-mix(in srgb, var(--theme-surface) 92%, transparent);
  color: var(--theme-backdrop-text);
  font: inherit;
  line-height: 1.4;
  outline: none;
  padding: 3px 5px;
}

.core-queued-input-edit:focus {
  border-color: color-mix(in srgb, var(--theme-backdrop-text) 32%, transparent);
}

.core-queued-input-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 4px;
}

.core-queued-input-actions button {
  height: 24px;
  min-width: 24px;
  border: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 10%, transparent);
  background: color-mix(in srgb, var(--theme-backdrop-text) 5%, transparent);
  color: color-mix(in srgb, var(--theme-backdrop-text) 72%, transparent);
  cursor: pointer;
  font-size: 11px;
}

.core-queued-input-actions button:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-backdrop-text) 10%, transparent);
  color: var(--theme-backdrop-text);
}

.core-queued-input-actions button:disabled {
  cursor: default;
  opacity: 0.38;
}

.core-queued-input-icon-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.core-queued-input-icon-action svg {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
}

@media (max-width: 720px) {
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
