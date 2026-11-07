<template>
  <div class="full-area-column full-area-surface account-view" :style="settingsThemeStyle">
    <main class="account-body">
      <!-- user:“现在不再需要登录/账号了……改为 Sunday / Sunday M 远程连接功能”+
           (这一页只做一件事：让手机连上电脑，或者让电脑接受手机。标题与返回键
           由整版页面顶部条统一提供，页面内不再重复一份)。 -->
      <RemoteConnectionPanel :platform="props.appRuntime?.platform" />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import RemoteConnectionPanel from '@/components/RemoteConnectionPanel.vue'
import { relativeLuminance, themeAreaBackground, type ThemeData } from '@/helpers/theme.ts'

const props = defineProps<{
  theme?: ThemeData | null
  /** 只用来决定面板是「出码」还是「扫码」。 */
  appRuntime?: { platform?: 'desktop' | 'mobile' | 'web' }
}>()

const settingsThemeStyle = computed(() => {
  if (!props.theme) return {}
  const theme = props.theme
  const lightMain = relativeLuminance(theme.mainText) < 0.45
  return {
    '--settings-backdrop-background': themeAreaBackground(theme, 'backdrop'),
    '--settings-backdrop-text': theme.backdropText,
    '--settings-main-background': themeAreaBackground(theme, 'main'),
    '--settings-main-text': theme.mainText,
    '--settings-main-solid': theme.mainStops[0]?.color || '#111111',
    '--settings-card-background': 'color-mix(in srgb, var(--settings-main-solid) 96%, var(--settings-main-text) 4%)',
    '--settings-card-text': theme.mainText,
    '--settings-control-background': themeAreaBackground(theme, 'control'),
    '--settings-control-text': theme.controlText,
    '--settings-control-solid': theme.controlStops[0]?.color || '#3a3834',
    ...(lightMain
      ? {
          '--settings-panel-2': '#f0efeb',
          '--settings-line': '#d4d0cc',
          '--settings-muted': '#8a8580',
        }
      : {}),
  } as Record<string, string>
})
</script>

<style scoped>
.account-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-3);
  --text: var(--settings-card-text, var(--settings-main-text, #fff));
  color: var(--text);
}
</style>
