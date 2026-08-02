<template>
  <div v-if="commands.length" class="command-palette" role="listbox" aria-label="命令">
    <div class="command-list">
      <button
        v-for="(command, index) in commands"
        :key="command.name"
        class="command-item"
        :class="{ active: index === activeIndex }"
        type="button"
        role="option"
        :aria-selected="index === activeIndex"
        :aria-label="commandLabel(command)"
        :data-command-name="command.name"
        @click.prevent="$emit('select', command)"
      >
        <span class="command-copy">
          <strong>/{{ command.name }}</strong>
          <small>{{ command.description || command.title }}</small>
        </span>
      </button>
    </div>
    <div class="command-footer" aria-hidden="true">
      <span><kbd>↑↓</kbd> Move</span>
      <span><kbd>Enter</kbd> Select</span>
      <span><kbd>Esc</kbd> Close</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { CoreCommandCatalogItem } from '../types'

defineProps<{
  commands: CoreCommandCatalogItem[]
  activeIndex: number
}>()

defineEmits<{
  select: [command: CoreCommandCatalogItem]
}>()

function commandLabel(command: CoreCommandCatalogItem): string {
  const detail = command.description || command.title || command.name
  return `/${command.name}: ${detail}`
}

</script>

<style scoped>
.command-palette {
  position: absolute;
  left: 0;
  width: min(380px, 100%);
  bottom: calc(100% + 6px);
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text, currentColor) 16%, transparent);
  border-radius: 8px;
  background: var(--theme-composer-background, #111);
  box-shadow: var(--shadow-md);
  z-index: 20;
}

.command-list {
  max-height: min(320px, calc(100vh - 180px));
  overflow-y: auto;
  padding: 4px;
}

.command-item {
  width: 100%;
  display: block;
  align-items: center;
  border: 0;
  border-radius: var(--radius-sm);
  min-height: 42px;
  padding: 7px 9px;
  background: transparent;
  color: var(--theme-composer-text, currentColor);
  text-align: left;
  cursor: default;
}

.command-item.active,
.command-item:hover {
  background: color-mix(in srgb, var(--theme-composer-text, currentColor) 7%, transparent);
}

.command-copy {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.command-copy strong,
.command-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.command-copy strong {
  min-width: 0;
  color: var(--theme-composer-text, currentColor);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  font-weight: 600;
}

.command-copy small {
  color: color-mix(in srgb, var(--theme-composer-text, currentColor) 62%, transparent);
  font-size: 11px;
  line-height: 1.25;
}

.command-footer {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  border-top: 1px solid color-mix(in srgb, var(--theme-composer-text, currentColor) 9%, transparent);
  padding: 5px 9px 6px;
  color: color-mix(in srgb, var(--theme-composer-text, currentColor) 50%, transparent);
  font-size: 10px;
}

.command-footer span {
  display: inline-flex;
  gap: 4px;
  align-items: center;
}

.command-footer kbd {
  min-width: 18px;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text, currentColor) 14%, transparent);
  border-radius: 4px;
  padding: 1px 4px;
  background: color-mix(in srgb, var(--theme-composer-text, currentColor) 5%, transparent);
  color: color-mix(in srgb, var(--theme-composer-text, currentColor) 72%, transparent);
  font: inherit;
  line-height: 1.25;
  text-align: center;
}

@media (max-width: 560px) {
  .command-palette {
    width: 100%;
  }

  .command-footer {
    gap: 8px;
  }
}
</style>
