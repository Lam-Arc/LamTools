<template>
  <nav class="app-rail" data-app-rail aria-label="主导航">
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
    >
      <component :is="item.icon" :size="20" :stroke-width="item.strokeWidth ?? 1.8" aria-hidden="true" />
    </button>
    <span class="app-rail__spacer" aria-hidden="true"></span>
    <!-- 更新入口：只在真有新版本时出现，就在账号上方。它是这里唯一「有事可做」的
         一枚，所以给一层柔和的圆角底座，和上面纯图标的导航区分开。 -->
    <button
      v-if="updateAvailable"
      ref="updateButton"
      class="app-rail__button app-rail__update"
      type="button"
      :aria-label="updateLabel || '有新版本可用'"
      :title="updateLabel || '有新版本可用'"
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
      aria-label="账号"
      title="账号"
      :aria-pressed="props.active === 'account'"
      data-rail-entry="account"
      @click="emit('open', 'account')"
    >
      <UserRound :size="20" :stroke-width="1.8" aria-hidden="true" />
    </button>
  </nav>
</template>

<script setup lang="ts">
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
import { ref, type Component } from 'vue'
import { CalendarClock, Download, House, PackageCheck, Settings, UserRound } from 'lucide-vue-next'
import { BookOne, Receive } from '@icon-park/vue-next'

export type AppRailView = 'chat' | 'arrange' | 'library' | 'plugins' | 'settings' | 'account'

const props = defineProps<{
  /** 当前所处的整界面分区；'chat' 表示在聊天界面。 */
  active?: AppRailView
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
}>()

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
  { id: 'chat', label: '聊天', icon: House },
  // 定时任务用 lucide 的 calendar-clock：IconPark 的时间家族里没有「日历+时钟」这一枚。
  { id: 'arrange', label: '定时任务', icon: CalendarClock },
  // 资料库用 IconPark 的 book-one：一叠合着的资料，而不是一本摊开的书。
  { id: 'library', label: '资料库', icon: BookOne, strokeWidth: 3.6 },
  { id: 'plugins', label: '插件', icon: Receive, strokeWidth: 3.6 },
  { id: 'settings', label: '设置', icon: Settings },
]
</script>
