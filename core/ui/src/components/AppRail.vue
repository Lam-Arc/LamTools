<template>
  <nav class="app-rail" data-app-rail data-ui-id="shell.app-rail" :aria-label="t('主导航')">
    <button
      v-for="item in topItems"
      :key="item.id"
      class="app-rail__button"
      type="button"
      :aria-label="item.label"
      :title="item.label"
      :aria-pressed="props.active === item.id"
      :data-rail-entry="item.id"
      @click="emit('open', item.id)"
      @contextmenu.prevent="openSplitMenu($event, item.id)"
    >
      <component :is="item.icon" :size="20" :stroke-width="item.strokeWidth ?? 1.8" aria-hidden="true" />
    </button>
    <!-- user:“左竖栏多余的插件提供的按钮折叠进一个···，悬浮时再右侧弹一个透明抽屉”
         +(插件导航按钮一个都不常驻：竖栏只保留“···”，悬浮/键盘聚焦时从竖栏右侧弹出低透玻璃抽屉
         列出全部插件页面；条目仍可左键打开、右键选择分屏)。 -->
    <div v-if="pluginPages.length" ref="moreWrap" class="app-rail__more-wrap" data-rail-plugin-more-wrap @mouseenter="openMoreDrawer"
      @mouseleave="scheduleCloseMoreDrawer" @focusin="openMoreDrawer" @focusout="onMoreFocusOut">
      <button
        class="app-rail__button"
        type="button"
        :aria-label="t('更多插件')"
        :title="t('更多插件')"
        :aria-pressed="moreEntryActive"
        aria-haspopup="menu"
        :aria-expanded="moreOpen"
        data-rail-plugin-more
        @click="openMoreDrawer"
      >
        <MoreHorizontal :size="20" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <div
        v-if="moreOpen"
        class="app-rail__more-drawer optical-glass optical-glass--low-trans"
        data-rail-plugin-drawer
        role="menu"
        :aria-label="t('更多插件')"
      >
        <button
          v-for="page in pluginPages"
          :key="`${page.plugin}:${page.id}`"
          type="button"
          role="menuitem"
          class="app-rail__more-item"
          :class="{ active: activePluginPage === `${page.plugin}:${page.id}` }"
          :aria-current="activePluginPage === `${page.plugin}:${page.id}` ? 'page' : undefined"
          :title="page.title"
          :data-rail-plugin-drawer-item="`${page.plugin}:${page.id}`"
          @click="openFoldedPage(page)"
          @contextmenu.prevent="openFoldedSplitMenu($event, page)"
        >
          <Network :size="16" :stroke-width="1.8" aria-hidden="true" />
          <span class="app-rail__more-label">{{ page.title }}</span>
        </button>
      </div>
    </div>
    <span class="app-rail__spacer" aria-hidden="true"></span>
    <!-- 更新入口：只在真有新版本时出现，就在账号上方。它是这里唯一「有事可做」的
         一枚，所以给一层柔和的圆角底座，和上面纯图标的导航区分开。 -->
    <button
      v-if="updateAvailable"
      ref="updateButton"
      class="app-rail__button app-rail__update"
      type="button"
      :aria-label="updateLabel || t('有新版本可用')"
      :title="updateLabel || t('有新版本可用')"
      data-rail-update
      :data-rail-update-action="updateAction || 'download'"
      :data-rail-update-state="updateBusy ? 'busy' : 'ready'"
      @click="emit('update')"
    >
      <component
        :is="updateAction === 'install' ? PackageCheck : Download"
        :size="19"
        :stroke-width="1.9"
        aria-hidden="true"
      />
    </button>
    <button
      class="app-rail__button"
      type="button"
      :aria-label="t('账号')"
      :title="t('账号')"
      :aria-pressed="props.active === 'account'"
      data-rail-entry="account"
      @click="emit('open', 'account')"
      @contextmenu.prevent="openSplitMenu($event, 'account')"
    >
      <UserRound :size="20" :stroke-width="1.8" aria-hidden="true" />
    </button>
  </nav>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

/**
 * AppRail — 最左竖栏（Codex 式整界面导航）。
 *
 * 常驻的窄图标列：主页（回聊天）+ 整版分区（定时任务 / 资料库 / 插件 /
 * 设置），底部账号，账号上方是「有新版本」时的更新入口。记忆不再单开入口
 * ——它在资料库里面。
 *
 * 图标只用最简形状：这里只有 20px，多一个细节就糊一层。并且同一个入口用
 * 同一个图形——「插件」的插头与搜索页一致。点击分区时整个界面切走（会话栏退场），由宿主决定具体
 * 的切换与折叠语义；这里只负责渲染与上报。
 */
import { computed, onBeforeUnmount, ref, watch, type Component } from 'vue'
import { contributionState } from '@/plugins/contributions'
import type { PluginPageEntry } from '@/plugins/pages'
import { openContextMenu } from '@/components/context-menu/context-menu'
import { CalendarClock, Download, House, MoreHorizontal, Network, PackageCheck, Settings, UserRound } from 'lucide-vue-next'
import { BookOne, Receive } from '@icon-park/vue-next'

export type AppRailView = 'chat' | 'arrange' | 'library' | 'plugins' | 'settings' | 'account'

const props = defineProps<{
  /** 当前所处的整界面分区；'chat' 表示在聊天界面。 */
  active?: AppRailView
  activePluginPage?: string
  /** 有新版本可装时出现更新入口；没有更新时这枚图标根本不存在。 */
  updateAvailable?: boolean
  /** 该入口此刻的动作：'download' 先下载，'install' 已下载并校验、可以安装。 */
  updateAction?: 'download' | 'install'
  /** 正在下载（底座透出柔和的呼吸，说明进度在走）。 */
  updateBusy?: boolean
  /** 悬停/读屏说明，含版本号与当前状态；由宿主按更新状态生成。 */
  updateLabel?: string
}>()

