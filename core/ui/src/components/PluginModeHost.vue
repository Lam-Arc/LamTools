<template>
  <section v-if="loading" class="plugin-mode-host plugin-mode-host--loading" aria-live="polite">
    正在加载 {{ modeTitle || '插件功能' }}…
  </section>
  <section v-else-if="error" class="plugin-mode-host plugin-mode-host--error" role="alert">
    {{ error }}
  </section>
  <component
    :is="component"
    v-else-if="component"
    v-bind="modeProps"
  />
  <section v-else class="plugin-mode-host plugin-mode-host--empty">
    插件功能不可用
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import type { Component } from 'vue'
import { getMode } from '../plugins/registry'

const props = defineProps<{
  modeId: string
  pluginId?: string
  modeProps?: Record<string, unknown>
}>()

const component = ref<Component | null>(null)
const loading = ref(false)
const error = ref('')
const modeTitle = ref('')
let loadRevision = 0

async function loadMode(): Promise<void> {
  const revision = ++loadRevision
  const mode = getMode(props.modeId, props.pluginId)
  component.value = null
  error.value = ''
  modeTitle.value = mode?.title || ''
  if (!mode) return
  loading.value = true
  try {
    const loaded = await mode.load()
    if (revision !== loadRevision) return
    component.value = 'default' in loaded ? loaded.default : loaded
  } catch (cause) {
    if (revision !== loadRevision) return
    error.value = `加载 ${mode.title} 失败：${cause instanceof Error ? cause.message : String(cause)}`
  } finally {
    if (revision === loadRevision) loading.value = false
  }
}

watch(() => [props.modeId, props.pluginId], () => { void loadMode() }, { immediate: true })
onBeforeUnmount(() => { loadRevision += 1 })
</script>

<style scoped>
.plugin-mode-host {
  min-height: 100%;
  display: grid;
  place-items: center;
  color: var(--theme-main-text);
  padding: var(--space-4);
}

.plugin-mode-host--loading,
.plugin-mode-host--empty {
  color: color-mix(in srgb, var(--theme-main-text) 65%, transparent);
}

.plugin-mode-host--error {
  color: var(--red);
}
</style>
