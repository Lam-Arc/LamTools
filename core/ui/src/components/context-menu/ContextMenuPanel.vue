<template>
  <div
    ref="panelRef"
    class="context-menu-panel optical-glass optical-glass--low-trans"
    role="menu"
    tabindex="-1"
    :aria-label="defaultUiText(ariaLabel, '上下文菜单')"
    :data-context-menu-panel="pathKey"
    :data-context-menu-level="level"
    :data-placement="placement"
    :style="panelStyle"
    v-bind="panelAttributes"
    @pointerdown.stop
    @click.stop
    @contextmenu.prevent.stop
  >
    <div class="context-menu-panel-content">
      <template v-for="run in itemRuns" :key="run.key">
        <div class="context-menu-run" :class="{ 'context-menu-run--group': run.group }">
          <button
            v-if="run.group"
            type="button"
            class="context-menu-group-head"
            role="menuitemcheckbox"
            :aria-checked="!isGroupCollapsed(run.group)"
            :tabindex="0"
            @click="toggleMenuGroup(run.group)"
            @keydown.enter.prevent="toggleMenuGroup(run.group)"
            @keydown.space.prevent="toggleMenuGroup(run.group)"
          >
            <ChevronDown
              class="context-menu-group-chevron"
              :class="{ 'is-open': !isGroupCollapsed(run.group) }"
              :size="14"
              :stroke-width="1.8"
              aria-hidden="true"
            />
            <span>{{ run.group.label }}</span>
          </button>
          <div
            class="context-menu-group-body"
            :class="{ 'is-collapsed': run.group !== null && isGroupCollapsed(run.group) }"
            :aria-hidden="run.group !== null && isGroupCollapsed(run.group) ? 'true' : undefined"
            :inert="run.group !== null && isGroupCollapsed(run.group) || undefined"
          >
            <div class="context-menu-group-rows">
              <template
                v-for="{ entry, index } in run.entries"
                :key="entry.id || `${pathKey}-${index}`"
              >
                <div v-if="entry.type === 'separator'" class="context-menu-separator" role="separator" />
                <div v-else-if="entry.type === 'label'" class="context-menu-label" role="presentation">{{ entry.label }}</div>
                <ContextMenuItem
                  v-else-if="entry.type !== 'submenu'"
                  :entry="entry"
                  :focused="focusedIndex === index"
                  :tabindex="focusedIndex === index ? 0 : -1"
                  :data-index="index"
                  @mounted="setItemRef(index, $event)"
                  @activate="activate(index)"
                  @pointer-enter="focusItem(index, true)"
                  @focus="focusItem(index, false)"
                  @keydown="handleKeydown(index, $event)"
                />
                <ContextMenuSubmenu
                  v-else
                  :entry="entry"
                  :focused="focusedIndex === index"
                  :expanded="isSubmenuExpanded(index)"
                  :tabindex="focusedIndex === index ? 0 : -1"
                  :data-index="index"
                  @mounted="setItemRef(index, $event)"
                  @activate="activate(index)"
                  @pointer-enter="focusItem(index, true)"
                  @focus="focusItem(index, false)"
                  @keydown="handleKeydown(index, $event)"
                />
              </template>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { defaultUiText } from '../../i18n/index'

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronDown } from 'lucide-vue-next'
import ContextMenuItem from './ContextMenuItem.vue'
import ContextMenuSubmenu from './ContextMenuSubmenu.vue'
import {
  isMenuGroupCollapsed,
  setMenuGroupCollapsed,
} from './context-menu'
import type {
  ContextMenuAnchor,
  ContextMenuAttributes,
  ContextMenuEntry,
  ContextMenuGroupMeta,
} from './types'

const props = withDefaults(defineProps<{
  items: ContextMenuEntry[]
  anchor: ContextMenuAnchor
  level: number
  path: number[]
  ariaLabel?: string
  panelAttributes?: ContextMenuAttributes
  expandedPath?: number[]
}>(), {
  ariaLabel: '上下文菜单',
  panelAttributes: undefined,
  expandedPath: () => [],
})