const emit = defineEmits<{
  open: [view: AppRailView]
  update: []
  'open-split': [view: AppRailView, edge: 'right' | 'bottom']
  'open-plugin-page': [page: PluginPageEntry]
  'split-plugin-page': [page: PluginPageEntry, edge: 'right' | 'bottom']
}>()
const pluginPages = computed(() => contributionState().pages.filter(page => page.navigation === true))
// user:“一个都不常驻”+(插件导航按钮全部收进“更多”抽屉，竖栏不再逐个占用图标位)。
const moreEntryActive = computed(() =>
  pluginPages.value.some(page => `${page.plugin}:${page.id}` === props.activePluginPage),
)

const moreOpen = ref(false)
const moreWrap = ref<HTMLElement | null>(null)
let moreCloseTimer: ReturnType<typeof setTimeout> | undefined
function cancelMoreClose(): void {
  if (moreCloseTimer !== undefined) {
    clearTimeout(moreCloseTimer)
    moreCloseTimer = undefined
  }
}
// 悬停直接展开；离开时留一小段时间，让指针能跨过竖栏与抽屉之间的缝隙。
function openMoreDrawer(): void {
  cancelMoreClose()
  moreOpen.value = true
}
function scheduleCloseMoreDrawer(): void {
  cancelMoreClose()
  moreCloseTimer = setTimeout(() => {
    moreCloseTimer = undefined
    moreOpen.value = false
  }, 140)
}
function closeMoreDrawer(): void {
  cancelMoreClose()
  moreOpen.value = false
}
function onMoreFocusOut(event: FocusEvent): void {
  const next = event.relatedTarget
  if (next instanceof Node && (event.currentTarget as HTMLElement | null)?.contains(next)) return
  scheduleCloseMoreDrawer()
}
function openFoldedPage(page: PluginPageEntry): void {
  closeMoreDrawer()
  emit('open-plugin-page', page)
}
function openFoldedSplitMenu(event: MouseEvent, page: PluginPageEntry): void {
  closeMoreDrawer()
  openPluginSplitMenu(event, page)
}
// 键盘打开后，点击抽屉外任意位置或按 Esc 都收起，避免浮层一直挂着。
function onMoreDocumentPointerDown(event: PointerEvent): void {
  if (!(event.target instanceof Node) || !moreWrap.value?.contains(event.target)) closeMoreDrawer()
}
function onMoreDocumentKeyDown(event: KeyboardEvent): void {
  if (event.key === 'Escape') closeMoreDrawer()
}
function syncMoreDocumentListeners(open: boolean): void {
  if (typeof document === 'undefined') return
  if (open) {
    document.addEventListener('pointerdown', onMoreDocumentPointerDown, true)
    document.addEventListener('keydown', onMoreDocumentKeyDown)
  } else {
    document.removeEventListener('pointerdown', onMoreDocumentPointerDown, true)
    document.removeEventListener('keydown', onMoreDocumentKeyDown)
  }
}
watch(moreOpen, syncMoreDocumentListeners)
onBeforeUnmount(() => {
  cancelMoreClose()
  syncMoreDocumentListeners(false)
})

function openPluginSplitMenu(event: MouseEvent, page: PluginPageEntry) {
  openContextMenu({ event, ariaLabel: t('在分屏中打开'), items: [
    { label: t('在右侧分屏中打开'), action: () => emit('split-plugin-page', page, 'right') },
    { label: t('在下方分屏中打开'), action: () => emit('split-plugin-page', page, 'bottom') },
  ] })
}

// user:“可以在分屏开一个库、设置等”+(导航保留普通点击，分屏操作通过统一右键菜单进入)。
function openSplitMenu(event: MouseEvent, view: AppRailView) {
  if (view === 'chat') return
  openContextMenu({ event, ariaLabel: t('在分屏中打开'), items: [
    { label: t('在右侧分屏中打开'), action: () => emit('open-split', view, 'right') },
    { label: t('在下方分屏中打开'), action: () => emit('open-split', view, 'bottom') },
  ] })
}

/** 更新图标本身：宿主把它交给更新卡片，卡片从这里长出来、也缩回这里。 */
const updateButton = ref<HTMLElement | null>(null)
defineExpose({ updateButton })

interface RailEntry {
  id: AppRailView
  label: string
  icon: Component
  /**
   * 描边粗细。两家的网格不同：lucide 是 24 网格，IconPark 是 48 网格，
   * 所以同一个视觉粗细要写不同的数（48 网格上约为 24 网格的两倍）。
   */
  strokeWidth?: number
}

const topItems: RailEntry[] = [
  { id: 'chat', get label() { return t("聊天") }, icon: House },
  // 定时任务用 lucide 的 calendar-clock：IconPark 的时间家族里没有「日历+时钟」这一枚。
  { id: 'arrange', get label() { return t("定时任务") }, icon: CalendarClock },
  // 资料库用 IconPark 的 book-one：一叠合着的资料，而不是一本摊开的书。
  { id: 'library', get label() { return t("资料库") }, icon: BookOne, strokeWidth: 3.6 },
  { id: 'plugins', get label() { return t("插件") }, icon: Receive, strokeWidth: 3.6 },
  { id: 'settings', get label() { return t("设置") }, icon: Settings },
]
</script>
