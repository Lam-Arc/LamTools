<template>
  <PluginRegionBlocks
    v-if="regions.length"
    :regions="regions"
    :request-rpc="requestRpc"
  />
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import PluginRegionBlocks from './PluginRegionBlocks.vue'

interface PluginStyleEntry {
  plugin: string
  url: string
}

interface PluginBlock {
  type: string
  label: string
  value: unknown
  text: string
  state: string
  items: unknown[]
  detail: string
  max?: number
}

interface PluginAction {
  id: string
  title: string
  operation: string
  dangerous?: boolean
  mutates?: boolean
}

interface PluginRegionContribution {
  plugin: string
  region: string
  order: number
  mode: string
  replace: boolean
  blocks: PluginBlock[]
  actions: PluginAction[]
}

type PluginRpc = (
  method: string,
  params?: Record<string, unknown>,
) => Promise<Record<string, unknown>>

const props = defineProps<{
  requestRpc: PluginRpc
  region: string
}>()

// Styles are page-scoped: inject once per URL, never remove on unmount so two
// hosts on the same page cannot unstyle each other.
const injectedStyles = new Set<string>()
const injectedScripts = new Set<string>()

const regions = ref<PluginRegionContribution[]>([])

function injectStyle(url: string): void {
  if (!url || injectedStyles.has(url)) return
  const link = document.createElement('link')
  link.rel = 'stylesheet'
  link.href = url
  link.dataset.pluginSystemStyle = 'true'
  document.head.appendChild(link)
  injectedStyles.add(url)
}

// user:“全局脚本”+声明了 ui.script 的插件在同一个页面里执行自己的脚本，
// 每个地址只注入一次，重复挂载不会跑第二遍。
function injectScript(url: string): void {
  if (!url || injectedScripts.has(url)) return
  if (document.querySelector(`script[data-plugin-system-script="${url}"]`)) {
    injectedScripts.add(url)
    return
  }
  const script = document.createElement('script')
  script.type = 'module'
  script.src = url
  script.dataset.pluginSystemScript = url
  document.head.appendChild(script)
  injectedScripts.add(url)
}

async function fetchUi(): Promise<void> {
  try {
    const payload = await props.requestRpc('plugin.system.ui', {})
    const styles = Array.isArray(payload.styles) ? (payload.styles as PluginStyleEntry[]) : []
    for (const style of styles) injectStyle(String(style.url || ''))
    const scripts = Array.isArray(payload.scripts)
      ? (payload.scripts as PluginStyleEntry[])
      : []
    for (const script of scripts) injectScript(String(script.url || ''))
    const all = Array.isArray(payload.regions)
      ? (payload.regions as PluginRegionContribution[])
      : []
    regions.value = all.filter((item) => item.region === props.region)
  } catch (cause) {
    console.warn('[plugin-contributions] failed to load ui declarations:', cause)
  }
}

onMounted(fetchUi)
</script>