const emit = defineEmits<{
  activate: [index: number]
  'open-submenu': [index: number, anchor: ContextMenuAnchor]
  'close-submenus': []
  'close-submenu': []
  close: []
}>()

const panelRef = ref<HTMLDivElement | null>(null)
const itemRefs = ref<Array<HTMLButtonElement | null>>([])
const focusedIndex = ref<number | null>(null)
const position = ref({ left: 0, top: 0 })
const placement = ref<'down' | 'up' | 'right' | 'left'>('down')

const pathKey = computed(() => props.path.length ? props.path.join('.') : 'root')
const panelStyle = computed(() => ({
  left: `${Math.round(position.value.left)}px`,
  top: `${Math.round(position.value.top)}px`,
}))

// ── 语义分组：把携带同一 group 元数据且相邻的条目收进一个可折叠组。──
// 分组只是视图结构：条目的扁平下标不变，键盘导航 / 激活 / 子菜单路径都按
// 原下标工作。没带 group 的条目（含分隔线）自成一段，不参与任何组。
interface ItemRun {
  key: string
  group: ContextMenuGroupMeta | null
  entries: Array<{ entry: ContextMenuEntry; index: number }>
}

function entryGroup(entry: ContextMenuEntry): ContextMenuGroupMeta | null {
  if (!entry || entry.type === 'separator' || entry.type === 'label') return null
  const group = (entry as { group?: ContextMenuGroupMeta }).group
  return group && group.id ? group : null
}

const itemRuns = computed<ItemRun[]>(() => {
  const runs: ItemRun[] = []
  let current: ItemRun | null = null
  props.items.forEach((entry, index) => {
    const group = entryGroup(entry)
    // 相邻同组条目并入同一段；没带 group 的条目（含分隔线、标签）并入当前段，
    // 没有当前段就新起一段——整份无组菜单保持原来的兄弟结构，不拆散选择器
    // 依赖的行序（nth-last-of-type 等）。
    if (current && (group ? current.group?.id === group.id : current.group === null)) {
      current.entries.push({ entry, index })
      return
    }
    current = group
      ? { key: `${group.id}:${index}`, group, entries: [{ entry, index }] }
      : { key: `bare:${index}`, group: null, entries: [{ entry, index }] }
    runs.push(current)
  })
  return runs
})

const indexGroups = computed(() => {
  const map = new Map<number, ContextMenuGroupMeta>()
  for (const run of itemRuns.value) {
    if (!run.group) continue
    for (const { index } of run.entries) map.set(index, run.group)
  }
  return map
})

function isGroupCollapsed(group: ContextMenuGroupMeta): boolean {
  return isMenuGroupCollapsed(group.id, group.defaultCollapsed === true)
}

function toggleMenuGroup(group: ContextMenuGroupMeta): void {
  setMenuGroupCollapsed(group.id, !isGroupCollapsed(group))
  // 组体高度要变：先收起挂着的子菜单，等折叠动画铺开后再校一次定位。
  emit('close-submenus')
  if (focusedIndex.value !== null && indexGroups.value.get(focusedIndex.value)?.id === group.id) {
    focusIndex(null)
  }
  void nextTick(positionPanel)
}

function isNavigable(index: number): boolean {
  const entry = props.items[index]
  if (!entry || entry.type === 'separator' || entry.type === 'label') return false
  if (entry.type === 'submenu'
    ? entry.disabled || entry.children.length === 0
    : entry.disabled) return false
  const group = indexGroups.value.get(index)
  if (group && isGroupCollapsed(group)) return false
  return true
}

function firstNavigableIndex(): number | null {
  const index = props.items.findIndex((_entry, candidate) => isNavigable(candidate))
  return index >= 0 ? index : null
}

function setItemRef(index: number, element: unknown): void {
  itemRefs.value[index] = element && element instanceof HTMLButtonElement ? element : null
}

function focusIndex(index: number | null): void {
  focusedIndex.value = index
  if (index === null) {
    panelRef.value?.focus({ preventScroll: true })
    return
  }
  void nextTick(() => itemRefs.value[index]?.focus({ preventScroll: true }))
}

