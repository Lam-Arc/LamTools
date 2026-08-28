<template>
  <aside
    :id="id"
    data-workspace-left-drawer
    class="workspace-drawer drawer-left"
    :class="{ open, pinned }"
    :inert="!open || undefined"
    :aria-hidden="!open"
    @mouseleave="emit('mouseleave', $event)"
  >
    <header class="drawer-head sidebar-header">
      <div class="sidebar-title sidebar-label">{{ title || '项目' }}</div>
      <button
        class="sidebar-pin-button"
        :class="{ 'is-active': pinned }"
        type="button"
        :title="pinned ? '取消固定左侧栏' : '固定左侧栏'"
        :aria-label="pinned ? '取消固定左侧栏' : '固定左侧栏'"
        :aria-pressed="pinned"
        @click="togglePinned"
      >
        <Pin :size="14" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <div class="sidebar-header-actions">
        <slot name="sidebar-header-action">
          <slot name="header-actions">
            <button class="icon-btn" type="button" title="新建" aria-label="新建会话" @click="emit('new-session')">+</button>
          </slot>
        </slot>
      </div>
    </header>

    <div v-if="$slots.primary || $slots['sidebar-primary']" class="sidebar-primary">
      <slot name="primary">
        <slot name="sidebar-primary" />
      </slot>
    </div>

    <div class="drawer-body">
      <slot name="sidebar-body">
        <slot>
          <div class="sidebar-empty">No content</div>
        </slot>
      </slot>
    </div>

    <footer class="drawer-footer">
      <button class="settings-entry" type="button" aria-label="打开搜索" @click="emit('search')">
        <span aria-hidden="true"><Search :size="14" :stroke-width="1.8" /></span>
        <span>搜索</span>
      </button>
      <button class="settings-entry" type="button" aria-label="打开插件" @click="emit('plugins')">
        <span aria-hidden="true"><Puzzle :size="14" :stroke-width="1.8" /></span>
        <span>插件</span>
      </button>
      <button class="settings-entry" type="button" aria-label="打开设置" @click="emit('settings')">
        <span aria-hidden="true"><Command :size="14" :stroke-width="1.8" /></span>
        <span>设置</span>
      </button>
      <slot name="sidebar-footer">
        <slot name="footer" />
      </slot>
    </footer>
  </aside>
</template>

<script setup lang="ts">
import { Command, Pin, Puzzle, Search } from 'lucide-vue-next'

withDefaults(
  defineProps<{
    id: string
    open: boolean
    pinned: boolean
    title?: string
  }>(),
  {
    title: '',
  },
)

const emit = defineEmits<{
  close: []
  'toggle-pinned': []
  'new-session': []
  settings: []
  plugins: []
  search: []
  mouseleave: [event: MouseEvent]
}>()

// Keep these host commands available for a future in-drawer close/pin
// control without moving ownership of layout state out of useShellLayout.
function close() {
  emit('close')
}

function togglePinned() {
  emit('toggle-pinned')
}

defineExpose({ close, togglePinned })
</script>

<style scoped>
.sidebar-label {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 650;
  color: var(--theme-backdrop-text);
  opacity: 0.8;
  letter-spacing: -0.02em;
}

.sidebar-title {
  font-size: 14px;
  font-weight: 600;
}

.sidebar-header-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
}

.sidebar-pin-button {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--theme-backdrop-text);
  opacity: 0.55;
  display: grid;
  place-items: center;
  transition: opacity var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}

.sidebar-pin-button:hover,
.sidebar-pin-button:focus-visible,
.sidebar-pin-button.is-active {
  opacity: 1;
}

.sidebar-pin-button:hover {
  background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent);
}

.sidebar-pin-button:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--blue) 75%, transparent);
  outline-offset: 1px;
}

.icon-btn {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent);
  color: color-mix(in srgb, var(--theme-backdrop-text) 56%, transparent);
  display: grid;
  place-items: center;
  font-size: 18px;
  font-weight: 700;
}

.icon-btn:hover {
  background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-active), transparent);
  color: var(--theme-backdrop-text);
}

@media (prefers-reduced-motion: reduce) {
  .sidebar-pin-button {
    transition: none;
  }
}
</style>
