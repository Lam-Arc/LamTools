<template>
  <div v-if="commands.length" class="command-palette" role="listbox" aria-label="命令">
    <div class="command-list">
      <section v-for="group in groupedCommands" :key="group.kind" class="command-group">
        <div class="command-group-label">{{ group.label }}</div>
        <button
          v-for="item in group.items"
          :key="item.command.name"
          class="command-item"
          :class="{ active: item.index === activeIndex }"
          type="button"
          role="option"
          :aria-selected="item.index === activeIndex"
          :aria-label="commandLabel(item.command)"
          :data-command-name="item.command.name"
          @click.prevent="$emit('select', item.command)"
        >
          <span class="command-icon" aria-hidden="true">
            <component :is="commandIcon(item.command)" :size="17" :stroke-width="1.8" />
          </span>
          <span class="command-copy">
            <strong>/{{ item.command.name }}</strong>
            <small>{{ item.command.description || item.command.title }}</small>
          </span>
          <span class="command-source">{{ commandSourceLabel(item.command) }}</span>
        </button>
      </section>
    </div>
    <div class="command-footer" aria-hidden="true">
      <span><kbd>↑↓</kbd> 移动</span>
      <span><kbd>Enter</kbd> 选择</span>
      <span><kbd>Esc</kbd> 关闭</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, watch, type Component } from 'vue'
import { resolveComposerCommandKind } from '../composer/syntax'
import { coreCommandIcon } from '../composer/commandIcons'
import type { CoreCommandCatalogItem, CoreCommandKind } from '../types'

const props = defineProps<{
  commands: CoreCommandCatalogItem[]
  activeIndex: number
}>()

defineEmits<{
  select: [command: CoreCommandCatalogItem]
}>()

const groupedCommands = computed(() => {
  const groups: Array<{
    kind: CoreCommandKind
    label: string
    items: Array<{ command: CoreCommandCatalogItem; index: number }>
  }> = [
    { kind: 'action', label: '操作', items: [] },
    { kind: 'skill', label: '技能', items: [] },
  ]
  props.commands.forEach((command, index) => {
    const kind = resolveComposerCommandKind(command)
    groups.find(group => group.kind === kind)?.items.push({ command, index })
  })
  return groups.filter(group => group.items.length)
})

watch(
  () => props.activeIndex,
  () => {
    void nextTick(() => {
      const list = document.querySelector('.command-palette .command-list')
      const active = list?.querySelector('.command-item.active')
      active?.scrollIntoView({ block: 'nearest' })
    })
  },
)

function commandIcon(command: CoreCommandCatalogItem): Component {
  return coreCommandIcon(command)
}

function commandSourceLabel(command: CoreCommandCatalogItem): string {
  if (resolveComposerCommandKind(command) === 'skill') return '技能'
  if (command.source === 'plugin') {
    return String(command.metadata?.plugin_title || command.metadata?.plugin_name || '插件')
  }
  if (command.source === 'member') return '成员'
  return 'Core'
}

function commandLabel(command: CoreCommandCatalogItem): string {
  const detail = command.description || command.title || command.name
  return `/${command.name}: ${detail}`
}
</script>

<style scoped>
.command-palette {
  --text: var(--theme-composer-text);
  position: absolute;
  left: 0;
  bottom: calc(100% + var(--space-2));
  z-index: var(--z-popover);
  width: min(520px, 100%);
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius);
  background: var(--theme-composer-background);
  color: var(--text);
  box-shadow: var(--shadow-md);
  animation: popover-in var(--dur-base) var(--ease-out);
  transform-origin: bottom;
}

.command-list {
  max-height: min(420px, calc(100vh - 240px));
  overflow-y: auto;
  padding: var(--space-2);
}

.command-group + .command-group {
  margin-top: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid color-mix(in srgb, var(--text) 8%, transparent);
}

.command-group-label {
  padding: 0 var(--space-2) var(--space-1);
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .08em;
}

.command-item {
  position: relative;
  display: grid;
  grid-template-columns: var(--space-6) minmax(0, 1fr) auto;
  gap: var(--space-2);
  align-items: center;
  width: 100%;
  min-height: 48px;
  border: 0;
  border-radius: 0;
  padding: var(--space-2);
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: default;
}

.command-item::before {
  content: '';
  position: absolute;
  inset: 0;
  background: transparent;
  pointer-events: none;
  -webkit-mask-image: linear-gradient(to right, rgba(0, 0, 0, .2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0, 0, 0, .2) 100%);
  mask-image: linear-gradient(to right, rgba(0, 0, 0, .2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0, 0, 0, .2) 100%);
}

.command-item:hover::before {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}

.command-item.active::before {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.command-icon {
  position: relative;
  display: grid;
  place-items: center;
  width: var(--space-6);
  height: var(--space-6);
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--text) 4%, transparent);
  color: color-mix(in srgb, var(--text) 72%, transparent);
}

.command-copy {
  position: relative;
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
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 650;
}

.command-copy small {
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 11px;
  line-height: 1.25;
}

.command-source {
  position: relative;
  max-width: 120px;
  overflow: hidden;
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.command-footer {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: center;
  border-top: 1px solid color-mix(in srgb, var(--text) 8%, transparent);
  padding: var(--space-1) var(--space-3) var(--space-2);
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: 10px;
}

.command-footer span {
  display: inline-flex;
  gap: var(--space-1);
  align-items: center;
}

.command-footer kbd {
  min-width: 20px;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  padding: 1px var(--space-1);
  background: color-mix(in srgb, var(--text) 4%, transparent);
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font: inherit;
  line-height: 1.25;
  text-align: center;
}

@media (max-width: 560px) {
  .command-palette {
    width: 100%;
  }

  .command-source {
    display: none;
  }

  .command-item {
    grid-template-columns: var(--space-6) minmax(0, 1fr);
  }
}

@media (prefers-reduced-motion: reduce) {
  .command-palette {
    animation: none;
  }
}
</style>
