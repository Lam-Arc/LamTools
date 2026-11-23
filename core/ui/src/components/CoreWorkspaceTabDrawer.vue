<script setup lang="ts">
/**
 * user:“agent 界面下分屏键替换后标签抽屉 / 无需搜索，标签页抽屉需要你自行设计实现 / 替换掉右上角的分屏键”+
 * (替换右上角原分屏键为统一工作区标签页抽屉：汇总分屏区标签、浮层与已收起窗口，支持一键切换、浮起/固定/恢复/关闭与新建网页)。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Columns2, FileText, Globe, Layers, PanelRightOpen, PictureInPicture2, Plus, RotateCcw, X } from 'lucide-vue-next'
import { t } from '@/i18n'
import { openOverlay } from '@/split/browserOverlays'
import type { SplitTab } from '@/workspace/types'
import type { WorkspaceController } from '@/workspace/useWorkspace'

const props = defineProps<{
  controller: WorkspaceController
}>()

const open = ref(false)
const rootRef = ref<HTMLElement | null>(null)
let releaseOverlay: (() => void) | null = null

interface DrawerItem {
  id: string
  tab: SplitTab
  location: 'main' | 'split' | 'float' | 'parked'
  paneId?: string
  active: boolean
}

const items = computed<DrawerItem[]>(() => {
  const list: DrawerItem[] = []
  for (const areaEntry of props.controller.areas.value) {
    const isMain = areaEntry.area.role === 'main'
    for (const tab of areaEntry.tabs) {
      if (tab.kind === 'agent') continue
      list.push({
        id: tab.id,
        tab,
        location: isMain ? 'main' : 'split',
        paneId: areaEntry.area.id,
        active: areaEntry.area.active === tab.id,
      })
    }
  }
  for (const floatEntry of props.controller.floats.value) {
    list.push({
      id: floatEntry.tab.id,
      tab: floatEntry.tab,
      location: 'float',
      active: props.controller.floatFocus.value === floatEntry.tab.id,
    })
  }
  for (const parked of props.controller.parkedFloats.value) {
    list.push({
      id: parked.id,
      tab: parked,
      location: 'parked',
      active: false,
    })
  }
  return list
})

const splitPaneCount = computed(() => props.controller.areas.value.filter(entry => entry.area.role !== 'main').length)
const totalCount = computed(() => items.value.length)

function locationLabel(loc: DrawerItem['location']): string {
  if (loc === 'main') return t('标签页')
  if (loc === 'split') return t('分屏')
  if (loc === 'float') return t('浮层')
  return t('已收起')
}

function itemTitle(tab: SplitTab): string {
  return tab.title || tab.resource || t('新标签')
}

function closeDrawer() {
  open.value = false
}

function toggleDrawer() {
  open.value = !open.value
}

function activateItem(item: DrawerItem) {
  if (item.location === 'parked') {
    props.controller.reviveFloat(item.id)
  } else if (item.location === 'float') {
    props.controller.focusFloat(item.id)
  } else if (item.paneId) {
    props.controller.show(item.paneId)
    props.controller.activate(item.paneId, item.id)
  }
  closeDrawer()
}

function pinFromDrawer(id: string) {
  props.controller.pinCommit(id)
  closeDrawer()
}

function floatFromDrawer(id: string) {
  props.controller.setSurfaceMode(id, 'float')
  closeDrawer()
}

function closeItem(item: DrawerItem) {
  if (item.location === 'float') {
    props.controller.collapseFloat(item.id)
    return
  }
  if (item.location === 'parked') {
    // user:“快速精准高效的解决”+(删除收起的内容也经过关闭保护并清理存档)。
    props.controller.closeTab('parked', item.tab)
    return
  }
  if (item.paneId) {
    props.controller.closeTab(item.paneId, item.tab)
  }
}

function openNewBrowserFloat() {
  props.controller.openFloat('browser', '', t('新标签'))
  closeDrawer()
}

function openRightSplit() {
  const pane = props.controller.split('main', 'right')
  if (pane) props.controller.add('browser', '', t('新标签'), pane)
  closeDrawer()
}

function toggleWorkspaceVisibility() {
  props.controller.toggle()
}

function onOutsidePointerDown(event: PointerEvent) {
  if (!open.value) return
  const target = event.target as Node | null
  if (target && rootRef.value?.contains(target)) return
  closeDrawer()
}

function onKeydown(event: KeyboardEvent) {
  if (open.value && event.key === 'Escape') {
    event.stopPropagation()
    closeDrawer()
  }
}

watch(open, value => {
  if (value) {
    if (!releaseOverlay) releaseOverlay = openOverlay('tab-drawer')
  } else {
    releaseOverlay?.()
    releaseOverlay = null
  }
})

onMounted(() => {
  window.addEventListener('pointerdown', onOutsidePointerDown, true)
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('pointerdown', onOutsidePointerDown, true)
  window.removeEventListener('keydown', onKeydown)
  releaseOverlay?.()
  releaseOverlay = null
})
</script>

<template>
  <div ref="rootRef" class="ws2-tab-drawer-anchor">
    <button
      class="window-control-button ws2-tab-drawer-trigger"
      type="button"
      data-ws2-tab-drawer-trigger
      :title="t('标签页抽屉')"
      :aria-label="t('标签页抽屉')"
      :aria-expanded="open"
      aria-haspopup="dialog"
      @click.stop="toggleDrawer"
    >
      <Layers aria-hidden="true" />
    </button>

    <div
      v-if="open"
      class="ws2-tab-drawer"
      data-ws2-tab-drawer
      role="dialog"
      :aria-label="t('标签页抽屉')"
    >
      <div class="ws2-tab-drawer__head">
        <span class="ws2-tab-drawer__title">{{ t('标签页') }}</span>
        <span class="ws2-tab-drawer__count">{{ totalCount }}</span>
        <div class="ws2-tab-drawer__head-actions">
          <button
            class="ws2-tab-drawer__chip"
            type="button"
            data-ws2-drawer-new-float
            :title="t('打开网页浮层')"
            @click="openNewBrowserFloat"
          >
            <Plus :size="12" aria-hidden="true" />
            <span>{{ t('浮层') }}</span>
          </button>
          <button
            v-if="props.controller.canSplit('main', 'right')"
            class="ws2-tab-drawer__chip"
            type="button"
            data-ws2-drawer-new-split
            :title="t('在右侧新建分屏')"
            @click="openRightSplit"
          >
            <Columns2 :size="12" aria-hidden="true" />
            <span>{{ t('分屏') }}</span>
          </button>
        </div>
      </div>

      <div v-if="items.length" class="ws2-tab-drawer__list">
        <div
          v-for="item in items"
          :key="`${item.location}:${item.id}`"
          class="ws2-tab-drawer__row"
          :class="{ 'is-active': item.active }"
          :data-ws2-drawer-item="item.id"
        >
          <button
            class="ws2-tab-drawer__main"
            type="button"
            @click="activateItem(item)"
          >
            <Globe v-if="item.tab.kind === 'browser'" :size="13" aria-hidden="true" />
            <FileText v-else :size="13" aria-hidden="true" />
            <span class="ws2-tab-drawer__name">{{ itemTitle(item.tab) }}</span>
            <span class="ws2-tab-drawer__tag">{{ locationLabel(item.location) }}</span>
          </button>
          <div class="ws2-tab-drawer__ops">
            <button
              v-if="item.location === 'float'"
              class="ws2-tab-drawer__op"
              type="button"
              :title="t('固定到分屏')"
              :aria-label="t('固定到分屏')"
              @click.stop="pinFromDrawer(item.id)"
            >
              <Columns2 :size="12" aria-hidden="true" />
            </button>
            <button
              v-else-if="item.location !== 'parked'"
              class="ws2-tab-drawer__op"
              type="button"
              :title="t('转为浮层')"
              :aria-label="t('转为浮层')"
              @click.stop="floatFromDrawer(item.id)"
            >
              <PictureInPicture2 :size="12" aria-hidden="true" />
            </button>
            <button
              v-if="item.location === 'parked'"
              class="ws2-tab-drawer__op"
              type="button"
              :title="t('恢复浮层')"
              :aria-label="t('恢复浮层')"
              @click.stop="activateItem(item)"
            >
              <RotateCcw :size="12" aria-hidden="true" />
            </button>
            <button
              class="ws2-tab-drawer__op"
              type="button"
              :title="item.location === 'float' ? t('收起') : t('关闭')"
              :aria-label="item.location === 'float' ? t('收起') : t('关闭')"
              @click.stop="closeItem(item)"
            >
              <X :size="12" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
      <div v-else class="ws2-tab-drawer__empty">
        <span>{{ t('暂无已打开的标签页') }}</span>
      </div>

      <div v-if="splitPaneCount > 0" class="ws2-tab-drawer__foot">
        <button
          class="ws2-tab-drawer__foot-btn"
          type="button"
          data-ws2-drawer-toggle-split
          @click="toggleWorkspaceVisibility"
        >
          <PanelRightOpen :size="13" aria-hidden="true" />
          <span>{{ props.controller.state.hidden ? t('显示分屏') : t('暂存收起分屏') }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ws2-tab-drawer-anchor {
  position: relative;
}

.ws2-tab-drawer {
  position: absolute;
  top: calc(100% + var(--space-1));
  right: 0;
  z-index: var(--z-popover, 600);
  width: min(320px, calc(100vw - var(--window-corner-width, 0px) - var(--space-5)));
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-2);
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius);
  /* user:“层级应为红>绿>黄”+(抽屉表面盖住其下的活网页，文字与操作保持清晰)。 */
  background: var(--theme-main-solid, var(--theme-main-background));
  color: var(--theme-main-text);
  box-shadow: var(--shadow-md);
}

