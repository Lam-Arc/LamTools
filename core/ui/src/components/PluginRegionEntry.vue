<script setup lang="ts">
// user:“该调的模块就是该写的东西”+(区域、分屏和窗口共用同一种可清理的插件页面协议)。
import { inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CORE_PLUGIN_MODE_CONTEXT } from '@/plugins/context'
import { createPluginPageInstance, loadPluginPageModule } from '@/plugins/pages'
import type { PluginRpc } from '@/plugins/types'
const props = defineProps<{ plugin: string; entryUrl: string; requestRpc: PluginRpc }>()
const host = ref<HTMLElement | null>(null), error = ref('')
const context = inject(CORE_PLUGIN_MODE_CONTEXT, null)
let instance: ReturnType<typeof createPluginPageInstance> | undefined
let generation = 0, alive = true
function dispose() { const old = instance; instance = undefined; if (old) void old.dispose().catch(() => {}) }
function start() {
  if (!host.value || !alive) return
  const current = ++generation
  dispose(); error.value = ''
  instance = createPluginPageInstance(host.value, { plugin: props.plugin, id: 'region', title: props.plugin, entry_url: props.entryUrl }, {
    instanceId: `${props.plugin}:region`, workRoot: context?.currentWorkRoot() || '',
    projectId: context?.selectedProjectId.value, sessionId: context?.activeSessionId.value,
  }, props.requestRpc, { loadModule: loadPluginPageModule })
  void instance.ready.catch(cause => { if (alive && current === generation) error.value = String(cause) })
}
watch(() => [props.plugin, props.entryUrl], start, { flush: 'post' })
onMounted(start)
onBeforeUnmount(() => { alive = false; generation++; dispose() })
</script>
<template>
  <p v-if="error" role="alert">{{ error }}</p>
  <div ref="host" class="plugin-region-entry" :data-plugin-entry="plugin" :data-entry-url="entryUrl" />
</template>
