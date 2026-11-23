<template>
  <div class="full-area-column full-area-surface account-view" :style="settingsThemeStyle">
    <main class="account-body">
      <!-- user:“现在不再需要登录/账号了……改为 Sunday / Sunday M 远程连接功能”+
           (这一页只做一件事：让手机连上电脑，或者让电脑接受手机。标题与返回键
           由整版页面顶部条统一提供，页面内不再重复一份)。 -->
      <RemoteConnectionPanel :platform="props.appRuntime?.platform" :services="props.remoteServices" />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import RemoteConnectionPanel from '@/components/RemoteConnectionPanel.vue'
import { type ThemeData } from '@/helpers/theme.ts'
import { settingsThemeVars } from '@/helpers/settingsTheme.ts'
import type { RemoteConnectionServices } from '@/components/remoteConnectionServices.ts'

const props = defineProps<{
  theme?: ThemeData | null
  /** 只用来决定面板是「出码」还是「扫码」。 */
  appRuntime?: { platform?: 'desktop' | 'mobile' | 'web' }
  /** user:“交互测试”+(展厅可注入隔离连接服务)。 */
  remoteServices?: RemoteConnectionServices
}>()

// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(多个页面使用同一主题映射)。
const settingsThemeStyle = computed(() => settingsThemeVars(props.theme))
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