function focusItem(index: number, fromPointer: boolean): void {
  if (!isNavigable(index)) return
  focusedIndex.value = index
  const entry = props.items[index]
  if (entry.type === 'submenu') {
    if (fromPointer) itemRefs.value[index]?.focus({ preventScroll: true })
    emit('open-submenu', index, anchorForItem(index))
  } else {
    emit('close-submenus')
  }
}

function anchorForItem(index: number): ContextMenuAnchor {
  const rect = itemRefs.value[index]?.getBoundingClientRect()
  if (!rect) return { type: 'rect', left: 0, right: 0, top: 0, bottom: 0 }
  return { type: 'rect', left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom }
}

function isSubmenuExpanded(index: number): boolean {
  return props.expandedPath?.length === props.path.length + 1
    && props.expandedPath[props.expandedPath.length - 1] === index
}

function activate(index: number): void {
  if (!isNavigable(index)) return
  const entry = props.items[index]
  if (entry.type === 'submenu') {
    emit('open-submenu', index, anchorForItem(index))
    return
  }
  emit('activate', index)
}

function moveFocus(direction: 1 | -1): void {
  const start = focusedIndex.value ?? (direction > 0 ? -1 : props.items.length)
  for (let offset = 1; offset <= props.items.length; offset += 1) {
    const index = (start + direction * offset + props.items.length) % props.items.length
    if (isNavigable(index)) {
      focusIndex(index)
      const entry = props.items[index]
      if (entry.type === 'submenu') emit('open-submenu', index, anchorForItem(index))
      else emit('close-submenus')
      return
    }
  }
}

function handleKeydown(index: number, event: KeyboardEvent): void {
  switch (event.key) {
    case 'ArrowDown':
      event.preventDefault()
      moveFocus(1)
      break
    case 'ArrowUp':
      event.preventDefault()
      moveFocus(-1)
      break
    case 'Home':
      event.preventDefault()
      focusIndex(firstNavigableIndex())
      break
    case 'End': {
      event.preventDefault()
      const last = [...props.items].map((_entry, candidate) => candidate).reverse().find((candidate) => isNavigable(candidate))
      focusIndex(last === undefined ? null : last)
      break
    }
    case 'Enter':
    case ' ':
      event.preventDefault()
      activate(index)
      break
    case 'ArrowRight':
      if (props.items[index]?.type === 'submenu') {
        event.preventDefault()
        activate(index)
      }
      break
    case 'ArrowLeft':
      if (props.level > 0) {
        event.preventDefault()
        emit('close-submenu')
      }
      break
    case 'Escape':
      event.preventDefault()
      event.stopPropagation()
      emit('close')
      break
    case 'Tab':
      event.preventDefault()
      emit('close')
      break
  }
}

function positionPanel(): void {
  const panel = panelRef.value
  if (!panel || typeof window === 'undefined') return
  const rect = panel.getBoundingClientRect()
  const viewportWidth = Math.max(window.innerWidth || 0, document.documentElement?.clientWidth || 0)
  const viewportHeight = Math.max(window.innerHeight || 0, document.documentElement?.clientHeight || 0)
  if (!viewportWidth || !viewportHeight) return

  const margin = 8
  const gap = 4
  const width = rect.width
  const height = rect.height
  let left = props.anchor.type === 'point' ? props.anchor.x : props.anchor.right + gap
  let top = props.anchor.type === 'point' ? props.anchor.y : props.anchor.top
  placement.value = props.level === 0 ? 'down' : 'right'

  if (props.level > 0 && left + width + margin > viewportWidth) {
    left = props.anchor.type === 'rect' ? props.anchor.left - width - gap : left - width
    placement.value = 'left'
  } else if (props.level === 0 && left + width + margin > viewportWidth) {
    left = props.anchor.type === 'point' ? props.anchor.x - width : left - width
  }

  if (top + height + margin > viewportHeight) {
    top = props.anchor.type === 'point'
      ? props.anchor.y - height
      : props.anchor.bottom - height
    if (props.level === 0) placement.value = 'up'
  }

  const maxLeft = Math.max(margin, viewportWidth - width - margin)
  const maxTop = Math.max(margin, viewportHeight - height - margin)
  position.value = {
    left: Math.min(Math.max(left, margin), maxLeft),
    top: Math.min(Math.max(top, margin), maxTop),
  }
}