.ws2-tab-drawer__head {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding-inline: var(--space-1);
}

.ws2-tab-drawer__title {
  font-size: 12px;
  font-weight: 600;
}

.ws2-tab-drawer__count {
  font-size: 11px;
  color: color-mix(in srgb, var(--theme-main-text) 55%, transparent);
  margin-right: auto;
  font-variant-numeric: tabular-nums;
}

.ws2-tab-drawer__head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.ws2-tab-drawer__chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 22px;
  padding: 0 var(--space-2);
  border: 0;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover, 8%), transparent);
  color: var(--theme-main-text);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.ws2-tab-drawer__chip:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-active, 12%), transparent);
}

.ws2-tab-drawer__list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: min(46vh, 300px);
  overflow-y: auto;
}

.ws2-tab-drawer__row {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  border-radius: var(--radius-sm);
  padding: 2px var(--space-1);
}

.ws2-tab-drawer__row:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover, 8%), transparent);
}

.ws2-tab-drawer__row.is-active {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-active, 12%), transparent);
}

.ws2-tab-drawer__main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--space-1);
  border: 0;
  background: transparent;
  color: inherit;
  padding: var(--space-1);
  text-align: left;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.ws2-tab-drawer__main svg {
  flex: 0 0 auto;
  opacity: .72;
}

.ws2-tab-drawer__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ws2-tab-drawer__tag {
  flex: 0 0 auto;
  font-size: 10px;
  padding: 0 5px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover, 8%), transparent);
  color: color-mix(in srgb, var(--theme-main-text) 70%, transparent);
}

.ws2-tab-drawer__ops {
  display: flex;
  align-items: center;
  gap: 2px;
  flex: 0 0 auto;
}

.ws2-tab-drawer__op {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 65%, transparent);
  cursor: pointer;
}

.ws2-tab-drawer__op:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-active, 12%), transparent);
  color: var(--theme-main-text);
}

.ws2-tab-drawer__empty {
  padding: var(--space-3) var(--space-2);
  text-align: center;
  font-size: 12px;
  color: color-mix(in srgb, var(--theme-main-text) 52%, transparent);
}

.ws2-tab-drawer__foot {
  border-top: 1px solid color-mix(in srgb, var(--theme-main-text) 8%, transparent);
  padding-top: var(--space-1);
}

.ws2-tab-drawer__foot-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  height: 26px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 78%, transparent);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.ws2-tab-drawer__foot-btn:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover, 8%), transparent);
  color: var(--theme-main-text);
}
</style>
