<script setup lang="ts">
import { reactive, ref } from 'vue'
import CoreSplitBrowser, { type SplitBrowserServices } from '@/components/CoreSplitBrowser.vue'
import type { BrowserNativeEvent } from '@/split/native'
import type { SplitTab } from '@/workspace/types'
import '@/styles/split-workspace.css'

// user:“交互测试”+(所有浏览器动作只记录在内存，绝不打开网页或系统浏览器)。
const tab = reactive<SplitTab>({ id: 'gallery-browser', kind: 'browser', resource: '', title: '浏览器' })
const fail = ref(false), navigation = ref(''), external = ref('')
let callback: ((event: BrowserNativeEvent) => void) | undefined
const services: SplitBrowserServices = {
  available: () => true,
  async call(id, action, options) {
    if ((action === 'create' || action === 'navigate') && fail.value) throw new Error('示例导航失败')
    if (action === 'create' || action === 'navigate') { navigation.value = String(options?.url || ''); callback?.({ id, url: navigation.value, loading: false }) }
  },
  async subscribe(next) { callback = next; return () => { callback = undefined } },
  async openExternal(url) { external.value = url },
}
</script>

<template>
  <div class="browser-example">
    <label><input v-model="fail" class="sunday-checkbox" type="checkbox" />模拟导航失败</label>
    <div class="browser-example-view"><CoreSplitBrowser :tab="tab" :visible="true" :services="services" /></div>
    <span v-if="navigation">本地导航：{{ navigation }}</span>
    <span v-if="external">本地外部打开：{{ external }}</span>
  </div>
</template>

<style scoped>
.browser-example { width: 100%; display: grid; gap: var(--space-3); }
.browser-example-view { height: 300px; min-width: 0; overflow: hidden; border: 1px solid var(--theme-main-border); border-radius: var(--radius); }
</style>
