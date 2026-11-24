<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { Bot, ChevronLeft, ChevronRight, Circle, FileText, Folder, Globe, Image, MessageCircle, Pencil, Plug, X } from 'lucide-vue-next'
import { browserTabIcon } from '@/split/browserIcons'
import { startWindowDragFromBlank } from '@/composables/useWindowDrag.ts'
import type { SplitTab } from '@/workspace/types'

const TAB_WIDTH = { title: 96, icon: 32 }
const tabIcons = {
  agent: Bot,
  browser: Globe,
  page: FileText,
  files: Folder,
  editor: Pencil,
  preview: Image,
  plugin: Plug,
  conversation: MessageCircle,
}

const props = defineProps<{
  areaId: string
  axis: 'vertical' | 'horizontal'
  tabs: SplitTab[]
  activeId: string | null
  compact?: boolean
  allowAdd?: boolean
}>()

const emit = defineEmits<{
  select: [surfaceId: string]
  close: [surfaceId: string]
  add: []
  rename: [surfaceId: string, title: string]
  'tab-pointerdown': [surfaceId: string, event: PointerEvent]
}>()

function onRename(tab: SplitTab) {
  if (typeof window === 'undefined' || typeof window.prompt !== 'function') return
  const next = window.prompt('重命名标签', tab.title)
  if (next && next.trim() && next.trim() !== tab.title) emit('rename', tab.id, next.trim())
}

function onPointerDown(surfaceId: string, event: PointerEvent) {
  // 只在左键上开始拖动；右键留给菜单（菜单由外壳统一登记浮层）。
  if (event.button !== 0) return
  emit('tab-pointerdown', surfaceId, event)
}

const rail = ref<HTMLElement | null>(null)
const viewport = ref<HTMLElement | null>(null)
const viewportId = useId()
const available = ref(Infinity)
const scrolled = ref(0)
const maxScroll = ref(0)
const horizontal = computed(() => props.axis === 'horizontal')
// user:“标签页过多时应该是这样的”+(按分屏内实际可用宽度，依次显示标题、图标、左右翻页键)。
const iconOnly = computed(() => horizontal.value && props.tabs.length * TAB_WIDTH.title > available.value)
const paged = computed(() => iconOnly.value && props.tabs.length * TAB_WIDTH.icon > available.value)
// user:“找出 3 个及以上优化”+(键盘进入标签条只停一次，再用与标签排列方向一致的方向键切换)。
const tabStopId = computed(() => props.tabs.find(tab => tab.id === props.activeId)?.id ?? props.tabs[0]?.id)
let observer: ResizeObserver | undefined

function measure() {
  if (!rail.value || !viewport.value) return
  const width = rail.value.getBoundingClientRect().width
  if (width <= 0) return
  const { paddingLeft, paddingRight } = getComputedStyle(viewport.value)
  available.value = Math.max(0, width - (parseFloat(paddingLeft) || 0) - (parseFloat(paddingRight) || 0))
  readScroll()
}

function readScroll() {
  const view = viewport.value
  if (!view) return
  scrolled.value = view.scrollLeft
  maxScroll.value = Math.max(0, view.scrollWidth - view.clientWidth)
}

function turnPage(direction: -1 | 1) {
  const view = viewport.value
  if (!view) return
  const page = Math.max(1, Math.floor(view.clientWidth / TAB_WIDTH.icon)) * TAB_WIDTH.icon
  view.scrollLeft = Math.max(0, Math.min(maxScroll.value, view.scrollLeft + direction * page))
  readScroll()
}

function revealTab(control: HTMLElement) {
  const view = viewport.value
  if (!view || !paged.value) return
  const tab = (control.closest('.ws2-tab') ?? control).getBoundingClientRect()
  const visible = view.getBoundingClientRect()
  if (tab.left < visible.left) view.scrollLeft += tab.left - visible.left
  else if (tab.right > visible.right) view.scrollLeft += tab.right - visible.right
}

function revealSelected() {
  const selected = viewport.value?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')
  if (selected) revealTab(selected)
  readScroll()
}

function onTabKeydown(event: KeyboardEvent, index: number) {
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
  const count = props.tabs.length
  const previous = horizontal.value ? 'ArrowLeft' : 'ArrowUp'
  const next = horizontal.value ? 'ArrowRight' : 'ArrowDown'
  let target: number
  if (event.key === previous) target = (index + count - 1) % count
  else if (event.key === next) target = (index + 1) % count
  else if (event.key === 'Home') target = 0
  else if (event.key === 'End') target = count - 1
  else return
  event.preventDefault()
  event.stopPropagation()
  const control = viewport.value?.querySelectorAll<HTMLElement>('[role="tab"]')[target]
  if (control) {
    control.focus({ preventScroll: true })
    revealTab(control)
  }
  if (props.tabs[target].id !== props.activeId) emit('select', props.tabs[target].id)
}

