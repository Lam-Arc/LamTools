<script setup lang="ts">
// user:“支持一下”+(标签只保存页面身份；从当前启用目录挂载，每个实例独立清理)。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { SplitTab } from '@/split/layout'
import type { PluginRpc } from '@/plugins/types'
import { contributionState, ensureContributions } from '@/plugins/contributions'
import { createPluginPageInstance, loadPluginPageModule, parsePluginPageKey } from '@/plugins/pages'
import { t } from '@/i18n'
const props = defineProps<{ tab: SplitTab; visible: boolean; workRoot: string; requestRpc: PluginRpc }>()
const emit = defineEmits<{ 'open-page': [target: { plugin: string; id: string }]; 'open-file': [path: string, scope: {workRoot: string; projectId?: string; sessionId?: string}] }>()
const host = ref<HTMLElement | null>(null), error = ref(''), loading = ref(false)
const page = computed(() => {
  const key = parsePluginPageKey(props.tab.resource)
  return key ? contributionState().pages.find(page => page.plugin === key[0] && page.id === key[1]) : undefined
})
const signature = computed(() => JSON.stringify([props.tab.id, page.value?.entry_url, page.value?.version]))
let instance: ReturnType<typeof createPluginPageInstance> | undefined, lastSignature = '', generation = 0, alive = true
function dispose() {
  const previous = instance; instance = undefined
  if (previous) void previous.dispose().catch(cause => { if (alive) error.value = String(cause) })
}
function start(force = false) {
  if (!alive || !host.value || (!force && instance && lastSignature === signature.value)) return
  const current = ++generation
  dispose(); lastSignature = signature.value; error.value = ''; loading.value = false
  const entry = page.value
  if (!entry) { error.value = t('插件页面暂不可用：可能已禁用、移除或连接尚未就绪'); return }
  loading.value = true
  const bound = { instanceId: props.tab.id, workRoot: props.tab.root || props.workRoot,
    projectId: props.tab.projectId, sessionId: props.tab.sessionId, filePath: parsePluginPageKey(props.tab.resource)?.[2] }
  instance = createPluginPageInstance(host.value, entry, bound, props.requestRpc, { visible: props.visible, loadModule: loadPluginPageModule,
    openPage: id => emit('open-page', { plugin: entry.plugin, id }),
    openFile: path => emit('open-file', path, {workRoot:bound.workRoot,projectId:bound.projectId,sessionId:bound.sessionId}),
  })
  void instance.ready.catch(cause => { if (alive && current === generation) error.value = String(cause) })
    .finally(() => { if (alive && current === generation) loading.value = false })
}
async function refresh(force = true) {
  await ensureContributions(props.requestRpc)
  start(force)
}
watch(signature, () => start(), { flush: 'post' })
watch(() => props.visible, value => instance?.setVisible(value))
onMounted(() => { void refresh(false) })
onBeforeUnmount(() => { alive = false; generation++; dispose() })
</script>
<template>
  <div class="split-plugin-page">
    <div class="split-content-toolbar"><span>{{ page?.title || tab.title }}</span><button class="split-text-button" type="button" :disabled="loading" @click="refresh()">{{ t('刷新') }}</button></div>
    <p v-if="loading" class="split-content-notice">{{ t('正在打开插件页面…') }}</p>
    <p v-if="error" class="split-content-error" role="alert">{{ error }}</p>
    <div ref="host" class="split-plugin-page__host" />
  </div>
</template>
<style scoped>
.split-plugin-page { display: flex; flex-direction: column; min-height: 0; height: 100%; color: var(--theme-main-text); background: var(--theme-main-background); }
.split-plugin-page__host { flex: 1; min-height: 0; overflow: auto; padding: var(--space-3); }
</style>
