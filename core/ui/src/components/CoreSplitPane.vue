<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { BookOpen, Bot, FileImage, FileText, FolderTree, Globe, MessageCircle, Puzzle, Plus, X } from 'lucide-vue-next'
import { t } from '@/i18n'
import type { SplitPane, SplitTab } from '@/split/layout'
const props = defineProps<{ pane: SplitPane; active: boolean; dirty?: Set<string> }>()
const emit = defineEmits<{ focus: []; activate: [id: string]; open: [event: MouseEvent]; menu: [event: MouseEvent]; 'split-pull': [event: PointerEvent]; 'close-pane': []; close: [tab: SplitTab]; tabMenu: [event: MouseEvent, tab: SplitTab]; drag: [event: DragEvent, tab: SplitTab] }>()
const strip = ref<HTMLElement | null>(null)
// user:“样式优化：动画、交互体验、圆角策略等”+(活动标签始终可见，滚轮只在标签栏可继续滚动时接管)。
function revealSelected() {
  const list = strip.value, tab = list?.querySelector<HTMLElement>('[aria-selected="true"]')?.parentElement
  if (!list || !tab) return
  const left = tab.offsetLeft, right = left + tab.offsetWidth
  const target = left < list.scrollLeft ? left : right > list.scrollLeft + list.clientWidth ? right - list.clientWidth : list.scrollLeft
  if (target !== list.scrollLeft) list.scrollTo?.({ left: target, behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' })
}
watch(() => [props.pane.activeTab, props.pane.tabs.length], revealSelected, { flush: 'post' })
let observer: ResizeObserver | undefined
onMounted(() => {
  revealSelected()
  if (typeof ResizeObserver !== 'undefined' && strip.value) { observer = new ResizeObserver(revealSelected); observer.observe(strip.value) }
})
onBeforeUnmount(() => observer?.disconnect())
function scrollTabs(event: WheelEvent) {
  const list = strip.value
  if (!list || event.ctrlKey || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return
  const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? list.clientWidth : 1)
  const next = Math.max(0, Math.min(list.scrollWidth - list.clientWidth, list.scrollLeft + delta))
  if (next !== list.scrollLeft) { event.preventDefault(); list.scrollLeft = next }
}
const icons = { page: BookOpen, agent: Bot, editor: FileText, preview: FileImage, files: FolderTree, browser: Globe, conversation: MessageCircle, plugin: Puzzle }
function navigate(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  const buttons = Array.from((event.currentTarget as HTMLElement).querySelectorAll<HTMLButtonElement>('[role="tab"]'))
  const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length
  event.preventDefault(); buttons[next]?.focus(); buttons[next]?.click()
}
</script>
<template>
  <!-- user:“主区无需标签”+(此标签栏仅用于辅助分屏，主区仍由原有标题栏承载)。 -->
  <header class="split-pane-bar" :class="{ 'is-active': active }" @pointerdown.stop="emit('focus')" @focusin="emit('focus')" @contextmenu.prevent="emit('menu', $event)">
    <div ref="strip" class="split-pane-tabs" role="tablist" :aria-label="t('分屏标签')" @keydown="navigate" @wheel="scrollTabs">
      <div v-for="tab in pane.tabs" :key="tab.id" class="split-pane-tab" :class="{ 'is-selected': tab.id === pane.activeTab }" draggable="true" @auxclick.middle.prevent="emit('close', tab)" @mousedown.middle.prevent @dragstart="emit('drag', $event, tab)" @contextmenu.stop.prevent="emit('tabMenu', $event, tab)">
        <button :id="`split-tab-${tab.id}`" type="button" role="tab" :aria-selected="tab.id === pane.activeTab" :aria-controls="`split-content-${tab.id}`" :tabindex="tab.id === pane.activeTab ? 0 : -1" :title="tab.title" @click="emit('activate', tab.id)">
          <component :is="icons[tab.kind]" :size="13" :stroke-width="1.6" aria-hidden="true" />
          <span>{{ tab.title }}</span>
          <span v-if="dirty?.has(tab.id)" class="split-unsaved" :aria-label="t('未保存')"></span>
        </button>
        <button class="split-tab-close" type="button" :title="t('关闭标签')" :aria-label="t('关闭 {0}', { 0: tab.title })" @click="emit('close', tab)"><X :size="11" aria-hidden="true" /></button>
      </div>
      <span v-if="!pane.tabs.length" class="split-empty-label">{{ t('分屏') }}</span>
    </div>
    <!-- user:“分屏的右上角，只需要留一个加号来新增标签页即可，一个 x 来关闭此分屏，不需要再有一个分屏键了”+(辅助屏头部只保留加号与关闭；拆分改由角部单层角铁拖出)。 -->
    <button type="button" class="split-icon-button" :title="t('打开内容')" :aria-label="t('打开内容')" @click="emit('open', $event)"><Plus :size="15" aria-hidden="true" /></button>
    <button type="button" class="split-icon-button split-pane-close" :title="t('关闭分屏')" :aria-label="t('关闭分屏')" @click="emit('close-pane')"><X :size="14" aria-hidden="true" /></button>
    <span class="split-corner-grip split-corner-grip--top-left" :title="t('拖动角新建分屏')" aria-hidden="true" @pointerdown.prevent="emit('split-pull', $event)"></span>
  </header>
</template>