onMounted(() => {
  focusedIndex.value = firstNavigableIndex()
  void nextTick(() => {
    positionPanel()
    focusIndex(focusedIndex.value)
    // 定位必须用稳定后的真实尺寸：首帧布局、字体替换、条目渲染都会让
    // 挂载时量到的高度偏小，而定位按量到的高度钳制——偏小就压不住底边。
    // 因此下一帧再校一次，并挂尺寸观察：之后任何高度变化（组折叠、
    // 字体就绪、条目增减）都立即重定位，面板任何时刻都不得超出窗口。
    if (typeof requestAnimationFrame === 'function') {
      repositionFrame = requestAnimationFrame(() => {
        repositionFrame = 0
        positionPanel()
      })
    }
    if (typeof ResizeObserver !== 'undefined' && panelRef.value) {
      contentObserver = new ResizeObserver(() => scheduleReposition())
      contentObserver.observe(panelRef.value)
    }
  })
})

// ── 尺寸稳定后的重定位 ──
let contentObserver: ResizeObserver | null = null
let repositionFrame = 0

function scheduleReposition(): void {
  if (typeof requestAnimationFrame !== 'function') {
    positionPanel()
    return
  }
  if (repositionFrame) return
  repositionFrame = requestAnimationFrame(() => {
    repositionFrame = 0
    positionPanel()
  })
}

onBeforeUnmount(() => {
  contentObserver?.disconnect()
  contentObserver = null
  if (repositionFrame && typeof cancelAnimationFrame === 'function') {
    cancelAnimationFrame(repositionFrame)
  }
  repositionFrame = 0
})

watch(() => props.anchor, () => void nextTick(positionPanel), { deep: true })
watch(() => props.items, () => {
  const next = focusedIndex.value !== null && isNavigable(focusedIndex.value)
    ? focusedIndex.value
    : firstNavigableIndex()
  focusedIndex.value = next
  void nextTick(positionPanel)
}, { deep: false })

defineExpose({
  panel: panelRef,
  reposition: positionPanel,
})
</script>

<style>
.context-menu-panel {
  --text: var(--theme-main-text);
  position: fixed;
  z-index: var(--z-popover, 60);
  box-sizing: border-box;
  width: max-content;
  min-width: 200px;
  max-width: min(280px, calc(100vw - var(--space-4)));
  max-height: calc(100dvh - var(--space-4));
  overflow: hidden;
  padding: 0;
  border-radius: var(--radius);
  color: var(--text);
  pointer-events: auto;
}

.context-menu-panel-content {
  position: relative;
  z-index: 1;
  box-sizing: border-box;
  max-height: inherit;
  overflow-y: auto;
  padding: var(--space-1);
  animation: popover-in var(--dur-base) var(--ease-out);
}

.context-menu-item {
  position: relative;
  z-index: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-height: var(--space-6);
  box-sizing: border-box;
  padding: 0 var(--space-2);
  border: 0;
  border-radius: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 13px;
  line-height: 1.2;
  text-align: left;
  cursor: pointer;
}

.context-menu-item::before {
  content: '';
  position: absolute;
  z-index: -1;
  inset: 0;
  pointer-events: none;
  background: transparent;
  -webkit-mask-image: linear-gradient(to right, rgba(0, 0, 0, .2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0, 0, 0, .2) 100%);
  mask-image: linear-gradient(to right, rgba(0, 0, 0, .2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0, 0, 0, .2) 100%);
}

.context-menu-item:hover:not(:disabled)::before,
.context-menu-item:focus-visible:not(:disabled)::before {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}

