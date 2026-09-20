<template>
  <section v-if="loading" class="plugin-mode-host plugin-mode-host--loading" aria-live="polite">
    <HistoryLoadingIndicator :active="loading" />
  </section>
  <section v-else-if="error" class="plugin-mode-host plugin-mode-host--error" role="alert">
    {{ error }}
  </section>
  <ModeContent
    :component="component"
    :context="scopedContext"
    v-else-if="component"
    :mode-props="modeProps"
  />
  <section v-else class="plugin-mode-host plugin-mode-host--empty">
    插件功能不可用
  </section>
</template>

<script setup lang="ts">
import { defineComponent, h, onBeforeUnmount, provide, ref, shallowRef, watch, type PropType } from 'vue'
import type { Component } from 'vue'
import { getMode } from '../plugins/registry'
import { CORE_PLUGIN_MODE_CONTEXT, useCorePluginModeContext, type CorePluginModeContext } from '../plugins/context'
import HistoryLoadingIndicator from './HistoryLoadingIndicator.vue'

const props = defineProps<{
  modeId: string
  pluginId?: string
  modeProps?: Record<string, unknown>
}>()

const component = shallowRef<Component | null>(null)
const loading = ref(false)
const error = ref('')
const modeTitle = ref('')
let loadRevision = 0
const context = useCorePluginModeContext()
const scopedContext = shallowRef(context)
const ModeContent = defineComponent({
  props: {
    component: { type: Object as PropType<Component>, required: true },
    context: { type: Object as PropType<CorePluginModeContext>, required: true },
    modeProps: Object as PropType<Record<string, unknown>>,
  },
  setup(props) {
    provide(CORE_PLUGIN_MODE_CONTEXT, props.context)
    return () => h(props.component, props.modeProps)
  },
})

async function loadMode(): Promise<void> {
  const revision = ++loadRevision
  // Async work from a previous mode must not select a session after switching.
  scopedContext.value = {
    ...context,
    selectSession: async (id) => {
      if (revision !== loadRevision) return
      await context.selectSession(id)
    },
  }
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