onMounted(() => {
  measure()
  if (typeof ResizeObserver !== 'undefined' && rail.value) {
    observer = new ResizeObserver(measure)
    observer.observe(rail.value)
  }
})
onBeforeUnmount(() => observer?.disconnect())
const tabIds = computed(() => props.tabs.map(tab => tab.id))
watch([() => props.activeId, tabIds, available, paged], revealSelected, { flush: 'post' })
watch(tabIds, async (ids) => {
  const focused = document.activeElement
  if (!viewport.value?.contains(focused)) return
  const tab = focused?.closest<HTMLElement>('[data-ws2-tab]')
  if (!tab?.dataset.ws2Tab || ids.includes(tab.dataset.ws2Tab)) return
  await nextTick()
  if (document.activeElement !== document.body) return
  viewport.value?.querySelector<HTMLElement>('[role="tab"][tabindex="0"]')?.focus({ preventScroll: true })
})

function favicon(tab: SplitTab) { return tab.kind === 'browser' ? browserTabIcon(tab.id) : undefined }
function tabIcon(tab: SplitTab) { return tabIcons[tab.kind as keyof typeof tabIcons] ?? Circle }
</script>

<template>
  <div
    class="ws2-tabs"
    :class="[`ws2-tabs--${props.axis}`, { 'ws2-tabs--compact': props.compact, 'ws2-tabs--icons': iconOnly }]"
    :style="{ '--ws2-tab-min-width': `${TAB_WIDTH.title}px`, '--ws2-icon-tab-width': `${TAB_WIDTH.icon}px` }"
    :data-ws2-tabbar="props.areaId"
    @pointerdown="startWindowDragFromBlank"
  >
    <div ref="rail" class="ws2-tabs__rail">
      <button
        v-if="paged"
        type="button"
        class="ws2-tab__add ws2-tab__page"
        data-ws2-tab-page="previous"
        aria-label="上一页标签"
        title="上一页标签"
        :aria-controls="viewportId"
        :disabled="scrolled < 1"
        @click="turnPage(-1)"
      ><ChevronLeft :size="14" aria-hidden="true" /></button>
      <div :id="viewportId" ref="viewport" class="ws2-tabs__viewport" @scroll.passive="readScroll">
        <div class="ws2-tabs__items" role="tablist" :aria-orientation="props.axis">
          <div
            v-for="(tab, index) in props.tabs"
            :key="tab.id"
            class="ws2-tab"
            :class="{ 'is-active': tab.id === props.activeId }"
            :data-ws2-tab="tab.id"
            :title="tab.title"
            @pointerdown="onPointerDown(tab.id, $event)"
            @click="emit('select', tab.id)"
            @dblclick.stop="onRename(tab)"
          >
            <!-- user:“选中的那个标签页，显示为 x 键，点击可关闭，其余标签页使用图标”+(紧凑态让关闭键占满选中标签，仍保留标题提示)。 -->
            <button
              type="button"
              class="ws2-tab__select"
              role="tab"
              :aria-selected="tab.id === props.activeId"
              :aria-label="tab.title"
              :tabindex="tab.id === tabStopId ? 0 : -1"
              @keydown="onTabKeydown($event, index)"
            >
              <template v-if="!iconOnly || tab.id !== props.activeId">
                <img v-if="favicon(tab)" class="ws2-tab__icon" :src="favicon(tab)" alt="" draggable="false">
                <component :is="tabIcon(tab)" v-else class="ws2-tab__icon" aria-hidden="true" />
                <span v-if="!iconOnly" class="ws2-tab__title">{{ tab.title }}</span>
              </template>
            </button>
            <button
              v-if="!iconOnly || tab.id === props.activeId"
              class="ws2-tab__close"
              type="button"
              :aria-label="`关闭 ${tab.title}`"
              :tabindex="tab.id === props.activeId ? 0 : -1"
              @pointerdown.stop
              @click.stop="emit('close', tab.id)"
              @dblclick.stop
            ><X :size="14" aria-hidden="true" /></button>
          </div>
        </div>
      </div>
      <button
        v-if="paged"
        type="button"
        class="ws2-tab__add ws2-tab__page"
        data-ws2-tab-page="next"
        aria-label="下一页标签"
        title="下一页标签"
        :aria-controls="viewportId"
        :disabled="maxScroll - scrolled < 1"
        @click="turnPage(1)"
      ><ChevronRight :size="14" aria-hidden="true" /></button>
    </div>
    <button
      v-if="props.allowAdd && horizontal"
      class="ws2-tab__add"
      type="button"
      data-ws2-tab-add
      aria-label="新建标签"
      title="新建标签"
      @click="emit('add')"
    >+</button>
  </div>
</template>