.context-menu-item:active:not(:disabled)::before {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

/* 菜单的聚焦指示由行高亮承担（与 hover 同配方）。菜单打开即把焦点交给第一项，
   再叠一层焦点环会让鼠标打开的菜单看起来像有选中态。 */
.context-menu-item:focus-visible {
  outline: none;
}

.context-menu-item:disabled {
  opacity: .45;
  cursor: default;
}

.context-menu-item.is-destructive {
  color: var(--red);
}

.context-menu-item.is-destructive:hover:not(:disabled)::before,
.context-menu-item.is-destructive:focus-visible:not(:disabled)::before {
  background: color-mix(in srgb, var(--red) var(--alpha-hover), transparent);
}

.context-menu-item-main {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
}

.context-menu-item-main > span:last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 两行条目：标签 + 小字说明（模式切换等）。 */
.context-menu-item-text {
  display: grid;
  gap: 1px;
  min-width: 0;
}

.context-menu-item-text > span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.context-menu-item-description {
  font-size: 11.5px;
  line-height: 1.4;
  color: color-mix(in srgb, var(--text) 56%, transparent);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.context-menu-item-icon,
.context-menu-submenu-chevron {
  flex: 0 0 auto;
}

.context-menu-item-shortcut,
.context-menu-submenu-chevron {
  margin-left: var(--space-4);
  color: color-mix(in srgb, var(--text) 56%, transparent);
  font-size: 12px;
}

/* 行右侧的选中对号：全文字色，与左侧图标区分开。 */
.context-menu-item-check {
  display: inline-flex;
  flex: 0 0 auto;
  margin-left: var(--space-4);
  color: var(--text);
}

.context-menu-separator {
  height: 1px;
  margin: var(--space-1) var(--space-2);
  background: color-mix(in srgb, var(--text) 10%, transparent);
}

/* ── 语义分组 ──
   组头是披露按钮（menuitemcheckbox）：点击或回车折叠/展开本组。折叠体用
   grid-template-rows 过渡收展，收起后行不可达（导航跳过 + inert）。 */
.context-menu-group-head {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  width: 100%;
  min-height: var(--space-6);
  box-sizing: border-box;
  padding: 0 var(--space-2);
  border: 0;
  background: transparent;
  color: color-mix(in srgb, var(--text) 56%, transparent);
  font: inherit;
  font-size: 12px;
  font-weight: 560;
  letter-spacing: .02em;
  text-align: left;
  cursor: pointer;
}

.context-menu-group-head:hover,
.context-menu-group-head:focus-visible {
  outline: none;
  color: var(--text);
}

.context-menu-group-chevron {
  flex: 0 0 auto;
  transform: rotate(-90deg);
  transition: transform var(--dur-base) var(--ease-out);
}

.context-menu-group-chevron.is-open {
  transform: rotate(0deg);
}

.context-menu-group-body {
  display: grid;
  grid-template-rows: 1fr;
  transition:
    grid-template-rows var(--dur-base) var(--ease-out),
    opacity var(--dur-base) var(--ease-out);
}

.context-menu-group-body > .context-menu-group-rows {
  min-height: 0;
  overflow: hidden;
}

.context-menu-group-body.is-collapsed {
  grid-template-rows: 0fr;
  opacity: 0;
}

/* ── 菜单退场：短淡出，消失与出现同节奏。 ── */
.context-menu-leave-active {
  transition: opacity var(--dur-fast) var(--ease-out);
}

.context-menu-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .context-menu-panel-content {
    animation: none;
  }

  .context-menu-leave-active {
    transition: none;
  }

  .context-menu-group-body,
  .context-menu-group-chevron {
    transition: none;
  }
}

.context-menu-label {
  min-height: var(--space-6);
  display: flex;
  align-items: center;
  padding: 0 var(--space-2);
  color: color-mix(in srgb, var(--text) 56%, transparent);
  font-size: 12px;
  font-weight: 560;
  letter-spacing: .02em;
}

@media (max-width: 640px) {
  .context-menu-panel {
    max-width: calc(100vw - var(--space-6));
    max-height: calc(100dvh - var(--space-6));
  }

  .context-menu-item {
    min-height: 44px;
  }
}
</style>
