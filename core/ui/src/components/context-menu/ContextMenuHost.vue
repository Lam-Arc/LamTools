<template>
  <Teleport to="body">
    <template v-if="contextMenuState.open">
      <ContextMenuPanel
        :items="contextMenuState.items"
        :anchor="rootAnchor"
        :level="0"
        :path="[]"
        :expanded-path="expandedPath"
        :aria-label="contextMenuState.ariaLabel"
        :panel-attributes="contextMenuState.panelAttributes"
        @activate="activate([],$event)"
        @open-submenu="handleRootSubmenu"
        @close-submenus="closeSubmenus(0)"
        @close="closeContextMenu"
      />
      <ContextMenuPanel
        v-for="panel in submenuPanels"
        :key="panel.path.join('.')"
        :items="panel.items"
        :anchor="panel.anchor"
        :level="panel.path.length"
        :path="panel.path"
        :expanded-path="expandedPath"
        :aria-label="panel.ariaLabel"
        :panel-attributes="panel.panelAttributes"
        @activate="activate(panel.path,$event)"
        @open-submenu="(...args) => handlePanelSubmenu(panel.path, ...args)"
        @close-submenus="closeSubmenus(panel.path.length)"
        @close-submenu="closeOneSubmenu(panel.path)"
        @close="closeContextMenu"
      />
    </template>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import ContextMenuPanel from './ContextMenuPanel.vue'
import {
  closeContextMenu,
  contextMenuState,
  installContextMenuGuard,
  installLongPressContextMenu,
  removeContextMenuGuard,
  removeLongPressContextMenu,
} from './context-menu'
import type { ContextMenuAnchor, ContextMenuEntry } from './types'

interface SubmenuPanelState {
  path: number[]
  items: ContextMenuEntry[]
  anchor: ContextMenuAnchor
  ariaLabel: string
  panelAttributes?: Record<string, string | number | boolean | undefined>
}

const rootAnchor = computed<ContextMenuAnchor>(() => ({
  type: 'point',
  x: contextMenuState.x,
  y: contextMenuState.y,
}))
const submenuPanels = ref<SubmenuPanelState[]>([])
const expandedPath = computed(() => submenuPanels.value.at(-1)?.path || [])

onMounted(() => {
  installContextMenuGuard()
  installLongPressContextMenu()
})

watch(() => contextMenuState.revision, () => {
  // `openContextMenu()` can replace an open menu synchronously, so the
  // boolean `open` value may never observe a false -> true transition. The
  // revision is the explicit replacement boundary and prevents an old
  // submenu panel from leaking into the next target's menu.
  submenuPanels.value = []
})

watch(() => contextMenuState.open, (open) => {
  if (!open) submenuPanels.value = []
})

onUnmounted(() => {
  removeLongPressContextMenu()
  removeContextMenuGuard()
  closeContextMenu()
})

function entryAt(path: number[], index: number): ContextMenuEntry | undefined {
  let entries = contextMenuState.items
  for (const pathIndex of path) {
    const entry = entries[pathIndex]
    if (!entry || entry.type !== 'submenu') return undefined
    entries = entry.children
  }
  return entries[index]
}

function openSubmenu(path: number[], index: number, anchor: ContextMenuAnchor): void {
  const entry = entryAt(path, index)
  if (!entry || entry.type !== 'submenu' || entry.disabled || !entry.children.length) return
  const childPath = [...path, index]
  submenuPanels.value = [
    ...submenuPanels.value.filter((panel) => panel.path.length < childPath.length),
    {
      path: childPath,
      items: entry.children,
      anchor,
      ariaLabel: entry.label,
      panelAttributes: entry.panelAttributes,
    },
  ]
}

function handleRootSubmenu(index: number, anchor: ContextMenuAnchor): void {
  openSubmenu([], index, anchor)
}

function handlePanelSubmenu(path: number[], index: number, anchor: ContextMenuAnchor): void {
  openSubmenu(path, index, anchor)
}

function closeSubmenus(level: number): void {
  submenuPanels.value = submenuPanels.value.slice(0, level)
}

function closeOneSubmenu(path: number[]): void {
  submenuPanels.value = submenuPanels.value.slice(0, Math.max(0, path.length - 1))
  const parentPath = path.slice(0, -1)
  const triggerIndex = path.at(-1)
  if (triggerIndex === undefined) return
  void nextTick(() => {
    const key = parentPath.length ? parentPath.join('.') : 'root'
    const trigger = document.querySelector<HTMLElement>(
      `[data-context-menu-panel="${key}"] [data-context-menu-index="${triggerIndex}"]`,
    )
    trigger?.focus({ preventScroll: true })
  })
}

async function activate(path: number[], index: number): Promise<void> {
  const entry = entryAt(path, index)
  if (!entry || entry.type === 'separator' || entry.type === 'label' || entry.disabled) return
  if (entry.type === 'submenu') {
    openSubmenu(path, index, { type: 'rect', left: 0, right: 0, top: 0, bottom: 0 })
    return
  }
  closeContextMenu()
  try {
    await entry.action()
  } catch {
    // Business actions own their error reporting; a rejected action must not
    // leave an invisible menu listener installed or create an unhandled error.
  }
}

</script>
