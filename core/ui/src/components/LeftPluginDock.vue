<template>
  <!-- user:“左侧栏可以添加图标注册一个项”+插件贡献注册成底部图标项，点击
       在 dock 上方展开面板渲染块与动作；图标行超宽横向滚动，面板限高纵向
       滚动，数量再多也不撑破抽屉。 -->
  <div v-if="items.length" class="left-plugin-dock" data-left-plugin-dock>
    <div v-if="expandedRegions.length" class="left-plugin-dock-panel" :data-plugin-dock-panel="expanded">
      <PluginRegionBlocks :regions="expandedRegions" :request-rpc="requestRpc" />
    </div>
    <div class="left-plugin-dock-row" role="toolbar" :aria-label="t('插件')">
      <button
        v-for="item in items"
        :key="item.key"
        type="button"
        class="left-plugin-dock-btn"
        :class="{ active: expanded === item.key }"
        :title="item.plugin"
        :data-plugin-dock-item="item.plugin"
        :aria-expanded="expanded === item.key"
        @click="toggle(item.key)"
      >
        {{ initial(item.plugin) }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { t } from '@/i18n/index'
import PluginRegionBlocks from '@/components/PluginRegionBlocks.vue'
import {
  contributionsFor,
  ensureContributions,
  type PluginRegionContribution,
  type PluginRpc,
} from '@/plugins/contributions'

interface DockItem {
  key: string
  plugin: string
  contribution: PluginRegionContribution
}

const props = defineProps<{ requestRpc: PluginRpc }>()

const ready = ref(false)
const expanded = ref('')

onMounted(async () => {
  await ensureContributions(props.requestRpc)
  ready.value = true
})

const items = computed<DockItem[]>(() => {
  if (!ready.value) return []
  return contributionsFor('left')
    .filter((item) => !item.replace)
    .map((contribution, index) => ({
      key: `${contribution.plugin}:${index}`,
      plugin: contribution.plugin,
      contribution,
    }))
})

const expandedRegions = computed<PluginRegionContribution[]>(() => {
  const item = items.value.find((candidate) => candidate.key === expanded.value)
  return item ? [item.contribution] : []
})

function toggle(key: string): void {
  expanded.value = expanded.value === key ? '' : key
}

function initial(plugin: string): string {
  return plugin.slice(0, 1).toUpperCase()
}
</script>

<style scoped>
.left-plugin-dock {
  display: grid;
  gap: 6px;
  padding: 6px var(--sidebar-inline-padding) 8px;
  border-top: 1px solid color-mix(in srgb, var(--theme-main-text) 10%, transparent);
}

.left-plugin-dock-panel {
  max-height: 40vh;
  overflow-y: auto;
  min-height: 0;
}

.left-plugin-dock-row {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.left-plugin-dock-row::-webkit-scrollbar {
  display: none;
}

.left-plugin-dock-btn {
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 62%, transparent);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.left-plugin-dock-btn:hover {
  background: color-mix(in srgb, var(--theme-main-text) 8%, transparent);
  color: var(--theme-main-text);
}

.left-plugin-dock-btn.active {
  background: color-mix(in srgb, var(--blue) 18%, transparent);
  color: var(--theme-main-text);
}
</style>
