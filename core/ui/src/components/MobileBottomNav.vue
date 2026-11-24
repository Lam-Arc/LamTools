<template>
  <nav class="mobile-bottom-nav" :aria-label="t('主导航')" data-mobile-bottom-nav>
    <button
      v-for="item in items"
      :key="item.id"
      type="button"
      class="mobile-bottom-nav__item"
      :class="{ 'is-active': props.active === item.id }"
      :aria-current="props.active === item.id ? 'page' : undefined"
      :data-mobile-nav="item.id"
      @click="emit('select', item.id)"
    >
      <component :is="item.icon" :size="22" :stroke-width="1.9" aria-hidden="true" />
      <span class="mobile-bottom-nav__label">{{ item.label }}</span>
    </button>
  </nav>
</template>

<script setup lang="ts">
import { computed, type Component } from 'vue'
import { CalendarClock, LayoutGrid, MessageCircle, Settings } from 'lucide-vue-next'
import { t } from '@/i18n/index.ts'

/**
 * user:“一级入口收敛为对话 / 工作区 / 任务 / 设置四项，底部常驻”+
 * (Android 一级导航：四个入口固定在底部，不随页面变化移动；插件与远程连接收进设置。
 *  触控目标 48dp 起，标签与图标同时出现，当前项有 aria-current 与高亮)。
 */
export type MobileNavKey = 'chat' | 'workspace' | 'task' | 'settings'

const props = defineProps<{ active: MobileNavKey }>()
const emit = defineEmits<{ select: [key: MobileNavKey] }>()

interface NavItem {
  id: MobileNavKey
  label: string
  icon: Component
}

const items = computed<NavItem[]>(() => [
  { id: 'chat', label: t('对话'), icon: MessageCircle },
  { id: 'workspace', label: t('工作区'), icon: LayoutGrid },
  { id: 'task', label: t('任务'), icon: CalendarClock },
  { id: 'settings', label: t('设置'), icon: Settings },
])
</script>

<style scoped>
.mobile-bottom-nav {
  position: fixed;
  inset: auto 0 0 0;
  z-index: var(--z-popover);
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  align-items: stretch;
  height: var(--mobile-bottom-nav-height, 56px);
  /* 底部安全区（手势条/刘海屏）由变量吃进来，导航条本身贴着窗口下沿。 */
  padding-bottom: var(--safe-area-bottom);
  box-sizing: content-box;
  border-top: 1px solid color-mix(in srgb, var(--theme-main-text) 8%, transparent);
  background: var(--theme-main-background);
  color: color-mix(in srgb, var(--theme-main-text) 62%, transparent);
  user-select: none;
}

.mobile-bottom-nav__item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  min-width: 48px;
  min-height: 48px;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  transition: color var(--dur-fast) var(--ease-out);
}

.mobile-bottom-nav__item.is-active {
  color: var(--theme-main-text);
}

.mobile-bottom-nav__label {
  font-size: 11px;
  line-height: 1.2;
}

@media (prefers-reduced-motion: reduce) {
  .mobile-bottom-nav__item { transition: none; }
}
</style>
