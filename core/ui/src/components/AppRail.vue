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
 * 设置），底部账号。记忆不再单开入口——它在资料库里面。
 *
 * 图标只用最简形状：这里只有 20px，多一个细节就糊一层。并且同一个入口用
 * 同一个图形——「插件」的插头与搜索页一致。点击分区时整个界面切走（会话栏退场），由宿主决定具体
 * 的切换与折叠语义；这里只负责渲染与上报。
 */
import type { Component } from 'vue'
import { CalendarClock, House, Settings, UserRound } from 'lucide-vue-next'
import { BookOne, Receive } from '@icon-park/vue-next'

export type AppRailView = 'chat' | 'arrange' | 'library' | 'plugins' | 'settings' | 'account'

const props = defineProps<{
  /** 当前所处的整界面分区；'chat' 表示在聊天界面。 */
  active?: AppRailView
}>()

const emit = defineEmits<{
  open: [view: AppRailView]
}>()

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
